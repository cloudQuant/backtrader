"""A missing planned slot freezes one epoch without starving Broker updates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import threading
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import FactorHistoryContract, FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveSourceOrigin,
)
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionDecisionJournal,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.factor_execution_facts import FactorExecutionTarget
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.unit.feeds.test_btapifeed_cohort_runnext import CohortClose
from tests.unit.stores import test_factor_execution as execution_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


UTC = timezone.utc
INSTRUMENT = facts_fixtures._INSTRUMENT
EXCHANGE = facts_fixtures._EXCHANGE
TARGETS = (INSTRUMENT, "cu2510")
ACCOUNT_SCOPE = "acct-scope"
STRATEGY_SCOPE = "alpha003"
LOGICAL_RUN_ID = "alpha003-gap-rebuild-r1"
START = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
BAR_COUNT = 12
FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class _FiniteClose(CohortClose):
    history_contract = FactorHistoryContract.finite_window(span_bars=1)


class _ReplayClock:
    def __init__(self, now: datetime, *, wait_timeout_seconds: float, on_first_wait=None):
        self._now = now
        self._monotonic_ns = 1_000_000_000
        self.wait_timeout_seconds = wait_timeout_seconds
        self.on_first_wait = on_first_wait
        self.wait_calls = 0

    def utc_now(self):
        return self._now

    def monotonic_ns(self):
        return self._monotonic_ns

    def wait(self, timeout_seconds):
        self.wait_calls += 1
        if self.wait_calls == 1 and self.on_first_wait is not None:
            self.on_first_wait()
            elapsed = min(float(timeout_seconds) / 2.0, self.wait_timeout_seconds / 4.0)
        else:
            elapsed = float(timeout_seconds)
        elapsed = max(elapsed, 0.000001)
        self._now += timedelta(seconds=elapsed)
        self._monotonic_ns += max(1, int(elapsed * 1_000_000_000))


class _GapExecutionStrategy(bt.Strategy):
    params = (
        ("cohort", None),
        ("plan", None),
        ("coordinator", None),
        ("execution_facts", None),
        ("api", None),
        ("provider_state", None),
        ("strategy_holder", None),
    )

    def __init__(self):
        if self.p.strategy_holder is not None:
            self.p.strategy_holder["strategy"] = self
        self._data_by_target = {data._name: data for data in self.datas}
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            self._data_by_target,
            cohort=self.p.cohort,
        )
        self.observations = []
        self.orders_by_slot = []
        self.order = None
        self.order_batch = None
        self.terminal_notifications = []

    def prenext(self):
        self.next()

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        snapshot = self.live_factors.snapshot()
        self.observations.append(
            {
                "batch": batch,
                "snapshot": snapshot,
                "feed_lengths": {name: len(data) for name, data in self._data_by_target.items()},
                "ready": snapshot.readiness,
            }
        )
        if snapshot.readiness is not LiveFactorReadiness.LIVE_READY or self.order is not None:
            return

        outputs = tuple(snapshot.factors["close"].values[name] for name in TARGETS)
        assert all(math.isfinite(float(output.value)) for output in outputs)
        self._submit_one_open(batch, snapshot)

    def _submit_one_open(self, batch, snapshot):
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
            "risk_policy_id": "alpha003-gap-rebuild-risk-v1",
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
            decision_kind="ALPHA003_GAP_REBUILD_OPEN",
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
        self.orders_by_slot.append(batch.slot_index)
        self.p.provider_state["working"] = True

    def notify_order(self, order):
        if order.getstatusname() == "Canceled":
            self.terminal_notifications.append(
                {
                    "order_ref": order.ref,
                    "intent_id": order.info.get("factor_intent_id"),
                    "cohort_frozen": self.p.cohort.frozen,
                    "wait_started": self.p.cohort._wait_started_ns,
                    "next_slot_index": self.p.cohort._next_slot_index,
                    "batch_slot_index": self.p.cohort.current_batch().slot_index,
                    "engine_thread": threading.get_ident(),
                }
            )


def _calendar(epoch_id: int, version: str) -> LiveCohortCalendar:
    sessions = {
        "member-"
        + target: LiveCalendarMemberSession(trading_day="20261024", session_segment="regular")
        for target in TARGETS
    }
    slots = tuple(
        LiveCalendarSlot(
            slot_id="planned-minute-{}".format(index),
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="20261024",
            session_segment="regular",
            member_sessions=sessions,
        )
        for index in range(BAR_COUNT)
    )
    return LiveCohortCalendar(
        calendar_id="alpha003-gap-plan",
        version=version,
        epoch_id=epoch_id,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-alpha003-gap-rebuild",
        session_semantics="ctp-regular-v1",
        slots=slots,
    )


def _bars(calendar: LiveCohortCalendar, *, generation: str):
    rows_by_target = {}
    for target_index, target in enumerate(TARGETS):
        rows = []
        for index, slot in enumerate(calendar.slots):
            open_value = float(10 + ((target_index + index) % len(TARGETS)))
            volume_value = float(100 + ((2 * target_index + index) % len(TARGETS)))
            close = 50.0 + target_index + (index % 5) / 10.0
            event = {
                "instrument": target,
                "symbol": target,
                "timestamp": slot.close_time.timestamp(),
                "datetime": slot.close_time,
                "bucket_start": slot.bucket_start,
                "bucket_end": slot.close_time,
                "available_at": slot.close_time,
                "trading_day": slot.trading_day,
                "session_segment": slot.session_segment,
                "timezone_id": "UTC",
                "clock_domain_id": calendar.clock_domain_id,
                "connection_generation": generation,
                "bar_sequence": index + 1,
                "bar_id": "{}-planned-minute-{}-{}".format(target, index, generation),
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
                "source": "alpha003-09a-synthetic",
            }
            rows.append(MappingProxyType(event))
        rows_by_target[target] = tuple(rows)
    return rows_by_target


def _plan(calendar: LiveCohortCalendar) -> LiveFactorPlan:
    return LiveFactorPlan(
        targets=TARGETS,
        groups=dict.fromkeys(TARGETS, "portfolio"),
        factors={
            "close": FactorSpec(
                name="close",
                indicator=_FiniteClose,
                panel_line="factor",
                mode="native",
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=2,
        wait_timeout_ns=20_000_000,
        max_live_bar_age_seconds=3600.0,
        max_future_skew_seconds=0.0,
        allow_history_prewarm=True,
    )


def _execution_stack(feeds, *, facts_time: datetime):
    query_rows = facts_fixtures._query_rows()
    query_time = facts_time - timedelta(seconds=1)
    tick = facts_fixtures._quote(event_time=facts_time - timedelta(milliseconds=500))
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
        account_refresh_interval=0.0,
        positions_refresh_interval=0.0,
        open_orders_refresh_interval=0.0,
        contract_metadata={INSTRUMENT: {"instrument_id": INSTRUMENT, "exchange_id": EXCHANGE}},
    )
    target = FactorExecutionTarget("rb", INSTRUMENT, EXCHANGE, feeds[INSTRUMENT])
    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id=LOGICAL_RUN_ID,
        max_order_intents_per_grid=3,
        max_order_intents_per_run=12,
    )
    receipt = facts_fixtures._refresh_all(store, target)
    facts_fixtures._arm(store)
    assert facts_fixtures._consume_quote(store) is not None
    execution_facts = facts_fixtures._project(
        store,
        broker,
        target,
        facts_time - timedelta(milliseconds=100),
        query_set=receipt.query_set,
    )
    assert execution_facts.open_risk_ready is True, execution_facts.blockers
    provider_state = {"working": False, "order_ref": None}
    query_observations = []

    def fetch_open_orders():
        query_observations.append(
            {
                "working": provider_state["working"],
                "cohort_frozen": getattr(feeds[INSTRUMENT].live_bar_cohort, "frozen", False),
                "wait_started": getattr(
                    feeds[INSTRUMENT].live_bar_cohort, "_wait_started_ns", None
                ),
            }
        )
        if not provider_state["working"]:
            return []
        return [
            {
                "OrderRef": provider_state["order_ref"],
                "InstrumentID": INSTRUMENT,
                "ExchangeID": EXCHANGE,
                "OrderStatus": "3",
                "VolumeTotalOriginal": "1",
                "VolumeTraded": "0",
                "VolumeTotal": "1",
            }
        ]

    api.fetch_open_orders = fetch_open_orders
    return (
        store,
        api,
        broker,
        journal,
        coordinator,
        execution_facts,
        provider_state,
        query_observations,
    )


def _compose_epoch(
    calendar: LiveCohortCalendar,
    rows_by_target,
    *,
    epoch_id: int,
    cohort_id: str,
    facts_time: datetime,
    history_length: int = 0,
    missing_target: str | None = None,
    missing_slot: int | None = None,
    callback_on_wait=None,
    strategy_holder=None,
):
    cohort = LiveBarCohort(
        cohort_id,
        calendar,
        max_pending_slots=2,
        max_window_bars=2,
        wait_timeout_ns=20_000_000,
    )
    clock = _ReplayClock(
        calendar.slots[-1].close_time + timedelta(seconds=2),
        wait_timeout_seconds=0.020,
        on_first_wait=callback_on_wait,
    )
    feeds = {}
    for target in TARGETS:
        live_rows = tuple(
            row
            for index, row in enumerate(rows_by_target[target])
            if not (target == missing_target and index == missing_slot)
        )
        source_ref = "fixture-feed-" + target
        origin_row = rows_by_target[target][0]
        source_origin = LiveSourceOrigin(
            member_id="member-" + target,
            epoch_id=epoch_id,
            source_ref=source_ref,
            source_role="history" if history_length else "live",
            connection_generation=origin_row["connection_generation"],
            bar_id=origin_row["bar_id"],
            feed_sequence=origin_row["bar_sequence"],
            close_time=origin_row["bucket_end"],
        )
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            historical_bars=rows_by_target[target][:history_length],
            live_bars=rows_by_target[target][max(history_length - 1, 0) :]
            if history_length
            else live_rows,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            clock=clock,
            cohort_source_origin=source_origin,
        )
        feeds[target] = feed
        cohort.register_member(
            "member-" + target,
            feed,
            instrument=target,
            source_ref=source_ref,
            line_fields=FIELDS,
            raw_fields=FIELDS,
            numeric_fields=FIELDS,
            source_origin=source_origin,
        )
    cohort.seal()
    (
        store,
        api,
        broker,
        journal,
        coordinator,
        execution_facts,
        provider_state,
        query_observations,
    ) = _execution_stack(feeds, facts_time=facts_time)
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.setbroker(broker)
    for target in TARGETS:
        cerebro.adddata(feeds[target], name=target)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _GapExecutionStrategy,
        cohort=cohort,
        plan=_plan(calendar),
        coordinator=coordinator,
        execution_facts=execution_facts,
        api=api,
        provider_state=provider_state,
        strategy_holder=strategy_holder,
    )
    return cerebro, cohort, calendar, feeds, clock, store, api, broker, journal, query_observations


@pytest.mark.integration
def test_missing_planned_slot_keeps_order_query_and_callback_live_then_rebuilds_same_grid():
    old_calendar = _calendar(epoch_id=1, version="rules-v1")
    old_rows = _bars(old_calendar, generation="connection-1")
    old_decision_time = old_calendar.slots[0].close_time
    api_holder = {}
    strategy_holder = {}

    def enqueue_terminal_callback():
        api = api_holder["api"]
        strategy = strategy_holder["strategy"]
        cohort = strategy.p.cohort
        assert cohort._wait_started_ns is not None
        assert cohort.frozen is False
        assert cohort._next_slot_index == 1
        assert strategy.orders_by_slot == [0], [
            (
                row["batch"].slot_index,
                row["ready"],
                row["snapshot"].readiness_reasons,
                {
                    name: (member.qualified, member.reason)
                    for name, member in row["batch"].history_continuity.items()
                },
            )
            for row in strategy.observations
        ]
        order_ref = str(api.native_calls[-1][3])
        assert strategy.order is not None and strategy.order.alive()
        assert api._provider_orders[order_ref]["size"] == 1
        strategy.p.provider_state["order_ref"] = order_ref
        strategy.p.api.emit_provider_order_callback(
            order_ref,
            status="canceled",
            filled=0,
            remaining=1,
        )
        strategy.p.provider_state["working"] = False

    # The missing member is explicit by omission: the other member's slot 1
    # remains pending and slot 2 is available as lookahead, so this is a
    # planned missing-member wait followed by its bounded deadline, not EOF.
    old_broken_rows = {target: tuple(rows) for target, rows in old_rows.items()}
    old_broken_rows[TARGETS[1]] = tuple(
        row for index, row in enumerate(old_rows[TARGETS[1]]) if index != 1
    )
    old = _compose_epoch(
        old_calendar,
        old_broken_rows,
        epoch_id=1,
        cohort_id="cohort-old-gap",
        facts_time=old_decision_time,
        missing_target=TARGETS[1],
        missing_slot=1,
        callback_on_wait=enqueue_terminal_callback,
        strategy_holder=strategy_holder,
    )
    (
        old_cerebro,
        old_cohort,
        _old_calendar,
        old_feeds,
        old_clock,
        _old_store,
        old_api,
        _old_broker,
        old_journal,
        old_queries,
    ) = old
    api_holder["api"] = old_api

    old_result = old_cerebro.run(runonce=False, preload=False)
    old_strategy = strategy_holder["strategy"]
    assert len(old_result) == 1 and old_result[0] is old_strategy
    assert old_strategy.orders_by_slot == [0]
    assert old_strategy.order_batch is not None and old_strategy.order_batch.slot_index == 0
    assert old_cohort.frozen is True
    assert old_cohort.frozen_reason == "planned_gap_requires_rebuild"
    assert len(old_cohort.gaps) == 1
    gap = old_cohort.gaps[0]
    assert gap.slot_index == 1
    assert gap.slot_id == old_calendar.slots[1].slot_id
    assert gap.close_time == old_calendar.slots[1].close_time
    assert gap.missing_member_ids == ("member-" + TARGETS[1],)
    assert old_cohort._next_slot_index == 1
    assert old_cohort.current_batch() is old_strategy.observations[-1]["batch"]
    assert old_cohort.current_batch().slot_index == 0
    assert [len(old_feeds[target]) for target in TARGETS] == [1, 1]
    assert old_clock.wait_calls >= 2

    assert old_strategy.order.status == bt.Order.Canceled
    assert old_strategy.order.alive() is False
    assert len(old_strategy.terminal_notifications) == 1
    terminal = old_strategy.terminal_notifications[0]
    assert terminal["order_ref"] == old_strategy.order.ref
    assert terminal["intent_id"] == old_strategy.order.info["factor_intent_id"]
    assert terminal["cohort_frozen"] is False
    assert terminal["wait_started"] is not None
    assert terminal["batch_slot_index"] == 0
    assert terminal["next_slot_index"] == 1
    assert terminal["engine_thread"]
    assert any(
        reading["wait_started"] is not None
        and reading["cohort_frozen"] is False
        and reading["working"] is True
        for reading in old_queries
    ), old_queries
    assert [call[0] for call in old_api.native_calls] == ["insert"]
    assert old_journal.decision_capacity_snapshot().base_record_count == 1

    # Rebuild the whole group from the same planned calendar, with one
    # historical bar and its live overlap. The missing slot is restored at
    # ordinal 1; it is not replaced by whichever bar happened to arrive next.
    rebuilt_calendar = _calendar(epoch_id=2, version="rules-v2")
    assert tuple(slot.slot_id for slot in rebuilt_calendar.slots) == tuple(
        slot.slot_id for slot in old_calendar.slots
    )
    assert tuple(slot.close_time for slot in rebuilt_calendar.slots) == tuple(
        slot.close_time for slot in old_calendar.slots
    )
    rebuilt_rows = _bars(rebuilt_calendar, generation="connection-2")
    rebuilt_decision_time = rebuilt_calendar.slots[1].close_time
    rebuilt = _compose_epoch(
        rebuilt_calendar,
        rebuilt_rows,
        epoch_id=2,
        cohort_id="cohort-rebuilt-gap",
        facts_time=rebuilt_decision_time,
        history_length=1,
    )
    (
        rebuilt_cerebro,
        rebuilt_cohort,
        _calendar_result,
        rebuilt_feeds,
        _rebuilt_clock,
        _rebuilt_store,
        rebuilt_api,
        _rebuilt_broker,
        rebuilt_journal,
        _rebuilt_queries,
    ) = rebuilt
    rebuilt_strategy = rebuilt_cerebro.run(runonce=False, preload=False)[0]

    assert old_cohort.frozen is True and old_cohort.epoch_id == 1
    assert old_cohort._next_slot_index == 1
    assert [len(old_feeds[target]) for target in TARGETS] == [1, 1]
    assert rebuilt_cohort.epoch_id == 2 and rebuilt_cohort.frozen is False
    assert rebuilt_cohort.cohort_id != old_cohort.cohort_id
    assert [row["batch"].slot_index for row in rebuilt_strategy.observations] == list(
        range(BAR_COUNT)
    )
    assert rebuilt_strategy.observations[0]["ready"] is LiveFactorReadiness.WARMUP
    restored = rebuilt_strategy.observations[1]
    assert restored["batch"].slot_index == gap.slot_index
    assert restored["batch"].close_time == gap.close_time
    assert set(restored["batch"].members) == {"member-" + target for target in TARGETS}
    assert all(
        restored["batch"].receipt_for_feed(rebuilt_feeds[target]).present is True
        for target in TARGETS
    )
    assert restored["ready"] is LiveFactorReadiness.LIVE_READY
    assert rebuilt_strategy.orders_by_slot == [1]
    assert [call[0] for call in rebuilt_api.native_calls] == ["insert"]
    assert rebuilt_journal.decision_capacity_snapshot().base_record_count == 1
    assert Decimal(str(rebuilt_strategy.order.size)) == Decimal("1")
