"""Point-in-time futures main-contract selection and rollover contracts.

This module contains only deterministic policy and evidence types.  It does
not query a broker, choose a data provider, or send orders.  A source adapter
must supply a complete candidate inventory and complete, finalized rankings
from the previous trading day for the legacy policy.  The explicit CTP query
policy consumes current-day catalog and depth-query evidence and never labels
that snapshot as finalized EOD.

The default policy ranks actual monthly futures by prior-day open interest,
then volume, then expiry date, then the provider's exact InstrumentID.  The
InstrumentID is retained verbatim for routing; only exchange/product keys are
canonicalized for comparisons.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence, Tuple, Union


_SOURCE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONTH_CONTRACT = re.compile(r"^[A-Za-z]{1,8}([0-9]{3,4})$")
_KNOWN_NON_FUTURES = frozenset(
    {
        "option",
        "options",
        "combination",
        "spot",
        "efp",
        "spot_option",
        "tas",
        "mi",
        "index",
    }
)
_CTP_PRODUCT_CLASS_ASSET_TYPE = {
    "1": "future",
    "2": "option",
    "3": "combination",
    "4": "spot",
    "5": "efp",
    "6": "spot_option",
    "7": "tas",
    "I": "mi",
}
_ASSET_TYPE_ALIASES = {"futures": "future", "options": "option"}
LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_V1 = "legacy_previous_complete_day_eod_oi_v1"
CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_V1 = "ctp_query_snapshot_equal_weight_v1"
RANKING_MODE_LEGACY_PRIOR_DAY_OI = "legacy_previous_complete_day_eod_oi_v1"
RANKING_MODE_CTP_QUERY_SNAPSHOT = "ctp_query_snapshot_equal_weight_v1"
_QUERY_METRIC_MAX_DIGITS = 512
_QUERY_METRIC_MAX_ABS_EXPONENT = 256
MAX_VISIBLE_CTP_PRODUCTS = 256
MAX_VISIBLE_FUTURE_PRODUCTS = MAX_VISIBLE_CTP_PRODUCTS
MAX_PRODUCT_INSTRUMENT_ROWS = 20_000
MAX_VISIBLE_DEPTH_ROWS = 20_000
MAX_STAGED_QUERY_REQUESTS = MAX_VISIBLE_FUTURE_PRODUCTS + 2
EXCLUSION_REASON_NO_LISTED_CONTRACTS = "NO_LISTED_CONTRACTS"


class TradingCalendarContractError(ValueError):
    """Raised when an exchange calendar cannot prove a requested date fact."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MainContractSelectionBlocked(RuntimeError):
    """Raised when code asks for an executable mapping from a blocked manifest."""


def _identity_text(value: Any, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("{} must be non-empty trimmed text".format(field_name))
    return value


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(field_name))
    return value


def _calendar_date(value: Any, field_name: str) -> date:
    # datetime is a date subclass, but is never a valid exchange-day label.
    if type(value) is not date:
        raise ValueError("{} must be a date, not a datetime".format(field_name))
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _key_order(key: "ProductKey") -> Tuple[str, str]:
    return key.exchange_id, key.product_id


def _number_as_decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def _decimal_text(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format(value, "f")


def _is_actual_month_contract(instrument_id: str, product_id: str) -> bool:
    """Accept CTP-style month contracts and reject continuous/index aliases."""

    match = _MONTH_CONTRACT.fullmatch(instrument_id)
    if match is None:
        return False
    digits = match.group(1)
    product_prefix = instrument_id[: -len(digits)]
    if product_prefix.casefold() != product_id.casefold():
        return False
    # CTP products use a three- or four-digit year/month suffix.  Requiring a
    # real month rejects synthetic 888/999/8888/9999 continuous aliases.
    month = int(digits[-2:])
    return 1 <= month <= 12


@dataclass(frozen=True)
class ProductKey:
    """Canonical product identity; instrument IDs remain untouched."""

    exchange_id: str
    product_id: str

    def __post_init__(self) -> None:
        exchange = _identity_text(self.exchange_id, "exchange_id").upper()
        product = _identity_text(self.product_id, "product_id").upper()
        object.__setattr__(self, "exchange_id", exchange)
        object.__setattr__(self, "product_id", product)


@dataclass(frozen=True)
class ExchangeTradingDay:
    """The CTP/session TradingDay being considered for one exchange."""

    exchange_id: str
    trading_day: date

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exchange_id", _identity_text(self.exchange_id, "exchange_id").upper()
        )
        _calendar_date(self.trading_day, "trading_day")


@dataclass(frozen=True)
class ExchangeTradingCalendar:
    """Immutable, source-described exchange trading-day evidence.

    ``complete`` means the supplied day sequence is exhaustive over the
    declared coverage interval.  The selector never substitutes weekdays or
    a local calendar when this evidence is missing or incomplete.
    """

    exchange_id: str
    source_id: str
    version: str
    available_at: datetime
    retrieved_at: datetime
    coverage_start: date
    coverage_through: date
    trading_days: Tuple[date, ...]
    complete: bool = True
    evidence_mode: str = "source_backed"
    source_manifest_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exchange_id", _identity_text(self.exchange_id, "exchange_id").upper()
        )
        object.__setattr__(self, "source_id", _identity_text(self.source_id, "calendar source_id"))
        object.__setattr__(self, "version", _identity_text(self.version, "calendar version"))
        if self.evidence_mode not in ("source_backed", "expected_rule_derived"):
            raise ValueError("unsupported calendar evidence_mode")
        if self.evidence_mode == "expected_rule_derived":
            if type(self.source_manifest_sha256) is not str or not _SOURCE_SHA256.fullmatch(
                self.source_manifest_sha256
            ):
                raise ValueError("expected-rule calendar requires a rules manifest SHA-256")
        elif self.source_manifest_sha256 is not None:
            raise ValueError("source_manifest_sha256 is only valid for expected-rule calendars")
        _aware_datetime(self.available_at, "calendar available_at")
        _aware_datetime(self.retrieved_at, "calendar retrieved_at")
        if self.retrieved_at.astimezone(timezone.utc) < self.available_at.astimezone(timezone.utc):
            raise ValueError("calendar retrieved_at precedes available_at")
        start = _calendar_date(self.coverage_start, "coverage_start")
        through = _calendar_date(self.coverage_through, "coverage_through")
        if through < start:
            raise ValueError("calendar coverage_through precedes coverage_start")
        days = tuple(self.trading_days)
        if any(type(day) is not date for day in days):
            raise ValueError("calendar trading_days must contain only dates")
        if tuple(sorted(set(days))) != days:
            raise ValueError("calendar trading_days must be unique and ascending")
        if any(day < start or day > through for day in days):
            raise ValueError("calendar trading day lies outside its declared coverage")
        if type(self.complete) is not bool:
            raise ValueError("calendar complete must be a bool")
        object.__setattr__(self, "trading_days", days)

    @property
    def evidence_sha256(self) -> str:
        projection = {
            "exchange_id": self.exchange_id,
            "source_id": self.source_id,
            "version": self.version,
            "available_at": _utc_text(self.available_at),
            "retrieved_at": _utc_text(self.retrieved_at),
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_through": self.coverage_through.isoformat(),
            "complete": self.complete,
            "trading_days": [day.isoformat() for day in self.trading_days],
        }
        if self.evidence_mode != "source_backed":
            projection["evidence_mode"] = self.evidence_mode
            projection["source_manifest_sha256"] = self.source_manifest_sha256
        return _canonical_json_sha256(projection)

    def previous_complete_trading_day(self, current_trading_day: date) -> date:
        if not self.complete:
            raise TradingCalendarContractError("CALENDAR_INCOMPLETE")
        current = _calendar_date(current_trading_day, "current_trading_day")
        if current < self.coverage_start or current > self.coverage_through:
            raise TradingCalendarContractError("CURRENT_DAY_OUTSIDE_CALENDAR")
        try:
            index = self.trading_days.index(current)
        except ValueError:
            raise TradingCalendarContractError("CURRENT_DAY_NOT_TRADING_DAY") from None
        if index == 0:
            raise TradingCalendarContractError("PRIOR_TRADING_DAY_UNAVAILABLE")
        return self.trading_days[index - 1]

    def trading_days_to_expiry(self, current_trading_day: date, expiry_date: date) -> int:
        if not self.complete:
            raise TradingCalendarContractError("CALENDAR_INCOMPLETE")
        current = _calendar_date(current_trading_day, "current_trading_day")
        expiry = _calendar_date(expiry_date, "expiry_date")
        if current not in self.trading_days:
            raise TradingCalendarContractError("CURRENT_DAY_NOT_TRADING_DAY")
        if expiry > self.coverage_through or expiry < self.coverage_start:
            raise TradingCalendarContractError("EXPIRY_OUTSIDE_CALENDAR")
        if expiry not in self.trading_days:
            raise TradingCalendarContractError("EXPIRY_NOT_COVERED_AS_TRADING_DAY")
        return sum(current < day <= expiry for day in self.trading_days)


@dataclass(frozen=True)
class RolloverBoundaryEvidence:
    """Source evidence for the first session open of a new TradingDay.

    Session boundary resolution stays with the shared exchange-calendar
    adapter.  The rollover planner accepts only this explicit evidence; it
    never derives a boundary from local midnight or the machine clock.
    """

    boundary_id: str
    source_id: str
    source_sha256: str
    available_at: datetime
    retrieved_at: datetime
    effective_at: datetime
    trading_days: Tuple[ExchangeTradingDay, ...]
    boundary_kind: str = "FIRST_SESSION_OPEN_FOR_TRADING_DAY"

    def __post_init__(self) -> None:
        _identity_text(self.boundary_id, "boundary_id")
        _identity_text(self.source_id, "boundary source_id")
        if type(self.source_sha256) is not str or not _SOURCE_SHA256.fullmatch(self.source_sha256):
            raise ValueError("boundary source_sha256 must be lowercase SHA-256 hex")
        _aware_datetime(self.available_at, "boundary available_at")
        _aware_datetime(self.retrieved_at, "boundary retrieved_at")
        _aware_datetime(self.effective_at, "boundary effective_at")
        if self.retrieved_at.astimezone(timezone.utc) < self.available_at.astimezone(timezone.utc):
            raise ValueError("boundary retrieved_at precedes available_at")
        if self.boundary_kind != "FIRST_SESSION_OPEN_FOR_TRADING_DAY":
            raise ValueError("unsupported rollover boundary kind")
        days = tuple(self.trading_days)
        if any(not isinstance(item, ExchangeTradingDay) for item in days):
            raise ValueError("boundary trading_days must contain ExchangeTradingDay records")
        exchange_ids = [item.exchange_id for item in days]
        if len(set(exchange_ids)) != len(exchange_ids):
            raise ValueError("boundary trading_days contains duplicate exchanges")
        object.__setattr__(
            self, "trading_days", tuple(sorted(days, key=lambda item: item.exchange_id))
        )


@dataclass(frozen=True)
class FuturesContractRecord:
    """One source candidate, including rows that the policy will exclude."""

    product: ProductKey
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]
    open_interest: Any
    volume: Any

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("contract product must be a ProductKey")
        if type(self.instrument_id) is not str:
            raise ValueError("instrument_id must be text")
        if self.asset_type is not None and type(self.asset_type) is not str:
            raise ValueError("asset_type must be text or None")
        if self.is_trading is not None and type(self.is_trading) is not bool:
            raise ValueError("is_trading must be bool or None")
        if self.expiry_date is not None and type(self.expiry_date) is not date:
            raise ValueError("expiry_date must be date or None")


