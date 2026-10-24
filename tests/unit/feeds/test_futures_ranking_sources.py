"""Coverage contracts for the source-neutral EOD ranking combiner."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtrader.feeds.futures_main_contract import ProductKey
from backtrader.feeds.futures_eod_cffex import (
    CffexCatalogJoinReport,
    CffexDailyContractRow,
    CffexDailyReport,
    CffexJoinedRankingRow,
)
from backtrader.feeds.futures_eod_shfe import (
    ShfeCatalogJoinReport,
    ShfeDailyContractRow,
    ShfeDailyReport,
    ShfeJoinedRankingRow,
)
from backtrader.feeds.futures_ranking_sources import (
    CatalogInstrument,
    CtpCatalogSnapshot,
    DailyRankingRow,
    ExchangeEodRankingSource,
    aggregate_eod_ranking_sources,
    ranking_source_from_cffex,
    ranking_source_from_shfe,
)


UTC = timezone.utc
DAY = date(2026, 10, 23)
NOW = datetime(2026, 10, 24, 3, tzinfo=UTC)
PRIOR_OBSERVED = NOW - timedelta(minutes=1)

PRODUCTS = (
    ProductKey("SHFE", "cu"),
    ProductKey("INE", "sc"),
    ProductKey("DCE", "m"),
    ProductKey("CZCE", "cf"),
    ProductKey("CFFEX", "if"),
    ProductKey("GFEX", "si"),
)


def _catalog(instruments=None, *, complete=True):
    if instruments is None:
        instruments = (
            CatalogInstrument(PRODUCTS[0], "cu2611", "future", True, date(2026, 11, 16)),
            CatalogInstrument(PRODUCTS[1], "sc2612", "future", True, date(2026, 12, 10)),
            CatalogInstrument(PRODUCTS[2], "M2611", "future", True, date(2026, 11, 16)),
            CatalogInstrument(PRODUCTS[3], "CF701", "future", True, date(2027, 1, 15)),
            CatalogInstrument(PRODUCTS[4], "IF2612", "future", True, date(2026, 12, 18)),
            CatalogInstrument(PRODUCTS[4], "IF2612-C-4000", "option", True, date(2026, 12, 18)),
            CatalogInstrument(PRODUCTS[5], "SI2612", "future", True, date(2026, 12, 10)),
        )
    return CtpCatalogSnapshot(
        source_id="simnow.ctp-instrument-catalog",
        snapshot_id="catalog-20261024-1",
        source_sha256="a" * 64,
        available_at=PRIOR_OBSERVED,
        retrieved_at=NOW,
        complete=complete,
        instruments=tuple(instruments),
    )


def _source(source_id, exchange_ids, rows, *, offset_minutes=0, **changes):
    observed_at = NOW + timedelta(minutes=offset_minutes)
    values = {
        "source_id": source_id,
        "snapshot_id": source_id + "-snapshot-20261023",
        "source_sha256": ("b" if source_id.endswith("shfe") else "c") * 64,
        "source_url": "https://example.invalid/" + source_id,
        "available_at": observed_at,
        "retrieved_at": observed_at,
        "exchange_ids": tuple(exchange_ids),
        "trading_day": DAY,
        "open_interest_unit": "contracts_single_sided",
        "volume_unit": "contracts_single_sided",
        "finalized": True,
        "latest_available": True,
        "rows": tuple(rows),
        "unscoped_join_issue_count": 0,
    }
    values.update(changes)
    return ExchangeEodRankingSource(**values)


def _current_supported_sources():
    return (
        _source(
            "shfe-ine-public-daily-kx-v1",
            ("SHFE", "INE"),
            (
                DailyRankingRow(PRODUCTS[0], "cu2611", 147002, 66085),
                DailyRankingRow(PRODUCTS[1], "sc2612", 4212, 8031),
            ),
            offset_minutes=-3,
        ),
        _source(
            "cffex-public-daily-quote-csv-v1",
            ("CFFEX",),
            (DailyRankingRow(PRODUCTS[4], "IF2612", 61020, 55053),),
            offset_minutes=-2,
        ),
    )


def _by_product(result):
    return {item.product: item for item in result.coverage}


def test_committed_exchange_reports_adapt_to_exact_joined_ctp_identifiers():
    shfe_row = ShfeDailyContractRow("cu", "cu_f", "1", "2611", 66085, 147002, -14051, 1)
    shfe_report = ShfeDailyReport(
        source_id="shfe-ine-public-daily-kx-v1",
        snapshot_id="shfe-20261023",
        source_sha256="d" * 64,
        report_date=DAY,
        reported_update_at=NOW - timedelta(minutes=2),
        available_at=NOW,
        retrieved_at=NOW,
        rows=(shfe_row,),
        source_row_count=1,
        product_summary_row_count=0,
        overall_summary_row_count=0,
        nonordinary_row_count=0,
        nonordinary_class_counts=(),
        product_summary_table_count=0,
    )
    shfe_join = ShfeCatalogJoinReport(
        matched_rows=(
            ShfeJoinedRankingRow(
                "SHFE", "cu", "cu2611", "future", True, date(2026, 11, 16), shfe_row
            ),
        ),
        unmatched_source_rows=(),
        ambiguous_source_matches=(),
        duplicate_source_keys=(),
        duplicate_catalog_instrument_ids=(),
        catalog_instrument_ids_without_daily_row=(),
        out_of_scope_catalog_instrument_ids=(),
        ignored_nonfuture_catalog_instrument_ids=(),
        unknown_asset_type_catalog_instrument_ids=(),
    )
    cffex_row = CffexDailyContractRow("IF2612", "IF", 55053, 61020, 2863, 1)
    cffex_report = CffexDailyReport(
        source_id="cffex-public-daily-quote-csv-v1",
        snapshot_id="cffex-20261023",
        source_sha256="e" * 64,
        trading_day=DAY,
        available_at=NOW,
        retrieved_at=NOW,
        rows=(cffex_row,),
        source_row_count=1,
        futures_row_count=1,
        option_row_count=0,
        summary_rows=(),
        summary_label_counts=(),
        http_last_modified_at=None,
    )
    cffex_join = CffexCatalogJoinReport(
        matched_rows=(
            CffexJoinedRankingRow(
                "CFFEX", "IF", "IF2612", "future", True, date(2026, 12, 18), cffex_row
            ),
        ),
        unmatched_source_rows=(),
        ambiguous_source_matches=(),
        duplicate_source_instrument_ids=(),
        duplicate_catalog_instrument_ids=(),
        catalog_instrument_ids_without_daily_row=(),
        out_of_scope_catalog_instrument_ids=(),
        ignored_nonfuture_catalog_instrument_ids=(),
        unknown_asset_type_catalog_instrument_ids=(),
    )

    shfe = ranking_source_from_shfe(shfe_report, shfe_join, finalized=True, latest_available=True)
    cffex = ranking_source_from_cffex(
        cffex_report, cffex_join, finalized=True, latest_available=True
    )

    assert shfe.exchange_ids == ("INE", "SHFE")
    assert shfe.source_url.endswith("kx20261023.dat")
    assert shfe.rows[0].instrument_id == "cu2611"
    assert (shfe.rows[0].open_interest, shfe.rows[0].volume) == (147002, 66085)
    assert cffex.exchange_ids == ("CFFEX",)
    assert cffex.source_url.endswith("/202610/23/20261023_1.csv")
    assert cffex.rows[0].instrument_id == "IF2612"
    assert (cffex.rows[0].open_interest, cffex.rows[0].volume) == (61020, 55053)


def test_partial_exchange_sources_keep_every_target_and_report_missing_venues():
    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, _current_supported_sources())

    assert result.snapshot is not None
    assert tuple(item.product for item in result.coverage) == tuple(
        sorted(PRODUCTS, key=lambda item: (item.exchange_id, item.product_id))
    )
    assert not result.source_coverage_complete
    by_product = _by_product(result)
    for product in (PRODUCTS[0], PRODUCTS[1], PRODUCTS[4]):
        assert by_product[product].complete
    for product in (PRODUCTS[2], PRODUCTS[3], PRODUCTS[5]):
        assert not by_product[product].complete
        assert "EXCHANGE_RANKING_SOURCE_MISSING" in by_product[product].blockers

    coverage = {item.product: item for item in result.snapshot.coverage}
    assert coverage[PRODUCTS[2]].candidate_set_complete
    assert not coverage[PRODUCTS[2]].ranking_values_complete
    assert coverage[PRODUCTS[2]].ranking_trading_day is None
    assert coverage[PRODUCTS[2]].open_interest_unit is None
    assert coverage[PRODUCTS[2]].ranking_instrument_ids == ()
    assert result.snapshot.available_at == NOW - timedelta(minutes=2)
    assert result.snapshot.retrieved_at == NOW - timedelta(minutes=2)

    cffex = [row for row in result.snapshot.candidates if row.product == PRODUCTS[4]]
    assert {row.instrument_id for row in cffex} == {"IF2612", "IF2612-C-4000"}
    assert next(row for row in cffex if row.instrument_id == "IF2612").open_interest == 61020
    assert next(row for row in cffex if row.instrument_id.endswith("4000")).open_interest is None


def test_missing_exchange_feed_and_empty_source_set_are_explicit():
    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, ())

    assert result.snapshot is None
    assert not result.source_coverage_complete
    assert len(result.coverage) == len(PRODUCTS)
    assert all("EXCHANGE_RANKING_SOURCE_MISSING" in item.blockers for item in result.coverage)


def test_all_declared_venues_can_be_combined_without_rewriting_instrument_ids():
    sources = list(_current_supported_sources())
    for index, product in enumerate((PRODUCTS[2], PRODUCTS[3], PRODUCTS[5])):
        contract = next(
            row
            for row in _catalog().instruments
            if row.product == product and row.asset_type == "future"
        )
        sources.append(
            _source(
                "official-{}-fixture".format(product.exchange_id.lower()),
                (product.exchange_id,),
                (DailyRankingRow(product, contract.instrument_id, Decimal("10.5"), 20),),
                offset_minutes=index,
            )
        )

    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, sources)

    assert result.source_coverage_complete
    assert all(item.complete for item in result.coverage)
    assert result.snapshot is not None
    assert result.snapshot.source_id == "backtrader.exchange-eod-ranking-composite.v1"
    assert result.snapshot.available_at == NOW + timedelta(minutes=2)
    assert result.snapshot.retrieved_at == NOW + timedelta(minutes=2)
    assert (
        next(row for row in result.snapshot.candidates if row.product == PRODUCTS[0]).instrument_id
        == "cu2611"
    )
    assert (
        next(row for row in result.snapshot.candidates if row.product == PRODUCTS[2]).instrument_id
        == "M2611"
    )


def test_missing_catalog_future_is_reported_and_ranking_is_incomplete():
    catalog = _catalog()
    report = _current_supported_sources()[0]
    without_ine_row = replace(
        report,
        rows=tuple(row for row in report.rows if row.product != PRODUCTS[1]),
    )
    cffex = _current_supported_sources()[1]
    result = aggregate_eod_ranking_sources(catalog, PRODUCTS, (without_ine_row, cffex))

    ine = _by_product(result)[PRODUCTS[1]]
    assert "RANKING_ROWS_MISSING_FOR_CATALOG_FUTURES" in ine.blockers
    assert ine.missing_ranking_instrument_ids == ("sc2612",)
    coverage = next(row for row in result.snapshot.coverage if row.product == PRODUCTS[1])
    assert not coverage.ranking_values_complete
    assert coverage.expected_instrument_ids == ("sc2612",)
    assert coverage.ranking_instrument_ids == ()


def test_ranking_text_is_not_silently_coerced_to_numeric_values():
    base = _current_supported_sources()[1]
    source = replace(
        base,
        rows=(replace(base.rows[0], open_interest="61020"),),
    )

    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (source,))

    cffex = _by_product(result)[PRODUCTS[4]]
    assert "RANKING_VALUE_INVALID" in cffex.blockers
    coverage = next(row for row in result.snapshot.coverage if row.product == PRODUCTS[4])
    assert not coverage.ranking_values_complete
    candidate = next(row for row in result.snapshot.candidates if row.instrument_id == "IF2612")
    assert candidate.open_interest == "61020"


def test_duplicate_or_unmatched_daily_rows_never_become_complete():
    base = _current_supported_sources()[1]
    duplicate = replace(base, rows=base.rows + base.rows)
    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (duplicate,))

    cffex = _by_product(result)[PRODUCTS[4]]
    assert "DUPLICATE_SOURCE_INSTRUMENT_ID" in cffex.blockers
    assert "RANKING_ROWS_MISSING_FOR_CATALOG_FUTURES" in cffex.blockers
    assert cffex.duplicate_source_instrument_ids == ("IF2612",)
    coverage = next(row for row in result.snapshot.coverage if row.product == PRODUCTS[4])
    assert coverage.ranking_instrument_ids == ()
    assert not coverage.ranking_values_complete

    extra = replace(
        base,
        rows=base.rows + (DailyRankingRow(PRODUCTS[4], "IF9999", 1, 1),),
    )
    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (extra,))
    cffex = _by_product(result)[PRODUCTS[4]]
    assert "UNMATCHED_SOURCE_INSTRUMENT_ID" in cffex.blockers
    assert cffex.unmatched_source_instrument_ids == ("IF9999",)


def test_catalog_duplicate_id_across_products_is_ambiguous():
    other_dce = ProductKey("DCE", "m2")
    catalog = _catalog()
    catalog = replace(
        catalog,
        instruments=catalog.instruments
        + (CatalogInstrument(other_dce, "M2611", "future", True, date(2026, 11, 16)),),
    )
    dce = _source(
        "dce-report",
        ("DCE",),
        (DailyRankingRow(PRODUCTS[2], "M2611", 100, 200),),
    )
    targets = PRODUCTS + (other_dce,)

    result = aggregate_eod_ranking_sources(catalog, targets, _current_supported_sources() + (dce,))

    by_product = _by_product(result)
    assert "DUPLICATE_CATALOG_INSTRUMENT_ID" in by_product[PRODUCTS[2]].blockers
    assert "DUPLICATE_CATALOG_INSTRUMENT_ID" in by_product[other_dce].blockers
    assert not result.source_coverage_complete


def test_duplicate_exchange_source_and_unscoped_join_issue_block_product():
    first, second = _current_supported_sources()
    competing = _source(
        "second-cffex-source",
        ("CFFEX",),
        first.rows[:0],
    )
    issue_source = replace(first, unscoped_join_issue_count=1)
    result = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (issue_source, second, competing))

    shfe = _by_product(result)[PRODUCTS[0]]
    assert "SOURCE_JOIN_HAS_UNSCOPED_ISSUES" in shfe.blockers
    cffex = _by_product(result)[PRODUCTS[4]]
    assert "EXCHANGE_RANKING_SOURCE_AMBIGUOUS" in cffex.blockers
    coverage = {item.product: item for item in result.snapshot.coverage}
    assert not coverage[PRODUCTS[4]].ranking_values_complete


def test_composite_digest_binds_joined_ranking_values_and_caller_status():
    source = _current_supported_sources()[0]
    changed_value = replace(
        source,
        rows=(replace(source.rows[0], open_interest=147003), source.rows[1]),
    )
    changed_claim = replace(source, latest_available=False)

    first = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (source,)).snapshot
    second = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (changed_value,)).snapshot
    third = aggregate_eod_ranking_sources(_catalog(), PRODUCTS, (changed_claim,)).snapshot

    assert first.source_sha256 != second.source_sha256
    assert first.source_sha256 != third.source_sha256
    assert first.source_sha256 == first.snapshot_id[len("composite:") :]

    reversed_sources = aggregate_eod_ranking_sources(
        _catalog(), PRODUCTS, tuple(reversed(_current_supported_sources()))
    ).snapshot
    both_sources = aggregate_eod_ranking_sources(
        _catalog(), PRODUCTS, _current_supported_sources()
    ).snapshot
    assert reversed_sources.source_sha256 == both_sources.source_sha256


def test_incomplete_catalog_is_not_reported_complete():
    result = aggregate_eod_ranking_sources(
        _catalog(complete=False), PRODUCTS, _current_supported_sources()
    )

    assert not result.source_coverage_complete
    for product in (PRODUCTS[0], PRODUCTS[1], PRODUCTS[4]):
        item = _by_product(result)[product]
        assert "CATALOG_SNAPSHOT_INCOMPLETE" in item.blockers
        coverage = next(row for row in result.snapshot.coverage if row.product == product)
        assert not coverage.candidate_set_complete


def test_target_set_cannot_be_narrowed_by_duplicating_or_omitting_input_types():
    with pytest.raises(ValueError, match="contains duplicates"):
        aggregate_eod_ranking_sources(_catalog(), (PRODUCTS[0], PRODUCTS[0]), ())

    with pytest.raises(ValueError, match="non-empty ProductKey"):
        aggregate_eod_ranking_sources(_catalog(), (), ())


def test_target_cannot_omit_a_future_product_in_the_actual_catalog_scope():
    narrowed = PRODUCTS[:-1]

    result = aggregate_eod_ranking_sources(_catalog(), narrowed, _current_supported_sources())

    assert result.snapshot is None
    assert not result.source_coverage_complete
    assert result.catalog_future_products_outside_target == (PRODUCTS[-1],)
    assert "SI2612" in result.catalog_instrument_ids_outside_target


def test_sources_for_same_exchange_are_not_silently_preferred():
    source = _current_supported_sources()[1]
    result = aggregate_eod_ranking_sources(
        _catalog(), PRODUCTS, (source, replace(source, source_id="cffex-second"))
    )
    cffex = _by_product(result)[PRODUCTS[4]]
    assert "EXCHANGE_RANKING_SOURCE_AMBIGUOUS" in cffex.blockers
    assert not result.source_coverage_complete
