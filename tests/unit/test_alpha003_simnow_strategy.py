"""Source contracts for the 028 Alpha003 live target policy."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import MethodType
from types import MappingProxyType, SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research.alpha101 import get_alpha
from backtrader.research.live import (
    LiveFactorOutput,
    LiveFactorPlan,
    LiveFactorReadiness,
    LiveFactorResult,
    LiveFactorSnapshot,
    LiveFactorOutputStatus,
)
from backtrader.research.specs import FactorSpec


_ROOT = Path(__file__).resolve().parents[2]
_STRATEGY_PATH = (
    _ROOT / "examples" / "unified" / "028_alpha003_simnow_minute" / "alpha003_strategy.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "alpha003_simnow_strategy_test_module", _STRATEGY_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_STRATEGY = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _STRATEGY
_SPEC.loader.exec_module(_STRATEGY)


UTC = timezone.utc
CLOSE = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
AVAILABLE = CLOSE + timedelta(seconds=2)


def _history_batch_snapshot(batch_id, close_time, available_at):
    outputs = {
        target: LiveFactorOutput(
            value=value,
            status=LiveFactorOutputStatus.OUTPUT_AVAILABLE,
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role="history",
            member_id="member-" + target,
            source_ref="history-" + target,
            sequence=1,
            generation="history-generation-1",
        )
        for target, value in (("A", 2.0), ("B", -1.0))
    }
    factor = LiveFactorResult(
        name="alpha003",
        mode="native",
        panel_line="factor",
        direction=1,
        source_sha256="b" * 64,
        inputs=MappingProxyType({}),
        values=MappingProxyType(outputs),
    )
    batch = SimpleNamespace(
        status="COMPLETE",
        batch_id=batch_id,
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        epoch_id=1,
        close_time=close_time,
        available_at=available_at,
    )
    snapshot = LiveFactorSnapshot(
        plan_id="plan-1",
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        calendar_version="v1",
        frequency="1min",
        epoch_id=1,
        batch_id=batch_id,
        close_time=close_time,
        available_at=available_at,
        batch_complete=True,
        readiness=LiveFactorReadiness.WARMUP,
        readiness_reasons=("history_only",),
        factors=MappingProxyType({"alpha003": factor}),
    )
    return batch, snapshot


def _exchange(instrument):
    return instrument.split(".", 1)[0]


def _point(
    target,
    value,
    *,
    status="OUTPUT_AVAILABLE",
    present=True,
    complete=True,
    quality="GOOD",
    product_key=None,
):
    if product_key is None:
        product_key = ("EX", target)
    return _STRATEGY.FactorPoint(
        target_id=target,
        product_key=product_key,
        value=value,
        status=status,
        present=present,
        complete=complete,
        quality=quality,
    )


def _policy(
    points,
    *,
    direction=1,
    cohort_status="COMPLETE",
    readiness="LIVE_READY",
    batch_complete=True,
    cohort_available=AVAILABLE,
    factor_available=AVAILABLE,
    quality=None,
    required=None,
    authorized=None,
    grid=5,
    rebalance_every=5,
):
    points = tuple(points)
    if quality is not None:
        points = tuple(
            _point(
                point.target_id,
                point.value,
                status=point.status,
                present=point.present,
                complete=point.complete,
                quality=quality,
                product_key=point.product_key,
            )
            for point in points
        )
    if required is None:
        required = tuple(point.target_id for point in points)
    if authorized is None:
        authorized = frozenset(required)
    cohort = _STRATEGY.CohortBatchFacts(
        status=cohort_status,
        batch_id="batch-1",
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        epoch_id=1,
        close_time=CLOSE,
        available_at=cohort_available,
    )
    factor = _STRATEGY.FactorSnapshotFacts(
        readiness=readiness,
        batch_complete=batch_complete,
        batch_id="batch-1",
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        epoch_id=1,
        close_time=CLOSE,
        available_at=factor_available,
        factor_name="alpha003",
        mode="native",
        direction=direction,
        source_sha256="a" * 64,
        points=points,
    )
    return _STRATEGY.Alpha003PolicyInput(
        cohort=cohort,
        factor=factor,
        required_targets=required,
        authorized_targets=frozenset(authorized),
        eligible_grid_index=grid,
        rebalance_every=rebalance_every,
    )


def _target_pairs(decision):
    return tuple((target.target_id, target.target_position) for target in decision.targets)


def _risk_policy(**changes):
    values = {
        "risk_policy_id": "alpha003-example-risk-v1",
        "max_hold_eligible_bars": 12,
        "preclose_grace_seconds": 60,
        "run_end_policy": "CLOSE_ALL",
        "quote_max_age_seconds": Decimal("5"),
        "max_state_age_seconds": Decimal("30"),
        "max_notional_per_position": Decimal("2000"),
        "max_total_notional": Decimal("3000"),
        "max_margin_per_position": Decimal("250"),
        "max_total_margin": Decimal("500"),
        "max_loss_per_position": Decimal("20"),
        "max_total_loss": Decimal("40"),
        "stop_loss_ticks": 2,
        "max_order_intents_per_grid": 2,
        "max_order_intents_per_run": 20,
        "round_trip_fee_upper_bound_per_contract": Decimal("1"),
    }
    values.update(changes)
    return _STRATEGY.Alpha003RiskPolicy(**values)


def _target_decision():
    return _STRATEGY.select_alpha003_targets(_policy((_point("A", 2.0), _point("B", -1.0)), grid=5))


def _quote(
    instrument,
    *,
    bid="99.5",
    ask="100",
    event_time=None,
    available_at=None,
    tick="0.5",
    lower="90",
    upper="110",
    generation=1,
    sequence=1,
):
    event_time = event_time or AVAILABLE + timedelta(seconds=4)
    available_at = available_at or AVAILABLE + timedelta(seconds=5)
    return _STRATEGY.Alpha003QuoteFact(
        instrument=instrument,
        source_ref="quote-" + instrument,
        metadata_snapshot_id="metadata-" + instrument,
        generation=generation,
        sequence=sequence,
        event_time=event_time,
        available_at=available_at,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=Decimal("1"),
        ask_size=Decimal("1"),
        tick_size=Decimal(tick),
        lower_limit=Decimal(lower),
        upper_limit=Decimal(upper),
        exchange=_exchange(instrument),
    )


def _risk_facts(*, account_changes=None, positions=None, orders=(), quotes=None, instruments=None):
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    account_values = {
        "account_scope": "simnow-paper-account",
        "snapshot_id": "account-snapshot-1",
        "available_at": evaluated_at,
        "route_permitted": True,
        "available_margin": Decimal("1000"),
        "used_margin": Decimal("0"),
        "current_notional": Decimal("0"),
        "current_worst_case_loss": Decimal("0"),
    }
    account_values.update(account_changes or {})
    if positions is None:
        positions = (
            _STRATEGY.Alpha003PositionFact(
                target_id="A",
                instrument="SHFE.rb",
                exchange="SHFE",
                quantity=0,
                snapshot_id="positions-1",
                available_at=evaluated_at,
            ),
            _STRATEGY.Alpha003PositionFact(
                target_id="B",
                instrument="DCE.i",
                exchange="DCE",
                quantity=0,
                snapshot_id="positions-1",
                available_at=evaluated_at,
            ),
        )
    if quotes is None:
        quotes = (_quote("SHFE.rb"), _quote("DCE.i"))
    if instruments is None:
        instruments = (
            _STRATEGY.Alpha003InstrumentRiskFact(
                target_id="A",
                instrument="SHFE.rb",
                exchange="SHFE",
                snapshot_id="metadata-SHFE.rb",
                available_at=evaluated_at,
                trading_permitted=True,
                multiplier=Decimal("10"),
                long_margin_per_hand=Decimal("100"),
                short_margin_per_hand=Decimal("100"),
                route_permitted=True,
            ),
            _STRATEGY.Alpha003InstrumentRiskFact(
                target_id="B",
                instrument="DCE.i",
                exchange="DCE",
                snapshot_id="metadata-DCE.i",
                available_at=evaluated_at,
                trading_permitted=True,
                multiplier=Decimal("10"),
                long_margin_per_hand=Decimal("100"),
                short_margin_per_hand=Decimal("100"),
                route_permitted=True,
            ),
        )
    return _STRATEGY.Alpha003OrderPlanningInput(
        strategy_scope="alpha003-simnow-example",
        evaluated_at=evaluated_at,
        risk_evidence_available_at=AVAILABLE,
        session_close_at=evaluated_at + timedelta(hours=3),
        run_end=False,
        risk_policy=_risk_policy(),
        account=_STRATEGY.Alpha003AccountRiskFact(**account_values),
        positions=tuple(positions),
        working_orders=tuple(orders),
        quotes=tuple(quotes),
        instruments=tuple(instruments),
        target_decision=_target_decision(),
        run_order_intents_used=0,
    )


def _genericize_target_exchange(inputs, target_id="A"):
    """Keep generic-close unit cases off SHFE/INE's dated-close contract."""

    instrument = "DCE.rb"
    exchange = "DCE"
    return replace(
        inputs,
        positions=tuple(
            replace(item, instrument=instrument, exchange=exchange)
            if item.target_id == target_id
            else item
            for item in inputs.positions
        ),
        working_orders=tuple(
            replace(item, instrument=instrument, exchange=exchange)
            if item.target_id == target_id
            else item
            for item in inputs.working_orders
        ),
        quotes=tuple(
            replace(item, instrument=instrument, exchange=exchange)
            if item.instrument == "SHFE.rb" and item.exchange == "SHFE"
            else item
            for item in inputs.quotes
        ),
        instruments=tuple(
            replace(item, instrument=instrument, exchange=exchange)
            if item.target_id == target_id
            else item
            for item in inputs.instruments
        ),
    )


def _source_backed_dated_close_facts(position_date, *, partial_close=False):
    """Load the Store/Broker/Book integration fixture lazily for close tests."""

    module_name = "_alpha003_source_backed_dated_facts_fixture"
    module = sys.modules.get(module_name)
    if module is None:
        path = _ROOT / "tests" / "unit" / "stores" / "test_factor_execution_facts.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("dated execution-facts source fixture is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module._build_source_backed_dated_close_facts(
        position_date=position_date, partial_close=partial_close
    )


def _dated_source_planning_input(facts, now):
    return _STRATEGY._live_planning_input(
        facts,
        strategy_scope=facts.strategy_scope,
        evaluated_at=now,
        risk_evidence_available_at=facts.available_at,
        session_close_at=None,
        run_end=True,
        risk_policy=_risk_policy(),
        target_decision=None,
        eligible_grid_ordinal=None,
        run_order_intents_used=0,
    )


def test_alpha003_plan_uses_production_factor_and_cohort_capacity_contract():
    spec = _STRATEGY.make_alpha003_factor_spec()
    assert isinstance(spec, FactorSpec)
    assert spec.indicator is get_alpha(3)
    assert spec.field_bindings == {
        "open": "feed:target:open",
        "volume": "feed:target:volume",
    }
    assert spec.direction == 1
    assert spec.mode == "native"

    plan = _STRATEGY.make_alpha003_live_plan(
        ("SHFE.rb", "DCE.i"), calendar_id="simnow-common-minutes-v1"
    )
    assert isinstance(plan, LiveFactorPlan)
    assert plan.targets == ("SHFE.rb", "DCE.i")
    assert plan.warmup_min_bars == 30
    assert (plan.max_pending_slots, plan.max_window_bars, plan.wait_timeout_ns) == (
        8,
        512,
        5_000_000_000,
    )
    assert plan.max_live_bar_age_seconds == 60.0
    assert plan.max_future_skew_seconds == 0.0
    assert plan.factors["alpha003"].indicator is get_alpha(3)

    bounded = _STRATEGY.make_alpha003_live_plan(
        ("SHFE.rb", "DCE.i"),
        calendar_id="simnow-common-minutes-v1",
        max_live_bar_age_seconds=17.5,
        max_future_skew_seconds=0.25,
    )
    assert bounded.max_live_bar_age_seconds == 17.5
    assert bounded.max_future_skew_seconds == 0.25


def test_authorized_subset_does_not_shrink_factor_pool_and_selects_extrema():
    policy = _policy(
        (
            _point("A", 1.5),
            _point("B", 100.0),
            _point("C", -2.0),
            _point("D", 4.0),
        ),
        required=("A", "B", "C", "D"),
        authorized={"A", "C", "D"},
    )

    decision = _STRATEGY.select_alpha003_targets(policy)

    assert decision.status == "TARGETS_READY"
    assert decision.authorized_targets == ("A", "C", "D")
    assert decision.eligible_targets == ("A", "C", "D")
    assert _target_pairs(decision) == (("D", 1), ("C", -1))
    assert decision.targets[0].raw_score == 4.0
    assert decision.targets[0].oriented_score == 4.0
    assert decision.close_time == CLOSE
    assert decision.available_at == AVAILABLE


def test_direction_is_applied_once_and_ties_use_product_key_order():
    policy = _policy(
        (
            _point("late-high", -8.0, product_key=("SHFE", "rb")),
            _point("early-high", -8.0, product_key=("DCE", "i")),
            _point("low", 5.0, product_key=("CZCE", "TA")),
        ),
        direction=-1,
    )

    decision = _STRATEGY.select_alpha003_targets(policy)

    assert decision.status == "TARGETS_READY"
    assert _target_pairs(decision) == (("early-high", 1), ("low", -1))
    assert decision.targets[0].raw_score == -8.0
    assert decision.targets[0].oriented_score == 8.0
    assert decision.targets[1].raw_score == 5.0
    assert decision.targets[1].oriented_score == -5.0


