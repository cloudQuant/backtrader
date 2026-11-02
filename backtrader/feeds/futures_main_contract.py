"""Point-in-time futures main-contract selection and rollover contracts.

This module contains deterministic futures selection policies and their
evidence projections.  The provider-neutral policy consumes the SDK's
normalized futures catalog, per-venue session, and quote snapshot DTOs.  The
legacy ranking input remains available for prior-day finalized OI sources.

The default policy ranks actual monthly futures by prior-day open interest,
then volume, then expiry date, then the exact instrument identifier. Instrument
identifiers are retained verbatim for routing; only exchange/product keys are
canonicalized for comparisons.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence, Tuple


_SOURCE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONTH_CONTRACT = re.compile(r"^[A-Za-z]{1,8}([0-9]{3,4})$")
_KNOWN_NON_FUTURES = frozenset(
    {
        "option",
        "options",
        "non_future",
        "non_futures",
        "combination",
        "spot",
        "spot_option",
        "index",
    }
)
LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_V1 = "legacy_previous_complete_day_eod_oi_v1"
RANKING_MODE_LEGACY_PRIOR_DAY_OI = "legacy_previous_complete_day_eod_oi_v1"
RANKING_MODE_FUTURES_MARKET_SNAPSHOT = "futures_market_snapshot_equal_weight_v1"
_RANKING_METRIC_MAX_DIGITS = 512
_RANKING_METRIC_MAX_ABS_EXPONENT = 256
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
    """Accept standard year-month contracts and reject continuous aliases."""

    match = _MONTH_CONTRACT.fullmatch(instrument_id)
    if match is None:
        return False
    digits = match.group(1)
    product_prefix = instrument_id[: -len(digits)]
    if product_prefix.casefold() != product_id.casefold():
        return False
    # A real month suffix rejects common 888/999/8888/9999 continuous aliases.
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
    """Provider session trading day being considered for one exchange."""

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
            RANKING_MODE_FUTURES_MARKET_SNAPSHOT,
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
FUTURES_MARKET_SNAPSHOT_EQUAL_WEIGHT_POLICY = MainContractPolicy(
    policy_id=RANKING_MODE_FUTURES_MARKET_SNAPSHOT,
    ranking_mode=RANKING_MODE_FUTURES_MARKET_SNAPSHOT,
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
    quote_trading_day: Optional[date] = None
    contract_kind: Optional[str] = None
    provider_event_date: Optional[date] = None
    provider_event_time: Optional[str] = None
    provider_event_millisecond: Optional[int] = None
    volume_semantics: Optional[str] = None


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
class MainContractMarketCoverage:
    """Neutral catalog/quote identity coverage for one selected product."""

    product: ProductKey
    catalog_instrument_ids: Tuple[str, ...]
    expected_quote_instrument_ids: Tuple[str, ...]
    observed_quote_instrument_ids: Tuple[str, ...]
    metric_unit: str = "contracts"
    volume_semantics: str = "cumulative_trading_day"

    def __post_init__(self) -> None:
        if type(self.product) is not ProductKey:
            raise ValueError("market coverage product must be a ProductKey")
        for name in (
            "catalog_instrument_ids",
            "expected_quote_instrument_ids",
            "observed_quote_instrument_ids",
        ):
            values = tuple(getattr(self, name))
            if any(type(value) is not str for value in values):
                raise ValueError("{} must contain neutral instrument IDs".format(name))
            object.__setattr__(self, name, values)
        _identity_text(self.metric_unit, "metric_unit")
        _identity_text(self.volume_semantics, "volume_semantics")


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
    market_coverage: Tuple[MainContractMarketCoverage, ...] = ()
    market_snapshot_evidence_json: Optional[str] = None

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
            "market_coverage",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.market_snapshot_evidence_json is not None:
            if type(self.market_snapshot_evidence_json) is not str:
                raise ValueError("market_snapshot_evidence_json must be text or None")
            try:
                snapshot_evidence = json.loads(self.market_snapshot_evidence_json)
            except (TypeError, ValueError):
                raise ValueError("market snapshot evidence must be valid JSON") from None
            if type(snapshot_evidence) is not dict:
                raise ValueError("market snapshot evidence must be a JSON object")

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

        market_snapshot_mode = (
            self.policy.ranking_mode == RANKING_MODE_FUTURES_MARKET_SNAPSHOT
        )
        projection = {
            "schema": (
                "backtrader.futures_main_contract_manifest.v3"
                if market_snapshot_mode
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
                    **({"selected_score": item.selected_score} if market_snapshot_mode else {}),
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
                            "contract_kind": item.contract_kind,
                            "is_trading": item.is_trading,
                            "quote_trading_day": item.quote_trading_day.isoformat()
                            if item.quote_trading_day is not None
                            else None,
                            "provider_event_date": item.provider_event_date.isoformat()
                            if item.provider_event_date is not None
                            else None,
                            "provider_event_time": item.provider_event_time,
                            "provider_event_millisecond": item.provider_event_millisecond,
                            "volume_semantics": item.volume_semantics,
                        }
                        if market_snapshot_mode
                        else {}
                    ),
                }
                for item in self.candidates
            ],
            "blockers": list(self.blockers),
        }
        if market_snapshot_mode:
            projection["policy"].update(
                {
                    "ranking_mode": self.policy.ranking_mode,
                    "score_formula": "0.5 * open_interest + 0.5 * volume",
                    "weights": {"open_interest": "0.5", "volume": "0.5"},
                    "metric_unit": "contracts",
                    "volume_semantics": "cumulative_trading_day",
                    "ranking": [
                        "equal_weight_score_desc",
                        "open_interest_desc",
                        "volume_desc",
                        "expiry_date_asc",
                        "instrument_id_asc",
                    ],
                    "max_snapshot_age_seconds": self.policy.max_snapshot_age_seconds,
                    "max_collection_span_seconds": self.policy.max_collection_span_seconds,
                }
            )
            projection["market_snapshot"] = (
                json.loads(self.market_snapshot_evidence_json)
                if self.market_snapshot_evidence_json is not None
                else None
            )
            projection["market_coverage"] = [
                {
                    "product": _product_dict(item.product),
                    "catalog_instrument_ids": list(item.catalog_instrument_ids),
                    "expected_quote_instrument_ids": list(item.expected_quote_instrument_ids),
                    "observed_quote_instrument_ids": list(item.observed_quote_instrument_ids),
                    "metric_unit": item.metric_unit,
                    "volume_semantics": item.volume_semantics,
                }
                for item in self.market_coverage
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

    Ranking metrics are normally bounded count values. A finite bound keeps
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
        or abs(left_exponent) > _RANKING_METRIC_MAX_ABS_EXPONENT
        or abs(right_exponent) > _RANKING_METRIC_MAX_ABS_EXPONENT
    ):
        return None
    if (
        len(left.digits) > _RANKING_METRIC_MAX_DIGITS
        or len(right.digits) > _RANKING_METRIC_MAX_DIGITS
    ):
        return None
    left_digits = "".join(str(digit) for digit in left.digits) or "0"
    right_digits = "".join(str(digit) for digit in right.digits) or "0"
    common_exponent = min(left_exponent, right_exponent)
    left_shift = left_exponent - common_exponent
    right_shift = right_exponent - common_exponent
    if (
        len(left_digits) + left_shift > _RANKING_METRIC_MAX_DIGITS
        or len(right_digits) + right_shift > _RANKING_METRIC_MAX_DIGITS
        or abs(common_exponent - 1) > _RANKING_METRIC_MAX_ABS_EXPONENT + 1
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
    require_month_contract: bool = True,
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
    if require_month_contract and not _is_actual_month_contract(
        record.instrument_id, record.product.product_id
    ):
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


def _futures_market_sdk_types() -> Optional[dict[str, Any]]:
    """Load exact SDK contracts only for the provider-neutral selector."""

    try:
        from bt_api_py.futures_contracts import (
            FuturesAssetType,
            FuturesCatalogDisposition,
            FuturesCatalogRecord,
            FuturesContractKind,
            FuturesFamilyCoverage,
            FuturesMarketSnapshotCoverage,
            FuturesMarketSnapshotRequest,
            FuturesProductKey,
            FuturesQuantityUnit,
            FuturesQuoteRecord,
            FuturesSessionRecord,
            FuturesSessionStatus,
            FuturesVolumeSemantics,
            MarketInstrumentKey,
            QuerySnapshotLease,
        )
        from bt_api_py.futures_market_facade import (
            FuturesMarketSnapshot,
            FuturesMarketSnapshotFacade,
        )
    except ImportError:
        return None
    return {
        "FuturesAssetType": FuturesAssetType,
        "FuturesCatalogDisposition": FuturesCatalogDisposition,
        "FuturesCatalogRecord": FuturesCatalogRecord,
        "FuturesContractKind": FuturesContractKind,
        "FuturesFamilyCoverage": FuturesFamilyCoverage,
        "FuturesMarketSnapshotCoverage": FuturesMarketSnapshotCoverage,
        "FuturesMarketSnapshotRequest": FuturesMarketSnapshotRequest,
        "FuturesMarketSnapshot": FuturesMarketSnapshot,
        "FuturesMarketSnapshotFacade": FuturesMarketSnapshotFacade,
        "FuturesProductKey": FuturesProductKey,
        "FuturesQuantityUnit": FuturesQuantityUnit,
        "FuturesQuoteRecord": FuturesQuoteRecord,
        "FuturesSessionRecord": FuturesSessionRecord,
        "FuturesSessionStatus": FuturesSessionStatus,
        "FuturesVolumeSemantics": FuturesVolumeSemantics,
        "MarketInstrumentKey": MarketInstrumentKey,
        "QuerySnapshotLease": QuerySnapshotLease,
    }


def _market_snapshot_json(snapshot: Any, sdk: Mapping[str, Any]) -> Optional[str]:
    """Project finite neutral receipt facts without retaining SDK rows."""

    if type(snapshot) is not sdk["FuturesMarketSnapshot"]:
        return None
    coverage = getattr(snapshot, "coverage", None)
    if type(coverage) is not sdk["FuturesMarketSnapshotCoverage"]:
        return None

    def time_text(value: Any) -> Optional[str]:
        normalized = _source_timestamp(value)
        return _utc_text(normalized) if normalized is not None else None

    def family_projection(value: Any) -> Optional[dict[str, Any]]:
        if type(value) is not sdk["FuturesFamilyCoverage"]:
            return None
        completeness = getattr(value.completeness, "value", None)
        return {
            "family": _source_text(value.family),
            "request_ref": _source_text(value.request_ref),
            "source_ref": _source_text(value.source_ref),
            "generation": _source_text(value.generation),
            "snapshot_ref": _source_text(value.snapshot_ref),
            "completeness": _source_text(completeness),
            "scope_complete": value.scope_complete if type(value.scope_complete) is bool else None,
            "complete": value.complete if type(value.complete) is bool else None,
            "started_at": time_text(value.started_at),
            "completed_at": time_text(value.completed_at),
            "observed_at": time_text(value.observed_at),
            "records_digest": _source_digest(value.records_digest),
            "record_count": value.record_count
            if type(value.record_count) is int and value.record_count >= 0
            else None,
            "blockers": [item for item in value.blockers if type(item) is str],
            "continuation_present": value.continuation_ref is not None,
        }

    sessions = []
    for row in getattr(snapshot, "sessions", ()):
        if type(row) is not sdk["FuturesSessionRecord"]:
            continue
        sessions.append(
            {
                "venue": _source_text(row.venue),
                "environment": _source_text(row.environment),
                "trading_day": row.trading_day.isoformat()
                if type(row.trading_day) is date
                else None,
                "session_status": _source_text(getattr(row.session_status, "value", None)),
            }
        )
    projection = {
        "source_ref": _source_text(snapshot.source_ref),
        "generation": _source_text(snapshot.generation),
        "records_digest": _source_digest(snapshot.records_digest),
        "request_refs": [
            item for item in snapshot.request_refs if type(item) is str and item
        ],
        "requested_at": time_text(snapshot.requested_at),
        "completed_at": time_text(snapshot.completed_at),
        "observed_at": time_text(snapshot.observed_at),
        "complete": snapshot.complete if type(snapshot.complete) is bool else None,
        "freshness_status": _source_text(
            getattr(snapshot.freshness_status, "value", snapshot.freshness_status)
        ),
        "freshness_blockers": [
            item for item in snapshot.freshness_blockers if type(item) is str
        ],
        "coverage": {
            name: family_projection(getattr(coverage, name, None))
            for name in ("session", "catalog", "quotes", "depth")
        },
        "coverage_scope_complete": coverage.scope_complete
        if type(coverage.scope_complete) is bool
        else None,
        "coverage_complete": coverage.complete if type(coverage.complete) is bool else None,
        "expected_instrument_count": len(coverage.expected_instruments),
        "missing_quote_instrument_count": len(coverage.missing_quote_instruments),
        "missing_depth_instrument_count": len(coverage.missing_depth_instruments),
        "missing_quote_field_row_count": len(coverage.missing_quote_fields),
        "unclassified_instrument_count": len(coverage.unclassified_instruments),
        "quote_unit_mismatch_count": len(getattr(coverage, "quote_unit_mismatches", ())),
        "quote_semantic_mismatch_count": len(
            getattr(coverage, "quote_semantic_mismatches", ())
        ),
        "depth_unit_mismatch_count": len(
            getattr(coverage, "depth_unit_mismatches", ())
        ),
        "sessions": sessions,
        "blockers": [item for item in coverage.blockers if type(item) is str],
    }
    return json.dumps(projection, sort_keys=True, separators=(",", ":"))


def _market_snapshot_source_fields(snapshot: Any, sdk: Mapping[str, Any]) -> dict[str, Any]:
    if type(snapshot) is not sdk["FuturesMarketSnapshot"]:
        return {
            "source_id": None,
            "source_snapshot_id": None,
            "source_sha256": None,
            "source_available_at": None,
            "source_retrieved_at": None,
            "catalog_source_id": None,
            "catalog_snapshot_id": None,
            "catalog_sha256": None,
            "catalog_available_at": None,
            "catalog_retrieved_at": None,
        }
    coverage = snapshot.coverage
    catalog = getattr(coverage, "catalog", None)
    quotes = getattr(coverage, "quotes", None)
    return {
        "source_id": _source_text(snapshot.source_ref),
        "source_snapshot_id": _source_text(getattr(quotes, "snapshot_ref", None)),
        "source_sha256": _source_digest(snapshot.records_digest),
        "source_available_at": _source_timestamp(snapshot.completed_at),
        "source_retrieved_at": _source_timestamp(snapshot.observed_at),
        "catalog_source_id": _source_text(getattr(catalog, "source_ref", None)),
        "catalog_snapshot_id": _source_text(getattr(catalog, "snapshot_ref", None)),
        "catalog_sha256": _source_digest(getattr(catalog, "records_digest", None)),
        "catalog_available_at": _source_timestamp(getattr(catalog, "completed_at", None)),
        "catalog_retrieved_at": _source_timestamp(getattr(catalog, "observed_at", None)),
    }


def _neutral_partial_manifest(
    snapshot: Any,
    expected_products: Sequence[ProductKey],
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    blockers: Sequence[str],
    sdk: Optional[Mapping[str, Any]],
) -> MainContractManifest:
    targets = tuple(sorted(expected_products, key=_key_order))
    blocker_rows = tuple(dict.fromkeys(blockers or ("MARKET_SNAPSHOT_COVERAGE_UNAVAILABLE",)))
    trading_days = {}
    if sdk is not None and type(snapshot) is sdk["FuturesMarketSnapshot"]:
        raw_days = getattr(snapshot, "trading_days", {})
        if isinstance(raw_days, Mapping):
            trading_days = {
                venue.upper(): day
                for venue, day in raw_days.items()
                if type(venue) is str and type(day) is date
            }
    source_fields = (
        _market_snapshot_source_fields(snapshot, sdk)
        if sdk is not None
        else {
            "source_id": None,
            "source_snapshot_id": None,
            "source_sha256": None,
            "source_available_at": None,
            "source_retrieved_at": None,
            "catalog_source_id": None,
            "catalog_snapshot_id": None,
            "catalog_sha256": None,
            "catalog_available_at": None,
            "catalog_retrieved_at": None,
        }
    )
    return MainContractManifest(
        status="PARTIAL",
        decision_at=decision_at,
        policy=policy,
        target_products=targets,
        **source_fields,
        trading_days=tuple(
            TradingDayReference(venue, day, None) for venue, day in sorted(trading_days.items())
        ),
        calendars=(),
        coverage=(),
        products=tuple(
            ProductSelection(
                product=product,
                in_target_pool=True,
                status="PARTIAL",
                expected_prior_trading_day=None,
                ranking_trading_day=trading_days.get(product.exchange_id),
                selected_instrument_id=None,
                ranked_instrument_ids=(),
                excluded_instrument_ids=(),
                blockers=blocker_rows,
            )
            for product in targets
        ),
        candidates=(),
        blockers=blocker_rows,
        market_snapshot_evidence_json=(
            _market_snapshot_json(snapshot, sdk) if sdk is not None else None
        ),
    )


def _sdk_family_complete(family: Any, sdk: Mapping[str, Any]) -> bool:
    return (
        type(family) is sdk["FuturesFamilyCoverage"]
        and family.complete is True
        and family.scope_complete is True
    )


def _neutral_snapshot_blockers(
    snapshot: Any,
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    sdk: Mapping[str, Any],
) -> Tuple[str, ...]:
    coverage = getattr(snapshot, "coverage", None)
    if type(coverage) is not sdk["FuturesMarketSnapshotCoverage"]:
        return ("MARKET_SNAPSHOT_COVERAGE_TYPE_INVALID",)
    blockers = []
    request = getattr(snapshot, "request", None)
    request_is_exact = type(request) is sdk["FuturesMarketSnapshotRequest"]
    if not request_is_exact:
        blockers.append("MARKET_SNAPSHOT_REQUEST_TYPE_INVALID")
    include_depth = getattr(request, "include_depth", False)
    if type(include_depth) is not bool:
        blockers.append("MARKET_SNAPSHOT_DEPTH_REQUIREMENT_INVALID")
        include_depth = True
    elif not include_depth and coverage.depth is not None:
        blockers.append("UNREQUESTED_DEPTH_FAMILY_PRESENT")
    if snapshot.complete is not True or coverage.complete is not True:
        blockers.append("MARKET_SNAPSHOT_COVERAGE_INCOMPLETE")
    if coverage.scope_complete is not True:
        blockers.append("MARKET_SNAPSHOT_SCOPE_INCOMPLETE")
    family_names = ("session", "catalog", "quotes") + (("depth",) if include_depth else ())
    for name in family_names:
        if not _sdk_family_complete(getattr(coverage, name, None), sdk):
            blockers.append("{}_FAMILY_COVERAGE_INCOMPLETE".format(name.upper()))
    blockers.extend(item for item in coverage.blockers if type(item) is str and item)
    if coverage.missing_quote_instruments:
        blockers.append("QUOTE_COVERAGE_MISSING_INSTRUMENTS")
    if coverage.missing_quote_fields:
        blockers.append("QUOTE_COVERAGE_MISSING_REQUIRED_FIELDS")
    if coverage.unclassified_instruments:
        blockers.append("CATALOG_COVERAGE_HAS_UNCLASSIFIED_INSTRUMENTS")
    if getattr(coverage, "quote_unit_mismatches", ()):
        blockers.append("QUOTE_COVERAGE_UNIT_MISMATCH")
    if getattr(coverage, "quote_semantic_mismatches", ()):
        blockers.append("QUOTE_COVERAGE_SEMANTICS_MISMATCH")
    if include_depth and getattr(coverage, "depth_unit_mismatches", ()):
        blockers.append("DEPTH_COVERAGE_UNIT_MISMATCH")

    environment = getattr(request, "environment", None)
    if type(environment) is not str or environment.casefold() == "unknown":
        blockers.append("MARKET_SNAPSHOT_ENVIRONMENT_UNAVAILABLE")
    quantity_unit = sdk["FuturesQuantityUnit"]
    if request is None or (
        getattr(request, "required_open_interest_unit", None) is not quantity_unit.CONTRACTS
        or getattr(request, "required_volume_unit", None) is not quantity_unit.CONTRACTS
    ):
        blockers.append("RANKING_QUANTITY_UNIT_REQUIREMENT_UNAVAILABLE")
    volume_semantics = sdk["FuturesVolumeSemantics"]
    if getattr(request, "required_volume_semantics", None) is not (
        volume_semantics.CUMULATIVE_TRADING_DAY
    ):
        blockers.append("RANKING_VOLUME_SEMANTICS_REQUIREMENT_UNAVAILABLE")
    if include_depth and getattr(request, "required_depth_volume_unit", None) is not (
        quantity_unit.CONTRACTS
    ):
        blockers.append("DEPTH_QUANTITY_UNIT_REQUIREMENT_UNAVAILABLE")

    source_ref = _source_text(getattr(snapshot, "source_ref", None))
    generation = _source_text(getattr(snapshot, "generation", None))
    if source_ref is None or generation is None:
        blockers.append("MARKET_SNAPSHOT_SOURCE_BINDING_UNAVAILABLE")
    for name in family_names:
        family = getattr(coverage, name, None)
        if type(family) is not sdk["FuturesFamilyCoverage"]:
            continue
        if family.source_ref != source_ref or family.generation != generation:
            blockers.append("MARKET_SNAPSHOT_FAMILY_SOURCE_MISMATCH")

    requested_at = _source_timestamp(getattr(snapshot, "requested_at", None))
    completed_at = _source_timestamp(getattr(snapshot, "completed_at", None))
    observed_at = _source_timestamp(getattr(snapshot, "observed_at", None))
    decision_utc = decision_at.astimezone(timezone.utc)
    if requested_at is None or completed_at is None or observed_at is None:
        blockers.append("MARKET_SNAPSHOT_TIME_UNAVAILABLE")
    else:
        requested_utc = requested_at.astimezone(timezone.utc)
        completed_utc = completed_at.astimezone(timezone.utc)
        observed_utc = observed_at.astimezone(timezone.utc)
        if requested_utc > completed_utc or completed_utc > observed_utc:
            blockers.append("MARKET_SNAPSHOT_TIME_ORDER_INVALID")
        if completed_utc > decision_utc or observed_utc > decision_utc:
            blockers.append("MARKET_SNAPSHOT_NOT_AVAILABLE_AT_DECISION")
        if (decision_utc - completed_utc).total_seconds() > policy.max_snapshot_age_seconds:
            blockers.append("MARKET_SNAPSHOT_TOO_OLD")
        if (completed_utc - requested_utc).total_seconds() > policy.max_collection_span_seconds:
            blockers.append("MARKET_SNAPSHOT_COLLECTION_SPAN_EXCEEDED")
    return tuple(dict.fromkeys(blockers))


def _neutral_classification(record: Any, sdk: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """Classify through neutral SDK enums without inspecting native provider rows."""

    if type(record) is not sdk["FuturesCatalogRecord"]:
        return "unknown", "CATALOG_ROW_TYPE_INVALID"
    if (
        type(record.contract_kind) is not sdk["FuturesContractKind"]
        or type(record.asset_type) is not sdk["FuturesAssetType"]
        or type(record.disposition) is not sdk["FuturesCatalogDisposition"]
    ):
        return "unknown", "CATALOG_CLASSIFICATION_TYPE_INVALID"
    if record.disposition is sdk["FuturesCatalogDisposition"].EXCLUDED:
        return "non_future", record.disposition_reason or "CATALOG_DISPOSITION_EXCLUDED"
    if (
        record.disposition is sdk["FuturesCatalogDisposition"].UNKNOWN
        or record.contract_kind is sdk["FuturesContractKind"].UNKNOWN
    ):
        return "unknown", "CATALOG_CLASSIFICATION_UNAVAILABLE"
    if record.contract_kind is not sdk["FuturesContractKind"].FUTURE:
        return "non_future", record.disposition_reason or "NOT_ORDINARY_FUTURE"
    if record.asset_type is sdk["FuturesAssetType"].UNKNOWN:
        return "unknown", "CATALOG_CLASSIFICATION_UNAVAILABLE"
    return "future", None


def _select_futures_market_snapshot_rows(
    snapshot: Any,
    expected_products: Sequence[ProductKey],
    calendars: Sequence[ExchangeTradingCalendar],
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    sdk: Mapping[str, Any],
) -> MainContractManifest:
    targets = tuple(expected_products)
    if any(type(item) is not ProductKey for item in targets):
        raise ValueError("expected_products must contain ProductKey records")
    targets = tuple(sorted(targets, key=_key_order))
    target_by_id = {_key_order(item): item for item in targets}
    if len(target_by_id) != len(targets):
        raise ValueError("expected_products contains duplicate product keys")

    session_blockers = []
    session_by_venue = {}
    route_session = None
    request = getattr(snapshot, "request", None)
    requested_environment = getattr(request, "environment", None)
    require_active_session = getattr(request, "require_active_session", False)
    if type(require_active_session) is not bool:
        session_blockers.append("SESSION_ACTIVE_REQUIREMENT_INVALID")
    for row in tuple(getattr(snapshot, "sessions", ())):
        if type(row) is not sdk["FuturesSessionRecord"]:
            session_blockers.append("SESSION_ROW_TYPE_INVALID")
            continue
        if type(row.session_status) is not sdk["FuturesSessionStatus"]:
            session_blockers.append("SESSION_STATUS_UNKNOWN")
            continue
        if type(requested_environment) is not str or row.environment != requested_environment:
            session_blockers.append("SESSION_ENVIRONMENT_MISMATCH")
        if require_active_session and row.session_status is not sdk["FuturesSessionStatus"].ACTIVE:
            session_blockers.append("SESSION_NOT_ACTIVE")
        if row.venue is None:
            if route_session is not None or session_by_venue:
                session_blockers.append("SESSION_ROUTE_VENUE_SCOPE_MIXED_OR_DUPLICATE")
                continue
            route_session = row
        else:
            venue = row.venue.upper()
            if route_session is not None:
                session_blockers.append("SESSION_ROUTE_VENUE_SCOPE_MIXED_OR_DUPLICATE")
                continue
            if venue in session_by_venue:
                session_blockers.append("SESSION_ROW_DUPLICATE_VENUE")
                continue
            session_by_venue[venue] = row
    raw_days = getattr(snapshot, "trading_days", None)
    day_by_venue = {}
    if isinstance(raw_days, Mapping):
        for venue, trading_day in raw_days.items():
            if type(venue) is not str or type(trading_day) is not date:
                session_blockers.append("SESSION_TRADING_DAY_INVALID")
                continue
            venue_key = venue.upper()
            if venue_key in day_by_venue:
                session_blockers.append("SESSION_TRADING_DAY_DUPLICATE_VENUE")
                continue
            day_by_venue[venue_key] = trading_day
    else:
        session_blockers.append("SESSION_TRADING_DAYS_UNAVAILABLE")
    for venue, row in session_by_venue.items():
        if day_by_venue.get(venue) != row.trading_day:
            session_blockers.append("SESSION_TRADING_DAY_MISMATCH")
    if route_session is not None:
        for venue, trading_day in day_by_venue.items():
            if trading_day != route_session.trading_day:
                session_blockers.append("SESSION_ROUTE_TRADING_DAY_MISMATCH")
    for product in targets:
        has_session = product.exchange_id in session_by_venue or route_session is not None
        if not has_session or product.exchange_id not in day_by_venue:
            session_blockers.append("TARGET_SESSION_COVERAGE_MISSING")
        requested_day = getattr(request, "trading_day", None)
        if requested_day is not None and day_by_venue.get(product.exchange_id) != requested_day:
            session_blockers.append("SESSION_REQUESTED_TRADING_DAY_MISMATCH")
    session_blockers = list(dict.fromkeys(session_blockers))

    instrument_type = sdk["MarketInstrumentKey"]
    product_type = sdk["FuturesProductKey"]
    catalog_by_identity = {}
    catalog_by_product = {}
    classification_by_identity = {}
    row_blockers = []
    for row in tuple(getattr(snapshot, "catalog", ())):
        if type(row) is not sdk["FuturesCatalogRecord"]:
            row_blockers.append("CATALOG_ROW_TYPE_INVALID")
            continue
        if (
            type(row.instrument) is not instrument_type
            or type(row.product) is not product_type
            or row.instrument.venue != row.product.venue
            or type(requested_environment) is not str
            or row.instrument.environment != requested_environment
        ):
            row_blockers.append("CATALOG_ROW_IDENTITY_INVALID")
            continue
        catalog_by_identity.setdefault(row.instrument, []).append(row)
        product = ProductKey(row.product.venue, row.product.product_id)
        catalog_by_product.setdefault(_key_order(product), []).append(row)
        classification_by_identity[row.instrument] = _neutral_classification(row, sdk)
    if any(len(rows) > 1 for rows in catalog_by_identity.values()):
        row_blockers.append("DUPLICATE_CATALOG_INSTRUMENT_IDENTITY")

    quote_by_identity = {}
    quote_rows = tuple(getattr(snapshot, "quotes", ()))
    for quote in quote_rows:
        if type(quote) is not sdk["FuturesQuoteRecord"]:
            row_blockers.append("QUOTE_ROW_TYPE_INVALID")
            continue
        if (
            type(quote.instrument) is not instrument_type
            or type(requested_environment) is not str
            or quote.instrument.environment != requested_environment
        ):
            row_blockers.append("QUOTE_ROW_IDENTITY_INVALID")
            continue
        if quote.instrument not in catalog_by_identity:
            row_blockers.append("QUOTE_IDENTITY_NOT_IN_CATALOG")
            continue
        quote_by_identity.setdefault(quote.instrument, []).append(quote)
        if day_by_venue.get(quote.instrument.venue.upper()) != quote.trading_day:
            row_blockers.append("QUOTE_TRADING_DAY_MISMATCH")
    if any(len(rows) > 1 for rows in quote_by_identity.values()):
        row_blockers.append("DUPLICATE_QUOTE_INSTRUMENT_IDENTITY")
    row_blockers = list(dict.fromkeys(row_blockers))

    source_blockers = list(
        _neutral_snapshot_blockers(
            snapshot,
            decision_at=decision_at,
            policy=policy,
            sdk=sdk,
        )
    )
    source_blockers.extend(session_blockers)
    source_blockers.extend(row_blockers)
    source_blockers = list(dict.fromkeys(source_blockers))

    calendar_rows = tuple(calendars)
    if any(type(item) is not ExchangeTradingCalendar for item in calendar_rows):
        raise ValueError("calendars must contain ExchangeTradingCalendar records")
    calendar_index = {}
    for calendar in calendar_rows:
        if calendar.exchange_id in calendar_index:
            raise ValueError("calendars contains duplicate exchanges")
        calendar_index[calendar.exchange_id] = calendar

    expected_by_product = {}
    for identity in snapshot.coverage.expected_instruments:
        if type(identity) is not instrument_type:
            source_blockers.append("EXPECTED_QUOTE_IDENTITY_INVALID")
            continue
        rows = catalog_by_identity.get(identity, ())
        if len(rows) == 1:
            product = rows[0].product
            product_id = _key_order(ProductKey(product.venue, product.product_id))
            expected_by_product.setdefault(product_id, []).append(identity.instrument_id)
    source_blockers = list(dict.fromkeys(source_blockers))

    request = getattr(snapshot, "request", None)
    requested_products = getattr(request, "products", None)
    requested_venues = getattr(request, "venues", None)
    requested_instruments = getattr(request, "instruments", None)
    requested_contract_kinds = getattr(request, "contract_kinds", ())
    requested_quote_fields = getattr(request, "required_quote_fields", ())
    if requested_instruments is not None:
        source_blockers.append("MARKET_SNAPSHOT_INSTRUMENT_FILTER_INCOMPLETE")
    if sdk["FuturesContractKind"].FUTURE not in requested_contract_kinds:
        source_blockers.append("MARKET_SNAPSHOT_FUTURE_SCOPE_MISSING")
    if not {"open_interest", "volume"}.issubset(set(requested_quote_fields)):
        source_blockers.append("MARKET_SNAPSHOT_RANKING_FIELDS_MISSING")
    source_blockers = list(dict.fromkeys(source_blockers))
    requested_product_ids = None
    if requested_products is not None:
        requested_product_ids = {
            _key_order(ProductKey(row.venue, row.product_id))
            for row in requested_products
            if type(row) is product_type
        }
    requested_venue_ids = (
        {item.upper() for item in requested_venues if type(item) is str}
        if requested_venues is not None
        else None
    )
    no_listed_ids = set()
    product_scope_blockers = {}
    for product_id, product in target_by_id.items():
        in_request_scope = (
            product_id in requested_product_ids
            if requested_product_ids is not None
            else product.exchange_id in requested_venue_ids
            if requested_venue_ids is not None
            else True
        )
        if not in_request_scope:
            product_scope_blockers[product_id] = "TARGET_PRODUCT_OUTSIDE_REQUEST_SCOPE"
        if (
            in_request_scope
            and requested_instruments is None
            and not catalog_by_product.get(product_id)
            and not source_blockers
        ):
            no_listed_ids.add(product_id)

    selections = []
    assessments = []
    market_coverage = []
    day_references = {}
    used_calendars = {}
    for product_id in sorted(set(target_by_id).union(catalog_by_product)):
        product = target_by_id.get(product_id)
        if product is None:
            first = catalog_by_product[product_id][0].product
            product = ProductKey(first.venue, first.product_id)
        records = catalog_by_product.get(product_id, ())
        in_target = product_id in target_by_id
        if not in_target:
            for row in records:
                classification, issue = classification_by_identity.get(
                    row.instrument, ("unknown", "CATALOG_CLASSIFICATION_UNAVAILABLE")
                )
                assessments.append(
                    ContractAssessment(
                        product=product,
                        instrument_id=row.instrument.instrument_id,
                        status="OUT_OF_SCOPE" if classification == "future" else (
                            "PARTIAL" if classification == "unknown" else "EXCLUDED"
                        ),
                        reason=issue,
                        expiry_date=row.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=row.asset_type.value,
                        is_trading=row.is_trading,
                        contract_kind=row.contract_kind.value,
                    )
                )
            continue
        if product_id in no_listed_ids:
            selections.append(
                ProductSelection(
                    product=product,
                    in_target_pool=False,
                    status="EXCLUDED",
                    expected_prior_trading_day=None,
                    ranking_trading_day=day_by_venue.get(product.exchange_id),
                    selected_instrument_id=None,
                    ranked_instrument_ids=(),
                    excluded_instrument_ids=(),
                    blockers=(),
                    exclusion_reason=EXCLUSION_REASON_NO_LISTED_CONTRACTS,
                )
            )
            market_coverage.append(
                MainContractMarketCoverage(
                    product=product,
                    catalog_instrument_ids=(),
                    expected_quote_instrument_ids=(),
                    observed_quote_instrument_ids=(),
                )
            )
            continue

        current_day = day_by_venue.get(product.exchange_id)
        if current_day is not None:
            day_references[product.exchange_id] = TradingDayReference(
                product.exchange_id, current_day, None
            )
        calendar, calendar_blockers = _calendar_for(product, calendar_index, decision_at)
        if calendar is not None and not calendar_blockers:
            used_calendars[product.exchange_id] = _calendar_evidence(calendar)
        product_blockers = list(source_blockers)
        if product_id in product_scope_blockers:
            product_blockers.append(product_scope_blockers[product_id])
        product_blockers.extend(calendar_blockers)
        if current_day is None:
            product_blockers.append("CURRENT_TRADING_DAY_UNAVAILABLE")
        if not records:
            product_blockers.append("PRODUCT_CATALOG_COVERAGE_UNAVAILABLE")

        catalog_ids = tuple(sorted(row.instrument.instrument_id for row in records))
        expected_quote_ids = tuple(sorted(set(expected_by_product.get(product_id, ()))))
        observed_quote_ids = tuple(
            sorted(
                quote.instrument.instrument_id
                for quote in quote_rows
                if type(quote) is sdk["FuturesQuoteRecord"]
                and quote.instrument in catalog_by_identity
                and _key_order(
                    ProductKey(
                        catalog_by_identity[quote.instrument][0].product.venue,
                        catalog_by_identity[quote.instrument][0].product.product_id,
                    )
                )
                == product_id
            )
        )
        market_coverage.append(
            MainContractMarketCoverage(
                product=product,
                catalog_instrument_ids=catalog_ids,
                expected_quote_instrument_ids=expected_quote_ids,
                observed_quote_instrument_ids=observed_quote_ids,
            )
        )

        eligible = []
        group_assessments = []
        for catalog_row in records:
            classification, issue = classification_by_identity.get(
                catalog_row.instrument, ("unknown", "CATALOG_CLASSIFICATION_UNAVAILABLE")
            )
            if classification == "unknown":
                product_blockers.append(issue or "CATALOG_CLASSIFICATION_UNAVAILABLE")
                group_assessments.append(
                    ContractAssessment(
                        product=product,
                        instrument_id=catalog_row.instrument.instrument_id,
                        status="PARTIAL",
                        reason=issue,
                        expiry_date=catalog_row.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=catalog_row.asset_type.value,
                        is_trading=catalog_row.is_trading,
                        contract_kind=catalog_row.contract_kind.value,
                    )
                )
                continue
            if classification != "future":
                group_assessments.append(
                    ContractAssessment(
                        product=product,
                        instrument_id=catalog_row.instrument.instrument_id,
                        status="EXCLUDED",
                        reason=issue or "NOT_ORDINARY_FUTURE",
                        expiry_date=catalog_row.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=catalog_row.asset_type.value,
                        is_trading=catalog_row.is_trading,
                        contract_kind=catalog_row.contract_kind.value,
                    )
                )
                continue
            matching = quote_by_identity.get(catalog_row.instrument, ())
            quote = matching[0] if len(matching) == 1 else None
            if quote is None:
                product_blockers.append("QUOTE_ROW_MISSING_FOR_CANDIDATE")
                group_assessments.append(
                    ContractAssessment(
                        product=product,
                        instrument_id=catalog_row.instrument.instrument_id,
                        status="PARTIAL",
                        reason="QUOTE_ROW_MISSING_FOR_CANDIDATE",
                        expiry_date=catalog_row.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=catalog_row.asset_type.value,
                        is_trading=catalog_row.is_trading,
                        contract_kind=catalog_row.contract_kind.value,
                    )
                )
                continue
            quantity_unit = sdk["FuturesQuantityUnit"]
            if (
                type(quote.open_interest_unit) is not quantity_unit
                or type(quote.volume_unit) is not quantity_unit
                or quote.open_interest_unit is not quantity_unit.CONTRACTS
                or quote.volume_unit is not quantity_unit.CONTRACTS
            ):
                product_blockers.append("RANKING_QUANTITY_UNIT_UNAVAILABLE")
                group_assessments.append(
                    ContractAssessment(
                        product=product,
                        instrument_id=catalog_row.instrument.instrument_id,
                        status="PARTIAL",
                        reason="RANKING_QUANTITY_UNIT_UNAVAILABLE",
                        expiry_date=catalog_row.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=catalog_row.asset_type.value,
                        is_trading=catalog_row.is_trading,
                        contract_kind=catalog_row.contract_kind.value,
                        quote_trading_day=quote.trading_day,
                        provider_event_date=quote.provider_event_date,
                        provider_event_time=quote.provider_event_time,
                        provider_event_millisecond=quote.provider_event_millisecond,
                    )
                )
                continue
            volume_semantics = sdk["FuturesVolumeSemantics"]
            if (
                type(quote.volume_semantics) is not volume_semantics
                or quote.volume_semantics is not volume_semantics.CUMULATIVE_TRADING_DAY
            ):
                product_blockers.append("RANKING_VOLUME_SEMANTICS_UNAVAILABLE")
                group_assessments.append(
                    ContractAssessment(
                        product=product,
                        instrument_id=catalog_row.instrument.instrument_id,
                        status="PARTIAL",
                        reason="RANKING_VOLUME_SEMANTICS_UNAVAILABLE",
                        expiry_date=catalog_row.expiry_date,
                        trading_days_to_expiry=None,
                        open_interest=None,
                        volume=None,
                        rank=None,
                        asset_type=catalog_row.asset_type.value,
                        is_trading=catalog_row.is_trading,
                        contract_kind=catalog_row.contract_kind.value,
                        quote_trading_day=quote.trading_day,
                        provider_event_date=quote.provider_event_date,
                        provider_event_time=quote.provider_event_time,
                        provider_event_millisecond=quote.provider_event_millisecond,
                        volume_semantics=getattr(quote.volume_semantics, "value", None),
                    )
                )
                continue
            ranking_record = FuturesContractRecord(
                product=product,
                instrument_id=catalog_row.instrument.instrument_id,
                asset_type="future",
                is_trading=catalog_row.is_trading,
                expiry_date=catalog_row.expiry_date,
                open_interest=quote.open_interest,
                volume=quote.volume,
            )
            assessment, is_eligible = _candidate_assessment(
                ranking_record,
                current_trading_day=current_day,
                calendar=calendar if not calendar_blockers else None,
                policy=policy,
                suppress_source_values=False,
                exact_metric_limit=True,
                require_month_contract=False,
            )
            assessment = replace(
                assessment,
                asset_type=catalog_row.asset_type.value,
                is_trading=catalog_row.is_trading,
                contract_kind=catalog_row.contract_kind.value,
                quote_trading_day=quote.trading_day,
                provider_event_date=quote.provider_event_date,
                provider_event_time=quote.provider_event_time,
                provider_event_millisecond=quote.provider_event_millisecond,
                volume_semantics=quote.volume_semantics.value,
            )
            score = None
            if is_eligible:
                oi = _number_as_decimal(quote.open_interest)
                volume = _number_as_decimal(quote.volume)
                score = (
                    _exact_equal_weight_score(oi, volume)
                    if oi is not None and volume is not None
                    else None
                )
                if score is None:
                    is_eligible = False
                    assessment = replace(
                        assessment,
                        status="BLOCKED",
                        reason="RANKING_VALUE_RANGE_UNSUPPORTED",
                        open_interest=None,
                        volume=None,
                    )
                else:
                    assessment = replace(assessment, ranking_score=_decimal_text(score))
            if assessment.status == "BLOCKED" and assessment.reason:
                product_blockers.append(assessment.reason)
            if is_eligible:
                eligible.append((catalog_row, assessment, score))
            group_assessments.append(assessment)

        product_blockers = list(dict.fromkeys(product_blockers))
        partial_reasons = {
            "CATALOG_CLASSIFICATION_UNAVAILABLE",
            "CATALOG_CLASSIFICATION_TYPE_INVALID",
            "CATALOG_FUTURES_CLASSIFICATION_CONFLICT",
            "QUOTE_ROW_MISSING_FOR_CANDIDATE",
            "RANKING_QUANTITY_UNIT_UNAVAILABLE",
            "RANKING_VOLUME_SEMANTICS_UNAVAILABLE",
            "CATALOG_TRADING_STATUS_UNAVAILABLE",
            "PRODUCT_CATALOG_COVERAGE_UNAVAILABLE",
            "TARGET_PRODUCT_OUTSIDE_REQUEST_SCOPE",
            "ASSET_TYPE_UNKNOWN",
            "TRADING_STATUS_UNKNOWN",
            "EXPIRY_UNAVAILABLE",
            "EXPIRY_CALENDAR_UNAVAILABLE",
            "EXPIRY_SAFETY_UNPROVEN",
            "RANKING_VALUE_MISSING_OR_INVALID",
            "RANKING_VALUE_RANGE_UNSUPPORTED",
            "EXCHANGE_CALENDAR_UNAVAILABLE",
            "EXCHANGE_CALENDAR_INCOMPLETE",
            "CALENDAR_NOT_AVAILABLE_AT_DECISION",
            "CALENDAR_RETRIEVED_AFTER_DECISION",
        }
        is_partial = bool(source_blockers) or any(
            item in partial_reasons
            or item.startswith(
                (
                    "SESSION_",
                    "MARKET_SNAPSHOT_",
                    "CATALOG_COVERAGE_",
                    "QUOTE_COVERAGE_",
                    "CALENDAR_",
                    "EXCHANGE_CALENDAR_",
                )
            )
            for item in product_blockers
        )
        if is_partial:
            assessments.extend(
                replace(item, status="PARTIAL", rank=None)
                if item.status == "ELIGIBLE"
                else item
                for item in group_assessments
            )
            selections.append(
                ProductSelection(
                    product=product,
                    in_target_pool=True,
                    status="PARTIAL",
                    expected_prior_trading_day=None,
                    ranking_trading_day=current_day,
                    selected_instrument_id=None,
                    ranked_instrument_ids=tuple(
                        row.instrument.instrument_id for row, _assessment, _score in eligible
                    ),
                    excluded_instrument_ids=tuple(
                        item.instrument_id for item in group_assessments if item.status == "EXCLUDED"
                    ),
                    blockers=tuple(product_blockers or ("MARKET_SNAPSHOT_COVERAGE_INCOMPLETE",)),
                )
            )
            continue
        if product_blockers or not eligible:
            if not product_blockers:
                product_blockers.append("NO_ELIGIBLE_FUTURES_CONTRACTS")
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
                        item.instrument_id for item in group_assessments if item.status == "EXCLUDED"
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
                item[0].instrument.instrument_id,
            ),
        )
        rank_by_id = {
            item[0].instrument.instrument_id: index for index, item in enumerate(ranked, 1)
        }
        score_by_id = {
            item[0].instrument.instrument_id: _decimal_text(item[2]) for item in ranked
        }
        assessments.extend(
            replace(
                assessment,
                status="RANKED",
                reason=None,
                rank=rank_by_id[assessment.instrument_id],
                ranking_score=score_by_id[assessment.instrument_id],
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
                selected_instrument_id=ranked[0][0].instrument.instrument_id,
                ranked_instrument_ids=tuple(
                    item[0].instrument.instrument_id for item in ranked
                ),
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
    manifest_blockers = list(source_blockers)
    manifest_blockers.extend(reason for item in target_selections for reason in item.blockers)
    if not narrowed_targets:
        manifest_blockers.append("TARGET_PRODUCT_POOL_EMPTY")
    manifest_blockers = list(dict.fromkeys(manifest_blockers))
    has_partial = bool(source_blockers) or any(item.status == "PARTIAL" for item in target_selections)
    status = (
        "PARTIAL"
        if has_partial
        else "READY"
        if narrowed_targets and all(item.status == "READY" for item in target_selections)
        else "BLOCKED"
    )
    return MainContractManifest(
        status=status,
        decision_at=decision_at,
        policy=policy,
        target_products=narrowed_targets,
        **_market_snapshot_source_fields(snapshot, sdk),
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
        market_coverage=tuple(
            sorted(market_coverage, key=lambda item: _key_order(item.product))
        ),
        market_snapshot_evidence_json=_market_snapshot_json(snapshot, sdk),
    )


def _select_futures_market_snapshot(
    snapshot: Any,
    expected_products: Sequence[ProductKey],
    calendars: Sequence[ExchangeTradingCalendar],
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    snapshot_lease: Any,
    snapshot_facade: Any,
) -> MainContractManifest:
    sdk = _futures_market_sdk_types()
    if sdk is None:
        return _neutral_partial_manifest(
            None,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("FUTURES_MARKET_SDK_CONTRACT_UNAVAILABLE",),
            sdk=None,
        )
    if snapshot is None:
        return _neutral_partial_manifest(
            None,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("MARKET_SNAPSHOT_UNAVAILABLE",),
            sdk=sdk,
        )
    if type(snapshot) is not sdk["FuturesMarketSnapshot"]:
        return _neutral_partial_manifest(
            None,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("MARKET_SNAPSHOT_TYPE_INVALID",),
            sdk=sdk,
        )
    if (
        type(snapshot_lease) is not sdk["QuerySnapshotLease"]
        or type(snapshot_facade) is not sdk["FuturesMarketSnapshotFacade"]
    ):
        return _neutral_partial_manifest(
            snapshot,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("MARKET_SNAPSHOT_LEASE_UNAVAILABLE",),
            sdk=sdk,
        )
    try:
        lease_before = snapshot_facade.validate_lease(
            snapshot, snapshot_lease, now=datetime.now(timezone.utc)
        )
    except Exception:
        lease_before = False
    if lease_before is not True:
        return _neutral_partial_manifest(
            snapshot,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("MARKET_SNAPSHOT_LEASE_INVALID_BEFORE_SELECTION",),
            sdk=sdk,
        )
    try:
        manifest = _select_futures_market_snapshot_rows(
            snapshot,
            expected_products,
            calendars,
            decision_at=decision_at,
            policy=policy,
            sdk=sdk,
        )
    except Exception:
        manifest = _neutral_partial_manifest(
            snapshot,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("MARKET_SNAPSHOT_PROJECTION_INVALID",),
            sdk=sdk,
        )
    try:
        lease_after = snapshot_facade.validate_lease(
            snapshot, snapshot_lease, now=datetime.now(timezone.utc)
        )
    except Exception:
        lease_after = False
    if lease_after is not True:
        return _neutral_partial_manifest(
            snapshot,
            expected_products,
            decision_at=decision_at,
            policy=policy,
            blockers=("MARKET_SNAPSHOT_LEASE_INVALID_AFTER_SELECTION",),
            sdk=sdk,
        )
    return manifest


def select_main_contracts(
    snapshot: Optional[Any],
    expected_products: Sequence[ProductKey],
    current_trading_days: Sequence[ExchangeTradingDay],
    calendars: Sequence[ExchangeTradingCalendar],
    *,
    decision_at: datetime,
    policy: MainContractPolicy = DEFAULT_MAIN_CONTRACT_POLICY,
    snapshot_lease: Any = None,
    snapshot_facade: Any = None,
) -> MainContractManifest:
    """Select one future per target product, fail-closed.

    The input pool is product identities only, never contract IDs.  The
    legacy policy requires finalized latest prior-day rankings.  The explicit
    provider-neutral market snapshot policy consumes only exact SDK catalog,
    session, and quote DTOs. It uses each venue's own session trading day and
    requires the exact snapshot lease to validate before and after selection.
    Quote event timestamps are audit fields; they do not establish freshness.
    """

    _aware_datetime(decision_at, "decision_at")
    if not isinstance(policy, MainContractPolicy):
        raise ValueError("policy must be a MainContractPolicy")
    if policy.ranking_mode == RANKING_MODE_FUTURES_MARKET_SNAPSHOT:
        return _select_futures_market_snapshot(
            snapshot,
            expected_products,
            calendars,
            decision_at=decision_at,
            policy=policy,
            snapshot_lease=snapshot_lease,
            snapshot_facade=snapshot_facade,
        )
    if snapshot is not None and not isinstance(snapshot, MainContractRankingSnapshot):
        raise ValueError("snapshot must be MainContractRankingSnapshot or None")
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
    "EXCLUSION_REASON_NO_LISTED_CONTRACTS",
    "CalendarEvidence",
    "ContractAssessment",
    "DEFAULT_MAIN_CONTRACT_POLICY",
    "ExchangeTradingCalendar",
    "ExchangeTradingDay",
    "FuturesContractRecord",
    "FUTURES_MARKET_SNAPSHOT_EQUAL_WEIGHT_POLICY",
    "LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_POLICY",
    "LEGACY_PREVIOUS_COMPLETE_DAY_EOD_OI_V1",
    "MainContractBinding",
    "MainContractManifest",
    "MainContractMarketCoverage",
    "MainContractPolicy",
    "MainContractRankingSnapshot",
    "MainContractRolloverPlan",
    "MainContractSelectionBlocked",
    "ProductKey",
    "ProductRankingCoverage",
    "ProductSelection",
    "RANKING_MODE_FUTURES_MARKET_SNAPSHOT",
    "RANKING_MODE_LEGACY_PRIOR_DAY_OI",
    "RolloverBoundaryEvidence",
    "RolloverAuthorization",
    "RolloverReadiness",
    "TradingCalendarContractError",
    "TradingDayReference",
    "authorize_main_contract_rollover",
    "plan_main_contract_rollover",
    "select_main_contracts",
]
