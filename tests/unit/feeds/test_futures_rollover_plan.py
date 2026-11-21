"""Changed and unchanged mapping projections for BT rollover plans."""

from datetime import date, datetime, timezone

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")

from backtrader.futures import (  # noqa: E402
    ExchangeTradingDay,
    MainContractBinding,
    MainContractManifest,
    MainContractPolicy,
    ProductKey,
    ProductSelection,
    RolloverBoundaryEvidence,
    TradingDayReference,
    plan_main_contract_rollover,
)


UTC = timezone.utc
PRODUCT = ProductKey(exchange_id="DCE", product_id="M")
CURRENT_DAY = date(2026, 11, 20)
PRIOR_DAY = date(2026, 11, 19)
POLICY = MainContractPolicy()
ROLLOVER_CHECKS = (
    "OLD_ORDERS_TERMINAL",
    "OLD_ORDER_EVENTS_RECONCILED",
    "OLD_POSITIONS_FLAT",
    "OLD_STATE_RECONCILED",
    "UNKNOWN_ORDERS_ZERO",
    "OLD_INSTRUMENT_EVENT_ROUTES_PRESERVED",
    "ALL_COHORT_STATE_RESET",
    "ALL_MEMBERS_REWARMED",
)


def _manifest(*, decision_at, selected_instrument_id):
    product_selection = ProductSelection(
        product=PRODUCT,
        in_target_pool=True,
        status="READY",
        expected_prior_trading_day=PRIOR_DAY,
        ranking_trading_day=PRIOR_DAY,
        selected_instrument_id=selected_instrument_id,
        ranked_instrument_ids=(selected_instrument_id,),
        excluded_instrument_ids=(),
        blockers=(),
    )
    return MainContractManifest(
        status="READY",
        decision_at=decision_at,
        policy=POLICY,
        target_products=(PRODUCT,),
        source_id=None,
        source_snapshot_id=None,
        source_sha256=None,
        source_available_at=None,
        source_retrieved_at=None,
        catalog_source_id=None,
        catalog_snapshot_id=None,
        catalog_sha256=None,
        catalog_available_at=None,
        catalog_retrieved_at=None,
        trading_days=(
            TradingDayReference(
                exchange_id="DCE",
                current_trading_day=CURRENT_DAY,
                expected_prior_trading_day=PRIOR_DAY,
            ),
        ),
        calendars=(),
        coverage=(),
        products=(product_selection,),
        candidates=(),
        blockers=(),
    )


def _boundary():
    return RolloverBoundaryEvidence(
        boundary_id="rollover-boundary-2026-11-20",
        source_id="fixture-session-source",
        source_sha256="a" * 64,
        available_at=datetime(2026, 11, 20, 8, tzinfo=UTC),
        retrieved_at=datetime(2026, 11, 20, 9, tzinfo=UTC),
        effective_at=datetime(2026, 11, 20, 13, tzinfo=UTC),
        trading_days=(ExchangeTradingDay("DCE", CURRENT_DAY),),
    )


def _plan(current_instrument, proposed_instrument):
    return plan_main_contract_rollover(
        _manifest(
            decision_at=datetime(2026, 11, 19, 12, tzinfo=UTC),
            selected_instrument_id=current_instrument,
        ),
        _manifest(
            decision_at=datetime(2026, 11, 20, 12, tzinfo=UTC),
            selected_instrument_id=proposed_instrument,
        ),
        current_epoch_id="epoch-2026-11-19",
        boundary=_boundary(),
    )


def test_changed_mapping_creates_pending_rollover_plan():
    plan = _plan("M2611", "M2612")

    assert plan.status == "PENDING_OLD_EPOCH_RECONCILIATION"
    assert plan.old_mapping == (MainContractBinding(PRODUCT, "M2611"),)
    assert plan.new_mapping == (MainContractBinding(PRODUCT, "M2612"),)
    assert plan.changed_products == (PRODUCT,)
    assert plan.next_epoch_id != plan.prior_epoch_id
    assert plan.halt_new_entries_until_ready is True
    assert plan.preserve_old_instrument_event_routing is True
    assert plan.reset_all_cohort_state is True
    assert plan.rewarm_all_members is True
    assert plan.required_checks == ROLLOVER_CHECKS


def test_unchanged_mapping_keeps_epoch_and_has_no_rollover_checks():
    plan = _plan("M2612", "M2612")

    assert plan.status == "NO_MAPPING_CHANGE"
    assert plan.old_mapping == plan.new_mapping == (MainContractBinding(PRODUCT, "M2612"),)
    assert plan.changed_products == ()
    assert plan.next_epoch_id == plan.prior_epoch_id == "epoch-2026-11-19"
    assert plan.halt_new_entries_until_ready is False
    assert plan.preserve_old_instrument_event_routing is False
    assert plan.reset_all_cohort_state is False
    assert plan.rewarm_all_members is False
    assert plan.required_checks == ()