@pytest.mark.parametrize(
    "points",
    [
        (_point("A", 1.0), _point("B", 1.0)),
        (
            _point("A", 3.0),
            _point("B", float("nan"), status="OUTPUT_UNAVAILABLE"),
            _point("C", None, status="OUTPUT_UNAVAILABLE"),
        ),
    ],
)
def test_equal_or_insufficient_finite_extrema_do_not_create_targets(points):
    decision = _STRATEGY.select_alpha003_targets(_policy(points))
    assert decision.status == "BLOCKED"
    assert decision.reason == "NO_VALID_SIGNAL"
    assert decision.targets == ()


@pytest.mark.parametrize(
    "changes, expected_reason",
    [
        ({"cohort_status": "GAP"}, "COHORT_NOT_COMPLETE"),
        ({"readiness": "WARMUP"}, "FACTOR_NOT_LIVE_READY"),
        ({"readiness": "CATCHING_UP"}, "FACTOR_NOT_LIVE_READY"),
        ({"batch_complete": False}, "FACTOR_BATCH_NOT_COMPLETE"),
        (
            {
                "cohort_available": CLOSE - timedelta(seconds=1),
                "factor_available": CLOSE - timedelta(seconds=1),
            },
            "INVALID_AVAILABILITY_ORDER",
        ),
        ({"quality": "BAD"}, "INPUT_QUALITY_UNAVAILABLE"),
    ],
)
def test_incomplete_or_nonlive_evidence_blocks_new_signal(changes, expected_reason):
    points = (_point("A", 2.0), _point("B", -1.0))
    decision = _STRATEGY.select_alpha003_targets(_policy(points, **changes))
    assert decision.status == "BLOCKED"
    assert decision.reason == expected_reason
    assert decision.targets == ()


def test_batch_snapshot_identity_must_match_and_inputs_must_be_complete():
    good = (_point("A", 2.0), _point("B", -1.0))
    mismatch = _policy(good, factor_available=AVAILABLE + timedelta(seconds=1))
    assert _STRATEGY.select_alpha003_targets(mismatch).reason == "COHORT_SNAPSHOT_MISMATCH"

    incomplete = (
        _point("A", 2.0),
        _point("B", -1.0, present=False, complete=False, quality="MISSING"),
    )
    assert _STRATEGY.select_alpha003_targets(_policy(incomplete)).reason == "INPUT_INCOMPLETE"


def test_rebalance_cadence_counts_eligible_grids_and_defaults_to_five():
    points = (_point("A", 3.0), _point("B", -1.0))
    assert _STRATEGY.DEFAULT_REBALANCE_GRIDS == 5
    assert _STRATEGY.select_alpha003_targets(_policy(points, grid=4)).reason == "REBALANCE_NOT_DUE"
    assert _STRATEGY.select_alpha003_targets(_policy(points, grid=5)).status == "TARGETS_READY"


def test_shared_snapshot_projection_preserves_epoch_availability_and_quality():
    output_rows = {
        "A": LiveFactorOutput(
            value=2.0,
            status=LiveFactorOutputStatus.OUTPUT_AVAILABLE,
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role="live",
            member_id="member-A",
            source_ref="source-A",
            sequence=1,
            generation="generation-1",
        ),
        "B": LiveFactorOutput(
            value=-1.0,
            status=LiveFactorOutputStatus.OUTPUT_AVAILABLE,
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role="live",
            member_id="member-B",
            source_ref="source-B",
            sequence=1,
            generation="generation-1",
        ),
    }
    block = LiveFactorResult(
        name="alpha003",
        mode="native",
        panel_line="factor",
        direction=1,
        source_sha256="b" * 64,
        inputs=MappingProxyType({}),
        values=MappingProxyType(output_rows),
    )
    snapshot = LiveFactorSnapshot(
        plan_id="plan-1",
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        calendar_version="v1",
        frequency="1min",
        epoch_id=1,
        batch_id="batch-1",
        close_time=CLOSE,
        available_at=AVAILABLE,
        batch_complete=True,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
        factors=MappingProxyType({"alpha003": block}),
    )
    batch = SimpleNamespace(
        status="COMPLETE",
        batch_id="batch-1",
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        epoch_id=1,
        close_time=CLOSE,
        available_at=AVAILABLE,
    )

    policy = _STRATEGY.policy_input_from_shared_snapshot(
        batch,
        snapshot,
        required_targets=("A", "B"),
        authorized_targets=("A", "B"),
        product_keys={"A": ("SHFE", "rb"), "B": ("DCE", "i")},
    )

    assert policy.factor.epoch_id == 1
    assert policy.factor.available_at == AVAILABLE
    assert tuple(point.quality for point in policy.factor.points) == ("GOOD", "GOOD")
    decision = _STRATEGY.select_alpha003_targets(replace(policy, eligible_grid_index=5))
    assert decision.status == "TARGETS_READY"


def test_history_projection_can_be_replay_ready_without_mutating_live_readiness():
    batch, snapshot = _history_batch_snapshot("history-batch", CLOSE, AVAILABLE)

    policy = _STRATEGY.policy_input_from_shared_snapshot(
        batch,
        snapshot,
        required_targets=("A", "B"),
        authorized_targets=("A", "B"),
        product_keys={"A": ("SHFE", "rb"), "B": ("DCE", "i")},
        execution_mode="REPLAY",
        eligible_grid_index=5,
    )
    decision = _STRATEGY.select_alpha003_targets(policy)

    assert snapshot.readiness == LiveFactorReadiness.WARMUP
    assert policy.factor.readiness == "REPLAY_READY"
    assert decision.status == "TARGETS_READY"


def test_live_decision_reacquires_and_rejects_a_changed_factor_snapshot():
    from contextlib import contextmanager

    batch, history_snapshot = _history_batch_snapshot("batch-1", CLOSE, AVAILABLE)
    snapshot = replace(
        history_snapshot,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
    )
    changed_snapshot = replace(snapshot, available_at=AVAILABLE + timedelta(milliseconds=1))

    class _Cohort:
        def current_batch(self):
            return batch

    entered = []

    class _Coordinator:
        @contextmanager
        def decision_scope(self, **kwargs):
            entered.append(kwargs)
            yield SimpleNamespace(dispatch_allowed=False)

    strategy = SimpleNamespace(
        _coordinator=_Coordinator(),
        p=SimpleNamespace(cohort=_Cohort(), execution_enabled=False),
        live_factors=SimpleNamespace(snapshot=lambda: changed_snapshot),
        _account_scope="paper",
        _strategy_scope="alpha003-test",
        _logical_run_id="run-1",
        _last_signal_target=None,
        last_execution_block_reason=None,
        _order_intents=lambda plan, batch: ((), ()),
    )
    blocked = _STRATEGY.Alpha003OrderPlan(
        "BLOCKED", "NO_ACTION", (), "batch-1", AVAILABLE, "account-1"
    )

    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
        strategy,
        batch,
        snapshot,
        SimpleNamespace(
            snapshot_id="facts-1",
            available_at=AVAILABLE,
            account=None,
            quotes=(),
            query_provenance=(),
        ),
        blocked,
    )

    assert entered == []
    assert strategy.last_execution_block_reason == "FACTOR_SNAPSHOT_CHANGED_BEFORE_DECISION"


def test_live_shadow_records_eligible_grid_as_noop_and_never_dispatches():
    from contextlib import contextmanager

    batch, history_snapshot = _history_batch_snapshot("batch-1", CLOSE, AVAILABLE)
    snapshot = replace(
        history_snapshot,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
    )

    class _Cohort:
        cohort_id = batch.cohort_id

        def current_batch(self):
            return batch

    entered = []
    dispatched = []

    class _Coordinator:
        def run_order_count(self):
            return 0

        @contextmanager
        def decision_scope(self, **kwargs):
            entered.append(kwargs)
            yield SimpleNamespace(dispatch_allowed=True)

    action = _STRATEGY.Alpha003OrderAction(
        action="SUBMIT",
        target_id="A",
        instrument="SHFE.rb2610",
        side="BUY",
        position_effect="OPEN",
        quantity=1,
        limit_price=Decimal("100"),
        offset="open",
        reason="ALPHA003_TARGET",
        planned_stop_price=Decimal("99"),
        exchange="SHFE",
        decision_available_at=AVAILABLE,
        entry_grid_ordinal=5,
    )
    plan = _STRATEGY.Alpha003OrderPlan(
        "READY", None, (action,), batch.batch_id, AVAILABLE, "account-snapshot-1"
    )
    strategy = SimpleNamespace(
        _coordinator=_Coordinator(),
        p=SimpleNamespace(cohort=_Cohort(), execution_enabled=False),
        live_factors=SimpleNamespace(snapshot=lambda: snapshot),
        _account_scope="paper",
        _strategy_scope="alpha003-test",
        _logical_run_id="run-1",
        _last_signal_target=None,
        last_execution_block_reason=None,
        _order_intents=lambda _plan, _batch: pytest.fail(
            "shadow previews must not declare execution intents"
        ),
        _dispatch_live_actions=lambda actions, _batch: dispatched.append(actions),
    )

    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(strategy, batch, snapshot, None, plan)

    assert len(entered) == 1
    assert entered[0]["intent_keys"] == ()
    assert entered[0]["execution_facts"] is None
    payload = entered[0]["economic_payload"]
    assert payload["intent_economics"] == ()
    assert payload["dispatch_suppressed"] is True
    assert payload["proposed_actions"][0]["target_id"] == "A"
    assert payload["proposed_actions"][0]["planned_stop_price"] == "99"
    assert entered[0]["expected_run_order_intents_used"] == 0
    assert entered[0]["remaining_exit_intent_reserve"] == 0
    assert dispatched == []


def test_live_grid_scope_forwards_sampled_budget_count_and_exit_reserve():
    from contextlib import contextmanager

    batch, history_snapshot = _history_batch_snapshot("batch-1", CLOSE, AVAILABLE)
    snapshot = replace(
        history_snapshot,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
    )

    class _Cohort:
        def current_batch(self):
            return batch

    entered = []

    class _Coordinator:
        def run_order_count(self):
            pytest.fail("the planner's sampled count must be reused for CAS")

        @contextmanager
        def decision_scope(self, **kwargs):
            entered.append(kwargs)
            yield SimpleNamespace(dispatch_allowed=False)

    planning = replace(_risk_facts(), run_order_intents_used=7)
    actions = (
        _STRATEGY.Alpha003OrderAction(
            action="SUBMIT",
            target_id=target,
            instrument=instrument,
            exchange=exchange,
            side="BUY",
            position_effect="OPEN",
            quantity=1,
            limit_price=Decimal("100"),
            offset="open",
            reason="ALPHA003_TARGET",
            planned_stop_price=Decimal("99"),
            entry_grid_ordinal=5,
        )
        for target, instrument, exchange in (
            ("A", "SHFE.rb2610", "SHFE"),
            ("B", "DCE.i2610", "DCE"),
        )
    )
    plan = _STRATEGY.Alpha003OrderPlan(
        "READY", None, tuple(actions), batch.batch_id, AVAILABLE, "account-1"
    )
    strategy = SimpleNamespace(
        _coordinator=_Coordinator(),
        p=SimpleNamespace(cohort=_Cohort(), execution_enabled=True),
        live_factors=SimpleNamespace(snapshot=lambda: snapshot),
        _account_scope="paper",
        _strategy_scope="alpha003-test",
        _logical_run_id="run-1",
        _last_signal_target=None,
        last_execution_block_reason=None,
        _order_intents=lambda _plan, _batch: ((object(), object()), (object(), object())),
        _dispatch_live_actions=lambda *_args: pytest.fail("dispatch is disabled in the scope"),
    )

    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
        strategy,
        batch,
        snapshot,
        None,
        plan,
        planning=planning,
    )

    assert len(entered) == 1
    assert entered[0]["expected_run_order_intents_used"] == 7
    # Two fresh OPENs each reserve a future cancellation and first close.
    assert entered[0]["remaining_exit_intent_reserve"] == 4


def test_live_risk_scope_forwards_sampled_budget_count_and_post_plan_reserve():
    from contextlib import contextmanager

    entered = []

    class _Coordinator:
        def run_order_count(self):
            pytest.fail("the planner's sampled count must be reused for CAS")

        @contextmanager
        def risk_decision_scope(self, **kwargs):
            entered.append(kwargs)
            yield SimpleNamespace(dispatch_allowed=False)

    planning = replace(_risk_facts(), run_order_intents_used=4)
    action = _STRATEGY.Alpha003OrderAction(
        action="SUBMIT",
        target_id="A",
        instrument="SHFE.rb2610",
        exchange="SHFE",
        side="SELL",
        position_effect="CLOSE",
        quantity=1,
        limit_price=Decimal("100"),
        offset="close",
        reason="RUN_END",
        owner_intent_id="open-intent-A",
    )
    plan = _STRATEGY.Alpha003OrderPlan("READY", None, (action,), "batch-1", AVAILABLE, "account-1")
    facts = SimpleNamespace(snapshot_id="facts-1", available_at=AVAILABLE)
    strategy = SimpleNamespace(
        p=SimpleNamespace(execution_enabled=True, cohort=SimpleNamespace(cohort_id="cohort-1")),
        _coordinator=_Coordinator(),
        _risk_policy=None,
        _strategy_scope="alpha003-test",
        _account_scope="paper",
        _logical_run_id="run-1",
        _order_intents=lambda _plan, _batch: ((object(),), (object(),)),
        _dispatch_live_actions=lambda *_args: pytest.fail("dispatch is disabled in the scope"),
    )

    _STRATEGY.Alpha003TargetStrategy._live_risk_decision(
        strategy, None, facts, plan, planning=planning
    )

    assert len(entered) == 1
    assert entered[0]["expected_run_order_intents_used"] == 4
    assert entered[0]["remaining_exit_intent_reserve"] == 0


