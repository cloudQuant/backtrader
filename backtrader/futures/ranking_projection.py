"""Project SDK EOD ranking snapshots into Backtrader selection inputs."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, Iterable, Optional, Tuple
from bt_api_py.futures_selection import (
    FuturesContractRecord,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
)



_COMPOSITE_SOURCE_ID = "backtrader.neutral-futures-eod-ranking.v1"


class RankingAggregationError(ValueError):
    """Stable input-contract error from the neutral ranking projection."""

    _CODES = frozenset(
        {
            "MARKET_SNAPSHOT_INVALID",
            "EOD_SNAPSHOT_INVALID",
            "TARGET_PRODUCTS_INVALID",
            "TARGET_PRODUCTS_SCOPE_MISMATCH",
            "MARKET_CATALOG_BINDING_MISMATCH",
            "MARKET_CATALOG_LEASE_INVALID",
            "MARKET_CATALOG_LEASE_EXPIRED",
            "SNAPSHOT_TIME_INVALID",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "EOD_SNAPSHOT_INVALID"
        super().__init__(self.code)


@dataclass(frozen=True)
class RankingProductCoverage:
    """Generic diagnostics for one exchange/product ranking projection."""

    product: ProductKey
    source_ids: Tuple[str, ...]
    catalog_candidate_count: int
    ranking_row_count: int
    ranking_instrument_ids: Tuple[str, ...]
    missing_ranking_instrument_ids: Tuple[str, ...]
    unmatched_source_instrument_ids: Tuple[str, ...]
    duplicate_catalog_instrument_ids: Tuple[str, ...]
    duplicate_source_instrument_ids: Tuple[str, ...]
    blockers: Tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class RankingAggregationResult:
    """Selector input plus the exact neutral EOD snapshot and diagnostics."""

    snapshot: Optional[MainContractRankingSnapshot]
    target_products: Tuple[ProductKey, ...]
    eod_snapshot: Any
    coverage: Tuple[RankingProductCoverage, ...]
    catalog_instrument_ids_outside_target: Tuple[str, ...]
    catalog_future_products_outside_target: Tuple[ProductKey, ...]
    ranking_rows_outside_target: Tuple[Any, ...]

    @property
    def source_coverage_complete(self) -> bool:
        """Whether all requested products have internally complete facts.

        Selector readiness additionally requires report finality/latest-version
        evidence and an exact current market-catalog lease. A provider that
        cannot publish either claim leaves this property false until the
        required evidence is available.
        """

        return (
            self.snapshot is not None
            and self.eod_snapshot.complete is True
            and not self.catalog_future_products_outside_target
            and all(item.complete for item in self.coverage)
        )


def _neutral_decimal(value: Any) -> Optional[Decimal]:
    if type(value) is not str or not value or len(value) > 512:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def _aware_utc(value: Any) -> bool:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset().total_seconds() == 0
    )


def _contract_kind(record: Any, sdk: Any) -> Optional[str]:
    if record.disposition is sdk.FuturesCatalogDisposition.EXCLUDED:
        return "non_future"
    if record.contract_kind is sdk.FuturesContractKind.FUTURE:
        return "future"
    if record.contract_kind is sdk.FuturesContractKind.OPTION:
        return "option"
    if record.contract_kind is sdk.FuturesContractKind.NON_FUTURES:
        return "non_future"
    return None


def _classification_blockers(records: Iterable[Any], sdk: Any) -> Tuple[str, ...]:
    blockers = set()
    for record in records:
        if record.disposition is sdk.FuturesCatalogDisposition.EXCLUDED:
            continue
        if record.contract_kind is sdk.FuturesContractKind.UNKNOWN:
            blockers.add("CATALOG_CONTRACT_KIND_UNKNOWN")
        if record.asset_type is sdk.FuturesAssetType.UNKNOWN:
            blockers.add("CATALOG_ASSET_TYPE_UNKNOWN")
        if record.disposition is sdk.FuturesCatalogDisposition.UNKNOWN:
            blockers.add("CATALOG_DISPOSITION_UNKNOWN")
        if record.expiry_date is None and record.contract_kind is sdk.FuturesContractKind.FUTURE:
            blockers.add("CATALOG_EXPIRY_UNKNOWN")
        if record.is_trading is None and record.contract_kind is sdk.FuturesContractKind.FUTURE:
            blockers.add("CATALOG_TRADING_STATUS_UNKNOWN")
    return tuple(sorted(blockers))


def aggregate_eod_ranking_snapshot(
    market_snapshot: Any,
    eod_snapshot: Any,
    target_products: Iterable[ProductKey],
    *,
    market_snapshot_facade: Any = None,
    market_snapshot_lease: Any = None,
) -> RankingAggregationResult:
    """Build the generic selector snapshot from neutral SDK ranking facts.

    ``target_products`` must match the explicit product set in the SDK EOD
    request. Exchange report parsing and catalog joins are deliberately absent
    here. When the current market snapshot has no SDK lease, candidate and
    ranking coverage is downgraded and the selector cannot return READY.
    """

    try:
        from bt_api_py.futures_contracts import (
            FuturesAssetType,
            FuturesCatalogDisposition,
            FuturesContractKind,
            FuturesEodRankingSnapshot,
            FuturesQuantityUnit,
            FuturesVolumeSemantics,
            QuerySnapshotLease,
        )
        from bt_api_py.futures_market_facade import (
            FuturesMarketSnapshot,
            FuturesMarketSnapshotFacade,
        )
        from bt_api_py.futures_eod_projection import (
            eod_snapshot_manifest_digest,
            validate_eod_snapshot_lease,
            validate_eod_market_binding,
        )
    except ImportError:
        raise RankingAggregationError("EOD_SNAPSHOT_INVALID") from None

    sdk = SimpleNamespace(
        FuturesAssetType=FuturesAssetType,
        FuturesCatalogDisposition=FuturesCatalogDisposition,
        FuturesContractKind=FuturesContractKind,
        FuturesQuantityUnit=FuturesQuantityUnit,
        FuturesVolumeSemantics=FuturesVolumeSemantics,
    )

    if type(market_snapshot) is not FuturesMarketSnapshot:
        raise RankingAggregationError("MARKET_SNAPSHOT_INVALID")
    if type(eod_snapshot) is not FuturesEodRankingSnapshot:
        raise RankingAggregationError("EOD_SNAPSHOT_INVALID")
    if (market_snapshot_facade is None) != (market_snapshot_lease is None):
        raise RankingAggregationError("MARKET_CATALOG_LEASE_INVALID")
    if market_snapshot_facade is not None and (
        type(market_snapshot_facade) is not FuturesMarketSnapshotFacade
        or type(market_snapshot_lease) is not QuerySnapshotLease
    ):
        raise RankingAggregationError("MARKET_CATALOG_LEASE_INVALID")

    products = tuple(target_products)
    if not products or any(type(item) is not ProductKey for item in products):
        raise RankingAggregationError("TARGET_PRODUCTS_INVALID")
    products = tuple(sorted(products, key=lambda item: (item.exchange_id, item.product_id)))
    product_keys = tuple((item.exchange_id, item.product_id) for item in products)
    if len(set(product_keys)) != len(product_keys):
        raise RankingAggregationError("TARGET_PRODUCTS_INVALID")
    request_products = tuple(
        (item.venue, item.product_id) for item in eod_snapshot.request.products
    )
    if request_products != product_keys:
        raise RankingAggregationError("TARGET_PRODUCTS_SCOPE_MISMATCH")

    if not all(
        _aware_utc(getattr(market_snapshot, name, None))
        for name in ("requested_at", "completed_at", "observed_at")
    ) or not all(
        _aware_utc(getattr(eod_snapshot, name, None))
        for name in ("requested_at", "completed_at", "observed_at")
    ):
        raise RankingAggregationError("SNAPSHOT_TIME_INVALID")
    validate_eod_market_binding(market_snapshot, eod_snapshot, sdk, RankingAggregationError)

    lease_present = market_snapshot_facade is not None
    if lease_present and not validate_eod_snapshot_lease(
        market_snapshot_facade, market_snapshot, market_snapshot_lease
    ):
        raise RankingAggregationError("MARKET_CATALOG_LEASE_INVALID")
    lease_verified = lease_present

    target_set = set(product_keys)
    catalog_rows_by_product = defaultdict(list)
    outside_catalog_ids = []
    outside_future_products = set()
    catalog_identity_counts = Counter(
        (item.instrument.venue, item.instrument.instrument_id.casefold())
        for item in eod_snapshot.catalog.catalog_records
    )
    for row in eod_snapshot.catalog.catalog_records:
        product_key = (row.product.venue, row.product.product_id)
        if product_key in target_set:
            catalog_rows_by_product[product_key].append(row)
        else:
            outside_catalog_ids.append(row.instrument.instrument_id)
            if row.contract_kind in (FuturesContractKind.FUTURE, FuturesContractKind.UNKNOWN):
                outside_future_products.add(ProductKey(*product_key))

    eod_rows_by_product = defaultdict(list)
    rows_outside_target = []
    eod_identity_counts = Counter(
        (item.product.venue, item.instrument.instrument_id.casefold())
        for item in eod_snapshot.records
    )
    for row in eod_snapshot.records:
        product_key = (row.product.venue, row.product.product_id)
        if product_key in target_set:
            eod_rows_by_product[product_key].append(row)
        else:
            rows_outside_target.append(row)

    source_by_ref = {item.source_ref: item for item in eod_snapshot.sources}
    product_coverage_by_key = {
        (item.product.venue, item.product.product_id): item
        for item in eod_snapshot.product_coverage
    }
    candidates = []
    selector_coverage = []
    diagnostics = []
    observed_sources = tuple(
        item
        for item in eod_snapshot.sources
        if item.snapshot_ref is not None
        and item.source_digest is not None
        and item.retrieved_at is not None
    )

    for product in products:
        product_key = (product.exchange_id, product.product_id)
        catalog_rows = tuple(catalog_rows_by_product.get(product_key, ()))
        ranking_rows = tuple(eod_rows_by_product.get(product_key, ()))
        product_coverage = product_coverage_by_key.get(product_key)
        catalog_counts = Counter(row.instrument.instrument_id.casefold() for row in catalog_rows)
        duplicate_catalog = tuple(
            sorted(
                row.instrument.instrument_id
                for row in catalog_rows
                if catalog_counts[row.instrument.instrument_id.casefold()] > 1
                or catalog_identity_counts[
                    (row.instrument.venue, row.instrument.instrument_id.casefold())
                ] > 1
            )
        )
        exact_catalog = {
            row.instrument: row
            for row in catalog_rows
            if catalog_counts[row.instrument.instrument_id.casefold()] == 1
            and catalog_identity_counts[
                (row.instrument.venue, row.instrument.instrument_id.casefold())
            ] == 1
        }
        ranking_counts = Counter(row.instrument.instrument_id.casefold() for row in ranking_rows)
        duplicate_ranking = tuple(
            sorted(
                row.instrument.instrument_id
                for row in ranking_rows
                if ranking_counts[row.instrument.instrument_id.casefold()] > 1
                or eod_identity_counts[
                    (row.product.venue, row.instrument.instrument_id.casefold())
                ] > 1
            )
        )
        exact_ranking = {
            row.instrument: row
            for row in ranking_rows
            if ranking_counts[row.instrument.instrument_id.casefold()] == 1
            and eod_identity_counts[
                (row.product.venue, row.instrument.instrument_id.casefold())
            ] == 1
        }
        unmatched_source_rows = tuple(
            sorted(
                row.instrument.instrument_id
                for row in ranking_rows
                if row.instrument not in exact_catalog
            )
        )
        joined = {
            instrument: ranking
            for instrument, ranking in exact_ranking.items()
            if instrument in exact_catalog
        }
        expected_future = {
            row.instrument
            for row in catalog_rows
            if row.contract_kind is FuturesContractKind.FUTURE
            and row.disposition is not FuturesCatalogDisposition.EXCLUDED
        }
        missing_ranking = tuple(
            sorted(
                (
                    instrument.instrument_id
                    for instrument in expected_future - set(joined)
                ),
                key=str.casefold,
            )
        )
        classification_blockers = _classification_blockers(catalog_rows, sdk)
        market_catalog_complete = (
            market_snapshot.coverage.catalog.completeness.value == "complete"
            and market_snapshot.coverage.catalog.scope_complete is True
        )
        candidate_set_complete = (
            market_catalog_complete
            and lease_verified
            and product_coverage is not None
            and product_coverage.candidate_set_complete
            and not product_coverage.blockers
            and not classification_blockers
            and not duplicate_catalog
        )
        source_refs = () if product_coverage is None else product_coverage.source_refs
        sources_for_product = tuple(
            source_by_ref[item]
            for item in source_refs
            if item in source_by_ref and product.exchange_id in source_by_ref[item].venues
        )
        source_coverage_complete = (
            bool(sources_for_product)
            and all(item.complete for item in sources_for_product)
        )
        value_units_ok = bool(joined) and all(
            item.open_interest_unit is FuturesQuantityUnit.CONTRACTS
            and item.volume_unit is FuturesQuantityUnit.CONTRACTS
            and item.volume_semantics is FuturesVolumeSemantics.CUMULATIVE_TRADING_DAY
            and _neutral_decimal(item.open_interest) is not None
            and _neutral_decimal(item.volume) is not None
            for item in joined.values()
        )
        ranking_values_complete = (
            product_coverage is not None
            and product_coverage.ranking_values_complete
            and not product_coverage.blockers
            and source_coverage_complete
            and not missing_ranking
            and not unmatched_source_rows
            and not duplicate_ranking
            and value_units_ok
        )
        blockers = list(classification_blockers)
        if not catalog_rows and not candidate_set_complete:
            blockers.append("PRODUCT_CATALOG_UNAVAILABLE")
        if not market_catalog_complete:
            blockers.append("MARKET_CATALOG_SCOPE_INCOMPLETE")
        if not lease_present:
            blockers.append("MARKET_CATALOG_LEASE_UNAVAILABLE")
        if duplicate_catalog:
            blockers.append("DUPLICATE_CATALOG_INSTRUMENT_ID")
        if product_coverage is None:
            blockers.append("PRODUCT_COVERAGE_UNAVAILABLE")
        else:
            blockers.extend(product_coverage.blockers)
        if not sources_for_product:
            blockers.append("EOD_SOURCE_COVERAGE_UNAVAILABLE")
        elif not source_coverage_complete:
            blockers.append("EOD_SOURCE_COVERAGE_INCOMPLETE")
        if unmatched_source_rows:
            blockers.append("UNMATCHED_SOURCE_INSTRUMENT_ID")
        if duplicate_ranking:
            blockers.append("DUPLICATE_SOURCE_INSTRUMENT_ID")
        if missing_ranking:
            blockers.append("RANKING_ROWS_MISSING_FOR_CATALOG_FUTURES")
        if joined and not value_units_ok:
            blockers.append("RANKING_UNIT_OR_SEMANTICS_UNSUPPORTED")
        if not ranking_values_complete:
            blockers.append("RANKING_VALUES_INCOMPLETE")
        finalized = bool(sources_for_product) and all(
            item.report_finalized is True for item in sources_for_product
        )
        latest_available = bool(sources_for_product) and all(
            item.latest_snapshot is True for item in sources_for_product
        )
        if not finalized:
            blockers.append(
                "RANKING_NOT_FINALIZED"
                if any(item.report_finalized is False for item in sources_for_product)
                else "RANKING_FINALITY_UNAVAILABLE"
            )
        if not latest_available:
            blockers.append(
                "RANKING_SNAPSHOT_NOT_LATEST"
                if any(item.latest_snapshot is False for item in sources_for_product)
                else "RANKING_LATEST_VERSION_UNAVAILABLE"
            )

        for catalog_row in catalog_rows:
            ranking = joined.get(catalog_row.instrument)
            candidates.append(
                FuturesContractRecord(
                    product=product,
                    instrument_id=catalog_row.instrument.instrument_id,
                    asset_type=_contract_kind(catalog_row, sdk),
                    is_trading=catalog_row.is_trading,
                    expiry_date=catalog_row.expiry_date,
                    open_interest=(
                        None if ranking is None else _neutral_decimal(ranking.open_interest)
                    ),
                    volume=None if ranking is None else _neutral_decimal(ranking.volume),
                )
            )

        valid_source = bool(sources_for_product) and all(
            item.snapshot_ref is not None
            and item.source_digest is not None
            and item.retrieved_at is not None
            for item in sources_for_product
        )
        source_day = (
            eod_snapshot.request.trading_day
            if valid_source and all(
                item.trading_day == eod_snapshot.request.trading_day
                for item in sources_for_product
            )
            else None
        )
        selected_metrics = tuple(joined.values())
        units_known = bool(selected_metrics) and all(
            item.open_interest_unit is FuturesQuantityUnit.CONTRACTS
            and item.volume_unit is FuturesQuantityUnit.CONTRACTS
            and item.volume_semantics is FuturesVolumeSemantics.CUMULATIVE_TRADING_DAY
            for item in selected_metrics
        )
        ranking_ids = tuple(
            sorted(item.instrument_id for item in joined)
        )
        expected_ids = tuple(sorted(row.instrument.instrument_id for row in catalog_rows))
        selector_coverage.append(
            ProductRankingCoverage(
                product=product,
                candidate_count=len(catalog_rows),
                expected_instrument_ids=expected_ids,
                ranking_instrument_ids=ranking_ids,
                candidate_set_complete=candidate_set_complete,
                ranking_values_complete=ranking_values_complete,
                finalized=finalized,
                latest_available=latest_available,
                ranking_trading_day=source_day,
                open_interest_unit="contracts" if units_known else None,
                volume_unit="contracts" if units_known else None,
            )
        )
        diagnostics.append(
            RankingProductCoverage(
                product=product,
                source_ids=tuple(sorted({item.source_ref for item in sources_for_product})),
                catalog_candidate_count=len(catalog_rows),
                ranking_row_count=len(ranking_rows),
                ranking_instrument_ids=ranking_ids,
                missing_ranking_instrument_ids=missing_ranking,
                unmatched_source_instrument_ids=unmatched_source_rows,
                duplicate_catalog_instrument_ids=tuple(dict.fromkeys(duplicate_catalog)),
                duplicate_source_instrument_ids=tuple(dict.fromkeys(duplicate_ranking)),
                blockers=tuple(dict.fromkeys(blockers)),
            )
        )

    sources_with_times = tuple(
        item
        for item in observed_sources
        if _aware_utc(item.retrieved_at)
        and (item.reported_update_at is None or _aware_utc(item.reported_update_at))
        and (item.reported_update_at is None or item.reported_update_at <= item.retrieved_at)
    )
    if sources_with_times:
        available_at = max(
            (
                item.reported_update_at or item.retrieved_at
                for item in sources_with_times
            ),
            key=lambda item: item.astimezone(timezone.utc),
        )
        retrieved_at = max(
            (item.retrieved_at for item in sources_with_times),
            key=lambda item: item.astimezone(timezone.utc),
        )
        ranking_digest = eod_snapshot_manifest_digest(eod_snapshot)
        ranking_source_id = _COMPOSITE_SOURCE_ID
        ranking_snapshot_id = "eod:" + ranking_digest[:24]
    else:
        available_at = eod_snapshot.completed_at
        retrieved_at = eod_snapshot.observed_at
        ranking_source_id = ""
        ranking_snapshot_id = ""
        ranking_digest = ""

    catalog_family = market_snapshot.coverage.catalog
    catalog_available_at = catalog_family.completed_at or market_snapshot.completed_at
    catalog_retrieved_at = catalog_family.observed_at or market_snapshot.observed_at
    catalog_source_id = (
        "sdk-query:" + market_snapshot.source_ref if market_snapshot.source_ref else ""
    )
    main_snapshot = MainContractRankingSnapshot(
        source_id=ranking_source_id,
        snapshot_id=ranking_snapshot_id,
        source_sha256=ranking_digest,
        available_at=available_at,
        retrieved_at=retrieved_at,
        catalog_source_id=catalog_source_id,
        catalog_snapshot_id=catalog_family.snapshot_ref or "",
        catalog_sha256=(
            catalog_family.records_digest
            if catalog_family.records_digest
            else ""
        ),
        catalog_available_at=catalog_available_at,
        catalog_retrieved_at=catalog_retrieved_at,
        coverage=tuple(selector_coverage),
        candidates=tuple(candidates),
    )

    if lease_present and not validate_eod_snapshot_lease(market_snapshot_facade, market_snapshot, market_snapshot_lease):
        raise RankingAggregationError("MARKET_CATALOG_LEASE_EXPIRED")

    return RankingAggregationResult(
        snapshot=main_snapshot,
        target_products=products,
        eod_snapshot=eod_snapshot,
        coverage=tuple(diagnostics),
        catalog_instrument_ids_outside_target=tuple(sorted(outside_catalog_ids)),
        catalog_future_products_outside_target=tuple(
            sorted(outside_future_products, key=lambda item: (item.exchange_id, item.product_id))
        ),
        ranking_rows_outside_target=tuple(
            sorted(
                rows_outside_target,
                key=lambda row: (
                    row.product.venue,
                    row.product.product_id,
                    row.instrument.instrument_id,
                ),
            )
        ),
    )
