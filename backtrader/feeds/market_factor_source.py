"""Project authenticated market events onto a Backtrader factor-minute plan.

Backtrader owns the common minute grid and its product membership. The SDK
owns event-clock qualification and provider session interpretation through a
route-bound ``MarketSessionResolver``. This module only adapts the selected
framework schedule to the neutral SDK contract and matches a complete result
back to a planned grid slot; it never infers provider time or session rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .futures_main_contract import ProductKey
from .futures_sessions import (
    CommonMinuteGrid,
    ExchangeSessionCalendar,
    ProductTradingDaySessions,
    SessionSlotEvidence,
)


_UTC = timezone.utc
_MAX_LOCAL_SEQUENCE = (1 << 63) - 1


class MarketFactorSourceError(ValueError):
    """A market event cannot be bound to the selected factor-minute plan."""

    _CODES = frozenset(
        {
            "MARKET_FACTOR_SOURCE_API_UNAVAILABLE",
            "MARKET_FACTOR_SOURCE_PLAN_INVALID",
            "MARKET_FACTOR_SOURCE_BINDING_INVALID",
            "MARKET_FACTOR_SOURCE_TICK_REQUIRED",
            "MARKET_FACTOR_SOURCE_CLOCK_UNAVAILABLE",
            "MARKET_FACTOR_SOURCE_ROUTE_MISMATCH",
            "MARKET_FACTOR_SOURCE_SEQUENCE_INVALID",
            "MARKET_FACTOR_SOURCE_SESSION_UNAVAILABLE",
            "MARKET_FACTOR_SOURCE_SESSION_MISMATCH",
            "MARKET_FACTOR_SOURCE_PLAN_MEMBER_MISSING",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in self._CODES
            else "MARKET_FACTOR_SOURCE_PLAN_INVALID"
        )
        super().__init__(self.code)


def _sdk_contracts():
    """Load the public SDK contracts only when the optional bridge is enabled."""

    try:
        from bt_api_py.facade_protocol import (
            FuturesProductKey,
            MarketInstrumentKey,
            MarketSessionCalendar,
            MarketSessionResolution,
            MarketSessionResolutionStatus,
            MarketSessionResolver,
            MarketSessionResolverSelector,
            MarketSessionSegmentKind,
            MarketSessionWindow,
            MarketTickEvent,
        )
    except (ImportError, AttributeError) as exc:
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_API_UNAVAILABLE") from exc
    return (
        FuturesProductKey,
        MarketInstrumentKey,
        MarketSessionCalendar,
        MarketSessionResolution,
        MarketSessionResolutionStatus,
        MarketSessionResolver,
        MarketSessionResolverSelector,
        MarketSessionSegmentKind,
        MarketSessionWindow,
        MarketTickEvent,
    )


def _parse_utc(value: Any) -> Optional[datetime]:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_UTC)


@dataclass(frozen=True)
class MarketFactorSourceCalendar:
    """One immutable Backtrader common-minute plan and source calendar set."""

    grid: CommonMinuteGrid
    members_by_close: Mapping[datetime, Mapping[ProductKey, SessionSlotEvidence]] = field(
        repr=False
    )
    target_products: frozenset
    calendar_hashes_by_exchange: Mapping[str, str] = field(repr=False)
    trading_days_by_product: Mapping[ProductKey, frozenset] = field(repr=False)
    calendars_by_exchange: Mapping[str, ExchangeSessionCalendar] = field(repr=False)
    product_days_by_key: Mapping[tuple, ProductTradingDaySessions] = field(repr=False)

    @classmethod
    def from_grid(
        cls,
        grid: CommonMinuteGrid,
        session_calendars: Mapping[str, ExchangeSessionCalendar],
    ):
        if not isinstance(grid, CommonMinuteGrid) or grid.status != "READY" or not grid.minutes:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
        if type(grid.minutes) is not tuple or type(grid.target_products) is not tuple:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
        if type(grid.calendar_hashes) is not tuple or type(grid.product_trading_days) is not tuple:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")

        targets = frozenset(grid.target_products)
        if not targets or len(targets) != len(grid.target_products):
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")

        previous_close = None
        for minute in grid.minutes:
            close = minute.close_time
            if (
                type(close) is not datetime
                or close.tzinfo is None
                or close.utcoffset() != timedelta(0)
                or (previous_close is not None and close <= previous_close)
            ):
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
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
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
            days_by_product[row[0]] = frozenset(row[1])
        if set(days_by_product) != targets:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")

        hashes = {}
        for row in grid.calendar_hashes:
            if type(row) is not tuple or len(row) != 2:
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
            exchange_id, digest = row
            if (
                type(exchange_id) is not str
                or not exchange_id
                or type(digest) is not str
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or exchange_id in hashes
            ):
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
            hashes[exchange_id] = digest
        if set(hashes) != {product.exchange_id for product in targets}:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")

        if not isinstance(session_calendars, Mapping):
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
        exchanges = {product.exchange_id for product in targets}
        calendars = {}
        for exchange_id, calendar in session_calendars.items():
            if (
                type(exchange_id) is not str
                or not isinstance(calendar, ExchangeSessionCalendar)
                or calendar.exchange_id != exchange_id
                or exchange_id in calendars
                or calendar.complete is not True
                or calendar.evidence_sha256 != hashes.get(exchange_id)
            ):
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
            calendars[exchange_id] = calendar
        if set(calendars) != exchanges:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")

        products_by_exchange = {}
        for product in targets:
            products_by_exchange.setdefault(product.exchange_id, set()).add(product)
        product_days = {}
        for exchange_id, calendar in calendars.items():
            products_for_exchange = products_by_exchange[exchange_id]
            for row in calendar.product_days:
                if (
                    row.product in products_for_exchange
                    and row.trading_day in days_by_product[row.product]
                ):
                    key = (row.product, row.trading_day)
                    if key in product_days:
                        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
                    product_days[key] = row

        expected_keys = {
            (product, trading_day)
            for product, trading_days in days_by_product.items()
            for trading_day in trading_days
        }
        if set(product_days) != expected_keys:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")

        indexed = {}
        for minute in grid.minutes:
            close = minute.close_time.astimezone(_UTC)
            members = {}
            if type(minute.members) is not tuple:
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
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
                    raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
                members[member.product] = member
            if set(members) != targets:
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
            indexed[close] = MappingProxyType(members)

        return cls(
            grid=grid,
            members_by_close=MappingProxyType(indexed),
            target_products=targets,
            calendar_hashes_by_exchange=MappingProxyType(hashes),
            trading_days_by_product=MappingProxyType(days_by_product),
            calendars_by_exchange=MappingProxyType(calendars),
            product_days_by_key=MappingProxyType(product_days),
        )

    def calendar_hash_for(self, product: ProductKey) -> str:
        if not isinstance(product, ProductKey) or product not in self.target_products:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_BINDING_INVALID")
        try:
            return self.calendar_hashes_by_exchange[product.exchange_id]
        except KeyError as exc:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID") from exc

    def market_calendar_for(self, product: ProductKey, instrument: Any):
        """Adapt one exact framework schedule to the public neutral SDK DTO."""

        (
            FuturesProductKey,
            MarketInstrumentKey,
            MarketSessionCalendar,
            _,
            _,
            _,
            _,
            _,
            MarketSessionWindow,
            _,
        ) = _sdk_contracts()
        if (
            not isinstance(product, ProductKey)
            or product not in self.target_products
            or type(instrument) is not MarketInstrumentKey
            or instrument.venue != product.exchange_id
        ):
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_BINDING_INVALID")

        trading_days = tuple(sorted(self.trading_days_by_product[product]))
        windows = []
        all_days_have_windows = True
        for trading_day in trading_days:
            row = self.product_days_by_key.get((product, trading_day))
            if row is None or not row.windows:
                all_days_have_windows = False
                continue
            for session in row.windows:
                if (
                    type(session.start) is not datetime
                    or type(session.end) is not datetime
                    or session.start.tzinfo is None
                    or session.end.tzinfo is None
                    or session.start.utcoffset() is None
                    or session.end.utcoffset() is None
                    or session.end <= session.start
                ):
                    raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_INVALID")
                # Schedule values already carry their timezone. Convert those
                # instants generically; provider event-time interpretation is
                # left to the SDK resolver.
                start_utc = session.start.astimezone(_UTC)
                end_utc = session.end.astimezone(_UTC)
                last_included = session.end - timedelta(microseconds=1)
                event_dates = tuple(
                    sorted({session.session_date, session.start.date(), last_included.date()})
                )
                windows.append(
                    MarketSessionWindow(
                        trading_date=trading_day,
                        session_date=session.session_date,
                        event_session_dates=event_dates,
                        start_at_utc=start_utc,
                        end_at_utc=end_utc,
                        session_id=session.session_id,
                    )
                )

        windows.sort(key=lambda item: item.start_at_utc)
        base_calendar = self.calendars_by_exchange[product.exchange_id]
        sdk_product = FuturesProductKey(
            venue=product.exchange_id,
            product_id=product.product_id,
        )
        calendar_ref = "backtrader-session:{}:{}:{}".format(
            base_calendar.calendar_source_id,
            product.exchange_id,
            product.product_id,
        )
        digest_payload = {
            "schema": "backtrader.market_session_calendar.v1",
            "source_calendar_digest": self.calendar_hash_for(product),
            "instrument": instrument.to_dict(),
            "product": sdk_product.to_dict(),
            "trading_dates": [item.isoformat() for item in trading_days],
            "windows": [
                {
                    "trading_date": item.trading_date.isoformat(),
                    "session_date": item.session_date.isoformat(),
                    "event_session_dates": [
                        value.isoformat() for value in item.event_session_dates
                    ],
                    "start_at_utc": item.start_at_utc.isoformat(),
                    "end_at_utc": item.end_at_utc.isoformat(),
                    "session_id": item.session_id,
                }
                for item in windows
            ],
        }
        calendar_digest = hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8", errors="strict")
        ).hexdigest()
        return MarketSessionCalendar(
            instrument=instrument,
            product=sdk_product,
            trading_dates=trading_days,
            windows=tuple(windows),
            calendar_ref=calendar_ref,
            calendar_digest=calendar_digest,
            complete=bool(base_calendar.complete and all_days_have_windows),
        )


@dataclass(frozen=True)
class MarketFactorSourceBinding:
    """Exact feed, product, SDK resolver, trading-date and generation binding."""

    calendar: MarketFactorSourceCalendar
    target_id: str
    product: ProductKey
    instrument: Any
    trading_date: date
    expected_connection_generation: int
    session_resolver: Any = field(repr=False, compare=False)
    market_calendar: Any = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        (
            FuturesProductKey,
            MarketInstrumentKey,
            _,
            _,
            _,
            MarketSessionResolver,
            _,
            _,
            _,
            _,
        ) = _sdk_contracts()
        if (
            type(self.calendar) is not MarketFactorSourceCalendar
            or type(self.target_id) is not str
            or not self.target_id
            or type(self.product) is not ProductKey
            or self.product not in self.calendar.target_products
            or type(self.instrument) is not MarketInstrumentKey
            or self.instrument.venue != self.product.exchange_id
            or type(self.trading_date) is not date
            or self.trading_date
            not in self.calendar.trading_days_by_product.get(self.product, frozenset())
            or type(self.expected_connection_generation) is not int
            or self.expected_connection_generation <= 0
            or not isinstance(self.session_resolver, MarketSessionResolver)
        ):
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_BINDING_INVALID")

        sdk_product = FuturesProductKey(
            venue=self.product.exchange_id,
            product_id=self.product.product_id,
        )
        market_calendar = self.calendar.market_calendar_for(self.product, self.instrument)
        if market_calendar.product != sdk_product:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_BINDING_INVALID")
        object.__setattr__(self, "market_calendar", market_calendar)

    @classmethod
    def from_sdk(
        cls,
        *,
        calendar: MarketFactorSourceCalendar,
        target_id: str,
        product: ProductKey,
        instrument: Any,
        trading_date: date,
        expected_connection_generation: int,
        sdk: Any,
        exchange_name: str,
    ):
        """Bind through the SDK's public exact-route resolver selector."""

        MarketSessionResolverSelector = _sdk_contracts()[6]
        if type(exchange_name) is not str or not exchange_name:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_BINDING_INVALID")
        if not isinstance(sdk, MarketSessionResolverSelector):
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_API_UNAVAILABLE")
        try:
            resolver = sdk.market_session_resolver(exchange_name, instrument)
        except Exception as exc:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_API_UNAVAILABLE") from exc
        return cls(
            calendar=calendar,
            target_id=target_id,
            product=product,
            instrument=instrument,
            trading_date=trading_date,
            expected_connection_generation=expected_connection_generation,
            session_resolver=resolver,
        )