def test_live_shadow_does_not_submit_risk_reduction_preview():
    class _Coordinator:
        def risk_decision_scope(self, **_kwargs):
            pytest.fail("shadow mode must not create an executable risk scope")

    strategy = SimpleNamespace(
        p=SimpleNamespace(execution_enabled=False),
        _coordinator=_Coordinator(),
    )
    plan = _STRATEGY.Alpha003OrderPlan("READY", None, (), "batch-1", AVAILABLE, "account-1")

    _STRATEGY.Alpha003TargetStrategy._live_risk_decision(strategy, None, SimpleNamespace(), plan)


def test_live_shadow_records_grid_even_without_risk_budget_facts():
    batch, snapshot = _history_batch_snapshot("batch-1", CLOSE, AVAILABLE)
    snapshot = replace(
        snapshot,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
    )
    observed = []
    strategy = SimpleNamespace(
        p=SimpleNamespace(execution_enabled=False),
        _coordinator=None,
        _live_shadow_order_count=0,
        _shutdown_requested=Event(),
        _live_facts=lambda _now: None,
        _last_signal_target=None,
        _risk_policy=None,
        last_order_plan=None,
        _record_decision_tape=lambda *_args: (True, None, None),
        _gate_open_actions=lambda plan, **_kwargs: plan,
        _live_grid_decision=lambda *args, **kwargs: observed.append((args, kwargs)),
        _live_risk_decision=lambda *_args: pytest.fail(
            "shadow mode must not enter the risk dispatch path"
        ),
    )

    _STRATEGY.Alpha003TargetStrategy._run_live(
        strategy,
        batch,
        snapshot,
        AVAILABLE,
        5,
        None,
        False,
        is_new_batch=True,
    )

    assert len(observed) == 1
    assert observed[0][0][:3] == (batch, snapshot, None)
    assert strategy.last_order_plan.status == "BLOCKED"


def test_prenext_durably_records_each_complete_warmup_grid_once():
    batch, snapshot = _history_batch_snapshot("warmup-batch-1", CLOSE, AVAILABLE)
    writes = []

    class _Tape:
        file_id = "tape-file-1"

        def __init__(self):
            self.last_record_reference = None

        def record_decision(self, actual_batch, actual_snapshot, target, plan):
            writes.append((actual_batch, actual_snapshot, target, plan))
            self.last_record_reference = MappingProxyType(
                {
                    "file_id": self.file_id,
                    "record_id": "record-1",
                    "record_index": 0,
                    "batch_id": actual_batch.batch_id,
                }
            )
            return True

    strategy = SimpleNamespace(
        p=SimpleNamespace(replay_mode=False, decision_tape=_Tape()),
        _current_batch_snapshot=lambda: (batch, snapshot),
        _clock_now=lambda: AVAILABLE,
        _last_decision_tape_batch_id=None,
        _last_decision_tape_reference=None,
        _last_decision_tape_error=None,
        last_execution_block_reason=None,
    )
    strategy._record_decision_tape = MethodType(
        _STRATEGY.Alpha003TargetStrategy._record_decision_tape, strategy
    )

    _STRATEGY.Alpha003TargetStrategy.prenext(strategy)
    _STRATEGY.Alpha003TargetStrategy.prenext(strategy)
    batch2, snapshot2 = _history_batch_snapshot(
        "warmup-batch-2", CLOSE + timedelta(minutes=1), AVAILABLE + timedelta(minutes=1)
    )
    strategy._current_batch_snapshot = lambda: (batch2, snapshot2)
    _STRATEGY.Alpha003TargetStrategy.prenext(strategy)
    _STRATEGY.Alpha003TargetStrategy.prenext(strategy)

    assert len(writes) == 2
    assert writes[0][:3] == (batch, snapshot, None)
    assert writes[0][3].status == "NO_ACTION"
    assert writes[0][3].reason == "CALCULATION_WARMUP"
    assert writes[0][3].actions == ()
    assert writes[1][:3] == (batch2, snapshot2, None)
    assert strategy._last_decision_tape_reference["batch_id"] == batch2.batch_id


def test_prenext_leaves_ready_grid_for_target_decision_path():
    batch, snapshot = _history_batch_snapshot("ready-batch-1", CLOSE, AVAILABLE)
    snapshot = replace(snapshot, readiness=LiveFactorReadiness.LIVE_READY)
    writes = []
    strategy = SimpleNamespace(
        p=SimpleNamespace(replay_mode=False, decision_tape=object()),
        _current_batch_snapshot=lambda: (batch, snapshot),
        _clock_now=lambda: AVAILABLE,
        _last_decision_tape_batch_id=None,
        last_execution_block_reason=None,
        _record_decision_tape=lambda *args: writes.append(args),
    )

    _STRATEGY.Alpha003TargetStrategy.prenext(strategy)

    assert writes == []


def test_prenext_leaves_replay_ready_history_grid_for_target_decision_path():
    batch, snapshot = _history_batch_snapshot("replay-ready-batch-1", CLOSE, AVAILABLE)
    writes = []
    strategy = SimpleNamespace(
        p=SimpleNamespace(replay_mode=True, rebalance_every=5, decision_tape=object()),
        _current_batch_snapshot=lambda: (batch, snapshot),
        _target_ids=("A", "B"),
        _authorized_targets=frozenset(("A", "B")),
        _product_keys={"A": ("SHFE", "rb"), "B": ("DCE", "i")},
        _eligible_grid_count=0,
        _last_decision_tape_batch_id=None,
        last_execution_block_reason=None,
        _record_decision_tape=lambda *args: writes.append(args),
    )

    _STRATEGY.Alpha003TargetStrategy.prenext(strategy)

    assert writes == []


def test_live_execution_evidence_payload_binds_quote_and_query_times():
    quote = SimpleNamespace(
        instrument="SHFE.rb2610",
        exchange="SHFE",
        source_ref="tick-7",
        metadata_snapshot_id="margin-3",
        generation=4,
        sequence=7,
        event_time=AVAILABLE + timedelta(seconds=1),
        available_at=AVAILABLE + timedelta(seconds=2),
        quality="GOOD",
        bid=Decimal("100"),
        ask=Decimal("100.5"),
    )
    query = SimpleNamespace(
        family="positions_result",
        target_id=None,
        request_id=11,
        connection_generation=4,
        started_at=AVAILABLE,
        completed_at=AVAILABLE + timedelta(seconds=1),
        query_complete=True,
        scope_complete=True,
        row_count=2,
    )
    facts = SimpleNamespace(
        snapshot_id="facts-2",
        available_at=AVAILABLE + timedelta(seconds=2),
        account=SimpleNamespace(
            snapshot_id="account-2", available_at=AVAILABLE + timedelta(seconds=1)
        ),
        quotes=(quote,),
        query_provenance=(query,),
    )

    payload = _STRATEGY._live_execution_evidence_payload(facts)

    assert payload["snapshot_id"] == "facts-2"
    assert payload["available_at"] == _STRATEGY._time_key(facts.available_at)
    assert payload["quotes"][0]["generation"] == 4
    assert payload["quotes"][0]["sequence"] == 7
    assert payload["quotes"][0]["available_at"] == _STRATEGY._time_key(quote.available_at)
    assert payload["query_provenance"][0]["request_id"] == 11
    assert payload["query_provenance"][0]["completed_at"] == _STRATEGY._time_key(query.completed_at)


def test_non_due_grid_clears_older_actionable_target():
    batch5, snapshot5 = _history_batch_snapshot("history-5", CLOSE, AVAILABLE)
    batch6, snapshot6 = _history_batch_snapshot(
        "history-6", CLOSE + timedelta(minutes=1), AVAILABLE + timedelta(minutes=1)
    )
    strategy = SimpleNamespace(
        p=SimpleNamespace(
            replay_mode=True,
            factor_mode="native",
            direction=1,
            rebalance_every=5,
        ),
        _eligible_grid_count=4,
        _coordinator=None,
        _product_keys={"A": ("SHFE", "rb"), "B": ("DCE", "i")},
        _authorized_targets=frozenset(("A", "B")),
        _target_ids=("A", "B"),
        _last_signal_target=None,
    )
    strategy._cursor_ordinal = lambda _batch, *, is_new: strategy._eligible_grid_count + int(is_new)

    _STRATEGY.Alpha003TargetStrategy._update_target_decision(
        strategy, batch5, snapshot5, is_new=True
    )
    assert strategy._last_signal_target.status == "TARGETS_READY"

    _STRATEGY.Alpha003TargetStrategy._update_target_decision(
        strategy, batch6, snapshot6, is_new=True
    )
    assert strategy.last_target_decision.reason == "REBALANCE_NOT_DUE"
    assert strategy._last_signal_target is None


def test_strategy_remains_an_ordinary_backtrader_strategy():
    assert issubclass(_STRATEGY.Alpha003TargetStrategy, bt.Strategy)


def test_order_planner_creates_one_hand_per_extreme_at_fresh_tick_aligned_prices():
    plan = _STRATEGY.plan_alpha003_orders(_risk_facts())

    assert plan.status == "READY"
    assert [action.action for action in plan.actions] == ["SUBMIT", "SUBMIT"]
    assert [(action.target_id, action.side, action.quantity) for action in plan.actions] == [
        ("A", "BUY", 1),
        ("B", "SELL", 1),
    ]
    assert [action.limit_price for action in plan.actions] == [
        Decimal("100"),
        Decimal("99.5"),
    ]
    assert all(action.offset == "open" for action in plan.actions)
    assert all(action.planned_stop_price is not None for action in plan.actions)


@pytest.mark.parametrize(
    "quote_changes, expected_reason",
    [
        ({"ask": "100.1"}, "CURRENT_QUOTE_INVALID_OR_STALE"),
        ({"ask": "111"}, "CURRENT_QUOTE_INVALID_OR_STALE"),
        (
            {
                "event_time": AVAILABLE - timedelta(seconds=1),
                "available_at": AVAILABLE + timedelta(seconds=5),
            },
            "CURRENT_QUOTE_INVALID_OR_STALE",
        ),
        (
            {
                "event_time": AVAILABLE + timedelta(seconds=4),
                "available_at": AVAILABLE + timedelta(seconds=5),
            },
            None,
        ),
    ],
)
def test_order_planner_enforces_quote_availability_tick_and_price_limits(
    quote_changes, expected_reason
):
    quote = _quote("SHFE.rb", **quote_changes)
    plan = _STRATEGY.plan_alpha003_orders(_risk_facts(quotes=(quote, _quote("DCE.i"))))

    if expected_reason is None:
        assert plan.status == "READY"
    else:
        assert plan.status == "BLOCKED"
        assert plan.reason == expected_reason
        assert plan.actions == ()


@pytest.mark.parametrize(
    "kwargs",
    (
        {"max_live_bar_age_seconds": None},
        {"max_live_bar_age_seconds": True},
        {"max_live_bar_age_seconds": 0.0},
        {"max_live_bar_age_seconds": float("nan")},
        {"max_future_skew_seconds": None},
        {"max_future_skew_seconds": True},
        {"max_future_skew_seconds": -0.1},
        {"max_future_skew_seconds": float("inf")},
    ),
)
def test_live_plan_rejects_missing_or_invalid_freshness_bounds(kwargs):
    with pytest.raises((TypeError, ValueError)):
        _STRATEGY.make_alpha003_live_plan(
            ("SHFE.rb", "DCE.i"), calendar_id="simnow-common-minutes-v1", **kwargs
        )


def test_replay_metadata_availability_is_preserved_for_freshness_checks():
    metadata = MappingProxyType(
        {
            "instrument": "SHFE.rb",
            "exchange": "SHFE",
            "snapshot_id": "instrument-meta-A",
            "available_at": AVAILABLE,
            "trading_permitted": True,
            "multiplier": "10",
            "long_margin_per_hand": "100",
            "short_margin_per_hand": "100",
            "tick_size": "0.5",
            "lower_limit": "90",
            "upper_limit": "110",
        }
    )
    strategy = SimpleNamespace(
        _replay_instruments={"A": metadata},
        _routes={"A": ("SHFE.rb", "SHFE")},
    )
    later_now = AVAILABLE + timedelta(minutes=1)

    fact = _STRATEGY.Alpha003TargetStrategy._replay_instrument_facts(strategy, "A", later_now)

    assert fact.available_at == AVAILABLE
    assert fact.available_at != later_now
    assert fact.multiplier == Decimal("10")


