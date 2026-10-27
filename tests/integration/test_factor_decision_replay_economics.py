"""Compose the 028 Alpha003 planner with durable factor-grid decisions.

The Store's provider class is a test leaf and is never instantiated. These
checks exercise planning and journal admission only; they make no account or
provider calls and do not submit an order.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
from types import MappingProxyType, SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research.live import (
    LiveFactorReadiness,
    LiveFactorResult,
    LiveFactorSnapshot,
)
from backtrader.research.live_cohort import LiveCohortBatch
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.registered_sim import RegisteredSimStore


_ROOT = Path(__file__).resolve().parents[2]
_STRATEGY_PATH = (
    _ROOT / "examples" / "unified" / "028_alpha003_simnow_minute" / "alpha003_strategy.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "alpha003_decision_replay_economics_test_module", _STRATEGY_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_STRATEGY = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _STRATEGY
_SPEC.loader.exec_module(_STRATEGY)


UTC = timezone.utc
ACCOUNT_SCOPE = "alpha003-account-fixture"
STRATEGY_SCOPE = "alpha003-strategy-fixture"
RUN_ID = "alpha003-run-one"
CLOSE = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
AVAILABLE = CLOSE + timedelta(seconds=2)
EVALUATED = CLOSE + timedelta(seconds=4)
TARGETS = ("rb", "i")
ROUTES = {"rb": ("rb2610", "SHFE"), "i": ("i2610", "DCE")}
PRODUCT_KEYS = {"rb": ("SHFE", "rb"), "i": ("DCE", "i")}


class _NeverCalledProvider:
    """External API leaf: construction or calls would invalidate this test."""

    def __init__(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("the provider leaf must remain unused")


def _risk_policy():
    return _STRATEGY.Alpha003RiskPolicy(
        risk_policy_id="alpha003-replay-economics-v1",
        max_hold_eligible_bars=12,
        preclose_grace_seconds=60,
        run_end_policy="CLOSE_ALL",
        quote_max_age_seconds=Decimal("5"),
        max_state_age_seconds=Decimal("30"),
        max_notional_per_position=Decimal("3000"),
        max_total_notional=Decimal("5000"),
        max_margin_per_position=Decimal("250"),
        max_total_margin=Decimal("500"),
        max_loss_per_position=Decimal("20"),
        max_total_loss=Decimal("40"),
        stop_loss_ticks=2,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=20,
        round_trip_fee_upper_bound_per_contract=Decimal("1"),
    )


def _target_decision(*, mode, cohort_id="cohort-one", batch_id="batch-one", close=CLOSE, epoch=1):
    available = close + timedelta(seconds=2)
    cohort = _STRATEGY.CohortBatchFacts(
        status="COMPLETE",
        batch_id=batch_id,
        cohort_id=cohort_id,
        calendar_id="alpha003-calendar-v1",
        epoch_id=epoch,
        close_time=close,
        available_at=available,
    )
    factor = _STRATEGY.FactorSnapshotFacts(
        readiness="LIVE_READY",
        batch_complete=True,
        batch_id=batch_id,
        cohort_id=cohort_id,
        calendar_id="alpha003-calendar-v1",
        epoch_id=epoch,
        close_time=close,
        available_at=available,
        factor_name="alpha003",
        mode=mode,
        direction=1,
        source_sha256="a" * 64,
        points=(
            _STRATEGY.FactorPoint(
                target_id="rb",
                product_key=PRODUCT_KEYS["rb"],
                value=1.25,
                status="OUTPUT_AVAILABLE",
                present=True,
                complete=True,
                quality="GOOD",
            ),
            _STRATEGY.FactorPoint(
                target_id="i",
                product_key=PRODUCT_KEYS["i"],
                value=-0.75,
                status="OUTPUT_AVAILABLE",
                present=True,
                complete=True,
                quality="GOOD",
            ),
        ),
    )
    policy_input = _STRATEGY.Alpha003PolicyInput(
        cohort=cohort,
        factor=factor,
        required_targets=TARGETS,
        authorized_targets=frozenset(TARGETS),
        eligible_grid_index=5,
        rebalance_every=5,
        execution_mode="LIVE",
    )
    return _STRATEGY.select_alpha003_targets(policy_input)


def _planning_input(target_decision, *, close=CLOSE):
    evaluated_at = close + timedelta(seconds=4)
    state_at = close + timedelta(seconds=3)
    positions = tuple(
        _STRATEGY.Alpha003PositionFact(
            target_id=target,
            instrument=instrument,
            exchange=exchange,
            quantity=0,
            snapshot_id="positions-snapshot-v1",
            available_at=state_at,
        )
        for target, (instrument, exchange) in ROUTES.items()
    )
    instruments = tuple(
        _STRATEGY.Alpha003InstrumentRiskFact(
            target_id=target,
            instrument=instrument,
            exchange=exchange,
            snapshot_id="metadata-snapshot-v1",
            available_at=state_at,
            trading_permitted=True,
            multiplier=Decimal("10"),
            long_margin_per_hand=Decimal("100"),
            short_margin_per_hand=Decimal("100"),
            tick_size=Decimal("0.1"),
            lower_limit=Decimal("80"),
            upper_limit=Decimal("130"),
            route_permitted=True,
        )
        for target, (instrument, exchange) in ROUTES.items()
    )
    quotes = tuple(
        _STRATEGY.Alpha003QuoteFact(
            instrument=instrument,
            exchange=exchange,
            source_ref="fixture-quote-" + target,
            metadata_snapshot_id="metadata-snapshot-v1",
            generation=1,
            sequence=17,
            event_time=close + timedelta(seconds=2),
            available_at=close + timedelta(seconds=3),
            bid=Decimal("100.0"),
            ask=Decimal("100.1"),
            bid_size=Decimal("2"),
            ask_size=Decimal("2"),
            tick_size=Decimal("0.1"),
            lower_limit=Decimal("80"),
            upper_limit=Decimal("130"),
            quality="GOOD",
        )
        for target, (instrument, exchange) in ROUTES.items()
    )
    account = _STRATEGY.Alpha003AccountRiskFact(
        account_scope=ACCOUNT_SCOPE,
        snapshot_id="account-snapshot-v1",
        available_at=state_at,
        route_permitted=True,
        available_margin=Decimal("10000"),
        used_margin=Decimal("0"),
        current_notional=Decimal("0"),
        current_worst_case_loss=Decimal("0"),
        cash=Decimal("10000"),
        equity=Decimal("10000"),
    )
    return _STRATEGY.Alpha003OrderPlanningInput(
        strategy_scope=STRATEGY_SCOPE,
        evaluated_at=evaluated_at,
        risk_evidence_available_at=state_at,
        session_close_at=close + timedelta(hours=1),
        run_end=False,
        risk_policy=_risk_policy(),
        account=account,
        positions=positions,
        working_orders=(),
        quotes=quotes,
        instruments=instruments,
        target_decision=target_decision,
        run_order_intents_used=0,
    )


def _batch_and_snapshot(decision):
    batch = LiveCohortBatch(
        batch_id=decision.batch_id,
        cohort_id=decision.cohort_id,
        calendar_id="alpha003-calendar-v1",
        calendar_version="rules-v1",
        epoch_id=1,
        slot_index=4,
        close_time=decision.close_time,
        available_at=decision.available_at,
    )
    factor = LiveFactorResult(
        name="alpha003",
        mode=decision.mode,
        panel_line="factor",
        direction=decision.direction,
        source_sha256=decision.source_sha256,
        field_policy_sha256="b" * 64,
        pit_policy_complete=True,
        pit_qualified=True,
        unqualified_fields=(),
        inputs=MappingProxyType({}),
        values=MappingProxyType({}),
    )
    snapshot = LiveFactorSnapshot(
        plan_id="alpha003-live-v1",
        cohort_id=decision.cohort_id,
        calendar_id="alpha003-calendar-v1",
        calendar_version="rules-v1",
        frequency="1min",
        epoch_id=1,
        batch_id=decision.batch_id,
        close_time=decision.close_time,
        available_at=decision.available_at,
        batch_complete=True,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
        factors=MappingProxyType({"alpha003": factor}),
    )
    return batch, snapshot


def _strategy_facade(broker, coordinator, decision, batch, snapshot):
    cohort = SimpleNamespace(cohort_id=batch.cohort_id, current_batch=lambda: batch)
    owner = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    owner.broker = broker
    owner._coordinator = coordinator
    owner._account_scope = ACCOUNT_SCOPE
    owner._strategy_scope = STRATEGY_SCOPE
    owner._logical_run_id = coordinator.logical_run_id
    owner._source_kind = "ALPHA003_GRID"
    owner._last_signal_target = decision
    owner.last_execution_block_reason = None
    owner.p = SimpleNamespace(cohort=cohort, execution_enabled=False)
    owner.live_factors = SimpleNamespace(snapshot=lambda: snapshot)
    owner._dispatch_live_actions = lambda *_args: pytest.fail("shadow decision dispatched an order")
    assert isinstance(owner, bt.Strategy)
    return owner


@pytest.mark.integration
def test_alpha003_economics_replay_and_unknown_owner_stay_bound_to_the_durable_grid():
    """Identical signal inputs yield identical economics; journal identity wins on replay."""
    native_target = _target_decision(mode="native")
    build_target = _target_decision(mode="build")
    assert native_target.status == build_target.status == "TARGETS_READY"
    assert tuple((item.target_id, item.target_position) for item in native_target.targets) == tuple(
        (item.target_id, item.target_position) for item in build_target.targets
    )
    assert tuple((item.target_id, item.target_position) for item in native_target.targets) == (
        ("rb", 1),
        ("i", -1),
    )

    # Account, positions, metadata, exact quote receipt, and evaluation time
    # are unchanged while native/build factor results are compared.
    frozen = _planning_input(native_target)
    native_plan = _STRATEGY.plan_alpha003_orders(frozen)
    build_plan = _STRATEGY.plan_alpha003_orders(replace(frozen, target_decision=build_target))
    assert native_plan.status == build_plan.status == "READY"
    assert tuple(native_plan.actions) == tuple(build_plan.actions)
    economics_owner = SimpleNamespace(_risk_policy=frozen.risk_policy)
    economics_owner._risk_policy_payload = (
        lambda: _STRATEGY.Alpha003TargetStrategy._risk_policy_payload(economics_owner)
    )
    native_keys, native_economics = _STRATEGY.Alpha003TargetStrategy._order_intents(
        economics_owner, native_plan, SimpleNamespace(batch_id=native_target.batch_id)
    )
    build_keys, build_economics = _STRATEGY.Alpha003TargetStrategy._order_intents(
        economics_owner, build_plan, SimpleNamespace(batch_id=build_target.batch_id)
    )
    assert native_keys == build_keys
    assert native_economics == build_economics
    assert len(native_keys) == len(native_economics) == 2

    store = RegisteredSimStore(allow_writes=False, api_cls=_NeverCalledProvider)
    broker = bt.brokers.BtApiBroker(
        store=store,
        cash=10_000,
        validation_enabled=False,
        cash_check_enabled=False,
    )
    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id=RUN_ID,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=20,
    )
    batch, snapshot = _batch_and_snapshot(native_target)
    owner = _strategy_facade(broker, coordinator, native_target, batch, snapshot)

    # The real 028 decision method uses the real coordinator/journal. Shadow
    # mode records the proposed economics as a durable NOOP before dispatch.
    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(owner, batch, snapshot, None, native_plan)
    cursor = coordinator.grid_cursor(batch.cohort_id)
    assert cursor is not None and cursor.ordinal == 1
    saved = journal.decision(cursor.decision_id)
    assert saved is not None and saved.is_noop is True
    assert saved.intent_keys == ()
    assert saved.economic_payload["dispatch_suppressed"] is True
    assert len(saved.economic_payload["proposed_actions"]) == 2
    assert owner._coordinator.run_order_count() == 0

    # Exact replay stays a no-dispatch replay. A changed child order under the
    # same business key is a conflict, not a second order decision.
    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(owner, batch, snapshot, None, native_plan)
    assert coordinator.grid_cursor(batch.cohort_id) == cursor
    changed_action = replace(
        native_plan.actions[0], limit_price=native_plan.actions[0].limit_price + 1
    )
    changed_plan = replace(native_plan, actions=(changed_action,) + native_plan.actions[1:])
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
            owner, batch, snapshot, None, changed_plan
        )

    # A new logical run/cohort/mode/config at the already-consumed UTC grid
    # cannot reset account+strategy highwater. The transaction leaves no new
    # cohort cursor behind.
    restarted_key = ExecutionDecisionKey(
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id="alpha003-run-two",
        cohort_id="cohort-new-epoch-build-config",
        close_time=CLOSE.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    changed_grid_economics = {
        name: value
        for name, value in saved.economic_payload.items()
        if name != "_journal_run_order_reservation"
    }
    changed_grid_economics.update(
        factor_mode="build",
        config_sha256="c" * 64,
        generation="connection-generation-2",
    )
    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        journal.record_grid_decision(
            restarted_key,
            changed_grid_economics,
            epoch_id="2",
            batch_id="batch-new-epoch",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=20,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
    assert journal.grid_cursor(ACCOUNT_SCOPE, STRATEGY_SCOPE, restarted_key.cohort_id) is None
    assert journal.run_order_count(ACCOUNT_SCOPE, STRATEGY_SCOPE, "alpha003-run-two") == 0

    # A source-backed UNKNOWN owner for the planned instrument remains active
    # across runs. The later grid may be recorded, but its matching Alpha003
    # child intent cannot be prepared or dispatched under a new run ID.
    seed_key = ExecutionDecisionKey(
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id="alpha003-prior-run",
        cohort_id="cohort-prior-run",
        close_time=(CLOSE - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    seed_intent_key = native_keys[0]
    seed_economics = dict(native_economics[0])
    seed_decision = journal.record_decision(
        seed_key,
        {"signal": "same-alpha003-target", "intent_economics": (seed_economics,)},
        intent_keys=(seed_intent_key,),
    )
    unknown_intent = journal.prepare_intent(
        seed_decision.decision_id,
        seed_intent_key,
        seed_economics,
        original_identity={"backtrader_order_ref": 101},
    )
    assert journal.claim_dispatch(unknown_intent.intent_id) is not None
    journal.record_dispatch_result(
        unknown_intent.intent_id,
        state="UNKNOWN",
        outcome_code="connection_lost_after_dispatch",
    )

    next_target = _target_decision(
        mode="build",
        cohort_id="cohort-next-run",
        batch_id="batch-next-run",
        close=CLOSE + timedelta(minutes=2),
        epoch=2,
    )
    next_plan = _STRATEGY.plan_alpha003_orders(
        _planning_input(next_target, close=next_target.close_time)
    )
    assert next_plan.status == "READY"
    next_keys, next_economics = _STRATEGY.Alpha003TargetStrategy._order_intents(
        economics_owner, next_plan, SimpleNamespace(batch_id=next_target.batch_id)
    )
    next_key = ExecutionDecisionKey(
        account_scope=ACCOUNT_SCOPE,
        strategy_scope=STRATEGY_SCOPE,
        logical_run_id="alpha003-run-two",
        cohort_id=next_target.cohort_id,
        close_time=next_target.close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    durable_next = journal.record_grid_decision(
        next_key,
        {"signal": "same-alpha003-target", "intent_economics": next_economics},
        intent_keys=next_keys,
        epoch_id="2",
        batch_id=next_target.batch_id,
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=20,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )
    assert durable_next.is_new_grid is True
    with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_ACTIVE"):
        journal.prepare_intent(
            durable_next.decision.decision_id,
            next_keys[0],
            dict(next_economics[0]),
            original_identity={"backtrader_order_ref": 202},
        )
    owner_row = journal.active_instrument_owner(ACCOUNT_SCOPE, seed_intent_key.instrument)
    assert owner_row is not None
    assert owner_row.intent_id == unknown_intent.intent_id
    assert owner_row.state == "UNKNOWN"
    journal.close()
