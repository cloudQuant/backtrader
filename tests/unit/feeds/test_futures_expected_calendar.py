"""Rule-derived 2026 daytime calendars remain explicit and auditable."""

from datetime import date, datetime, timedelta, timezone
import hashlib

import pytest

from backtrader.feeds.futures_expected_calendar import (
    EXCHANGE_ANNUAL_NOTICE_METADATA,
    EXCHANGE_RULE_SOURCE_URLS,
    EXPECTED_RULE_EVIDENCE_MODE,
    RULE_REVIEW_VERSION,
    RULE_REVIEW_RETRIEVED_AT_UTC,
    STATE_COUNCIL_HOLIDAY_REPRODUCTION_URL,
    STATE_COUNCIL_2026_HOLIDAY_RANGES,
    STATE_COUNCIL_2026_MAKEUP_WEEKENDS,
    ExpectedCalendarError,
    build_expected_daytime_calendars,
    expected_2026_trading_days,
)
from backtrader.feeds.futures_main_contract import (
    CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    CurrentDayQuoteRecord,
    ExchangeTradingDay,
    FuturesContractCatalogRecord,
    FuturesContractRecord,
    MainContractQuerySnapshot,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
    QuerySnapshotSourceEvidence,
    select_main_contracts,
)
from backtrader.feeds.futures_sessions import (
    ExpectedRuleEvidence,
    ExchangeSessionCalendar,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionWindow,
    build_common_minute_grid,
    load_exchange_session_calendar,
)


CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")
UTC = timezone.utc
# Historical timestamps below are synthetic fixtures, not source-review facts.
SYNTHETIC_AS_OF = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)
SYNTHETIC_RETRIEVED_AT = datetime(2026, 10, 23, 23, 55, tzinfo=UTC)
CURRENT_DAY = date(2026, 10, 26)

FULL_POOL_SAMPLE = (
    ProductKey("CFFEX", "IF"),
    ProductKey("CZCE", "SR"),
    ProductKey("DCE", "M"),
    ProductKey("GFEX", "LC"),
    ProductKey("INE", "SC"),
    ProductKey("SHFE", "CU"),
)


def _build(products=FULL_POOL_SAMPLE, **kwargs):
    current_days = {product.exchange_id: CURRENT_DAY for product in products}
    kwargs.setdefault("as_of", SYNTHETIC_AS_OF)
    kwargs.setdefault("retrieved_at", SYNTHETIC_RETRIEVED_AT)
    return build_expected_daytime_calendars(
        products,
        current_days,
        **kwargs,
    )


def _local_close_values(grid):
    return tuple(minute.close_time.astimezone(CHINA).strftime("%H:%M") for minute in grid.minutes)


def test_rule_calendar_keeps_full_target_pool_and_daytime_common_grid():
    result = _build()
    assert result.evidence_mode == EXPECTED_RULE_EVIDENCE_MODE
    assert result.target_products == FULL_POOL_SAMPLE
    assert result.rules_manifest_sha256
    assert result.fifth_future_trading_days == (
        ("CFFEX", date(2026, 11, 2)),
        ("CZCE", date(2026, 11, 2)),
        ("DCE", date(2026, 11, 2)),
        ("GFEX", date(2026, 11, 2)),
        ("INE", date(2026, 11, 2)),
        ("SHFE", date(2026, 11, 2)),
    )
    assert {calendar.exchange_id for calendar in result.session_calendars} == {
        product.exchange_id for product in FULL_POOL_SAMPLE
    }
    assert all(
        calendar.evidence_mode == EXPECTED_RULE_EVIDENCE_MODE
        for calendar in result.session_calendars
    )
    assert all(
        calendar.evidence_mode == EXPECTED_RULE_EVIDENCE_MODE
        for calendar in result.trading_calendars
    )
    assert all(
        calendar.source_manifest_sha256 == result.rules_manifest_sha256
        for calendar in result.trading_calendars
    )
    assert all(
        calendar.product_universe
        == tuple(
            product for product in FULL_POOL_SAMPLE if product.exchange_id == calendar.exchange_id
        )
        for calendar in result.session_calendars
    )

    product_days = dict.fromkeys(FULL_POOL_SAMPLE, (CURRENT_DAY,))
    grid = build_common_minute_grid(
        FULL_POOL_SAMPLE,
        result.session_calendars,
        product_days,
        decision_at=SYNTHETIC_AS_OF,
    )
    local_closes = _local_close_values(grid)
    assert len(local_closes) == 195
    assert local_closes[:1] == ("09:31",)
    assert "10:15" in local_closes
    assert "10:16" not in local_closes
    assert "10:30" not in local_closes
    assert "10:31" in local_closes
    assert "11:30" in local_closes
    assert "13:00" not in local_closes
    assert "13:30" not in local_closes
    assert "13:31" in local_closes
    assert local_closes[-1] == "15:00"