def test_replay_quote_lookup_uses_latest_causal_row_and_dispatch_keeps_its_identity():
    earlier = _STRATEGY.Alpha003ReplayQuoteFact(
        instrument="SHFE.rb",
        exchange="SHFE",
        event_time=AVAILABLE + timedelta(seconds=2),
        available_at=AVAILABLE + timedelta(seconds=3),
        bid=Decimal("99.5"),
        ask=Decimal("100"),
        source_ref="tape-source",
        quote_id="quote-early",
    )
    selected = _STRATEGY.Alpha003ReplayQuoteFact(
        instrument="SHFE.rb",
        exchange="SHFE",
        event_time=AVAILABLE + timedelta(seconds=4),
        available_at=AVAILABLE + timedelta(seconds=5),
        bid=Decimal("100"),
        ask=Decimal("100.5"),
        source_ref="tape-source",
        quote_id="quote-selected",
    )
    future = _STRATEGY.Alpha003ReplayQuoteFact(
        instrument="SHFE.rb",
        exchange="SHFE",
        event_time=AVAILABLE + timedelta(seconds=7),
        available_at=AVAILABLE + timedelta(seconds=8),
        bid=Decimal("100"),
        ask=Decimal("100.5"),
        source_ref="tape-source",
        quote_id="quote-future",
    )
    quote_rows = (future, selected, earlier)
    observed = []
    strategy = SimpleNamespace(
        p=SimpleNamespace(execution_enabled=True),
        _replay_quotes=quote_rows,
        _logical_run_id="replay-run-1",
        _strategy_scope="alpha003-simnow-example",
        _last_signal_target=None,
        _data_by_target={"A": object()},
        _orders_by_broker_ref={},
        _replay_order_count=0,
        buy=lambda **kwargs: (observed.append(kwargs) or SimpleNamespace(ref=17)),
    )
    strategy._latest_replay_quote = lambda instrument, exchange, *, available_by: (
        _STRATEGY.Alpha003TargetStrategy._latest_replay_quote(
            strategy, instrument, exchange, available_by=available_by
        )
    )
    cutoff = selected.available_at
    action = _STRATEGY.Alpha003OrderAction(
        action="SUBMIT",
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        side="BUY",
        position_effect="OPEN",
        quantity=1,
        limit_price=Decimal("100.5"),
        offset="open",
        reason="fixture",
        decision_available_at=cutoff,
        entry_grid_ordinal=5,
    )
    plan = _STRATEGY.Alpha003OrderPlan("READY", None, (action,), "batch-1", cutoff, "account-1")

    _STRATEGY.Alpha003TargetStrategy._dispatch_replay_actions(
        strategy, plan, SimpleNamespace(batch_id="batch-1")
    )

    assert len(observed) == 1
    assert observed[0]["decision_available_at"] == cutoff
    assert observed[0]["replay_quote_id"] == "quote-selected"
    assert observed[0]["data"] is strategy._data_by_target["A"]


def test_missing_opening_margin_blocks_increase_without_inventing_a_default():
    instruments = list(_risk_facts().instruments)
    instruments[0] = replace(instruments[0], long_margin_per_hand=None)

    plan = _STRATEGY.plan_alpha003_orders(replace(_risk_facts(), instruments=tuple(instruments)))

    assert plan.status == "BLOCKED"
    assert plan.reason == "INSTRUMENT_RISK_METADATA_UNAVAILABLE"
    assert plan.actions == ()


def test_risk_reduction_survives_missing_opening_capital_and_margin_facts():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    flat = replace(_risk_facts().positions[1], available_at=evaluated_at)
    instruments = list(_risk_facts().instruments)
    instruments[0] = replace(
        instruments[0],
        multiplier=None,
        long_margin_per_hand=None,
        short_margin_per_hand=None,
    )
    account = replace(
        _risk_facts().account,
        available_margin=None,
        used_margin=None,
        current_notional=None,
        current_worst_case_loss=None,
        cash=None,
        equity=None,
    )
    inputs = _genericize_target_exchange(
        replace(
            _risk_facts(),
            positions=(position, flat),
            instruments=tuple(instruments),
            account=account,
            target_decision=None,
            open_risk_ready=False,
            open_risk_blockers=("OPEN_CAPACITY_UNAVAILABLE",),
        )
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "READY"
    assert len(plan.actions) == 1
    assert plan.actions[0].position_effect == "CLOSE"
    assert plan.actions[0].reason == "MAX_HOLD"


def test_cancel_open_order_intent_keeps_original_owner_without_opening_policy_payload():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    pending = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        order_ref="intent-open-pending",
        broker_order_ref=47,
        state="ACCEPTED",
        side="BUY",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-pending",
    )
    planning = replace(
        _risk_facts(positions=(position, _risk_facts().positions[1]), orders=(pending,)),
        target_decision=None,
    )
    plan = _STRATEGY.plan_alpha003_orders(planning)
    assert plan.status == "READY"
    assert plan.actions[0].action == "CANCEL"
    assert plan.actions[0].position_effect == "OPEN"

    strategy = SimpleNamespace(_risk_policy=None)
    keys, economics = _STRATEGY.Alpha003TargetStrategy._order_intents(
        strategy, plan, SimpleNamespace(batch_id="batch-risk")
    )

    assert keys[0].action == "CANCEL"
    assert keys[0].position_effect == "OPEN"
    assert economics[0]["owner_intent_id"] == "intent-open-pending"
    assert economics[0]["order_ref"] == "intent-open-pending"
    assert "risk_policy_id" not in economics[0]


@pytest.mark.parametrize(
    "policy_changes, expected_reason",
    [
        ({"max_order_intents_per_grid": 1}, "ORDER_INTENT_BUDGET_EXCEEDED"),
        ({"max_total_margin": Decimal("150")}, "ACCOUNT_RISK_LIMIT"),
        ({"max_total_notional": Decimal("1000")}, "ACCOUNT_RISK_LIMIT"),
        ({"max_total_loss": Decimal("10")}, "ACCOUNT_RISK_LIMIT"),
    ],
)
def test_order_planner_refuses_new_risk_when_explicit_budgets_are_exceeded(
    policy_changes, expected_reason
):
    inputs = replace(_risk_facts(), risk_policy=_risk_policy(**policy_changes))

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "BLOCKED"
    assert plan.reason == expected_reason
    assert plan.actions == ()


@pytest.mark.parametrize(
    ("denial", "expected_reason"),
    (
        ("account_route", "ROUTE_NOT_AUTHORIZED"),
        ("instrument_route", "INSTRUMENT_NOT_AUTHORIZED"),
        ("instrument_trading", "INSTRUMENT_NOT_AUTHORIZED"),
    ),
)
def test_order_planner_never_opens_when_route_or_trading_permission_is_denied(
    denial, expected_reason
):
    inputs = _risk_facts()
    if denial == "account_route":
        inputs = replace(
            inputs,
            account=replace(inputs.account, route_permitted=False),
        )
    else:
        instrument = inputs.instruments[0]
        if denial == "instrument_route":
            instrument = replace(instrument, route_permitted=False)
        else:
            instrument = replace(instrument, trading_permitted=False)
        inputs = replace(inputs, instruments=(instrument,) + inputs.instruments[1:])

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "BLOCKED"
    assert plan.reason == expected_reason
    assert plan.actions == ()


def test_live_run_keeps_source_backed_owned_order_cancel_during_warmup_without_open_readiness():
    from contextlib import contextmanager
    from types import MethodType

    module_name = "_alpha003_source_backed_dated_facts_fixture"
    facts_fixture = sys.modules.get(module_name)
    if facts_fixture is None:
        path = _ROOT / "tests" / "unit" / "stores" / "test_factor_execution_facts.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        facts_fixture = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = facts_fixture
        spec.loader.exec_module(facts_fixture)

    now = datetime.now(UTC)
    remote_order = {
        "OrderRef": "94",
        "OrderSysID": "sys-94",
        "InstrumentID": facts_fixture._INSTRUMENT,
        "ExchangeID": facts_fixture._EXCHANGE,
        "OrderStatus": "3",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotal": "1",
        "FrontID": 4,
        "SessionID": 7,
    }
    api, store, broker, _journal, _source_coordinator, target = facts_fixture._system_under_test(
        now=now,
        rows=facts_fixture._query_rows(orders=(remote_order,)),
        tick=None,
    )
    receipt = facts_fixture._refresh_all(store, target)
    facts_fixture._arm(store)
    order = facts_fixture.BuyOrder(
        owner=None,
        data=target.data,
        size=1,
        price=100,
        exectype=facts_fixture.Order.Limit,
        simulated=True,
    )
    order.status = facts_fixture.Order.Accepted
    order.info.update(
        {
            "external_order_ref": "94",
            "order_sys_id": "sys-94",
            "instrument_id": facts_fixture._INSTRUMENT,
            "exchange_id": facts_fixture._EXCHANGE,
            "factor_position_effect": "OPEN",
            "factor_strategy_scope": "alpha003",
            "factor_intent_id": "intent-94",
            "front_id": 4,
            "session_id": 7,
            "execution_unknown": False,
            "cancel_requested_remote": False,
            "cancel_intent_active": False,
            "managed_execution_cancel_pending": False,
        }
    )
    broker.orders[order.ref] = order
    store._latest_ticks.clear()

    batch = SimpleNamespace(
        status="COMPLETE",
        batch_id="warmup-batch",
        cohort_id="cohort-1",
        calendar_id="simnow-common-minutes-v1",
        epoch_id=1,
        close_time=CLOSE,
        available_at=AVAILABLE,
    )
    snapshot = SimpleNamespace(
        readiness=LiveFactorReadiness.WARMUP,
        batch_complete=False,
    )
    scopes = []
    canceled = []

    class _Coordinator:
        def run_order_count(self):
            return 0

        def decision_scope(self, **_kwargs):
            pytest.fail("WARMUP must not dispatch a new OPEN grid decision")

        @contextmanager
        def risk_decision_scope(self, **kwargs):
            scopes.append(kwargs)
            yield SimpleNamespace(dispatch_allowed=True)

    strategy = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    strategy.p = SimpleNamespace(
        execution_enabled=True,
        replay_mode=False,
        cohort=SimpleNamespace(cohort_id=batch.cohort_id, current_batch=lambda: batch),
        control_refresh_loop=SimpleNamespace(last_receipt=receipt),
    )
    strategy.broker = broker
    strategy._coordinator = _Coordinator()
    strategy._risk_policy = _risk_policy()
    strategy._account_scope = "acct-scope"
    strategy._strategy_scope = "alpha003"
    strategy._logical_run_id = "run-1"
    strategy._routes = {target.target_id: (target.instrument, target.exchange)}
    strategy._target_ids = (target.target_id,)
    strategy._data_by_target = {target.target_id: target.data}
    strategy._orders_by_broker_ref = {}
    strategy._quote_max_age_seconds = None
    strategy._max_query_age_seconds = None
    strategy._last_signal_target = None
    strategy._live_shadow_order_count = 0
    strategy._shutdown_requested = Event()
    strategy.last_order_plan = None
    strategy.last_execution_facts = None
    strategy.last_execution_block_reason = None
    strategy.cancel = lambda candidate: canceled.append(candidate)
    strategy._record_decision_tape = lambda *_args: (True, None, None)
    strategy._find_order_object = MethodType(
        _STRATEGY.Alpha003TargetStrategy._find_order_object, strategy
    )
    strategy._order_intents = MethodType(_STRATEGY.Alpha003TargetStrategy._order_intents, strategy)
    strategy._dispatch_live_actions = MethodType(
        _STRATEGY.Alpha003TargetStrategy._dispatch_live_actions, strategy
    )

    _STRATEGY.Alpha003TargetStrategy._run_live(
        strategy,
        batch,
        snapshot,
        datetime.now(UTC),
        None,
        None,
        True,
        is_new_batch=True,
    )

    facts = strategy.last_execution_facts
    assert facts is not None
    assert tuple(query.family for query in facts.query_provenance) == (
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
        "instrument_margin_rate_result",
    )
    assert facts.open_risk_ready is False
    assert facts.order_cancel_ready is True, facts.order_cancel_blockers
    assert facts.account is not None and facts.account.route_permitted is True
    assert facts.working_orders[0].owner_strategy_scope == facts.strategy_scope
    assert facts.working_orders[0].owner_intent_id == "intent-94"
    assert api.query_calls

    assert strategy.last_order_plan.status == "READY"
    assert strategy.last_order_plan.reason == "CANCEL_OPEN_ORDERS_BEFORE_EXIT"
    assert len(strategy.last_order_plan.actions) == 1
    assert strategy.last_order_plan.actions[0].action == "CANCEL"
    assert len(scopes) == 1
    assert len(scopes[0]["intent_keys"]) == 1
    assert scopes[0]["intent_keys"][0].action == "CANCEL"
    assert scopes[0]["intent_keys"][0].position_effect == "OPEN"
    assert scopes[0]["economic_payload"]["intent_economics"][0]["owner_intent_id"] == ("intent-94")
    assert canceled == [order]


def test_reduction_is_submitted_alone_before_any_new_target_is_opened():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    positions = (
        _STRATEGY.Alpha003PositionFact(
            target_id="A",
            instrument="SHFE.rb",
            exchange="SHFE",
            quantity=-1,
            snapshot_id="positions-1",
            available_at=evaluated_at,
            owner_strategy_scope="alpha003-simnow-example",
            owner_intent_id="intent-open-A",
            average_price=Decimal("101"),
            stop_price=Decimal("105"),
            held_eligible_bars=1,
        ),
        _STRATEGY.Alpha003PositionFact(
            target_id="B",
            instrument="DCE.i",
            exchange="DCE",
            quantity=0,
            snapshot_id="positions-1",
            available_at=evaluated_at,
        ),
    )
    plan = _STRATEGY.plan_alpha003_orders(
        _genericize_target_exchange(_risk_facts(positions=positions))
    )

    assert plan.status == "READY"
    assert plan.reason == "REDUCTIONS_BEFORE_INCREASES"
    assert len(plan.actions) == 1
    assert (
        plan.actions[0].action,
        plan.actions[0].target_id,
        plan.actions[0].side,
        plan.actions[0].position_effect,
        plan.actions[0].quantity,
        plan.actions[0].offset,
    ) == ("SUBMIT", "A", "BUY", "CLOSE", 1, "close")
    assert plan.actions[0].owner_intent_id == "intent-open-A"


def test_unquoted_existing_position_freezes_a_new_target_increase():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=1,
    )
    flat = replace(_risk_facts().positions[1], available_at=evaluated_at)

    plan = _STRATEGY.plan_alpha003_orders(
        _risk_facts(
            positions=(position, flat),
            quotes=(_quote("DCE.i"),),
        )
    )

    assert plan.status == "BLOCKED"
    assert plan.reason == "OPEN_POSITION_QUOTE_UNAVAILABLE"
    assert plan.actions == ()


def test_unknown_working_intent_freezes_all_new_risk():
    unknown = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        order_ref="order-unknown",
        state="UNKNOWN",
        side="SELL",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-unknown",
    )

    plan = _STRATEGY.plan_alpha003_orders(_risk_facts(orders=(unknown,)))

    assert plan.status == "BLOCKED"
    assert plan.reason == "UNRESOLVED_INTENT_BLOCKS_NEW_RISK"
    assert plan.actions == ()


