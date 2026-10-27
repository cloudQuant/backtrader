"""OPEN-only commission evidence must not block read-only retirement."""

from dataclasses import replace

import pytest

from tests.unit import test_alpha003_simnow_strategy as strategy_tests


_MISSING = object()


def _retirement_strategy(
    case,
    *,
    commission_required_for_open=_MISSING,
    commission_identity_by_target=_MISSING,
):
    class RefreshLoop:
        last_receipt = case.receipt

        @staticmethod
        def stop_and_join():
            return None

    refresh_loop = RefreshLoop()
    if commission_required_for_open is not _MISSING:
        refresh_loop.commission_required_for_open = commission_required_for_open
    if commission_identity_by_target is not _MISSING:
        refresh_loop.commission_identity_by_target = commission_identity_by_target
    return strategy_tests._live_shutdown_strategy_for_case(case, refresh_loop)


def test_missing_commission_blocks_open_but_not_flat_readonly_retirement():
    case = strategy_tests._source_backed_read_only_reconciliation_case("positive")
    strategy = _retirement_strategy(case, commission_required_for_open=False)

    facts = strategy._live_facts(case.now)
    assert facts is not None
    assert case.store.allow_writes is False
    assert facts.working_orders == ()
    assert all(position.quantity == 0 for position in facts.positions)
    assert all(not item.commission_fee_required for item in facts.instruments)
    assert facts.read_only_reconciliation_ready, facts.read_only_reconciliation_blockers

    strategy.stop()

    assert strategy.shutdown_ready is True
    assert strategy.shutdown_post_join_confirmed is True
    assert strategy.shutdown_post_join_blocker is None

    # A fee requirement still makes an unqualified selected OPEN fail closed.
    opening = strategy_tests._three_target_fee_planning_input(
        fee_status_by_target={
            "A": "IDENTITY_UNAVAILABLE",
            "B": "IDENTITY_UNAVAILABLE",
            "C": "RATE_UNAVAILABLE",
        }
    )
    plan = strategy_tests._STRATEGY.plan_alpha003_orders(opening)
    assert plan.status == "BLOCKED"
    assert plan.reason == "ROUND_TRIP_FEE_BUDGET_UNAVAILABLE"
    assert plan.actions == ()


def test_required_missing_commission_does_not_block_flat_retirement():
    case = strategy_tests._source_backed_read_only_reconciliation_case("positive")
    strategy = _retirement_strategy(case, commission_required_for_open=True)

    facts = strategy._live_facts(case.now)
    assert facts is not None
    assert all(item.commission_fee_required for item in facts.instruments)
    assert all(
        item.commission_fee_status == "IDENTITY_UNAVAILABLE" for item in facts.instruments
    )
    assert any(
        blocker.startswith("commission_fee_identity_unavailable:")
        for blocker in facts.blockers
    )
    assert facts.read_only_reconciliation_ready, facts.read_only_reconciliation_blockers
    quote_blocked = replace(
        facts,
        blockers=facts.blockers
        + ("consumed_quote_price_tick_mismatch:{}".format(case.target.target_id),),
    )
    assert quote_blocked.read_only_reconciliation_ready

    strategy.stop()

    assert strategy.shutdown_ready is True
    assert strategy.shutdown_post_join_confirmed is True
    assert strategy.shutdown_post_join_blocker is None


@pytest.mark.parametrize(
    "loop_fields",
    (
        {},
        {"commission_required_for_open": False, "commission_identity_by_target": {}},
    ),
    ids=("custom-loop-missing-commission-fields", "custom-loop-false-override"),
)
def test_live_facts_cannot_disable_missing_commission_for_open(loop_fields):
    case = strategy_tests._source_backed_read_only_reconciliation_case("positive")
    try:
        strategy = _retirement_strategy(case, **loop_fields)
        strategy.p.execution_enabled = True

        facts = strategy._live_facts(case.now)

        assert facts is not None
        assert facts.execution_target_ids == (case.target.target_id,)
        assert facts.commission_required_for_open is True
        assert all(item.commission_fee_required for item in facts.instruments)
        assert all(
            item.commission_fee_status == "IDENTITY_UNAVAILABLE"
            for item in facts.instruments
        )

        live_fee_status = facts.instruments[0].commission_fee_status
        opening = strategy_tests._three_target_fee_planning_input(
            fee_status_by_target={
                target_id: live_fee_status for target_id in ("A", "B", "C")
            }
        )
        plan = strategy_tests._STRATEGY.plan_alpha003_orders(opening)
        assert plan.status == "BLOCKED"
        assert plan.reason == "ROUND_TRIP_FEE_BUDGET_UNAVAILABLE"
        assert plan.actions == ()
    finally:
        case.journal.close()


@pytest.mark.parametrize("invalid", (0, 1, "false"))
def test_invalid_commission_required_override_fails_closed(invalid):
    case = strategy_tests._source_backed_read_only_reconciliation_case("positive")
    try:
        strategy = _retirement_strategy(
            case,
            commission_required_for_open=invalid,
            commission_identity_by_target={},
        )

        assert strategy._live_facts(case.now) is None
        assert strategy.last_execution_block_reason == "COMMISSION_REQUIRED_FOR_OPEN_INVALID"
    finally:
        case.journal.close()


def test_invalid_execution_mode_fails_closed_before_projection():
    case = strategy_tests._source_backed_read_only_reconciliation_case("positive")
    try:
        strategy = _retirement_strategy(case, commission_required_for_open=False)
        strategy.p.execution_enabled = 1

        assert strategy._live_facts(case.now) is None
        assert strategy.last_execution_block_reason == "EXECUTION_MODE_INVALID"
    finally:
        case.journal.close()


@pytest.mark.parametrize("missing", ("query", "account", "positions", "order_identity"))
def test_commission_filter_preserves_core_shutdown_evidence_requirements(missing):
    scenario = "pending_order" if missing == "order_identity" else "positive"
    case = strategy_tests._source_backed_read_only_reconciliation_case(scenario)
    facts = case.facts
    if missing == "query":
        facts = replace(
            facts,
            query_provenance=tuple(
                item for item in facts.query_provenance if item.family != "account_result"
            ),
        )
    elif missing == "account":
        facts = replace(facts, account=None)
    elif missing == "positions":
        facts = replace(facts, positions=())
    else:
        assert facts.working_orders
        assert all(
            order.owner_strategy_scope is None and order.owner_intent_id is None
            for order in facts.working_orders
        )

    strategy = strategy_tests._shutdown_strategy_for_facts(facts, case.target)
    strategy_tests._STRATEGY.Alpha003TargetStrategy._update_shutdown_state(
        strategy, facts, None
    )

    assert facts.read_only_reconciliation_ready is False
    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker.startswith("SHUTDOWN_RECONCILIATION_BLOCKED:")
