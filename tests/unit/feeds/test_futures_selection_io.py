"""Public JSON bundles rerun point-in-time selection from source inputs."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib

import pytest

from backtrader.feeds.futures_main_contract import (
    ExchangeTradingDay,
    FuturesContractRecord,
    MainContractPolicy,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
    select_main_contracts,
)
from backtrader.feeds.futures_selection_io import (
    SelectionBundleInputError,
    load_selection_bundle,
    selection_bundle_to_dict,
)
from backtrader.feeds.futures_sessions import (
    ExchangeSessionCalendar,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionWindow,
)


UTC = timezone.utc
PRODUCT = ProductKey("DCE", "M")
DECISION = datetime(2026, 10, 21, 16, tzinfo=UTC)
CURRENT_DAY = date(2026, 10, 21)
TRADING_DAYS = (
    date(2026, 10, 19),
    date(2026, 10, 21),
    date(2026, 10, 22),
    date(2026, 10, 23),
    date(2026, 10, 26),
    date(2026, 10, 27),
    date(2026, 10, 28),
)


def _calendar():
    published = datetime(2026, 10, 1, tzinfo=UTC)
    retrieved = published + timedelta(hours=1)
    return ExchangeSessionCalendar(
        exchange_id="DCE",
        calendar_source_id="dce-calendar",
        coverage_start=TRADING_DAYS[0],
        coverage_through=TRADING_DAYS[-1],
        trading_days=TRADING_DAYS,
        product_universe=(PRODUCT,),
        product_days=(
            ProductTradingDaySessions(
                product=PRODUCT,
                trading_day=CURRENT_DAY,
                source_id="dce-hours",
                windows=(
                    SessionWindow(
                        session_id="day-am",
                        session_date=CURRENT_DAY,
                        start=datetime(2026, 10, 21, 9, tzinfo=timezone(timedelta(hours=8))),
                        end=datetime(2026, 10, 21, 10, 15, tzinfo=timezone(timedelta(hours=8))),
                        source_id="dce-hours",
                    ),
                ),
            ),
        ),
        sources=(
            PublicSourceEvidence(
                source_id="dce-calendar",
                source_url="https://example.invalid/calendar",
                version="source-fixture-v1",
                available_at=published,
                retrieved_at=retrieved,
                sha256=hashlib.sha256(b"calendar").hexdigest(),
            ),
            PublicSourceEvidence(
                source_id="dce-hours",
                source_url="https://example.invalid/hours",
                version="source-fixture-v1",
                available_at=published,
                retrieved_at=retrieved,
                sha256=hashlib.sha256(b"hours").hexdigest(),
            ),
        ),
    )


def _snapshot(*, complete=True):
    prior = date(2026, 10, 19)
    candidates = (
        FuturesContractRecord(
            product=PRODUCT,
            instrument_id="M2611",
            asset_type="future",
            is_trading=True,
            expiry_date=date(2026, 11, 16),
            open_interest=Decimal("120.50"),
            volume=Decimal("302.25"),
        ),
        FuturesContractRecord(
            product=PRODUCT,
            instrument_id="M2612",
            asset_type="future",
            is_trading=True,
            expiry_date=date(2026, 12, 15),
            open_interest=Decimal("140.25"),
            volume=Decimal("101.75"),
        ),
    )
    coverage = ProductRankingCoverage(
        product=PRODUCT,
        candidate_count=len(candidates),
        expected_instrument_ids=("M2611", "M2612"),
        ranking_instrument_ids=("M2611", "M2612"),
        candidate_set_complete=complete,
        ranking_values_complete=True,
        finalized=True,
        latest_available=True,
        ranking_trading_day=prior,
        open_interest_unit="contracts",
        volume_unit="lots",
    )
    available = datetime(2026, 10, 20, 9, tzinfo=UTC)
    catalog_available = datetime(2026, 10, 1, tzinfo=UTC)
    return MainContractRankingSnapshot(
        source_id="official-daily-ranking-fixture",
        snapshot_id="rank-2026-10-19-final",
        source_sha256=hashlib.sha256(b"ranking").hexdigest(),
        available_at=available,
        retrieved_at=available + timedelta(minutes=10),
        catalog_source_id="ctp-instrument-catalog-fixture",
        catalog_snapshot_id="catalog-2026-10-01",
        catalog_sha256=hashlib.sha256(b"catalog").hexdigest(),
        catalog_available_at=catalog_available,
        catalog_retrieved_at=catalog_available + timedelta(minutes=10),
        coverage=(coverage,),
        candidates=candidates,
    )


def _document(*, complete=True):
    snapshot = _snapshot(complete=complete)
    policy = MainContractPolicy()
    current_days = (ExchangeTradingDay("DCE", CURRENT_DAY),)
    calendars = (_calendar(),)
    claim = select_main_contracts(
        snapshot,
        (PRODUCT,),
        current_days,
        tuple(item.to_main_contract_calendar() for item in calendars),
        decision_at=DECISION,
        policy=policy,
    )
    return selection_bundle_to_dict(
        snapshot,
        (PRODUCT,),
        current_days,
        calendars,
        decision_at=DECISION,
        policy=policy,
        selection_claim=claim,
    )


def test_json_roundtrip_reruns_selection_and_preserves_exact_source_ids_and_decimals():
    document = _document()
    manifest = load_selection_bundle(document)

    assert manifest.status == "READY"
    assert manifest.selected_mapping() == ((PRODUCT, "M2612"),)
    selected = next(row for row in manifest.candidates if row.instrument_id == "M2612")
    assert selected.open_interest == "140.25"
    assert selected.volume == "101.75"
    assert manifest.source_snapshot_id == "rank-2026-10-19-final"
    assert manifest.catalog_snapshot_id == "catalog-2026-10-01"
    assert manifest.trading_days[0].expected_prior_trading_day == date(2026, 10, 19)


def test_saved_selection_claim_cannot_override_incomplete_source_coverage():
    document = _document(complete=False)
    document["selection_claim"] = {
        "status": "READY",
        "selected_mapping": [{"exchange_id": "DCE", "product_id": "M", "instrument_id": "M2612"}],
    }

    manifest = load_selection_bundle(document)

    assert manifest.status == "BLOCKED"
    assert manifest.products[0].status == "BLOCKED"
    assert "CANDIDATE_SET_INCOMPLETE" in manifest.blockers


def test_saved_blocked_claim_cannot_override_complete_recomputed_selection():
    document = _document()
    document["selection_claim"]["status"] = "BLOCKED"
    document["selection_claim"]["selected_mapping"] = []

    manifest = load_selection_bundle(document)

    assert manifest.status == "READY"
    assert manifest.selected_mapping() == ((PRODUCT, "M2612"),)


def test_loader_rejects_wrong_schema_and_naive_decision_timestamp():
    document = _document()
    wrong_schema = deepcopy(document)
    wrong_schema["schema"] = "backtrader.futures_selection_bundle.v2"
    with pytest.raises(SelectionBundleInputError, match="SCHEMA_UNSUPPORTED"):
        load_selection_bundle(wrong_schema)

    naive = deepcopy(document)
    naive["decision_at"] = "2026-10-21T16:00:00"
    with pytest.raises(SelectionBundleInputError, match="NAIVE_DATETIME"):
        load_selection_bundle(naive)
