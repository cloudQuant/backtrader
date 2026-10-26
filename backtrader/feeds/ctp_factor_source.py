"""Strict source-time binding for live CTP factor feeds.

This adapter maps the CTP Asia/Shanghai fields carried by a generation-aware
callback to the exact immutable session slot selected for a live factor run.
It does not create an authenticated market-data identity or claim wire-level
callback continuity.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .futures_expected_calendar import CFFEX_INDEX_PRODUCTS
from .futures_main_contract import ProductKey
from .futures_sessions import (
    CommonMinuteGrid,
    ExchangeSessionCalendar,
    SessionSlotEvidence,
)


_UTC = timezone.utc
_CTP_ASIA_SHANGHAI = timezone(timedelta(hours=8))
_CFFEX_INDEX_OPENING_AUCTION_START = time(9, 25)
_CFFEX_INDEX_OPENING_AUCTION_END = time(9, 30)
CTP_FACTOR_SOURCE_TIME_CONTRACT = "ctp-asia-shanghai-fixed-utc8-v1"
_DATE_RE = re.compile(r"^[0-9]{8}$")
_TIME_RE = re.compile(r"^[0-9]{2}:[0-9]{2}:[0-9]{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_LOCAL_SEQUENCE = (1 << 63) - 1


class CtpFactorSourceError(ValueError):
    """A callback does not satisfy its frozen CTP factor-source binding."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_ctp_trading_day(value: Any) -> date:
    """Parse a public CTP ``YYYYMMDD`` day without a fallback or coercion."""

    if type(value) is not str or _DATE_RE.fullmatch(value) is None:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TRADING_DAY_INVALID")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TRADING_DAY_INVALID") from exc


