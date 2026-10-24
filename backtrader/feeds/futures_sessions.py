"""Source-backed futures sessions and deterministic shared-minute grids.

This module deliberately does not infer an exchange calendar from weekdays,
derive product hours from a product-code heuristic, fetch a source, or inspect
arriving bars.  A source adapter must provide explicit exchange TradingDays
and an explicit product/session row for every requested product/day pair.
Only then can the pure planner publish common one-minute close times.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .futures_main_contract import ExchangeTradingCalendar, ProductKey


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHINA_OFFSET = timedelta(hours=8)
_ONE_MINUTE = timedelta(minutes=1)
_MAX_TARGET_PRODUCTS = 2_000
_MAX_EXCHANGE_CALENDARS = 6
_MAX_CALENDAR_DAYS = 10_000
_MAX_PRODUCT_DAY_ROWS = 100_000
_MAX_PRODUCT_DAYS_PER_TARGET = 10_000
_MAX_TOTAL_REQUESTED_PRODUCT_DAYS = 100_000
_MAX_SOURCES_PER_CALENDAR = 10_000
_MAX_WINDOWS_PER_PRODUCT_DAY = 16
_MAX_WINDOWS_PER_CALENDAR = 300_000
_MAX_EXPANDED_PRODUCT_MINUTES = 1_000_000
_MAX_STREAM_WINDOWS = 300_000
_MAX_STREAM_PRODUCT_MINUTES = 20_000_000
_MAX_STREAM_COMMON_MINUTES = 1_000_000
_MAX_STREAM_CHUNK_MEMBER_RECORDS = 65_536
_MAX_ROLLING_WINDOW_MINUTES = 4_096
_MAX_SESSION_DURATION = timedelta(hours=24)


class SessionCalendarError(ValueError):
    """Raised when public calendar/session facts cannot prove the requested grid."""

    def __init__(self, code: str, detail: Optional[str] = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else "{}: {}".format(code, detail))


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("{} must be non-empty trimmed text".format(name))
    return value


def _day(value: Any, name: str) -> date:
    if type(value) is not date:
        raise ValueError("{} must be a date, not a datetime".format(name))
    return value


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(name))
    return value


def _url(value: Any, name: str) -> str:
    value = _text(value, name)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("{} must be an HTTPS URL".format(name))
    return value


def _sha256(value: Any, name: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError("{} must be lowercase SHA-256 hex".format(name))
    return value


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bounded_sequence(value: Any, name: str, limit: int) -> Tuple[Any, ...]:
    """Materialize a small explicit sequence only after checking its size."""

    if not isinstance(value, Sequence):
        raise SessionCalendarError("INPUT_SEQUENCE_INVALID", name)
    if len(value) > limit:
        raise SessionCalendarError("INPUT_LIMIT_EXCEEDED", name)
    return tuple(value)


def _iso_date(value: Any, name: str) -> date:
    if type(value) is not str:
        raise ValueError("{} must be an ISO date string".format(name))
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("{} must be an ISO date string".format(name)) from None
    if parsed.isoformat() != value:
        raise ValueError("{} must be an ISO date string".format(name))
    return parsed


def _iso_datetime(value: Any, name: str) -> datetime:
    if type(value) is not str:
        raise ValueError("{} must be an ISO timestamp string".format(name))
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise ValueError("{} must be an ISO timestamp string".format(name)) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(name))
    return parsed


def _product_order(product: ProductKey) -> Tuple[str, str]:
    return product.exchange_id, product.product_id


@dataclass(frozen=True)
class PublicSourceEvidence:
    """One public source observation used to build a normalized schedule.

    ``sha256`` is the digest of the exact response/document bytes captured by
    the adapter.  ``available_at`` is when the source facts became public;
    ``retrieved_at`` is when those exact bytes were obtained.  If a historic
    publication time cannot be established, adapters should conservatively
    set ``available_at`` to ``retrieved_at``.
    """

    source_id: str
    source_url: str
    version: str
    available_at: datetime
    retrieved_at: datetime
    sha256: str

    def __post_init__(self) -> None:
        _text(self.source_id, "source_id")
        _url(self.source_url, "source_url")
        _text(self.version, "version")
        available = _aware(self.available_at, "available_at")
        retrieved = _aware(self.retrieved_at, "retrieved_at")
        if retrieved.astimezone(timezone.utc) < available.astimezone(timezone.utc):
            raise ValueError("retrieved_at precedes available_at")
        _sha256(self.sha256, "sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "version": self.version,
            "available_at": _utc(self.available_at),
            "retrieved_at": _utc(self.retrieved_at),
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class SessionWindow:
    """An explicit continuous trading interval for one product TradingDay.

    Timestamps are exchange wall-clock instants with the China UTC+08:00
    offset.  Session dates remain explicit so a night segment can be labeled
    with its actual ActionDay while belonging to the following TradingDay.
    Windows are continuous matching intervals only; call auctions are not
    minute-bar trading windows.
    """

    session_id: str
    session_date: date
    start: datetime
    end: datetime
    source_id: str

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id")
        _day(self.session_date, "session_date")
        start = _aware(self.start, "session start")
        end = _aware(self.end, "session end")
        if start.utcoffset() != _CHINA_OFFSET or end.utcoffset() != _CHINA_OFFSET:
            raise ValueError("session timestamps must use the China UTC+08:00 offset")
        if start.second or start.microsecond or end.second or end.microsecond:
            raise ValueError("session boundaries must align to whole minutes")
        if end <= start:
            raise ValueError("session end must follow session start")
        duration = end - start
        if duration % _ONE_MINUTE:
            raise ValueError("session duration must contain whole minutes")
        if duration > _MAX_SESSION_DURATION or (end.date() - start.date()).days > 1:
            raise ValueError(
                "session window must be no longer than 24 hours or cross midnight once"
            )
        if start.date() != self.session_date:
            raise ValueError("session_date must equal the local start date")
        _text(self.source_id, "session source_id")


@dataclass(frozen=True)
class ProductTradingDaySessions:
    """The complete explicit session fact for one product and TradingDay."""

    product: ProductKey
    trading_day: date
    source_id: str
    windows: Tuple[SessionWindow, ...]
    closed_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.product, ProductKey):
            raise ValueError("product must be ProductKey")
        _day(self.trading_day, "trading_day")
        _text(self.source_id, "product-day source_id")
        windows = _bounded_sequence(
            self.windows, "product-day windows", _MAX_WINDOWS_PER_PRODUCT_DAY
        )
        if any(not isinstance(window, SessionWindow) for window in windows):
            raise ValueError("windows must contain SessionWindow records")
        ids = [window.session_id for window in windows]
        if len(ids) != len(set(ids)):
            raise ValueError("session_id values must be unique within a product TradingDay")
        ordered = tuple(sorted(windows, key=lambda window: window.start))
        for previous, current in zip(ordered, ordered[1:]):
            if current.start < previous.end:
                raise ValueError("product session windows overlap")
        if not windows:
            if self.closed_reason is None:
                raise ValueError("empty session windows require an explicit closed_reason")
            _text(self.closed_reason, "closed_reason")
        elif self.closed_reason is not None:
            raise ValueError("open product TradingDay cannot also have closed_reason")
        object.__setattr__(self, "windows", ordered)


@dataclass(frozen=True)
class ExchangeSessionCalendar:
    """An immutable, source-backed exchange calendar and product schedule.

    ``trading_days`` is an explicit exhaustive sequence over the declared
    range, never a weekday expansion.  ``product_universe`` is the exchange
    product set covered by the official schedule sources.  The grid builder
    still requires a matching schedule row for every requested product/day,
    so ``complete=True`` alone cannot hide missing product rows.
    """

    exchange_id: str
    calendar_source_id: str
    coverage_start: date
    coverage_through: date
    trading_days: Tuple[date, ...]
    product_universe: Tuple[ProductKey, ...]
    product_days: Tuple[ProductTradingDaySessions, ...]
    sources: Tuple[PublicSourceEvidence, ...]
    complete: bool = True

    def __post_init__(self) -> None:
        exchange = _text(self.exchange_id, "exchange_id").upper()
        object.__setattr__(self, "exchange_id", exchange)
        _text(self.calendar_source_id, "calendar_source_id")
        start = _day(self.coverage_start, "coverage_start")
        through = _day(self.coverage_through, "coverage_through")
        if through < start:
            raise ValueError("coverage_through precedes coverage_start")
        days = _bounded_sequence(self.trading_days, "calendar trading_days", _MAX_CALENDAR_DAYS)
        if any(type(item) is not date for item in days):
            raise ValueError("trading_days must contain date values")
        if tuple(sorted(set(days))) != days:
            raise ValueError("trading_days must be unique and ascending")
        if any(day < start or day > through for day in days):
            raise ValueError("trading day lies outside calendar coverage")
        products = _bounded_sequence(
            self.product_universe, "calendar product_universe", _MAX_TARGET_PRODUCTS
        )
        if any(not isinstance(item, ProductKey) for item in products):
            raise ValueError("product_universe must contain ProductKey values")
        if any(item.exchange_id != exchange for item in products):
            raise ValueError("product_universe exchange does not match exchange_id")
        if len(set(products)) != len(products):
            raise ValueError("product_universe contains duplicates")
        products = tuple(sorted(products, key=_product_order))
        rows = _bounded_sequence(self.product_days, "calendar product_days", _MAX_PRODUCT_DAY_ROWS)
        if any(not isinstance(item, ProductTradingDaySessions) for item in rows):
            raise ValueError("product_days must contain ProductTradingDaySessions")
        if sum(len(item.windows) for item in rows) > _MAX_WINDOWS_PER_CALENDAR:
            raise SessionCalendarError("INPUT_LIMIT_EXCEEDED", "calendar session windows")
        row_keys = [(item.product, item.trading_day) for item in rows]
        if len(set(row_keys)) != len(row_keys):
            raise ValueError("product_days contains duplicate product/TradingDay rows")
        if any(item.product not in products for item in rows):
            raise ValueError("product-day row is outside product_universe")
        if any(item.trading_day not in days for item in rows):
            raise ValueError("product-day row is outside explicit trading_days")
        sources = _bounded_sequence(self.sources, "calendar sources", _MAX_SOURCES_PER_CALENDAR)
        if not sources or any(not isinstance(item, PublicSourceEvidence) for item in sources):
            raise ValueError("sources must contain PublicSourceEvidence records")
        source_ids = [item.source_id for item in sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("sources contains duplicate source_id values")
        if self.calendar_source_id not in source_ids:
            raise ValueError("calendar_source_id is missing from sources")
        known_sources = set(source_ids)
        if any(item.source_id not in known_sources for item in rows):
            raise ValueError("product-day row references an unknown source")
        if any(window.source_id not in known_sources for row in rows for window in row.windows):
            raise ValueError("session window references an unknown source")
        if type(self.complete) is not bool:
            raise ValueError("complete must be bool")
        object.__setattr__(self, "trading_days", days)
        object.__setattr__(self, "product_universe", products)
        object.__setattr__(
            self,
            "product_days",
            tuple(sorted(rows, key=lambda r: (_product_order(r.product), r.trading_day))),
        )
        object.__setattr__(self, "sources", tuple(sorted(sources, key=lambda item: item.source_id)))

    @property
    def source_index(self) -> Mapping[str, PublicSourceEvidence]:
        return {item.source_id: item for item in self.sources}

    @property
    def evidence_sha256(self) -> str:
        return _json_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "backtrader.exchange_session_calendar.v1",
            "exchange_id": self.exchange_id,
            "calendar_source_id": self.calendar_source_id,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_through": self.coverage_through.isoformat(),
            "complete": self.complete,
            "trading_days": [day.isoformat() for day in self.trading_days],
            "product_universe": [
                {"exchange_id": item.exchange_id, "product_id": item.product_id}
                for item in self.product_universe
            ],
            "sources": [item.to_dict() for item in self.sources],
            "product_days": [
                {
                    "product": {
                        "exchange_id": item.product.exchange_id,
                        "product_id": item.product.product_id,
                    },
                    "trading_day": item.trading_day.isoformat(),
                    "source_id": item.source_id,
                    "closed_reason": item.closed_reason,
                    "windows": [
                        {
                            "session_id": window.session_id,
                            "session_date": window.session_date.isoformat(),
                            "start": window.start.isoformat(),
                            "end": window.end.isoformat(),
                            "source_id": window.source_id,
                        }
                        for window in item.windows
                    ],
                }
                for item in self.product_days
            ],
        }

    def to_main_contract_calendar(self) -> ExchangeTradingCalendar:
        """Adapt the exact day set to the selector's existing calendar contract."""

        source = self.source_index[self.calendar_source_id]
        return ExchangeTradingCalendar(
            exchange_id=self.exchange_id,
            source_id=source.source_id,
            version=source.version,
            available_at=source.available_at,
            retrieved_at=source.retrieved_at,
            coverage_start=self.coverage_start,
            coverage_through=self.coverage_through,
            trading_days=self.trading_days,
            complete=self.complete,
        )