@dataclass(frozen=True)
class MarketFactorTickProjection:
    """One SDK-resolved event and its optional common-grid minute slot."""

    event_time_utc: datetime
    planned_close_time: Optional[datetime]
    session_segment: str
    calendar_digest: str
    venue: str
    identity_source: str
    cursor_sequence: int
    provider_sequence: int
    received_wall_time: float
    received_monotonic_ns: int
    clock_domain_id: str
    trading_date: date
    session_date: date
    event_session_date: date


def project_market_factor_tick(
    binding: MarketFactorSourceBinding, tick: Any
) -> MarketFactorTickProjection:
    """Resolve a typed SDK event, then match only a complete continuous slot."""

    if type(binding) is not MarketFactorSourceBinding:
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_BINDING_INVALID")
    (
        _,
        MarketInstrumentKey,
        _,
        MarketSessionResolution,
        MarketSessionResolutionStatus,
        _,
        _,
        MarketSessionSegmentKind,
        _,
        MarketTickEvent,
    ) = _sdk_contracts()
    event = getattr(tick, "market_tick_event", tick)
    if type(event) is not MarketTickEvent:
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_TICK_REQUIRED")
    if not event.data_clock_qualified:
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_CLOCK_UNAVAILABLE")

    if (
        type(event.key.instrument) is not MarketInstrumentKey
        or event.key.instrument != binding.instrument
        or event.source.key.instrument != binding.instrument
        or event.source.connection_generation != binding.expected_connection_generation
    ):
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_ROUTE_MISMATCH")

    cursor_sequence = event.cursor.sequence
    provider_sequence = event.data.provider_sequence
    received_monotonic_ns = event.clock.received_monotonic_ns
    received_time = _parse_utc(event.clock.received_at_utc)
    if (
        type(cursor_sequence) is not int
        or not 1 <= cursor_sequence <= _MAX_LOCAL_SEQUENCE
        or type(provider_sequence) is not int
        or not 1 <= provider_sequence <= _MAX_LOCAL_SEQUENCE
        or type(received_monotonic_ns) is not int
        or received_monotonic_ns <= 0
        or received_time is None
    ):
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SEQUENCE_INVALID")

    try:
        resolution = binding.session_resolver.resolve(event, binding.market_calendar)
    except Exception as exc:
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_UNAVAILABLE") from exc
    if type(resolution) is not MarketSessionResolution:
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_UNAVAILABLE")
    if (
        resolution.status is not MarketSessionResolutionStatus.COMPLETE
        or not resolution.clock_qualified
        or resolution.instrument != binding.instrument
        or resolution.product.venue != binding.product.exchange_id
        or resolution.product.product_id != binding.product.product_id
        or resolution.calendar_ref != binding.market_calendar.calendar_ref
        or resolution.calendar_digest != binding.market_calendar.calendar_digest
        or resolution.trading_date != binding.trading_date
        or resolution.event_time_utc is None
        or resolution.session_date is None
        or resolution.event_session_date is None
    ):
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_UNAVAILABLE")

    event_time = resolution.event_time_utc
    if (
        event_time.tzinfo is None
        or event_time.utcoffset() != timedelta(0)
        or event_time != _parse_utc(event.clock.provider_event_time_utc)
        or event.data.trading_date != resolution.trading_date.isoformat()
        or event.data.event_session_date != resolution.event_session_date.isoformat()
        or event_time > received_time
    ):
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_MISMATCH")

    planned_close = None
    segment = resolution.segment_kind.value
    if resolution.segment_kind is MarketSessionSegmentKind.CONTINUOUS:
        if resolution.session_id is None:
            raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_MISMATCH")
        close_time = event_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        members = binding.calendar.members_by_close.get(close_time)
        if members is not None:
            member = members.get(binding.product)
            if member is None:
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_PLAN_MEMBER_MISSING")
            if (
                member.trading_day != resolution.trading_date
                or member.session_date != resolution.session_date
                or member.action_day != resolution.event_session_date
                or member.session_id != resolution.session_id
            ):
                raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_MISMATCH")
            planned_close = close_time
    elif resolution.segment_kind not in (
        MarketSessionSegmentKind.OPENING_AUCTION_BASELINE,
        MarketSessionSegmentKind.OUTSIDE,
    ):
        raise MarketFactorSourceError("MARKET_FACTOR_SOURCE_SESSION_UNAVAILABLE")

    return MarketFactorTickProjection(
        event_time_utc=event_time.astimezone(_UTC),
        planned_close_time=planned_close,
        session_segment=segment,
        calendar_digest=binding.market_calendar.calendar_digest,
        venue=binding.instrument.venue,
        identity_source="sdk_market_key",
        cursor_sequence=cursor_sequence,
        provider_sequence=provider_sequence,
        received_wall_time=received_time.timestamp(),
        received_monotonic_ns=received_monotonic_ns,
        clock_domain_id=event.source.clock_domain_id,
        trading_date=resolution.trading_date,
        session_date=resolution.session_date,
        event_session_date=resolution.event_session_date,
    )


__all__ = [
    "MarketFactorSourceBinding",
    "MarketFactorSourceCalendar",
    "MarketFactorSourceError",
    "MarketFactorTickProjection",
    "project_market_factor_tick",
]