@dataclass(frozen=True)
class CtpFactorSourceCalendar:
    """One shared frozen common-minute plan and immutable lookup index."""

    grid: CommonMinuteGrid
    clock_domain_id: str
    members_by_close: Mapping[datetime, Mapping[ProductKey, SessionSlotEvidence]] = field(
        repr=False
    )
    target_products: frozenset
    calendar_hashes_by_exchange: Mapping[str, str] = field(repr=False)
    trading_days_by_product: Mapping[ProductKey, frozenset] = field(repr=False)
    action_days_by_product_day: Mapping[tuple, frozenset] = field(repr=False)
    sessions_by_product: Mapping[ProductKey, tuple] = field(repr=False)

    @classmethod
    def from_grid(
        cls,
        grid: CommonMinuteGrid,
        clock_domain_id: str,
        session_calendars: Mapping[str, ExchangeSessionCalendar],
    ):
        if not isinstance(grid, CommonMinuteGrid) or grid.status != "READY" or not grid.minutes:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
        if type(clock_domain_id) is not str or not clock_domain_id.strip():
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_CLOCK_DOMAIN_INVALID")
        if type(grid.minutes) is not tuple or type(grid.target_products) is not tuple:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
        if type(grid.calendar_hashes) is not tuple or type(grid.product_trading_days) is not tuple:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")

        targets = frozenset(grid.target_products)
        if not targets or len(targets) != len(grid.target_products):
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
        previous_close = None
        for minute in grid.minutes:
            close = minute.close_time
            if (
                type(close) is not datetime
                or close.tzinfo is None
                or close.utcoffset() != timedelta(0)
                or (previous_close is not None and close <= previous_close)
            ):
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            previous_close = close

        days_by_product = {}
        for row in grid.product_trading_days:
            if (
                type(row) is not tuple
                or len(row) != 2
                or row[0] not in targets
                or type(row[1]) is not tuple
                or any(type(day) is not date for day in row[1])
                or not row[1]
                or tuple(sorted(set(row[1]))) != row[1]
                or row[0] in days_by_product
            ):
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            days_by_product[row[0]] = frozenset(row[1])
        if set(days_by_product) != targets:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")

        hashes = {}
        for row in grid.calendar_hashes:
            if type(row) is not tuple or len(row) != 2:
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            exchange_id, digest = row
            if (
                type(exchange_id) is not str
                or not exchange_id
                or type(digest) is not str
                or _SHA256_RE.fullmatch(digest) is None
                or exchange_id in hashes
            ):
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            hashes[exchange_id] = digest
        if set(hashes) != {product.exchange_id for product in targets}:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")

        if not isinstance(session_calendars, Mapping):
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
        exchanges = {product.exchange_id for product in targets}
        calendars_by_exchange = {}
        for exchange_id, calendar in session_calendars.items():
            if (
                type(exchange_id) is not str
                or not isinstance(calendar, ExchangeSessionCalendar)
                or calendar.exchange_id != exchange_id
                or exchange_id in calendars_by_exchange
                or calendar.complete is not True
                or calendar.evidence_sha256 != hashes.get(exchange_id)
            ):
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            calendars_by_exchange[exchange_id] = calendar
        if set(calendars_by_exchange) != exchanges:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")

        products_by_exchange = {}
        for product in targets:
            products_by_exchange.setdefault(product.exchange_id, set()).add(product)
        selected_product_days = {}
        for exchange_id, calendar in calendars_by_exchange.items():
            products_for_exchange = products_by_exchange[exchange_id]
            for row in calendar.product_days:
                if (
                    row.product in products_for_exchange
                    and row.trading_day in days_by_product[row.product]
                ):
                    key = (row.product, row.trading_day)
                    if key in selected_product_days:
                        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
                    selected_product_days[key] = row

        sessions_by_product = {}
        action_days_by_product_day = {}
        for product in targets:
            calendar = calendars_by_exchange[product.exchange_id]
            if product not in calendar.product_universe:
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            requested_days = days_by_product[product]
            if any((product, day) not in selected_product_days for day in requested_days):
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            windows = []
            for trading_day in sorted(requested_days):
                day_row = selected_product_days[(product, trading_day)]
                action_days = set()
                for window in day_row.windows:
                    local_start = window.start.astimezone(_CTP_ASIA_SHANGHAI)
                    local_end = window.end.astimezone(_CTP_ASIA_SHANGHAI)
                    action_day = local_start.date()
                    while action_day <= local_end.date():
                        action_days.add(action_day)
                        action_day += timedelta(days=1)
                    start_utc = window.start.astimezone(_UTC)
                    end_utc = window.end.astimezone(_UTC)
                    if end_utc <= start_utc:
                        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
                    windows.append(
                        (
                            start_utc,
                            end_utc,
                            trading_day,
                            window.session_date,
                            window.session_id,
                        )
                    )
                action_days_by_product_day[(product, trading_day)] = frozenset(action_days)
            windows.sort(key=lambda item: item[0])
            if any(current[0] < previous[1] for previous, current in zip(windows, windows[1:])):
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            sessions_by_product[product] = tuple(windows)

        indexed = {}
        for minute in grid.minutes:
            close = minute.close_time.astimezone(_UTC)
            members = {}
            if type(minute.members) is not tuple:
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            for member in minute.members:
                if (
                    not isinstance(member, SessionSlotEvidence)
                    or member.product not in targets
                    or member.product in members
                    or type(member.trading_day) is not date
                    or type(member.session_date) is not date
                    or type(member.action_day) is not date
                    or type(member.session_id) is not str
                    or not member.session_id
                ):
                    raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
                members[member.product] = member
            if set(members) != targets:
                raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
            indexed[close] = MappingProxyType(members)

        return cls(
            grid=grid,
            clock_domain_id=clock_domain_id,
            members_by_close=MappingProxyType(indexed),
            target_products=targets,
            calendar_hashes_by_exchange=MappingProxyType(hashes),
            trading_days_by_product=MappingProxyType(days_by_product),
            action_days_by_product_day=MappingProxyType(action_days_by_product_day),
            sessions_by_product=MappingProxyType(sessions_by_product),
        )

    def calendar_hash_for(self, product: ProductKey) -> str:
        if not isinstance(product, ProductKey) or product not in self.target_products:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PRODUCT_INVALID")
        try:
            return self.calendar_hashes_by_exchange[product.exchange_id]
        except KeyError as exc:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID") from exc

    def session_for(self, product: ProductKey, event_time_utc: datetime, trading_day: date):
        """Resolve one exact source timestamp against selected product sessions."""
        windows = self.sessions_by_product.get(product)
        if windows is None:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PRODUCT_INVALID")
        low = 0
        high = len(windows)
        while low < high:
            middle = (low + high) // 2
            if windows[middle][0] <= event_time_utc:
                low = middle + 1
            else:
                high = middle
        index = low - 1
        if index < 0:
            return None
        start, end, window_trading_day, session_date, session_id = windows[index]
        if start <= event_time_utc < end and window_trading_day == trading_day:
            return session_date, session_id
        return None

    def opening_auction_baseline_for(
        self, product: ProductKey, event_time_utc: datetime, trading_day: date
    ):
        """Resolve an eligible CFFEX index opening-auction baseline time.

        The CFFEX IF, IH, IC, and IM contract rules specify an opening auction
        from 09:25 to 09:30, followed by continuous trading from 09:30. This
        method identifies that interval only for the first cumulative-volume
        baseline; it does not add auction minutes to the continuous sessions or
        the common bar grid. Official rule PDFs are linked from
        ``futures_expected_calendar.EXCHANGE_RULE_SOURCE_URLS['CFFEX']``.
        """

        if (
            not isinstance(product, ProductKey)
            or product.exchange_id != "CFFEX"
            or product.product_id not in CFFEX_INDEX_PRODUCTS
        ):
            return None

        product_days = self.trading_days_by_product.get(product)
        if (
            product_days is None
            or type(trading_day) is not date
            or trading_day not in product_days
            or type(event_time_utc) is not datetime
            or event_time_utc.tzinfo is None
            or event_time_utc.utcoffset() is None
        ):
            return None

        local_time = event_time_utc.astimezone(_CTP_ASIA_SHANGHAI)
        local_clock = local_time.timetz().replace(tzinfo=None)
        if (
            local_time.date() != trading_day
            or not _CFFEX_INDEX_OPENING_AUCTION_START
            <= local_clock
            < _CFFEX_INDEX_OPENING_AUCTION_END
        ):
            return None
        return local_time.date(), "opening-auction-baseline"

    @property
    def source_time_contract(self) -> str:
        return CTP_FACTOR_SOURCE_TIME_CONTRACT