def load_exchange_session_calendar(document: Mapping[str, Any]) -> ExchangeSessionCalendar:
    """Restore a typed session snapshot from its public JSON representation."""

    if not isinstance(document, Mapping):
        raise SessionCalendarError("SESSION_CALENDAR_MUST_BE_OBJECT")
    if document.get("schema") != "backtrader.exchange_session_calendar.v1":
        raise SessionCalendarError("SESSION_CALENDAR_SCHEMA_UNSUPPORTED")
    source_values = _bounded_sequence(
        document.get("sources", ()), "calendar sources", _MAX_SOURCES_PER_CALENDAR
    )
    product_values = _bounded_sequence(
        document.get("product_universe", ()),
        "calendar product_universe",
        _MAX_TARGET_PRODUCTS,
    )
    row_values = _bounded_sequence(
        document.get("product_days", ()), "calendar product_days", _MAX_PRODUCT_DAY_ROWS
    )
    day_values = _bounded_sequence(
        document.get("trading_days", ()), "calendar trading_days", _MAX_CALENDAR_DAYS
    )
    total_windows = 0
    for value in row_values:
        if not isinstance(value, Mapping):
            raise SessionCalendarError("PRODUCT_DAY_MUST_BE_OBJECT")
        windows = _bounded_sequence(
            value.get("windows", ()),
            "product-day windows",
            _MAX_WINDOWS_PER_PRODUCT_DAY,
        )
        total_windows += len(windows)
        if total_windows > _MAX_WINDOWS_PER_CALENDAR:
            raise SessionCalendarError("INPUT_LIMIT_EXCEEDED", "calendar session windows")

    sources = []
    for value in source_values:
        if not isinstance(value, Mapping):
            raise SessionCalendarError("SESSION_SOURCE_MUST_BE_OBJECT")
        sources.append(
            PublicSourceEvidence(
                source_id=value.get("source_id"),
                source_url=value.get("source_url"),
                version=value.get("version"),
                available_at=_iso_datetime(value.get("available_at"), "available_at"),
                retrieved_at=_iso_datetime(value.get("retrieved_at"), "retrieved_at"),
                sha256=value.get("sha256"),
            )
        )
    products = []
    for value in product_values:
        if not isinstance(value, Mapping):
            raise SessionCalendarError("SESSION_PRODUCT_MUST_BE_OBJECT")
        products.append(
            ProductKey(
                exchange_id=value.get("exchange_id"),
                product_id=value.get("product_id"),
            )
        )
    rows = []
    for value in row_values:
        if not isinstance(value, Mapping):
            raise SessionCalendarError("PRODUCT_DAY_MUST_BE_OBJECT")
        product_row = value.get("product")
        if not isinstance(product_row, Mapping):
            raise SessionCalendarError("PRODUCT_DAY_PRODUCT_MUST_BE_OBJECT")
        windows = []
        for window in value.get("windows", ()):
            if not isinstance(window, Mapping):
                raise SessionCalendarError("SESSION_WINDOW_MUST_BE_OBJECT")
            windows.append(
                SessionWindow(
                    session_id=window.get("session_id"),
                    session_date=_iso_date(window.get("session_date"), "session_date"),
                    start=_iso_datetime(window.get("start"), "session start"),
                    end=_iso_datetime(window.get("end"), "session end"),
                    source_id=window.get("source_id"),
                )
            )
        rows.append(
            ProductTradingDaySessions(
                product=ProductKey(
                    exchange_id=product_row.get("exchange_id"),
                    product_id=product_row.get("product_id"),
                ),
                trading_day=_iso_date(value.get("trading_day"), "trading_day"),
                source_id=value.get("source_id"),
                windows=tuple(windows),
                closed_reason=value.get("closed_reason"),
            )
        )
    complete = document.get("complete")
    if type(complete) is not bool:
        raise SessionCalendarError("SESSION_CALENDAR_COMPLETE_INVALID")
    return ExchangeSessionCalendar(
        exchange_id=document.get("exchange_id"),
        calendar_source_id=document.get("calendar_source_id"),
        coverage_start=_iso_date(document.get("coverage_start"), "coverage_start"),
        coverage_through=_iso_date(document.get("coverage_through"), "coverage_through"),
        trading_days=tuple(_iso_date(value, "trading_day") for value in day_values),
        product_universe=tuple(products),
        product_days=tuple(rows),
        sources=tuple(sources),
        complete=complete,
    )


