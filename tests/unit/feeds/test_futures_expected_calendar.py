"""Source-backed calendar serialization retains its original shape."""

from datetime import date, datetime, timedelta, timezone
import hashlib

from backtrader.futures import (
    ExchangeSessionCalendar,
    ProductKey,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionWindow,
)

CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")
UTC = timezone.utc
SYNTHETIC_RETRIEVED_AT = datetime(2026, 10, 23, 23, 55, tzinfo=UTC)
CURRENT_DAY = date(2026, 10, 26)


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
