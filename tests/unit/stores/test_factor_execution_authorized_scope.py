"""Authorized execution scope stays separate from full account facts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backtrader.stores.factor_execution_facts import (
    FactorExecutionAccountFacts,
    FactorExecutionFacts,
    FactorExecutionInstrumentFacts,
    FactorExecutionPositionFacts,
    FactorExecutionQueryFact,
    FactorExecutionQuoteFacts,
    FactorExecutionRouteFacts,
    FactorExecutionWorkingOrderFacts,
    project_factor_execution_facts,
    refresh_factor_execution_queries,
)


_NOW = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
_SNAPSHOT_ID = "snapshot-1"
_QUERY_SET_ID = "query-set-1"
_ACCOUNT = "account-1"
_GENERATION = 7
_TRADING_DAY = "20261025"
_TARGETS = (("M", "m2511"), ("Y", "y2511"), ("A", "a2511"))
_AUTHORIZED = ("M", "A")
_FACTS_FIXTURE_PATH = Path(__file__).with_name("test_factor_execution_facts.py")
_FACTS_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "alpha003_authorized_scope_facts_fixture", _FACTS_FIXTURE_PATH
)
assert _FACTS_FIXTURE_SPEC is not None and _FACTS_FIXTURE_SPEC.loader is not None
_FACTS_FIXTURE = importlib.util.module_from_spec(_FACTS_FIXTURE_SPEC)
sys.modules[_FACTS_FIXTURE_SPEC.name] = _FACTS_FIXTURE
_FACTS_FIXTURE_SPEC.loader.exec_module(_FACTS_FIXTURE)
_STRATEGY_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "unified"
    / "028_alpha003_simnow_minute"
    / "alpha003_strategy.py"
)
_STRATEGY_SPEC = importlib.util.spec_from_file_location(
    "alpha003_authorized_scope_strategy_test", _STRATEGY_PATH
)
assert _STRATEGY_SPEC is not None and _STRATEGY_SPEC.loader is not None
_STRATEGY = importlib.util.module_from_spec(_STRATEGY_SPEC)
sys.modules[_STRATEGY_SPEC.name] = _STRATEGY
_STRATEGY_SPEC.loader.exec_module(_STRATEGY)


def _route(target_id, instrument, *, eligible=True, missing_template=False, **changes):
    values = dict(
        target_id=target_id,
        instrument=instrument,
        exchange="DCE",
        route_name="ctp/direct/registered-sim",
        eligible=eligible,
        allow_writes=True,
        frozen=False,
        capability_observed=True,
        capability_managed=True,
        capability_armed=True,
        capability_matches_route=True,
        instrument_query_complete=True,
        instrument_eligible=True,
        unknown_order_count=0,
        dispatching_order_count=0,
        connection_generation=_GENERATION,
        trading_day=_TRADING_DAY,
        reason_codes=(),
        sdk_frozen=False,
        arm_template_configured=None if missing_template else True,
        arm_templates_configured=True,
        arm_template_membership=False if missing_template else True,
        arm_api_available=True,
        current_session_account_fingerprint=_ACCOUNT,
        current_session_connection_generation=_GENERATION,
        current_session_trading_day=_TRADING_DAY,
        current_session_trading_ready=True,
    )
    values.update(changes)
    return FactorExecutionRouteFacts(**values)


def _facts(
    *,
    unauthorized_quantity=Decimal(0),
    unauthorized_unknown=False,
    routes=None,
    orders=(),
    execution_ids=_AUTHORIZED,
):
    available_at = _NOW - timedelta(seconds=1)
    positions = []
    instruments = []
    quotes = []
    for target_id, instrument in _TARGETS:
        quantity = unauthorized_quantity if target_id == "Y" else Decimal(0)
        if unauthorized_unknown and target_id == "Y":
            quantity = None
        positions.append(
            FactorExecutionPositionFacts(
                target_id=target_id,
                instrument=instrument,
                exchange="DCE",
                quantity=quantity,
                snapshot_id=_SNAPSHOT_ID,
                available_at=available_at,
                owner_strategy_scope="alpha003" if quantity not in (None, Decimal(0)) else None,
                owner_intent_id="intent-y" if quantity not in (None, Decimal(0)) else None,
                average_price=Decimal(10) if quantity not in (None, Decimal(0)) else None,
                stop_price=Decimal(9) if quantity not in (None, Decimal(0)) else None,
                held_eligible_bars=1 if quantity not in (None, Decimal(0)) else None,
                long_quantity=quantity,
                short_quantity=Decimal(0) if quantity is not None else None,
                broker_quantity=quantity,
                position_book_status=(
                    "FLAT" if quantity == 0 else "UNKNOWN" if quantity is None else "MATCHED"
                ),
            )
        )
        instruments.append(
            FactorExecutionInstrumentFacts(
                target_id=target_id,
                instrument=instrument,
                exchange="DCE",
                snapshot_id=_SNAPSHOT_ID,
                available_at=available_at,
                trading_permitted=True,
                multiplier=Decimal(10),
                long_margin_per_hand=Decimal(5),
                short_margin_per_hand=Decimal(5),
                tick_size=Decimal(1),
                lower_limit=Decimal(1),
                upper_limit=Decimal(100),
            )
        )
        quotes.append(
            FactorExecutionQuoteFacts(
                instrument=instrument,
                exchange="DCE",
                source="ctp-native-live",
                source_ref="tick-{}".format(target_id),
                metadata_snapshot_id=_SNAPSHOT_ID,
                generation=_GENERATION,
                sequence=1,
                trading_day=_TRADING_DAY,
                event_time=available_at,
                available_at=available_at,
                bid=Decimal(10),
                ask=Decimal(11),
                bid_size=Decimal(1),
                ask_size=Decimal(1),
                tick_size=Decimal(1),
                lower_limit=Decimal(1),
                upper_limit=Decimal(100),
                quality="GOOD",
            )
        )

    families = (
        ("account_result", "account"),
        ("orders_result", "orders"),
        ("trades_result", "trades"),
        ("instruments_result", "instruments"),
        ("positions_result", "positions"),
    )
    query_provenance = tuple(
        FactorExecutionQueryFact(
            family=family,
            request_type=request_type,
            request_id=index,
            connection_generation=_GENERATION,
            account_fingerprint=_ACCOUNT,
            trading_day=_TRADING_DAY,
            started_at=available_at - timedelta(milliseconds=100),
            completed_at=available_at,
            source_owned=True,
            query_complete=True,
            scope_complete=True,
            row_count=0,
        )
        for index, (family, request_type) in enumerate(families, start=1)
    )
    if routes is None:
        routes = tuple(
            _route(
                target_id,
                instrument,
                eligible=target_id != "Y",
                missing_template=target_id == "Y",
            )
            for target_id, instrument in _TARGETS
        )
    blockers = tuple(
        sorted(
            {
                blocker
                for route in routes
                for blocker in (
                    ("route_ineligible:{}".format(route.target_id),)
                    if route.eligible is False
                    else ()
                )
                + (
                    ("route_arm_template_missing:{}".format(route.target_id),)
                    if route.arm_templates_configured is True
                    and route.arm_template_configured is not True
                    else ()
                )
            }
        )
    )
    return FactorExecutionFacts(
        account_scope="account-scope",
        strategy_scope="alpha003",
        snapshot_id=_SNAPSHOT_ID,
        available_at=available_at,
        account=FactorExecutionAccountFacts(
            account_scope="account-scope",
            snapshot_id=_SNAPSHOT_ID,
            available_at=available_at,
            route_permitted=True,
            available_margin=Decimal(1000),
            used_margin=Decimal(0),
            current_notional=Decimal(0),
            current_worst_case_loss=Decimal(0),
            account_fingerprint=_ACCOUNT,
            connection_generation=_GENERATION,
            trading_day=_TRADING_DAY,
        ),
        positions=tuple(positions),
        working_orders=tuple(orders),
        terminal_orders=(),
        trade_observations=(),
        quotes=tuple(quotes),
        instruments=tuple(instruments),
        route_eligibilities=tuple(routes),
        query_provenance=query_provenance,
        blockers=blockers,
        query_set_id=_QUERY_SET_ID,
        target_ids=tuple(target_id for target_id, _instrument in _TARGETS),
        execution_target_ids=execution_ids,
    )


def _active_order(target_id, instrument):
    return FactorExecutionWorkingOrderFacts(
        target_id=target_id,
        instrument=instrument,
        exchange="DCE",
        order_ref="order-1",
        state="ACCEPTED",
        side="BUY",
        position_effect="OPEN",
        remaining_quantity=Decimal(1),
        owner_strategy_scope="alpha003",
        owner_intent_id="intent-1",
        execution_unknown=False,
        cancel_pending=False,
        broker_order_ref=11,
        front_id=2,
        session_id=3,
    )


def test_rank_only_missing_template_keeps_full_snapshot_and_authorized_readiness():
    facts = _facts()

    assert facts.target_ids == ("M", "Y", "A")
    assert tuple(item.target_id for item in facts.positions) == facts.target_ids
    assert tuple(item.target_id for item in facts.instruments) == facts.target_ids
    assert tuple(item.target_id for item in facts.route_eligibilities) == facts.target_ids
    assert facts.route_eligibilities[1].eligible is False
    assert "route_arm_template_missing:Y" in facts.blockers
    assert facts.aggregate_write_blockers == ()
    assert facts._scoped_route_permitted() is True
    assert facts.risk_reduction_ready is True
    assert facts.open_risk_ready is True
    assert (
        facts.read_only_reconciliation_blockers
        == replace(facts, execution_target_ids=None).read_only_reconciliation_blockers
    )


def test_incomplete_template_key_projection_does_not_suppress_missing_route_blocker():
    incomplete_route = _route(
        "Y",
        "y2511",
        eligible=False,
        missing_template=True,
        arm_template_membership=None,
    )
    facts = _facts(
        routes=(_route("M", "m2511"), incomplete_route, _route("A", "a2511")),
    )

    assert "route_arm_template_missing:Y" in facts.blockers
    assert "route_arm_template_missing:Y" in facts.aggregate_write_blockers
    assert facts._scoped_route_permitted() is False


def test_future_or_stale_core_instrument_query_does_not_suppress_missing_route_blocker():
    facts = _facts()
    assert facts.available_at is not None
    future_completed = facts.available_at + timedelta(seconds=1)
    future_provenance = tuple(
        replace(fact, completed_at=future_completed)
        if fact.family == "instruments_result"
        else fact
        for fact in facts.query_provenance
    )
    future_query = replace(facts, query_provenance=future_provenance)

    assert "route_arm_template_missing:Y" in future_query.aggregate_write_blockers
    assert future_query._scoped_route_permitted() is not True
    assert future_query.risk_reduction_ready is False

    stale_completed = facts.available_at - timedelta(minutes=5)
    stale_provenance = tuple(
        replace(fact, started_at=stale_completed, completed_at=stale_completed)
        if fact.family == "instruments_result"
        else fact
        for fact in facts.query_provenance
    )
    stale_query = replace(
        facts,
        query_provenance=stale_provenance,
        blockers=facts.blockers + ("query_snapshot_invalid_or_stale:instruments_result",),
    )

    assert "route_arm_template_missing:Y" in stale_query.aggregate_write_blockers
    assert "query_snapshot_invalid_or_stale:instruments_result" in (
        stale_query.aggregate_write_blockers
    )
    assert stale_query._scoped_route_permitted() is False


@pytest.mark.parametrize(
    "routes",
    (
        (
            _route("M", "m2511"),
            _route("Y", "y2511", eligible=False, missing_template=True, frozen=True),
            _route("A", "a2511"),
        ),
        (
            _route("M", "m2511"),
            _route(
                "Y",
                "y2511",
                eligible=False,
                missing_template=True,
                current_session_connection_generation=_GENERATION + 1,
            ),
            _route("A", "a2511"),
        ),
        (
            _route("M", "m2511"),
            _route(
                "Y",
                "y2511",
                eligible=False,
                missing_template=True,
                current_session_trading_ready=False,
            ),
            _route("A", "a2511"),
        ),
    ),
    ids=("frozen", "session_generation_mismatch", "session_not_ready"),
)
def test_unarmed_route_exception_does_not_hide_frozen_or_session_blockers(routes):
    facts = _facts(routes=routes)

    assert "route_ineligible:Y" in facts.aggregate_write_blockers
    assert facts._scoped_route_permitted() is False
    assert facts.risk_reduction_ready is False


def test_unarmed_target_position_or_unknown_exposure_is_a_hard_blocker():
    nonflat = _facts(unauthorized_quantity=Decimal(1))
    unknown = _facts(unauthorized_unknown=True)

    assert "execution_scope_observation_not_flat:Y" in nonflat.aggregate_write_blockers
    assert nonflat._scoped_route_permitted() is False
    assert "execution_scope_observation_position_unavailable:Y" in unknown.aggregate_write_blockers
    assert unknown._scoped_route_permitted() is None


def test_unarmed_target_order_blocks_cancellation_but_authorized_order_can_cancel():
    authorized_order = _facts(orders=(_active_order("M", "m2511"),))
    unauthorized_order = _facts(orders=(_active_order("Y", "y2511"),))

    assert authorized_order.order_cancel_ready is True
    assert (
        "execution_scope_observation_order_present:Y" in unauthorized_order.aggregate_write_blockers
    )
    assert unauthorized_order.order_cancel_ready is False


def test_strategy_action_route_guard_requires_the_authorized_target_own_route():
    authorized = SimpleNamespace(
        execution_target_ids=("M", "A"),
        instruments=(
            SimpleNamespace(
                target_id="M", instrument="m2511", exchange="DCE", route_permitted=True
            ),
            SimpleNamespace(
                target_id="A", instrument="a2511", exchange="DCE", route_permitted=True
            ),
            SimpleNamespace(
                target_id="Y", instrument="y2511", exchange="DCE", route_permitted=False
            ),
        ),
    )
    denied_route = SimpleNamespace(
        execution_target_ids=authorized.execution_target_ids,
        instruments=(
            SimpleNamespace(
                target_id="M", instrument="m2511", exchange="DCE", route_permitted=False
            ),
            *authorized.instruments[1:],
        ),
    )

    assert _STRATEGY._execution_route_authorized(
        authorized, "M", instrument="m2511", exchange="DCE"
    )
    assert not _STRATEGY._execution_route_authorized(
        authorized, "Y", instrument="y2511", exchange="DCE"
    )
    assert not _STRATEGY._execution_route_authorized(
        denied_route, "M", instrument="m2511", exchange="DCE"
    )


def test_an_authorized_route_denial_and_omitted_scope_remain_fail_closed():
    denied_authorized = _facts(
        routes=(
            _route("M", "m2511", eligible=False, frozen=True),
            _route("Y", "y2511", eligible=False, missing_template=True),
            _route("A", "a2511"),
        )
    )
    legacy_full_scope = _facts(execution_ids=None)

    assert "route_ineligible:M" in denied_authorized.aggregate_write_blockers
    assert denied_authorized._scoped_route_permitted() is False
    assert "route_ineligible:Y" in legacy_full_scope.aggregate_write_blockers
    assert "route_arm_template_missing:Y" in legacy_full_scope.aggregate_write_blockers
    assert legacy_full_scope._scoped_route_permitted() is False


def test_scope_tuple_is_immutable_unique_and_a_subset_of_full_targets():
    facts = _facts()

    with pytest.raises(TypeError):
        replace(facts, execution_target_ids=["M", "A"])
    with pytest.raises(ValueError):
        replace(facts, execution_target_ids=("M", "M"))
    with pytest.raises(ValueError):
        replace(facts, execution_target_ids=("M", "outside"))


def _risk_policy():
    return _STRATEGY.Alpha003RiskPolicy(
        risk_policy_id="alpha003-authorized-scope-test-v1",
        max_hold_eligible_bars=12,
        preclose_grace_seconds=60,
        run_end_policy="CLOSE_ALL",
        quote_max_age_seconds=Decimal("5"),
        max_state_age_seconds=Decimal("30"),
        max_notional_per_position=Decimal("2000"),
        max_total_notional=Decimal("3000"),
        max_margin_per_position=Decimal("250"),
        max_total_margin=Decimal("500"),
        max_loss_per_position=Decimal("100"),
        max_total_loss=Decimal("250"),
        stop_loss_ticks=2,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=20,
        round_trip_fee_upper_bound_per_contract=Decimal("1"),
    )


def _target_decision(facts, target_ids, *, authorized=_AUTHORIZED):
    available_at = facts.available_at
    assert available_at is not None
    target_ids = tuple(target_ids)
    targets = tuple(
        _STRATEGY.Alpha003SignalTarget(
            target_id=target_id,
            product_key=("DCE", instrument),
            target_position=1 if target_id in ("M", "Y") else -1,
            raw_score=1.0 if target_id in ("M", "Y") else -1.0,
            oriented_score=1.0 if target_id in ("M", "Y") else -1.0,
        )
        for target_id, instrument in _TARGETS
        if target_id in target_ids
    )
    return _STRATEGY.Alpha003TargetDecision(
        status="TARGETS_READY",
        reason=None,
        factor_name="alpha003",
        mode="native",
        execution_mode="LIVE",
        direction=1,
        source_sha256="a" * 64,
        cohort_id="authorized-scope-cohort",
        batch_id="authorized-scope-batch",
        close_time=available_at - timedelta(seconds=1),
        available_at=available_at,
        eligible_grid_index=1,
        rebalance_every=1,
        authorized_targets=tuple(authorized),
        eligible_targets=target_ids,
        targets=targets,
    )


def _production_scope_facts(now, *, missing_computed_margin_targets=()):
    target_specs = (
        ("M", "m2511", "DCE"),
        ("Y", "y2511", "DCE"),
        ("A", "a2511", "DCE"),
    )
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        targets,
        _templates,
    ) = _FACTS_FIXTURE._multi_target_system_under_test(
        now=now,
        target_specs=target_specs,
        missing_template=(target_specs[1],),
    )
    missing_margin_target_ids = set(missing_computed_margin_targets)
    missing_margin_instruments = {
        instrument
        for target_id, instrument, _exchange in target_specs
        if target_id in missing_margin_target_ids
    }
    for row in api.query_rows["instrument_margin_rate_result"]:
        if row["InstrumentID"] in missing_margin_instruments:
            # Valid zero ratios exercise the production per-hand calculation's
            # unobserved-margin result without introducing a query/schema error.
            row["LongMarginRatioByMoney"] = "0"
            row["LongMarginRatioByVolume"] = "0"
            row["ShortMarginRatioByMoney"] = "0"
            row["ShortMarginRatioByVolume"] = "0"
    receipt = refresh_factor_execution_queries(store, targets=targets, overall_timeout=4.0)
    assert receipt.blockers == ()
    assert receipt.pending_families == ()
    assert receipt.query_set is not None
    for target in targets:
        assert store.poll_tick(target.instrument) is not None
    facts = project_factor_execution_facts(
        store,
        broker,
        targets=targets,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        query_set=receipt.query_set,
        execution_target_ids=("M", "A"),
    )
    return api, store, broker, journal, coordinator, targets, receipt.query_set, facts


def _planning_input(facts, now, *, target_decision=None, orders=(), run_end=False):
    planning = _STRATEGY._live_planning_input(
        facts,
        strategy_scope=facts.strategy_scope,
        evaluated_at=now,
        risk_evidence_available_at=facts.available_at,
        session_close_at=now + timedelta(hours=1),
        run_end=run_end,
        risk_policy=_risk_policy(),
        target_decision=target_decision,
        eligible_grid_ordinal=1,
        run_order_intents_used=0,
    )
    if orders:
        planning = replace(
            planning,
            working_orders=tuple(orders),
            order_cancel_ready=True,
            order_cancel_blockers=(),
        )
    return planning


def test_real_store_projection_and_planner_keep_full_pool_but_emit_only_authorized_actions():
    now = datetime.now(timezone.utc)
    api, store, broker, journal, _coordinator, targets, query_set, facts = _production_scope_facts(
        now
    )
    try:
        y_route = store.registered_sim_route_eligibility("y2511", "DCE")
        assert y_route.arm_templates_configured is True
        assert y_route.arm_template_configured is None
        assert y_route.arm_template_membership is False
        assert facts.target_ids == ("M", "Y", "A")
        assert facts.execution_target_ids == ("M", "A")
        assert tuple(item.target_id for item in facts.positions) == ("M", "Y", "A")
        assert tuple(item.target_id for item in facts.instruments) == ("M", "Y", "A")
        assert tuple(item.target_id for item in facts.route_eligibilities) == ("M", "Y", "A")
        assert facts.route_eligibilities[1].eligible is False
        assert "route_arm_template_missing:Y" in facts.blockers
        assert facts.aggregate_write_blockers == ()
        assert facts.risk_reduction_ready is True
        assert facts.open_risk_ready is True

        planning = _planning_input(
            facts,
            now,
            target_decision=_target_decision(facts, ("M", "A")),
        )
        plan = _STRATEGY.plan_alpha003_orders(planning)
        assert plan.status == "READY", plan.reason
        assert [(item.action, item.target_id) for item in plan.actions] == [
            ("SUBMIT", "M"),
            ("SUBMIT", "A"),
        ]

        unapproved_target = _planning_input(
            facts,
            now,
            target_decision=_target_decision(facts, ("Y",)),
        )
        denied_open = _STRATEGY.plan_alpha003_orders(unapproved_target)
        assert denied_open.status == "BLOCKED"
        assert denied_open.reason == "OPEN_TARGET_ROUTE_NOT_AUTHORIZED"
        assert denied_open.actions == ()

        invalid = dict(api.registered_sim_execution_facts())
        invalid["arm_template_keys"] = (("malformed",),)
        api.registered_sim_execution_facts = lambda: dict(invalid)
        malformed_route = store.registered_sim_route_eligibility("y2511", "DCE")
        assert malformed_route.arm_template_membership is None
        invalid["arm_template_keys"] = [("m2511", "DCE"), ("a2511", "DCE")]
        malformed_list_route = store.registered_sim_route_eligibility("y2511", "DCE")
        assert malformed_list_route.arm_template_membership is None
        invalid["arm_template_keys"] = (("malformed",),)
        malformed_facts = project_factor_execution_facts(
            store,
            broker,
            targets=targets,
            account_scope="acct-scope",
            strategy_scope="alpha003",
            now=now,
            quote_max_age=timedelta(seconds=2),
            max_query_age=timedelta(seconds=10),
            query_set=query_set,
            execution_target_ids=("M", "A"),
        )
        malformed_y = next(
            route for route in malformed_facts.route_eligibilities if route.target_id == "Y"
        )
        assert malformed_y.arm_template_membership is None
        assert malformed_y.eligible is False
        assert "route_arm_template_missing:Y" in malformed_facts.blockers
        assert "route_arm_template_missing:Y" in malformed_facts.aggregate_write_blockers
        assert malformed_facts._scoped_route_permitted() is False
    finally:
        journal.close()


def test_passive_flat_target_missing_computed_margin_does_not_block_authorized_open():
    now = datetime.now(timezone.utc)
    api, store, broker, journal, _coordinator, targets, _query_set, facts = _production_scope_facts(
        now, missing_computed_margin_targets=("Y",)
    )
    try:
        missing_y_margin = {
            "long_margin_per_hand_unobserved:Y",
            "short_margin_per_hand_unobserved:Y",
        }
        y_instrument = next(item for item in facts.instruments if item.target_id == "Y")
        assert y_instrument.long_margin_per_hand is None
        assert y_instrument.short_margin_per_hand is None
        assert missing_y_margin.issubset(set(facts.blockers))
        assert missing_y_margin.isdisjoint(facts.aggregate_write_blockers)
        assert facts.open_risk_ready is True

        planning = _planning_input(
            facts,
            now,
            target_decision=_target_decision(facts, ("M", "A")),
        )
        plan = _STRATEGY.plan_alpha003_orders(planning)
        assert plan.status == "READY", plan.reason
        assert [(item.action, item.target_id) for item in plan.actions] == [
            ("SUBMIT", "M"),
            ("SUBMIT", "A"),
        ]

        # Omitting the explicit subset preserves the historical full-pool rule.
        y_route_blockers = {
            "route_ineligible:Y",
            "route_arm_template_missing:Y",
        }
        full_pool_routes = tuple(
            replace(
                route,
                eligible=True,
                arm_template_configured=True,
                arm_template_membership=True,
            )
            if route.target_id == "Y"
            else route
            for route in facts.route_eligibilities
        )
        full_pool = replace(
            facts,
            execution_target_ids=None,
            route_eligibilities=full_pool_routes,
            blockers=tuple(
                blocker for blocker in facts.blockers if blocker not in y_route_blockers
            ),
        )
        assert full_pool._scoped_route_permitted() is True
        assert missing_y_margin.issubset(set(full_pool.aggregate_write_blockers))
        assert full_pool.open_risk_ready is False
    finally:
        journal.close()


def test_authorized_target_missing_computed_margin_blocks_new_risk():
    now = datetime.now(timezone.utc)
    (
        _api,
        _store,
        _broker,
        journal,
        _coordinator,
        _targets,
        _query_set,
        facts,
    ) = _production_scope_facts(now, missing_computed_margin_targets=("M",))
    try:
        missing_m_margin = {
            "long_margin_per_hand_unobserved:M",
            "short_margin_per_hand_unobserved:M",
        }
        assert missing_m_margin.issubset(set(facts.blockers))
        assert missing_m_margin.issubset(set(facts.aggregate_write_blockers))
        assert facts.open_risk_ready is False

        plan = _STRATEGY.plan_alpha003_orders(
            _planning_input(
                facts,
                now,
                target_decision=_target_decision(facts, ("M", "A")),
            )
        )
        assert plan.status == "BLOCKED"
        assert plan.reason.startswith("OPEN_RISK_FACTS_BLOCKED:")
        assert plan.actions == ()
    finally:
        journal.close()


def test_passive_margin_is_not_suppressed_for_exposure_or_unknown_position():
    now = datetime.now(timezone.utc)
    (
        _api,
        _store,
        _broker,
        journal,
        _coordinator,
        _targets,
        _query_set,
        facts,
    ) = _production_scope_facts(now, missing_computed_margin_targets=("Y",))
    try:
        y_position_index = next(
            index for index, item in enumerate(facts.positions) if item.target_id == "Y"
        )
        y_position = facts.positions[y_position_index]
        exposed = replace(
            facts,
            positions=facts.positions[:y_position_index]
            + (
                replace(
                    y_position,
                    quantity=Decimal(1),
                    broker_quantity=Decimal(1),
                    long_quantity=Decimal(1),
                    short_quantity=Decimal(0),
                    position_book_status="MATCHED",
                ),
            )
            + facts.positions[y_position_index + 1 :],
        )
        margin_codes = {
            "long_margin_per_hand_unobserved:Y",
            "short_margin_per_hand_unobserved:Y",
        }
        assert "execution_scope_observation_not_flat:Y" in exposed.aggregate_write_blockers
        assert margin_codes.issubset(set(exposed.aggregate_write_blockers))
        assert exposed.open_risk_ready is False

        unknown = replace(
            facts,
            positions=facts.positions[:y_position_index]
            + (
                replace(
                    y_position,
                    quantity=None,
                    broker_quantity=None,
                    long_quantity=None,
                    short_quantity=None,
                    position_book_status="UNKNOWN",
                ),
            )
            + facts.positions[y_position_index + 1 :],
        )
        assert (
            "execution_scope_observation_position_unavailable:Y" in unknown.aggregate_write_blockers
        )
        assert margin_codes.issubset(set(unknown.aggregate_write_blockers))
        assert unknown.open_risk_ready is False
    finally:
        journal.close()


def test_planner_emits_authorized_reductions_and_cancels_and_blocks_y_exposure():
    now = datetime.now(timezone.utc)
    (
        _api,
        _store,
        _broker,
        journal,
        _coordinator,
        _targets,
        _query_set,
        facts,
    ) = _production_scope_facts(now)
    try:
        planning = _planning_input(facts, now)
        owned_positions = tuple(
            replace(
                position,
                quantity=1 if position.target_id in ("M", "A") else 0,
                owner_strategy_scope=facts.strategy_scope
                if position.target_id in ("M", "A")
                else None,
                owner_intent_id="intent-" + position.target_id
                if position.target_id in ("M", "A")
                else None,
                average_price=Decimal("100") if position.target_id in ("M", "A") else None,
                stop_price=Decimal("50") if position.target_id in ("M", "A") else None,
                held_eligible_bars=12 if position.target_id in ("M", "A") else None,
            )
            for position in planning.positions
        )
        reductions = _STRATEGY.plan_alpha003_orders(replace(planning, positions=owned_positions))
        assert reductions.status == "READY", reductions.reason
        assert [
            (item.action, item.target_id, item.position_effect) for item in reductions.actions
        ] == [("SUBMIT", "M", "CLOSE"), ("SUBMIT", "A", "CLOSE")]

        y_exposure = tuple(
            replace(
                position,
                quantity=1,
                owner_strategy_scope=facts.strategy_scope,
                owner_intent_id="intent-Y",
                average_price=Decimal("100"),
                stop_price=Decimal("50"),
                held_eligible_bars=1,
            )
            if position.target_id == "Y"
            else position
            for position in planning.positions
        )
        denied_reduction = _STRATEGY.plan_alpha003_orders(replace(planning, positions=y_exposure))
        assert denied_reduction.status == "BLOCKED"
        assert denied_reduction.reason == "UNAUTHORIZED_POSITION_SCOPE"
        assert denied_reduction.actions == ()

        active_orders = tuple(
            _STRATEGY.Alpha003WorkingOrderFact(
                target_id=target_id,
                instrument=instrument,
                exchange="DCE",
                order_ref="order-" + target_id,
                broker_order_ref=index,
                state="ACCEPTED",
                side="BUY",
                position_effect="OPEN",
                remaining_quantity=1,
                owner_strategy_scope=facts.strategy_scope,
                owner_intent_id="intent-" + target_id,
            )
            for index, target_id, instrument in (
                (11, "M", "m2511"),
                (12, "A", "a2511"),
            )
        )
        cancellations = _STRATEGY.plan_alpha003_orders(
            _planning_input(facts, now, orders=active_orders, run_end=True)
        )
        assert cancellations.status == "READY", cancellations.reason
        assert [(item.action, item.target_id) for item in cancellations.actions] == [
            ("CANCEL", "M"),
            ("CANCEL", "A"),
        ]

        y_order = _STRATEGY.Alpha003WorkingOrderFact(
            target_id="Y",
            instrument="y2511",
            exchange="DCE",
            order_ref="order-Y",
            broker_order_ref=13,
            state="ACCEPTED",
            side="BUY",
            position_effect="OPEN",
            remaining_quantity=1,
            owner_strategy_scope=facts.strategy_scope,
            owner_intent_id="intent-Y",
        )
        denied_cancel = _STRATEGY.plan_alpha003_orders(
            _planning_input(facts, now, orders=(y_order,), run_end=True)
        )
        assert denied_cancel.status == "BLOCKED"
        assert denied_cancel.reason == "UNAUTHORIZED_WORKING_ORDER_SCOPE"
        assert denied_cancel.actions == ()
    finally:
        journal.close()


@pytest.mark.parametrize("position_targets", [(), ("M",)])
def test_live_planning_input_fails_closed_when_current_positions_are_incomplete(
    position_targets,
):
    now = datetime.now(timezone.utc)
    (
        _api,
        _store,
        _broker,
        journal,
        _coordinator,
        _targets,
        _query_set,
        facts,
    ) = _production_scope_facts(now)
    try:
        positions_by_target = {item.target_id: item for item in facts.positions}
        incomplete_facts = replace(
            facts,
            positions=tuple(positions_by_target[target_id] for target_id in position_targets),
            blockers=tuple(
                dict.fromkeys(facts.blockers + ("broker_ctp_position_side_mismatch:M",))
            ),
        )
        planning = _planning_input(
            incomplete_facts,
            now,
            target_decision=_target_decision(facts, ("M", "A")),
        )

        assert planning.execution_target_ids == ("M", "A")
        assert "broker_ctp_position_side_mismatch:M" in planning.execution_blockers
        result = _STRATEGY.plan_alpha003_orders(planning)
        assert result.status == "BLOCKED"
        assert result.reason == "EXECUTION_FACT_SET_INVALID"
        assert result.actions == ()
    finally:
        journal.close()


def test_planning_input_still_validates_execution_target_configuration_shape():
    now = datetime.now(timezone.utc)
    api, store, broker, journal, _coordinator, targets, query_set, facts = _production_scope_facts(
        now
    )
    del api, store, broker, targets, query_set
    try:
        planning = _planning_input(facts, now)
        for invalid_ids in ([], (), ("M", "M")):
            with pytest.raises(ValueError):
                replace(planning, execution_target_ids=invalid_ids)
    finally:
        journal.close()