@dataclass(frozen=True)
class SessionSlotEvidence:
    product: ProductKey
    trading_day: date
    session_date: date
    action_day: date
    session_id: str


@dataclass(frozen=True)
class PlannedCommonMinute:
    """One common minute close with per-feed TradingDay/ActionDay provenance."""

    close_time: datetime
    members: Tuple[SessionSlotEvidence, ...]


@dataclass(frozen=True)
class CommonMinuteGrid:
    status: str
    decision_at: datetime
    target_products: Tuple[ProductKey, ...]
    product_trading_days: Tuple[Tuple[ProductKey, Tuple[date, ...]], ...]
    calendar_hashes: Tuple[Tuple[str, str], ...]
    minutes: Tuple[PlannedCommonMinute, ...]

    def __post_init__(self) -> None:
        if self.status not in ("READY", "NO_COMMON_TRADING_MINUTES"):
            raise ValueError("unsupported common-grid status")
        _aware(self.decision_at, "decision_at")
        products = _bounded_sequence(
            self.target_products, "grid target_products", _MAX_TARGET_PRODUCTS
        )
        minutes = _bounded_sequence(self.minutes, "grid minutes", _MAX_EXPANDED_PRODUCT_MINUTES)
        if not products or any(not isinstance(product, ProductKey) for product in products):
            raise ValueError("grid target_products must contain ProductKey values")
        if len(set(products)) != len(products):
            raise ValueError("grid target_products contains duplicates")
        previous_close = None
        if any(not isinstance(minute, PlannedCommonMinute) for minute in minutes):
            raise ValueError("grid minutes must contain PlannedCommonMinute records")
        for minute in minutes:
            close = _aware(minute.close_time, "planned close")
            if close.utcoffset() != timedelta(0):
                raise ValueError("planned closes must be normalized to UTC")
            if previous_close is not None and close <= previous_close:
                raise ValueError("planned closes must be unique and ascending")
            previous_close = close
        if (self.status == "READY") != bool(minutes):
            raise ValueError("grid status does not match minute coverage")
        object.__setattr__(self, "target_products", products)
        object.__setattr__(self, "minutes", minutes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "backtrader.futures_common_minute_grid.v1",
            "status": self.status,
            "decision_at": _utc(self.decision_at),
            "target_products": [
                {"exchange_id": product.exchange_id, "product_id": product.product_id}
                for product in self.target_products
            ],
            "product_trading_days": [
                {
                    "product": {
                        "exchange_id": product.exchange_id,
                        "product_id": product.product_id,
                    },
                    "trading_days": [day.isoformat() for day in days],
                }
                for product, days in self.product_trading_days
            ],
            "calendar_hashes": [
                {"exchange_id": exchange_id, "sha256": digest}
                for exchange_id, digest in self.calendar_hashes
            ],
            "minutes": [
                {
                    "close_time": _utc(minute.close_time),
                    "members": [
                        {
                            "product": {
                                "exchange_id": member.product.exchange_id,
                                "product_id": member.product.product_id,
                            },
                            "trading_day": member.trading_day.isoformat(),
                            "session_date": member.session_date.isoformat(),
                            "action_day": member.action_day.isoformat(),
                            "session_id": member.session_id,
                        }
                        for member in minute.members
                    ],
                }
                for minute in self.minutes
            ],
        }