def test_missing_risk_inputs_block_writes_but_leave_factor_selection_available():
    inputs = replace(_risk_facts(), risk_policy=None)

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "BLOCKED"
    assert plan.reason == "RISK_POLICY_REQUIRED"
    assert plan.actions == ()
    assert inputs.target_decision.status == "TARGETS_READY"


@pytest.mark.parametrize(
    ("used", "expected_status", "expected_reason"),
    (
        # Two proposed opens cost two immediate SUBMITs, two future CANCELs,
        # and one first CLOSE per possible position. No reserve is charged to
        # the durable count; used=14 is the last count that admits both.
        (14, "READY", None),
        (15, "BLOCKED", "RUN_ORDER_BUDGET_EXCEEDED"),
        (None, "BLOCKED", "RUN_ORDER_BUDGET_UNAVAILABLE"),
    ),
)
def test_opening_plan_reserves_bounded_exit_capacity_from_durable_run_budget(
    used, expected_status, expected_reason
):
    inputs = replace(_risk_facts(), run_order_intents_used=used)

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == expected_status
    if expected_reason is None:
        assert len(plan.actions) == 2
    else:
        assert plan.reason == expected_reason
        assert plan.actions == ()


@pytest.mark.parametrize(("limit", "used", "expected_status"), ((3, 0, "BLOCKED"), (4, 0, "READY")))
def test_one_shfe_open_reserves_cancel_and_first_close_for_each_exposure(
    limit, used, expected_status
):
    # Keep a valid two-extrema Alpha003 decision. B already holds its desired
    # short, leaving one new SHFE long leg while still reserving B's exit.
    decision = _target_decision()
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    held_b = _STRATEGY.Alpha003PositionFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        quantity=-1,
        snapshot_id="positions-existing-B",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-B",
        average_price=Decimal("100"),
        stop_price=Decimal("101"),
        held_eligible_bars=1,
    )
    facts = _risk_facts(
        positions=(
            _STRATEGY.Alpha003PositionFact(
                target_id="A",
                instrument="SHFE.rb",
                exchange="SHFE",
                quantity=0,
                snapshot_id="positions-existing-B",
                available_at=evaluated_at,
            ),
            held_b,
        ),
        account_changes={
            "available_margin": Decimal("900"),
            "used_margin": Decimal("100"),
            "current_notional": Decimal("1000"),
            "current_worst_case_loss": Decimal("11"),
        },
    )
    inputs = replace(
        facts,
        target_decision=decision,
        risk_policy=_risk_policy(max_order_intents_per_run=limit),
        run_order_intents_used=used,
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == expected_status
    if expected_status == "READY":
        assert len(plan.actions) == 1
        assert plan.actions[0].exchange == "SHFE"
    else:
        assert plan.reason == "RUN_ORDER_BUDGET_EXCEEDED"
        assert plan.actions == ()


def test_active_partial_open_and_new_open_reserve_their_full_possible_disposition():
    pending = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        order_ref="order-open-B",
        state="PARTIAL",
        side="SELL",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-B",
    )
    inputs = replace(
        _risk_facts(orders=(pending,)),
        order_cancel_ready=True,
        run_order_intents_used=15,
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    # B's in-flight OPEN retains 1 CANCEL + 1 CLOSE capacity. The proposed A
    # OPEN needs its own SUBMIT + 1 CANCEL + 1 CLOSE capacity: 15 + 5 = 20.
    assert plan.status == "READY"
    assert tuple(action.target_id for action in plan.actions) == ("A",)

    over_budget = _STRATEGY.plan_alpha003_orders(replace(inputs, run_order_intents_used=16))
    assert over_budget.status == "BLOCKED"
    assert over_budget.reason == "RUN_ORDER_BUDGET_EXCEEDED"
    assert over_budget.actions == ()


def test_last_budget_admitted_opens_leave_room_for_close_all_and_reserve_is_not_charged():
    opening = replace(_risk_facts(), run_order_intents_used=14)

    first_plan = _STRATEGY.plan_alpha003_orders(opening)
    repeated_same_count = _STRATEGY.plan_alpha003_orders(
        replace(opening, run_order_intents_used=14)
    )

    assert first_plan.status == "READY"
    assert len(first_plan.actions) == 2
    assert repeated_same_count == first_plan
    assert opening.run_order_intents_used == 14

    evaluated_at = opening.evaluated_at
    positions = (
        _STRATEGY.Alpha003PositionFact(
            target_id="A",
            instrument="SHFE.rb",
            exchange="SHFE",
            quantity=1,
            snapshot_id="positions-after-open",
            available_at=evaluated_at,
            owner_strategy_scope=opening.strategy_scope,
            owner_intent_id="intent-open-A",
            average_price=Decimal("100"),
            stop_price=Decimal("99"),
            held_eligible_bars=0,
        ),
        _STRATEGY.Alpha003PositionFact(
            target_id="B",
            instrument="DCE.i",
            exchange="DCE",
            quantity=-1,
            snapshot_id="positions-after-open",
            available_at=evaluated_at,
            owner_strategy_scope=opening.strategy_scope,
            owner_intent_id="intent-open-B",
            average_price=Decimal("100"),
            stop_price=Decimal("101"),
            held_eligible_bars=0,
        ),
    )
    closing = _genericize_target_exchange(
        replace(
            _risk_facts(positions=positions),
            target_decision=None,
            run_end=True,
            run_order_intents_used=16,
        )
    )

    close_plan = _STRATEGY.plan_alpha003_orders(closing)

    assert close_plan.status == "READY"
    assert len(close_plan.actions) == 2
    assert all(action.position_effect == "CLOSE" for action in close_plan.actions)
    assert {action.target_id for action in close_plan.actions} == {"A", "B"}


@pytest.mark.parametrize(("used", "expected_status"), ((19, "READY"), (20, "BLOCKED")))
def test_reduction_plan_obeys_the_same_durable_run_order_budget(used, expected_status):
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    flat = _STRATEGY.Alpha003PositionFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        quantity=0,
        snapshot_id="positions-1",
        available_at=evaluated_at,
    )
    inputs = _genericize_target_exchange(
        replace(
            _risk_facts(positions=(position, flat)),
            target_decision=None,
            run_order_intents_used=used,
        )
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == expected_status
    if expected_status == "READY":
        assert len(plan.actions) == 1
        assert plan.actions[0].position_effect == "CLOSE"
    else:
        assert plan.reason == "RUN_ORDER_BUDGET_EXCEEDED"
        assert plan.actions == ()


@pytest.mark.parametrize(("used", "expected_status"), ((18, "READY"), (19, "BLOCKED")))
def test_close_preserves_first_exit_capacity_for_another_owned_position(used, expected_status):
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    positions = (
        _STRATEGY.Alpha003PositionFact(
            target_id="A",
            instrument="SHFE.rb",
            exchange="SHFE",
            quantity=1,
            snapshot_id="positions-two-owned",
            available_at=evaluated_at,
            owner_strategy_scope="alpha003-simnow-example",
            owner_intent_id="intent-open-A",
            average_price=Decimal("100"),
            stop_price=Decimal("95"),
            held_eligible_bars=12,
        ),
        _STRATEGY.Alpha003PositionFact(
            target_id="B",
            instrument="DCE.i",
            exchange="DCE",
            quantity=-1,
            snapshot_id="positions-two-owned",
            available_at=evaluated_at,
            owner_strategy_scope="alpha003-simnow-example",
            owner_intent_id="intent-open-B",
            average_price=Decimal("100"),
            stop_price=Decimal("101"),
            held_eligible_bars=0,
        ),
    )
    inputs = _genericize_target_exchange(
        replace(
            _risk_facts(positions=positions),
            target_decision=None,
            run_order_intents_used=used,
        )
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == expected_status
    if expected_status == "READY":
        assert len(plan.actions) == 1
        assert plan.actions[0].target_id == "A"
        assert plan.actions[0].position_effect == "CLOSE"
    else:
        assert plan.reason == "RUN_ORDER_BUDGET_EXCEEDED"
        assert plan.actions == ()


@pytest.mark.parametrize(("used", "expected_status"), ((17, "READY"), (18, "BLOCKED")))
def test_exit_cancel_reserves_first_close_for_possible_fill_and_other_position(
    used, expected_status
):
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    held_b = _STRATEGY.Alpha003PositionFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        quantity=-1,
        snapshot_id="positions-pending-open",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-B",
        average_price=Decimal("100"),
        stop_price=Decimal("101"),
        held_eligible_bars=0,
    )
    pending_a = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        order_ref="pending-open-A",
        state="ACCEPTED",
        side="BUY",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
    )
    inputs = replace(
        _risk_facts(
            positions=(
                _STRATEGY.Alpha003PositionFact(
                    target_id="A",
                    instrument="SHFE.rb",
                    exchange="SHFE",
                    quantity=0,
                    snapshot_id="positions-pending-open",
                    available_at=evaluated_at,
                ),
                held_b,
            ),
            orders=(pending_a,),
        ),
        target_decision=None,
        run_end=True,
        order_cancel_ready=True,
        run_order_intents_used=used,
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == expected_status
    if expected_status == "READY":
        assert len(plan.actions) == 1
        assert (plan.actions[0].target_id, plan.actions[0].action) == ("A", "CANCEL")

        # After the charged cancel is terminal and A is confirmed flat, B's
        # still-owned CLOSE consumes the preserved remaining run capacity.
        after_cancel = replace(
            inputs,
            working_orders=(),
            run_order_intents_used=used + 1,
        )
        close_plan = _STRATEGY.plan_alpha003_orders(after_cancel)
        assert close_plan.status == "READY"
        assert len(close_plan.actions) == 1
        assert (close_plan.actions[0].target_id, close_plan.actions[0].position_effect) == (
            "B",
            "CLOSE",
        )
    else:
        assert plan.reason == "RUN_ORDER_BUDGET_EXCEEDED"
        assert plan.actions == ()


def test_maximum_hold_and_run_end_apply_independent_of_signal_availability():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    flat = _STRATEGY.Alpha003PositionFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        quantity=0,
        snapshot_id="positions-1",
        available_at=evaluated_at,
    )
    inputs = _genericize_target_exchange(
        replace(
            _risk_facts(
                positions=(position, flat),
                quotes=(_quote("SHFE.rb", bid="99.5"), _quote("DCE.i")),
            ),
            target_decision=None,
        )
    )
    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "READY"
    assert len(plan.actions) == 1
    assert plan.actions[0].reason == "MAX_HOLD"
    assert plan.actions[0].position_effect == "CLOSE"
    assert plan.actions[0].side == "SELL"

    run_end = replace(inputs, run_end=True)
    run_end_plan = _STRATEGY.plan_alpha003_orders(run_end)
    assert run_end_plan.status == "READY"
    assert run_end_plan.actions[0].reason == "RUN_END"


@pytest.mark.parametrize(
    ("run_end", "order_state"),
    ((True, "ACCEPTED"), (False, "PARTIAL")),
)
def test_flat_pending_open_is_cancelled_before_run_end_or_preclose_without_quote_facts(
    run_end, order_state
):
    base = _risk_facts()
    order = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        order_ref="ctp-order-ref-17",
        broker_order_ref=17,
        state=order_state,
        side="BUY",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
    )
    inputs = replace(
        base,
        account=None,
        quotes=(),
        working_orders=(order,),
        target_decision=None,
        run_end=run_end,
        session_close_at=(
            base.evaluated_at + timedelta(seconds=60) if not run_end else base.session_close_at
        ),
        risk_reduction_ready=False,
        risk_reduction_blockers=("QUOTE_UNAVAILABLE",),
        order_cancel_ready=True,
        order_cancel_blockers=(),
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "READY"
    assert plan.reason == "CANCEL_OPEN_ORDERS_BEFORE_EXIT"
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.action == "CANCEL"
    assert action.position_effect == "OPEN"
    assert action.owner_intent_id == "intent-open-A"
    assert action.order_ref == "ctp-order-ref-17"
    assert action.broker_order_ref == 17


def test_unknown_pending_open_blocks_run_end_instead_of_claiming_flat():
    order = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        order_ref="ctp-order-ref-unknown",
        broker_order_ref=18,
        state="UNKNOWN",
        side="BUY",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
    )
    inputs = replace(
        _risk_facts(orders=(order,)),
        run_end=True,
        target_decision=None,
        order_cancel_ready=True,
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "BLOCKED"
    assert plan.reason == "EXIT_ORDER_TERMINAL_EVIDENCE_PENDING"
    assert plan.actions == ()


def test_unowned_pending_open_blocks_exit_cancellation():
    order = _STRATEGY.Alpha003WorkingOrderFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        order_ref="external-order-19",
        broker_order_ref=19,
        state="ACCEPTED",
        side="BUY",
        position_effect="OPEN",
        remaining_quantity=1,
        owner_strategy_scope=None,
        owner_intent_id=None,
    )

    plan = _STRATEGY.plan_alpha003_orders(
        replace(_risk_facts(orders=(order,)), run_end=True, target_decision=None)
    )

    assert plan.status == "BLOCKED"
    assert plan.reason == "UNOWNED_WORKING_ORDER"
    assert plan.actions == ()