def test_emitted_calendar_is_clipped_to_prior_current_and_fifth_future_day():
    result = _build()
    fifth = dict(result.fifth_future_trading_days)
    for calendar in result.session_calendars:
        expected_fifth = fifth[calendar.exchange_id]
        assert calendar.coverage_start == date(2026, 10, 23)
        assert calendar.coverage_through == expected_fifth == date(2026, 11, 2)
        assert calendar.trading_days == (
            date(2026, 10, 23),
            date(2026, 10, 26),
            date(2026, 10, 27),
            date(2026, 10, 28),
            date(2026, 10, 29),
            date(2026, 10, 30),
            date(2026, 11, 2),
        )
        assert len(calendar.product_days) == len(calendar.product_universe) * 7
        assert all(row.trading_day >= calendar.coverage_start for row in calendar.product_days)
        assert all(row.trading_day <= calendar.coverage_through for row in calendar.product_days)


def test_expected_trading_days_close_makeup_weekends_and_2026_holidays():
    days = expected_2026_trading_days("SHFE")
    assert date(2026, 10, 24) not in days
    assert date(2026, 10, 25) not in days
    assert date(2026, 10, 10) in STATE_COUNCIL_2026_MAKEUP_WEEKENDS
    assert date(2026, 10, 10) not in days
    assert tuple(day for day in days if date(2026, 10, 26) <= day <= date(2026, 10, 30)) == (
        date(2026, 10, 26),
        date(2026, 10, 27),
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
    )
    for start, end in STATE_COUNCIL_2026_HOLIDAY_RANGES:
        assert not any(start <= day <= end for day in days)


def test_exchange_closure_overlay_shifts_the_fifth_future_day():
    result = _build(exchange_closures={"SHFE": (date(2026, 10, 27),)})
    fifth = dict(result.fifth_future_trading_days)
    assert fifth["SHFE"] == date(2026, 11, 3)
    assert fifth["DCE"] == date(2026, 11, 2)
    assert date(2026, 10, 27) not in result.calendar_by_exchange["SHFE"].trading_days


def test_expected_rule_evidence_is_not_misrepresented_as_source_bytes_and_roundtrips():
    result = _build()
    calendar = result.session_calendar_by_exchange["CFFEX"]
    source = calendar.source_index[calendar.calendar_source_id]
    assert isinstance(source, ExpectedRuleEvidence)
    evidence_dict = source.to_dict()
    assert evidence_dict["evidence_kind"] == EXPECTED_RULE_EVIDENCE_MODE
    assert evidence_dict["version"] == RULE_REVIEW_VERSION
    assert "source_urls" in evidence_dict
    assert "rules_manifest_sha256" in evidence_dict
    assert "sha256" not in evidence_dict
    assert source.available_at == SYNTHETIC_RETRIEVED_AT
    assert source.retrieved_at == SYNTHETIC_RETRIEVED_AT

    manifest_calendar = result.trading_calendars[0]
    assert manifest_calendar.evidence_mode == EXPECTED_RULE_EVIDENCE_MODE
    assert manifest_calendar.source_manifest_sha256 == result.rules_manifest_sha256
    restored = load_exchange_session_calendar(calendar.to_dict())
    assert restored == calendar
    assert restored.to_main_contract_calendar() == manifest_calendar


