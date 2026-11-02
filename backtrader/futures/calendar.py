"""Trading session calendars and their source evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse
import hashlib
import json
import re
from bt_api_py.futures_selection import ExchangeTradingCalendar, ProductKey



_SHA256 = re.compile(r"^[0-9a-f]{64}$")


_CHINA_OFFSET = timedelta(hours=8)


_ONE_MINUTE = timedelta(minutes=1)


_MAX_TARGET_PRODUCTS = 2_000


_MAX_CALENDAR_DAYS = 10_000


_MAX_PRODUCT_DAY_ROWS = 100_000


_MAX_SOURCES_PER_CALENDAR = 10_000


_MAX_WINDOWS_PER_PRODUCT_DAY = 16


_MAX_WINDOWS_PER_CALENDAR = 300_000


_MAX_SESSION_DURATION = timedelta(hours=24)


class SessionCalendarError(ValueError):
    """Raised when public calendar/session facts cannot prove the requested grid."""

    def __init__(self, code: str, detail: Optional[str] = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else "{}: {}".format(code, detail))


def _session_text(value: Any, name: str) -> str:
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
    value = _session_text(value, name)
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
        _session_text(self.source_id, "source_id")
        _url(self.source_url, "source_url")
        _session_text(self.version, "version")
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
class ExpectedRuleEvidence:
    """Public rule references used to derive an expected, not observed, calendar.

    ``rules_manifest_sha256`` fingerprints the normalized local rule manifest.
    It is deliberately distinct from ``PublicSourceEvidence.sha256``, which
    fingerprints captured source bytes.  The expected mode is an explicit
    forecast under reviewed rules and overlays; it does not claim an exchange
    response was captured or that no later notice will change the schedule.
    """

    source_id: str
    source_urls: Tuple[str, ...]
    version: str
    available_at: datetime
    retrieved_at: datetime
    rules_manifest_sha256: str
    limitations: Tuple[str, ...] = ()
    evidence_kind: str = "expected_rule_derived"

    def __post_init__(self) -> None:
        _session_text(self.source_id, "source_id")
        _session_text(self.version, "version")
        if self.evidence_kind != "expected_rule_derived":
            raise ValueError("evidence_kind must be expected_rule_derived")
        urls = _bounded_sequence(self.source_urls, "expected rule source_urls", 32)
        if not urls or any(not isinstance(url, str) for url in urls):
            raise ValueError("source_urls must contain HTTPS URLs")
        normalized_urls = tuple(sorted({_url(url, "source_url") for url in urls}))
        if len(normalized_urls) != len(urls):
            raise ValueError("source_urls must be unique")
        available = _aware(self.available_at, "available_at")
        retrieved = _aware(self.retrieved_at, "retrieved_at")
        if retrieved.astimezone(timezone.utc) < available.astimezone(timezone.utc):
            raise ValueError("retrieved_at precedes available_at")
        _sha256(self.rules_manifest_sha256, "rules_manifest_sha256")
        limitations = _bounded_sequence(self.limitations, "expected rule limitations", 32)
        if any(
            not isinstance(item, str) or not item or item != item.strip() for item in limitations
        ):
            raise ValueError("limitations must contain non-empty trimmed text")
        if len(set(limitations)) != len(limitations):
            raise ValueError("limitations must be unique")
        object.__setattr__(self, "source_urls", normalized_urls)
        object.__setattr__(self, "limitations", tuple(limitations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_kind": self.evidence_kind,
            "source_id": self.source_id,
            "source_urls": list(self.source_urls),
            "version": self.version,
            "available_at": _utc(self.available_at),
            "retrieved_at": _utc(self.retrieved_at),
            "rules_manifest_sha256": self.rules_manifest_sha256,
            "limitations": list(self.limitations),
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
        _session_text(self.session_id, "session_id")
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
        _session_text(self.source_id, "session source_id")


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
        _session_text(self.source_id, "product-day source_id")
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
            _session_text(self.closed_reason, "closed_reason")
        elif self.closed_reason is not None:
            raise ValueError("open product TradingDay cannot also have closed_reason")
        object.__setattr__(self, "windows", ordered)


@dataclass(frozen=True)
class ExchangeSessionCalendar:
    """An immutable exchange calendar and product schedule.

    ``trading_days`` is an explicit exhaustive sequence over the declared
    range, never an implicit weekday expansion.  ``evidence_mode`` distinguishes
    source-backed schedules from schedules expected under a normalized rule
    manifest.  ``product_universe`` is the exchange product set covered by the
    declared evidence; the grid builder still requires a matching schedule row
    for every requested product/day, so ``complete=True`` cannot hide missing
    product rows.
    """

    exchange_id: str
    calendar_source_id: str
    coverage_start: date
    coverage_through: date
    trading_days: Tuple[date, ...]
    product_universe: Tuple[ProductKey, ...]
    product_days: Tuple[ProductTradingDaySessions, ...]
    sources: Tuple[Union[PublicSourceEvidence, ExpectedRuleEvidence], ...]
    complete: bool = True
    evidence_mode: str = "source_backed"

    def __post_init__(self) -> None:
        exchange = _session_text(self.exchange_id, "exchange_id").upper()
        object.__setattr__(self, "exchange_id", exchange)
        _session_text(self.calendar_source_id, "calendar_source_id")
        if self.evidence_mode not in ("source_backed", "expected_rule_derived"):
            raise ValueError("unsupported calendar evidence_mode")
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
        if not sources or any(
            not isinstance(item, (PublicSourceEvidence, ExpectedRuleEvidence)) for item in sources
        ):
            raise ValueError("sources must contain public or expected-rule evidence records")
        expected_sources = tuple(item for item in sources if isinstance(item, ExpectedRuleEvidence))
        if self.evidence_mode == "expected_rule_derived":
            if len(expected_sources) != len(sources):
                raise ValueError("expected-rule calendars require expected-rule evidence only")
            if len({item.rules_manifest_sha256 for item in expected_sources}) != 1:
                raise ValueError("expected-rule sources must share one rules manifest")
        elif expected_sources:
            raise ValueError("expected-rule evidence requires expected_rule_derived mode")
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
    def source_index(
        self,
    ) -> Mapping[str, Union[PublicSourceEvidence, ExpectedRuleEvidence]]:
        return {item.source_id: item for item in self.sources}

    @property
    def evidence_sha256(self) -> str:
        return _json_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        result = {
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
        if self.evidence_mode != "source_backed":
            result["evidence_mode"] = self.evidence_mode
        return result

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
            evidence_mode=self.evidence_mode,
            source_manifest_sha256=(
                source.rules_manifest_sha256 if isinstance(source, ExpectedRuleEvidence) else None
            ),
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
        evidence_kind = value.get("evidence_kind", "public_source_bytes")
        if evidence_kind == "public_source_bytes":
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
        elif evidence_kind == "expected_rule_derived":
            sources.append(
                ExpectedRuleEvidence(
                    source_id=value.get("source_id"),
                    source_urls=tuple(
                        _bounded_sequence(value.get("source_urls", ()), "source_urls", 32)
                    ),
                    version=value.get("version"),
                    available_at=_iso_datetime(value.get("available_at"), "available_at"),
                    retrieved_at=_iso_datetime(value.get("retrieved_at"), "retrieved_at"),
                    rules_manifest_sha256=value.get("rules_manifest_sha256"),
                    limitations=tuple(
                        _bounded_sequence(value.get("limitations", ()), "limitations", 32)
                    ),
                )
            )
        else:
            raise SessionCalendarError("SESSION_SOURCE_KIND_UNSUPPORTED")
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
        evidence_mode=document.get("evidence_mode", "source_backed"),
    )