def test_missing_final_batch_evidence_blocks_new_risk(monkeypatch):
    planning = _risk_facts()
    close_at = planning.session_close_at
    monkeypatch.setattr(
        _STRATEGY,
        "_session_close_from_batch",
        lambda *_args, **_kwargs: (close_at, None),
    )
    for cohort, expected_reason in (
        (SimpleNamespace(), "FINAL_BATCH_EVIDENCE_UNAVAILABLE"),
        (
            SimpleNamespace(
                is_final_batch=lambda _batch: (_ for _ in ()).throw(OSError("calendar"))
            ),
            "FINAL_BATCH_EVIDENCE_INVALID",
        ),
        (SimpleNamespace(is_final_batch=lambda _batch: 1), "FINAL_BATCH_EVIDENCE_INVALID"),
    ):
        strategy = SimpleNamespace(
            p=SimpleNamespace(cohort=cohort),
            _data_by_target={},
            _product_keys={},
            _routes={},
            _session_calendars={},
        )
        # Session-close projection is pinned to an explicit source result;
        # this test isolates the independent cohort final-slot gate.
        _close, run_end, reason = _STRATEGY.Alpha003TargetStrategy._session_facts(
            strategy, object()
        )

        assert run_end is False
        assert reason == expected_reason
        plan = _STRATEGY.plan_alpha003_orders(replace(planning, execution_blockers=(reason,)))
        assert plan.status == "BLOCKED"
        assert plan.reason == "EXECUTION_FACTS_BLOCKED:" + expected_reason
        assert plan.actions == ()


def test_tape_failure_keeps_cancel_and_close_but_suppresses_open():
    open_action = _STRATEGY.Alpha003OrderAction(
        action="SUBMIT",
        target_id="A",
        instrument="SHFE.rb",
        side="BUY",
        position_effect="OPEN",
        quantity=1,
        limit_price=Decimal("100"),
        offset="open",
        reason="ALPHA003_TARGET",
        exchange="SHFE",
        decision_available_at=AVAILABLE,
        planned_stop_price=Decimal("99"),
        entry_grid_ordinal=5,
    )
    cancel_action = replace(
        open_action,
        action="CANCEL",
        reason="RUN_END_CANCEL_PENDING_OPEN",
        order_ref="remote-1",
        owner_intent_id="intent-open-A",
        broker_order_ref=1,
    )
    close_action = replace(
        open_action,
        target_id="B",
        instrument="DCE.i",
        side="SELL",
        position_effect="CLOSE",
        offset="close",
        reason="MAX_HOLD",
        planned_stop_price=None,
        owner_intent_id="intent-open-B",
        exchange="DCE",
        entry_grid_ordinal=None,
    )
    plan = _STRATEGY.Alpha003OrderPlan(
        "READY", None, (open_action, cancel_action, close_action), "batch-1", AVAILABLE, "account-1"
    )

    gated = _STRATEGY.Alpha003TargetStrategy._gate_open_actions(plan, tape_durable=False)

    assert gated.status == "READY"
    assert gated.reason == "OPEN_SUPPRESSED_DECISION_TAPE"
    assert gated.actions == (cancel_action, close_action)


def test_final_replay_residual_position_is_explicitly_blocked():
    feed = object()

    class _Broker:
        def getposition(self, _data):
            return SimpleNamespace(size=1)

        def get_orders_open(self, *, safe):
            assert safe is False
            return []

    strategy = SimpleNamespace(
        _shutdown_requested=Event(),
        _shutdown_ready_state=False,
        _shutdown_blocker_state=None,
        _target_ids=("A",),
        _data_by_target={"A": feed},
        _replay_owners={"A": {"owner_intent_id": "replay-owner-A", "stop_price": Decimal("95")}},
        _risk_policy=_risk_policy(run_end_policy="CLOSE_ALL"),
        _routes={"A": ("SHFE.rb", "SHFE")},
        _strategy_scope="alpha003-simnow-example",
        broker=_Broker(),
    )
    strategy._shutdown_requested.set()

    _STRATEGY.Alpha003TargetStrategy._update_replay_shutdown_state(strategy)

    assert strategy._shutdown_ready_state is False
    assert strategy._shutdown_blocker_state == "REPLAY_SHUTDOWN_POSITION_OPEN:A"


@pytest.mark.parametrize("ready", (True, False))
def test_notify_idle_requests_public_engine_stop_only_after_shutdown_ready(ready):
    calls = []
    strategy = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    strategy.p = SimpleNamespace(replay_mode=False)
    strategy._shutdown_requested = Event()
    strategy._shutdown_requested.set()
    strategy._shutdown_ready_state = False
    strategy._shutdown_engine_stop_requested = False
    strategy._shutdown_blocker_state = "SHUTDOWN_REQUESTED_PENDING_ENGINE"
    strategy._clock_now = lambda: AVAILABLE
    strategy._last_session_close_at = None
    strategy.cerebro = SimpleNamespace(runstop=lambda: calls.append("runstop"))

    def refresh_shutdown(*_args, **_kwargs):
        strategy._shutdown_ready_state = ready
        strategy._shutdown_blocker_state = None if ready else "SHUTDOWN_FACTS_UNAVAILABLE"

    strategy._run_live = refresh_shutdown

    _STRATEGY.Alpha003TargetStrategy.notify_idle(strategy)

    assert calls == (["runstop"] if ready else [])
    assert strategy._shutdown_engine_stop_requested is ready
    assert strategy.shutdown_ready is ready


def test_missing_round_trip_fee_bound_blocks_new_open_but_keeps_risk_reductions():
    opening = replace(
        _risk_facts(),
        risk_policy=_risk_policy(round_trip_fee_upper_bound_per_contract=None),
    )
    opening_plan = _STRATEGY.plan_alpha003_orders(opening)
    assert opening_plan.status == "BLOCKED"
    assert opening_plan.reason == "ROUND_TRIP_FEE_BUDGET_UNAVAILABLE"
    assert opening_plan.actions == ()

    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    flat = _STRATEGY.Alpha003PositionFact(
        target_id="B",
        instrument="DCE.i",
        exchange="DCE",
        quantity=0,
        snapshot_id="positions-1",
        available_at=evaluated_at,
    )
    closing = _genericize_target_exchange(
        replace(
            _risk_facts(positions=(position, flat)),
            target_decision=None,
            risk_policy=_risk_policy(round_trip_fee_upper_bound_per_contract=None),
        )
    )
    closing_plan = _STRATEGY.plan_alpha003_orders(closing)
    assert closing_plan.status == "READY"
    assert len(closing_plan.actions) == 1
    assert closing_plan.actions[0].position_effect == "CLOSE"
    assert closing_plan.actions[0].reason == "MAX_HOLD"


def test_round_trip_fee_upper_bound_is_included_in_opening_loss_budget():
    plan = _STRATEGY.plan_alpha003_orders(_risk_facts())

    assert plan.status == "READY"
    assert len(plan.actions) == 2
    # Each stop-distance loss is 10; the explicit fee reserve adds 1.
    policy = _risk_policy()
    per_position_loss = (
        plan.actions[0].limit_price - plan.actions[0].planned_stop_price
    ) * Decimal(10) + policy.round_trip_fee_upper_bound_per_contract
    assert per_position_loss == Decimal("11")


def test_unknown_run_end_policy_is_rejected_instead_of_becoming_a_write_default():
    values = {
        "risk_policy_id": "alpha003-example-risk-v1",
        "max_hold_eligible_bars": 12,
        "preclose_grace_seconds": 60,
        "run_end_policy": "",
        "quote_max_age_seconds": Decimal("5"),
        "max_state_age_seconds": Decimal("30"),
        "max_notional_per_position": Decimal("2000"),
        "max_total_notional": Decimal("3000"),
        "max_margin_per_position": Decimal("250"),
        "max_total_margin": Decimal("500"),
        "max_loss_per_position": Decimal("20"),
        "max_total_loss": Decimal("40"),
        "stop_loss_ticks": 2,
        "max_order_intents_per_grid": 2,
        "max_order_intents_per_run": 20,
    }

    with pytest.raises(ValueError, match="run_end_policy"):
        _STRATEGY.Alpha003RiskPolicy(**values)


@pytest.mark.parametrize("grace_seconds", (0, 60))
def test_risk_policy_mapping_matches_typed_policy_for_preclose_grace(grace_seconds):
    typed = _risk_policy(preclose_grace_seconds=grace_seconds)
    mapping = {name: getattr(typed, name) for name in typed.__dataclass_fields__}

    parsed = _STRATEGY._risk_policy(mapping)

    assert parsed == typed
    assert type(parsed.preclose_grace_seconds) is int
    assert parsed.preclose_grace_seconds == grace_seconds


@pytest.mark.parametrize("grace_seconds", (True, 1.5, -1))
def test_risk_policy_mapping_rejects_invalid_preclose_grace_types_and_values(
    grace_seconds,
):
    typed = _risk_policy()
    mapping = {name: getattr(typed, name) for name in typed.__dataclass_fields__}
    mapping["preclose_grace_seconds"] = grace_seconds

    with pytest.raises(ValueError, match="preclose_grace_seconds"):
        _STRATEGY._risk_policy(mapping)


def test_stop_joins_control_refresh_before_base_strategy_stop(monkeypatch):
    calls = []
    refresh_loop = SimpleNamespace(stop_and_join=lambda: calls.append("refresh"))
    strategy = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    strategy.p = SimpleNamespace(control_refresh_loop=refresh_loop)
    strategy._control_refresh_stopped = False
    strategy._shutdown_requested = Event()
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: calls.append("base"))

    _STRATEGY.Alpha003TargetStrategy.stop(strategy)
    _STRATEGY.Alpha003TargetStrategy.stop(strategy)

    assert calls == ["refresh", "base", "base"]


def test_strategy_stop_propagates_refresh_join_failure_without_base_stop(monkeypatch):
    calls = []

    def fail_to_join():
        calls.append("join")
        raise RuntimeError("refresh loop still active")

    strategy = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    strategy.p = SimpleNamespace(control_refresh_loop=SimpleNamespace(stop_and_join=fail_to_join))
    strategy._control_refresh_stopped = False
    strategy._shutdown_requested = Event()
    strategy._shutdown_requested.set()
    strategy._shutdown_ready_state = True
    strategy._shutdown_blocker_state = None
    strategy._shutdown_post_join_confirmed_state = False
    strategy._shutdown_post_join_blocker_state = "SHUTDOWN_POST_JOIN_CONFIRMATION_PENDING"
    strategy._confirm_shutdown_post_join = lambda: calls.append("confirm")
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: calls.append("base"))

    with pytest.raises(RuntimeError, match="still active"):
        _STRATEGY.Alpha003TargetStrategy.stop(strategy)

    assert calls == ["join"]
    assert strategy._control_refresh_stopped is False
    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker == "SHUTDOWN_REFRESH_JOIN_FAILED"
    assert strategy.shutdown_post_join_confirmed is False
    assert strategy.shutdown_post_join_blocker == "SHUTDOWN_REFRESH_JOIN_FAILED"


def test_cerebro_refresh_join_failure_skips_broker_and_store_teardown():
    calls = []

    class _RefreshLoop:
        def stop_and_join(self):
            calls.append("refresh.join")
            raise RuntimeError("refresh loop still active")

    class _Store:
        def start(self):
            calls.append("store.start")

        def stop(self):
            calls.append("store.stop")

    class _JoinFailureStrategy(_STRATEGY.Alpha003TargetStrategy):
        def __init__(self):
            self._control_refresh_stopped = False
            self._shutdown_requested = Event()
            self._shutdown_requested.set()
            self._shutdown_ready_state = True
            self._shutdown_blocker_state = None
            self._shutdown_post_join_confirmed_state = False
            self._shutdown_post_join_blocker_state = "SHUTDOWN_POST_JOIN_CONFIRMATION_PENDING"

        def prenext(self):
            pass

        def nextstart(self):
            pass

        def next(self):
            pass

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    broker = bt.BackBroker()
    broker.stop = lambda: calls.append("broker.stop")
    cerebro.setbroker(broker)
    cerebro.addstore(_Store())

    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=pd.DatetimeIndex([datetime(2026, 1, 5, 9, 1)]),
    )
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="target")
    cerebro.addstrategy(
        _JoinFailureStrategy,
        control_refresh_loop=_RefreshLoop(),
    )

    with pytest.raises(RuntimeError, match="refresh loop still active"):
        cerebro.run()

    assert calls == ["store.start", "refresh.join"]


def test_refresh_loop_stop_failure_does_not_claim_shutdown_completed():
    def fail_to_join():
        raise RuntimeError("refresh loop still active")

    strategy = SimpleNamespace(
        p=SimpleNamespace(control_refresh_loop=SimpleNamespace(stop_and_join=fail_to_join)),
        _control_refresh_stopped=False,
    )

    with pytest.raises(RuntimeError, match="still active"):
        _STRATEGY.Alpha003TargetStrategy._stop_control_refresh_loop(strategy)

    assert strategy._control_refresh_stopped is False