@dataclass(frozen=True)
class ProductRankingCoverage:
    """Completeness and units for one exchange/product's ranking rows."""

    product: ProductKey
    candidate_count: int
    expected_instrument_ids: Tuple[str, ...]
    ranking_instrument_ids: Tuple[str, ...]
    candidate_set_complete: bool
    ranking_values_complete: bool
    finalized: bool
    latest_available: bool
    ranking_trading_day: Optional[date]
    open_interest_unit: Optional[str]
    volume_unit: Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("coverage product must be a ProductKey")
        if type(self.candidate_count) is not int or self.candidate_count < 0:
            raise ValueError("candidate_count must be a non-negative int")
        for name in ("expected_instrument_ids", "ranking_instrument_ids"):
            ids = tuple(getattr(self, name))
            if any(type(instrument_id) is not str for instrument_id in ids):
                raise ValueError("{} must contain instrument ID text".format(name))
            object.__setattr__(self, name, tuple(sorted(ids)))
        for name in (
            "candidate_set_complete",
            "ranking_values_complete",
            "finalized",
            "latest_available",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError("{} must be a bool".format(name))
        if self.ranking_trading_day is not None:
            _calendar_date(self.ranking_trading_day, "ranking_trading_day")
        for name in ("open_interest_unit", "volume_unit"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not str or not value or value != value.strip()
            ):
                raise ValueError("{} must be non-empty text or None".format(name))


@dataclass(frozen=True)
class MainContractRankingSnapshot:
    """A point-in-time source snapshot consumed by the pure selector.

    The producer digest must identify the exact source payload.  It does not
    authenticate the producer by itself; that remains the adapter's duty.
    """

    source_id: str
    snapshot_id: str
    source_sha256: str
    available_at: datetime
    retrieved_at: datetime
    catalog_source_id: str
    catalog_snapshot_id: str
    catalog_sha256: str
    catalog_available_at: datetime
    catalog_retrieved_at: datetime
    coverage: Tuple[ProductRankingCoverage, ...]
    candidates: Tuple[FuturesContractRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage", tuple(self.coverage))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        if any(not isinstance(item, ProductRankingCoverage) for item in self.coverage):
            raise ValueError("coverage must contain ProductRankingCoverage records")
        if any(not isinstance(item, FuturesContractRecord) for item in self.candidates):
            raise ValueError("candidates must contain FuturesContractRecord records")


@dataclass(frozen=True)
class QuerySnapshotSourceEvidence:
    """Public provenance for one completed CTP query-result snapshot.

    ``available_at`` is deliberately represented by ``completed_at``.  It is
    the time the complete query result became available, not a per-row market
    receive time.  Query rows retain their native event-time fields separately
    for audit and are never made fresh by this completion time.
    """

    source_id: Any
    source_kind: Any
    snapshot_id: Any
    source_sha256: Any
    request_id: Any
    connection_generation: Any
    trading_day: Any
    started_at: Any
    completed_at: Any
    retrieved_at: Any
    complete: Any
    is_last_seen: Any
    record_count: Any
    request_filters: Any = None
    record_limit: Any = None
    record_limit_exceeded: Any = None


@dataclass(frozen=True)
class QuerySnapshotProductEvidence:
    """A ProductKey bound to its exact native CTP product filters."""

    product: ProductKey
    native_exchange_id: str
    native_product_id: str
    product_class: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("product must be a ProductKey")
        for name in ("native_exchange_id", "native_product_id", "product_class"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("{} must be non-empty trimmed text".format(name))
        if self.product.exchange_id != self.native_exchange_id.upper():
            raise ValueError("native exchange does not match canonical product")
        if self.product.product_id != self.native_product_id.upper():
            raise ValueError("native product does not match canonical product")
        if self.product_class != "1":
            raise ValueError("query-set products must be CTP futures")


@dataclass(frozen=True)
class QuerySnapshotExcludedProductEvidence:
    """One known non-futures product from the complete visible product query."""

    product: ProductKey
    native_exchange_id: str
    native_product_id: str
    product_class: str
    asset_type: str
    exclusion_reason: str = "NON_FUTURE_CTP_PRODUCT_CLASS"

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("product must be a ProductKey")
        for name in ("native_exchange_id", "native_product_id", "product_class", "asset_type"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("{} must be non-empty trimmed text".format(name))
        if self.product.exchange_id != self.native_exchange_id.upper():
            raise ValueError("native exchange does not match canonical product")
        if self.product.product_id != self.native_product_id.upper():
            raise ValueError("native product does not match canonical product")
        expected_asset_type = _CTP_PRODUCT_CLASS_ASSET_TYPE.get(self.product_class)
        if expected_asset_type is None or self.product_class == "1":
            raise ValueError("excluded products must have a known non-futures CTP class")
        if self.asset_type != expected_asset_type:
            raise ValueError("excluded product class and asset type disagree")
        if self.exclusion_reason != "NON_FUTURE_CTP_PRODUCT_CLASS":
            raise ValueError("excluded product reason is invalid")


@dataclass(frozen=True)
class QuerySnapshotSetEvidence:
    """One typed product query, exact per-product instrument queries, and depth."""

    source_id: Any
    snapshot_id: Any
    source_sha256: Any
    products: Tuple[QuerySnapshotProductEvidence, ...]
    requests: Tuple[QuerySnapshotSourceEvidence, ...]
    excluded_products: Tuple[QuerySnapshotExcludedProductEvidence, ...] = ()

    def __post_init__(self) -> None:
        products = tuple(self.products)
        requests = tuple(self.requests)
        excluded_products = tuple(self.excluded_products)
        if not products or len(products) > MAX_VISIBLE_FUTURE_PRODUCTS:
            raise ValueError("query-set products must be non-empty and bounded")
        if len(products) + len(excluded_products) > MAX_VISIBLE_CTP_PRODUCTS:
            raise ValueError("query-set classified products exceed the visible product cap")
        if any(not isinstance(item, QuerySnapshotProductEvidence) for item in products):
            raise ValueError("query-set products must contain QuerySnapshotProductEvidence")
        if any(
            not isinstance(item, QuerySnapshotExcludedProductEvidence)
            for item in excluded_products
        ):
            raise ValueError(
                "query-set exclusions must contain QuerySnapshotExcludedProductEvidence"
            )
        if any(not isinstance(item, QuerySnapshotSourceEvidence) for item in requests):
            raise ValueError("query-set requests must contain QuerySnapshotSourceEvidence")
        if len(requests) != len(products) + 2 or len(requests) > MAX_STAGED_QUERY_REQUESTS:
            raise ValueError("query-set request count does not match its products")
        product_keys = tuple(item.product for item in products)
        excluded_keys = tuple(item.product for item in excluded_products)
        all_product_keys = product_keys + excluded_keys
        if len(set(all_product_keys)) != len(all_product_keys):
            raise ValueError("query-set products contain canonical collisions")
        object.__setattr__(self, "products", products)
        object.__setattr__(self, "requests", requests)
        object.__setattr__(self, "excluded_products", excluded_products)

    @property
    def product_keys(self) -> Tuple[ProductKey, ...]:
        return tuple(item.product for item in self.products)


def query_snapshot_set_digest(
    products: Sequence[QuerySnapshotProductEvidence],
    requests: Sequence[QuerySnapshotSourceEvidence],
    excluded_products: Sequence[QuerySnapshotExcludedProductEvidence] = (),
) -> str:
    """Digest classified product rows and request receipts without retaining raw rows.

    The empty-exclusion form retains the exact v1 encoding so existing class-1
    query-set evidence remains readable.  A non-empty exclusion set is added
    to the v2 payload and is therefore bound to the query-set digest.
    """

    def time_value(value: Any) -> Optional[str]:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    def scalar(value: Any) -> Any:
        if value is None or type(value) in (str, int, bool):
            return value
        if type(value) is date:
            return value.isoformat()
        return "<{}>".format(type(value).__name__)

    def filter_values(value: Any) -> Any:
        if type(value) is not tuple or any(
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
            for pair in value
        ):
            return "<invalid-request-filters>"
        return [list(pair) for pair in value]

    payload = {
        "schema": (
            "backtrader.ctp_query_snapshot_set.v2"
            if excluded_products
            else "backtrader.ctp_query_snapshot_set.v1"
        ),
        "products": [
            {
                "exchange_id": item.product.exchange_id,
                "product_id": item.product.product_id,
                "native_exchange_id": item.native_exchange_id,
                "native_product_id": item.native_product_id,
                "product_class": item.product_class,
            }
            for item in products
        ],
        "requests": [
            {
                "source_id": scalar(item.source_id),
                "source_kind": scalar(item.source_kind),
                "snapshot_id": scalar(item.snapshot_id),
                "source_sha256": scalar(item.source_sha256),
                "request_id": scalar(item.request_id),
                "connection_generation": scalar(item.connection_generation),
                "trading_day": scalar(item.trading_day),
                "started_at": time_value(item.started_at),
                "completed_at": time_value(item.completed_at),
                "retrieved_at": time_value(item.retrieved_at),
                "complete": scalar(item.complete),
                "is_last_seen": scalar(item.is_last_seen),
                "record_count": scalar(item.record_count),
                "request_filters": filter_values(item.request_filters),
                "record_limit": scalar(item.record_limit),
                "record_limit_exceeded": scalar(item.record_limit_exceeded),
            }
            for item in requests
        ],
    }
    if excluded_products:
        payload["excluded_products"] = [
            {
                "exchange_id": item.product.exchange_id,
                "product_id": item.product.product_id,
                "native_exchange_id": item.native_exchange_id,
                "native_product_id": item.native_product_id,
                "product_class": item.product_class,
                "asset_type": item.asset_type,
                "exclusion_reason": item.exclusion_reason,
            }
            for item in excluded_products
        ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FuturesContractCatalogRecord:
    """A catalog row with exact provider InstrumentID and exclusion facts."""

    product: ProductKey
    instrument_id: str
    asset_type: Optional[str]
    is_trading: Optional[bool]
    expiry_date: Optional[date]
    product_class: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("catalog product must be a ProductKey")
        if type(self.instrument_id) is not str:
            raise ValueError("catalog instrument_id must be text")
        if self.asset_type is not None and type(self.asset_type) is not str:
            raise ValueError("catalog asset_type must be text or None")
        if self.is_trading is not None and type(self.is_trading) is not bool:
            raise ValueError("catalog is_trading must be bool or None")
        if self.expiry_date is not None and type(self.expiry_date) is not date:
            raise ValueError("catalog expiry_date must be date or None")
        if self.product_class is not None and type(self.product_class) is not str:
            raise ValueError("catalog product_class must be text or None")


@dataclass(frozen=True)
class CurrentDayQuoteRecord:
    """One raw row returned by the all-visible current-day depth query."""

    exchange_id: str
    instrument_id: str
    trading_day: Any
    open_interest: Any
    volume: Any
    action_day: Optional[str] = None
    update_time: Optional[str] = None
    update_millisec: Optional[int] = None

    def __post_init__(self) -> None:
        if type(self.exchange_id) is not str:
            raise ValueError("quote exchange_id must be text")
        if type(self.instrument_id) is not str:
            raise ValueError("quote instrument_id must be text")
        if self.trading_day is not None and type(self.trading_day) is not date:
            raise ValueError("quote trading_day must be date or None")
        if self.action_day is not None and type(self.action_day) is not str:
            raise ValueError("quote action_day must be text or None")
        if self.update_time is not None and type(self.update_time) is not str:
            raise ValueError("quote update_time must be text or None")
        if self.update_millisec is not None and (
            type(self.update_millisec) is not int or self.update_millisec < 0
        ):
            raise ValueError("quote update_millisec must be a non-negative int or None")


@dataclass(frozen=True)
class MainContractQuerySnapshot:
    """Real completed CTP query results plus the surrounding session facts.

    Catalog and quote records are retained verbatim as tuples so duplicate or
    unexpected IDs remain visible to the selector.  The adapter must not
    deduplicate or pre-filter either collection.
    """

    catalog_source: Optional[QuerySnapshotSourceEvidence]
    quote_source: Optional[QuerySnapshotSourceEvidence]
    catalog_records: Tuple[FuturesContractCatalogRecord, ...]
    quote_records: Tuple[CurrentDayQuoteRecord, ...]
    session_trading_day_before: Any
    session_trading_day_after: Any
    session_generation_before: Any
    session_generation_after: Any
    query_set: Optional[QuerySnapshotSetEvidence] = None

    def __post_init__(self) -> None:
        catalog = tuple(self.catalog_records)
        quotes = tuple(self.quote_records)
        if any(not isinstance(item, FuturesContractCatalogRecord) for item in catalog):
            raise ValueError("catalog_records must contain FuturesContractCatalogRecord records")
        if any(not isinstance(item, CurrentDayQuoteRecord) for item in quotes):
            raise ValueError("quote_records must contain CurrentDayQuoteRecord records")
        if self.catalog_source is not None and not isinstance(
            self.catalog_source, QuerySnapshotSourceEvidence
        ):
            raise ValueError("catalog_source must be QuerySnapshotSourceEvidence or None")
        if self.quote_source is not None and not isinstance(
            self.quote_source, QuerySnapshotSourceEvidence
        ):
            raise ValueError("quote_source must be QuerySnapshotSourceEvidence or None")
        if self.query_set is not None and not isinstance(
            self.query_set, QuerySnapshotSetEvidence
        ):
            raise ValueError("query_set must be QuerySnapshotSetEvidence or None")
        if self.query_set is not None and (
            self.catalog_source is not None or self.quote_source is not None
        ):
            raise ValueError("query-set snapshots cannot also claim legacy source pair")
        object.__setattr__(self, "catalog_records", catalog)
        object.__setattr__(self, "quote_records", quotes)


@dataclass(frozen=True)
class MainContractPolicy:
    """Frozen main-contract ranking and expiry-safety policy."""

    policy_id: str = "prior-day-oi-volume-expiry-id-v1"
    minimum_trading_days_to_expiry: int = 5
    ranking_mode: str = RANKING_MODE_LEGACY_PRIOR_DAY_OI
    max_snapshot_age_seconds: int = 300
    max_collection_span_seconds: int = 300

    def __post_init__(self) -> None:
        _identity_text(self.policy_id, "policy_id")
        if (
            type(self.minimum_trading_days_to_expiry) is not int
            or self.minimum_trading_days_to_expiry < 0
        ):
            raise ValueError("minimum_trading_days_to_expiry must be a non-negative int")
        if self.ranking_mode not in (
            RANKING_MODE_LEGACY_PRIOR_DAY_OI,
            RANKING_MODE_CTP_QUERY_SNAPSHOT,
        ):
            raise ValueError("unsupported main-contract ranking_mode")
        for name in ("max_snapshot_age_seconds", "max_collection_span_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("{} must be a non-negative int".format(name))


DEFAULT_MAIN_CONTRACT_POLICY = MainContractPolicy()
LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_POLICY = MainContractPolicy(
    policy_id=LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_V1,
    ranking_mode=RANKING_MODE_LEGACY_PRIOR_DAY_OI,
)
CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY = MainContractPolicy(
    policy_id=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_V1,
    ranking_mode=RANKING_MODE_CTP_QUERY_SNAPSHOT,
)


@dataclass(frozen=True)
class CalendarEvidence:
    exchange_id: str
    source_id: str
    version: str
    available_at: datetime
    retrieved_at: datetime
    coverage_start: date
    coverage_through: date
    complete: bool
    trading_days: Tuple[date, ...]
    sha256: str
    evidence_mode: str = "source_backed"
    source_manifest_sha256: Optional[str] = None


@dataclass(frozen=True)
class TradingDayReference:
    exchange_id: str
    current_trading_day: date
    expected_prior_trading_day: Optional[date]


@dataclass(frozen=True)
class ContractAssessment:
    product: ProductKey
    instrument_id: str
    status: str
    reason: Optional[str]
    expiry_date: Optional[date]
    trading_days_to_expiry: Optional[int]
    open_interest: Optional[str]
    volume: Optional[str]
    rank: Optional[int]
    trading_days_to_expiry_lower_bound: Optional[int] = None
    expiry_distance_exact: bool = False
    ranking_score: Optional[str] = None
    asset_type: Optional[str] = None
    is_trading: Optional[bool] = None
    product_class: Optional[str] = None
    quote_trading_day: Optional[date] = None
    action_day: Optional[str] = None
    update_time: Optional[str] = None
    update_millisec: Optional[int] = None


@dataclass(frozen=True)
class MainContractQueryCoverage:
    """Catalog and current-query row coverage for one target product."""

    product: ProductKey
    catalog_instrument_ids: Tuple[str, ...]
    expected_quote_instrument_ids: Tuple[str, ...]
    observed_quote_instrument_ids: Tuple[str, ...]
    metric_unit: str = "contracts"

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("query coverage product must be a ProductKey")
        for name in (
            "catalog_instrument_ids",
            "expected_quote_instrument_ids",
            "observed_quote_instrument_ids",
        ):
            values = tuple(getattr(self, name))
            if any(type(value) is not str for value in values):
                raise ValueError("{} must contain exact instrument ID text".format(name))
            object.__setattr__(self, name, values)
        _identity_text(self.metric_unit, "metric_unit")


@dataclass(frozen=True)
class ProductSelection:
    product: ProductKey
    in_target_pool: bool
    status: str
    expected_prior_trading_day: Optional[date]
    ranking_trading_day: Optional[date]
    selected_instrument_id: Optional[str]
    ranked_instrument_ids: Tuple[str, ...]
    excluded_instrument_ids: Tuple[str, ...]
    blockers: Tuple[str, ...]
    selected_score: Optional[str] = None
    exclusion_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.exclusion_reason is None:
            return
        if self.exclusion_reason != EXCLUSION_REASON_NO_LISTED_CONTRACTS:
            raise ValueError("unsupported product exclusion_reason")
        if self.in_target_pool or self.status != "EXCLUDED":
            raise ValueError("exclusion_reason requires an out-of-pool EXCLUDED product")


@dataclass(frozen=True)
class MainContractManifest:
    """Immutable selection outcome and enough public evidence to reproduce it."""

    status: str
    decision_at: datetime
    policy: MainContractPolicy
    target_products: Tuple[ProductKey, ...]
    source_id: Optional[str]
    source_snapshot_id: Optional[str]
    source_sha256: Optional[str]
    source_available_at: Optional[datetime]
    source_retrieved_at: Optional[datetime]
    catalog_source_id: Optional[str]
    catalog_snapshot_id: Optional[str]
    catalog_sha256: Optional[str]
    catalog_available_at: Optional[datetime]
    catalog_retrieved_at: Optional[datetime]
    trading_days: Tuple[TradingDayReference, ...]
    calendars: Tuple[CalendarEvidence, ...]
    coverage: Tuple[ProductRankingCoverage, ...]
    products: Tuple[ProductSelection, ...]
    candidates: Tuple[ContractAssessment, ...]
    blockers: Tuple[str, ...]
    query_snapshot: Optional[MainContractQuerySnapshot] = None
    query_coverage: Tuple[MainContractQueryCoverage, ...] = ()

    def __post_init__(self) -> None:
        _aware_datetime(self.decision_at, "decision_at")
        for name in (
            "target_products",
            "trading_days",
            "calendars",
            "coverage",
            "products",
            "candidates",
            "blockers",
            "query_coverage",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def selected_mapping(self) -> Tuple[Tuple[ProductKey, str], ...]:
        """Return the executable mapping only when every target product is ready."""

        if self.status != "READY":
            raise MainContractSelectionBlocked(
                "main-contract manifest is blocked: {}".format(", ".join(self.blockers))
            )
        selected = tuple(item for item in self.products if item.in_target_pool)
        targets = set(self.target_products)
        if (
            self.blockers
            or not targets
            or len(targets) != len(self.target_products)
            or len(selected) != len(targets)
            or {item.product for item in selected} != targets
            or any(
                item.status != "READY"
                or item.blockers
                or not isinstance(item.selected_instrument_id, str)
                or not item.selected_instrument_id.strip()
                or not item.ranked_instrument_ids
                or item.selected_instrument_id != item.ranked_instrument_ids[0]
                for item in selected
            )
        ):
            raise MainContractSelectionBlocked("main-contract manifest has an incomplete mapping")
        by_product = {item.product: item.selected_instrument_id for item in selected}
        return tuple((product, by_product[product]) for product in self.target_products)

    def to_dict(self) -> dict[str, Any]:
        """Create a fresh JSON-safe audit representation."""

        query_mode = self.policy.ranking_mode == RANKING_MODE_CTP_QUERY_SNAPSHOT
        projection = {
            "schema": (
                "backtrader.futures_main_contract_manifest.v2"
                if query_mode
                else "backtrader.futures_main_contract_manifest.v1"
            ),
            "status": self.status,
            "decision_at": _utc_text(self.decision_at),
            "policy": {
                "policy_id": self.policy.policy_id,
                "minimum_trading_days_to_expiry": self.policy.minimum_trading_days_to_expiry,
                "ranking": [
                    "open_interest_desc",
                    "volume_desc",
                    "expiry_date_asc",
                    "instrument_id_asc",
                ],
            },
            "target_products": [_product_dict(item) for item in self.target_products],
            "source": None
            if all(
                value is None
                for value in (
                    self.source_id,
                    self.source_snapshot_id,
                    self.source_sha256,
                    self.source_available_at,
                    self.source_retrieved_at,
                    self.catalog_source_id,
                    self.catalog_snapshot_id,
                    self.catalog_sha256,
                    self.catalog_available_at,
                    self.catalog_retrieved_at,
                )
            )
            else {
                "source_id": self.source_id,
                "snapshot_id": self.source_snapshot_id,
                "sha256": self.source_sha256,
                "available_at": _utc_text(self.source_available_at)
                if self.source_available_at is not None
                else None,
                "retrieved_at": _utc_text(self.source_retrieved_at)
                if self.source_retrieved_at is not None
                else None,
                "catalog": {
                    "source_id": self.catalog_source_id,
                    "snapshot_id": self.catalog_snapshot_id,
                    "sha256": self.catalog_sha256,
                    "available_at": _utc_text(self.catalog_available_at)
                    if self.catalog_available_at is not None
                    else None,
                    "retrieved_at": _utc_text(self.catalog_retrieved_at)
                    if self.catalog_retrieved_at is not None
                    else None,
                },
            },
            "trading_days": [
                {
                    "exchange_id": item.exchange_id,
                    "current": item.current_trading_day.isoformat(),
                    "expected_prior_complete": item.expected_prior_trading_day.isoformat()
                    if item.expected_prior_trading_day is not None
                    else None,
                }
                for item in self.trading_days
            ],
            "calendars": [
                {
                    "exchange_id": item.exchange_id,
                    "source_id": item.source_id,
                    "version": item.version,
                    "available_at": _utc_text(item.available_at),
                    "retrieved_at": _utc_text(item.retrieved_at),
                    "coverage_start": item.coverage_start.isoformat(),
                    "coverage_through": item.coverage_through.isoformat(),
                    "complete": item.complete,
                    "trading_days": [day.isoformat() for day in item.trading_days],
                    "sha256": item.sha256,
                    **(
                        {
                            "evidence_mode": item.evidence_mode,
                            "source_manifest_sha256": item.source_manifest_sha256,
                        }
                        if item.evidence_mode != "source_backed"
                        else {}
                    ),
                }
                for item in self.calendars
            ],
            "coverage": [_coverage_dict(item) for item in self.coverage],
            "products": [
                {
                    "product": _product_dict(item.product),
                    "in_target_pool": item.in_target_pool,
                    "status": item.status,
                    "expected_prior_trading_day": item.expected_prior_trading_day.isoformat()
                    if item.expected_prior_trading_day is not None
                    else None,
                    "ranking_trading_day": item.ranking_trading_day.isoformat()
                    if item.ranking_trading_day is not None
                    else None,
                    "selected_instrument_id": item.selected_instrument_id,
                    "ranked_instrument_ids": list(item.ranked_instrument_ids),
                    "excluded_instrument_ids": list(item.excluded_instrument_ids),
                    "blockers": list(item.blockers),
                    **({"selected_score": item.selected_score} if query_mode else {}),
                    **(
                        {"exclusion_reason": item.exclusion_reason}
                        if item.exclusion_reason
                        else {}
                    ),
                }
                for item in self.products
            ],
            "candidates": [
                {
                    "product": _product_dict(item.product),
                    "instrument_id": item.instrument_id,
                    "status": item.status,
                    "reason": item.reason,
                    "expiry_date": item.expiry_date.isoformat()
                    if item.expiry_date is not None
                    else None,
                    "trading_days_to_expiry": item.trading_days_to_expiry,
                    "trading_days_to_expiry_lower_bound": item.trading_days_to_expiry_lower_bound,
                    "expiry_distance_exact": item.expiry_distance_exact,
                    "open_interest": item.open_interest,
                    "volume": item.volume,
                    "rank": item.rank,
                    **(
                        {
                            "ranking_score": item.ranking_score,
                            "asset_type": item.asset_type,
                            "is_trading": item.is_trading,
                            "product_class": item.product_class,
                            "quote_trading_day": item.quote_trading_day.isoformat()
                            if item.quote_trading_day is not None
                            else None,
                            "action_day": item.action_day,
                            "update_time": item.update_time,
                            "update_millisec": item.update_millisec,
                        }
                        if query_mode
                        else {}
                    ),
                }
                for item in self.candidates
            ],
            "blockers": list(self.blockers),
        }
        if query_mode:
            projection["policy"].update(
                {
                    "ranking_mode": self.policy.ranking_mode,
                    "score_formula": "0.5 * open_interest + 0.5 * volume",
                    "weights": {"open_interest": "0.5", "volume": "0.5"},
                    "metric_unit": "contracts",
                    "ranking": [
                        "equal_weight_score_desc",
                        "open_interest_desc",
                        "volume_desc",
                        "expiry_date_asc",
                        "exact_instrument_id_asc",
                    ],
                    "tie_break_order": [
                        "score_desc",
                        "open_interest_desc",
                        "volume_desc",
                        "expiry_date_asc",
                        "exact_instrument_id_asc",
                    ],
                    "max_snapshot_age_seconds": self.policy.max_snapshot_age_seconds,
                    "max_collection_span_seconds": self.policy.max_collection_span_seconds,
                }
            )
            projection["query_snapshot"] = _query_snapshot_dict(self.query_snapshot)
            projection["query_coverage"] = [
                {
                    "product": _product_dict(item.product),
                    "catalog_instrument_ids": list(item.catalog_instrument_ids),
                    "expected_quote_instrument_ids": list(item.expected_quote_instrument_ids),
                    "observed_quote_instrument_ids": list(item.observed_quote_instrument_ids),
                    "metric_unit": item.metric_unit,
                }
                for item in self.query_coverage
            ]
        return projection

    @property
    def manifest_sha256(self) -> str:
        return _canonical_json_sha256(self.to_dict())


def _product_dict(key: ProductKey) -> dict[str, str]:
    return {"exchange_id": key.exchange_id, "product_id": key.product_id}


def _coverage_dict(item: ProductRankingCoverage) -> dict[str, Any]:
    return {
        "product": _product_dict(item.product),
        "candidate_count": item.candidate_count,
        "expected_instrument_ids": list(item.expected_instrument_ids),
        "ranking_instrument_ids": list(item.ranking_instrument_ids),
        "candidate_set_complete": item.candidate_set_complete,
        "ranking_values_complete": item.ranking_values_complete,
        "finalized": item.finalized,
        "latest_available": item.latest_available,
        "ranking_trading_day": item.ranking_trading_day.isoformat()
        if item.ranking_trading_day is not None
        else None,
        "open_interest_unit": item.open_interest_unit,
        "volume_unit": item.volume_unit,
    }


def _calendar_evidence(calendar: ExchangeTradingCalendar) -> CalendarEvidence:
    return CalendarEvidence(
        exchange_id=calendar.exchange_id,
        source_id=calendar.source_id,
        version=calendar.version,
        available_at=calendar.available_at,
        retrieved_at=calendar.retrieved_at,
        coverage_start=calendar.coverage_start,
        coverage_through=calendar.coverage_through,
        complete=calendar.complete,
        trading_days=calendar.trading_days,
        sha256=calendar.evidence_sha256,
        evidence_mode=calendar.evidence_mode,
        source_manifest_sha256=calendar.source_manifest_sha256,
    )


def _blocked_product(
    product: ProductKey,
    *,
    expected_prior: Optional[date],
    ranking_day: Optional[date],
    blockers: Sequence[str],
    in_target_pool: bool = True,
) -> ProductSelection:
    return ProductSelection(
        product=product,
        in_target_pool=in_target_pool,
        status="BLOCKED" if in_target_pool else "OUT_OF_SCOPE",
        expected_prior_trading_day=expected_prior,
        ranking_trading_day=ranking_day,
        selected_instrument_id=None,
        ranked_instrument_ids=(),
        excluded_instrument_ids=(),
        blockers=tuple(blockers) if in_target_pool else (),
    )


def _source_blockers(
    snapshot: Optional[MainContractRankingSnapshot], decision_at: datetime
) -> Tuple[str, ...]:
    if snapshot is None:
        return ("RANKING_SOURCE_UNAVAILABLE",)
    blockers = list(
        _named_source_blockers(
            "RANKING",
            source_id=snapshot.source_id,
            snapshot_id=snapshot.snapshot_id,
            source_sha256=snapshot.source_sha256,
            available_at=snapshot.available_at,
            retrieved_at=snapshot.retrieved_at,
            decision_at=decision_at,
        )
    )
    blockers.extend(
        _named_source_blockers(
            "CATALOG",
            source_id=snapshot.catalog_source_id,
            snapshot_id=snapshot.catalog_snapshot_id,
            source_sha256=snapshot.catalog_sha256,
            available_at=snapshot.catalog_available_at,
            retrieved_at=snapshot.catalog_retrieved_at,
            decision_at=decision_at,
        )
    )
    return tuple(blockers)


def _named_source_blockers(
    name: str,
    *,
    source_id: Any,
    snapshot_id: Any,
    source_sha256: Any,
    available_at: Any,
    retrieved_at: Any,
    decision_at: datetime,
) -> Tuple[str, ...]:
    """Validate one source's point-in-time identity and observation metadata."""

    blockers = []
    if type(source_id) is not str or not source_id or source_id != source_id.strip():
        blockers.append("{}_SOURCE_ID_MISSING".format(name))
    if type(snapshot_id) is not str or not snapshot_id or snapshot_id != snapshot_id.strip():
        blockers.append("{}_SNAPSHOT_ID_MISSING".format(name))
    if type(source_sha256) is not str or not _SOURCE_SHA256.fullmatch(source_sha256):
        blockers.append("{}_SOURCE_DIGEST_INVALID".format(name))
    if (
        not isinstance(available_at, datetime)
        or available_at.tzinfo is None
        or available_at.utcoffset() is None
    ):
        blockers.append("{}_AVAILABLE_AT_INVALID".format(name))
    elif available_at.astimezone(timezone.utc) > decision_at.astimezone(timezone.utc):
        blockers.append("{}_NOT_AVAILABLE_AT_DECISION".format(name))
    if (
        not isinstance(retrieved_at, datetime)
        or retrieved_at.tzinfo is None
        or retrieved_at.utcoffset() is None
    ):
        blockers.append("{}_RETRIEVED_AT_INVALID".format(name))
    else:
        retrieved_at_utc = retrieved_at.astimezone(timezone.utc)
        if retrieved_at_utc > decision_at.astimezone(timezone.utc):
            blockers.append("{}_RETRIEVED_AFTER_DECISION".format(name))
        if (
            isinstance(available_at, datetime)
            and available_at.tzinfo is not None
            and available_at.utcoffset() is not None
            and retrieved_at_utc < available_at.astimezone(timezone.utc)
        ):
            blockers.append("{}_RETRIEVED_BEFORE_AVAILABLE".format(name))
    return tuple(blockers)


def _source_text(value: Any) -> Optional[str]:
    if type(value) is str and value and value == value.strip():
        return value
    return None


def _source_digest(value: Any) -> Optional[str]:
    if type(value) is str and _SOURCE_SHA256.fullmatch(value):
        return value
    return None


def _source_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
        return value
    return None


def _exact_equal_weight_score(open_interest: Decimal, volume: Decimal) -> Optional[Decimal]:
    """Return the exact Decimal mean without using the active Decimal context.

    Query metrics are normally small CTP integer counts.  A finite bound keeps
    hostile or malformed exponents from allocating enormous powers of ten;
    values outside that bound fail closed rather than silently rounding.
    """

    left = open_interest.as_tuple()
    right = volume.as_tuple()
    left_exponent = left.exponent
    right_exponent = right.exponent
    if (
        not isinstance(left_exponent, int)
        or not isinstance(right_exponent, int)
        or abs(left_exponent) > _QUERY_METRIC_MAX_ABS_EXPONENT
        or abs(right_exponent) > _QUERY_METRIC_MAX_ABS_EXPONENT
    ):
        return None
    if len(left.digits) > _QUERY_METRIC_MAX_DIGITS or len(right.digits) > _QUERY_METRIC_MAX_DIGITS:
        return None
    left_digits = "".join(str(digit) for digit in left.digits) or "0"
    right_digits = "".join(str(digit) for digit in right.digits) or "0"
    common_exponent = min(left_exponent, right_exponent)
    left_shift = left_exponent - common_exponent
    right_shift = right_exponent - common_exponent
    if (
        len(left_digits) + left_shift > _QUERY_METRIC_MAX_DIGITS
        or len(right_digits) + right_shift > _QUERY_METRIC_MAX_DIGITS
        or abs(common_exponent - 1) > _QUERY_METRIC_MAX_ABS_EXPONENT + 1
    ):
        return None
    left_coefficient = int(left_digits) * (10**left_shift)
    right_coefficient = int(right_digits) * (10**right_shift)
    if left.sign:
        left_coefficient = -left_coefficient
    if right.sign:
        right_coefficient = -right_coefficient
    score_coefficient = (left_coefficient + right_coefficient) * 5
    digits = tuple(int(char) for char in str(abs(score_coefficient)))
    return Decimal((1 if score_coefficient < 0 else 0, digits, common_exponent - 1))


def _query_generation_valid(value: Any) -> bool:
    if type(value) is int:
        return value >= 0
    return type(value) is str and bool(value) and value == value.strip()


def _query_request_id_valid(value: Any) -> bool:
    if type(value) is int:
        return value >= 0
    return type(value) is str and bool(value) and value == value.strip()


def _query_source_blockers(
    snapshot: Optional[MainContractQuerySnapshot],
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    target_products: Sequence[ProductKey],
    current_days: Mapping[str, date],
) -> Tuple[str, ...]:
    if snapshot is None:
        return ("QUERY_SNAPSHOT_UNAVAILABLE",)
    if snapshot.query_set is not None:
        return _query_set_source_blockers(
            snapshot,
            decision_at=decision_at,
            policy=policy,
            target_products=target_products,
            current_days=current_days,
        )
    blockers = []
    catalog = snapshot.catalog_source
    quote = snapshot.quote_source
    if catalog is None:
        blockers.append("CATALOG_QUERY_UNAVAILABLE")
    if quote is None:
        blockers.append("QUOTE_QUERY_UNAVAILABLE")
    sources = (("CATALOG_QUERY", catalog), ("QUOTE_QUERY", quote))
    for name, source in sources:
        if source is None:
            continue
        blockers.extend(
            _named_source_blockers(
                name,
                source_id=source.source_id,
                snapshot_id=source.snapshot_id,
                source_sha256=source.source_sha256,
                available_at=source.completed_at,
                retrieved_at=source.retrieved_at,
                decision_at=decision_at,
            )
        )
        if type(source.source_kind) is not str or not source.source_kind.strip():
            blockers.append("{}_SOURCE_KIND_UNAVAILABLE".format(name))
        elif name == "CATALOG_QUERY" and source.source_kind != "instruments":
            blockers.append("CATALOG_QUERY_SOURCE_KIND_MISMATCH")
        elif name == "QUOTE_QUERY" and source.source_kind != "depth_market_data":
            blockers.append("QUOTE_QUERY_SOURCE_KIND_MISMATCH")
        if not _query_request_id_valid(source.request_id):
            blockers.append("{}_REQUEST_ID_UNAVAILABLE".format(name))
        if not _query_generation_valid(source.connection_generation):
            blockers.append("{}_CONNECTION_GENERATION_UNAVAILABLE".format(name))
        if type(source.trading_day) is not date:
            blockers.append("{}_TRADING_DAY_UNAVAILABLE".format(name))
        for field_name, value in (
            ("started_at", source.started_at),
            ("completed_at", source.completed_at),
            ("retrieved_at", source.retrieved_at),
        ):
            if _source_timestamp(value) is None:
                blockers.append("{}_{}_INVALID".format(name, field_name.upper()))
        started = _source_timestamp(source.started_at)
        completed = _source_timestamp(source.completed_at)
        retrieved = _source_timestamp(source.retrieved_at)
        if started is not None and completed is not None:
            started_utc = started.astimezone(timezone.utc)
            completed_utc = completed.astimezone(timezone.utc)
            if started_utc > completed_utc:
                blockers.append("{}_START_AFTER_COMPLETION".format(name))
            if (decision_at.astimezone(timezone.utc) - completed_utc).total_seconds() > (
                policy.max_snapshot_age_seconds
            ):
                blockers.append("{}_SNAPSHOT_STALE".format(name))
        if completed is not None and retrieved is not None:
            if retrieved.astimezone(timezone.utc) < completed.astimezone(timezone.utc):
                blockers.append("{}_RETRIEVED_BEFORE_COMPLETION".format(name))
        if source.complete is not True:
            blockers.append("{}_QUERY_INCOMPLETE".format(name))
        if source.is_last_seen is not True:
            blockers.append("{}_QUERY_TERMINAL_NOT_SEEN".format(name))
        if type(source.record_count) is not int or source.record_count < 0:
            blockers.append("{}_RECORD_COUNT_UNAVAILABLE".format(name))
        elif snapshot is not None:
            actual_count = (
                len(snapshot.catalog_records)
                if name == "CATALOG_QUERY"
                else len(snapshot.quote_records)
            )
            if source.record_count != actual_count:
                blockers.append("{}_RECORD_COUNT_MISMATCH".format(name))

    if catalog is not None and quote is not None:
        if (
            _query_generation_valid(catalog.connection_generation)
            and _query_generation_valid(quote.connection_generation)
            and catalog.connection_generation != quote.connection_generation
        ):
            blockers.append("CATALOG_QUOTE_GENERATION_MISMATCH")
        if type(catalog.trading_day) is date and type(quote.trading_day) is date:
            if catalog.trading_day != quote.trading_day:
                blockers.append("CATALOG_QUOTE_TRADING_DAY_MISMATCH")
        timestamps = tuple(
            _source_timestamp(value)
            for value in (
                catalog.started_at,
                catalog.completed_at,
                quote.started_at,
                quote.completed_at,
            )
        )
        if all(value is not None for value in timestamps):
            utc_timestamps = tuple(value.astimezone(timezone.utc) for value in timestamps)
            span = (max(utc_timestamps) - min(utc_timestamps)).total_seconds()
            if span < 0 or span > policy.max_collection_span_seconds:
                blockers.append("QUERY_COLLECTION_SPAN_EXCEEDED")

    generations = (snapshot.session_generation_before, snapshot.session_generation_after)
    if any(not _query_generation_valid(value) for value in generations):
        blockers.append("SESSION_GENERATION_UNAVAILABLE")
    elif generations[0] != generations[1]:
        blockers.append("QUERY_SESSION_CHANGED_DURING_COLLECTION")
    for source in (catalog, quote):
        if source is not None and _query_generation_valid(source.connection_generation):
            if any(generation != source.connection_generation for generation in generations):
                blockers.append("QUERY_SESSION_GENERATION_MISMATCH")

    session_days = (snapshot.session_trading_day_before, snapshot.session_trading_day_after)
    if any(type(value) is not date for value in session_days):
        blockers.append("SESSION_TRADING_DAY_UNAVAILABLE")
    elif session_days[0] != session_days[1]:
        blockers.append("QUERY_SESSION_TRADING_DAY_CHANGED_DURING_COLLECTION")
    elif catalog is not None and type(catalog.trading_day) is date:
        if session_days[0] != catalog.trading_day:
            blockers.append("QUERY_SESSION_TRADING_DAY_MISMATCH")
    for product in target_products:
        expected_day = current_days.get(product.exchange_id)
        if expected_day is None:
            blockers.append("CURRENT_TRADING_DAY_UNAVAILABLE")
            continue
        if type(snapshot.session_trading_day_before) is date:
            if expected_day != snapshot.session_trading_day_before:
                blockers.append("CURRENT_TRADING_DAY_MISMATCH")
    return tuple(dict.fromkeys(blockers))


def _query_set_source_blockers(
    snapshot: MainContractQuerySnapshot,
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    target_products: Sequence[ProductKey],
    current_days: Mapping[str, date],
) -> Tuple[str, ...]:
    query_set = snapshot.query_set
    if query_set is None:
        return ("QUERY_SET_UNAVAILABLE",)
    blockers = []
    products = query_set.products
    excluded_products = query_set.excluded_products
    requests = query_set.requests
    if snapshot.catalog_source is not None or snapshot.quote_source is not None:
        blockers.append("QUERY_SET_LEGACY_SOURCE_PAIR_MIXED")
    if not products or len(products) > MAX_VISIBLE_FUTURE_PRODUCTS:
        blockers.append("QUERY_SET_PRODUCT_COUNT_INVALID")
    product_keys = tuple(item.product for item in products)
    excluded_keys = tuple(item.product for item in excluded_products)
    all_product_keys = product_keys + excluded_keys
    if len(products) + len(excluded_products) > MAX_VISIBLE_CTP_PRODUCTS:
        blockers.append("QUERY_SET_VISIBLE_PRODUCT_COUNT_INVALID")
    if len(set(all_product_keys)) != len(all_product_keys):
        blockers.append("QUERY_SET_PRODUCT_CANONICAL_COLLISION")
    if tuple(sorted(product_keys, key=_key_order)) != product_keys:
        blockers.append("QUERY_SET_PRODUCT_ORDER_INVALID")
    if tuple(sorted(excluded_keys, key=_key_order)) != excluded_keys:
        blockers.append("QUERY_SET_EXCLUDED_PRODUCT_ORDER_INVALID")
    if any(item.product_class != "1" for item in products):
        blockers.append("QUERY_SET_FUTURE_PRODUCT_CLASS_INVALID")
    for item in excluded_products:
        expected_asset_type = _CTP_PRODUCT_CLASS_ASSET_TYPE.get(item.product_class)
        if (
            expected_asset_type is None
            or item.product_class == "1"
            or item.asset_type != expected_asset_type
            or item.exclusion_reason != "NON_FUTURE_CTP_PRODUCT_CLASS"
        ):
            blockers.append("QUERY_SET_EXCLUDED_PRODUCT_CLASS_INVALID")
    expected_keys = tuple(sorted(target_products, key=_key_order))
    if product_keys != expected_keys:
        blockers.append("QUERY_SET_PRODUCT_POOL_MISMATCH")
    if len(requests) != len(products) + 2 or len(requests) > MAX_STAGED_QUERY_REQUESTS:
        blockers.append("QUERY_SET_REQUEST_COUNT_INVALID")
        return tuple(dict.fromkeys(blockers))

    # Cross-bind the retained catalog projection to the exact futures products
    # and their per-product instrument-query receipts. The request digests are
    # opaque summaries here; this check does not independently prove each raw
    # callback row. It relies on the trusted collector to faithfully project
    # those rows into catalog_records.
    product_by_key = {item.product: item for item in products}
    catalog_counts = {}
    for record in snapshot.catalog_records:
        expected_product = product_by_key.get(record.product)
        if expected_product is None:
            blockers.append("QUERY_SET_CATALOG_PRODUCT_OUT_OF_SCOPE")
        elif (
            record.product_class != expected_product.product_class
            or record.product_class != "1"
        ):
            blockers.append("QUERY_SET_CATALOG_PRODUCT_CLASS_MISMATCH")
        catalog_counts[record.product] = catalog_counts.get(record.product, 0) + 1
    for product, source in zip(products, requests[1:-1]):
        if (
            type(source.record_count) is int
            and source.record_count >= 0
            and catalog_counts.get(product.product, 0) != source.record_count
        ):
            blockers.append("QUERY_SET_PRODUCT_INSTRUMENT_RECORD_COUNT_MISMATCH")

    if type(query_set.source_id) is not str or not query_set.source_id.strip():
        blockers.append("QUERY_SET_SOURCE_ID_MISSING")
    if type(query_set.snapshot_id) is not str or not query_set.snapshot_id.strip():
        blockers.append("QUERY_SET_SNAPSHOT_ID_MISSING")
    if type(query_set.source_sha256) is not str or not _SOURCE_SHA256.fullmatch(
        query_set.source_sha256
    ):
        blockers.append("QUERY_SET_SOURCE_DIGEST_INVALID")
    elif (
        query_snapshot_set_digest(products, requests, excluded_products)
        != query_set.source_sha256
    ):
        blockers.append("QUERY_SET_SOURCE_DIGEST_MISMATCH")

    product_source_suffix = ".query_products_result"
    first_source_id = requests[0].source_id
    source_prefix = None
    if type(first_source_id) is str and first_source_id.endswith(product_source_suffix):
        source_prefix = first_source_id[: -len(product_source_suffix)]
        if not source_prefix or source_prefix != source_prefix.strip():
            source_prefix = None
            blockers.append("QUERY_SET_PRODUCT_SOURCE_ID_MISMATCH")
    else:
        blockers.append("QUERY_SET_PRODUCT_SOURCE_ID_MISMATCH")
    if source_prefix is not None:
        expected_query_set_source_id = "{}.staged_futures_query_set".format(source_prefix)
        if query_set.source_id != expected_query_set_source_id:
            blockers.append("QUERY_SET_SOURCE_ID_MISMATCH")
        if (
            type(query_set.source_sha256) is str
            and _SOURCE_SHA256.fullmatch(query_set.source_sha256)
            and type(snapshot.session_generation_before) is int
            and snapshot.session_generation_before > 0
            and type(snapshot.session_trading_day_before) is date
        ):
            expected_query_set_snapshot_id = "ctp-visible-futures-set:{}:{}:{}".format(
                snapshot.session_generation_before,
                snapshot.session_trading_day_before.strftime("%Y%m%d"),
                query_set.source_sha256[:16],
            )
            if query_set.snapshot_id != expected_query_set_snapshot_id:
                blockers.append("QUERY_SET_SNAPSHOT_ID_MISMATCH")

    product_request_class = None
    if requests:
        request_filters = requests[0].request_filters
        if type(request_filters) is tuple and all(
            type(pair) is tuple
            and len(pair) == 2
            and type(pair[0]) is str
            and type(pair[1]) is str
            for pair in request_filters
        ):
            product_class_filters = tuple(
                value
                for name, value in request_filters
                if name == "ProductClass"
            )
            if len(product_class_filters) == 1:
                product_request_class = product_class_filters[0]
    if product_request_class == "":
        product_query_record_count = len(products) + len(excluded_products)
    elif product_request_class == "1" and not excluded_products:
        # v1 evidence queried futures only and used that row count directly.
        product_query_record_count = len(products)
    else:
        product_query_record_count = None
        blockers.append("QUERY_SET_PRODUCT_FILTER_MODE_INVALID")

    product_filters = (
        ("ExchangeID", ""),
        ("ProductClass", product_request_class if product_request_class is not None else ""),
        ("ProductID", ""),
    )
    instrument_filters = tuple(
        (
            ("ExchangeID", item.native_exchange_id),
            ("InstrumentID", ""),
            ("ProductID", item.native_product_id),
        )
        for item in products
    )
    depth_filters = (
        ("ExchangeID", ""),
        ("InstrumentID", ""),
        ("ProductClass", "1"),
    )
    expected_filters = (product_filters,) + instrument_filters + (depth_filters,)
    expected_kinds = ("products",) + ("instruments",) * len(products) + (
        "depth_market_data",
    )
    expected_methods = ("query_products_result",) + ("query_instruments_result",) * len(
        products
    ) + ("query_depth_market_data_result",)
    request_ids = []
    span_timestamps = []
    instrument_count = 0
    for index, (source, expected_kind, expected_method, filters) in enumerate(
        zip(requests, expected_kinds, expected_methods, expected_filters)
    ):
        name = "QUERY_SET_REQUEST_{}".format(index + 1)
        blockers.extend(
            _named_source_blockers(
                name,
                source_id=source.source_id,
                snapshot_id=source.snapshot_id,
                source_sha256=source.source_sha256,
                available_at=source.completed_at,
                retrieved_at=source.retrieved_at,
                decision_at=decision_at,
            )
        )
        if source.source_kind != expected_kind:
            blockers.append("{}_SOURCE_KIND_MISMATCH".format(name))
        if source_prefix is not None and source.source_id != "{}.{}".format(
            source_prefix, expected_method
        ):
            blockers.append("{}_SOURCE_ID_MISMATCH".format(name))
        if source.request_filters != filters:
            blockers.append("{}_FILTERS_MISMATCH".format(name))
        if type(source.request_id) is not int or source.request_id <= 0:
            blockers.append("{}_REQUEST_ID_UNAVAILABLE".format(name))
        else:
            request_ids.append(source.request_id)
        if type(source.connection_generation) is not int or source.connection_generation <= 0:
            blockers.append("{}_CONNECTION_GENERATION_UNAVAILABLE".format(name))
        if type(source.trading_day) is not date:
            blockers.append("{}_TRADING_DAY_UNAVAILABLE".format(name))
        if (
            type(source.connection_generation) is int
            and source.connection_generation > 0
            and type(source.trading_day) is date
            and type(source.request_id) is int
            and source.request_id > 0
            and type(source.source_sha256) is str
            and _SOURCE_SHA256.fullmatch(source.source_sha256)
        ):
            expected_request_snapshot_id = "ctp-visible-{}:{}:{}:{}:{}".format(
                expected_kind,
                source.connection_generation,
                source.trading_day.strftime("%Y%m%d"),
                source.request_id,
                source.source_sha256[:16],
            )
            if source.snapshot_id != expected_request_snapshot_id:
                blockers.append("{}_SNAPSHOT_ID_MISMATCH".format(name))
        for field_name, value in (
            ("started_at", source.started_at),
            ("completed_at", source.completed_at),
            ("retrieved_at", source.retrieved_at),
        ):
            normalized = _source_timestamp(value)
            if normalized is None:
                blockers.append("{}_{}_INVALID".format(name, field_name.upper()))
            elif field_name != "retrieved_at":
                span_timestamps.append(normalized.astimezone(timezone.utc))
        started = _source_timestamp(source.started_at)
        completed = _source_timestamp(source.completed_at)
        retrieved = _source_timestamp(source.retrieved_at)
        if started is not None and completed is not None:
            if started.astimezone(timezone.utc) > completed.astimezone(timezone.utc):
                blockers.append("{}_START_AFTER_COMPLETION".format(name))
            age_seconds = (
                decision_at.astimezone(timezone.utc)
                - completed.astimezone(timezone.utc)
            ).total_seconds()
            if age_seconds > policy.max_snapshot_age_seconds:
                blockers.append("{}_SNAPSHOT_STALE".format(name))
        if completed is not None and retrieved is not None:
            if retrieved.astimezone(timezone.utc) < completed.astimezone(timezone.utc):
                blockers.append("{}_RETRIEVED_BEFORE_COMPLETION".format(name))
        if source.complete is not True:
            blockers.append("{}_QUERY_INCOMPLETE".format(name))
        if source.is_last_seen is not True:
            blockers.append("{}_QUERY_TERMINAL_NOT_SEEN".format(name))
        if type(source.record_count) is not int or source.record_count < 0:
            blockers.append("{}_RECORD_COUNT_UNAVAILABLE".format(name))
        expected_record_limit = (
            MAX_VISIBLE_CTP_PRODUCTS
            if index == 0
            else MAX_VISIBLE_DEPTH_ROWS
            if index == len(requests) - 1
            else MAX_PRODUCT_INSTRUMENT_ROWS - instrument_count
        )
        if type(source.record_limit) is not int or source.record_limit != expected_record_limit:
            blockers.append("{}_RECORD_LIMIT_MISMATCH".format(name))
        if source.record_limit_exceeded is not False:
            blockers.append("{}_RECORD_LIMIT_EXCEEDED".format(name))
        if (
            type(source.record_count) is int
            and type(source.record_limit) is int
            and source.record_count > source.record_limit
        ):
            blockers.append("{}_RECORD_LIMIT_EXCEEDED".format(name))
        if index == 0 and (
            product_query_record_count is None
            or source.record_count != product_query_record_count
        ):
            blockers.append("QUERY_SET_PRODUCT_RECORD_COUNT_MISMATCH")
        elif 0 < index < len(requests) - 1:
            if type(source.record_count) is int and source.record_count >= 0:
                instrument_count += source.record_count
        elif index == len(requests) - 1 and source.record_count != len(
            snapshot.quote_records
        ):
            blockers.append("QUERY_SET_DEPTH_RECORD_COUNT_MISMATCH")

    if len(request_ids) != len(set(request_ids)):
        blockers.append("QUERY_SET_REQUEST_ID_COLLISION")
    if instrument_count > MAX_PRODUCT_INSTRUMENT_ROWS:
        blockers.append("QUERY_SET_INSTRUMENT_RECORD_CAP_EXCEEDED")
    if instrument_count != len(snapshot.catalog_records):
        blockers.append("QUERY_SET_INSTRUMENT_RECORD_COUNT_MISMATCH")
    if span_timestamps:
        span = (max(span_timestamps) - min(span_timestamps)).total_seconds()
        if span < 0 or span > policy.max_collection_span_seconds:
            blockers.append("QUERY_COLLECTION_SPAN_EXCEEDED")

    generations = (snapshot.session_generation_before, snapshot.session_generation_after)
    if any(not _query_generation_valid(value) for value in generations):
        blockers.append("SESSION_GENERATION_UNAVAILABLE")
    elif generations[0] != generations[1]:
        blockers.append("QUERY_SESSION_CHANGED_DURING_COLLECTION")
    session_days = (snapshot.session_trading_day_before, snapshot.session_trading_day_after)
    if any(type(value) is not date for value in session_days):
        blockers.append("SESSION_TRADING_DAY_UNAVAILABLE")
    elif session_days[0] != session_days[1]:
        blockers.append("QUERY_SESSION_TRADING_DAY_CHANGED_DURING_COLLECTION")

    for source in requests:
        if _query_generation_valid(source.connection_generation) and all(
            _query_generation_valid(generation) for generation in generations
        ):
            if any(generation != source.connection_generation for generation in generations):
                blockers.append("QUERY_SESSION_GENERATION_MISMATCH")
        if type(source.trading_day) is date and all(
            type(day) is date for day in session_days
        ):
            if any(day != source.trading_day for day in session_days):
                blockers.append("QUERY_SESSION_TRADING_DAY_MISMATCH")
        if type(source.trading_day) is date:
            for product in product_keys:
                expected_day = current_days.get(product.exchange_id)
                if expected_day is None:
                    blockers.append("CURRENT_TRADING_DAY_UNAVAILABLE")
                elif expected_day != source.trading_day:
                    blockers.append("CURRENT_TRADING_DAY_MISMATCH")

    return tuple(dict.fromkeys(blockers))


def _safe_query_value(value: Any) -> dict[str, Any]:
    number = _number_as_decimal(value)
    if number is not None:
        parts = number.as_tuple()
        if (
            isinstance(parts.exponent, int)
            and abs(parts.exponent) <= _QUERY_METRIC_MAX_ABS_EXPONENT
            and len(parts.digits) <= _QUERY_METRIC_MAX_DIGITS
        ):
            return {"value": _decimal_text(number), "valid_nonnegative_finite": True}
        return {"value": "<decimal-out-of-supported-range>", "valid_nonnegative_finite": False}
    if isinstance(value, Decimal):
        parts = value.as_tuple()
        if value.is_finite() and len(parts.digits) > 128:
            raw = "<decimal-out-of-supported-range>"
        else:
            raw = str(value)
    elif type(value) is float and not Decimal(str(value)).is_finite():
        raw = repr(value)
    elif type(value) is int and value.bit_length() > _QUERY_METRIC_MAX_DIGITS * 4:
        raw = "<integer-out-of-supported-range>"
    elif value is None or type(value) in (bool, int, float, str):
        raw = value
    else:
        raw = "<{}>".format(type(value).__name__)
    if isinstance(raw, str) and len(raw) > 128:
        raw = raw[:128]
    return {"value": raw, "valid_nonnegative_finite": False}


def _query_source_dict(source: Optional[QuerySnapshotSourceEvidence]) -> Optional[dict[str, Any]]:
    if source is None:
        return None

    def time_text(value: Any) -> Optional[str]:
        normalized = _source_timestamp(value)
        return _utc_text(normalized) if normalized is not None else None

    def scalar(value: Any) -> Any:
        if value is None or type(value) in (str, int, bool):
            return value
        return "<{}>".format(type(value).__name__)

    filters = None
    if type(source.request_filters) is tuple and all(
        type(pair) is tuple
        and len(pair) == 2
        and type(pair[0]) is str
        and type(pair[1]) is str
        for pair in source.request_filters
    ):
        filters = [[name, value] for name, value in source.request_filters]

    projection = {
        "source_id": _source_text(source.source_id),
        "source_kind": _source_text(source.source_kind),
        "snapshot_id": _source_text(source.snapshot_id),
        "sha256": _source_digest(source.source_sha256),
        "request_id": scalar(source.request_id),
        "connection_generation": scalar(source.connection_generation),
        "trading_day": source.trading_day.isoformat() if type(source.trading_day) is date else None,
        "started_at": time_text(source.started_at),
        "completed_at": time_text(source.completed_at),
        "available_at": time_text(source.completed_at),
        "retrieved_at": time_text(source.retrieved_at),
        "complete": source.complete if type(source.complete) is bool else None,
        "is_last_seen": source.is_last_seen if type(source.is_last_seen) is bool else None,
        "record_count": source.record_count
        if type(source.record_count) is int and source.record_count >= 0
        else None,
    }
    if source.request_filters is not None or source.record_limit is not None or (
        source.record_limit_exceeded is not None
    ):
        projection.update(
            {
                "request_filters": filters,
                "record_limit": source.record_limit
                if type(source.record_limit) is int and source.record_limit > 0
                else None,
                "record_limit_exceeded": source.record_limit_exceeded
                if type(source.record_limit_exceeded) is bool
                else None,
            }
        )
    return projection


def _query_snapshot_dict(
    snapshot: Optional[MainContractQuerySnapshot],
) -> Optional[dict[str, Any]]:
    if snapshot is None:
        return None
    catalog = [
        {
            "product": _product_dict(row.product),
            "instrument_id": row.instrument_id,
            "asset_type": row.asset_type,
            "is_trading": row.is_trading,
            "expiry_date": row.expiry_date.isoformat() if row.expiry_date is not None else None,
            "product_class": row.product_class,
        }
        for row in snapshot.catalog_records
    ]
    quotes = [
        {
            "exchange_id": row.exchange_id,
            "instrument_id": row.instrument_id,
            "trading_day": row.trading_day.isoformat() if type(row.trading_day) is date else None,
            "open_interest": _safe_query_value(row.open_interest),
            "volume": _safe_query_value(row.volume),
            "action_day": row.action_day,
            "update_time": row.update_time,
            "update_millisec": row.update_millisec,
        }
        for row in snapshot.quote_records
    ]

    query_set = None
    if snapshot.query_set is not None:
        query_set = {
            "source_id": _source_text(snapshot.query_set.source_id),
            "snapshot_id": _source_text(snapshot.query_set.snapshot_id),
            "sha256": _source_digest(snapshot.query_set.source_sha256),
            "digest_schema": "v2" if snapshot.query_set.excluded_products else "v1",
            "products": [
                {
                    "product": _product_dict(item.product),
                    "native_exchange_id": item.native_exchange_id,
                    "native_product_id": item.native_product_id,
                    "product_class": item.product_class,
                }
                for item in snapshot.query_set.products
            ],
            "excluded_products": [
                {
                    "product": _product_dict(item.product),
                    "native_exchange_id": item.native_exchange_id,
                    "native_product_id": item.native_product_id,
                    "product_class": item.product_class,
                    "asset_type": item.asset_type,
                    "exclusion_reason": item.exclusion_reason,
                }
                for item in snapshot.query_set.excluded_products
            ],
            "requests": [
                _query_source_dict(source) for source in snapshot.query_set.requests
            ],
        }

    def scalar(value: Any) -> Any:
        if value is None or type(value) in (str, int, bool):
            return value
        return "<{}>".format(type(value).__name__)

    projection = {
        "kind": "CTP_CURRENT_DAY_QUERY_SNAPSHOT_NOT_FINALIZED_EOD",
        "catalog_source": _query_source_dict(snapshot.catalog_source),
        "quote_source": _query_source_dict(snapshot.quote_source),
        "session": {
            "trading_day_before": snapshot.session_trading_day_before.isoformat()
            if type(snapshot.session_trading_day_before) is date
            else None,
            "trading_day_after": snapshot.session_trading_day_after.isoformat()
            if type(snapshot.session_trading_day_after) is date
            else None,
            "generation_before": scalar(snapshot.session_generation_before),
            "generation_after": scalar(snapshot.session_generation_after),
        },
        "catalog_records": catalog,
        "quote_records": quotes,
    }
    if query_set is not None:
        projection["query_set"] = query_set
    return projection


def _calendar_for(
    product: ProductKey,
    calendars: Mapping[str, ExchangeTradingCalendar],
    decision_at: datetime,
) -> Tuple[Optional[ExchangeTradingCalendar], Tuple[str, ...]]:
    calendar = calendars.get(product.exchange_id)
    if calendar is None:
        return None, ("EXCHANGE_CALENDAR_UNAVAILABLE",)
    if not calendar.complete:
        return calendar, ("EXCHANGE_CALENDAR_INCOMPLETE",)
    if calendar.available_at.astimezone(timezone.utc) > decision_at.astimezone(timezone.utc):
        return None, ("CALENDAR_NOT_AVAILABLE_AT_DECISION",)
    if calendar.retrieved_at.astimezone(timezone.utc) > decision_at.astimezone(timezone.utc):
        return None, ("CALENDAR_RETRIEVED_AFTER_DECISION",)
    return calendar, ()


def _candidate_assessment(
    record: FuturesContractRecord,
    *,
    current_trading_day: Optional[date],
    calendar: Optional[ExchangeTradingCalendar],
    policy: MainContractPolicy,
    suppress_source_values: bool,
    exact_metric_limit: bool = False,
) -> Tuple[ContractAssessment, bool]:
    """Return the assessment and whether it is rank-eligible."""

    if suppress_source_values:
        return (
            ContractAssessment(
                product=record.product,
                instrument_id=record.instrument_id,
                status="BLOCKED",
                reason="SOURCE_PROVENANCE_INVALID",
                expiry_date=None,
                trading_days_to_expiry=None,
                open_interest=None,
                volume=None,
                rank=None,
            ),
            False,
        )

    asset_type = record.asset_type.casefold() if record.asset_type is not None else None
    if asset_type in _KNOWN_NON_FUTURES:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "EXCLUDED",
                "NOT_ORDINARY_FUTURE",
                record.expiry_date,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if asset_type != "future":
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "BLOCKED",
                "ASSET_TYPE_UNKNOWN",
                record.expiry_date,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if record.is_trading is False:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "EXCLUDED",
                "NOT_TRADING",
                record.expiry_date,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if record.is_trading is not True:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "BLOCKED",
                "TRADING_STATUS_UNKNOWN",
                record.expiry_date,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if not _is_actual_month_contract(record.instrument_id, record.product.product_id):
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "EXCLUDED",
                "NOT_ACTUAL_MONTH_CONTRACT",
                record.expiry_date,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if record.expiry_date is None:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "BLOCKED",
                "EXPIRY_UNAVAILABLE",
                None,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if current_trading_day is None or calendar is None:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "BLOCKED",
                "EXPIRY_CALENDAR_UNAVAILABLE",
                record.expiry_date,
                None,
                None,
                None,
                None,
            ),
            False,
        )
    if record.expiry_date <= current_trading_day:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "EXCLUDED",
                "EXPIRED_OR_EXPIRY_DAY",
                record.expiry_date,
                0,
                None,
                None,
                None,
                0,
                True,
            ),
            False,
        )
    if record.expiry_date > calendar.coverage_through:
        lower_bound = sum(
            current_trading_day < day <= calendar.coverage_through for day in calendar.trading_days
        )
        remaining = None
        distance_exact = False
        if lower_bound < policy.minimum_trading_days_to_expiry:
            return (
                ContractAssessment(
                    record.product,
                    record.instrument_id,
                    "BLOCKED",
                    "EXPIRY_SAFETY_UNPROVEN",
                    record.expiry_date,
                    None,
                    None,
                    None,
                    None,
                    lower_bound,
                    False,
                ),
                False,
            )
    else:
        try:
            remaining = calendar.trading_days_to_expiry(current_trading_day, record.expiry_date)
        except TradingCalendarContractError as exc:
            return (
                ContractAssessment(
                    record.product,
                    record.instrument_id,
                    "BLOCKED",
                    exc.code,
                    record.expiry_date,
                    None,
                    None,
                    None,
                    None,
                ),
                False,
            )
        lower_bound = remaining
        distance_exact = True
    if remaining is not None and remaining < policy.minimum_trading_days_to_expiry:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "EXCLUDED",
                "EXPIRY_TOO_NEAR",
                record.expiry_date,
                remaining,
                None,
                None,
                None,
                lower_bound,
                distance_exact,
            ),
            False,
        )
    open_interest = _number_as_decimal(record.open_interest)
    volume = _number_as_decimal(record.volume)
    if open_interest is None or volume is None:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "BLOCKED",
                "RANKING_VALUE_MISSING_OR_INVALID",
                record.expiry_date,
                remaining,
                None,
                None,
                None,
                lower_bound,
                distance_exact,
            ),
            False,
        )
    if exact_metric_limit and _exact_equal_weight_score(open_interest, volume) is None:
        return (
            ContractAssessment(
                record.product,
                record.instrument_id,
                "BLOCKED",
                "RANKING_VALUE_RANGE_UNSUPPORTED",
                record.expiry_date,
                remaining,
                None,
                None,
                None,
                lower_bound,
                distance_exact,
            ),
            False,
        )
    return (
        ContractAssessment(
            record.product,
            record.instrument_id,
            "ELIGIBLE",
            None,
            record.expiry_date,
            remaining,
            _decimal_text(open_interest),
            _decimal_text(volume),
            None,
            lower_bound,
            distance_exact,
        ),
        True,
    )