def test_current_source_review_and_issuer_notice_metadata_are_bound_without_byte_hashes():
    as_of = RULE_REVIEW_RETRIEVED_AT_UTC + timedelta(seconds=1)
    result = build_expected_daytime_calendars(
        FULL_POOL_SAMPLE,
        {product.exchange_id: CURRENT_DAY for product in FULL_POOL_SAMPLE},
        as_of=as_of,
        retrieved_at=RULE_REVIEW_RETRIEVED_AT_UTC,
    )
    assert RULE_REVIEW_VERSION == "public-rule-review-2026-10-26"
    assert result.retrieved_at == RULE_REVIEW_RETRIEVED_AT_UTC
    assert len(result.rules_manifest_sha256) == 64
    later_retrieval = build_expected_daytime_calendars(
        FULL_POOL_SAMPLE,
        {product.exchange_id: CURRENT_DAY for product in FULL_POOL_SAMPLE},
        as_of=as_of + timedelta(seconds=2),
        retrieved_at=RULE_REVIEW_RETRIEVED_AT_UTC + timedelta(seconds=1),
    )
    assert later_retrieval.rules_manifest_sha256 == result.rules_manifest_sha256
    expected_notices = {
        "DCE": ("大连商品交易所", "大商所发〔2025〕437号"),
        "CZCE": ("郑州商品交易所", "郑商函〔2025〕939号"),
        "CFFEX": ("中国金融期货交易所", "中金所发〔2025〕55号"),
    }
    for exchange, (issuer, notice_id) in expected_notices.items():
        metadata = EXCHANGE_ANNUAL_NOTICE_METADATA[exchange]
        assert metadata["issuer"] == issuer
        assert metadata["notice_id"] == notice_id
        assert metadata["issued_on"] == "2025-12-17"
        assert "third-party portal" in metadata["provenance"]
        assert "not exchange-served bytes" in metadata["byte_identity_limit"]
        assert "raw notice digest not captured" in metadata["byte_identity_limit"]
        calendar = result.session_calendar_by_exchange[exchange]
        source = calendar.source_index[calendar.calendar_source_id]
        assert set(metadata["source_urls"]).issubset(source.source_urls)
        assert STATE_COUNCIL_HOLIDAY_REPRODUCTION_URL in source.source_urls
        assert source.version == RULE_REVIEW_VERSION
        assert source.available_at == RULE_REVIEW_RETRIEVED_AT_UTC
        assert source.retrieved_at == RULE_REVIEW_RETRIEVED_AT_UTC
        assert "sha256" not in source.to_dict()
    assert any(
        "secFutrsLawId=2805291336fd4780a93b6268d93caad0" in url
        for url in EXCHANGE_RULE_SOURCE_URLS["DCE"]
    )
    assert any(
        "27165822h30l.pdf" in url for url in EXCHANGE_RULE_SOURCE_URLS["CFFEX"]
    )
    assert any(
        "27165958okn6.pdf" in url for url in EXCHANGE_RULE_SOURCE_URLS["CFFEX"]
    )