@pytest.mark.parametrize(
    ("position_date", "partial_close", "expected_offset", "expected_offset_flag"),
    (
        ("TODAY", False, "close_today", "3"),
        ("TODAY", True, "close_today", "3"),
        ("HISTORY", False, "close_yesterday", "4"),
    ),
)
def test_source_backed_dated_position_produces_exact_close_leg_and_broker_order(
    position_date, partial_close, expected_offset, expected_offset_flag
):
    facts, live = _source_backed_dated_close_facts(position_date, partial_close=partial_close)
    planning = _dated_source_planning_input(facts, live["now"])

    plan = _STRATEGY.plan_alpha003_orders(planning)

    assert plan.status == "READY"
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert (
        action.target_id,
        action.instrument,
        action.exchange,
        action.side,
        action.position_effect,
        action.quantity,
        action.offset,
        action.position_date,
        action.offset_flag,
        action.hedge_flag,
    ) == (
        "rb",
        "rb2510",
        "SHFE",
        "SELL",
        "CLOSE",
        1,
        expected_offset,
        position_date,
        expected_offset_flag,
        "1",
    )
    assert action.dated_query_set_id == facts.query_set_id
    assert action.dated_snapshot_id == facts.snapshot_id
    assert action.dated_source_row_ids == facts.dated_close_legs[0].source_row_ids
    assert action.dated_opening_execution_ids == facts.dated_close_legs[0].opening_execution_ids
    assert action.quantity == abs(facts.positions[0].quantity)
    if partial_close:
        assert facts.positions[0].quantity == Decimal("1")
        assert facts.dated_close_legs[0].close_execution_ids

    batch = SimpleNamespace(batch_id="dated-close-batch")
    strategy = SimpleNamespace(_risk_policy=_risk_policy())
    keys, economics = _STRATEGY.Alpha003TargetStrategy._order_intents(strategy, plan, batch)
    assert len(keys) == len(economics) == 1
    assert keys[0].action == "SUBMIT"
    assert keys[0].instrument == "rb2510"
    assert keys[0].side == "SELL"
    assert keys[0].position_effect == "CLOSE"
    assert economics[0]["offset"] == expected_offset
    assert economics[0]["position_date"] == position_date
    assert economics[0]["offset_flag"] == expected_offset_flag
    assert economics[0]["hedge_flag"] == "1"
    assert economics[0]["owner_intent_id"] == facts.positions[0].owner_intent_id
    assert economics[0]["owner_side"] == "BUY"
    assert economics[0]["owner_position_effect"] == "OPEN"
    assert economics[0]["query_set_id"] == facts.query_set_id
    assert economics[0]["snapshot_id"] == facts.snapshot_id
    assert economics[0]["source_row_ids"] == action.dated_source_row_ids
    assert economics[0]["opening_execution_ids"] == action.dated_opening_execution_ids

    observed = []
    data = object()

    def sell(**kwargs):
        observed.append(kwargs)

    dispatch_owner = SimpleNamespace(
        _data_by_target={"rb": data},
        _strategy_scope=facts.strategy_scope,
        _orders_by_broker_ref={},
        sell=sell,
    )
    _STRATEGY.Alpha003TargetStrategy._dispatch_live_actions(dispatch_owner, plan.actions, batch)
    assert len(observed) == 1
    assert observed[0]["data"] is data
    assert observed[0]["offset"] == expected_offset
    assert observed[0]["position_side"] == "long"
    assert observed[0]["hedge_flag"] == "1"
    assert observed[0]["position_date"] == position_date
    assert observed[0]["offset_flag"] == expected_offset_flag
    assert observed[0]["factor_owner_side"] == economics[0]["owner_side"]
    assert observed[0]["factor_owner_position_effect"] == economics[0]["owner_position_effect"]
    assert observed[0]["factor_dated_query_set_id"] == facts.query_set_id
    assert observed[0]["factor_dated_source_row_ids"] == action.dated_source_row_ids


def test_generic_dce_close_dispatch_matches_owner_intent_economics():
    base = _risk_facts()
    owned = replace(
        base.positions[0],
        quantity=1,
        owner_strategy_scope=base.strategy_scope,
        owner_intent_id="intent-open-dce-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    planning = _genericize_target_exchange(
        replace(
            base,
            positions=(owned, base.positions[1]),
            target_decision=None,
            run_end=True,
        )
    )

    plan = _STRATEGY.plan_alpha003_orders(planning)

    assert plan.status == "READY"
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert (action.exchange, action.position_effect, action.side, action.position_date) == (
        "DCE",
        "CLOSE",
        "SELL",
        None,
    )
    strategy = SimpleNamespace(_risk_policy=_risk_policy())
    keys, economics = _STRATEGY.Alpha003TargetStrategy._order_intents(
        strategy, plan, SimpleNamespace(batch_id="generic-close-batch")
    )
    assert len(keys) == len(economics) == 1
    assert economics[0]["owner_intent_id"] == "intent-open-dce-A"
    assert economics[0]["owner_side"] == "BUY"
    assert economics[0]["owner_position_effect"] == "OPEN"

    observed = []
    data = object()
    dispatch_owner = SimpleNamespace(
        _data_by_target={"A": data},
        _strategy_scope=planning.strategy_scope,
        _orders_by_broker_ref={},
        sell=lambda **kwargs: observed.append(kwargs),
    )
    _STRATEGY.Alpha003TargetStrategy._dispatch_live_actions(
        dispatch_owner, plan.actions, SimpleNamespace(batch_id="generic-close-batch")
    )

    assert len(observed) == 1
    order_info = observed[0]
    assert order_info["factor_owner_side"] == economics[0]["owner_side"]
    assert order_info["factor_owner_position_effect"] == economics[0]["owner_position_effect"]
    assert order_info["instrument_id"] == economics[0]["instrument_id"]
    assert order_info["exchange_id"] == economics[0]["exchange"] == "DCE"
    assert "position_date" not in order_info
    assert "offset_flag" not in order_info
    assert "hedge_flag" not in order_info


def test_exhausted_run_budget_keeps_owned_residual_not_flat():
    """Planner/shutdown unit: a terminal close remainder cannot be reported flat."""
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    original = _risk_facts()
    residual = replace(
        original.positions[0],
        quantity=1,
        available_at=evaluated_at,
        owner_strategy_scope=original.strategy_scope,
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    policy = _risk_policy()
    planning = _genericize_target_exchange(
        replace(
            original,
            positions=(residual, replace(original.positions[1], available_at=evaluated_at)),
            risk_policy=policy,
            target_decision=None,
            run_end=True,
            run_order_intents_used=policy.max_order_intents_per_run,
        )
    )
    plan = _STRATEGY.plan_alpha003_orders(planning)

    assert plan.status == "BLOCKED"
    assert plan.reason == "RUN_ORDER_BUDGET_EXCEEDED"
    assert plan.actions == ()

    projected_facts, live = _source_backed_dated_close_facts("TODAY")
    target = live["target"]
    assert projected_facts.read_only_reconciliation_ready is True
    assert projected_facts.positions[0].quantity == Decimal("1")
    account_scope = projected_facts.account_scope
    strategy = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    strategy._shutdown_requested = Event()
    strategy._shutdown_requested.set()
    strategy._shutdown_ready_state = False
    strategy._shutdown_blocker_state = None
    strategy._account_scope = account_scope
    strategy._strategy_scope = projected_facts.strategy_scope
    strategy._target_ids = (target.target_id,)
    strategy._risk_policy = policy
    strategy._routes = {target.target_id: (target.instrument, target.exchange)}

    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(strategy, projected_facts, plan)

    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker == "SHUTDOWN_OWNED_POSITION_OPEN:" + target.target_id


def _source_backed_read_only_reconciliation_case(scenario="positive"):
    """Use the facts suite's real Store/Broker/coordinator/query projection."""

    module_name = "_alpha003_source_backed_dated_facts_fixture"
    module = sys.modules.get(module_name)
    if module is None:
        path = _ROOT / "tests" / "unit" / "stores" / "test_factor_execution_facts.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("read-only reconciliation source fixture is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    if scenario == "owned_nonflat":
        builder = getattr(module, "_build_source_backed_dated_close_facts", None)
        if not callable(builder):
            raise RuntimeError("source-backed nonflat fixture is unavailable")
        facts, inputs = builder()
        return SimpleNamespace(
            facts=facts,
            target=inputs["target"],
            broker=inputs["broker"],
            store=inputs["store"],
            journal=inputs["journal"],
            api=inputs["api"],
            receipt=inputs["query_receipt"],
            now=inputs["now"],
        )
    builder = getattr(module, "_build_source_backed_read_only_reconciliation_case", None)
    if not callable(builder):
        raise RuntimeError("read-only reconciliation source fixture is not available yet")
    return builder(scenario=scenario)


def _shutdown_strategy_for_facts(facts, target, *, policy=None):
    strategy = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    strategy._shutdown_requested = Event()
    strategy._shutdown_requested.set()
    strategy._shutdown_ready_state = False
    strategy._shutdown_blocker_state = None
    strategy._account_scope = facts.account_scope
    strategy._strategy_scope = facts.strategy_scope
    strategy._target_ids = (target.target_id,)
    strategy._risk_policy = policy or _risk_policy(run_end_policy="CLOSE_ALL")
    strategy._routes = {target.target_id: (target.instrument, target.exchange)}
    strategy._shutdown_post_join_confirmed_state = False
    strategy._shutdown_post_join_blocker_state = "SHUTDOWN_POST_JOIN_CONFIRMATION_PENDING"
    return strategy


def _live_shutdown_strategy_for_case(case, refresh_loop):
    strategy = _shutdown_strategy_for_facts(case.facts, case.target)
    strategy.p = SimpleNamespace(
        replay_mode=False,
        execution_enabled=False,
        control_refresh_loop=refresh_loop,
    )
    strategy.broker = case.broker
    strategy._data_by_target = {case.target.target_id: case.target.data}
    strategy._routes = {case.target.target_id: (case.target.instrument, case.target.exchange)}
    strategy._authorized_targets = frozenset((case.target.target_id,))
    strategy._risk_policy = _risk_policy()
    strategy._quote_max_age_seconds = None
    strategy._max_query_age_seconds = None
    strategy._control_refresh_stopped = False
    strategy._clock_now = lambda: case.now
    strategy.cerebro = SimpleNamespace(
        live_bar_cohort_clock=SimpleNamespace(utc_now=lambda: case.now)
    )
    strategy.last_order_plan = None
    strategy.last_execution_facts = None
    strategy.last_execution_block_reason = None
    return strategy


def test_read_only_flat_shadow_can_retire_while_trading_plan_is_blocked():
    """Read-only retirement needs complete reconciliation, not a write grant."""

    from backtrader.stores.factor_execution_facts import FactorExecutionFacts

    case = _source_backed_read_only_reconciliation_case("positive")
    facts = case.facts
    assert type(facts) is FactorExecutionFacts
    assert facts.read_only_reconciliation_ready is True, facts.read_only_reconciliation_blockers
    assert facts.risk_reduction_ready is False
    assert not any(quote.quality == "GOOD" for quote in facts.quotes)
    assert case.store.allow_writes is False
    assert case.api.trader_client.is_trading_ready is False

    strategy = _shutdown_strategy_for_facts(facts, case.target)
    blocked_trading_plan = _STRATEGY.Alpha003OrderPlan(
        "BLOCKED", "RISK_REDUCTION_FACTS_UNAVAILABLE", (), None, case.now, None
    )
    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(strategy, facts, blocked_trading_plan)

    assert strategy.shutdown_ready is True
    assert strategy.shutdown_blocker is None
    assert strategy._last_shutdown_facts_id == facts.snapshot_id


@pytest.mark.parametrize("scenario", ("active_order", "pending_order"))
def test_null_risk_read_only_stop_preserves_observed_working_orders(scenario):
    """A complete query can end observation without canceling old remote state."""
    case = _source_backed_read_only_reconciliation_case(scenario)
    joined = []

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            joined.append(True)

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)

        facts = strategy._live_facts(case.now)
        assert facts is not None
        assert facts.read_only_reconciliation_ready is False
        assert facts.read_only_observation_ready is True, facts.read_only_observation_blockers
        assert len(facts.working_orders) == 1
        preserved_order = facts.working_orders[0]
        before_broker_orders = tuple(strategy.broker.orders)

        strategy.request_shutdown()
        strategy.stop()

        assert joined == [True]
        assert strategy.shutdown_ready is True
        assert strategy.shutdown_post_join_confirmed is True
        assert strategy.shutdown_post_join_blocker is None
        assert strategy.last_execution_facts is not None
        assert tuple(strategy.last_execution_facts.working_orders) == (preserved_order,)
        assert tuple(strategy.broker.orders) == before_broker_orders
        assert case.store.allow_writes is False
        assert strategy.broker.get_market_data_only_audit() == {
            "submit_rejected": 0,
            "cancel_rejected": 0,
            "batch_cancel_rejected": 0,
            "total_rejected": 0,
        }
    finally:
        case.journal.close()


def test_null_risk_retirement_rejects_nonflat_projection_with_writable_store():
    """A writable Store cannot qualify for passive read-only retirement."""
    case = _source_backed_read_only_reconciliation_case("owned_nonflat")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)

        facts = strategy._live_facts(case.now)
        assert facts is not None
        assert facts.positions[0].quantity == Decimal("1")
        assert facts.read_only_observation_ready is True, facts.read_only_observation_blockers
        assert case.store.allow_writes is True
        assert strategy._passive_read_only_retirement_proven(facts) is False
        strategy.request_shutdown()
        strategy.stop()

        expected_blocker = "SHUTDOWN_OWNED_POSITION_OPEN:" + case.target.target_id
        assert strategy.shutdown_ready is False
        assert strategy.shutdown_blocker == expected_blocker
        assert strategy.shutdown_post_join_confirmed is False
        assert strategy.shutdown_post_join_blocker == expected_blocker
        assert strategy.last_execution_facts.positions[0].quantity == Decimal("1")
        assert strategy.broker.get_market_data_only_audit()["total_rejected"] == 0
    finally:
        case.journal.close()