def _requested_days(
    target_products: Tuple[ProductKey, ...],
    product_trading_days: Mapping[ProductKey, Sequence[date]],
) -> Tuple[Tuple[ProductKey, Tuple[date, ...]], ...]:
    if not isinstance(product_trading_days, Mapping):
        raise ValueError("product_trading_days must be a mapping")
    if len(product_trading_days) > _MAX_TARGET_PRODUCTS:
        raise SessionCalendarError("INPUT_LIMIT_EXCEEDED", "product_trading_days keys")
    if set(product_trading_days) != set(target_products):
        raise SessionCalendarError("TARGET_TRADING_DAY_KEYS_MISMATCH")
    result = []
    total_days = 0
    for product in target_products:
        days = _bounded_sequence(
            product_trading_days[product],
            "TradingDays for {}.{}".format(product.exchange_id, product.product_id),
            _MAX_PRODUCT_DAYS_PER_TARGET,
        )
        total_days += len(days)
        if total_days > _MAX_TOTAL_REQUESTED_PRODUCT_DAYS:
            raise SessionCalendarError(
                "INPUT_LIMIT_EXCEEDED", "total requested product TradingDays"
            )
        if not days or any(type(day) is not date for day in days):
            raise ValueError("each target product needs one or more date TradingDays")
        if tuple(sorted(set(days))) != days:
            raise ValueError("product TradingDays must be unique and ascending")
        result.append((product, days))
    return tuple(result)


