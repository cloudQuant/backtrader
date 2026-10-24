"""Point-in-time futures main-contract selection and rollover contracts.

This module contains only deterministic policy and evidence types.  It does
not query a broker, choose a data provider, or send orders.  A source adapter
must supply a complete candidate inventory and complete, finalized rankings
from the previous trading day before this selector can produce an executable
mapping.

The default policy ranks actual monthly futures by prior-day open interest,
then volume, then expiry date, then the provider's exact InstrumentID.  The
InstrumentID is retained verbatim for routing; only exchange/product keys are
canonicalized for comparisons.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence, Tuple


_SOURCE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONTH_CONTRACT = re.compile(r"^[A-Za-z]{1,8}([0-9]{3,4})$")
_KNOWN_NON_FUTURES = frozenset(
    {"option", "options", "combination", "spot", "efp", "spot_option", "tas", "index"}
)


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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exchange_id", _identity_text(self.exchange_id, "exchange_id").upper()
        )
        object.__setattr__(self, "source_id", _identity_text(self.source_id, "calendar source_id"))
        object.__setattr__(self, "version", _identity_text(self.version, "calendar version"))
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
        return _canonical_json_sha256(
            {
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
        )

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

    def __post_init__(self) -> None:
        _identity_text(self.policy_id, "policy_id")
        if (
            type(self.minimum_trading_days_to_expiry) is not int
            or self.minimum_trading_days_to_expiry < 0
        ):
            raise ValueError("minimum_trading_days_to_expiry must be a non-negative int")


DEFAULT_MAIN_CONTRACT_POLICY = MainContractPolicy()


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

        return {
            "schema": "backtrader.futures_main_contract_manifest.v1",
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
                }
                for item in self.candidates
            ],
            "blockers": list(self.blockers),
        }

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


def select_main_contracts(
    snapshot: Optional[MainContractRankingSnapshot],
    expected_products: Sequence[ProductKey],
    current_trading_days: Sequence[ExchangeTradingDay],
    calendars: Sequence[ExchangeTradingCalendar],
    *,
    decision_at: datetime,
    policy: MainContractPolicy = DEFAULT_MAIN_CONTRACT_POLICY,
) -> MainContractManifest:
    """Select one actual monthly future per target product, fail-closed.

    The input pool is product identities only, never contract IDs.  Every
    target requires a complete inventory, finalized latest prior-day rankings,
    source availability no later than ``decision_at``, and an available
    exchange calendar covering the expiry decision.  Any blocked target keeps
    the complete manifest non-executable; no smaller partial mapping is
    exposed through :meth:`MainContractManifest.selected_mapping`.
    """

    _aware_datetime(decision_at, "decision_at")
    if not isinstance(policy, MainContractPolicy):
        raise ValueError("policy must be a MainContractPolicy")
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
    "CalendarEvidence",
    "ContractAssessment",
    "DEFAULT_MAIN_CONTRACT_POLICY",
    "ExchangeTradingCalendar",
    "ExchangeTradingDay",
    "FuturesContractRecord",
    "MainContractBinding",
    "MainContractManifest",
    "MainContractPolicy",
    "MainContractRankingSnapshot",
    "MainContractRolloverPlan",
    "MainContractSelectionBlocked",
    "ProductKey",
    "ProductRankingCoverage",
    "ProductSelection",
    "RolloverBoundaryEvidence",
    "RolloverAuthorization",
    "RolloverReadiness",
    "TradingCalendarContractError",
    "TradingDayReference",
    "authorize_main_contract_rollover",
    "plan_main_contract_rollover",
    "select_main_contracts",
]