def test_null_risk_read_only_stop_preserves_foreign_target_position_without_attribution():
    case = _source_backed_read_only_reconciliation_case("foreign_target")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)

        facts = strategy._live_facts(case.now)
        assert facts is not None
        position = next(row for row in facts.positions if row.target_id == case.target.target_id)
        assert position.position_book_status == "FOREIGN_OWNER"
        assert position.owner_strategy_scope is None
        assert position.owner_intent_id is None
        assert case.same_day_facts.read_only_observation_ready is False
        assert any(
            blocker.startswith("terminal_order_not_reconciled:")
            for blocker in case.same_day_facts.read_only_observation_blockers
        )
        assert any(
            blocker.startswith("trade_observation_not_reconciled:")
            for blocker in case.same_day_facts.read_only_observation_blockers
        )
        assert case.terminal_page.items[0].status == "RESOLVED"
        assert case.journal.active_instrument_owner("acct-scope", case.target.instrument) is None
        assert facts.read_only_observation_ready is True, facts.read_only_observation_blockers

        strategy.request_shutdown()
        strategy.stop()

        assert strategy.shutdown_ready is True
        assert strategy.shutdown_post_join_confirmed is True
        assert strategy.shutdown_post_join_blocker is None
        retained = next(
            row
            for row in strategy.last_execution_facts.positions
            if row.target_id == case.target.target_id
        )
        assert retained.quantity == retained.broker_quantity == Decimal("1")
        assert retained.owner_strategy_scope is None
        assert retained.owner_intent_id is None
        assert case.store.allow_writes is False
        assert strategy.broker.get_market_data_only_audit()["total_rejected"] == 0
    finally:
        case.journal.close()


def test_null_risk_read_only_stop_blocks_unreconciled_foreign_order_slot():
    case = _source_backed_read_only_reconciliation_case("foreign_target_unreconciled")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)

        facts = strategy._live_facts(case.now)
        assert facts is not None
        assert facts.read_only_observation_ready is False
        assert any(
            blocker.startswith("journal_known_intent_not_joined:")
            for blocker in facts.read_only_observation_blockers
        )
        assert case.journal.active_instrument_owner("acct-scope", case.target.instrument) is not None

        strategy.request_shutdown()
        strategy.stop()

        assert strategy.shutdown_ready is False
        assert strategy.shutdown_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")
        assert strategy.broker.get_market_data_only_audit() == {
            "submit_rejected": 0,
            "cancel_rejected": 0,
            "batch_cancel_rejected": 0,
            "total_rejected": 0,
        }
    finally:
        case.journal.close()


def test_null_risk_read_only_stop_preserves_typed_external_position_and_order():
    case = _source_backed_read_only_reconciliation_case("external_state")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)
        initial_orders = tuple(strategy.broker.orders)

        facts = strategy._live_facts(case.now)
        assert facts is not None
        assert facts.read_only_reconciliation_ready is False
        assert facts.read_only_observation_ready is True, facts.read_only_observation_blockers
        external_position = next(row for row in facts.positions if row.target_id is None)
        external_order = next(row for row in facts.working_orders if row.target_id is None)
        assert (external_position.instrument, external_position.exchange) == ("m2501", "DCE")
        assert external_position.quantity == Decimal("1")
        assert (external_order.instrument, external_order.exchange) == ("m2501", "DCE")
        assert external_order.state == "REMOTE_ONLY"

        strategy.request_shutdown()
        strategy.stop()

        assert strategy.shutdown_ready is True
        assert strategy.shutdown_post_join_confirmed is True
        assert strategy.shutdown_post_join_blocker is None
        assert tuple(strategy.broker.orders) == initial_orders
        retained_position = next(
            row for row in strategy.last_execution_facts.positions if row.target_id is None
        )
        retained_order = next(
            row for row in strategy.last_execution_facts.working_orders if row.target_id is None
        )
        assert retained_position.quantity == Decimal("1")
        assert retained_order.state == "REMOTE_ONLY"
        assert case.store.allow_writes is False
        assert strategy.broker.get_market_data_only_audit() == {
            "submit_rejected": 0,
            "cancel_rejected": 0,
            "batch_cancel_rejected": 0,
            "total_rejected": 0,
        }
    finally:
        case.journal.close()


def test_null_risk_read_only_facts_require_explicit_freshness_and_current_receipt():
    case = _source_backed_read_only_reconciliation_case("positive")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = None
        strategy._max_query_age_seconds = Decimal("10")
        assert strategy._live_facts(case.now) is None
        assert strategy.last_execution_block_reason == "LIVE_FACT_AGE_BOUNDS_REQUIRED"

        strategy._quote_max_age_seconds = Decimal("2")
        strategy.p.control_refresh_loop.last_receipt = None
        facts = strategy._live_facts(case.now)
        assert facts is not None
        assert facts.read_only_observation_ready is False
        strategy.request_shutdown()
        strategy._update_shutdown_state(facts, None)
        assert strategy.shutdown_ready is False
        assert strategy.shutdown_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")
    finally:
        case.journal.close()


def test_null_risk_read_only_stop_rejects_stale_query_projection():
    case = _source_backed_read_only_reconciliation_case("stale_query")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)

        facts = strategy._live_facts(case.now)
        assert facts is not None
        assert facts.read_only_observation_ready is False
        strategy.request_shutdown()
        strategy._update_shutdown_state(facts, None)
        assert strategy.shutdown_ready is False
        assert strategy.shutdown_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")
    finally:
        case.journal.close()


@pytest.mark.parametrize("replacement", ("broker", "store"))
def test_passive_retirement_requires_same_projecting_broker_and_store(replacement):
    case = _source_backed_read_only_reconciliation_case("owned_nonflat")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)
        facts = strategy._live_facts(case.now)
        assert facts is not None
        if replacement == "store":
            strategy.broker.store = SimpleNamespace(allow_writes=False)
        else:
            prior_broker = strategy.broker
            strategy.broker = SimpleNamespace(
                store=case.store,
                get_param=prior_broker.get_param,
                get_market_data_only_audit=prior_broker.get_market_data_only_audit,
            )

        assert strategy._passive_read_only_retirement_proven(facts) is False
        strategy.request_shutdown()
        strategy._update_shutdown_state(facts, None)
        assert strategy.shutdown_ready is False
    finally:
        case.journal.close()


@pytest.mark.parametrize("failed_proof", ("execution_enabled", "broker_mode", "store_write"))
def test_nonflat_read_only_state_needs_all_positive_no_write_proofs(failed_proof):
    case = _source_backed_read_only_reconciliation_case("owned_nonflat")

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            return None

    try:
        strategy = _live_shutdown_strategy_for_case(case, _RefreshLoop())
        strategy._risk_policy = None
        strategy._quote_max_age_seconds = Decimal("2")
        strategy._max_query_age_seconds = Decimal("10")
        strategy.broker.set_param("market_data_only", True)
        facts = strategy._live_facts(case.now)
        assert facts is not None
        if failed_proof == "execution_enabled":
            strategy.p.execution_enabled = True
        elif failed_proof == "broker_mode":
            strategy.broker.set_param("market_data_only", False)
        else:
            strategy.broker.store._registered_sim_allow_writes = True

        assert strategy._passive_read_only_retirement_proven(facts) is False
        strategy.request_shutdown()
        strategy._update_shutdown_state(facts, None)
        assert strategy.shutdown_ready is False
    finally:
        case.journal.close()


def test_stop_confirms_fresh_read_only_state_after_refresh_join():
    case = _source_backed_read_only_reconciliation_case("positive")
    events = []

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            events.append("joined")

    loop = _RefreshLoop()
    strategy = _live_shutdown_strategy_for_case(case, loop)
    strategy._live_facts = MethodType(
        lambda self, now: (
            events.append(("projected", now)),
            _STRATEGY.Alpha003TargetStrategy._live_facts(self, now),
        )[1],
        strategy,
    )

    _STRATEGY.Alpha003TargetStrategy.stop(strategy)

    assert events[0] == "joined"
    assert events[1] == ("projected", case.now)
    assert strategy.shutdown_post_join_confirmed is True
    assert strategy.shutdown_post_join_blocker is None
    assert strategy.shutdown_ready is True


def test_stop_rejects_readiness_if_query_session_changes_during_join():
    case = _source_backed_read_only_reconciliation_case("positive")
    events = []

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            events.append("joined")
            case.api.trader_client._account_fingerprint = "changed-final-session"

    loop = _RefreshLoop()
    strategy = _live_shutdown_strategy_for_case(case, loop)
    strategy._live_facts = MethodType(
        lambda self, now: (
            events.append(("projected", now)),
            _STRATEGY.Alpha003TargetStrategy._live_facts(self, now),
        )[1],
        strategy,
    )
    prior_facts = strategy._live_facts(case.now)
    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(
        strategy, prior_facts, strategy.last_order_plan
    )
    assert strategy.shutdown_ready is True
    events.clear()

    _STRATEGY.Alpha003TargetStrategy.stop(strategy)

    assert events[0] == "joined"
    assert events[1] == ("projected", case.now)
    assert strategy.shutdown_ready is False
    assert strategy.shutdown_post_join_confirmed is False
    assert strategy.shutdown_post_join_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")


def test_stop_rejects_readiness_if_query_snapshot_ages_during_join():
    case = _source_backed_read_only_reconciliation_case("positive")
    current_time = [case.now]

    class _RefreshLoop:
        last_receipt = case.receipt

        def stop_and_join(self):
            current_time[0] = case.now + timedelta(seconds=31)

    loop = _RefreshLoop()
    strategy = _live_shutdown_strategy_for_case(case, loop)
    strategy._clock_now = lambda: current_time[0]
    prior_facts = strategy._live_facts(case.now)
    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(
        strategy, prior_facts, strategy.last_order_plan
    )
    assert strategy.shutdown_ready is True

    _STRATEGY.Alpha003TargetStrategy.stop(strategy)

    assert strategy.shutdown_ready is False
    assert strategy.shutdown_post_join_confirmed is False
    assert strategy.shutdown_post_join_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")


def test_read_only_retirement_rejects_missing_facts():
    case = _source_backed_read_only_reconciliation_case("positive")
    strategy = _shutdown_strategy_for_facts(case.facts, case.target)

    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(strategy, None, None)

    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker == "SHUTDOWN_FACTS_UNAVAILABLE"


@pytest.mark.parametrize(
    ("scenario", "expected_prefix"),
    (
        ("stale_query", "SHUTDOWN_RECONCILIATION_BLOCKED:"),
        ("session_mismatch", "SHUTDOWN_RECONCILIATION_BLOCKED:"),
        ("unknown_order", "SHUTDOWN_RECONCILIATION_BLOCKED:"),
        ("pending_order", "SHUTDOWN_RECONCILIATION_BLOCKED:"),
        ("frozen", "SHUTDOWN_RECONCILIATION_BLOCKED:"),
    ),
)
def test_read_only_retirement_blocks_stale_mixed_session_or_unknown_facts(
    scenario, expected_prefix
):
    case = _source_backed_read_only_reconciliation_case(scenario)
    facts = case.facts
    strategy = _shutdown_strategy_for_facts(facts, case.target)

    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(strategy, facts, None)

    assert facts.read_only_reconciliation_ready is False
    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker.startswith(expected_prefix)


def test_read_only_retirement_blocks_active_order_with_source_book_blocker():
    case = _source_backed_read_only_reconciliation_case("active_order")
    facts = case.facts
    strategy = _shutdown_strategy_for_facts(facts, case.target)

    _STRATEGY.Alpha003TargetStrategy._update_shutdown_state(strategy, facts, None)

    assert facts.read_only_reconciliation_ready is False
    assert "INSTRUMENT_ORDER_UNRESOLVED" in facts.read_only_reconciliation_blockers
    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker == (
        "SHUTDOWN_RECONCILIATION_BLOCKED:INSTRUMENT_ORDER_UNRESOLVED"
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        ({"offset": "close"}, "DATED_CLOSE_OFFSET_OR_HEDGE_INVALID"),
        ({"hedge_flag": "2"}, "DATED_CLOSE_HEDGE_UNSUPPORTED"),
    ),
)
def test_dated_close_rejects_generic_offset_or_unroutable_hedge(mutation, expected_reason):
    facts, live = _source_backed_dated_close_facts("TODAY")
    leg = replace(facts.dated_close_legs[0], **mutation)
    changed_facts = replace(facts, dated_close_legs=(leg,))
    # The neutral facts DTO already rejects a malformed offset at its outer
    # readiness gate. Keep the bridge's original complete projection here and
    # exercise the Strategy's defense-in-depth dated-leg validator directly.
    assert changed_facts.risk_reduction_ready is (mutation.get("offset") != "close")
    planning = replace(
        _dated_source_planning_input(facts, live["now"]),
        dated_close_legs=(leg,),
        risk_reduction_ready=True,
    )

    plan = _STRATEGY.plan_alpha003_orders(planning)

    assert plan.status == "BLOCKED"
    assert plan.reason == expected_reason
    assert plan.actions == ()


def test_shfe_close_without_source_backed_date_bucket_never_falls_back_to_generic_close():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="intent-open-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    inputs = replace(
        _risk_facts(positions=(position, _risk_facts().positions[1])),
        target_decision=None,
        run_end=True,
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "BLOCKED"
    assert plan.reason == "DATED_CLOSE_FACTS_UNAVAILABLE"
    assert plan.actions == ()


def test_replay_shfe_close_without_a_dated_replay_ledger_is_explicitly_blocked():
    evaluated_at = AVAILABLE + timedelta(seconds=6)
    position = _STRATEGY.Alpha003PositionFact(
        target_id="A",
        instrument="SHFE.rb",
        exchange="SHFE",
        quantity=1,
        snapshot_id="positions-1",
        available_at=evaluated_at,
        owner_strategy_scope="alpha003-simnow-example",
        owner_intent_id="replay-owner-A",
        average_price=Decimal("100"),
        stop_price=Decimal("95"),
        held_eligible_bars=12,
    )
    inputs = replace(
        _risk_facts(positions=(position, _risk_facts().positions[1])),
        quotes=tuple(
            replace(quote, evidence_source="REPLAY_TAPE") for quote in _risk_facts().quotes
        ),
        target_decision=None,
        run_end=True,
        evidence_source="CAUSAL_REPLAY",
    )

    plan = _STRATEGY.plan_alpha003_orders(inputs)

    assert plan.status == "BLOCKED"
    assert plan.reason == "REPLAY_DATED_CLOSE_FACTS_UNAVAILABLE"
    assert plan.actions == ()