def _catalog_requires_ranking_quote(
    record: FuturesContractCatalogRecord,
    *,
    current_trading_day: Optional[date],
    calendar: Optional[ExchangeTradingCalendar],
    policy: MainContractPolicy,
) -> bool:
    catalog_asset_type, _classification_issue = _query_catalog_classification(record)
    if not (
        catalog_asset_type == "future"
        and record.is_trading is True
        and _is_actual_month_contract(record.instrument_id, record.product.product_id)
        and record.expiry_date is not None
        and current_trading_day is not None
        and calendar is not None
    ):
        return False
    if record.expiry_date <= current_trading_day:
        return False
    if record.expiry_date > calendar.coverage_through:
        return (
            sum(
                current_trading_day < day <= calendar.coverage_through
                for day in calendar.trading_days
            )
            >= policy.minimum_trading_days_to_expiry
        )
    try:
        remaining = calendar.trading_days_to_expiry(current_trading_day, record.expiry_date)
    except TradingCalendarContractError:
        return False
    return remaining >= policy.minimum_trading_days_to_expiry


def _query_catalog_classification(
    record: FuturesContractCatalogRecord,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve CTP ProductClass and reject missing or contradictory metadata."""

    product_class = record.product_class
    asset_type = _CTP_PRODUCT_CLASS_ASSET_TYPE.get(product_class)
    if asset_type is None:
        return None, "CATALOG_PRODUCT_CLASS_UNKNOWN"

    source_type = record.asset_type
    if source_type is None or source_type.strip().casefold() in ("", "unknown"):
        return asset_type, None
    normalized = source_type.strip().casefold()
    normalized = _ASSET_TYPE_ALIASES.get(normalized, normalized)
    if normalized != asset_type:
        return asset_type, "CATALOG_PRODUCT_CLASS_ASSET_TYPE_MISMATCH"
    return asset_type, None


def _query_contract_assessment(
    catalog: FuturesContractCatalogRecord,
    quote: Optional[CurrentDayQuoteRecord],
    *,
    current_trading_day: Optional[date],
    calendar: Optional[ExchangeTradingCalendar],
    policy: MainContractPolicy,
    quote_missing: bool,
) -> Tuple[ContractAssessment, bool, Optional[Decimal]]:
    catalog_asset_type, classification_issue = _query_catalog_classification(catalog)
    if classification_issue is not None:
        return (
            ContractAssessment(
                product=catalog.product,
                instrument_id=catalog.instrument_id,
                status="BLOCKED",
                reason=classification_issue,
                expiry_date=catalog.expiry_date,
                trading_days_to_expiry=None,
                open_interest=None,
                volume=None,
                rank=None,
                asset_type=catalog.asset_type,
                is_trading=catalog.is_trading,
                product_class=catalog.product_class,
            ),
            False,
            None,
        )
    ranking = FuturesContractRecord(
        product=catalog.product,
        instrument_id=catalog.instrument_id,
        asset_type=catalog_asset_type,
        is_trading=catalog.is_trading,
        expiry_date=catalog.expiry_date,
        open_interest=quote.open_interest if quote is not None else None,
        volume=quote.volume if quote is not None else None,
    )
    assessment, eligible = _candidate_assessment(
        ranking,
        current_trading_day=current_trading_day,
        calendar=calendar,
        policy=policy,
        suppress_source_values=False,
        exact_metric_limit=True,
    )
    score = None
    if quote_missing and assessment.status not in ("EXCLUDED", "OUT_OF_SCOPE"):
        assessment = replace(
            assessment,
            status="BLOCKED",
            reason="QUOTE_ROW_MISSING_FOR_CANDIDATE",
            open_interest=None,
            volume=None,
            rank=None,
        )
        eligible = False
    elif eligible:
        open_interest = _number_as_decimal(quote.open_interest if quote is not None else None)
        volume = _number_as_decimal(quote.volume if quote is not None else None)
        if open_interest is None or volume is None:
            assessment = replace(
                assessment,
                status="BLOCKED",
                reason="RANKING_VALUE_MISSING_OR_INVALID",
                rank=None,
            )
            eligible = False
        else:
            score = _exact_equal_weight_score(open_interest, volume)
            if score is None:
                assessment = replace(
                    assessment,
                    status="BLOCKED",
                    reason="RANKING_VALUE_RANGE_UNSUPPORTED",
                    rank=None,
                )
                eligible = False
    assessment = replace(
        assessment,
        ranking_score=_decimal_text(score),
        asset_type=catalog.asset_type,
        is_trading=catalog.is_trading,
        product_class=catalog.product_class,
        quote_trading_day=quote.trading_day if quote is not None else None,
        action_day=quote.action_day if quote is not None else None,
        update_time=quote.update_time if quote is not None else None,
        update_millisec=quote.update_millisec if quote is not None else None,
    )
    return assessment, eligible, score


def _no_listed_contracts_products(
    snapshot: Optional[MainContractQuerySnapshot],
    *,
    target_ids: Sequence[Tuple[str, str]],
    catalog_by_product: Mapping[Tuple[str, str], Sequence[Any]],
) -> frozenset:
    """Return target products whose own complete instrument query returned no rows.

    AC51-18 permits a listed but non-trading product to leave the rankable pool
    only when the catalog holds no row for it at all *and* its per-product
    instrument query was complete with exactly zero records.  Anything weaker
    (an incomplete query, an unusable count, a catalog row) keeps the existing
    catalog-coverage/pool blockers unchanged.  The query set itself is never
    rewritten; this only narrows the selector's rankable target set.
    """

    if snapshot is None or snapshot.query_set is None:
        return frozenset()
    query_set = snapshot.query_set
    products = query_set.products
    requests = query_set.requests
    if len(requests) != len(products) + 2:
        return frozenset()
    target_set = set(target_ids)
    excluded = set()
    for product_evidence, request in zip(products, requests[1:-1]):
        key = _key_order(product_evidence.product)
        if key not in target_set or key in catalog_by_product:
            continue
        if request.complete is not True:
            continue
        if type(request.record_count) is not int or request.record_count != 0:
            continue
        excluded.add(key)
    return frozenset(excluded)


def _select_query_snapshot(
    snapshot: Optional[MainContractQuerySnapshot],
    expected_products: Sequence[ProductKey],
    current_trading_days: Sequence[ExchangeTradingDay],
    calendars: Sequence[ExchangeTradingCalendar],
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
) -> MainContractManifest:
    """Select from complete, same-session CTP instrument and depth queries."""

    _aware_datetime(decision_at, "decision_at")
    targets = tuple(expected_products)
    if any(not isinstance(item, ProductKey) for item in targets):
        raise ValueError("expected_products must contain ProductKey records")
    targets = tuple(sorted(targets, key=_key_order))
    if len({_key_order(item) for item in targets}) != len(targets):
        raise ValueError("expected_products contains duplicate product keys")
    day_rows = tuple(current_trading_days)
    if any(not isinstance(item, ExchangeTradingDay) for item in day_rows):
        raise ValueError("current_trading_days must contain ExchangeTradingDay records")
    day_index = {}
    for item in day_rows:
        if item.exchange_id in day_index:
            raise ValueError("current_trading_days contains duplicate exchanges")
        day_index[item.exchange_id] = item.trading_day
    calendar_rows = tuple(calendars)
    if any(not isinstance(item, ExchangeTradingCalendar) for item in calendar_rows):
        raise ValueError("calendars must contain ExchangeTradingCalendar records")
    calendar_index = {}
    for item in calendar_rows:
        if item.exchange_id in calendar_index:
            raise ValueError("calendars contains duplicate exchanges")
        calendar_index[item.exchange_id] = item

    global_blockers = list(
        _query_source_blockers(
            snapshot,
            decision_at=decision_at,
            policy=policy,
            target_products=targets,
            current_days=day_index,
        )
    )
    target_by_id = {_key_order(item): item for item in targets}
    catalog_by_key = {}
    catalog_by_product = {}
    expected_quotes_by_product = {}
    quote_rows_by_key = {}
    no_listed_ids = frozenset()
    query_quote_trading_day = None
    if snapshot is not None:
        if snapshot.quote_source is not None:
            query_quote_trading_day = snapshot.quote_source.trading_day
        elif snapshot.query_set is not None and snapshot.query_set.requests:
            query_quote_trading_day = snapshot.query_set.requests[-1].trading_day

    if snapshot is not None:
        for record in snapshot.catalog_records:
            join_key = (record.product.exchange_id, record.instrument_id)
            catalog_by_key.setdefault(join_key, []).append(record)
            catalog_by_product.setdefault(_key_order(record.product), []).append(record)
            exchange_calendar, _calendar_issue = _calendar_for(
                record.product, calendar_index, decision_at
            )
            if _catalog_requires_ranking_quote(
                record,
                current_trading_day=day_index.get(record.product.exchange_id),
                calendar=exchange_calendar,
                policy=policy,
            ):
                expected_quotes_by_product.setdefault(_key_order(record.product), []).append(
                    record.instrument_id
                )
        for join_key, rows in catalog_by_key.items():
            if len(rows) > 1:
                global_blockers.append("DUPLICATE_CATALOG_INSTRUMENT_ID")
        for quote in snapshot.quote_records:
            join_key = (quote.exchange_id.upper(), quote.instrument_id)
            matches = catalog_by_key.get(join_key)
            if not matches:
                global_blockers.append("QUOTE_ID_NOT_IN_CATALOG")
                continue
            quote_rows_by_key.setdefault(join_key, []).append(quote)
            if len(matches) != 1:
                continue
            product = matches[0].product
            expected_day = day_index.get(product.exchange_id)
            if type(quote.trading_day) is not date:
                global_blockers.append("QUOTE_TRADING_DAY_UNAVAILABLE")
            elif expected_day is not None and quote.trading_day != expected_day:
                global_blockers.append("QUOTE_TRADING_DAY_MISMATCH")
            if (
                type(query_quote_trading_day) is date
                and type(quote.trading_day) is date
                and quote.trading_day != query_quote_trading_day
            ):
                global_blockers.append("QUOTE_QUERY_ROW_CROSS_DAY")
        if any(len(rows) > 1 for rows in quote_rows_by_key.values()):
            global_blockers.append("DUPLICATE_QUOTE_ROW")

        # A listed product with no contracts at all is excluded only when its
        # own complete instrument query proves zero records (AC51-18).
        no_listed_ids = _no_listed_contracts_products(
            snapshot,
            target_ids=tuple(target_by_id),
            catalog_by_product=catalog_by_product,
        )
        rankable_target_ids = set(target_by_id).difference(no_listed_ids)
        catalog_future_products = set()
        for record in snapshot.catalog_records:
            catalog_asset_type, classification_issue = _query_catalog_classification(record)
            if classification_issue is not None:
                global_blockers.append(classification_issue)
            if catalog_asset_type == "future":
                catalog_future_products.add(_key_order(record.product))
        if catalog_future_products != rankable_target_ids:
            global_blockers.append("CATALOG_PRODUCT_POOL_MISMATCH")
        if not catalog_future_products:
            global_blockers.append("CATALOG_FUTURE_UNIVERSE_EMPTY")

        for product_id, expected_ids in expected_quotes_by_product.items():
            expected_keys = {(product_id[0], instrument_id) for instrument_id in expected_ids}
            observed_keys = expected_keys.intersection(quote_rows_by_key)
            if expected_keys != observed_keys:
                global_blockers.append("QUOTE_ROW_MISSING_FOR_CANDIDATE")

    global_blockers = list(dict.fromkeys(global_blockers))
    selections = []
    assessments = []
    query_coverage = []
    day_references = {}
    used_calendars = {}

    for product_id in sorted(set(target_by_id).union(catalog_by_product)):
        product = target_by_id.get(product_id, ProductKey(*product_id))
        records = catalog_by_product.get(product_id, ())
        in_target = product_id in target_by_id
        if product_id in no_listed_ids:
            # Out of the rankable pool, but kept visible with explicit evidence.
            selections.append(
                ProductSelection(
                    product=product,
                    in_target_pool=False,
                    status="EXCLUDED",
                    expected_prior_trading_day=None,
                    ranking_trading_day=day_index.get(product.exchange_id),
                    selected_instrument_id=None,
                    ranked_instrument_ids=(),
                    excluded_instrument_ids=(),
                    blockers=(),
                    exclusion_reason=EXCLUSION_REASON_NO_LISTED_CONTRACTS,
                )
            )
            query_coverage.append(
                MainContractQueryCoverage(
                    product=product,
                    catalog_instrument_ids=(),
                    expected_quote_instrument_ids=(),
                    observed_quote_instrument_ids=(),
                )
            )
            continue
        if not in_target:
            for record in records:
                catalog_asset_type, classification_issue = _query_catalog_classification(record)
                if classification_issue is not None:
                    status, reason = "BLOCKED", classification_issue
                elif catalog_asset_type != "future":
                    status, reason = "EXCLUDED", "NOT_ORDINARY_FUTURE"
                elif record.is_trading is False:
                    status, reason = "EXCLUDED", "NOT_TRADING"
                elif record.is_trading is not True:
                    status, reason = "BLOCKED", "TRADING_STATUS_UNKNOWN"
                else:
                    status, reason = "OUT_OF_SCOPE", "OUTSIDE_TARGET_POOL"
                assessments.append(
                    ContractAssessment(
                        product=record.product,
                        instrument_id=record.instrument_id,
                        status=status,
                        reason=reason,
                        expiry_date=record.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=record.asset_type,
                        is_trading=record.is_trading,
                        product_class=record.product_class,
                    )
                )
            continue

        product_blockers = list(global_blockers)
        current_day = day_index.get(product.exchange_id)
        if current_day is None:
            product_blockers.append("CURRENT_TRADING_DAY_UNAVAILABLE")
        if current_day is not None:
            day_references[product.exchange_id] = TradingDayReference(
                product.exchange_id, current_day, None
            )
        calendar, calendar_blockers = _calendar_for(product, calendar_index, decision_at)
        product_blockers.extend(calendar_blockers)
        if calendar is not None and not calendar_blockers:
            used_calendars[product.exchange_id] = _calendar_evidence(calendar)
        if not records:
            product_blockers.append("PRODUCT_CATALOG_COVERAGE_UNAVAILABLE")

        catalog_ids = tuple(record.instrument_id for record in records)
        expected_quote_ids = tuple(sorted(expected_quotes_by_product.get(product_id, ())))
        expected_quote_set = set(expected_quote_ids)
        observed_quote_ids = (
            tuple(
                quote.instrument_id
                for quote in snapshot.quote_records
                if snapshot is not None
                and (quote.exchange_id.upper(), quote.instrument_id) in quote_rows_by_key
                and (quote.exchange_id.upper(), quote.instrument_id)[0] == product.exchange_id
                and quote.instrument_id in expected_quote_set
            )
            if snapshot is not None
            else ()
        )
        query_coverage.append(
            MainContractQueryCoverage(
                product=product,
                catalog_instrument_ids=tuple(sorted(catalog_ids)),
                expected_quote_instrument_ids=expected_quote_ids,
                observed_quote_instrument_ids=tuple(sorted(observed_quote_ids)),
            )
        )

        group_assessments = []
        eligible = []
        for record in records:
            join_key = (record.product.exchange_id, record.instrument_id)
            matching_quotes = quote_rows_by_key.get(join_key, ())
            quote = matching_quotes[0] if matching_quotes else None
            quote_missing = (
                _catalog_requires_ranking_quote(
                    record,
                    current_trading_day=current_day,
                    calendar=calendar if not calendar_blockers else None,
                    policy=policy,
                )
                and quote is None
            )
            assessment, is_eligible, score = _query_contract_assessment(
                record,
                quote,
                current_trading_day=current_day,
                calendar=calendar if not calendar_blockers else None,
                policy=policy,
                quote_missing=quote_missing,
            )
            if assessment.status == "BLOCKED" and assessment.reason:
                product_blockers.append(assessment.reason)
            if is_eligible:
                eligible.append((record, assessment, score))
            group_assessments.append(assessment)

        product_blockers = list(dict.fromkeys(product_blockers))
        if not product_blockers and not eligible:
            product_blockers.append("NO_ELIGIBLE_MONTH_FUTURES")

        if product_blockers:
            assessments.extend(
                replace(item, status="BLOCKED", reason=product_blockers[0], rank=None)
                if item.status == "ELIGIBLE"
                else item
                for item in group_assessments
            )
            selections.append(
                ProductSelection(
                    product=product,
                    in_target_pool=True,
                    status="BLOCKED",
                    expected_prior_trading_day=None,
                    ranking_trading_day=current_day,
                    selected_instrument_id=None,
                    ranked_instrument_ids=(),
                    excluded_instrument_ids=tuple(
                        item.instrument_id
                        for item in group_assessments
                        if item.status == "EXCLUDED"
                    ),
                    blockers=tuple(product_blockers),
                )
            )
            continue

        ranked = sorted(
            eligible,
            key=lambda item: (
                item[2].copy_negate(),
                Decimal(item[1].open_interest).copy_negate(),
                Decimal(item[1].volume).copy_negate(),
                item[1].expiry_date,
                item[0].instrument_id,
            ),
        )
        rank_by_id = {item[0].instrument_id: index for index, item in enumerate(ranked, 1)}
        rank_score_by_id = {item[0].instrument_id: _decimal_text(item[2]) for item in ranked}
        assessments.extend(
            replace(
                assessment,
                status="RANKED",
                reason=None,
                rank=rank_by_id[assessment.instrument_id],
                ranking_score=rank_score_by_id[assessment.instrument_id],
            )
            if assessment.instrument_id in rank_by_id
            else assessment
            for assessment in group_assessments
        )
        selections.append(
            ProductSelection(
                product=product,
                in_target_pool=True,
                status="READY",
                expected_prior_trading_day=None,
                ranking_trading_day=current_day,
                selected_instrument_id=ranked[0][0].instrument_id,
                ranked_instrument_ids=tuple(item[0].instrument_id for item in ranked),
                excluded_instrument_ids=tuple(
                    item.instrument_id for item in group_assessments if item.status == "EXCLUDED"
                ),
                blockers=(),
                selected_score=_decimal_text(ranked[0][2]),
            )
        )

    narrowed_targets = tuple(
        item for item in targets if _key_order(item) not in no_listed_ids
    )
    target_selections = [item for item in selections if item.in_target_pool]
    manifest_blockers = list(global_blockers)
    manifest_blockers.extend(reason for item in target_selections for reason in item.blockers)
    if not narrowed_targets:
        manifest_blockers.append("TARGET_PRODUCT_POOL_EMPTY")
    manifest_blockers = list(dict.fromkeys(manifest_blockers))
    status = (
        "READY"
        if narrowed_targets and all(item.status == "READY" for item in target_selections)
        else "BLOCKED"
    )
    quote_source = snapshot.quote_source if snapshot is not None else None
    catalog_source = snapshot.catalog_source if snapshot is not None else None
    return MainContractManifest(
        status=status,
        decision_at=decision_at,
        policy=policy,
        target_products=narrowed_targets,
        source_id=_source_text(quote_source.source_id) if quote_source is not None else None,
        source_snapshot_id=_source_text(quote_source.snapshot_id)
        if quote_source is not None
        else None,
        source_sha256=_source_digest(quote_source.source_sha256)
        if quote_source is not None
        else None,
        source_available_at=_source_timestamp(quote_source.completed_at)
        if quote_source is not None
        else None,
        source_retrieved_at=_source_timestamp(quote_source.retrieved_at)
        if quote_source is not None
        else None,
        catalog_source_id=_source_text(catalog_source.source_id)
        if catalog_source is not None
        else None,
        catalog_snapshot_id=_source_text(catalog_source.snapshot_id)
        if catalog_source is not None
        else None,
        catalog_sha256=_source_digest(catalog_source.source_sha256)
        if catalog_source is not None
        else None,
        catalog_available_at=_source_timestamp(catalog_source.completed_at)
        if catalog_source is not None
        else None,
        catalog_retrieved_at=_source_timestamp(catalog_source.retrieved_at)
        if catalog_source is not None
        else None,
        trading_days=tuple(day_references[key] for key in sorted(day_references)),
        calendars=tuple(used_calendars[key] for key in sorted(used_calendars)),
        coverage=(),
        products=tuple(sorted(selections, key=lambda item: _key_order(item.product))),
        candidates=tuple(
            sorted(
                assessments,
                key=lambda item: (
                    _key_order(item.product),
                    item.rank if item.rank is not None else 2**31,
                    item.instrument_id,
                ),
            )
        ),
        blockers=tuple(manifest_blockers),
        query_snapshot=snapshot,
        query_coverage=tuple(sorted(query_coverage, key=lambda item: _key_order(item.product))),
    )


def select_main_contracts(
    snapshot: Optional[Union[MainContractRankingSnapshot, MainContractQuerySnapshot]],
    expected_products: Sequence[ProductKey],
    current_trading_days: Sequence[ExchangeTradingDay],
    calendars: Sequence[ExchangeTradingCalendar],
    *,
    decision_at: datetime,
    policy: MainContractPolicy = DEFAULT_MAIN_CONTRACT_POLICY,
) -> MainContractManifest:
    """Select one actual monthly future per target product, fail-closed.

    The input pool is product identities only, never contract IDs.  The
    legacy policy requires finalized latest prior-day rankings.  The explicit
    CTP query policy requires complete, same-session catalog and current-day
    depth results; it ranks by exact equal-weight OI and volume and does not
    label those values as finalized EOD.  Both require a proved exchange
    calendar and keep the complete manifest non-executable if any target is
    blocked.
    """

    _aware_datetime(decision_at, "decision_at")
    if not isinstance(policy, MainContractPolicy):
        raise ValueError("policy must be a MainContractPolicy")
    if policy.ranking_mode == RANKING_MODE_CTP_QUERY_SNAPSHOT:
        if snapshot is not None and not isinstance(snapshot, MainContractQuerySnapshot):
            raise ValueError("query-snapshot policy requires MainContractQuerySnapshot")
        return _select_query_snapshot(
            snapshot,
            expected_products,
            current_trading_days,
            calendars,
            decision_at=decision_at,
            policy=policy,
        )
    if isinstance(snapshot, MainContractQuerySnapshot):
        raise ValueError("CTP query snapshot requires the explicit query-snapshot policy")
    if snapshot is not None and not isinstance(snapshot, MainContractRankingSnapshot):
        raise ValueError("snapshot must be MainContractRankingSnapshot, query snapshot, or None")
    targets = tuple(expected_products)
    if any(not isinstance(item, ProductKey) for item in targets):
        raise ValueError("expected_products must contain ProductKey records")
    targets = tuple(sorted(targets, key=_key_order))
    target_ids = [_key_order(item) for item in targets]
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("expected_products contains duplicate product keys")

    day_rows = tuple(current_trading_days)
    if any(not isinstance(item, ExchangeTradingDay) for item in day_rows):
        raise ValueError("current_trading_days must contain ExchangeTradingDay records")
    day_index = {}
    for item in day_rows:
        key = item.exchange_id
        if key in day_index:
            raise ValueError("current_trading_days contains duplicate exchanges")
        day_index[key] = item.trading_day

    calendar_rows = tuple(calendars)
    if any(not isinstance(item, ExchangeTradingCalendar) for item in calendar_rows):
        raise ValueError("calendars must contain ExchangeTradingCalendar records")
    calendar_index = {}
    for item in calendar_rows:
        if item.exchange_id in calendar_index:
            raise ValueError("calendars contains duplicate exchanges")
        calendar_index[item.exchange_id] = item

    source_blockers = _source_blockers(snapshot, decision_at)
    suppress_source_values = bool(source_blockers)
    target_by_id = {_key_order(item): item for item in targets}
    coverage_by_id = {}
    records_by_id = {}
    if snapshot is not None:
        for coverage in snapshot.coverage:
            key = _key_order(coverage.product)
            coverage_by_id.setdefault(key, []).append(coverage)
        for record in snapshot.candidates:
            records_by_id.setdefault(_key_order(record.product), []).append(record)

    all_product_ids = set(target_by_id)
    all_product_ids.update(coverage_by_id)
    all_product_ids.update(records_by_id)
    selections = []
    assessments = []
    day_references = {}
    used_calendars = {}

    for key_id in sorted(all_product_ids):
        key = target_by_id.get(key_id)
        if key is None:
            key = ProductKey(*key_id)
            out_of_scope_records = records_by_id.get(key_id, ())
            for record in out_of_scope_records:
                assessments.append(
                    ContractAssessment(
                        record.product,
                        record.instrument_id,
                        "OUT_OF_SCOPE",
                        "OUTSIDE_TARGET_POOL",
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                )
            selections.append(
                _blocked_product(
                    key,
                    expected_prior=None,
                    ranking_day=(
                        coverage_by_id[key_id][0].ranking_trading_day
                        if coverage_by_id.get(key_id)
                        else None
                    ),
                    blockers=(),
                    in_target_pool=False,
                )
            )
            continue

        blockers = list(source_blockers)
        calendar, calendar_blockers = _calendar_for(key, calendar_index, decision_at)
        blockers.extend(calendar_blockers)
        current_day = day_index.get(key.exchange_id)
        expected_prior = None
        if current_day is None:
            blockers.append("CURRENT_TRADING_DAY_UNAVAILABLE")
        elif calendar is not None and not calendar_blockers:
            try:
                expected_prior = calendar.previous_complete_trading_day(current_day)
            except TradingCalendarContractError as exc:
                blockers.append(exc.code)
        if current_day is not None:
            day_references[key.exchange_id] = TradingDayReference(
                key.exchange_id, current_day, expected_prior
            )
        if calendar is not None and not calendar_blockers:
            used_calendars[key.exchange_id] = _calendar_evidence(calendar)

        coverage_matches = coverage_by_id.get(key_id, [])
        coverage = coverage_matches[0] if len(coverage_matches) == 1 else None
        if not coverage_matches:
            blockers.append("PRODUCT_COVERAGE_UNAVAILABLE")
        elif len(coverage_matches) > 1:
            blockers.append("DUPLICATE_PRODUCT_COVERAGE")
        records = records_by_id.get(key_id, [])
        if coverage is not None:
            if not coverage.candidate_set_complete:
                blockers.append("CANDIDATE_SET_INCOMPLETE")
            if coverage.candidate_count != len(records):
                blockers.append("CANDIDATE_COUNT_MISMATCH")
            record_ids = [record.instrument_id for record in records]
            expected_ids = list(coverage.expected_instrument_ids)
            expected_id_keys = [instrument_id.casefold() for instrument_id in expected_ids]
            if any(
                not instrument_id or instrument_id != instrument_id.strip()
                for instrument_id in expected_ids
            ):
                blockers.append("EXPECTED_INSTRUMENT_ID_INVALID")
            if len(set(expected_id_keys)) != len(expected_id_keys):
                blockers.append("DUPLICATE_EXPECTED_INSTRUMENT_ID")
            if len(expected_ids) != coverage.candidate_count:
                blockers.append("EXPECTED_INSTRUMENT_ID_COUNT_MISMATCH")
            if set(expected_ids) != set(record_ids):
                blockers.append("CANDIDATE_ID_SET_MISMATCH")
            ranking_ids = list(coverage.ranking_instrument_ids)
            ranking_id_keys = [instrument_id.casefold() for instrument_id in ranking_ids]
            if len(set(ranking_id_keys)) != len(ranking_id_keys):
                blockers.append("DUPLICATE_RANKING_INSTRUMENT_ID")
            if not set(ranking_ids).issubset(set(expected_ids)):
                blockers.append("RANKING_ID_OUTSIDE_CANDIDATE_SET")
            if not coverage.ranking_values_complete:
                blockers.append("RANKING_VALUES_INCOMPLETE")
            if not coverage.finalized:
                blockers.append("RANKING_NOT_FINALIZED")
            if not coverage.latest_available:
                blockers.append("RANKING_SNAPSHOT_NOT_LATEST")
            if coverage.ranking_trading_day is None:
                blockers.append("RANKING_TRADING_DAY_UNAVAILABLE")
            elif expected_prior is not None and coverage.ranking_trading_day != expected_prior:
                code = (
                    "RANKING_STALE"
                    if coverage.ranking_trading_day < expected_prior
                    else "RANKING_DAY_LOOKAHEAD"
                )
                blockers.append(code)
            if not coverage.open_interest_unit or not coverage.volume_unit:
                blockers.append("RANKING_UNIT_UNAVAILABLE")
        canonical_record_ids = [item.instrument_id.casefold() for item in records]
        if len(set(canonical_record_ids)) != len(canonical_record_ids):
            blockers.append("DUPLICATE_CONTRACT_RECORD")

        group_assessments = []
        eligible = []
        for record in records:
            assessment, is_eligible = _candidate_assessment(
                record,
                current_trading_day=current_day,
                calendar=calendar if not calendar_blockers else None,
                policy=policy,
                suppress_source_values=suppress_source_values,
            )
            group_assessments.append(assessment)
            if assessment.status == "BLOCKED" and assessment.reason:
                blockers.append(assessment.reason)
            if is_eligible:
                eligible.append((record, assessment))

        if coverage is not None:
            ranking_ids = set(coverage.ranking_instrument_ids)
            eligible_ids = {record.instrument_id for record, _assessment in eligible}
            if not eligible_ids.issubset(ranking_ids):
                blockers.append("RANKING_ROW_MISSING_FOR_ELIGIBLE_CANDIDATE")

        blockers = list(dict.fromkeys(blockers))
        if not blockers and not eligible:
            blockers.append("NO_ELIGIBLE_MONTH_FUTURES")

        if blockers:
            final_assessments = []
            for assessment in group_assessments:
                if assessment.status == "ELIGIBLE":
                    assessment = ContractAssessment(
                        assessment.product,
                        assessment.instrument_id,
                        "BLOCKED",
                        blockers[0],
                        assessment.expiry_date,
                        assessment.trading_days_to_expiry,
                        assessment.open_interest,
                        assessment.volume,
                        None,
                        assessment.trading_days_to_expiry_lower_bound,
                        assessment.expiry_distance_exact,
                    )
                final_assessments.append(assessment)
            assessments.extend(final_assessments)
            selections.append(
                _blocked_product(
                    key,
                    expected_prior=expected_prior,
                    ranking_day=coverage.ranking_trading_day if coverage is not None else None,
                    blockers=blockers,
                )
            )
            continue

        ranked = sorted(
            eligible,
            key=lambda pair: (
                -Decimal(pair[1].open_interest),
                -Decimal(pair[1].volume),
                pair[1].expiry_date,
                pair[0].instrument_id,
            ),
        )
        rank_by_id = {
            record.instrument_id.casefold(): index for index, (record, _) in enumerate(ranked, 1)
        }
        ranked_assessments = []
        for assessment in group_assessments:
            rank = rank_by_id.get(assessment.instrument_id.casefold())
            if rank is not None:
                assessment = ContractAssessment(
                    assessment.product,
                    assessment.instrument_id,
                    "RANKED",
                    None,
                    assessment.expiry_date,
                    assessment.trading_days_to_expiry,
                    assessment.open_interest,
                    assessment.volume,
                    rank,
                    assessment.trading_days_to_expiry_lower_bound,
                    assessment.expiry_distance_exact,
                )
            ranked_assessments.append(assessment)
        assessments.extend(ranked_assessments)
        selections.append(
            ProductSelection(
                product=key,
                in_target_pool=True,
                status="READY",
                expected_prior_trading_day=expected_prior,
                ranking_trading_day=coverage.ranking_trading_day,
                selected_instrument_id=ranked[0][0].instrument_id,
                ranked_instrument_ids=tuple(record.instrument_id for record, _ in ranked),
                excluded_instrument_ids=tuple(
                    item.instrument_id for item in group_assessments if item.status == "EXCLUDED"
                ),
                blockers=(),
            )
        )

    target_selections = [item for item in selections if item.in_target_pool]
    manifest_blockers = list(source_blockers)
    manifest_blockers.extend(reason for item in target_selections for reason in item.blockers)
    if not targets:
        manifest_blockers.append("TARGET_PRODUCT_POOL_EMPTY")
    manifest_blockers = list(dict.fromkeys(manifest_blockers))
    status = (
        "READY"
        if targets and all(item.status == "READY" for item in target_selections)
        else "BLOCKED"
    )

    source_id = _source_text(snapshot.source_id) if snapshot is not None else None
    snapshot_id = _source_text(snapshot.snapshot_id) if snapshot is not None else None
    source_sha256 = _source_digest(snapshot.source_sha256) if snapshot is not None else None
    source_available_at = _source_timestamp(snapshot.available_at) if snapshot is not None else None
    source_retrieved_at = _source_timestamp(snapshot.retrieved_at) if snapshot is not None else None
    catalog_source_id = _source_text(snapshot.catalog_source_id) if snapshot is not None else None
    catalog_snapshot_id = (
        _source_text(snapshot.catalog_snapshot_id) if snapshot is not None else None
    )
    catalog_sha256 = _source_digest(snapshot.catalog_sha256) if snapshot is not None else None
    catalog_available_at = (
        _source_timestamp(snapshot.catalog_available_at) if snapshot is not None else None
    )
    catalog_retrieved_at = (
        _source_timestamp(snapshot.catalog_retrieved_at) if snapshot is not None else None
    )
    return MainContractManifest(
        status=status,
        decision_at=decision_at,
        policy=policy,
        target_products=targets,
        source_id=source_id,
        source_snapshot_id=snapshot_id,
        source_sha256=source_sha256,
        source_available_at=source_available_at,
        source_retrieved_at=source_retrieved_at,
        catalog_source_id=catalog_source_id,
        catalog_snapshot_id=catalog_snapshot_id,
        catalog_sha256=catalog_sha256,
        catalog_available_at=catalog_available_at,
        catalog_retrieved_at=catalog_retrieved_at,
        trading_days=tuple(day_references[key] for key in sorted(day_references)),
        calendars=tuple(used_calendars[key] for key in sorted(used_calendars)),
        coverage=tuple(
            sorted(
                snapshot.coverage if snapshot is not None else (),
                key=lambda item: (
                    _key_order(item.product),
                    _canonical_json_sha256(_coverage_dict(item)),
                ),
            )
        ),
        products=tuple(sorted(selections, key=lambda item: _key_order(item.product))),
        candidates=tuple(
            sorted(
                assessments,
                key=lambda item: (
                    _key_order(item.product),
                    item.rank if item.rank is not None else 2**31,
                    item.instrument_id,
                ),
            )
        ),
        blockers=tuple(manifest_blockers),
    )


@dataclass(frozen=True)
class MainContractBinding:
    product: ProductKey
    instrument_id: str


@dataclass(frozen=True)
class MainContractRolloverPlan:
    status: str
    current_manifest_sha256: str
    proposed_manifest_sha256: str
    prior_epoch_id: str
    next_epoch_id: str
    effective_at: datetime
    boundary: RolloverBoundaryEvidence
    effective_trading_days: Tuple[TradingDayReference, ...]
    old_mapping: Tuple[MainContractBinding, ...]
    new_mapping: Tuple[MainContractBinding, ...]
    changed_products: Tuple[ProductKey, ...]
    halt_new_entries_until_ready: bool
    preserve_old_instrument_event_routing: bool
    reset_all_cohort_state: bool
    rewarm_all_members: bool
    required_checks: Tuple[str, ...]

    def __post_init__(self) -> None:
        _aware_datetime(self.effective_at, "rollover effective_at")
        if not isinstance(self.boundary, RolloverBoundaryEvidence):
            raise ValueError("rollover boundary must be RolloverBoundaryEvidence")
        for name in (
            "effective_trading_days",
            "old_mapping",
            "new_mapping",
            "changed_products",
            "required_checks",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class RolloverReadiness:
    """Observed old-epoch and whole-cohort facts required to activate a roll."""

    old_orders_terminal: bool
    old_positions_flat: bool
    old_order_events_reconciled: bool
    old_state_reconciled: bool
    unknown_order_count: int
    old_instrument_event_routes_preserved: bool
    all_cohort_state_reset: bool
    all_members_rewarmed: bool

    def __post_init__(self) -> None:
        for name in (
            "old_orders_terminal",
            "old_positions_flat",
            "old_order_events_reconciled",
            "old_state_reconciled",
            "old_instrument_event_routes_preserved",
            "all_cohort_state_reset",
            "all_members_rewarmed",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError("{} must be a bool".format(name))
        if type(self.unknown_order_count) is not int or self.unknown_order_count < 0:
            raise ValueError("unknown_order_count must be a non-negative int")


@dataclass(frozen=True)
class RolloverAuthorization:
    status: str
    activation_allowed: bool
    activation_required: bool
    blockers: Tuple[str, ...]
    epoch_id: str


_ROLLOVER_CHECKS = (
    "OLD_ORDERS_TERMINAL",
    "OLD_ORDER_EVENTS_RECONCILED",
    "OLD_POSITIONS_FLAT",
    "OLD_STATE_RECONCILED",
    "UNKNOWN_ORDERS_ZERO",
    "OLD_INSTRUMENT_EVENT_ROUTES_PRESERVED",
    "ALL_COHORT_STATE_RESET",
    "ALL_MEMBERS_REWARMED",
)


def plan_main_contract_rollover(
    current: MainContractManifest,
    proposed: MainContractManifest,
    *,
    current_epoch_id: str,
    boundary: RolloverBoundaryEvidence,
) -> MainContractRolloverPlan:
    """Describe, but do not execute, a complete mapping epoch switch."""

    if current.status != "READY" or proposed.status != "READY":
        raise MainContractSelectionBlocked("rollover requires two READY manifests")
    _identity_text(current_epoch_id, "current_epoch_id")
    if not isinstance(boundary, RolloverBoundaryEvidence):
        raise ValueError("boundary must be RolloverBoundaryEvidence")
    if current.policy != proposed.policy:
        raise ValueError("rollover cannot change the frozen selection policy")
    if proposed.decision_at.astimezone(timezone.utc) <= current.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("proposed selection predates the active selection")
    if boundary.available_at.astimezone(timezone.utc) > proposed.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("rollover boundary evidence was unavailable at selection time")
    if boundary.retrieved_at.astimezone(timezone.utc) > proposed.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("rollover boundary evidence was retrieved after selection time")
    if boundary.effective_at.astimezone(timezone.utc) < proposed.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("rollover boundary precedes its selection evidence")

    old_pairs = current.selected_mapping()
    new_pairs = proposed.selected_mapping()
    old_by_key = {_key_order(key): value for key, value in old_pairs}
    new_by_key = {_key_order(key): value for key, value in new_pairs}
    if set(old_by_key) != set(new_by_key):
        raise ValueError("rollover target product pool changed")
    proposed_trading_days = {
        item.exchange_id: item.current_trading_day for item in proposed.trading_days
    }
    boundary_trading_days = {item.exchange_id: item.trading_day for item in boundary.trading_days}
    if boundary_trading_days != proposed_trading_days:
        raise ValueError("rollover boundary does not match the proposed TradingDay set")
    changed = tuple(
        current_key
        for current_key, _instrument in old_pairs
        if old_by_key[_key_order(current_key)] != new_by_key[_key_order(current_key)]
    )
    changed_ids = {_key_order(item) for item in changed}
    old_mapping = tuple(MainContractBinding(key, instrument) for key, instrument in old_pairs)
    new_mapping = tuple(MainContractBinding(key, instrument) for key, instrument in new_pairs)
    if changed:
        next_epoch = _canonical_json_sha256(
            {
                "prior_epoch_id": current_epoch_id,
                "proposed_manifest_sha256": proposed.manifest_sha256,
                "effective_at": _utc_text(boundary.effective_at),
                "changed_products": [list(item) for item in sorted(changed_ids)],
            }
        )
        status = "PENDING_OLD_EPOCH_RECONCILIATION"
        halt = True
        reset = True
        required = _ROLLOVER_CHECKS
    else:
        next_epoch = current_epoch_id
        status = "NO_MAPPING_CHANGE"
        halt = False
        reset = False
        required = ()
    return MainContractRolloverPlan(
        status=status,
        current_manifest_sha256=current.manifest_sha256,
        proposed_manifest_sha256=proposed.manifest_sha256,
        prior_epoch_id=current_epoch_id,
        next_epoch_id=next_epoch,
        effective_at=boundary.effective_at,
        boundary=boundary,
        effective_trading_days=proposed.trading_days,
        old_mapping=old_mapping,
        new_mapping=new_mapping,
        changed_products=changed,
        halt_new_entries_until_ready=halt,
        preserve_old_instrument_event_routing=bool(changed),
        reset_all_cohort_state=reset,
        rewarm_all_members=reset,
        required_checks=required,
    )


def authorize_main_contract_rollover(
    plan: MainContractRolloverPlan,
    readiness: Optional[RolloverReadiness],
) -> RolloverAuthorization:
    """Evaluate old-epoch facts; this function never changes an active mapping."""

    if not plan.changed_products:
        return RolloverAuthorization(
            status="NO_MAPPING_CHANGE",
            activation_allowed=True,
            activation_required=False,
            blockers=(),
            epoch_id=plan.prior_epoch_id,
        )
    if readiness is None:
        return RolloverAuthorization(
            status="BLOCKED_OLD_EPOCH_NOT_RECONCILED",
            activation_allowed=False,
            activation_required=True,
            blockers=("ROLLOVER_READINESS_UNAVAILABLE",),
            epoch_id=plan.prior_epoch_id,
        )
    blockers = []
    if not readiness.old_orders_terminal:
        blockers.append("OLD_ORDERS_NOT_TERMINAL")
    if not readiness.old_order_events_reconciled:
        blockers.append("OLD_ORDER_EVENTS_NOT_RECONCILED")
    if not readiness.old_positions_flat:
        blockers.append("OLD_POSITIONS_NOT_FLAT")
    if not readiness.old_state_reconciled:
        blockers.append("OLD_STATE_NOT_RECONCILED")
    if readiness.unknown_order_count != 0:
        blockers.append("UNKNOWN_ORDERS_PRESENT")
    if not readiness.old_instrument_event_routes_preserved:
        blockers.append("OLD_INSTRUMENT_EVENT_ROUTES_NOT_PRESERVED")
    if not readiness.all_cohort_state_reset:
        blockers.append("COHORT_STATE_NOT_RESET")
    if not readiness.all_members_rewarmed:
        blockers.append("COHORT_REWARM_INCOMPLETE")
    if blockers:
        return RolloverAuthorization(
            status="BLOCKED_OLD_EPOCH_NOT_RECONCILED",
            activation_allowed=False,
            activation_required=True,
            blockers=tuple(blockers),
            epoch_id=plan.prior_epoch_id,
        )
    return RolloverAuthorization(
        status="ACTIVATION_CONDITIONS_MET",
        activation_allowed=True,
        activation_required=True,
        blockers=(),
        epoch_id=plan.next_epoch_id,
    )


__all__ = [
    "CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY",
    "CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_V1",
    "EXCLUSION_REASON_NO_LISTED_CONTRACTS",
    "CalendarEvidence",
    "ContractAssessment",
    "DEFAULT_MAIN_CONTRACT_POLICY",
    "ExchangeTradingCalendar",
    "ExchangeTradingDay",
    "FuturesContractCatalogRecord",
    "FuturesContractRecord",
    "CurrentDayQuoteRecord",
    "LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_POLICY",
    "LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_V1",
    "MainContractBinding",
    "MainContractManifest",
    "MainContractPolicy",
    "MainContractQueryCoverage",
    "MainContractQuerySnapshot",
    "MainContractRankingSnapshot",
    "MainContractRolloverPlan",
    "MainContractSelectionBlocked",
    "ProductKey",
    "ProductRankingCoverage",
    "ProductSelection",
    "QuerySnapshotExcludedProductEvidence",
    "QuerySnapshotProductEvidence",
    "QuerySnapshotSetEvidence",
    "QuerySnapshotSourceEvidence",
    "RANKING_MODE_CTP_QUERY_SNAPSHOT",
    "RANKING_MODE_LEGACY_PRIOR_DAY_OI",
    "RolloverBoundaryEvidence",
    "RolloverAuthorization",
    "RolloverReadiness",
    "TradingCalendarContractError",
    "TradingDayReference",
    "authorize_main_contract_rollover",
    "plan_main_contract_rollover",
    "query_snapshot_set_digest",
    "select_main_contracts",
]
