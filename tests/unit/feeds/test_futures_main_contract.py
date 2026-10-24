"""Pure contracts for point-in-time futures main-contract selection."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from backtrader.feeds.futures_main_contract import (
    CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    CurrentDayQuoteRecord,
    ExchangeTradingCalendar,
    ExchangeTradingDay,
    FuturesContractCatalogRecord,
    FuturesContractRecord,
    MainContractQuerySnapshot,
    MainContractRankingSnapshot,
    MainContractSelectionBlocked,
    QuerySnapshotSourceEvidence,
    ProductKey,
    ProductRankingCoverage,
    RolloverBoundaryEvidence,
    RolloverReadiness,
    authorize_main_contract_rollover,
    plan_main_contract_rollover,
    select_main_contracts,
)


UTC = timezone.utc
PRODUCT = ProductKey("dce", "m")
OTHER_PRODUCT = ProductKey("SHFE", "rb")
CURRENT_DAY = date(2026, 10, 21)
PRIOR_DAY = date(2026, 10, 19)  # 20 October is an exchange holiday in this fixture.
DECISION_AT = datetime(2026, 10, 21, 16, tzinfo=UTC)
SOURCE_AVAILABLE_AT = datetime(2026, 10, 20, 9, tzinfo=UTC)
CATALOG_AVAILABLE_AT = datetime(2026, 10, 1, 0, tzinfo=UTC)
CALENDAR_AVAILABLE_AT = datetime(2026, 10, 1, 0, tzinfo=UTC)
SOURCE_SHA256 = "a" * 64
CATALOG_SHA256 = "b" * 64


def _exchange_days(start=date(2026, 10, 1), through=date(2027, 1, 15)):
    holidays = {date(2026, 10, 20)}
    result = []
    day = start
    while day <= through:
        if day.weekday() < 5 and day not in holidays:
            result.append(day)
        day += timedelta(days=1)
    return tuple(result)


TRADING_DAYS = _exchange_days()


def _calendar(
    *, complete=True, available_at=CALENDAR_AVAILABLE_AT, retrieved_at=None, through=None
):
    coverage_through = through or TRADING_DAYS[-1]
    days = tuple(day for day in TRADING_DAYS if day <= coverage_through)
    retrieved = retrieved_at or (available_at + timedelta(hours=1))
    return ExchangeTradingCalendar(
        exchange_id="DCE",
        source_id="fixture.exchange-calendar",
        version="2026.10",
        available_at=available_at,
        retrieved_at=retrieved,
        coverage_start=TRADING_DAYS[0],
        coverage_through=coverage_through,
        trading_days=days,
        complete=complete,
    )


def _contract(
    instrument_id="M2611",
    *,
    product=PRODUCT,
    asset_type="future",
    is_trading=True,
    expiry=date(2026, 11, 16),
    open_interest=100,
    volume=200,
):
    return FuturesContractRecord(
        product=product,
        instrument_id=instrument_id,
        asset_type=asset_type,
        is_trading=is_trading,
        expiry_date=expiry,
        open_interest=open_interest,
        volume=volume,
    )


def _coverage(
    count,
    *,
    product=PRODUCT,
    expected_instrument_ids=("M2611",),
    ranking_instrument_ids=("M2611",),
    candidate_set_complete=True,
    ranking_values_complete=True,
    finalized=True,
    latest_available=True,
    ranking_trading_day=PRIOR_DAY,
    open_interest_unit="contracts",
    volume_unit="lots",
):
    return ProductRankingCoverage(
        product=product,
        candidate_count=count,
        expected_instrument_ids=expected_instrument_ids,
        ranking_instrument_ids=ranking_instrument_ids,
        candidate_set_complete=candidate_set_complete,
        ranking_values_complete=ranking_values_complete,
        finalized=finalized,
        latest_available=latest_available,
        ranking_trading_day=ranking_trading_day,
        open_interest_unit=open_interest_unit,
        volume_unit=volume_unit,
    )


def _snapshot(
    candidates=None,
    *,
    source_id="fixture.daily-ranking",
    snapshot_id="snapshot-2026-10-19-final",
    source_sha256=SOURCE_SHA256,
    available_at=SOURCE_AVAILABLE_AT,
    retrieved_at=None,
    catalog_source_id="fixture.ctp-instrument-catalog",
    catalog_snapshot_id="catalog-2026-10-01",
    catalog_sha256=CATALOG_SHA256,
    catalog_available_at=CATALOG_AVAILABLE_AT,
    catalog_retrieved_at=None,
    coverage=None,
):
    rows = tuple(candidates if candidates is not None else (_contract(),))
    if coverage is None:
        evidence = (
            _coverage(
                len(rows),
                expected_instrument_ids=tuple(row.instrument_id for row in rows),
                ranking_instrument_ids=tuple(
                    row.instrument_id
                    for row in rows
                    if row.open_interest is not None and row.volume is not None
                ),
            ),
        )
    else:
        evidence = tuple(coverage)
    return MainContractRankingSnapshot(
        source_id=source_id,
        snapshot_id=snapshot_id,
        source_sha256=source_sha256,
        available_at=available_at,
        retrieved_at=retrieved_at or (available_at + timedelta(hours=1)),
        catalog_source_id=catalog_source_id,
        catalog_snapshot_id=catalog_snapshot_id,
        catalog_sha256=catalog_sha256,
        catalog_available_at=catalog_available_at,
        catalog_retrieved_at=catalog_retrieved_at or (catalog_available_at + timedelta(hours=1)),
        coverage=evidence,
        candidates=rows,
    )


def _select(
    snapshot=None,
    *,
    products=(PRODUCT,),
    current_day=CURRENT_DAY,
    calendar=None,
    decision_at=DECISION_AT,
):
    return select_main_contracts(
        snapshot if snapshot is not None else _snapshot(),
        products,
        (ExchangeTradingDay("DCE", current_day),),
        (calendar or _calendar(),),
        decision_at=decision_at,
    )


def _query_source(
    source_kind,
    *,
    count,
    source_id=None,
    snapshot_id=None,
    sha256=None,
    request_id=41,
    generation=7,
    trading_day=CURRENT_DAY,
    started_at=datetime(2026, 10, 21, 15, 56, tzinfo=UTC),
    completed_at=datetime(2026, 10, 21, 15, 57, tzinfo=UTC),
    retrieved_at=datetime(2026, 10, 21, 15, 58, tzinfo=UTC),
    complete=True,
    is_last_seen=True,
):
    return QuerySnapshotSourceEvidence(
        source_id=source_id or "fixture.ctp.{}".format(source_kind),
        source_kind=source_kind,
        snapshot_id=snapshot_id or "generation-7-request-{}".format(request_id),
        source_sha256=sha256 or ("c" if source_kind == "instruments" else "d") * 64,
        request_id=request_id,
        connection_generation=generation,
        trading_day=trading_day,
        started_at=started_at,
        completed_at=completed_at,
        retrieved_at=retrieved_at,
        complete=complete,
        is_last_seen=is_last_seen,
        record_count=count,
    )


def _catalog(
    instrument_id,
    *,
    product=PRODUCT,
    asset_type="future",
    is_trading=True,
    expiry=date(2026, 11, 16),
    product_class="1",
):
    return FuturesContractCatalogRecord(
        product=product,
        instrument_id=instrument_id,
        asset_type=asset_type,
        is_trading=is_trading,
        expiry_date=expiry,
        product_class=product_class,
    )


def _query_quote(
    instrument_id,
    *,
    exchange_id="DCE",
    trading_day=CURRENT_DAY,
    open_interest=100,
    volume=200,
    action_day="20261021",
    update_time="08:00:00",
    update_millisec=500,
):
    return CurrentDayQuoteRecord(
        exchange_id=exchange_id,
        instrument_id=instrument_id,
        trading_day=trading_day,
        open_interest=open_interest,
        volume=volume,
        action_day=action_day,
        update_time=update_time,
        update_millisec=update_millisec,
    )


def _query_snapshot(catalog=None, quotes=None, **changes):
    catalog_rows = tuple(
        catalog
        if catalog is not None
        else (
            _catalog("M2611"),
            _catalog("M2612", expiry=date(2026, 12, 15)),
        )
    )
    quote_rows = tuple(
        quotes
        if quotes is not None
        else (
            _query_quote("M2611"),
            _query_quote("M2612", open_interest=100, volume=200),
        )
    )
    values = {
        "catalog_source": _query_source("instruments", count=len(catalog_rows)),
        "quote_source": _query_source(
            "depth_market_data",
            count=len(quote_rows),
            started_at=datetime(2026, 10, 21, 15, 57, tzinfo=UTC),
            completed_at=datetime(2026, 10, 21, 15, 58, tzinfo=UTC),
            retrieved_at=datetime(2026, 10, 21, 15, 59, tzinfo=UTC),
        ),
        "catalog_records": catalog_rows,
        "quote_records": quote_rows,
        "session_trading_day_before": CURRENT_DAY,
        "session_trading_day_after": CURRENT_DAY,
        "session_generation_before": 7,
        "session_generation_after": 7,
    }
    values.update(changes)
    return MainContractQuerySnapshot(**values)


def _query_select(snapshot=None, *, products=(PRODUCT,), decision_at=DECISION_AT, **changes):
    return select_main_contracts(
        snapshot if snapshot is not None else _query_snapshot(),
        products,
        (ExchangeTradingDay("DCE", CURRENT_DAY),),
        (_calendar(),),
        decision_at=decision_at,
        policy=changes.get("policy", CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY),
    )


def test_ranks_complete_prior_day_pool_and_preserves_provider_instrument_ids():
    candidates = (
        _contract("M2611", open_interest=100, volume=200),
        _contract("M2612", expiry=date(2026, 12, 15), open_interest=100, volume=201),
        _contract("m2701", expiry=date(2027, 1, 15), open_interest=100, volume=201),
        _contract("M2610", open_interest=101, volume=1),
    )
    manifest = _select(_snapshot(candidates))

    assert manifest.status == "READY"
    assert manifest.products[0].expected_prior_trading_day == PRIOR_DAY
    assert manifest.products[0].ranking_trading_day == PRIOR_DAY
    assert manifest.products[0].ranked_instrument_ids == (
        "M2610",
        "M2612",
        "m2701",
        "M2611",
    )
    assert manifest.selected_mapping() == ((PRODUCT, "M2610"),)
    assert [row.rank for row in manifest.candidates] == [1, 2, 3, 4]


def test_tie_break_order_is_volume_then_expiry_then_exact_code():
    candidates = (
        _contract("M2612", expiry=date(2026, 11, 16), open_interest=100, volume=200),
        _contract("M2611", expiry=date(2026, 11, 16), open_interest=100, volume=200),
        _contract("M2610", expiry=date(2026, 11, 16), open_interest=100, volume=201),
    )
    manifest = _select(_snapshot(candidates))

    assert manifest.products[0].ranked_instrument_ids == ("M2610", "M2611", "M2612")


@pytest.mark.parametrize("invalid_case", ("missing", "duplicate", "blocked", "no_code", "extra"))
def test_ready_manifest_rejects_incomplete_or_conflicting_mapping(invalid_case):
    manifest = _select()
    product = manifest.products[0]
    products = {
        "missing": (),
        "duplicate": (product, product),
        "blocked": (replace(product, status="BLOCKED"),),
        "no_code": (replace(product, selected_instrument_id=None),),
        "extra": (product, replace(product, product=OTHER_PRODUCT)),
    }[invalid_case]

    with pytest.raises(MainContractSelectionBlocked, match="incomplete mapping"):
        replace(manifest, products=products).selected_mapping()


def test_calendar_uses_exchange_sessions_across_weekends_and_holidays():
    calendar = _calendar()
    assert calendar.previous_complete_trading_day(date(2026, 10, 21)) == date(2026, 10, 19)
    assert calendar.trading_days_to_expiry(date(2026, 10, 21), date(2026, 11, 16)) == sum(
        date(2026, 10, 21) < day <= date(2026, 11, 16) for day in TRADING_DAYS
    )
    with pytest.raises(ValueError, match="date, not a datetime"):
        ExchangeTradingDay("DCE", datetime(2026, 10, 21, tzinfo=UTC))


@pytest.mark.parametrize(
    "record, expected_reason",
    [
        (
            _contract("M888", open_interest=None, volume=None),
            "NOT_ACTUAL_MONTH_CONTRACT",
        ),
        (
            _contract("M2611-C-3000", asset_type="option", open_interest=None, volume=None),
            "NOT_ORDINARY_FUTURE",
        ),
        (
            _contract("M2611", is_trading=False, open_interest=None, volume=None),
            "NOT_TRADING",
        ),
        (
            _contract("M2610", expiry=CURRENT_DAY, open_interest=None, volume=None),
            "EXPIRED_OR_EXPIRY_DAY",
        ),
        (
            _contract("M2610", expiry=date(2026, 10, 26), open_interest=None, volume=None),
            "EXPIRY_TOO_NEAR",
        ),
    ],
)
def test_known_non_candidates_are_retained_as_explicit_exclusions(record, expected_reason):
    valid = _contract("M2612", expiry=date(2026, 12, 15), open_interest=3, volume=3)
    manifest = _select(_snapshot((record, valid)))

    assert manifest.status == "READY"
    assert manifest.products[0].selected_instrument_id == "M2612"
    assert manifest.products[0].excluded_instrument_ids == (record.instrument_id,)
    assessment = next(
        item for item in manifest.candidates if item.instrument_id == record.instrument_id
    )
    assert assessment.status == "EXCLUDED"
    assert assessment.reason == expected_reason


def test_expiry_outside_calendar_uses_a_safe_lower_bound_or_blocks_if_unproven():
    record = _contract("M2701", expiry=date(2027, 1, 15))
    sufficient_calendar = _calendar(through=date(2026, 12, 31))
    safe_manifest = _select(_snapshot((record,)), calendar=sufficient_calendar)

    assert safe_manifest.status == "READY"
    assert safe_manifest.products[0].selected_instrument_id == "M2701"
    assert safe_manifest.candidates[0].trading_days_to_expiry is None
    assert safe_manifest.candidates[0].trading_days_to_expiry_lower_bound >= 5
    assert safe_manifest.candidates[0].expiry_distance_exact is False

    insufficient_calendar = _calendar(through=date(2026, 10, 26))
    blocked_manifest = _select(_snapshot((record,)), calendar=insufficient_calendar)
    assert blocked_manifest.status == "BLOCKED"
    assert "EXPIRY_SAFETY_UNPROVEN" in blocked_manifest.blockers
    assert blocked_manifest.candidates[0].reason == "EXPIRY_SAFETY_UNPROVEN"
    assert blocked_manifest.candidates[0].trading_days_to_expiry is None
    assert blocked_manifest.candidates[0].trading_days_to_expiry_lower_bound == 3
    with pytest.raises(MainContractSelectionBlocked):
        blocked_manifest.selected_mapping()


@pytest.mark.parametrize(
    "coverage_changes, expected_blocker",
    [
        ({"candidate_set_complete": False}, "CANDIDATE_SET_INCOMPLETE"),
        ({"candidate_count": 2}, "CANDIDATE_COUNT_MISMATCH"),
        ({"ranking_values_complete": False}, "RANKING_VALUES_INCOMPLETE"),
        ({"finalized": False}, "RANKING_NOT_FINALIZED"),
        ({"latest_available": False}, "RANKING_SNAPSHOT_NOT_LATEST"),
        ({"ranking_trading_day": date(2026, 10, 16)}, "RANKING_STALE"),
        ({"ranking_trading_day": date(2026, 10, 21)}, "RANKING_DAY_LOOKAHEAD"),
        ({"ranking_trading_day": None}, "RANKING_TRADING_DAY_UNAVAILABLE"),
        ({"open_interest_unit": None}, "RANKING_UNIT_UNAVAILABLE"),
        ({"volume_unit": None}, "RANKING_UNIT_UNAVAILABLE"),
    ],
)
def test_incomplete_or_wrong_day_coverage_never_yields_a_mapping(
    coverage_changes, expected_blocker
):
    row = _contract()
    coverage = replace(_coverage(1), **coverage_changes)
    manifest = _select(_snapshot((row,), coverage=(coverage,)))

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers
    assert manifest.products[0].selected_instrument_id is None
    assert manifest.products[0].ranked_instrument_ids == ()
    with pytest.raises(MainContractSelectionBlocked):
        manifest.selected_mapping()


def test_duplicate_candidate_or_coverage_rows_block_the_entire_product():
    record = _contract()
    duplicate_records = _select(_snapshot((record, record)))
    duplicate_coverage = _select(_snapshot((record,), coverage=(_coverage(1), _coverage(1))))

    assert "DUPLICATE_CONTRACT_RECORD" in duplicate_records.blockers
    assert duplicate_records.status == "BLOCKED"
    assert "DUPLICATE_PRODUCT_COVERAGE" in duplicate_coverage.blockers
    assert duplicate_coverage.status == "BLOCKED"


def test_catalog_expected_ids_and_retrieved_ranking_rows_are_checked_against_actual_rows():
    record = _contract()
    wrong_catalog_ids = _snapshot(
        (record,),
        coverage=(
            _coverage(
                1,
                expected_instrument_ids=("M2612",),
                ranking_instrument_ids=("M2611",),
            ),
        ),
    )
    missing_ranking_row = _snapshot(
        (record,),
        coverage=(
            _coverage(
                1,
                expected_instrument_ids=("M2611",),
                ranking_instrument_ids=(),
            ),
        ),
    )
    extra_ranking_row = _snapshot(
        (record,),
        coverage=(
            _coverage(
                1,
                expected_instrument_ids=("M2611",),
                ranking_instrument_ids=("M2611", "M2612"),
            ),
        ),
    )

    catalog_manifest = _select(wrong_catalog_ids)
    missing_row_manifest = _select(missing_ranking_row)
    extra_row_manifest = _select(extra_ranking_row)
    assert "CANDIDATE_ID_SET_MISMATCH" in catalog_manifest.blockers
    assert "RANKING_ROW_MISSING_FOR_ELIGIBLE_CANDIDATE" in missing_row_manifest.blockers
    assert "RANKING_ID_OUTSIDE_CANDIDATE_SET" in extra_row_manifest.blockers
    assert all(
        manifest.status == "BLOCKED"
        for manifest in (catalog_manifest, missing_row_manifest, extra_row_manifest)
    )


@pytest.mark.parametrize("bad_value", [None, -1, float("nan"), float("inf"), True, "100"])
def test_missing_or_invalid_ranking_values_block_instead_of_falling_back(bad_value):
    manifest = _select(_snapshot((_contract(open_interest=bad_value),)))

    assert manifest.status == "BLOCKED"
    assert "RANKING_VALUE_MISSING_OR_INVALID" in manifest.blockers
    assert manifest.products[0].selected_instrument_id is None


def test_unknown_asset_or_trading_status_blocks_complete_pool():
    unknown_asset = _select(_snapshot((_contract(asset_type="unknown"),)))
    unknown_trading = _select(_snapshot((_contract(is_trading=None),)))

    assert "ASSET_TYPE_UNKNOWN" in unknown_asset.blockers
    assert "TRADING_STATUS_UNKNOWN" in unknown_trading.blockers
    assert unknown_asset.status == unknown_trading.status == "BLOCKED"


@pytest.mark.parametrize(
    "snapshot_changes, expected_blocker",
    [
        ({"source_id": ""}, "RANKING_SOURCE_ID_MISSING"),
        ({"source_id": " fixture "}, "RANKING_SOURCE_ID_MISSING"),
        ({"snapshot_id": None}, "RANKING_SNAPSHOT_ID_MISSING"),
        ({"source_sha256": "not-a-digest"}, "RANKING_SOURCE_DIGEST_INVALID"),
        (
            {"available_at": datetime(2026, 10, 20, 9)},
            "RANKING_AVAILABLE_AT_INVALID",
        ),
        (
            {"available_at": datetime(2026, 10, 22, 9, tzinfo=UTC)},
            "RANKING_NOT_AVAILABLE_AT_DECISION",
        ),
        (
            {"retrieved_at": datetime(2026, 10, 20, 9)},
            "RANKING_RETRIEVED_AT_INVALID",
        ),
        (
            {"retrieved_at": datetime(2026, 10, 22, 9, tzinfo=UTC)},
            "RANKING_RETRIEVED_AFTER_DECISION",
        ),
        (
            {"retrieved_at": datetime(2026, 10, 20, 8, tzinfo=UTC)},
            "RANKING_RETRIEVED_BEFORE_AVAILABLE",
        ),
    ],
)
def test_invalid_or_future_source_provenance_is_blocked_and_serializable(
    snapshot_changes, expected_blocker
):
    snapshot = replace(_snapshot(), **snapshot_changes)
    manifest = _select(snapshot)

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers
    assert manifest.candidates[0].open_interest is None
    assert manifest.candidates[0].volume is None
    assert manifest.products[0].selected_instrument_id is None
    assert isinstance(manifest.to_dict(), dict)
    assert len(manifest.manifest_sha256) == 64


@pytest.mark.parametrize(
    "snapshot_changes, expected_blocker",
    [
        ({"catalog_source_id": " "}, "CATALOG_SOURCE_ID_MISSING"),
        ({"catalog_snapshot_id": None}, "CATALOG_SNAPSHOT_ID_MISSING"),
        ({"catalog_sha256": "invalid"}, "CATALOG_SOURCE_DIGEST_INVALID"),
        (
            {"catalog_available_at": datetime(2026, 10, 21, 17, tzinfo=UTC)},
            "CATALOG_NOT_AVAILABLE_AT_DECISION",
        ),
        (
            {"catalog_retrieved_at": datetime(2026, 10, 21, 17, tzinfo=UTC)},
            "CATALOG_RETRIEVED_AFTER_DECISION",
        ),
        (
            {"catalog_retrieved_at": datetime(2026, 9, 30, 23, tzinfo=UTC)},
            "CATALOG_RETRIEVED_BEFORE_AVAILABLE",
        ),
        (
            {"catalog_retrieved_at": datetime(2026, 10, 1, 1)},
            "CATALOG_RETRIEVED_AT_INVALID",
        ),
    ],
)
def test_catalog_provenance_is_point_in_time_and_separate_from_ranking_source(
    snapshot_changes, expected_blocker
):
    manifest = _select(replace(_snapshot(), **snapshot_changes))

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers
    assert manifest.products[0].selected_instrument_id is None
    assert manifest.candidates[0].open_interest is None
    assert manifest.candidates[0].volume is None
    projection = manifest.to_dict()
    assert projection["source"]["source_id"] == "fixture.daily-ranking"
    assert projection["source"]["catalog"]["source_id"] in (
        "fixture.ctp-instrument-catalog",
        None,
    )


def test_manifest_serializes_both_exact_source_provenances_and_catalog_coverage_ids():
    manifest = _select()
    projection = manifest.to_dict()

    assert projection["source"] == {
        "source_id": "fixture.daily-ranking",
        "snapshot_id": "snapshot-2026-10-19-final",
        "sha256": SOURCE_SHA256,
        "available_at": "2026-10-20T09:00:00Z",
        "retrieved_at": "2026-10-20T10:00:00Z",
        "catalog": {
            "source_id": "fixture.ctp-instrument-catalog",
            "snapshot_id": "catalog-2026-10-01",
            "sha256": CATALOG_SHA256,
            "available_at": "2026-10-01T00:00:00Z",
            "retrieved_at": "2026-10-01T01:00:00Z",
        },
    }
    assert projection["coverage"][0]["expected_instrument_ids"] == ["M2611"]
    assert projection["coverage"][0]["ranking_instrument_ids"] == ["M2611"]


def test_unavailable_source_missing_coverage_and_empty_pool_fail_closed():
    missing_source = select_main_contracts(
        None,
        (PRODUCT,),
        (ExchangeTradingDay("DCE", CURRENT_DAY),),
        (_calendar(),),
        decision_at=DECISION_AT,
    )
    missing_coverage = _select(_snapshot((_contract(),), coverage=()))
    empty_pool = _select(
        _snapshot(
            (),
            coverage=(_coverage(0, expected_instrument_ids=(), ranking_instrument_ids=()),),
        )
    )

    assert "RANKING_SOURCE_UNAVAILABLE" in missing_source.blockers
    assert "PRODUCT_COVERAGE_UNAVAILABLE" in missing_coverage.blockers
    assert empty_pool.status == "BLOCKED"
    assert "NO_ELIGIBLE_MONTH_FUTURES" in empty_pool.blockers
    with pytest.raises(MainContractSelectionBlocked):
        missing_source.selected_mapping()


def test_missing_stale_or_future_calendar_blocks_selection():
    no_calendar = select_main_contracts(
        _snapshot(),
        (PRODUCT,),
        (ExchangeTradingDay("DCE", CURRENT_DAY),),
        (),
        decision_at=DECISION_AT,
    )
    incomplete_calendar = _select(_snapshot(), calendar=_calendar(complete=False))
    future_calendar = _select(
        _snapshot(),
        calendar=_calendar(available_at=datetime(2026, 10, 22, tzinfo=UTC)),
    )
    retrieved_late_calendar = _select(
        _snapshot(),
        calendar=_calendar(retrieved_at=datetime(2026, 10, 22, tzinfo=UTC)),
    )
    no_current_day = select_main_contracts(
        _snapshot(), (), (), (_calendar(),), decision_at=DECISION_AT
    )

    assert "EXCHANGE_CALENDAR_UNAVAILABLE" in no_calendar.blockers
    assert "EXCHANGE_CALENDAR_INCOMPLETE" in incomplete_calendar.blockers
    assert "CALENDAR_NOT_AVAILABLE_AT_DECISION" in future_calendar.blockers
    assert "CALENDAR_RETRIEVED_AFTER_DECISION" in retrieved_late_calendar.blockers
    assert no_current_day.status == "BLOCKED"
    assert "TARGET_PRODUCT_POOL_EMPTY" in no_current_day.blockers


def test_non_target_products_are_recorded_without_entering_the_ranked_mapping():
    extra = _contract("RB2611", product=OTHER_PRODUCT, expiry=date(2026, 11, 16))
    extra_coverage = _coverage(
        1,
        product=OTHER_PRODUCT,
        expected_instrument_ids=("RB2611",),
        ranking_instrument_ids=("RB2611",),
    )
    manifest = _select(_snapshot((_contract(), extra), coverage=(_coverage(1), extra_coverage)))

    assert manifest.status == "READY"
    assert manifest.selected_mapping() == ((PRODUCT, "M2611"),)
    out_of_scope = next(item for item in manifest.candidates if item.product == OTHER_PRODUCT)
    assert out_of_scope.status == "OUT_OF_SCOPE"
    assert out_of_scope.reason == "OUTSIDE_TARGET_POOL"


def test_manifest_is_immutable_deterministic_and_returns_fresh_json_data():
    candidates = (
        _contract("M2612", expiry=date(2026, 12, 15), open_interest=10),
        _contract("M2611", open_interest=20),
    )
    left = _select(_snapshot(candidates))
    right = _select(_snapshot(tuple(reversed(candidates))))

    assert left.manifest_sha256 == right.manifest_sha256
    projection = left.to_dict()
    projection["products"].clear()
    assert left.products
    assert left.manifest_sha256 == right.manifest_sha256
    with pytest.raises(FrozenInstanceError):
        left.status = "READY"


def test_current_query_mode_uses_exact_equal_weight_score_and_audits_native_times():
    catalog = (
        _catalog("M2611"),
        _catalog("M2612", expiry=date(2026, 12, 15)),
        _catalog("M2613", is_trading=False),
        _catalog("M2610", expiry=date(2026, 10, 26)),
        _catalog("M2611-C-3000", asset_type="option", expiry=None, product_class="2"),
        _catalog("M2611-combo", asset_type=None, expiry=None, product_class="3"),
    )
    quotes = (
        _query_quote("M2611", open_interest=100, volume=0, update_time="08:00:00"),
        _query_quote("M2612", open_interest=0, volume=200, update_time="08:00:00"),
    )
    manifest = _query_select(_query_snapshot(catalog, quotes))

    assert manifest.status == "READY"
    assert manifest.products[0].expected_prior_trading_day is None
    assert manifest.products[0].ranking_trading_day == CURRENT_DAY
    assert manifest.products[0].selected_instrument_id == "M2612"
    assert manifest.products[0].selected_score == "100.0"
    assert manifest.selected_mapping() == ((PRODUCT, "M2612"),)
    by_id = {row.instrument_id: row for row in manifest.candidates}
    assert by_id["M2611"].ranking_score == "50.0"
    assert by_id["M2611"].action_day == "20261021"
    assert by_id["M2611"].update_time == "08:00:00"
    assert by_id["M2610"].status == "EXCLUDED"
    assert by_id["M2610"].reason == "EXPIRY_TOO_NEAR"
    assert by_id["M2613"].reason == "NOT_TRADING"
    assert by_id["M2611-C-3000"].reason == "NOT_ORDINARY_FUTURE"
    assert by_id["M2611-combo"].status == "EXCLUDED"
    assert by_id["M2611-combo"].reason == "NOT_ORDINARY_FUTURE"
    projection = manifest.to_dict()
    assert projection["schema"] == "backtrader.futures_main_contract_manifest.v2"
    assert projection["policy"]["policy_id"] == "ctp_query_snapshot_equal_weight_v1"
    assert projection["policy"]["score_formula"] == "0.5 * open_interest + 0.5 * volume"
    assert projection["query_snapshot"]["kind"].endswith("NOT_FINALIZED_EOD")
    assert projection["query_snapshot"]["quote_source"]["available_at"] == ("2026-10-21T15:58:00Z")
    assert projection["query_snapshot"]["quote_records"][0]["update_time"] == "08:00:00"
    assert manifest.query_coverage[0].expected_quote_instrument_ids == ("M2611", "M2612")


def test_equal_weight_score_arithmetic_and_sort_are_independent_of_decimal_context():
    catalog = (_catalog("M2611"), _catalog("M2612", expiry=date(2026, 12, 15)))
    quotes = (
        _query_quote(
            "M2611",
            open_interest=Decimal("100000000000000000000000000000.1"),
            volume=Decimal("0"),
        ),
        _query_quote(
            "M2612",
            open_interest=Decimal("100000000000000000000000000000"),
            volume=Decimal("0.2"),
        ),
    )
    with localcontext() as context:
        context.prec = 2
        manifest = _query_select(_query_snapshot(catalog, quotes))

    assert manifest.status == "READY"
    assert manifest.products[0].selected_instrument_id == "M2612"
    assert manifest.products[0].selected_score == "50000000000000000000000000000.10"
    assert manifest.candidates[0].ranking_score == "50000000000000000000000000000.10"


def test_query_snapshot_ties_use_open_interest_volume_then_expiry_and_exact_id():
    catalog = (
        _catalog("M2612", expiry=date(2026, 12, 15)),
        _catalog("M2611"),
        _catalog("M2701", expiry=date(2027, 1, 15)),
    )
    quotes = (
        _query_quote("M2612", open_interest=10, volume=10),
        _query_quote("M2611", open_interest=11, volume=9),
        _query_quote("M2701", open_interest=12, volume=8),
    )
    manifest = _query_select(_query_snapshot(catalog, quotes))

    assert manifest.status == "READY"
    assert manifest.products[0].ranked_instrument_ids == ("M2701", "M2611", "M2612")


def test_query_snapshot_equal_metrics_tie_break_by_expiry_then_exact_id():
    catalog = (
        _catalog("M2612", expiry=date(2026, 12, 15)),
        _catalog("m2611"),
        _catalog("M2701", expiry=date(2027, 1, 15)),
        _catalog("M2611"),
    )
    quotes = tuple(
        _query_quote(item.instrument_id, open_interest=10, volume=10) for item in catalog
    )
    manifest = _query_select(_query_snapshot(catalog, quotes))

    assert manifest.status == "READY"
    assert manifest.products[0].ranked_instrument_ids == ("M2611", "m2611", "M2612", "M2701")


@pytest.mark.parametrize(
    "snapshot_change, expected_blocker",
    [
        (
            {"catalog_source": replace(_query_source("instruments", count=2), complete=False)},
            "CATALOG_QUERY_QUERY_INCOMPLETE",
        ),
        (
            {
                "quote_source": replace(
                    _query_source("depth_market_data", count=2), is_last_seen=False
                )
            },
            "QUOTE_QUERY_QUERY_TERMINAL_NOT_SEEN",
        ),
        (
            {
                "quote_source": replace(
                    _query_source("depth_market_data", count=2),
                    completed_at=datetime(2026, 10, 21, 15, 54, tzinfo=UTC),
                    retrieved_at=datetime(2026, 10, 21, 15, 55, tzinfo=UTC),
                )
            },
            "QUOTE_QUERY_SNAPSHOT_STALE",
        ),
        ({"session_generation_after": 8}, "QUERY_SESSION_CHANGED_DURING_COLLECTION"),
        (
            {
                "quote_source": replace(
                    _query_source("depth_market_data", count=2), connection_generation=8
                )
            },
            "CATALOG_QUOTE_GENERATION_MISMATCH",
        ),
        (
            {"session_trading_day_after": date(2026, 10, 22)},
            "QUERY_SESSION_TRADING_DAY_CHANGED_DURING_COLLECTION",
        ),
        (
            {"catalog_source": replace(_query_source("instruments", count=2), record_count=1)},
            "CATALOG_QUERY_RECORD_COUNT_MISMATCH",
        ),
    ],
)
def test_query_provenance_completeness_age_generation_and_day_fail_closed(
    snapshot_change, expected_blocker
):
    changed = replace(_query_snapshot(), **snapshot_change)
    manifest = _query_select(changed)

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers
    with pytest.raises(MainContractSelectionBlocked):
        manifest.selected_mapping()


def test_query_collection_span_and_target_session_day_are_checked():
    snapshot = _query_snapshot()
    long_collection = replace(
        snapshot,
        catalog_source=replace(
            snapshot.catalog_source,
            started_at=datetime(2026, 10, 21, 15, 50, tzinfo=UTC),
        ),
    )
    span_manifest = _query_select(long_collection)
    wrong_day = select_main_contracts(
        snapshot,
        (PRODUCT,),
        (ExchangeTradingDay("DCE", date(2026, 10, 22)),),
        (_calendar(),),
        decision_at=DECISION_AT,
        policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    )

    assert "QUERY_COLLECTION_SPAN_EXCEEDED" in span_manifest.blockers
    assert "CURRENT_TRADING_DAY_MISMATCH" in wrong_day.blockers


@pytest.mark.parametrize(
    "quotes, expected_blocker",
    [
        ((_query_quote("M2611"),), "QUOTE_ROW_MISSING_FOR_CANDIDATE"),
        (
            (_query_quote("M2611"), _query_quote("M2611"), _query_quote("M2612")),
            "DUPLICATE_QUOTE_ROW",
        ),
        (
            (_query_quote("M2611"), _query_quote("M2612"), _query_quote("RB2611")),
            "QUOTE_ID_NOT_IN_CATALOG",
        ),
        (
            (
                _query_quote("M2611", trading_day=date(2026, 10, 20)),
                _query_quote("M2612"),
            ),
            "QUOTE_TRADING_DAY_MISMATCH",
        ),
    ],
)
def test_quote_id_coverage_duplicates_and_cross_day_rows_block(quotes, expected_blocker):
    manifest = _query_select(_query_snapshot(quotes=quotes))

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers


@pytest.mark.parametrize("bad_value", [None, -1, Decimal("NaN"), Decimal("Infinity")])
def test_invalid_query_ranking_metrics_block_without_shrinking_candidate_pool(bad_value):
    snapshot = _query_snapshot(
        quotes=(
            _query_quote("M2611", open_interest=bad_value),
            _query_quote("M2612"),
        )
    )
    manifest = _query_select(snapshot)

    assert manifest.status == "BLOCKED"
    assert "RANKING_VALUE_MISSING_OR_INVALID" in manifest.blockers
    assert manifest.products[0].selected_instrument_id is None


def test_query_metric_range_and_nonfinite_values_are_blocked_and_json_safe():
    out_of_range = _query_select(
        _query_snapshot(
            quotes=(
                _query_quote("M2611", open_interest=Decimal("1e100000000")),
                _query_quote("M2612"),
            )
        )
    )
    assert out_of_range.status == "BLOCKED"
    assert "RANKING_VALUE_RANGE_UNSUPPORTED" in out_of_range.blockers
    assert out_of_range.to_dict()["query_snapshot"]["quote_records"][0]["open_interest"] == {
        "value": "<decimal-out-of-supported-range>",
        "valid_nonnegative_finite": False,
    }
    assert len(out_of_range.manifest_sha256) == 64

    nonfinite = _query_select(
        _query_snapshot(
            quotes=(
                _query_quote("M2611", open_interest=float("nan")),
                _query_quote("M2612"),
            )
        )
    )
    assert nonfinite.status == "BLOCKED"
    assert json.dumps(nonfinite.to_dict(), allow_nan=False)


def test_catalog_duplicates_and_explicit_policy_mode_fail_closed():
    duplicate_catalog = _query_snapshot(
        catalog=(_catalog("M2611"), _catalog("M2611"), _catalog("M2612")),
        quotes=(_query_quote("M2611"), _query_quote("M2612")),
    )
    blocked = _query_select(duplicate_catalog)

    assert blocked.status == "BLOCKED"
    assert "DUPLICATE_CATALOG_INSTRUMENT_ID" in blocked.blockers
    with pytest.raises(ValueError, match="explicit query-snapshot policy"):
        select_main_contracts(
            _query_snapshot(),
            (PRODUCT,),
            (ExchangeTradingDay("DCE", CURRENT_DAY),),
            (_calendar(),),
            decision_at=DECISION_AT,
        )


@pytest.mark.parametrize(
    "product_class,asset_type,expected_blocker",
    [
        ("9", "future", "CATALOG_PRODUCT_CLASS_UNKNOWN"),
        ("1", "option", "CATALOG_PRODUCT_CLASS_ASSET_TYPE_MISMATCH"),
        (None, "future", "CATALOG_PRODUCT_CLASS_UNKNOWN"),
    ],
)
def test_query_unknown_or_contradictory_product_class_blocks(
    product_class, asset_type, expected_blocker
):
    catalog = (_catalog("M2611", product_class=product_class, asset_type=asset_type),)
    manifest = _query_select(_query_snapshot(catalog, (_query_quote("M2611"),)))

    assert manifest.status == "BLOCKED"
    assert expected_blocker in manifest.blockers


def test_query_catalog_reports_non_target_options_as_explicit_exclusions():
    other_product = ProductKey("DCE", "C")
    catalog = (
        _catalog("M2611"),
        _catalog(
            "C2611-C-3000",
            product=other_product,
            asset_type="option",
            product_class="2",
        ),
    )
    manifest = _query_select(_query_snapshot(catalog, (_query_quote("M2611"),)))
    option = next(item for item in manifest.candidates if item.instrument_id == "C2611-C-3000")

    assert manifest.status == "READY"
    assert option.status == "EXCLUDED"
    assert option.reason == "NOT_ORDINARY_FUTURE"


def _rollover_manifests():
    current_decision = datetime(2026, 10, 20, 16, tzinfo=UTC)
    proposed_decision = datetime(2026, 10, 21, 17, tzinfo=UTC)
    current = select_main_contracts(
        _snapshot((_contract("M2611", open_interest=200),)),
        (PRODUCT,),
        (ExchangeTradingDay("DCE", date(2026, 10, 21)),),
        (_calendar(),),
        decision_at=current_decision,
    )
    proposed = select_main_contracts(
        _snapshot(
            (_contract("M2612", expiry=date(2026, 12, 15), open_interest=300),),
            snapshot_id="snapshot-2026-10-21-final",
            available_at=datetime(2026, 10, 21, 16, tzinfo=UTC),
            coverage=(
                _coverage(
                    1,
                    expected_instrument_ids=("M2612",),
                    ranking_instrument_ids=("M2612",),
                    ranking_trading_day=date(2026, 10, 21),
                ),
            ),
        ),
        (PRODUCT,),
        (ExchangeTradingDay("DCE", date(2026, 10, 22)),),
        (_calendar(),),
        decision_at=proposed_decision,
    )
    boundary = RolloverBoundaryEvidence(
        boundary_id="DCE-2026-10-22-first-session-open",
        source_id="fixture.session-calendar",
        source_sha256="b" * 64,
        available_at=datetime(2026, 10, 21, 16, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 21, 16, 35, tzinfo=UTC),
        effective_at=datetime(2026, 10, 21, 21, tzinfo=UTC),
        trading_days=(ExchangeTradingDay("DCE", date(2026, 10, 22)),),
    )
    assert current.status == proposed.status == "READY"
    return current, proposed, boundary


def test_controlled_rollover_waits_for_exchange_boundary_and_new_epoch_readiness():
    current, proposed, boundary = _rollover_manifests()
    plan = plan_main_contract_rollover(
        current,
        proposed,
        current_epoch_id="epoch-12",
        boundary=boundary,
    )

    assert plan.status == "PENDING_OLD_EPOCH_RECONCILIATION"
    assert plan.effective_at == boundary.effective_at
    assert plan.changed_products == (PRODUCT,)
    assert plan.halt_new_entries_until_ready is True
    assert plan.preserve_old_instrument_event_routing is True
    assert plan.reset_all_cohort_state is True
    assert plan.rewarm_all_members is True
    assert authorize_main_contract_rollover(plan, None).activation_allowed is False

    readiness = RolloverReadiness(
        old_orders_terminal=True,
        old_positions_flat=True,
        old_order_events_reconciled=True,
        old_state_reconciled=True,
        unknown_order_count=0,
        old_instrument_event_routes_preserved=True,
        all_cohort_state_reset=True,
        all_members_rewarmed=True,
    )
    authorization = authorize_main_contract_rollover(plan, readiness)
    assert authorization.status == "ACTIVATION_CONDITIONS_MET"
    assert authorization.activation_allowed is True
    assert authorization.epoch_id == plan.next_epoch_id
    assert authorization.epoch_id != plan.prior_epoch_id


@pytest.mark.parametrize(
    "changes, expected_blocker",
    [
        ({"old_orders_terminal": False}, "OLD_ORDERS_NOT_TERMINAL"),
        ({"old_positions_flat": False}, "OLD_POSITIONS_NOT_FLAT"),
        ({"old_order_events_reconciled": False}, "OLD_ORDER_EVENTS_NOT_RECONCILED"),
        ({"old_state_reconciled": False}, "OLD_STATE_NOT_RECONCILED"),
        ({"unknown_order_count": 1}, "UNKNOWN_ORDERS_PRESENT"),
        (
            {"old_instrument_event_routes_preserved": False},
            "OLD_INSTRUMENT_EVENT_ROUTES_NOT_PRESERVED",
        ),
        ({"all_cohort_state_reset": False}, "COHORT_STATE_NOT_RESET"),
        ({"all_members_rewarmed": False}, "COHORT_REWARM_INCOMPLETE"),
    ],
)
def test_rollover_activation_stays_blocked_until_every_old_and_new_cohort_check(
    changes, expected_blocker
):
    current, proposed, boundary = _rollover_manifests()
    plan = plan_main_contract_rollover(
        current,
        proposed,
        current_epoch_id="epoch-12",
        boundary=boundary,
    )
    facts = {
        "old_orders_terminal": True,
        "old_positions_flat": True,
        "old_order_events_reconciled": True,
        "old_state_reconciled": True,
        "unknown_order_count": 0,
        "old_instrument_event_routes_preserved": True,
        "all_cohort_state_reset": True,
        "all_members_rewarmed": True,
    }
    facts.update(changes)
    authorization = authorize_main_contract_rollover(plan, RolloverReadiness(**facts))

    assert authorization.activation_allowed is False
    assert expected_blocker in authorization.blockers
    assert authorization.epoch_id == plan.prior_epoch_id


def test_rollover_rejects_wrong_boundary_day_late_evidence_or_policy_change():
    current, proposed, boundary = _rollover_manifests()
    wrong_day = replace(
        boundary,
        trading_days=(ExchangeTradingDay("DCE", date(2026, 10, 23)),),
    )
    late_evidence = replace(
        boundary,
        retrieved_at=datetime(2026, 10, 21, 18, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="does not match"):
        plan_main_contract_rollover(
            current, proposed, current_epoch_id="epoch-12", boundary=wrong_day
        )
    with pytest.raises(ValueError, match="retrieved after selection time"):
        plan_main_contract_rollover(
            current, proposed, current_epoch_id="epoch-12", boundary=late_evidence
        )
    with pytest.raises(ValueError, match="cannot change"):
        plan_main_contract_rollover(
            current,
            replace(proposed, policy=replace(proposed.policy, policy_id="other")),
            current_epoch_id="epoch-12",
            boundary=boundary,
        )


def test_no_mapping_change_keeps_epoch_and_requires_no_old_order_roll():
    current, _proposed, boundary = _rollover_manifests()
    proposed = replace(
        current,
        decision_at=datetime(2026, 10, 21, 17, tzinfo=UTC),
    )
    same_boundary = replace(
        boundary,
        trading_days=(ExchangeTradingDay("DCE", date(2026, 10, 21)),),
    )
    plan = plan_main_contract_rollover(
        current,
        proposed,
        current_epoch_id="epoch-12",
        boundary=same_boundary,
    )
    authorization = authorize_main_contract_rollover(plan, None)

    assert plan.status == "NO_MAPPING_CHANGE"
    assert plan.changed_products == ()
    assert plan.next_epoch_id == "epoch-12"
    assert authorization.status == "NO_MAPPING_CHANGE"
    assert authorization.activation_allowed is True
    assert authorization.activation_required is False