def test_selector_manifest_exposes_expected_rule_mode_and_manifest_digest():
    product = ProductKey("DCE", "M")
    result = _build((product,))
    previous_day = result.calendar_by_exchange["DCE"].previous_complete_trading_day(CURRENT_DAY)
    candidate = FuturesContractRecord(
        product=product,
        instrument_id="M2611",
        asset_type="future",
        is_trading=True,
        expiry_date=date(2026, 11, 16),
        open_interest=100,
        volume=200,
    )
    snapshot = MainContractRankingSnapshot(
        source_id="fixture.daily-eod",
        snapshot_id="eod-2026-10-23",
        source_sha256="a" * 64,
        available_at=SYNTHETIC_RETRIEVED_AT,
        retrieved_at=SYNTHETIC_RETRIEVED_AT,
        catalog_source_id="fixture.ctp-catalog",
        catalog_snapshot_id="catalog-2026-10-23",
        catalog_sha256="b" * 64,
        catalog_available_at=SYNTHETIC_RETRIEVED_AT,
        catalog_retrieved_at=SYNTHETIC_RETRIEVED_AT,
        coverage=(
            ProductRankingCoverage(
                product=product,
                candidate_count=1,
                expected_instrument_ids=(candidate.instrument_id,),
                ranking_instrument_ids=(candidate.instrument_id,),
                candidate_set_complete=True,
                ranking_values_complete=True,
                finalized=True,
                latest_available=True,
                ranking_trading_day=previous_day,
                open_interest_unit="contracts",
                volume_unit="lots",
            ),
        ),
        candidates=(candidate,),
    )
    manifest = select_main_contracts(
        snapshot,
        (product,),
        (ExchangeTradingDay("DCE", CURRENT_DAY),),
        result.trading_calendars,
        decision_at=SYNTHETIC_AS_OF,
    )
    assert manifest.status == "READY"
    calendar = manifest.to_dict()["calendars"][0]
    assert calendar["evidence_mode"] == EXPECTED_RULE_EVIDENCE_MODE
    assert calendar["source_manifest_sha256"] == result.rules_manifest_sha256
    assert "sha256" in calendar


def test_five_day_horizon_excludes_near_expiry_and_proves_far_expiry_lower_bound():
    product = ProductKey("DCE", "M")
    result = _build((product,))
    prior_day = result.calendar_by_exchange["DCE"].previous_complete_trading_day(CURRENT_DAY)
    near = FuturesContractRecord(
        product=product,
        instrument_id="M2610",
        asset_type="future",
        is_trading=True,
        expiry_date=date(2026, 10, 30),
        open_interest=10_000,
        volume=10_000,
    )
    far = FuturesContractRecord(
        product=product,
        instrument_id="M2611",
        asset_type="future",
        is_trading=True,
        expiry_date=date(2026, 11, 16),
        open_interest=100,
        volume=200,
    )
    candidates = (near, far)
    snapshot = MainContractRankingSnapshot(
        source_id="fixture.daily-eod",
        snapshot_id="eod-2026-10-23-near-far",
        source_sha256="c" * 64,
        available_at=SYNTHETIC_RETRIEVED_AT,
        retrieved_at=SYNTHETIC_RETRIEVED_AT,
        catalog_source_id="fixture.ctp-catalog",
        catalog_snapshot_id="catalog-2026-10-23",
        catalog_sha256="d" * 64,
        catalog_available_at=SYNTHETIC_RETRIEVED_AT,
        catalog_retrieved_at=SYNTHETIC_RETRIEVED_AT,
        coverage=(
            ProductRankingCoverage(
                product=product,
                candidate_count=len(candidates),
                expected_instrument_ids=tuple(item.instrument_id for item in candidates),
                ranking_instrument_ids=tuple(item.instrument_id for item in candidates),
                candidate_set_complete=True,
                ranking_values_complete=True,
                finalized=True,
                latest_available=True,
                ranking_trading_day=prior_day,
                open_interest_unit="contracts",
                volume_unit="lots",
            ),
        ),
        candidates=candidates,
    )

    manifest = select_main_contracts(
        snapshot,
        (product,),
        (ExchangeTradingDay("DCE", CURRENT_DAY),),
        result.trading_calendars,
        decision_at=SYNTHETIC_AS_OF,
    )

    assert manifest.status == "READY"
    selection = manifest.products[0]
    assert selection.selected_instrument_id == "M2611"
    assessments = {item.instrument_id: item for item in manifest.candidates}
    assert assessments["M2610"].reason == "EXPIRY_TOO_NEAR"
    assert assessments["M2610"].trading_days_to_expiry == 4
    assert assessments["M2611"].status == "RANKED"
    assert assessments["M2611"].trading_days_to_expiry is None
    assert assessments["M2611"].trading_days_to_expiry_lower_bound == 5


