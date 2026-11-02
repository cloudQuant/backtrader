"""Common trading-minute grids and streaming windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple, Union
from .calendar import (
    ExchangeSessionCalendar,
    ExpectedRuleEvidence,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionCalendarError,
    SessionWindow,
    _MAX_TARGET_PRODUCTS,
    _ONE_MINUTE,
    _aware,
    _bounded_sequence,
    _utc,
)
from bt_api_py.futures_selection import ProductKey



_MAX_EXCHANGE_CALENDARS = 6


_MAX_PRODUCT_DAYS_PER_TARGET = 10_000


_MAX_TOTAL_REQUESTED_PRODUCT_DAYS = 100_000


_MAX_EXPANDED_PRODUCT_MINUTES = 1_000_000


_MAX_STREAM_WINDOWS = 300_000


_MAX_STREAM_PRODUCT_MINUTES = 20_000_000


_MAX_STREAM_COMMON_MINUTES = 1_000_000


_MAX_STREAM_CHUNK_MEMBER_RECORDS = 65_536


_MAX_ROLLING_WINDOW_MINUTES = 4_096


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
    source_indexes: Dict[str, Mapping[str, Union[PublicSourceEvidence, ExpectedRuleEvidence]]] = {}
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
