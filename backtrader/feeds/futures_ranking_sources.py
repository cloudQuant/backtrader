"""Combine exchange EOD rankings without hiding market-coverage gaps.

This module is the source-neutral bridge between exchange-specific parsers and
the main-contract selector.  The caller supplies the full target product set,
the observed CTP catalog snapshot, and exchange ranking rows already joined to
the exact catalog ``InstrumentID`` values.  Missing exchange feeds and
catalog/source mismatches remain explicit; no product list is inferred from
whichever reports happened to load.

The combined ranking digest identifies a canonical manifest of constituent
report identities and digests.  It is not the digest of a single exchange
payload, nor does it authenticate any constituent source.  The earliest
defensible availability for the combined set is the latest constituent
``available_at``; source adapters should use observed retrieval completion
when the exchange publication time is unknown.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional, Sequence, Tuple

from .futures_main_contract import (
    FuturesContractRecord,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPOSITE_SOURCE_ID = "backtrader.exchange-eod-ranking-composite.v1"


class RankingAggregationError(ValueError):
    """Stable input-contract error from ranking-source aggregation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("{} must be non-empty trimmed text".format(field))
    return value


def _instrument_id(value: Any) -> str:
    # Keep the identifier byte-for-byte at the string level.  In particular,
    # do not case-fold or reconstruct a provider InstrumentID.
    if type(value) is not str or not value:
        raise ValueError("instrument_id must be non-empty text")
    return value


def _aware(value: Any, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(field))
    return value


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError("{} must be lowercase SHA-256 hex".format(field))
    return value


def _valid_nonnegative_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float, Decimal)):
        return False
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False
    return number.is_finite() and number >= 0