@dataclass(frozen=True)
class CtpFactorSourceBinding:
    """Immutable per-feed route, Trader-day, MD-generation and calendar binding."""

    calendar: CtpFactorSourceCalendar
    target_id: str
    product: ProductKey
    instrument_id: str
    exchange_id: str
    trader_trading_day: date
    expected_md_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.calendar, CtpFactorSourceCalendar):
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_INVALID")
        if (
            type(self.target_id) is not str
            or not self.target_id
            or not isinstance(self.product, ProductKey)
            or self.product not in self.calendar.target_products
            or type(self.instrument_id) is not str
            or not self.instrument_id
            or type(self.exchange_id) is not str
            or self.exchange_id != self.product.exchange_id
            or type(self.trader_trading_day) is not date
            or type(self.expected_md_generation) is not int
            or self.expected_md_generation <= 0
            or self.trader_trading_day
            not in self.calendar.trading_days_by_product.get(self.product, frozenset())
        ):
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_BINDING_INVALID")

    @property
    def calendar_hash(self) -> str:
        return self.calendar.calendar_hash_for(self.product)


@dataclass(frozen=True)
class CtpFactorTickProjection:
    """Validated source-time and planned-session fields for one callback."""

    event_time_utc: datetime
    planned_close_time: Optional[datetime]
    session_segment: Optional[str]
    calendar_hash: str
    exchange_id: str
    exchange_id_source: str
    callback_sequence: int
    callback_received_wall_time: float
    callback_received_monotonic_ns: int


