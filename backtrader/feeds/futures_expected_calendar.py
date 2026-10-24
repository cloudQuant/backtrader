"""Expected 2026 daytime futures calendars from reviewed public rule sources.

This adapter does not fetch exchange pages or claim an observed session feed.
Callers supply the actual catalog product keys, current CTP TradingDays,
source-review timestamps, and any known exchange/selected-contract overlays.
The resulting calendars are explicitly ``expected_rule_derived`` and remain
subject to later exchange notices.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any, Mapping, Optional, Sequence, Tuple

from .futures_main_contract import ExchangeTradingCalendar, ProductKey
from .futures_sessions import (
    ExchangeSessionCalendar,
    ExpectedRuleEvidence,
    ProductTradingDaySessions,
    SessionWindow,
)


EXPECTED_RULE_EVIDENCE_MODE = "expected_rule_derived"
RULE_REVIEW_VERSION = "public-rule-review-2026-10-24"
SUPPORTED_START = date(2026, 1, 1)
SUPPORTED_END = date(2026, 12, 31)
CHINA_TIME = timezone(timedelta(hours=8), "China Standard Time")
MAX_TARGET_PRODUCTS = 2_000
MAX_EXCHANGE_CLOSURES = 1_000
MAX_SELECTED_LAST_DAYS = 2_000
MAX_PRODUCT_DAY_ROWS = 100_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

STATE_COUNCIL_2026_HOLIDAY_RANGES = (
    (date(2026, 1, 1), date(2026, 1, 3)),
    (date(2026, 2, 15), date(2026, 2, 23)),
    (date(2026, 4, 4), date(2026, 4, 6)),
    (date(2026, 5, 1), date(2026, 5, 5)),
    (date(2026, 6, 19), date(2026, 6, 21)),
    (date(2026, 9, 25), date(2026, 9, 27)),
    (date(2026, 10, 1), date(2026, 10, 7)),
)

# These official makeup-work weekends remain closed because exchange rules use
# exchange trading days, not the State Council's workday designation.
STATE_COUNCIL_2026_MAKEUP_WEEKENDS = (
    date(2026, 1, 4),
    date(2026, 2, 14),
    date(2026, 2, 28),
    date(2026, 5, 9),
    date(2026, 9, 20),
    date(2026, 10, 10),
)

STATE_COUNCIL_HOLIDAY_URL = (
    "https://big5.www.gov.cn/gate/big5/www.gov.cn/zhengce/zhengceku/" "202511/content_7047091.htm"
)

EXCHANGE_RULE_SOURCE_URLS = {
    "SHFE": (
        "https://www.shfe.com.cn/services/calenderandholidays/tradinghours/",
        "https://www.shfe.com.cn/services/calenderandholidays/holiday/",
        "https://edu.shfe.com.cn/TradingAssistant/RulesIntroduction/518.html",
    ),
    "INE": (
        "https://www.ine.cn/services/calenderandholidays/tradinghours/",
        "https://www.ine.cn/services/calenderandholidays/holiday/",
        "https://www.shfe.com.cn/eng/services/Rules/INERules/202606/t20260603_831946.html",
    ),
    "DCE": (
        "https://www.dce.com.cn/dceg/file/2025-05-29/"
        "1748480876704ff80808197162e7128701971994e0a01313.pdf",
    ),
    "CZCE": (
        "https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/zcjjygz/2026/3/"
        "68c0dce01f984475be768ed93afd9b4f.pdf",
        "https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/ywbf/2026/5/"
        "a5ad00e02e484498abdbac8ddbfd5c35.pdf",
        "https://www.czce.com.cn/cn/flfg/zcjywgz/pzxz/webinfo/2024/02/" "1708568084281851.htm",
    ),
    "CFFEX": (
        "https://www.cffex.com.cn/u/cms/www/202003/27155912c7m4.pdf",
        "https://www.cffex.com.cn/u/cms/www/202003/27165505w3j5.pdf",
        "https://www.cffex.com.cn/u/cms/www/202207/182020307zry.pdf",
        "https://www.e-cffex.com.cn/u/cms/www/202007/08152522nwhg.pdf",
        "https://www.e-cffex.com.cn/u/cms/www/202007/08152340rnz2.pdf",
        "https://e-cffex.com.cn/u/cms/www/202007/08152235b2ys.pdf",
        "https://oa.hicend.com.cn/ftpfile/static/file/upload/file/202304/17/"
        "kmaiwuEFxlDM8cuu.pdf",
        "https://www.cffex.com.cn/u/cms/www/202405/31111942nrka.pdf",
    ),
    "GFEX": (
        "https://www.gfex.com.cn/gfex/sspzb/sspz.shtml",
        "https://www.gfex.com.cn/gfex/sytslqhhy/202307/" "9ad927b8ec4c458594e172fd1ada2a9b.shtml",
        "https://www.gfex.com.cn/en/Notices/202601/ecd5e39ce8a04d2eb0a88d47ba2abd26.shtml",
    ),
}

EXCHANGE_IDS = tuple(sorted(EXCHANGE_RULE_SOURCE_URLS))
COMMODITY_DAY_SESSIONS = (
    ("day-am-1", time(9, 0), time(10, 15)),
    ("day-am-2", time(10, 30), time(11, 30)),
    ("day-pm", time(13, 30), time(15, 0)),
)
CFFEX_INDEX_SESSIONS = (
    ("day-am", time(9, 30), time(11, 30)),
    ("day-pm", time(13, 0), time(15, 0)),
)
CFFEX_TREASURY_SESSIONS = (
    ("day-am", time(9, 30), time(11, 30)),
    ("day-pm", time(13, 0), time(15, 15)),
)
CFFEX_TREASURY_PRODUCTS = frozenset(("TS", "TF", "T", "TL"))
CFFEX_INDEX_PRODUCTS = frozenset(("IF", "IH", "IC", "IM"))

_LIMITATIONS = (
    "DCE, CZCE, and CFFEX 2026 annual closure notices were not verified in the 2026-10-24 source review; caller-supplied exchange closures are applied as overlays.",
    "Exchange URLs are public rule references, not captured response bytes; exchange-specific closure dates are included only when supplied in exchange_closures.",
    "The CFFEX TL rule is exchange-authored text hosted by a broker mirror; no exchange-served byte identity or latest-revision claim is made.",
    "CFFEX Treasury final-trading-day afternoon is removed only when the caller supplies the selected contract's exact final-day overlay; the five-session expiry rule excludes such a contract from normal main selection.",
    "The calendar is expected under cited weekday rules and known holiday closures; later exchange notices can change it.",
)


class ExpectedCalendarError(ValueError):
    """Raised when the supported rule inputs cannot prove an expected calendar."""

    def __init__(self, code: str, detail: Optional[str] = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else "{}: {}".format(code, detail))


@dataclass(frozen=True)
class ExpectedCalendarBuild:
    """Expected session calendars plus selector-ready date evidence."""

    target_products: Tuple[ProductKey, ...]
    current_trading_days: Tuple[Tuple[str, date], ...]
    session_calendars: Tuple[ExchangeSessionCalendar, ...]
    trading_calendars: Tuple[ExchangeTradingCalendar, ...]
    fifth_future_trading_days: Tuple[Tuple[str, date], ...]
    as_of: datetime
    retrieved_at: datetime
    rules_manifest_sha256: str
    evidence_mode: str = EXPECTED_RULE_EVIDENCE_MODE
    limitations: Tuple[str, ...] = _LIMITATIONS

    def __post_init__(self) -> None:
        if self.evidence_mode != EXPECTED_RULE_EVIDENCE_MODE:
            raise ValueError("expected calendar build evidence_mode is invalid")
        if not isinstance(self.rules_manifest_sha256, str) or not _SHA256.fullmatch(
            self.rules_manifest_sha256
        ):
            raise ValueError("rules_manifest_sha256 must be lowercase SHA-256 hex")
        values = (
            ("target_products", self.target_products, ProductKey),
            ("session_calendars", self.session_calendars, ExchangeSessionCalendar),
            ("trading_calendars", self.trading_calendars, ExchangeTradingCalendar),
        )
        for name, items, expected_type in values:
            if any(not isinstance(item, expected_type) for item in items):
                raise ValueError("{} contains an invalid record".format(name))
            object.__setattr__(self, name, tuple(items))
        object.__setattr__(self, "current_trading_days", tuple(self.current_trading_days))
        object.__setattr__(self, "fifth_future_trading_days", tuple(self.fifth_future_trading_days))
        object.__setattr__(self, "limitations", tuple(self.limitations))

    @property
    def calendar_by_exchange(self) -> Mapping[str, ExchangeTradingCalendar]:
        return {calendar.exchange_id: calendar for calendar in self.trading_calendars}

    @property
    def session_calendar_by_exchange(self) -> Mapping[str, ExchangeSessionCalendar]:
        return {calendar.exchange_id: calendar for calendar in self.session_calendars}


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExpectedCalendarError("TIMESTAMP_INVALID", name)
    return value


def _sequence(value: Any, name: str, limit: int) -> Tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ExpectedCalendarError("INPUT_SEQUENCE_INVALID", name)
    if len(value) > limit:
        raise ExpectedCalendarError("INPUT_LIMIT_EXCEEDED", name)
    return tuple(value)


def _date(value: Any, name: str) -> date:
    if type(value) is not date:
        raise ExpectedCalendarError("DATE_INVALID", name)
    if value < SUPPORTED_START or value > SUPPORTED_END:
        raise ExpectedCalendarError("DATE_OUTSIDE_SUPPORTED_2026", name)
    return value


def _normalize_exchange_date_map(
    values: Optional[Mapping[str, Sequence[date]]], name: str, limit: int
) -> Mapping[str, Tuple[date, ...]]:
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ExpectedCalendarError("INPUT_MAPPING_INVALID", name)
    normalized = {}
    for exchange_id, raw_days in values.items():
        if type(exchange_id) is not str or not exchange_id or exchange_id != exchange_id.strip():
            raise ExpectedCalendarError("EXCHANGE_ID_INVALID", name)
        exchange = exchange_id.upper()
        if exchange not in EXCHANGE_IDS:
            raise ExpectedCalendarError("EXCHANGE_UNSUPPORTED", exchange)
        if exchange in normalized:
            raise ExpectedCalendarError("DUPLICATE_EXCHANGE_ID", exchange)
        days = _sequence(raw_days, name, limit)
        if any(type(day) is not date for day in days):
            raise ExpectedCalendarError("DATE_INVALID", name)
        if any(day < SUPPORTED_START or day > SUPPORTED_END for day in days):
            raise ExpectedCalendarError("DATE_OUTSIDE_SUPPORTED_2026", name)
        if len(set(days)) != len(days):
            raise ExpectedCalendarError("DUPLICATE_DATE", name)
        normalized[exchange] = tuple(sorted(days))
    return normalized


def _normalize_holidays(
    ranges: Sequence[Tuple[date, date]],
) -> Tuple[Tuple[date, date], ...]:
    values = _sequence(ranges, "state_council_holiday_ranges", 32)
    normalized = []
    for pair in values:
        pair = _sequence(pair, "holiday range", 2)
        if len(pair) != 2:
            raise ExpectedCalendarError("HOLIDAY_RANGE_INVALID")
        start = _date(pair[0], "holiday start")
        end = _date(pair[1], "holiday end")
        if end < start:
            raise ExpectedCalendarError("HOLIDAY_RANGE_INVALID")
        normalized.append((start, end))
    normalized.sort()
    for previous, current in zip(normalized, normalized[1:]):
        if current[0] <= previous[1]:
            raise ExpectedCalendarError("HOLIDAY_RANGES_OVERLAP")
    return tuple(normalized)


def expected_2026_trading_days(
    exchange_id: str,
    *,
    state_council_holiday_ranges: Sequence[Tuple[date, date]] = (STATE_COUNCIL_2026_HOLIDAY_RANGES),
    additional_exchange_closures: Sequence[date] = (),
) -> Tuple[date, ...]:
    """Expand only the explicit 2026 weekday rule and supplied closure overlays."""

    if (
        type(exchange_id) is not str
        or not exchange_id
        or exchange_id != exchange_id.strip()
        or exchange_id.upper() not in EXCHANGE_IDS
    ):
        raise ExpectedCalendarError("EXCHANGE_UNSUPPORTED", str(exchange_id))
    exchange = exchange_id.upper()
    holiday_ranges = _normalize_holidays(state_council_holiday_ranges)
    closure_values = _sequence(additional_exchange_closures, "exchange closures", 1_000)
    if any(type(day) is not date for day in closure_values):
        raise ExpectedCalendarError("DATE_INVALID", "exchange closures")
    if any(day < SUPPORTED_START or day > SUPPORTED_END for day in closure_values):
        raise ExpectedCalendarError("DATE_OUTSIDE_SUPPORTED_2026", "exchange closures")
    if len(set(closure_values)) != len(closure_values):
        raise ExpectedCalendarError("DUPLICATE_DATE", "exchange closures")
    closures = set(closure_values)

    def is_state_holiday(day: date) -> bool:
        return any(start <= day <= end for start, end in holiday_ranges)

    days = []
    cursor = SUPPORTED_START
    while cursor <= SUPPORTED_END:
        if cursor.weekday() < 5 and not is_state_holiday(cursor) and cursor not in closures:
            days.append(cursor)
        cursor += timedelta(days=1)
    if not days:
        raise ExpectedCalendarError("EXPECTED_CALENDAR_EMPTY", exchange)
    return tuple(days)


def _manifest_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _window(
    session_id: str,
    trading_day: date,
    start: time,
    end: time,
    source_id: str,
) -> SessionWindow:
    return SessionWindow(
        session_id=session_id,
        session_date=trading_day,
        start=datetime.combine(trading_day, start, tzinfo=CHINA_TIME),
        end=datetime.combine(trading_day, end, tzinfo=CHINA_TIME),
        source_id=source_id,
    )


def _product_windows(
    product: ProductKey,
    trading_day: date,
    source_id: str,
    selected_contract_last_trading_days: Mapping[ProductKey, Tuple[date, ...]],
) -> Tuple[SessionWindow, ...]:
    if product.exchange_id != "CFFEX":
        intervals = COMMODITY_DAY_SESSIONS
    elif product.product_id in CFFEX_TREASURY_PRODUCTS:
        intervals = CFFEX_TREASURY_SESSIONS
        final_days = selected_contract_last_trading_days.get(product, ())
        if trading_day in final_days:
            intervals = CFFEX_TREASURY_SESSIONS[:1]
    elif product.product_id in CFFEX_INDEX_PRODUCTS:
        intervals = CFFEX_INDEX_SESSIONS
    else:
        raise ExpectedCalendarError(
            "CFFEX_PRODUCT_SESSION_CLASSIFICATION_UNKNOWN", product.product_id
        )
    return tuple(
        _window(session_id, trading_day, start, end, source_id)
        for session_id, start, end in intervals
    )


def build_expected_daytime_calendars(
    target_products: Sequence[ProductKey],
    current_trading_days: Mapping[str, date],
    *,
    as_of: datetime,
    retrieved_at: datetime,
    state_council_holiday_ranges: Sequence[Tuple[date, date]] = (STATE_COUNCIL_2026_HOLIDAY_RANGES),
    exchange_closures: Optional[Mapping[str, Sequence[date]]] = None,
    selected_contract_last_trading_days: Optional[Mapping[ProductKey, Sequence[date]]] = None,
) -> ExpectedCalendarBuild:
    """Build all requested product calendars without shrinking the catalog pool.

    ``retrieved_at`` is the caller's actual source-review retrieval time.
    Publication time is not backdated: expected-rule evidence sets
    ``available_at`` to this same conservative timestamp.  Each emitted
    calendar is clipped to the prior expected TradingDay when available and
    the current day through the fifth future expected TradingDay.  The
    standalone ``expected_2026_trading_days`` function remains the full-year
    rule lookup.
    """

    products = _sequence(target_products, "target_products", MAX_TARGET_PRODUCTS)
    if not products or any(not isinstance(item, ProductKey) for item in products):
        raise ExpectedCalendarError("TARGET_PRODUCTS_INVALID")
    if len(set(products)) != len(products):
        raise ExpectedCalendarError("TARGET_PRODUCTS_DUPLICATE")
    products = tuple(sorted(products, key=lambda item: (item.exchange_id, item.product_id)))
    exchanges = tuple(sorted({product.exchange_id for product in products}))
    if any(exchange not in EXCHANGE_IDS for exchange in exchanges):
        unknown = next(exchange for exchange in exchanges if exchange not in EXCHANGE_IDS)
        raise ExpectedCalendarError("EXCHANGE_UNSUPPORTED", unknown)

    if not isinstance(current_trading_days, Mapping):
        raise ExpectedCalendarError("CURRENT_DAYS_INVALID")
    normalized_current = {}
    for exchange_id, trading_day in current_trading_days.items():
        if type(exchange_id) is not str or not exchange_id or exchange_id != exchange_id.strip():
            raise ExpectedCalendarError("CURRENT_EXCHANGE_ID_INVALID")
        exchange = exchange_id.upper()
        if exchange in normalized_current:
            raise ExpectedCalendarError("CURRENT_EXCHANGE_ID_DUPLICATE", exchange)
        normalized_current[exchange] = _date(trading_day, "current_trading_day")
    if set(normalized_current) != set(exchanges):
        raise ExpectedCalendarError("CURRENT_DAY_EXCHANGE_COVERAGE_MISMATCH")

    as_of_value = _aware(as_of, "as_of")
    retrieved_value = _aware(retrieved_at, "retrieved_at")
    if retrieved_value.astimezone(timezone.utc) > as_of_value.astimezone(timezone.utc):
        raise ExpectedCalendarError("RULES_RETRIEVED_AFTER_AS_OF")

    holiday_ranges = _normalize_holidays(state_council_holiday_ranges)
    closures = _normalize_exchange_date_map(
        exchange_closures, "exchange_closures", MAX_EXCHANGE_CLOSURES
    )
    product_set = set(products)
    last_day_map: Mapping[ProductKey, Tuple[date, ...]] = {}
    if selected_contract_last_trading_days is not None:
        if not isinstance(selected_contract_last_trading_days, Mapping):
            raise ExpectedCalendarError("LAST_TRADING_DAY_OVERLAY_INVALID")
        normalized_last_days = {}
        for product, raw_days in selected_contract_last_trading_days.items():
            if not isinstance(product, ProductKey) or product not in product_set:
                raise ExpectedCalendarError("LAST_TRADING_DAY_PRODUCT_OUTSIDE_TARGET_POOL")
            if product.exchange_id != "CFFEX" or product.product_id not in CFFEX_TREASURY_PRODUCTS:
                raise ExpectedCalendarError("LAST_TRADING_DAY_OVERLAY_NOT_TREASURY")
            days = _sequence(
                raw_days, "selected contract last trading days", MAX_SELECTED_LAST_DAYS
            )
            if any(type(day) is not date for day in days):
                raise ExpectedCalendarError("DATE_INVALID", "selected contract last trading days")
            if any(day < SUPPORTED_START or day > SUPPORTED_END for day in days):
                raise ExpectedCalendarError(
                    "DATE_OUTSIDE_SUPPORTED_2026", "selected contract last trading days"
                )
            if len(set(days)) != len(days):
                raise ExpectedCalendarError("DUPLICATE_DATE", "selected contract last trading days")
            normalized_last_days[product] = tuple(sorted(days))
        last_day_map = normalized_last_days

    holidays_payload = [[start.isoformat(), end.isoformat()] for start, end in holiday_ranges]
    manifest_payload = {
        "evidence_mode": EXPECTED_RULE_EVIDENCE_MODE,
        "version": RULE_REVIEW_VERSION,
        "supported_range": [SUPPORTED_START.isoformat(), SUPPORTED_END.isoformat()],
        "state_council_holiday_url": STATE_COUNCIL_HOLIDAY_URL,
        "state_council_holiday_ranges": holidays_payload,
        "state_council_makeup_weekends_closed": [
            day.isoformat() for day in STATE_COUNCIL_2026_MAKEUP_WEEKENDS
        ],
        "exchange_sources": {
            exchange: list(EXCHANGE_RULE_SOURCE_URLS[exchange]) for exchange in EXCHANGE_IDS
        },
        "exchange_closures": {
            exchange: [day.isoformat() for day in closures.get(exchange, ())]
            for exchange in EXCHANGE_IDS
        },
        "commodity_day_sessions": [
            [session_id, start.isoformat(), end.isoformat()]
            for session_id, start, end in COMMODITY_DAY_SESSIONS
        ],
        "cffex_index_products": sorted(CFFEX_INDEX_PRODUCTS),
        "cffex_treasury_products": sorted(CFFEX_TREASURY_PRODUCTS),
        "cffex_index_sessions": [
            [session_id, start.isoformat(), end.isoformat()]
            for session_id, start, end in CFFEX_INDEX_SESSIONS
        ],
        "cffex_treasury_sessions": [
            [session_id, start.isoformat(), end.isoformat()]
            for session_id, start, end in CFFEX_TREASURY_SESSIONS
        ],
        "selected_contract_last_trading_days": {
            "{}.{}".format(product.exchange_id, product.product_id): [
                day.isoformat() for day in last_day_map[product]
            ]
            for product in sorted(
                last_day_map, key=lambda item: (item.exchange_id, item.product_id)
            )
        },
        "limitations": list(_LIMITATIONS),
    }
    manifest_sha256 = _manifest_sha256(manifest_payload)

    current_rows = []
    fifth_rows = []
    session_calendars = []
    trading_calendars = []
    for exchange in exchanges:
        exchange_products = tuple(
            product for product in products if product.exchange_id == exchange
        )
        days = expected_2026_trading_days(
            exchange,
            state_council_holiday_ranges=holiday_ranges,
            additional_exchange_closures=closures.get(exchange, ()),
        )
        current_day = normalized_current[exchange]
        try:
            current_index = days.index(current_day)
        except ValueError:
            raise ExpectedCalendarError("CURRENT_DAY_NOT_EXPECTED_TRADING_DAY", exchange) from None
        horizon_index = current_index + 5
        if horizon_index >= len(days):
            raise ExpectedCalendarError("FIVE_DAY_HORIZON_OUTSIDE_SUPPORTED_2026", exchange)
        fifth_rows.append((exchange, days[horizon_index]))
        current_rows.append((exchange, current_day))
        coverage_start_index = max(0, current_index - 1)
        calendar_days = days[coverage_start_index : horizon_index + 1]
        coverage_start = calendar_days[0]
        coverage_through = calendar_days[-1]

        selected_last_days = {
            product: last_day_map.get(product, ()) for product in exchange_products
        }
        for product, last_days in selected_last_days.items():
            if any(day not in days for day in last_days):
                raise ExpectedCalendarError(
                    "LAST_TRADING_DAY_NOT_EXPECTED_SESSION",
                    "{}.{}".format(product.exchange_id, product.product_id),
                )
        if len(exchange_products) * len(calendar_days) > MAX_PRODUCT_DAY_ROWS:
            raise ExpectedCalendarError("PRODUCT_DAY_ROW_BUDGET_EXCEEDED", exchange)

        source_id = "{}.expected-daytime-2026".format(exchange)
        source = ExpectedRuleEvidence(
            source_id=source_id,
            source_urls=(STATE_COUNCIL_HOLIDAY_URL,) + EXCHANGE_RULE_SOURCE_URLS[exchange],
            version=RULE_REVIEW_VERSION,
            available_at=retrieved_value,
            retrieved_at=retrieved_value,
            rules_manifest_sha256=manifest_sha256,
            limitations=_LIMITATIONS,
        )
        product_days = tuple(
            ProductTradingDaySessions(
                product=product,
                trading_day=trading_day,
                source_id=source_id,
                windows=_product_windows(product, trading_day, source_id, selected_last_days),
            )
            for product in exchange_products
            for trading_day in calendar_days
        )
        session_calendar = ExchangeSessionCalendar(
            exchange_id=exchange,
            calendar_source_id=source_id,
            coverage_start=coverage_start,
            coverage_through=coverage_through,
            trading_days=calendar_days,
            product_universe=exchange_products,
            product_days=product_days,
            sources=(source,),
            complete=True,
            evidence_mode=EXPECTED_RULE_EVIDENCE_MODE,
        )
        session_calendars.append(session_calendar)
        trading_calendars.append(session_calendar.to_main_contract_calendar())

    return ExpectedCalendarBuild(
        target_products=products,
        current_trading_days=tuple(current_rows),
        session_calendars=tuple(session_calendars),
        trading_calendars=tuple(trading_calendars),
        fifth_future_trading_days=tuple(fifth_rows),
        as_of=as_of_value,
        retrieved_at=retrieved_value,
        rules_manifest_sha256=manifest_sha256,
    )


__all__ = [
    "CFFEX_INDEX_PRODUCTS",
    "CFFEX_TREASURY_PRODUCTS",
    "EXCHANGE_IDS",
    "EXPECTED_RULE_EVIDENCE_MODE",
    "ExpectedCalendarBuild",
    "ExpectedCalendarError",
    "RULE_REVIEW_VERSION",
    "STATE_COUNCIL_2026_HOLIDAY_RANGES",
    "STATE_COUNCIL_2026_MAKEUP_WEEKENDS",
    "build_expected_daytime_calendars",
    "expected_2026_trading_days",
]