def test_selected_treasury_final_day_overlay_removes_only_that_products_afternoon():
    products = (ProductKey("CFFEX", "TS"), ProductKey("CFFEX", "TF"))
    final_day = date(2026, 11, 2)
    result = _build(
        products,
        selected_contract_last_trading_days={products[0]: (final_day,)},
    )
    calendar = result.session_calendar_by_exchange["CFFEX"]
    rows = {(row.product, row.trading_day): row for row in calendar.product_days}
    ts_row = rows[(products[0], final_day)]
    tf_row = rows[(products[1], final_day)]
    assert tuple(window.session_id for window in ts_row.windows) == ("day-am",)
    assert tuple(window.session_id for window in tf_row.windows) == ("day-am", "day-pm")
    assert tuple(window.end.astimezone(CHINA).strftime("%H:%M") for window in tf_row.windows) == (
        "11:30",
        "15:15",
    )
    assert any("selected contract's exact final-day overlay" in item for item in result.limitations)


def test_timestamps_are_not_backdated_or_used_after_decision():
    with pytest.raises(ExpectedCalendarError, match="RULES_RETRIEVED_AFTER_AS_OF"):
        _build(retrieved_at=SYNTHETIC_AS_OF + timedelta(seconds=1))
    late = _build(retrieved_at=SYNTHETIC_AS_OF)
    with pytest.raises(ValueError, match="SESSION_SOURCE_NOT_AVAILABLE_AT_DECISION"):
        build_common_minute_grid(
            FULL_POOL_SAMPLE,
            late.session_calendars,
            dict.fromkeys(FULL_POOL_SAMPLE, (CURRENT_DAY,)),
            decision_at=SYNTHETIC_AS_OF - timedelta(seconds=1),
        )


def test_unknown_exchange_or_cffex_schedule_classification_fails_closed():
    with pytest.raises(ExpectedCalendarError, match="EXCHANGE_UNSUPPORTED"):
        _build((ProductKey("UNKNOWN", "X"),))
    with pytest.raises(ExpectedCalendarError, match="CFFEX_PRODUCT_SESSION_CLASSIFICATION_UNKNOWN"):
        _build((ProductKey("CFFEX", "NEW"),))


def test_weekend_makeup_day_and_holiday_cannot_be_current_ctp_trading_day():
    with pytest.raises(ExpectedCalendarError, match="CURRENT_DAY_NOT_EXPECTED_TRADING_DAY"):
        build_expected_daytime_calendars(
            (ProductKey("DCE", "M"),),
            {"DCE": date(2026, 10, 10)},
            as_of=SYNTHETIC_AS_OF,
            retrieved_at=SYNTHETIC_RETRIEVED_AT,
        )
    with pytest.raises(ExpectedCalendarError, match="CURRENT_DAY_NOT_EXPECTED_TRADING_DAY"):
        build_expected_daytime_calendars(
            (ProductKey("DCE", "M"),),
            {"DCE": date(2026, 10, 5)},
            as_of=SYNTHETIC_AS_OF,
            retrieved_at=SYNTHETIC_RETRIEVED_AT,
        )


def test_calendar_refuses_to_invent_a_2027_horizon():
    with pytest.raises(ExpectedCalendarError, match="FIVE_DAY_HORIZON_OUTSIDE_SUPPORTED_2026"):
        build_expected_daytime_calendars(
            (ProductKey("SHFE", "CU"),),
            {"SHFE": date(2026, 12, 28)},
            as_of=SYNTHETIC_AS_OF,
            retrieved_at=SYNTHETIC_RETRIEVED_AT,
        )