def _digest_number(value: Any) -> dict:
    """Return a type-tagged stable representation for a ranking source value."""

    if value is None:
        return {"type": "none"}
    if type(value) is bool:
        return {"type": "bool", "value": value}
    if type(value) is int:
        return {"type": "int", "value": str(value)}
    if type(value) is float:
        return {"type": "float", "value": value.hex()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if type(value) is str:
        return {"type": "str", "value": value}
    raise RankingAggregationError("RANKING_VALUE_UNSUPPORTED_TYPE")


@dataclass(frozen=True)
class CatalogInstrument:
    """One exact CTP catalog row, including non-futures for explicit exclusion."""

    product: ProductKey
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("catalog product must be ProductKey")
        _instrument_id(self.instrument_id)
        if self.asset_type is not None and type(self.asset_type) is not str:
            raise ValueError("asset_type must be text or None")
        if self.is_trading is not None and type(self.is_trading) is not bool:
            raise ValueError("is_trading must be bool or None")
        if self.expiry_date is not None and type(self.expiry_date) is not date:
            raise ValueError("expiry_date must be date or None")


@dataclass(frozen=True)
class CtpCatalogSnapshot:
    """Observed catalog identity and rows for the selected SimNow scope."""

    source_id: str
    snapshot_id: str
    source_sha256: str
    available_at: datetime
    retrieved_at: datetime
    complete: bool
    instruments: Tuple[CatalogInstrument, ...]

    def __post_init__(self) -> None:
        for field in ("source_id", "snapshot_id"):
            _text(getattr(self, field), "catalog " + field)
        _sha256(self.source_sha256, "catalog source_sha256")
        available = _aware(self.available_at, "catalog available_at")
        retrieved = _aware(self.retrieved_at, "catalog retrieved_at")
        if retrieved.astimezone(timezone.utc) < available.astimezone(timezone.utc):
            raise ValueError("catalog retrieved_at precedes available_at")
        if type(self.complete) is not bool:
            raise ValueError("catalog complete must be bool")
        instruments = tuple(self.instruments)
        if any(not isinstance(item, CatalogInstrument) for item in instruments):
            raise ValueError("catalog instruments must contain CatalogInstrument records")
        object.__setattr__(self, "instruments", instruments)


@dataclass(frozen=True)
class DailyRankingRow:
    """One exchange daily ranking row already matched to a real CTP ID."""

    product: ProductKey
    instrument_id: str
    open_interest: Any
    volume: Any

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("ranking row product must be ProductKey")
        _instrument_id(self.instrument_id)


@dataclass(frozen=True)
class ExchangeEodRankingSource:
    """One parsed daily report and its explicit source-join status.

    ``finalized`` and ``latest_available`` are caller-supplied observations,
    not defaults asserted by this helper.  ``unscoped_join_issue_count`` is
    used when an exchange adapter found source-row problems that cannot be
    assigned to one catalog product without guessing.
    """

    source_id: str
    snapshot_id: str
    source_sha256: str
    source_url: str
    available_at: datetime
    retrieved_at: datetime
    exchange_ids: Tuple[str, ...]
    trading_day: date
    open_interest_unit: str
    volume_unit: str
    finalized: bool
    latest_available: bool
    rows: Tuple[DailyRankingRow, ...]
    unscoped_join_issue_count: int = 0

    def __post_init__(self) -> None:
        _text(self.source_id, "ranking source_id")
        _text(self.snapshot_id, "ranking snapshot_id")
        _text(self.source_url, "ranking source_url")
        _sha256(self.source_sha256, "ranking source_sha256")
        available = _aware(self.available_at, "ranking available_at")
        retrieved = _aware(self.retrieved_at, "ranking retrieved_at")
        if retrieved.astimezone(timezone.utc) < available.astimezone(timezone.utc):
            raise ValueError("ranking retrieved_at precedes available_at")
        if type(self.trading_day) is not date:
            raise ValueError("ranking trading_day must be a date")
        if (
            not self.open_interest_unit
            or self.open_interest_unit != self.open_interest_unit.strip()
        ):
            raise ValueError("open_interest_unit must be non-empty trimmed text")
        if not self.volume_unit or self.volume_unit != self.volume_unit.strip():
            raise ValueError("volume_unit must be non-empty trimmed text")
        if type(self.finalized) is not bool or type(self.latest_available) is not bool:
            raise ValueError("finalized and latest_available must be bool")
        if any(type(value) is not str for value in self.exchange_ids):
            raise ValueError("exchange_ids must contain text values")
        exchanges = tuple(value.upper() for value in self.exchange_ids)
        if not exchanges or any(not value or value != value.strip() for value in exchanges):
            raise ValueError("exchange_ids must contain non-empty exchange IDs")
        if len(set(exchanges)) != len(exchanges):
            raise ValueError("exchange_ids contains duplicates")
        rows = tuple(self.rows)
        if any(not isinstance(item, DailyRankingRow) for item in rows):
            raise ValueError("rows must contain DailyRankingRow records")
        if any(item.product.exchange_id not in exchanges for item in rows):
            raise ValueError("ranking row exchange is outside the source declaration")
        if type(self.unscoped_join_issue_count) is not int or self.unscoped_join_issue_count < 0:
            raise ValueError("unscoped_join_issue_count must be a non-negative int")
        object.__setattr__(self, "exchange_ids", tuple(sorted(exchanges)))
        object.__setattr__(self, "rows", rows)


@dataclass(frozen=True)
class RankingProductCoverage:
    """Product-level diagnostics returned alongside the selector snapshot."""

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
    """Combined selector input and the explicit coverage state."""

    snapshot: Optional[MainContractRankingSnapshot]
    target_products: Tuple[ProductKey, ...]
    ranking_sources: Tuple[ExchangeEodRankingSource, ...]
    coverage: Tuple[ProductRankingCoverage, ...]
    catalog_instrument_ids_outside_target: Tuple[str, ...]
    catalog_future_products_outside_target: Tuple[ProductKey, ...]
    ranking_rows_outside_target: Tuple[DailyRankingRow, ...]

    @property
    def source_coverage_complete(self) -> bool:
        """Whether the declared target products all have internally complete EOD inputs.

        This does not validate the prior TradingDay against a calendar or
        produce an executable mapping; callers must still run the selector.
        """

        return (
            self.snapshot is not None
            and not self.catalog_future_products_outside_target
            and all(item.complete for item in self.coverage)
        )


def ranking_source_from_shfe(
    report: Any,
    join_report: Any,
    *,
    finalized: bool,
    latest_available: bool,
) -> ExchangeEodRankingSource:
    """Adapt the committed SHFE/INE parser and exact catalog join result."""

    from .futures_eod_shfe import (
        SHFE_INE_EXCHANGE_IDS,
        ShfeCatalogJoinReport,
        ShfeDailyReport,
        shfe_eod_url,
    )

    if not isinstance(report, ShfeDailyReport) or not isinstance(
        join_report, ShfeCatalogJoinReport
    ):
        raise TypeError("report/join_report must be SHFE daily report and catalog join")
    rows = tuple(
        DailyRankingRow(
            ProductKey(item.exchange_id, item.product_id),
            item.instrument_id,
            item.source_row.open_interest,
            item.source_row.volume,
        )
        for item in join_report.matched_rows
    )
    unscoped = (
        len(join_report.unmatched_source_rows)
        + len(join_report.ambiguous_source_matches)
        + len(join_report.duplicate_source_keys)
    )
    return ExchangeEodRankingSource(
        source_id=report.source_id,
        snapshot_id=report.snapshot_id,
        source_sha256=report.source_sha256,
        source_url=shfe_eod_url(report.report_date),
        available_at=report.available_at,
        retrieved_at=report.retrieved_at,
        exchange_ids=SHFE_INE_EXCHANGE_IDS,
        trading_day=report.report_date,
        open_interest_unit=report.open_interest_unit,
        volume_unit=report.volume_unit,
        finalized=finalized,
        latest_available=latest_available,
        rows=rows,
        unscoped_join_issue_count=unscoped,
    )


def ranking_source_from_cffex(
    report: Any,
    join_report: Any,
    *,
    finalized: bool,
    latest_available: bool,
) -> ExchangeEodRankingSource:
    """Adapt the committed CFFEX parser and exact catalog join result."""

    from .futures_eod_cffex import (
        CffexCatalogJoinReport,
        CffexDailyReport,
        cffex_eod_url,
    )

    if not isinstance(report, CffexDailyReport) or not isinstance(
        join_report, CffexCatalogJoinReport
    ):
        raise TypeError("report/join_report must be CFFEX daily report and catalog join")
    rows = tuple(
        DailyRankingRow(
            ProductKey(item.exchange_id, item.product_id),
            item.instrument_id,
            item.source_row.open_interest,
            item.source_row.volume,
        )
        for item in join_report.matched_rows
    )
    unscoped = (
        len(join_report.unmatched_source_rows)
        + len(join_report.ambiguous_source_matches)
        + len(join_report.duplicate_source_instrument_ids)
    )
    return ExchangeEodRankingSource(
        source_id=report.source_id,
        snapshot_id=report.snapshot_id,
        source_sha256=report.source_sha256,
        source_url=cffex_eod_url(report.trading_day),
        available_at=report.available_at,
        retrieved_at=report.retrieved_at,
        exchange_ids=("CFFEX",),
        trading_day=report.trading_day,
        open_interest_unit=report.open_interest_unit,
        volume_unit=report.volume_unit,
        finalized=finalized,
        latest_available=latest_available,
        rows=rows,
        unscoped_join_issue_count=unscoped,
    )


def _composite_source_digest(sources: Sequence[ExchangeEodRankingSource]) -> str:
    source_facts = [
        {
            "source_id": item.source_id,
            "snapshot_id": item.snapshot_id,
            "source_sha256": item.source_sha256,
            "source_url": item.source_url,
            "available_at": _iso(item.available_at),
            "retrieved_at": _iso(item.retrieved_at),
            "exchange_ids": list(item.exchange_ids),
            "trading_day": item.trading_day.isoformat(),
            "open_interest_unit": item.open_interest_unit,
            "volume_unit": item.volume_unit,
            "finalized": item.finalized,
            "latest_available": item.latest_available,
            "unscoped_join_issue_count": item.unscoped_join_issue_count,
            "rows": [
                {
                    "exchange_id": row.product.exchange_id,
                    "product_id": row.product.product_id,
                    "instrument_id": row.instrument_id,
                    "open_interest": _digest_number(row.open_interest),
                    "volume": _digest_number(row.volume),
                }
                for row in sorted(
                    item.rows,
                    key=lambda row: (
                        row.product.exchange_id,
                        row.product.product_id,
                        row.instrument_id,
                    ),
                )
            ],
        }
        for item in sorted(sources, key=lambda value: (value.source_id, value.snapshot_id))
    ]
    payload = json.dumps(
        source_facts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def aggregate_eod_ranking_sources(
    catalog: CtpCatalogSnapshot,
    target_products: Iterable[ProductKey],
    ranking_sources: Iterable[ExchangeEodRankingSource],
) -> RankingAggregationResult:
    """Build a selector snapshot while preserving absent and conflicting feeds.

    ``target_products`` must be the complete target set derived by the caller
    from its selected SimNow catalog scope.  This function never chooses a
    smaller set because some exchange reports are missing.
    """

    if not isinstance(catalog, CtpCatalogSnapshot):
        raise TypeError("catalog must be CtpCatalogSnapshot")
    products = tuple(target_products)
    if not products or any(not isinstance(item, ProductKey) for item in products):
        raise ValueError("target_products must be a non-empty ProductKey collection")
    product_keys = tuple(sorted(products, key=lambda item: (item.exchange_id, item.product_id)))
    product_pairs = [(item.exchange_id, item.product_id) for item in product_keys]
    if len(set(product_pairs)) != len(product_pairs):
        raise ValueError("target_products contains duplicates")
    sources = tuple(ranking_sources)
    if any(not isinstance(item, ExchangeEodRankingSource) for item in sources):
        raise TypeError("ranking_sources must contain ExchangeEodRankingSource records")
    sources = tuple(sorted(sources, key=lambda item: (item.source_id, item.snapshot_id)))

    sources_by_exchange = defaultdict(list)
    for source in sources:
        for exchange_id in source.exchange_ids:
            sources_by_exchange[exchange_id].append(source)

    catalog_by_product = defaultdict(list)
    all_target_ids = set(product_pairs)
    outside_catalog_ids = []
    outside_future_products = set()
    catalog_identity_counts = Counter(
        (item.product.exchange_id, item.instrument_id) for item in catalog.instruments
    )
    for instrument in catalog.instruments:
        pair = (instrument.product.exchange_id, instrument.product.product_id)
        if pair in all_target_ids:
            catalog_by_product[pair].append(instrument)
        else:
            outside_catalog_ids.append(instrument.instrument_id)
            if instrument.asset_type is not None and instrument.asset_type.casefold() == "future":
                outside_future_products.add(instrument.product)

    source_rows_by_product = defaultdict(list)
    outside_rows = []
    source_identity_counts = Counter(
        (source.source_id, source.snapshot_id, row.product.exchange_id, row.instrument_id)
        for source in sources
        for row in source.rows
    )
    duplicate_source_identity_keys = {
        key for key, count in source_identity_counts.items() if count > 1
    }
    for source in sources:
        for row in source.rows:
            pair = (row.product.exchange_id, row.product.product_id)
            if pair in all_target_ids:
                source_rows_by_product[pair].append((source, row))
            else:
                outside_rows.append(row)

    candidates = []
    coverage_rows = []
    diagnostics = []
    for product in product_keys:
        pair = (product.exchange_id, product.product_id)
        catalog_rows = tuple(catalog_by_product.get(pair, ()))
        catalog_counts = Counter(row.instrument_id for row in catalog_rows)
        duplicate_catalog = tuple(
            sorted(
                instrument_id
                for instrument_id, count in catalog_counts.items()
                if count > 1 or catalog_identity_counts[(product.exchange_id, instrument_id)] > 1
            )
        )
        expected_ids = tuple(sorted(row.instrument_id for row in catalog_rows))
        expected_id_set = set(expected_ids)

        exchange_sources = tuple(sources_by_exchange.get(product.exchange_id, ()))
        chosen_source = exchange_sources[0] if len(exchange_sources) == 1 else None
        product_source_rows = tuple(source_rows_by_product.get(pair, ()))
        row_counts = Counter(row.instrument_id for _source, row in product_source_rows)
        duplicate_source = tuple(
            sorted(
                row.instrument_id
                for source, row in product_source_rows
                if row_counts[row.instrument_id] > 1
                or (
                    source.source_id,
                    source.snapshot_id,
                    row.product.exchange_id,
                    row.instrument_id,
                )
                in duplicate_source_identity_keys
            )
        )
        duplicate_source = tuple(dict.fromkeys(duplicate_source))
        source_ids = tuple(sorted({source.source_id for source in exchange_sources}))
        unmatched_rows = tuple(
            sorted(
                row.instrument_id
                for _source, row in product_source_rows
                if row.instrument_id not in expected_id_set
            )
        )

        unique_source_rows = {
            row.instrument_id: (source, row)
            for source, row in product_source_rows
            if row_counts[row.instrument_id] == 1
            and (
                source.source_id,
                source.snapshot_id,
                row.product.exchange_id,
                row.instrument_id,
            )
            not in duplicate_source_identity_keys
        }
        catalog_unique = {
            row.instrument_id: row
            for row in catalog_rows
            if catalog_counts[row.instrument_id] == 1
            and catalog_identity_counts[(product.exchange_id, row.instrument_id)] == 1
        }
        joined_values = {}
        ranking_ids = []
        invalid_values = []
        for instrument_id, (source, row) in unique_source_rows.items():
            if chosen_source is None:
                continue
            if instrument_id not in catalog_unique:
                continue
            ranking_ids.append(instrument_id)
            joined_values[instrument_id] = (row.open_interest, row.volume)
            if not _valid_nonnegative_number(row.open_interest) or not _valid_nonnegative_number(
                row.volume
            ):
                invalid_values.append(instrument_id)

        missing_ranking_ids = tuple(
            sorted(
                row.instrument_id
                for row in catalog_rows
                if row.asset_type is not None
                and row.asset_type.casefold() == "future"
                and row.instrument_id not in joined_values
            )
        )

        blockers = []
        if len(catalog_rows) == 0:
            blockers.append("CATALOG_PRODUCT_MISSING")
        if not catalog.complete:
            blockers.append("CATALOG_SNAPSHOT_INCOMPLETE")
        if duplicate_catalog:
            blockers.append("DUPLICATE_CATALOG_INSTRUMENT_ID")
        if len(exchange_sources) == 0:
            blockers.append("EXCHANGE_RANKING_SOURCE_MISSING")
        elif len(exchange_sources) > 1:
            blockers.append("EXCHANGE_RANKING_SOURCE_AMBIGUOUS")
        if chosen_source is not None:
            if not chosen_source.finalized:
                blockers.append("RANKING_NOT_FINALIZED")
            if not chosen_source.latest_available:
                blockers.append("RANKING_SNAPSHOT_NOT_LATEST")
            if chosen_source.unscoped_join_issue_count:
                blockers.append("SOURCE_JOIN_HAS_UNSCOPED_ISSUES")
        if unmatched_rows:
            blockers.append("UNMATCHED_SOURCE_INSTRUMENT_ID")
        if duplicate_source:
            blockers.append("DUPLICATE_SOURCE_INSTRUMENT_ID")
        if missing_ranking_ids:
            blockers.append("RANKING_ROWS_MISSING_FOR_CATALOG_FUTURES")
        if invalid_values:
            blockers.append("RANKING_VALUE_INVALID")

        for instrument in catalog_rows:
            open_interest, volume = joined_values.get(instrument.instrument_id, (None, None))
            candidates.append(
                FuturesContractRecord(
                    product=instrument.product,
                    instrument_id=instrument.instrument_id,
                    asset_type=instrument.asset_type,
                    is_trading=instrument.is_trading,
                    expiry_date=instrument.expiry_date,
                    open_interest=open_interest,
                    volume=volume,
                )
            )

        coverage_rows.append(
            ProductRankingCoverage(
                product=product,
                candidate_count=len(catalog_rows),
                expected_instrument_ids=expected_ids,
                ranking_instrument_ids=tuple(sorted(ranking_ids)),
                candidate_set_complete=(
                    catalog.complete and bool(catalog_rows) and not duplicate_catalog
                ),
                ranking_values_complete=(
                    chosen_source is not None
                    and chosen_source.unscoped_join_issue_count == 0
                    and not unmatched_rows
                    and not duplicate_source
                    and not missing_ranking_ids
                    and not invalid_values
                ),
                finalized=chosen_source.finalized if chosen_source is not None else False,
                latest_available=(
                    chosen_source.latest_available if chosen_source is not None else False
                ),
                ranking_trading_day=chosen_source.trading_day
                if chosen_source is not None
                else None,
                open_interest_unit=(
                    chosen_source.open_interest_unit if chosen_source is not None else None
                ),
                volume_unit=chosen_source.volume_unit if chosen_source is not None else None,
            )
        )
        diagnostics.append(
            RankingProductCoverage(
                product=product,
                source_ids=source_ids,
                catalog_candidate_count=len(catalog_rows),
                ranking_row_count=len(product_source_rows),
                ranking_instrument_ids=tuple(sorted(ranking_ids)),
                missing_ranking_instrument_ids=missing_ranking_ids,
                unmatched_source_instrument_ids=unmatched_rows,
                duplicate_catalog_instrument_ids=duplicate_catalog,
                duplicate_source_instrument_ids=duplicate_source,
                blockers=tuple(dict.fromkeys(blockers)),
            )
        )

    snapshot = None
    if sources and not outside_future_products:
        composite_digest = _composite_source_digest(sources)
        available_at = max(
            (item.available_at for item in sources),
            key=lambda value: value.astimezone(timezone.utc),
        )
        retrieved_at = max(
            (item.retrieved_at for item in sources),
            key=lambda value: value.astimezone(timezone.utc),
        )
        snapshot = MainContractRankingSnapshot(
            source_id=_COMPOSITE_SOURCE_ID,
            snapshot_id="composite:" + composite_digest,
            source_sha256=composite_digest,
            available_at=available_at,
            retrieved_at=retrieved_at,
            catalog_source_id=catalog.source_id,
            catalog_snapshot_id=catalog.snapshot_id,
            catalog_sha256=catalog.source_sha256,
            catalog_available_at=catalog.available_at,
            catalog_retrieved_at=catalog.retrieved_at,
            coverage=tuple(coverage_rows),
            candidates=tuple(candidates),
        )

    return RankingAggregationResult(
        snapshot=snapshot,
        target_products=product_keys,
        ranking_sources=sources,
        coverage=tuple(diagnostics),
        catalog_instrument_ids_outside_target=tuple(sorted(outside_catalog_ids)),
        catalog_future_products_outside_target=tuple(
            sorted(
                outside_future_products,
                key=lambda item: (item.exchange_id, item.product_id),
            )
        ),
        ranking_rows_outside_target=tuple(
            sorted(
                outside_rows,
                key=lambda row: (
                    row.product.exchange_id,
                    row.product.product_id,
                    row.instrument_id,
                ),
            )
        ),
    )
