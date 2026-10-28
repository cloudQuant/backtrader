"""History/live cutover readiness gates the ordinary RegisteredSim order path.

This is a local source-composition test.  Cerebro, BtApiFeed, LiveBarCohort,
Alpha003, LiveFactorSet, BtApiBroker, RegisteredSimStore, the execution
coordinator, and the journal are real; only the provider SDK leaves are fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace
import math
import os
from pathlib import Path
import sqlite3
import sys
from types import MappingProxyType, SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research import FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.alpha101 import get_alpha
from backtrader.research.live import (
    LiveFactorOutputStatus,
    LiveFactorReadiness,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionIntentKey,
    ExecutionSourceReceipt,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.factor_execution_facts import FactorExecutionTarget
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.unit.stores import test_execution_fee_pair_candidate_journal as fee_pair_fixtures
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


class _WallUtcReplayClock(_ReplayClock):
    """Keep historical cohort slots while sampling live facts on wall UTC."""

    def utc_now(self):
        return datetime.now(UTC)


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


@pytest.mark.integration
def test_fee_pair_source_only_history_survives_same_run_warmup_chain_reopen(tmp_path):
    """A terminal fee-pair source row stays valid as the run HWM advances."""

    import importlib
    import importlib.util

    from backtrader.stores import execution_decision_journal as journal_api
    from tests.integration import test_alpha003_fee_pair_source_only_tape as source_only

    example_dir = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
    )
    runner_name = "_alpha003_same_run_source_chain_writer_fixture"
    runner = sys.modules.get(runner_name)
    if runner is None:
        runner_spec = importlib.util.spec_from_file_location(runner_name, example_dir / "run.py")
        assert runner_spec is not None and runner_spec.loader is not None
        runner = importlib.util.module_from_spec(runner_spec)
        sys.modules[runner_name] = runner
        runner_spec.loader.exec_module(runner)
    assert Path(runner.__file__).resolve() == example_dir / "run.py"

    seed_writer, seed_journal, candidate, batch, snapshot, target_decision = (
        source_only._fixture(tmp_path, filename="same-run-seed.jsonl")
    )
    journal_path = seed_journal.path
    seed_writer.close()
    seed_journal.close()

    selection_evidence, restart_identity = source_only._selection_binding(
        "saved_bundle_legacy"
    )
    writer = runner.DecisionTapeWriter(
        tmp_path / "same-run-live.jsonl",
        1_000_000,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=source_only._TARGETS,
        calendar_id=candidate.calendar_id,
        grid_sha256="a" * 64,
        source_snapshot_id="source-only-synthetic-snapshot",
        restart_identity=restart_identity,
        selection_evidence=selection_evidence,
        calendar_fingerprint=candidate.calendar_fingerprint,
        cross_process_generation_lease=True,
    )
    journal = ExecutionDecisionJournal(journal_path)
    candidate = replace(candidate, expected_tape_file_id=writer.file_id)
    source_only_result = None
    journal_closed = False

    def append_warmup_anchor(active_journal, coordinator, slot_index):
        close_time = batch.close_time + timedelta(minutes=slot_index)
        available_at = close_time + timedelta(seconds=2)
        slot_id = "slot-{:04d}".format(slot_index)
        batch_id = "{}:{}:{}:{}:{}".format(
            batch.cohort_id,
            batch.calendar_id,
            batch.epoch_id,
            batch.calendar_version,
            slot_index,
        )
        members = {}
        for member_id, old_member in batch.members.items():
            old_envelope = old_member.envelope
            envelope = replace(
                old_envelope,
                slot_index=slot_index,
                slot_id=slot_id,
                feed_sequence=old_envelope.feed_sequence + slot_index,
                bucket_start=close_time - timedelta(minutes=1),
                close_time=close_time,
                available_at=available_at,
                bar_id="same-run-warmup-{}-{}".format(member_id, slot_index),
            )
            members[member_id] = replace(
                old_member,
                batch_id=batch_id,
                slot_index=slot_index,
                envelope=envelope,
                feed_sequence=envelope.feed_sequence,
                close_time=close_time,
                available_at=available_at,
            )
        warmup_batch = replace(
            batch,
            batch_id=batch_id,
            slot_index=slot_index,
            close_time=close_time,
            available_at=available_at,
            members=MappingProxyType(members),
        )
        warmup_snapshot = replace(
            snapshot,
            batch_id=batch_id,
            close_time=close_time,
            available_at=available_at,
            readiness=LiveFactorReadiness.WARMUP,
            readiness_reasons=("synthetic_source_warmup",),
        )
        no_action_plan = SimpleNamespace(
            status="NO_ACTION",
            reason="CALCULATION_WARMUP",
            actions=(),
            decision_batch_id=batch_id,
            decision_available_at=available_at,
        )
        assert writer.record_decision(
            warmup_batch, warmup_snapshot, None, no_action_plan
        ) is True
        row = tuple(runner.iter_decision_tape(writer.path, max_bytes=writer.max_bytes))[-1]
        predecessor = active_journal.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        )
        assert predecessor is not None
        receipt = ExecutionSourceReceipt(
            source_kind=candidate.source_kind,
            cohort_id=row["cohort_id"],
            calendar_id=row["calendar_id"],
            calendar_version=row["calendar_version"],
            calendar_fingerprint=row["calendar_fingerprint"],
            epoch_id=row["epoch_id"],
            slot_index=row["slot_index"],
            slot_id=row["slot_id"],
            close_time=row["close_time"],
            batch_id=row["batch_id"],
            readiness=row["readiness"],
            tape_file_id=row["file_id"],
            tape_record_id=row["record_id"],
            tape_record_index=row["record_index"],
            members=runner._fee_pair_source_members_from_tape_row(row, journal_api),
            predecessor=predecessor.reference,
        )
        key = ExecutionDecisionKey(
            account_scope=candidate.key.account_scope,
            strategy_scope=candidate.key.strategy_scope,
            logical_run_id=candidate.key.logical_run_id,
            cohort_id=receipt.cohort_id,
            close_time=receipt.close_time,
            decision_kind=receipt.source_kind,
        )
        result = writer.record_verified_source_prewarm(
            key=key,
            batch=warmup_batch,
            source_receipt=receipt,
            coordinator=coordinator,
        )
        assert result.eligible is False and result.is_new_grid is False
        confirmed = active_journal.source_highwater(
            key.account_scope,
            key.strategy_scope,
            key.logical_run_id,
            receipt.source_kind,
        )
        assert confirmed is not None and confirmed.receipt == receipt
        return confirmed

    try:
        journal.register_fee_pair_required_scope(
            candidate.key.account_scope, candidate.key.strategy_scope
        )
        source_only_result = writer.record_fee_pair_source_only(
            candidate,
            batch,
            snapshot,
            target_decision,
            journal,
            owner_token=source_only._OWNER_TOKEN,
            ttl_seconds=10,
        )
        first_hwm = journal.source_highwater(
            candidate.key.account_scope,
            candidate.key.strategy_scope,
            candidate.key.logical_run_id,
            candidate.source_kind,
        )
        assert first_hwm is not None
        assert first_hwm.anchor_kind == "SOURCE_ONLY"
        assert journal.fee_pair_workflow_candidate(
            source_only_result["candidate_id"]
        ).state == "SOURCE_ONLY"

        def coordinator_for(active_journal):
            broker = SimpleNamespace(
                store=SimpleNamespace(
                    registered_sim_route_id="simnow-registered-v1",
                    allow_writes=True,
                )
            )
            return FactorExecutionCoordinator(
                broker,
                active_journal,
                account_scope=candidate.key.account_scope,
                strategy_scope=candidate.key.strategy_scope,
                logical_run_id=candidate.key.logical_run_id,
                max_order_intents_per_grid=0,
                max_order_intents_per_run=0,
            )

        first_coordinator = coordinator_for(journal)
        second_hwm = append_warmup_anchor(journal, first_coordinator, 1)
        journal.close()
        journal_closed = True

        reopened_journal = ExecutionDecisionJournal(journal_path)
        try:
            reopened_coordinator = coordinator_for(reopened_journal)
            third_hwm = append_warmup_anchor(
                reopened_journal, reopened_coordinator, 2
            )
            assert third_hwm.receipt.predecessor == second_hwm.reference
            assert third_hwm.receipt.readiness == "WARMUP"
            workflow = reopened_journal.fee_pair_workflow_candidate(
                source_only_result["candidate_id"]
            )
            assert workflow.state == "SOURCE_ONLY"
            assert workflow.source_only_decision_id == source_only_result["decision"].decision_id
            assert reopened_journal.grid_cursor(
                candidate.key.account_scope,
                candidate.key.strategy_scope,
                candidate.key.cohort_id,
            ) is None
            assert reopened_journal.run_order_count(
                candidate.key.account_scope,
                candidate.key.strategy_scope,
                candidate.key.logical_run_id,
            ) == 0
            assert source_only_result["decision"].intent_keys == ()

            writer.close()
            rows = tuple(
                runner.iter_decision_tape(writer.path, max_bytes=writer.max_bytes)
            )
            assert len(rows) == 4
            assert rows[1]["order_plan"]["status"] == "SOURCE_ONLY"
            assert all(row["order_plan"]["actions"] == [] for row in rows[1:])
            assert all(row["target_decision"] is None for row in rows[2:])
            final_readback = runner._decision_tape_readback(
                writer.path, writer.max_bytes
            )
            assert final_readback["raw_sha256"] == writer.summary()["sha256"]
            assert final_readback["record_count"] == writer.summary()["record_count"]
        finally:
            reopened_journal.close()
    finally:
        if not journal_closed:
            try:
                journal.close()
            except Exception:
                pass
        if not writer.summary()["closed"]:
            writer.close()


@pytest.mark.integration
@pytest.mark.parametrize("factor_mode", ("native", "build"))
@pytest.mark.parametrize(
    ("scope_history", "prewarm_expected"),
    (
        ("none", True),
        ("SOURCE_ONLY", True),
        ("GRID_SETTLED", True),
        ("CORRUPT_GRID_SETTLED", False),
        ("RESERVED", False),
        ("APPEND_CLAIMED", False),
        ("RECEIPT_VERIFIED", False),
        ("LEGACY_APPEND_CLAIMED", False),
    ),
)
def test_alpha003_catching_up_source_anchor_requires_verified_no_intent_tape(
    factor_mode, scope_history, prewarm_expected, tmp_path
):
    """Production Strategy/Writers anchor catch-up without opening GRID.

    Completed modern fee-pair workflows must permit a later prewarm. Active
    workflows and unlinked legacy candidates remain fail-closed.
    """

    import importlib
    import importlib.util

    example_dir = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
    )
    if str(example_dir) not in sys.path:
        sys.path.insert(0, str(example_dir))
    strategy_module = importlib.import_module("alpha003_strategy")
    runner_name = "_alpha003_catching_up_writer_fixture"
    runner = sys.modules.get(runner_name)
    if runner is None:
        runner_spec = importlib.util.spec_from_file_location(runner_name, example_dir / "run.py")
        assert runner_spec is not None and runner_spec.loader is not None
        runner = importlib.util.module_from_spec(runner_spec)
        sys.modules[runner_name] = runner
        runner_spec.loader.exec_module(runner)

    targets = ("rb", "cu")
    history_lengths = {"rb": 10, "cu": 12}
    member_sessions = {
        target: LiveCalendarMemberSession(
            trading_day="2026-10-24", session_segment="regular"
        )
        for target in targets
    }
    slots = tuple(
        LiveCalendarSlot(
            slot_id="catchup-minute-{}".format(index),
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="2026-10-24",
            session_segment="regular",
            member_sessions=member_sessions,
        )
        for index in range(12)
    )
    calendar = LiveCohortCalendar(
        calendar_id="alpha003-catchup-source-v1",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-alpha003-catchup-source",
        session_semantics="ctp-regular-v1",
        slots=slots,
    )
    now = slots[-1].close_time + timedelta(seconds=2)
    clock = _ReplayClock(now)
    cohort = LiveBarCohort(
        "cohort-alpha003-catchup-source",
        calendar,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=2_000_000_000,
    )
    feeds = {}
    for asset_index, target in enumerate(targets):
        bars = tuple(
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
                    "clock_domain_id": "clock-alpha003-catchup-source",
                    "connection_generation": "catchup-generation-1",
                    "bar_sequence": index + 1,
                    "bar_id": "{}-catchup-{}".format(target, index),
                    "open": float(10 + ((asset_index + index) % 2)),
                    "high": float(12 + ((asset_index + index) % 2)),
                    "low": float(9 + ((asset_index + index) % 2)),
                    "close": float(11 + ((asset_index + index) % 2)),
                    "volume": float(100 + ((2 * asset_index + index) % 2)),
                    "openinterest": 0.0,
                    "present": True,
                    "complete": True,
                    "quality": "GOOD",
                    "quality_flags": (),
                    "source": "alpha003-catching-up-source-fixture",
                }
            )
            for index, slot in enumerate(slots)
        )
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            historical_bars=bars[: history_lengths[target]],
            live_bars=bars[history_lengths[target] - 1 :],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            clock=clock,
        )
        feeds[target] = feed
        cohort.register_member(
            target,
            feed,
            instrument=target,
            source_ref="fixture-catching-up-" + target,
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )
    cohort.seal()

    api, store, broker, journal, coordinator, *_unused = execution_fixtures._system(
        now=now,
        query_rows=facts_fixtures._query_rows(),
        journal_path=(
            tmp_path / "corrupt-terminal-workflow.sqlite3"
            if scope_history == "CORRUPT_GRID_SETTLED"
            else None
        ),
    )
    journal.register_fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE)
    if scope_history != "none":
        if scope_history in ("GRID_SETTLED", "CORRUPT_GRID_SETTLED"):
            fee_case, fee_candidate, quote_by_route = (
                fee_pair_fixtures._fee_pair_settlement_fixture(
                    "catchup-terminal-grid"
                )
            )
        else:
            fee_candidate = fee_pair_fixtures._candidate(
                run_id="catchup-prior-{}".format(scope_history.lower()),
                close_time="2026-10-28T10:00:00Z",
            )
            fee_candidate = replace(
                fee_candidate,
                key=replace(
                    fee_candidate.key,
                    account_scope=ACCOUNT_SCOPE,
                    strategy_scope=STRATEGY_SCOPE,
                ),
            )
            fee_case = None
            quote_by_route = None
        assert fee_candidate.key.account_scope == ACCOUNT_SCOPE
        assert fee_candidate.key.strategy_scope == STRATEGY_SCOPE
        owner_token = "catchup-fee-pair-owner-" + scope_history.lower() + "-" + "w" * 40
        if scope_history == "LEGACY_APPEND_CLAIMED":
            legacy = journal.reserve_fee_pair_candidate(
                fee_candidate, owner_token=owner_token, ttl_seconds=10
            )
            claimed_legacy = journal.record_fee_pair_append_claim(
                legacy.candidate_id, owner_token=owner_token
            )
            assert claimed_legacy.state == "APPEND_CLAIMED"
        else:
            reserved = journal.reserve_fee_pair_workflow_candidate(
                fee_candidate, owner_token=owner_token, ttl_seconds=10
            )
            if scope_history in (
                "APPEND_CLAIMED",
                "RECEIPT_VERIFIED",
                "SOURCE_ONLY",
                "GRID_SETTLED",
                "CORRUPT_GRID_SETTLED",
            ):
                claimed = journal.record_fee_pair_workflow_append_claim(
                    reserved.candidate_id, owner_token=owner_token
                )
                assert claimed.state == "APPEND_CLAIMED"
            if scope_history in (
                "RECEIPT_VERIFIED",
                "SOURCE_ONLY",
                "GRID_SETTLED",
                "CORRUPT_GRID_SETTLED",
            ):
                from backtrader.stores import execution_decision_journal as journal_module

                receipt = journal_module._fee_pair_receipt_from_candidate(
                    fee_candidate, "catchup-prior-verified-tape-row"
                )
                attached = journal.attach_verified_fee_pair_source_receipt(
                    reserved.candidate_id, receipt, owner_token=owner_token
                )
                assert attached.state == "RECEIPT_VERIFIED"
            if scope_history == "SOURCE_ONLY":
                terminal = journal.finalize_fee_pair_source_only_from_attached_receipt(
                    reserved.candidate_id, owner_token=owner_token
                )
                assert terminal.is_noop
                assert journal.fee_pair_workflow_candidate(reserved.candidate_id).state == (
                    "SOURCE_ONLY"
                )
            elif scope_history in ("GRID_SETTLED", "CORRUPT_GRID_SETTLED"):
                payload = fee_pair_fixtures._fee_pair_grid_economic_payload(
                    fee_candidate,
                    fee_case.facts,
                    quote_by_route,
                    receipt,
                )
                settled = journal.settle_fee_pair_grid_decision(
                    reserved.candidate_id,
                    owner_token=owner_token,
                    facts=fee_case.facts,
                    current_account_session_id=fee_candidate.account_session_id,
                    current_account_session_generation=(
                        fee_candidate.account_session_generation
                    ),
                    max_query_age_seconds=20.0,
                    max_quote_age_seconds=10.0,
                    economic_payload=payload,
                    max_order_intents_per_run=100,
                    expected_run_order_intents_used=0,
                    remaining_exit_intent_reserve=0,
                )
                assert settled.is_new_grid is True
                terminal_workflow = journal.fee_pair_workflow_candidate(
                    reserved.candidate_id
                )
                assert terminal_workflow.state == "RECEIPT_VERIFIED"
                assert terminal_workflow.grid_settled_decision_id is not None
                if scope_history == "CORRUPT_GRID_SETTLED":
                    with journal._transaction() as cursor:
                        journal._raise_if_fee_pair_scope_prewarm_busy(
                            cursor,
                            account_scope=ACCOUNT_SCOPE,
                            strategy_scope=STRATEGY_SCOPE,
                        )
                    with sqlite3.connect(str(journal.path)) as corrupt_database:
                        corrupt_database.execute(
                            "DROP TRIGGER execution_fee_pair_workflow_state"
                        )
                        corrupt_database.execute(
                            """UPDATE execution_fee_pair_workflows
                               SET grid_decision_id=? WHERE candidate_id=?""",
                            ("0" * 64, reserved.candidate_id),
                        )
            elif scope_history in ("RESERVED", "APPEND_CLAIMED", "RECEIPT_VERIFIED"):
                current_workflow = journal.fee_pair_workflow_candidate(
                    reserved.candidate_id
                )
                assert current_workflow.state == scope_history
                assert current_workflow.grid_settled_decision_id is None
    writer = runner.DecisionTapeWriter(
        tmp_path / (factor_mode + "-catchup-source.jsonl"),
        2_000_000,
        mode="live",
        factor_mode=factor_mode,
        direction=1,
        targets=targets,
        calendar_id=calendar.calendar_id,
        grid_sha256=None,
        source_snapshot_id=None,
        calendar_fingerprint=cohort.calendar_fingerprint,
        cross_process_generation_lease=True,
    )

    class _ProductionCatchupStrategy(strategy_module.Alpha003TargetStrategy):
        def __init__(self):
            super().__init__()
            self.source_observations = []

        def _live_facts(self, now):
            return None

        def _observe(self, phase):
            batch, snapshot = self._current_batch_snapshot()
            if batch is not None and snapshot is not None:
                self.source_observations.append((phase, batch, snapshot))

        def prenext(self):
            self._observe("prenext")
            super().prenext()

        def next(self):
            self._observe("next")
            super().next()

    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.setbroker(broker)
    for target in targets:
        cerebro.adddata(feeds[target], name=target)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(
        _ProductionCatchupStrategy,
        cohort=cohort,
        calendar_id=calendar.calendar_id,
        factor_mode=factor_mode,
        direction=1,
        authorized_targets=targets,
        product_keys={target: ("SYNTH", target) for target in targets},
        preheat_bars=10,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=2_000_000_000,
        rebalance_every=5,
        replay_mode=False,
        execution_enabled=False,
        risk_policy=None,
        routes={target: (target, "SYNTH") for target in targets},
        session_calendars={},
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id="run-1",
        max_live_bar_age_seconds=120,
        max_future_skew_seconds=0,
        decision_tape=writer,
    )

    try:
        result = cerebro.run(runonce=False, preload=False)
        if prewarm_expected:
            writer.close()
        else:
            with pytest.raises(runner.RunnerError, match="DECISION_TAPE_CLOSE_FAILED"):
                writer.close()
        strategy = result[0]
        assert strategy.source_observations
        assert any(
            snapshot.readiness is LiveFactorReadiness.WARMUP
            for _phase, _batch, snapshot in strategy.source_observations
        )
        catchup = [
            (phase, batch, snapshot)
            for phase, batch, snapshot in strategy.source_observations
            if snapshot.readiness is LiveFactorReadiness.CATCHING_UP
        ]
        assert catchup and any(phase == "next" for phase, _batch, _snapshot in catchup)
        assert all(
            set(member.envelope.source_role for member in batch.members.values())
            == {"history", "live"}
            for _phase, batch, _snapshot in catchup
        )
        logical_run_id = "run-1"
        highwater = journal.source_highwater(
            ACCOUNT_SCOPE, STRATEGY_SCOPE, logical_run_id, strategy._source_kind
        )
        if not prewarm_expected:
            assert highwater is None
            assert writer.summary()["closed"] is True
            assert writer.summary()["failed"] is True
            assert writer._generation_lease.held is False
            assert coordinator.run_order_count() == 0
            assert journal.grid_cursor(
                ACCOUNT_SCOPE, STRATEGY_SCOPE, cohort.cohort_id
            ) is None
            for _phase, blocked_batch, _snapshot in strategy.source_observations:
                blocked_key = ExecutionDecisionKey(
                    account_scope=ACCOUNT_SCOPE,
                    strategy_scope=STRATEGY_SCOPE,
                    logical_run_id=logical_run_id,
                    cohort_id=blocked_batch.cohort_id,
                    close_time=blocked_batch.close_time.isoformat().replace("+00:00", "Z"),
                    decision_kind=strategy._source_kind,
                )
                assert journal.decision_for_key(blocked_key) is None
            blocked_rows = tuple(
                runner.iter_decision_tape(writer.path, max_bytes=2_000_000)
            )
            assert len(blocked_rows) >= 2
            assert all(row["order_plan"]["actions"] == [] for row in blocked_rows[1:])
            return
        assert highwater is not None and highwater.anchor_kind == "SOURCE_ONLY"
        assert highwater.receipt.readiness == "CATCHING_UP"
        assert coordinator.run_order_count() == 0
        assert journal.grid_cursor(
            ACCOUNT_SCOPE, STRATEGY_SCOPE, cohort.cohort_id
        ) is None
        rows = tuple(runner.iter_decision_tape(writer.path, max_bytes=2_000_000))
        assert len(rows) == writer.summary()["record_count"] + 1
        assert rows[-1]["readiness"] == "CATCHING_UP"
        assert "target_decision" in rows[-1]
        assert rows[-1]["factors"]["factors"]
        assert rows[-1]["members"]
        assert all(row["order_plan"]["actions"] == [] for row in rows[1:])
        final_batch = catchup[-1][1]
        final_member_rows = rows[-1]["members"]
        roles = set()
        for target, member in final_batch.members.items():
            envelope = member.envelope
            roles.add(envelope.source_role)
            saved_member = final_member_rows[target]
            assert saved_member["source_role"] == envelope.source_role
            assert set(saved_member["raw_values"]) == {
                "open",
                "high",
                "low",
                "close",
                "volume",
                "openinterest",
            }
            assert saved_member["raw_values"] == {
                field: runner._tape_scalar(
                    envelope.raw_values[field], "{}.{}".format(target, field)
                )
                for field in sorted(envelope.raw_values)
            }
        assert roles == {"history", "live"}
        assert rows[-1]["record_index"] == highwater.receipt.tape_record_index

        key = ExecutionDecisionKey(
            account_scope=ACCOUNT_SCOPE,
            strategy_scope=STRATEGY_SCOPE,
            logical_run_id=logical_run_id,
            cohort_id=highwater.receipt.cohort_id,
            close_time=highwater.receipt.close_time,
            decision_kind=strategy._source_kind,
        )
        with pytest.raises(ExecutionDecisionJournalError, match="VERIFIED_SOURCE_TAPE_READBACK_REQUIRED"):
            journal.record_verified_source_prewarm(key, highwater.receipt)
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"):
            coordinator.record_source_receipt(
                key=key,
                batch=catchup[-1][1],
                source_receipt=highwater.receipt,
            )
        grid_receipt = replace(highwater.receipt, readiness="LIVE_READY")
        with pytest.raises(ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"):
            journal.record_grid_decision(
                key,
                {},
                intent_keys=(),
                epoch_id=str(grid_receipt.epoch_id),
                batch_id=grid_receipt.batch_id,
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
                source_receipt=grid_receipt,
            )
        final_readback = runner._decision_tape_readback(writer.path, 2_000_000)
        assert final_readback["raw_sha256"] == writer.summary()["sha256"]
        assert final_readback["record_count"] == writer.summary()["record_count"]
    finally:
        if not writer.summary()["closed"]:
            writer.close()
        journal.close()

@pytest.mark.integration
@pytest.mark.parametrize(
    ("tape_write_confirmed", "tamper_mode", "expected_tape_errors"),
    (
        (True, None, (None, None)),
        (
            False,
            None,
            ("DECISION_TAPE_WRITE_NOT_CONFIRMED", "DECISION_TAPE_WRITE_NOT_CONFIRMED"),
        ),
        (
            True,
            "before_readback",
            ("SOURCE_RECEIPT_WRITE_FAILED", "DECISION_TAPE_WRITE_FAILED"),
        ),
        (True, "after_anchor", (None, None)),
    ),
    ids=("durable-tape", "tape-write-failed", "tampered-before-anchor", "tampered-after-anchor"),
)
def test_alpha003_prenext_history_warmup_dispatches_owned_risk_cancel(
    tape_write_confirmed, tamper_mode, expected_tape_errors, monkeypatch, tmp_path
):
    """Production WARMUP prenext adds only risk CANCEL after fixture seeding."""
    import importlib
    import importlib.util

    example_dir = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
    )
    if str(example_dir) not in sys.path:
        sys.path.insert(0, str(example_dir))
    strategy_module = importlib.import_module("alpha003_strategy")
    assert Path(strategy_module.__file__).resolve() == example_dir / "alpha003_strategy.py"
    alpha_strategy = strategy_module.Alpha003TargetStrategy
    runner_name = "_alpha003_loss_guard_runner_fixture"
    runner = sys.modules.get(runner_name)
    if runner is None:
        runner_spec = importlib.util.spec_from_file_location(
            runner_name, example_dir / "run.py"
        )
        if runner_spec is None or runner_spec.loader is None:
            raise RuntimeError("production runner source is unavailable")
        runner = importlib.util.module_from_spec(runner_spec)
        sys.modules[runner_name] = runner
        runner_spec.loader.exec_module(runner)
    assert Path(runner.__file__).resolve() == example_dir / "run.py"
    now = datetime.now(UTC)
    minute = now.replace(second=0, microsecond=0)
    closes = (minute - timedelta(minutes=1), minute)
    session_day = TRADING_DAY[:4] + "-" + TRADING_DAY[4:6] + "-" + TRADING_DAY[6:]
    member_id = "rb"
    calendar_id = execution_fixtures._CALENDAR
    cohort_id = execution_fixtures._COHORT
    clock = _WallUtcReplayClock(now)
    member_sessions = {
        member_id: LiveCalendarMemberSession(
            trading_day=session_day,
            session_segment="regular",
        )
    }
    calendar = LiveCohortCalendar(
        calendar_id=calendar_id,
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-alpha003-prenext-risk",
        session_semantics="ctp-regular-v1",
        slots=tuple(
            LiveCalendarSlot(
                slot_id="history-minute-{}".format(index),
                bucket_start=close - timedelta(minutes=1),
                close_time=close,
                trading_day=session_day,
                session_segment="regular",
                member_sessions=member_sessions,
            )
            for index, close in enumerate(closes)
        ),
    )
    bars = tuple(
        MappingProxyType(
            {
                "instrument": INSTRUMENT,
                "symbol": INSTRUMENT,
                "timestamp": close.timestamp(),
                "datetime": close,
                "bucket_start": close - timedelta(minutes=1),
                "bucket_end": close,
                "available_at": close,
                "trading_day": session_day,
                "session_segment": "regular",
                "timezone_id": "UTC",
                "clock_domain_id": "clock-alpha003-prenext-risk",
                "connection_generation": "history-generation-1",
                "bar_sequence": index + 1,
                "bar_id": "{}-history-{}".format(INSTRUMENT, index),
                "open": 100.0 + index,
                "high": 102.0 + index,
                "low": 99.0 + index,
                "close": 101.0 + index,
                "volume": 100.0 + index,
                "openinterest": 0.0,
                "present": True,
                "complete": True,
                "quality": "GOOD",
                "quality_flags": (),
                "source": "alpha003-history-prenext-risk-fixture",
            }
        )
        for index, close in enumerate(closes)
    )
    feed = bt.feeds.BtApiFeed(
        dataname=INSTRUMENT,
        historical_bars=bars,
        live_bars=(),
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        clock=clock,
    )
    cohort = LiveBarCohort(
        cohort_id,
        calendar,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=2_000_000_000,
    )
    cohort.register_member(
        member_id,
        feed,
        instrument=INSTRUMENT,
        source_ref="fixture-alpha003-history-prenext-risk",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        clock_domain_id="clock-alpha003-prenext-risk",
        timezone_id="UTC",
        session_semantics="ctp-regular-v1",
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    cohort.seal()

    api, store, broker, journal, coordinator, _old_target, *_unused = (
        execution_fixtures._source_sdk_system(
            monkeypatch,
            now=now,
            query_rows=facts_fixtures._query_rows(
                account={
                    "Available": "100000",
                    "CurrMargin": "0",
                    "CloseProfit": "1000",
                    "PositionProfit": "0",
                    "Commission": "0",
                    "CurrencyID": "CNY",
                    "TradingDay": TRADING_DAY,
                }
            ),
        )
    )
    source_anchor_expected = tape_write_confirmed and tamper_mode != "before_readback"
    target = FactorExecutionTarget("rb", INSTRUMENT, EXCHANGE, feed)
    # _system() configures its Broker for the fixture's original instrument-
    # named PandasData. This Cerebro run binds the real history feed as "rb",
    # which is the Broker position key; give that exact feed alias the same
    # exchange contract metadata before projecting any execution facts.
    broker._contract_metadata["rb"] = dict(broker._contract_metadata[INSTRUMENT])

    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.setbroker(broker)
    cerebro.adddata(feed, name="rb")
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    refresh_loop = runner.QueryRefreshLoop(
        store,
        broker,
        (target,),
        execution_target_ids=("rb",),
        coordinator=coordinator,
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        clock=clock,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=7200),
        timeout=1.0,
        overall_timeout=2.0,
        interval=0.1,
        cerebro=cerebro,
        shutdown_grace_seconds=1.0,
    )
    projection_clock_observations = []
    next_quote_sequence = 1

    def refresh_post_callback_facts(*, retain_quote=False):
        nonlocal next_quote_sequence
        receipt, projection_now, consumed = facts_fixtures._refresh_complete_facts_after_callback(
            api,
            store,
            target,
            sequence=next_quote_sequence,
            trading_day=TRADING_DAY,
        )
        next_quote_sequence += 1
        assert runner.QueryRefreshLoop._receipt_complete(receipt) is True
        refresh_loop.last_receipt = receipt
        assert api._use_observed_query_clock is True
        assert receipt.query_set.completed_at_utc <= projection_now
        assert projection_now <= clock.utc_now()
        assert consumed.received_wall_time <= projection_now.timestamp()
        if retain_quote:
            assert store.get_latest_tick_snapshot(INSTRUMENT) is not None
        else:
            # Exercise the complete fresh query/quote boundary while
            # deliberately leaving no executable quote for WARMUP risk.
            store._latest_ticks.clear()
            assert store.get_latest_tick_snapshot(INSTRUMENT) is None
        return receipt, projection_now

    class _DecisionTape:
        def __init__(self):
            self.rows = []
            self.path = tmp_path / "prenext-risk-decision-tape.jsonl"
            self.tamper_done = False
            self.close_error = None
            self.writer = runner.DecisionTapeWriter(
                self.path,
                1_000_000,
                mode="live",
                factor_mode="native",
                direction=1,
                targets=("rb",),
                calendar_id=calendar_id,
                grid_sha256=None,
                source_snapshot_id=None,
                calendar_fingerprint=cohort.calendar_fingerprint,
                cross_process_generation_lease=True,
            )

        @property
        def file_id(self):
            return self.writer.file_id

        @property
        def calendar_fingerprint(self):
            return self.writer.calendar_fingerprint

        @property
        def last_record_reference(self):
            return self.writer.last_record_reference

        def record_decision(self, batch, snapshot, target_decision, order_plan):
            self.rows.append((batch, snapshot, target_decision, order_plan))
            if not tape_write_confirmed:
                return False
            confirmed = self.writer.record_decision(batch, snapshot, target_decision, order_plan)
            if tamper_mode == "before_readback" and self.writer.summary()["record_count"] == 1:
                self._tamper_first_row()
            return confirmed

        def record_verified_source_prewarm(self, **kwargs):
            result = self.writer.record_verified_source_prewarm(**kwargs)
            if tamper_mode == "after_anchor" and not self.tamper_done:
                self._tamper_first_row()
            return result

        def _tamper_first_row(self):
            raw = self.path.read_bytes()
            marker = b"CALCULATION_WARMUP"
            offset = raw.find(marker)
            assert offset >= 0
            with self.path.open("r+b") as handle:
                handle.seek(offset)
                handle.write(b"X")
                handle.flush()
                os.fsync(handle.fileno())
            self.tamper_done = True

        def latch_failure(self):
            self.writer.latch_failure()

        def summary(self):
            return self.writer.summary()

        def close(self):
            try:
                return self.writer.close()
            except runner.RunnerError as error:
                self.close_error = error.code
                summary = self.writer.summary()
                if (
                    tamper_mode == "before_readback"
                    and summary["closed"]
                    and summary["failed"]
                    and not self.writer._generation_lease.held
                ):
                    return summary
                raise

    tape = _DecisionTape()
    risk_policy = strategy_module.Alpha003RiskPolicy(
        risk_policy_id="prenext-history-cancel-v1",
        max_hold_eligible_bars=10,
        preclose_grace_seconds=0,
        run_end_policy="CLOSE_ALL",
        quote_max_age_seconds=Decimal("2"),
        max_state_age_seconds=Decimal("7200"),
        max_notional_per_position=Decimal("100000"),
        max_total_notional=Decimal("300000"),
        max_margin_per_position=Decimal("10000"),
        max_total_margin=Decimal("30000"),
        max_loss_per_position=Decimal("10000"),
        max_total_loss=Decimal("20000"),
        stop_loss_ticks=5,
        max_order_intents_per_grid=4,
        max_order_intents_per_run=20,
        round_trip_fee_upper_bound_per_contract=Decimal("1"),
    )
    observations = []
    grid_decision_calls = []
    cancel_calls = []
    fee_pair_scope_registered = False

    def ctp_order_row(order_ref, status, remaining):
        identity = api._provider_orders[str(order_ref)]
        return {
            "OrderRef": str(order_ref),
            "OrderSysID": identity["order_sys_id"] or "",
            "BrokerID": api.trader_client._broker_id,
            "InvestorID": api.trader_client._investor_id,
            "InstrumentID": identity["instrument_id"],
            "ExchangeID": identity["exchange_id"],
            "OrderStatus": status,
            "Direction": "0",
            "CombOffsetFlag": "0",
            "LimitPrice": "100",
            "VolumeTotalOriginal": "1",
            "VolumeTraded": "0",
            "VolumeTotal": str(remaining),
            "FrontID": identity["front_id"],
            "SessionID": identity["session_id"],
            "TradingDay": TRADING_DAY,
        }

    original_cancel = api.cancel_order

    def ctp_cancel(order_ref, dataname=None, *, registered_sim_cancel_target=None):
        response = original_cancel(
            order_ref,
            dataname=dataname,
            registered_sim_cancel_target=registered_sim_cancel_target,
        )
        cancel_calls.append((str(order_ref), dataname))
        api.query_rows["orders_result"] = [ctp_order_row(order_ref, "5", 0)]
        api.emit_provider_order_callback(order_ref, status="canceled", filled=0, remaining=0)
        api._order_updates[-1]["details"]["OrderStatus"] = "5"
        api._order_updates[-1]["details"]["TradingDay"] = TRADING_DAY
        return response

    api.cancel_order = ctp_cancel

    class _PrenextRiskStrategy(alpha_strategy):
        def _live_facts(self, now):
            receipt = refresh_loop.last_receipt
            completed_at = None if receipt is None else receipt.query_set.completed_at_utc
            assert completed_at is None or completed_at <= now, (completed_at, now)
            if completed_at is not None:
                projection_clock_observations.append((completed_at, now))
            return super()._live_facts(now)

        def start(self):
            super().start()
            # Cerebro starts the Store immediately before strategy.start();
            # that lifecycle intentionally clears pre-start quote/query facts.
            # Establish the seed OPEN's evidence only after that boundary.
            store.registered_sim_configure_arm_templates(
                {
                    (INSTRUMENT, EXCHANGE): {
                        "md_front": "tcp://182.254.243.31:30012",
                        "strategy_identity_sha256": "a" * 64,
                        "execution_cycle_id": "alpha003-prenext-risk-v1",
                        "preflight_sha256": "b" * 64,
                    }
                }
            )
            store.registered_sim_arm(
                instrument=INSTRUMENT,
                exchange=EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="alpha003-prenext-risk-v1",
                preflight_sha256="b" * 64,
            )
            _startup_receipt, startup_projection_now = refresh_post_callback_facts(
                retain_quote=True
            )
            facts = self._live_facts(startup_projection_now)
            assert facts is not None and facts.open_risk_ready is True, (
                None if facts is None else facts.blockers
            )
            self.seed_order = None
            self.seed_decision_id = None
            self.seed_intent_id = None
            self.terminal_resolution = None
            self.terminal_reconciliation_page = None
            self.prenext_observations = observations
            self.grid_decision_calls = grid_decision_calls
            # Shutdown is requested before the first history callback. The
            # fixture will seed one owner order once a real bar is loaded,
            # then production prenext may only maintain its risk.
            self.request_shutdown()

        def _seed_owned_open_before_history_prenext(self):
            data = self._data_by_target["rb"]
            assert len(data) > 0
            assert math.isfinite(float(data.close[0]))
            _seed_receipt, seed_projection_now = refresh_post_callback_facts(retain_quote=True)
            facts = self._live_facts(seed_projection_now)
            assert facts is not None and facts.open_risk_ready is True, (
                None if facts is None else facts.blockers
            )
            loss_guard_context, loss_guard_blocker = self._refresh_run_loss_guard(
                facts, seed_projection_now
            )
            assert loss_guard_blocker is None and loss_guard_context is not None, (
                loss_guard_blocker
            )
            open_key = ExecutionIntentKey(
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
                "risk_policy_id": risk_policy.risk_policy_id,
                "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
                "entry_grid_ordinal": 1,
                "batch_id": "batch-1",
                "price": "100",
            }
            seed_scope = execution_fixtures._live_scope(
                coordinator,
                self,
                facts,
                now=self._clock_now(),
                intent_key=open_key,
                economics=economics,
                loss_guard_context=loss_guard_context,
            )
            with seed_scope:
                self.seed_order = self.buy(
                    data=data,
                    size=1,
                    price=100.0,
                    exectype=bt.Order.Limit,
                    instrument_id=INSTRUMENT,
                    exchange_id=EXCHANGE,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=STRATEGY_SCOPE,
                    offset="open",
                )
            self.seed_decision_id = seed_scope.decision_id
            self.seed_intent_id = self.seed_order.info["factor_intent_id"]
            api._provider_orders[self.seed_order.info["external_order_ref"]][
                "order_sys_id"
            ] = "sys-501"
            api.emit_provider_order_callback(
                self.seed_order.info["external_order_ref"],
                status="accepted",
                filled=0,
                remaining=1,
            )
            api._order_updates[-1]["details"]["OrderStatus"] = "3"
            api._order_updates[-1]["details"]["TradingDay"] = TRADING_DAY
            api.query_rows["orders_result"] = [
                ctp_order_row(self.seed_order.info["external_order_ref"], "3", 1)
            ]
            refresh_post_callback_facts()
            binding_failures = coordinator.bind_known_order_sysids_from_current_query()
            assert binding_failures == (), (
                binding_failures,
                store.get_registered_sim_query_snapshot("orders_result"),
            )

        def _live_grid_decision(self, *args, **kwargs):
            grid_decision_calls.append((args, kwargs))
            return super()._live_grid_decision(*args, **kwargs)

        def prenext(self):
            nonlocal fee_pair_scope_registered
            batch = cohort.current_batch()
            snapshot = self.live_factors.snapshot() if batch is not None else None
            if batch is not None and self.seed_order is None:
                assert batch.status == "COMPLETE"
                assert snapshot is not None
                assert snapshot.readiness is LiveFactorReadiness.WARMUP
                self._seed_owned_open_before_history_prenext()
            if not fee_pair_scope_registered:
                journal.register_fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE)
                fee_pair_scope_registered = True
            pre_production_order_count = coordinator.run_order_count()
            pre_production_native_actions = tuple(call[0] for call in api.native_calls)
            super().prenext()
            if batch is not None:
                receipt = batch.receipt_for_feed(feed)
                observations.append(
                    {
                        "batch": batch,
                        "snapshot": snapshot,
                        "source_role": receipt.envelope.source_role,
                        "facts": self.last_execution_facts,
                        "plan": self.last_order_plan,
                        "block_reason": self.last_execution_block_reason,
                        "pre_production_order_count": pre_production_order_count,
                        "pre_production_native_actions": pre_production_native_actions,
                    }
                )
                refresh_receipt, projection_now = refresh_post_callback_facts(
                    retain_quote=(
                        self.terminal_resolution is None
                        and self.seed_order is not None
                        and self.seed_order.getstatusname() == "Canceled"
                    )
                )
                if (
                    self.terminal_resolution is None
                    and self.seed_order is not None
                    and self.seed_order.getstatusname() == "Canceled"
                ):
                    terminal_facts = self._live_facts(projection_now)
                    assert terminal_facts is not None
                    assert len(terminal_facts.terminal_orders) == 1
                    terminal_page = coordinator.reconcile_terminal_order_observations(
                        terminal_facts,
                        refresh_receipt=refresh_receipt,
                    )
                    assert len(terminal_page.items) == 1
                    assert terminal_page.items[0].status == "RESOLVED", terminal_page.items[0]
                    self.terminal_reconciliation_page = terminal_page
                    self.terminal_resolution = journal.instrument_resolution(self.seed_intent_id)
                    assert self.terminal_resolution is not None
                    assert self.terminal_resolution.position_flat is True
                    # Re-query after the durable owner release so shutdown
                    # reads a causally newer complete execution snapshot.
                    refresh_post_callback_facts()

    cerebro.addstrategy(
        _PrenextRiskStrategy,
        cohort=cohort,
        calendar_id=calendar_id,
        factor_mode="native",
        direction=1,
        authorized_targets=("rb",),
        product_keys={"rb": (EXCHANGE, "rb")},
        preheat_bars=10,
        max_pending_slots=2,
        max_window_bars=10,
        wait_timeout_ns=2_000_000_000,
        rebalance_every=5,
        replay_mode=False,
        execution_enabled=True,
        risk_policy=risk_policy,
        routes={"rb": (INSTRUMENT, EXCHANGE)},
        session_calendars={},
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id="run-1",
        quote_max_age_seconds=2,
        max_query_age_seconds=7200,
        max_live_bar_age_seconds=120,
        max_future_skew_seconds=0,
        loss_guard_net_loss_threshold=Decimal("1000"),
        loss_guard_max_observation_age_seconds=30,
        control_refresh_loop=refresh_loop,
        decision_tape=tape,
    )

    try:
        result = cerebro.run(runonce=False, preload=False)
        tape.close()
        assert len(result) == 1
        strategy = result[0]
        assert len(observations) == 2
        assert all(row["batch"].status == "COMPLETE" for row in observations)
        assert all(row["source_role"] == "history" for row in observations)
        assert all(row["snapshot"].readiness is LiveFactorReadiness.WARMUP for row in observations)
        assert all(row["snapshot"].batch_complete is True for row in observations)
        assert observations[0]["pre_production_order_count"] == 1
        assert observations[0]["pre_production_native_actions"] == ("insert",)
        assert observations[0]["facts"].open_risk_ready is False
        assert observations[0]["facts"].order_cancel_ready is True, (
            "cancel_blockers={!r}; aggregate_blockers={!r}".format(
                observations[0]["facts"].order_cancel_blockers,
                observations[0]["facts"].aggregate_write_blockers,
            )
        )
        assert observations[0]["facts"].available_at > observations[0]["batch"].close_time
        assert observations[0]["plan"].status == "READY"
        assert tuple(action.action for action in observations[0]["plan"].actions) == ("CANCEL",)
        assert all(tape_row[2] is None for tape_row in tape.rows)
        assert all(tape_row[3].reason == "CALCULATION_WARMUP" for tape_row in tape.rows)
        assert all(tape_row[3].actions == () for tape_row in tape.rows)
        assert tuple(row["block_reason"] for row in observations) == expected_tape_errors
        assert grid_decision_calls == []
        assert strategy.seed_order is not None
        assert strategy.seed_order.info["factor_dispatch_state"] == "KNOWN"
        assert strategy.seed_order.info["factor_position_effect"] == "OPEN"
        assert strategy.seed_order.info["cancel_acknowledged"] is True
        assert strategy.seed_order.getstatusname() == "Canceled"
        assert strategy.terminal_reconciliation_page is not None
        assert len(strategy.terminal_reconciliation_page.items) == 1
        assert strategy.terminal_reconciliation_page.items[0].status == "RESOLVED"
        assert strategy.terminal_resolution is not None
        assert strategy.terminal_resolution.position_flat is True
        source_highwater = journal.source_highwater(
            ACCOUNT_SCOPE,
            STRATEGY_SCOPE,
            "run-1",
            strategy._source_kind,
        )
        if source_anchor_expected:
            assert source_highwater is not None
            assert source_highwater.anchor_kind == "SOURCE_ONLY"
            assert source_highwater.receipt.readiness == "WARMUP"
            assert source_highwater.receipt.tape_record_index == 2
            source_anchor = journal.decision(source_highwater.decision_id)
            assert source_anchor is not None
            assert source_anchor.intent_keys == ()
            assert source_anchor.economic_payload["_execution_source_anchor_only"] is True
            if tamper_mode is None:
                tape_rows = tuple(runner.iter_decision_tape(tape.path, max_bytes=1_000_000))
                assert len(tape_rows) == 3  # header plus both complete warmup rows
                assert all(row["factors"]["factors"] for row in tape_rows[1:])
                assert all(row["members"] for row in tape_rows[1:])
                assert all(row["order_plan"]["actions"] == [] for row in tape_rows[1:])
                readback = runner._decision_tape_readback(tape.path, 1_000_000)
                assert readback["raw_sha256"] == tape.writer.summary()["sha256"]
            else:
                with pytest.raises(runner.RunnerError):
                    runner._decision_tape_readback(tape.path, 1_000_000)
        else:
            assert source_highwater is None
        if tamper_mode == "before_readback":
            assert tape.writer.summary()["failed"] is True
        assert projection_clock_observations
        assert all(
            completed_at <= sampled_at
            for completed_at, sampled_at in projection_clock_observations
        )
        final_facts = strategy.last_execution_facts
        assert strategy.shutdown_ready is True, {
            "shutdown_blocker": strategy.shutdown_blocker,
            "shutdown_post_join_blocker": strategy.shutdown_post_join_blocker,
            "last_execution_block_reason": strategy.last_execution_block_reason,
            "refresh_joined": refresh_loop.joined,
            "final_facts": None
            if final_facts is None
            else {
                "available_at": getattr(final_facts, "available_at", None),
                "query_set_id": getattr(final_facts, "query_set_id", None),
                "read_only_reconciliation_ready": getattr(
                    final_facts, "read_only_reconciliation_ready", None
                ),
                "read_only_reconciliation_blockers": getattr(
                    final_facts, "read_only_reconciliation_blockers", None
                ),
                "read_only_observation_blockers": getattr(
                    final_facts, "read_only_observation_blockers", None
                ),
                "positions": tuple(
                    (
                        getattr(item, "target_id", None),
                        getattr(item, "quantity", None),
                        getattr(item, "owner_strategy_scope", None),
                        getattr(item, "owner_intent_id", None),
                    )
                    for item in getattr(final_facts, "positions", ())
                ),
                "working_orders": tuple(
                    (
                        getattr(item, "target_id", None),
                        getattr(item, "instrument", None),
                        getattr(item, "exchange", None),
                        getattr(item, "state", None),
                        getattr(item, "execution_unknown", None),
                        getattr(item, "owner_strategy_scope", None),
                        getattr(item, "owner_intent_id", None),
                    )
                    for item in getattr(final_facts, "working_orders", ())
                ),
            },
        }
        assert strategy.shutdown_post_join_confirmed is True
        assert refresh_loop.joined is True
        assert cancel_calls == [(strategy.seed_order.info["external_order_ref"], EXCHANGE + "." + INSTRUMENT)]
        assert [call[0] for call in api.native_calls] == ["insert", "cancel"]
        assert coordinator.run_order_count() == 2
        capacity = journal.decision_capacity_snapshot()
        assert capacity.base_record_count == (3 if source_anchor_expected else 1)
        assert capacity.settlement_record_count == 1
        seed_decision = journal.decision(strategy.seed_decision_id)
        assert seed_decision is not None
        assert seed_decision.key.decision_kind == "ALPHA003_GRID"
        seed_intent = journal.intent(strategy.seed_intent_id)
        assert seed_intent is not None
        assert seed_intent.key.action == "SUBMIT"
        assert seed_intent.key.position_effect == "OPEN"
        assert seed_intent.state == "KNOWN"

        cancel_intent_id = strategy.seed_order.info["factor_cancel_intent_id"]
        cancel_intent = journal.intent(cancel_intent_id)
        assert cancel_intent is not None
        assert cancel_intent.key.action == "CANCEL"
        assert cancel_intent.owner_intent_id == strategy.seed_intent_id
        assert cancel_intent.state == "KNOWN"
        risk_facts = observations[0]["facts"]
        risk_key = ExecutionDecisionKey(
            account_scope=ACCOUNT_SCOPE,
            strategy_scope=STRATEGY_SCOPE,
            logical_run_id="run-1",
            cohort_id=cohort_id,
            close_time=risk_facts.available_at.isoformat().replace("+00:00", "Z"),
            decision_kind="ALPHA003_RISK_REDUCTION",
        )
        risk_decision = journal.decision_for_key(risk_key)
        assert risk_decision is not None
        assert risk_decision.key.close_time == risk_facts.available_at.isoformat().replace(
            "+00:00", "Z"
        )
        assert risk_decision.intent_keys == (cancel_intent.key,)
        assert risk_decision.economic_payload["batch_id"] is None
        assert observations[1]["facts"].working_orders == ()
        assert observations[1]["facts"].query_set_id != observations[0]["facts"].query_set_id
        assert observations[1]["facts"].available_at > observations[0]["facts"].available_at
        assert strategy.last_execution_facts.working_orders == ()
        assert tuple(row["block_reason"] for row in observations) == expected_tape_errors
        tape_summary = tape.summary()
        assert tape_summary["closed"] is True
        if tamper_mode == "before_readback":
            assert tape_summary["failed"] is True
            assert tape.close_error == "DECISION_TAPE_CLOSE_FAILED"
            assert tape.writer._generation_lease.held is False
            with pytest.raises(runner.RunnerError):
                runner._decision_tape_readback(tape.path, 1_000_000)
        else:
            assert tape_summary["failed"] is False
            assert tape.close_error is None
        source_head = journal.source_highwater(
            ACCOUNT_SCOPE,
            STRATEGY_SCOPE,
            "run-1",
            "ALPHA003_GRID",
        )
        if source_anchor_expected:
            assert tape_summary["record_count"] == len(observations) == 2
            last_reference = tape_summary["last_record_reference"]
            assert last_reference is not None and last_reference["record_index"] == 2
            assert source_head is not None and source_head.anchor_kind == "SOURCE_ONLY"
            assert source_head.receipt.tape_file_id == tape_summary["file_id"]
            assert source_head.receipt.tape_record_id == last_reference["record_id"]
            assert source_head.receipt.tape_record_index == last_reference["record_index"]
            assert source_head.receipt.batch_id == observations[-1]["batch"].batch_id
            assert tuple(member.member_id for member in source_head.receipt.members) == ("rb",)
        elif tamper_mode == "before_readback":
            assert tape_summary["record_count"] == 1
            assert tape_summary["last_record_reference"]["record_index"] == 1
            assert source_head is None
        else:
            assert tape_summary["record_count"] == 0
            assert tape_summary["last_record_reference"] is None
            assert source_head is None
    finally:
        try:
            tape.close()
        finally:
            journal.close()