def test_first_supported_trading_day_supports_query_selection_without_prior_day():
    product = ProductKey("DCE", "M")
    current = date(2026, 1, 5)
    retrieved_at = datetime(2026, 1, 5, 1, 2, tzinfo=UTC)
    decision_at = datetime(2026, 1, 5, 1, 4, tzinfo=UTC)
    result = build_expected_daytime_calendars(
        (product,),
        {"DCE": current},
        as_of=decision_at,
        retrieved_at=retrieved_at,
    )
    calendar = result.calendar_by_exchange["DCE"]
    assert expected_2026_trading_days("DCE")[0] == current
    assert calendar.coverage_start == current
    assert calendar.coverage_through == date(2026, 1, 12)
    assert calendar.trading_days == (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
    )
    with pytest.raises(ValueError, match="PRIOR_TRADING_DAY_UNAVAILABLE"):
        calendar.previous_complete_trading_day(current)

    catalog_completed_at = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)
    quote_completed_at = datetime(2026, 1, 5, 1, 1, tzinfo=UTC)
    catalog = FuturesContractCatalogRecord(
        product=product,
        instrument_id="M2605",
        asset_type="future",
        is_trading=True,
        expiry_date=date(2026, 5, 15),
        product_class="1",
    )
    quote = CurrentDayQuoteRecord(
        exchange_id="DCE",
        instrument_id="M2605",
        trading_day=current,
        open_interest=100,
        volume=200,
        action_day="20260105",
        update_time="09:00:00",
        update_millisec=0,
    )
    query_snapshot = MainContractQuerySnapshot(
        catalog_source=QuerySnapshotSourceEvidence(
            source_id="fixture.ctp.instruments",
            source_kind="instruments",
            snapshot_id="generation-7-request-1",
            source_sha256="a" * 64,
            request_id=1,
            connection_generation=7,
            trading_day=current,
            started_at=datetime(2026, 1, 5, 0, 59, tzinfo=UTC),
            completed_at=catalog_completed_at,
            retrieved_at=retrieved_at,
            complete=True,
            is_last_seen=True,
            record_count=1,
        ),
        quote_source=QuerySnapshotSourceEvidence(
            source_id="fixture.ctp.depth",
            source_kind="depth_market_data",
            snapshot_id="generation-7-request-2",
            source_sha256="b" * 64,
            request_id=2,
            connection_generation=7,
            trading_day=current,
            started_at=catalog_completed_at,
            completed_at=quote_completed_at,
            retrieved_at=retrieved_at,
            complete=True,
            is_last_seen=True,
            record_count=1,
        ),
        catalog_records=(catalog,),
        quote_records=(quote,),
        session_trading_day_before=current,
        session_trading_day_after=current,
        session_generation_before=7,
        session_generation_after=7,
    )
    manifest = select_main_contracts(
        query_snapshot,
        (product,),
        (ExchangeTradingDay("DCE", current),),
        result.trading_calendars,
        decision_at=decision_at,
        policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
    )
    assert manifest.status == "READY"
    assert manifest.products[0].expected_prior_trading_day is None
    assert manifest.products[0].selected_instrument_id == "M2605"


def test_default_calendar_json_shape_does_not_add_expected_rule_claims():
    # The source-backed path keeps its prior JSON/evidence shape and default.
    product = ProductKey("SHFE", "CU")
    source_id = "SHFE.fixture"
    source = PublicSourceEvidence(
        source_id=source_id,
        source_url="https://fixture.invalid/calendar.html",
        version="fixture-v1",
        available_at=SYNTHETIC_RETRIEVED_AT - timedelta(hours=1),
        retrieved_at=SYNTHETIC_RETRIEVED_AT,
        sha256=hashlib.sha256(b"fixture").hexdigest(),
    )
    local = datetime.combine(CURRENT_DAY, datetime.min.time(), tzinfo=CHINA)
    row = ProductTradingDaySessions(
        product=product,
        trading_day=CURRENT_DAY,
        source_id=source_id,
        windows=(
            SessionWindow(
                session_id="day",
                session_date=CURRENT_DAY,
                start=local.replace(hour=9, minute=0),
                end=local.replace(hour=15, minute=0),
                source_id=source_id,
            ),
        ),
    )
    legacy = ExchangeSessionCalendar(
        exchange_id="SHFE",
        calendar_source_id=source_id,
        coverage_start=CURRENT_DAY,
        coverage_through=CURRENT_DAY,
        trading_days=(CURRENT_DAY,),
        product_universe=(product,),
        product_days=(row,),
        sources=(source,),
    )
    document = legacy.to_dict()
    assert "evidence_mode" not in document
    assert "evidence_kind" not in document["sources"][0]
    assert legacy.evidence_mode == "source_backed"
    assert legacy.to_main_contract_calendar().evidence_mode == "source_backed"