def _minute_slots(row: ProductTradingDaySessions) -> Dict[datetime, SessionSlotEvidence]:
    slots: Dict[datetime, SessionSlotEvidence] = {}
    for window in row.windows:
        cursor = window.start
        while cursor < window.end:
            close_local = cursor + _ONE_MINUTE
            close_utc = close_local.astimezone(timezone.utc)
            if close_utc in slots:
                raise SessionCalendarError("PRODUCT_MINUTE_SLOT_AMBIGUOUS")
            slots[close_utc] = SessionSlotEvidence(
                product=row.product,
                trading_day=row.trading_day,
                session_date=window.session_date,
                action_day=close_local.date(),
                session_id=window.session_id,
            )
            cursor = close_local
    return slots


def build_common_minute_grid(
    target_products: Sequence[ProductKey],
    calendars: Sequence[ExchangeSessionCalendar],
    product_trading_days: Mapping[ProductKey, Sequence[date]],
    *,
    decision_at: datetime,
) -> CommonMinuteGrid:
    """Build the exact whole-group minute-close intersection.

    The product set is supplied by the caller from the full selected cohort;
    every member must be covered.  The planner never shrinks that set, makes
    a weekday calendar, forward-fills a price, or intersects observed bars.
    ``product_trading_days`` can preserve different exchange TradingDay labels
    for the same UTC grid interval.
    """

    decision = _aware(decision_at, "decision_at")
    products = _bounded_sequence(target_products, "target_products", _MAX_TARGET_PRODUCTS)
    if not products or any(not isinstance(item, ProductKey) for item in products):
        raise ValueError("target_products must contain at least one ProductKey")
    if len(set(products)) != len(products):
        raise ValueError("target_products contains duplicates")
    requested = _requested_days(products, product_trading_days)
    requested_by_product = dict(requested)

    exchange_index: Dict[str, ExchangeSessionCalendar] = {}
    calendar_values = _bounded_sequence(calendars, "calendars", _MAX_EXCHANGE_CALENDARS)
    for calendar in calendar_values:
        if not isinstance(calendar, ExchangeSessionCalendar):
            raise ValueError("calendars must contain ExchangeSessionCalendar records")
        if calendar.exchange_id in exchange_index:
            raise ValueError("calendars contains duplicate exchange_id")
        exchange_index[calendar.exchange_id] = calendar

    target_exchanges = {product.exchange_id for product in products}
    selected_calendars: Dict[str, ExchangeSessionCalendar] = {}
    for exchange_id in target_exchanges:
        calendar = exchange_index.get(exchange_id)
        if calendar is None:
            raise SessionCalendarError("EXCHANGE_CALENDAR_MISSING", exchange_id)
        if not calendar.complete:
            raise SessionCalendarError("EXCHANGE_CALENDAR_INCOMPLETE", exchange_id)
        selected_calendars[exchange_id] = calendar

    target_product_set = set(products)
    rows_by_target_product: Dict[ProductKey, Dict[date, ProductTradingDaySessions]] = {
        product: {} for product in products
    }
    source_indexes = {}
    for exchange_id, calendar in selected_calendars.items():
        source_indexes[exchange_id] = calendar.source_index
        for row in calendar.product_days:
            if row.product in target_product_set:
                rows_by_target_product[row.product][row.trading_day] = row

    rows_by_product: Dict[ProductKey, Dict[date, ProductTradingDaySessions]] = {}
    total_expansion = 0
    for product in products:
        calendar = selected_calendars[product.exchange_id]
        if product not in calendar.product_universe:
            raise SessionCalendarError(
                "PRODUCT_SESSION_UNIVERSE_MISSING",
                "{}.{}".format(product.exchange_id, product.product_id),
            )
        source_index = source_indexes[product.exchange_id]
        source_ids_needed = {calendar.calendar_source_id}
        rows_by_day = rows_by_target_product[product]
        selected_rows = {}
        for trading_day in requested_by_product[product]:
            if trading_day < calendar.coverage_start or trading_day > calendar.coverage_through:
                raise SessionCalendarError(
                    "TRADING_DAY_OUTSIDE_COVERAGE",
                    "{}.{} {}".format(product.exchange_id, product.product_id, trading_day),
                )
            if trading_day not in calendar.trading_days:
                raise SessionCalendarError(
                    "TRADING_DAY_NOT_IN_SOURCE_CALENDAR",
                    "{}.{} {}".format(product.exchange_id, product.product_id, trading_day),
                )
            row = rows_by_day.get(trading_day)
            if row is None:
                raise SessionCalendarError(
                    "PRODUCT_SESSION_ROW_MISSING",
                    "{}.{} {}".format(product.exchange_id, product.product_id, trading_day),
                )
            selected_rows[trading_day] = row
            source_ids_needed.add(row.source_id)
            source_ids_needed.update(window.source_id for window in row.windows)
            total_expansion += sum(
                (window.end - window.start) // _ONE_MINUTE for window in row.windows
            )
            if total_expansion > _MAX_EXPANDED_PRODUCT_MINUTES:
                raise SessionCalendarError(
                    "GRID_EXPANSION_BUDGET_EXCEEDED",
                    "estimated product-minute slots exceed {}".format(
                        _MAX_EXPANDED_PRODUCT_MINUTES
                    ),
                )
        for source_id in source_ids_needed:
            source = source_index[source_id]
            if source.available_at.astimezone(timezone.utc) > decision.astimezone(timezone.utc):
                raise SessionCalendarError("SESSION_SOURCE_NOT_AVAILABLE_AT_DECISION", source_id)
            if source.retrieved_at.astimezone(timezone.utc) > decision.astimezone(timezone.utc):
                raise SessionCalendarError("SESSION_SOURCE_RETRIEVED_AFTER_DECISION", source_id)
        rows_by_product[product] = selected_rows

    slot_maps: Dict[ProductKey, Dict[datetime, SessionSlotEvidence]] = {}
    for product in products:
        slots: Dict[datetime, SessionSlotEvidence] = {}
        for row in rows_by_product[product].values():
            for close_time, provenance in _minute_slots(row).items():
                if close_time in slots:
                    raise SessionCalendarError("PRODUCT_MINUTE_SLOT_AMBIGUOUS")
                slots[close_time] = provenance
        slot_maps[product] = slots

    if any(not slot_maps[product] for product in products):
        common_closes = set()
    else:
        common_closes = set(slot_maps[products[0]])
        for product in products[1:]:
            common_closes.intersection_update(slot_maps[product])

    minutes = tuple(
        PlannedCommonMinute(
            close_time=close_time,
            members=tuple(slot_maps[product][close_time] for product in products),
        )
        for close_time in sorted(common_closes)
    )
    calendar_hashes = tuple(
        (exchange_id, selected_calendars[exchange_id].evidence_sha256)
        for exchange_id in sorted(target_exchanges)
    )
    return CommonMinuteGrid(
        status="READY" if minutes else "NO_COMMON_TRADING_MINUTES",
        decision_at=decision,
        target_products=products,
        product_trading_days=requested,
        calendar_hashes=calendar_hashes,
        minutes=minutes,
    )


