"""History/live cutover readiness gates the ordinary RegisteredSim order path.

This is a local source-composition test.  Cerebro, BtApiFeed, LiveBarCohort,
Alpha003, LiveFactorSet, BtApiBroker, RegisteredSimStore, the execution
coordinator, and the journal are real; only the provider SDK leaves are fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.alpha101 import get_alpha
from backtrader.research.live import LiveFactorOutputStatus, LiveFactorReadiness
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionDecisionJournal,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.factor_execution_facts import FactorExecutionTarget
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.unit.stores import test_factor_execution as execution_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


UTC = timezone.utc
INSTRUMENT = facts_fixtures._INSTRUMENT
EXCHANGE = facts_fixtures._EXCHANGE
TRADING_DAY = facts_fixtures._TRADING_DAY
ACCOUNT_SCOPE = "acct-scope"
STRATEGY_SCOPE = "alpha003"
LOGICAL_RUN_ID = "alpha003-history-catchup"
TARGETS = (INSTRUMENT, "cu2510", "au2512")
HISTORY_LENGTHS = (30, 33, 36)
BAR_COUNT = 37
START = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)


class _ReplayClock:
    """A deterministic scheduler clock with the ordinary cohort clock API."""

    def __init__(self, now: datetime):
        self._now = now
        self._monotonic_ns = 1_000_000_000

    def utc_now(self):
        return self._now

    def monotonic_ns(self):
        return self._monotonic_ns

    def wait(self, timeout_seconds):
        elapsed = max(0.0, float(timeout_seconds))
        self._now += timedelta(seconds=elapsed)
        self._monotonic_ns += max(1, int(elapsed * 1_000_000_000))


def _calendar_and_bars():
    member_sessions = {
        "member-"
        + target: LiveCalendarMemberSession(trading_day="2026-10-24", session_segment="regular")
        for target in TARGETS
    }
    slots = tuple(
        LiveCalendarSlot(
            slot_id="minute-{}".format(index),
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="2026-10-24",
            session_segment="regular",
            member_sessions=member_sessions,
        )
        for index in range(BAR_COUNT)
    )
    calendar = LiveCohortCalendar(
        calendar_id="alpha003-history-live-v1",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-alpha003-history-live",
        session_semantics="ctp-regular-v1",
        slots=slots,
    )
    by_target = {}
    for asset_index, target in enumerate(TARGETS):
        rows = []
        for bar_index, slot in enumerate(slots):
            # Each cross section is a permutation.  The two rank series have
            # different per-asset phase, yielding finite, nonidentical
            # ten-bar correlations once the actual graph is warm.
            open_value = float(10 + ((asset_index + bar_index) % len(TARGETS)))
            volume_value = float(100 + ((2 * asset_index + bar_index) % len(TARGETS)))
            close = 50.0 + asset_index + (bar_index % 7) / 10.0
            rows.append(
                MappingProxyType(
                    {
                        "instrument": target,
                        "symbol": target,
                        "timestamp": slot.close_time.timestamp(),
                        "datetime": slot.close_time,
                        "bucket_start": slot.bucket_start,
                        "bucket_end": slot.close_time,
                        "available_at": slot.close_time,
                        "trading_day": "2026-10-24",
                        "session_segment": "regular",
                        "timezone_id": "UTC",
                        "clock_domain_id": "clock-alpha003-history-live",
                        "connection_generation": "fixture-generation-1",
                        "bar_sequence": bar_index + 1,
                        "bar_id": "{}-minute-{}".format(target, bar_index),
                        "open": open_value,
                        "high": max(open_value, close) + 1.0,
                        "low": min(open_value, close) - 1.0,
                        "close": close,
                        "volume": volume_value,
                        "openinterest": 0.0,
                        "present": True,
                        "complete": True,
                        "quality": "GOOD",
                        "quality_flags": (),
                        "source": "alpha003-history-live-fixture",
                    }
                )
            )
        by_target[target] = tuple(rows)
    return calendar, by_target


class _HistoryCatchupStrategy(bt.Strategy):
    params = (
        ("cohort", None),
        ("plan", None),
        ("coordinator", None),
        ("execution_facts", None),
        ("api", None),
    )

    def __init__(self):
        self._data_by_target = {data._name: data for data in self.datas}
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            self._data_by_target,
            cohort=self.p.cohort,
        )
        self.observations = []
        self.order = None
        self.order_batch = None

    def prenext(self):
        # Keep actual warmup batches observable through the standard Strategy
        # callback; this does not advance any indicator or cohort itself.
        self.next()

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        snapshot = self.live_factors.snapshot()
        roles = {
            target: batch.receipt_for_feed(data).envelope.source_role
            for target, data in self._data_by_target.items()
        }
        window_counts = {
            target: len(self.p.cohort.complete_window_bars(data, ("open", "volume"), 10))
            for target, data in self._data_by_target.items()
        }
        capacity_before = self.p.coordinator.decision_capacity_snapshot().base_record_count
        order_count_before = self.p.coordinator.run_order_count()
        native_calls_before = len(self.p.api.native_calls)
        self.observations.append(
            {
                "batch": batch,
                "snapshot": snapshot,
                "roles": roles,
                "window_counts": window_counts,
                "capacity_before": capacity_before,
                "order_count_before": order_count_before,
                "native_calls_before": native_calls_before,
                "feed_lengths": {
                    target: len(data) for target, data in self._data_by_target.items()
                },
            }
        )

        if snapshot.readiness is not LiveFactorReadiness.LIVE_READY or self.order is not None:
            return

        assert snapshot.batch_complete is True
        assert all(role == "live" for role in roles.values())
        assert all(count == 10 for count in window_counts.values())
        factor = snapshot.factors["alpha003"]
        outputs = tuple(factor.values[target] for target in TARGETS)
        assert all(output.status is LiveFactorOutputStatus.OUTPUT_AVAILABLE for output in outputs)
        values = tuple(output.value for output in outputs)
        assert all(math.isfinite(value) for value in values)
        assert len(set(values)) > 1

        intent_key = ExecutionIntentKey(
            action="SUBMIT",
            instrument=INSTRUMENT,
            side="BUY",
            position_effect="OPEN",
            leg=0,
        )
        economics = {
            "instrument": INSTRUMENT,
            "instrument_id": INSTRUMENT,
            "exchange": EXCHANGE,
            "side": "BUY",
            "position_effect": "OPEN",
            "quantity": "1",
            "limit_price": "100",
            "offset": "open",
            "factor_stop_price": "95",
            "stop_price": "95",
            "risk_policy_id": "alpha003-history-live-risk-v1",
            "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
            "entry_grid_ordinal": batch.slot_index + 1,
            "batch_id": batch.batch_id,
            "price": "100",
        }
        key = ExecutionDecisionKey(
            account_scope=ACCOUNT_SCOPE,
            strategy_scope=STRATEGY_SCOPE,
            logical_run_id=LOGICAL_RUN_ID,
            cohort_id=batch.cohort_id,
            close_time=batch.close_time.isoformat().replace("+00:00", "Z"),
            decision_kind="ALPHA003_HISTORY_LIVE_OPEN",
        )
        with self.p.coordinator.decision_scope(
            owner=self,
            key=key,
            economic_payload={"intent_economics": (economics,)},
            intent_keys=(intent_key,),
            batch=batch,
            snapshot=snapshot,
            execution_facts=self.p.execution_facts,
            inputs_complete=True,
            expected_run_order_intents_used=self.p.coordinator.run_order_count(),
            remaining_exit_intent_reserve=0,
        ):
            self.order = self.buy(
                data=self._data_by_target[INSTRUMENT],
                size=1,
                price=100.0,
                exectype=bt.Order.Limit,
                instrument_id=INSTRUMENT,
                exchange_id=EXCHANGE,
                factor_position_effect="OPEN",
                factor_strategy_scope=STRATEGY_SCOPE,
                offset="open",
            )
        self.order_batch = batch


@pytest.mark.integration
@pytest.mark.parametrize("factor_mode", ("native", "build"))
def test_history_overlap_and_staggered_live_cutovers_block_orders_until_qualified_grid(
    factor_mode,
):
    calendar, bars = _calendar_and_bars()
    clock = _ReplayClock(calendar.slots[-1].close_time + timedelta(seconds=2))
    cohort = LiveBarCohort(
        "cohort-alpha003-history-live",
        calendar,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=2_000_000_000,
    )
    feeds = {}
    for target, history_length in zip(TARGETS, HISTORY_LENGTHS):
        rows = bars[target]
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            historical_bars=rows[:history_length],
            # The first live source row exactly overlaps the final history
            # row. The cohort must retain the history receipt once, then
            # transition on the following new live slot.
            live_bars=rows[history_length - 1 :],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            clock=clock,
        )
        feeds[target] = feed
        cohort.register_member(
            "member-" + target,
            feed,
            instrument=target,
            source_ref="fixture-feed-" + target,
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )
    cohort.seal()

    plan = LiveFactorPlan(
        targets=TARGETS,
        groups=dict.fromkeys(TARGETS, "portfolio"),
        factors={
            "alpha003": FactorSpec(
                name="alpha003",
                indicator=get_alpha(3),
                panel_line="factor",
                mode=factor_mode,
                field_bindings={
                    "open": "feed:target:open",
                    "volume": "feed:target:volume",
                },
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=10,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=2_000_000_000,
        max_live_bar_age_seconds=120.0,
        max_future_skew_seconds=0.0,
        allow_history_prewarm=True,
    )

    decision_close = calendar.slots[HISTORY_LENGTHS[-1]].close_time
    query_rows = facts_fixtures._query_rows()
    query_time = decision_close - timedelta(seconds=2)
    tick = facts_fixtures._quote(event_time=decision_close - timedelta(seconds=1))
    store = RegisteredSimStore(
        allow_writes=True,
        preserve_raw_bars=True,
        api_cls=execution_fixtures._FakeProviderClient,
        live_tick_provenance={"source": "fake-ctp-event"},
    )
    api = store._api_cls(query_rows=query_rows, query_time=query_time, tick=tick)
    store._api = api
    store._connected = True
    store.live_tick_provenance = {"source": "fake-ctp-event"}
    broker = bt.brokers.BtApiBroker(
        store=store,
        cash=1_000_000,
        validation_enabled=False,
        cash_check_enabled=False,
        contract_metadata={INSTRUMENT: {"instrument_id": INSTRUMENT, "exchange_id": EXCHANGE}},
    )
    targets_for_execution = FactorExecutionTarget("rb", INSTRUMENT, EXCHANGE, feeds[INSTRUMENT])
    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id=LOGICAL_RUN_ID,
        max_order_intents_per_grid=4,
        max_order_intents_per_run=20,
    )

    query_receipt = facts_fixtures._refresh_all(store, targets_for_execution)
    facts_fixtures._arm(store)
    assert facts_fixtures._consume_quote(store) is not None
    facts_now = decision_close - timedelta(milliseconds=500)
    execution_facts = facts_fixtures._project(
        store,
        broker,
        targets_for_execution,
        facts_now,
        query_set=query_receipt.query_set,
    )
    assert execution_facts.open_risk_ready is True, execution_facts.blockers

    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.setbroker(broker)
    for target in TARGETS:
        cerebro.adddata(feeds[target], name=target)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _HistoryCatchupStrategy,
        cohort=cohort,
        plan=plan,
        coordinator=coordinator,
        execution_facts=execution_facts,
        api=api,
    )

    result = cerebro.run(runonce=False, preload=False)

    assert len(result) == 1
    strategy = result[0]
    assert len(strategy.observations) == BAR_COUNT
    assert [row["batch"].slot_index for row in strategy.observations] == list(range(BAR_COUNT))
    assert all(
        row["feed_lengths"] == dict.fromkeys(TARGETS, row["batch"].slot_index + 1)
        for row in strategy.observations
    )

    # Every overlap is retained exactly once as history; the first subsequent
    # slot carries the source's live role. This checks the actual Feed and
    # cohort receipts rather than a separately implemented source merger.
    for target, history_length in zip(TARGETS, HISTORY_LENGTHS):
        overlap = strategy.observations[history_length - 1]
        first_new_live = strategy.observations[history_length]
        assert overlap["roles"][target] == "history"
        assert (
            overlap["batch"].receipt_for_feed(feeds[target]).envelope.event_ref
            is bars[target][history_length - 1]
        )
        assert first_new_live["roles"][target] == "live"
        assert len(feeds[target]) == BAR_COUNT

    warmup_rows = [
        row
        for row in strategy.observations
        if row["snapshot"].readiness is LiveFactorReadiness.WARMUP
    ]
    catching_rows = [
        row
        for row in strategy.observations
        if row["snapshot"].readiness is LiveFactorReadiness.CATCHING_UP
    ]
    assert warmup_rows
    assert any(
        row["snapshot"].readiness_reasons.count("input_window_incomplete_or_warmup_short")
        for row in warmup_rows
    )
    assert all(set(row["roles"].values()) == {"history"} for row in warmup_rows)
    assert catching_rows
    assert all(row["window_counts"] == dict.fromkeys(TARGETS, 10) for row in catching_rows)
    assert all(any(role == "live" for role in row["roles"].values()) for row in catching_rows)
    assert all(any(role == "history" for role in row["roles"].values()) for row in catching_rows)
    assert all(
        "live_cutover_incomplete" in row["snapshot"].readiness_reasons for row in catching_rows
    )

    assert strategy.order is not None and strategy.order.alive()
    assert strategy.order_batch is not None
    assert strategy.order_batch.slot_index == HISTORY_LENGTHS[-1]
    final = strategy.observations[-1]
    assert final["snapshot"].readiness is LiveFactorReadiness.LIVE_READY
    assert final["batch"] is strategy.order_batch
    assert all(role == "live" for role in final["roles"].values())
    assert all(
        cutover.transition_kind == "history_to_live" for cutover in final["batch"].cutovers.values()
    )
    assert all(count == 10 for count in final["window_counts"].values())

    # There is no durable decision or native write during history, graph
    # warmup, or partial cutover. The first and only decision is attached to
    # the new common LIVE_READY batch.
    for row in strategy.observations[:-1]:
        assert row["capacity_before"] == 0
        assert row["order_count_before"] == 0
        assert row["native_calls_before"] == 0
    assert final["capacity_before"] == 0
    assert final["order_count_before"] == 0
    assert final["native_calls_before"] == 0
    assert journal.decision_capacity_snapshot().base_record_count == 1
    assert coordinator.run_order_count() == 1
    assert [call[0] for call in api.native_calls] == ["insert"]
    assert api.native_calls[0][1:3] == (INSTRUMENT, EXCHANGE)

    intent = journal.intent(strategy.order.info["factor_intent_id"])
    assert intent is not None
    assert intent.key == ExecutionIntentKey(
        action="SUBMIT",
        instrument=INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    assert intent.state == "KNOWN"
    assert intent.dispatch_state == "KNOWN"
    assert intent.original_identity["order_ref"] == "501"
    assert Decimal(str(strategy.order.size)) == Decimal("1")