def project_ctp_factor_tick(
    binding: CtpFactorSourceBinding, tick: Any
) -> CtpFactorTickProjection:
    """Validate a callback and mark whether its minute is in the common plan.

    A valid product-session callback outside the common plan remains available
    for bounded quote-only handling, without authorizing bar aggregation.
    """

    if not isinstance(binding, CtpFactorSourceBinding):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_BINDING_INVALID")

    raw = getattr(tick, "ctp_raw_tick", None)
    if not isinstance(raw, Mapping):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_RAW_TICK_MISSING")

    if getattr(tick, "ctp_callback_generation_captured", None) is not True:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_CALLBACK_GENERATION_UNBOUND")
    generation = getattr(tick, "connection_generation", None)
    stream_generation = getattr(tick, "stream_generation", None)
    raw_generation = raw.get("connection_generation")
    if (
        type(generation) is not int
        or generation != binding.expected_md_generation
        or type(stream_generation) is not int
        or stream_generation != binding.expected_md_generation
        or type(raw_generation) is not int
        or raw_generation != binding.expected_md_generation
    ):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_GENERATION_MISMATCH")

    sequence = getattr(tick, "ctp_callback_sequence", None)
    received_wall = getattr(tick, "ctp_callback_received_wall_time", None)
    received_monotonic_ns = getattr(tick, "ctp_callback_received_monotonic_ns", None)
    if (
        type(sequence) is not int
        or not 1 <= sequence <= _MAX_LOCAL_SEQUENCE
        or getattr(tick, "ingest_seq", None) != sequence
        or getattr(tick, "sequence", None) != sequence
        or type(received_wall) not in (int, float)
        or not math.isfinite(float(received_wall))
        or float(received_wall) <= 0.0
        or getattr(tick, "received_wall_time", None) != received_wall
        or type(received_monotonic_ns) is not int
        or received_monotonic_ns <= 0
        or getattr(tick, "received_monotonic_ns", None) != received_monotonic_ns
    ):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_CALLBACK_RECEIPT_INVALID")

    instrument = raw.get("InstrumentID")
    if (
        type(instrument) is not str
        or instrument != binding.instrument_id
        or getattr(tick, "instrument_id", None) != binding.instrument_id
    ):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_ROUTE_MISMATCH")

    raw_exchange = raw.get("ExchangeID")
    if type(raw_exchange) is not str:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_ROUTE_MISMATCH")
    raw_exchange = raw_exchange.strip().upper()
    if raw_exchange and raw_exchange != binding.exchange_id:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_ROUTE_MISMATCH")
    event_exchange = getattr(tick, "exchange_id", None)
    if type(event_exchange) is not str or event_exchange.strip().upper() != binding.exchange_id:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_ROUTE_MISMATCH")
    exchange_source = "ctp_native" if raw_exchange else "subscription_plan"

    trading_day_value = raw.get("TradingDay")
    action_day_value = raw.get("ActionDay")
    update_time = raw.get("UpdateTime")
    millisec = raw.get("UpdateMillisec")
    if (
        type(trading_day_value) is not str
        or _DATE_RE.fullmatch(trading_day_value) is None
        or type(action_day_value) is not str
        or _DATE_RE.fullmatch(action_day_value) is None
        or type(update_time) is not str
        or _TIME_RE.fullmatch(update_time) is None
        or type(millisec) is not int
        or not 0 <= millisec <= 999
    ):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TIME_FIELDS_INVALID")
    try:
        trading_day = datetime.strptime(trading_day_value, "%Y%m%d").date()
        action_day = datetime.strptime(action_day_value, "%Y%m%d").date()
        source_local = datetime.strptime(
            f"{action_day_value} {update_time}", "%Y%m%d %H:%M:%S"
        ).replace(microsecond=millisec * 1000, tzinfo=_CTP_ASIA_SHANGHAI)
    except ValueError as exc:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TIME_FIELDS_INVALID") from exc
    if trading_day != binding.trader_trading_day:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_SESSION_MISMATCH")
    selected_days = binding.calendar.trading_days_by_product.get(binding.product)
    if selected_days is None or trading_day not in selected_days:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_SESSION_MISMATCH")
    if (
        getattr(tick, "trading_day", None) != trading_day_value
        or getattr(tick, "action_day", None) != action_day_value
        or getattr(tick, "update_time", None) != update_time
        or getattr(tick, "update_millisec", None) != millisec
    ):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_RAW_EVENT_CONFLICT")
    event_time = source_local.astimezone(_UTC)
    event_datetime = getattr(tick, "datetime", None)
    if not isinstance(event_datetime, datetime):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TIME_CONFLICT")
    if event_datetime.tzinfo is None:
        event_datetime_utc = event_datetime.replace(tzinfo=_UTC)
    else:
        event_datetime_utc = event_datetime.astimezone(_UTC)
    if event_datetime_utc != event_time:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TIME_CONFLICT")
    event_timestamp = getattr(tick, "timestamp", None)
    if type(event_timestamp) not in (int, float) or not math.isfinite(float(event_timestamp)):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TIME_CONFLICT")
    if abs(float(event_timestamp) - event_time.timestamp()) > 0.000001:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_TIME_CONFLICT")

    selected_session = binding.calendar.session_for(binding.product, event_time, trading_day)
    if selected_session is None:
        selected_action_days = binding.calendar.action_days_by_product_day.get(
            (binding.product, trading_day), frozenset()
        )
        if action_day not in selected_action_days:
            raise CtpFactorSourceError("CTP_FACTOR_SOURCE_SESSION_MISMATCH")
        return CtpFactorTickProjection(
            event_time_utc=event_time,
            planned_close_time=None,
            session_segment=None,
            calendar_hash=binding.calendar_hash,
            exchange_id=binding.exchange_id,
            exchange_id_source=exchange_source,
            callback_sequence=sequence,
            callback_received_wall_time=float(received_wall),
            callback_received_monotonic_ns=received_monotonic_ns,
        )

    close_time = event_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    members = binding.calendar.members_by_close.get(close_time)
    if members is None:
        return CtpFactorTickProjection(
            event_time_utc=event_time,
            planned_close_time=None,
            session_segment=None,
            calendar_hash=binding.calendar_hash,
            exchange_id=binding.exchange_id,
            exchange_id_source=exchange_source,
            callback_sequence=sequence,
            callback_received_wall_time=float(received_wall),
            callback_received_monotonic_ns=received_monotonic_ns,
        )
    member = members.get(binding.product)
    if member is None:
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_PLAN_MEMBER_MISSING")
    if (
        member.trading_day != trading_day
        or member.session_id != selected_session[1]
        or member.session_date != selected_session[0]
        or action_day not in {member.action_day, member.session_date}
    ):
        raise CtpFactorSourceError("CTP_FACTOR_SOURCE_SESSION_MISMATCH")

    return CtpFactorTickProjection(
        event_time_utc=event_time,
        planned_close_time=close_time,
        session_segment=selected_session[1],
        calendar_hash=binding.calendar_hash,
        exchange_id=binding.exchange_id,
        exchange_id_source=exchange_source,
        callback_sequence=sequence,
        callback_received_wall_time=float(received_wall),
        callback_received_monotonic_ns=received_monotonic_ns,
    )


__all__ = [
    "CTP_FACTOR_SOURCE_TIME_CONTRACT",
    "CtpFactorSourceBinding",
    "CtpFactorSourceCalendar",
    "CtpFactorSourceError",
    "CtpFactorTickProjection",
    "parse_ctp_trading_day",
    "project_ctp_factor_tick",
]