def iter_common_minute_windows(
    target_products: Sequence[ProductKey],
    calendars: Sequence[ExchangeSessionCalendar],
    product_trading_days: Mapping[ProductKey, Sequence[date]],
    *,
    decision_at: datetime,
    window_size: int = 1_024,
    max_common_minutes: int = _MAX_STREAM_COMMON_MINUTES,
) -> Iterator[Tuple[PlannedCommonMinute, ...]]:
    """Lazily yield bounded chunks of the exact full-cohort minute grid.

    The exchange calendars, product-day rows, requested dates and source
    availability are validated before the first chunk is yielded.  Session
    intervals are sorted and checked for overlap without expanding them into
    minute dictionaries.  The multiway merge retains only one pending minute
    per product plus one output chunk, so a long finite snapshot does not need
    a ``product x minute`` slot map in memory.

    The source range remains finite and explicitly covered; this is not an
    infinite calendar or a dynamic-cohort API.  Call again with the complete
    new target set and new session snapshots to start a changed mapping,
    calendar, or membership epoch.  The caller must exhaust the iterator to
    prove completion.  If the configured common-minute budget is exceeded,
    iteration raises instead of silently truncating.  Each output chunk also
    stays under a fixed aggregate member-record budget; for ``N`` products its
    effective size is ``min(window_size, 65536 // N)``.
    """

    if type(window_size) is not int or not 1 <= window_size <= _MAX_ROLLING_WINDOW_MINUTES:
        raise SessionCalendarError(
            "ROLLING_WINDOW_SIZE_INVALID",
            "window_size must be in 1..{}".format(_MAX_ROLLING_WINDOW_MINUTES),
        )
    if (
        type(max_common_minutes) is not int
        or not 1 <= max_common_minutes <= _MAX_STREAM_COMMON_MINUTES
    ):
        raise SessionCalendarError(
            "STREAM_MINUTE_BUDGET_INVALID",
            "max_common_minutes must be in 1..{}".format(_MAX_STREAM_COMMON_MINUTES),
        )

    decision = _aware(decision_at, "decision_at")
    products = _bounded_sequence(target_products, "target_products", _MAX_TARGET_PRODUCTS)
    if not products or any(not isinstance(item, ProductKey) for item in products):
        raise ValueError("target_products must contain at least one ProductKey")
    if len(set(products)) != len(products):
        raise ValueError("target_products contains duplicates")
    chunk_size = min(window_size, _MAX_STREAM_CHUNK_MEMBER_RECORDS // len(products))
    requested = _requested_days(products, product_trading_days)
    requested_by_product = dict(requested)

    calendar_values = _bounded_sequence(calendars, "calendars", _MAX_EXCHANGE_CALENDARS)
    exchange_index: Dict[str, ExchangeSessionCalendar] = {}
    for calendar in calendar_values:
        if not isinstance(calendar, ExchangeSessionCalendar):
            raise ValueError("calendars must contain ExchangeSessionCalendar records")
        if calendar.exchange_id in exchange_index:
            raise ValueError("calendars contains duplicate exchange_id")
        exchange_index[calendar.exchange_id] = calendar

    target_exchanges = {product.exchange_id for product in products}
    selected_calendars: Dict[str, ExchangeSessionCalendar] = {}
    for exchange_id in target_exchanges:
        calendar = exchange_index.get(exchange_id)
        if calendar is None:
            raise SessionCalendarError("EXCHANGE_CALENDAR_MISSING", exchange_id)
        if not calendar.complete:
            raise SessionCalendarError("EXCHANGE_CALENDAR_INCOMPLETE", exchange_id)
        selected_calendars[exchange_id] = calendar

    product_set = set(products)
    rows_by_product: Dict[ProductKey, Dict[date, ProductTradingDaySessions]] = {
        product: {} for product in products
    }
    source_indexes: Dict[str, Mapping[str, PublicSourceEvidence]] = {}
    for exchange_id, calendar in selected_calendars.items():
        source_indexes[exchange_id] = calendar.source_index
        for row in calendar.product_days:
            if row.product in product_set:
                rows_by_product[row.product][row.trading_day] = row

    intervals_by_product: Dict[ProductKey, list[Tuple[SessionWindow, date]]] = {
        product: [] for product in products
    }
    requested_window_count = 0
    estimated_product_minutes = 0
    for product in products:
        calendar = selected_calendars[product.exchange_id]
        if product not in calendar.product_universe:
            raise SessionCalendarError(
                "PRODUCT_SESSION_UNIVERSE_MISSING",
                "{}.{}".format(product.exchange_id, product.product_id),
            )
        source_ids_needed = {calendar.calendar_source_id}
        for trading_day in requested_by_product[product]:
            if trading_day < calendar.coverage_start or trading_day > calendar.coverage_through:
                raise SessionCalendarError(
                    "TRADING_DAY_OUTSIDE_COVERAGE",
                    "{}.{} {}".format(product.exchange_id, product.product_id, trading_day),
                )
            if trading_day not in calendar.trading_days:
                raise SessionCalendarError(
                    "TRADING_DAY_NOT_IN_SOURCE_CALENDAR",
                    "{}.{} {}".format(product.exchange_id, product.product_id, trading_day),
                )
            row = rows_by_product[product].get(trading_day)
            if row is None:
                raise SessionCalendarError(
                    "PRODUCT_SESSION_ROW_MISSING",
                    "{}.{} {}".format(product.exchange_id, product.product_id, trading_day),
                )
            source_ids_needed.add(row.source_id)
            requested_window_count += len(row.windows)
            if requested_window_count > _MAX_STREAM_WINDOWS:
                raise SessionCalendarError(
                    "STREAM_SESSION_WINDOW_BUDGET_EXCEEDED",
                    "requested product-day windows exceed {}".format(_MAX_STREAM_WINDOWS),
                )
            for window in row.windows:
                source_ids_needed.add(window.source_id)
                intervals_by_product[product].append((window, row.trading_day))
                estimated_product_minutes += (window.end - window.start) // _ONE_MINUTE
                if estimated_product_minutes > _MAX_STREAM_PRODUCT_MINUTES:
                    raise SessionCalendarError(
                        "STREAM_PRODUCT_MINUTE_BUDGET_EXCEEDED",
                        "estimated source slots exceed {}".format(_MAX_STREAM_PRODUCT_MINUTES),
                    )
        source_index = source_indexes[product.exchange_id]
        for source_id in source_ids_needed:
            source = source_index[source_id]
            if source.available_at.astimezone(timezone.utc) > decision.astimezone(timezone.utc):
                raise SessionCalendarError("SESSION_SOURCE_NOT_AVAILABLE_AT_DECISION", source_id)
            if source.retrieved_at.astimezone(timezone.utc) > decision.astimezone(timezone.utc):
                raise SessionCalendarError("SESSION_SOURCE_RETRIEVED_AFTER_DECISION", source_id)

    ordered_intervals: Dict[ProductKey, Tuple[Tuple[SessionWindow, date], ...]] = {}
    for product in products:
        intervals = sorted(intervals_by_product[product], key=lambda item: item[0].start)
        previous_end = None
        for window, _trading_day in intervals:
            if previous_end is not None and window.start < previous_end:
                raise SessionCalendarError(
                    "PRODUCT_MINUTE_SLOT_AMBIGUOUS",
                    "{}.{}".format(product.exchange_id, product.product_id),
                )
            previous_end = window.end
        ordered_intervals[product] = tuple(intervals)

    def product_minutes(
        product: ProductKey,
    ) -> Iterator[Tuple[datetime, SessionSlotEvidence]]:
        for window, trading_day in ordered_intervals[product]:
            cursor = window.start
            while cursor < window.end:
                close_local = cursor + _ONE_MINUTE
                yield (
                    close_local.astimezone(timezone.utc),
                    SessionSlotEvidence(
                        product=product,
                        trading_day=trading_day,
                        session_date=window.session_date,
                        action_day=close_local.date(),
                        session_id=window.session_id,
                    ),
                )
                cursor = close_local

    def common_minutes() -> Iterator[PlannedCommonMinute]:
        streams = [iter(product_minutes(product)) for product in products]
        sentinel = object()
        current = [next(stream, sentinel) for stream in streams]
        if any(value is sentinel for value in current):
            return
        while True:
            target_close = max(value[0] for value in current)
            for index, stream in enumerate(streams):
                while current[index] is not sentinel and current[index][0] < target_close:
                    current[index] = next(stream, sentinel)
                if current[index] is sentinel:
                    return
            latest_close = max(value[0] for value in current)
            if all(value[0] == latest_close for value in current):
                yield PlannedCommonMinute(
                    close_time=latest_close,
                    members=tuple(value[1] for value in current),
                )
                for index, stream in enumerate(streams):
                    current[index] = next(stream, sentinel)
                if any(value is sentinel for value in current):
                    return

    def windows() -> Iterator[Tuple[PlannedCommonMinute, ...]]:
        common = iter(common_minutes())
        sentinel = object()
        emitted = 0
        exhausted = False
        while not exhausted:
            chunk = []
            while len(chunk) < chunk_size:
                planned = next(common, sentinel)
                if planned is sentinel:
                    exhausted = True
                    break
                if emitted >= max_common_minutes:
                    raise SessionCalendarError(
                        "STREAM_COMMON_MINUTE_BUDGET_EXCEEDED",
                        "common closes exceed {}".format(max_common_minutes),
                    )
                chunk.append(planned)
                emitted += 1
                if emitted == max_common_minutes:
                    # Prove the limit is the end of the finite source range
                    # before publishing a final-looking capped chunk.
                    if next(common, sentinel) is not sentinel:
                        raise SessionCalendarError(
                            "STREAM_COMMON_MINUTE_BUDGET_EXCEEDED",
                            "common closes exceed {}".format(max_common_minutes),
                        )
                    exhausted = True
                    break
            if chunk:
                yield tuple(chunk)
        return

    return windows()


def find_planned_common_minute(
    grid: CommonMinuteGrid, close_time: datetime
) -> Optional[PlannedCommonMinute]:
    """Return exact planned close evidence for one aware timestamp, if present.

    This lookup only reads the frozen grid produced from explicit calendar and
    session snapshots.  It does not authorize arbitrary callback/session times
    or infer a close from a product's nominal hours.
    """

    if not isinstance(grid, CommonMinuteGrid):
        raise TypeError("grid must be CommonMinuteGrid")
    close = _aware(close_time, "close_time").astimezone(timezone.utc)
    if grid.status != "READY":
        return None
    low = 0
    high = len(grid.minutes)
    while low < high:
        middle = (low + high) // 2
        planned = grid.minutes[middle]
        if planned.close_time < close:
            low = middle + 1
        else:
            high = middle
    if low < len(grid.minutes) and grid.minutes[low].close_time == close:
        return grid.minutes[low]
    return None


__all__ = [
    "CommonMinuteGrid",
    "ExchangeSessionCalendar",
    "PlannedCommonMinute",
    "ProductTradingDaySessions",
    "PublicSourceEvidence",
    "SessionCalendarError",
    "SessionSlotEvidence",
    "SessionWindow",
    "build_common_minute_grid",
    "find_planned_common_minute",
    "iter_common_minute_windows",
    "load_exchange_session_calendar",
]
