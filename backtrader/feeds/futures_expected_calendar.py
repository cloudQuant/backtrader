"""Project provider-neutral expected-calendar DTOs into BT session inputs.

Exchange holidays, venue-specific session rules, source references and rule
manifest data live in the configured ``bt_api_py`` provider. This module keeps
only the Backtrader-side conversion into its generic minute-grid DTOs. It does
not infer weekdays, exchange products, holidays, or session hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Mapping

from .futures_main_contract import ExchangeTradingCalendar, ProductKey
from .futures_sessions import (
    ExchangeSessionCalendar,
    ExpectedRuleEvidence,
    ProductTradingDaySessions,
    SessionWindow,
)


EXPECTED_RULE_EVIDENCE_MODE = "expected_rule_derived"
CHINA_TIME = timezone(timedelta(hours=8), "China Standard Time")


class ExpectedCalendarError(ValueError):
    """Finite Backtrader projection failure for an SDK calendar result."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExpectedCalendarBuild:
    """BT generic calendars plus the exact expected-rule scope metadata."""

    target_products: tuple[ProductKey, ...]
    current_trading_days: tuple[tuple[str, date], ...]
    session_calendars: tuple[ExchangeSessionCalendar, ...]
    trading_calendars: tuple[ExchangeTradingCalendar, ...]
    fifth_future_trading_days: tuple[tuple[str, date], ...]
    as_of: datetime
    retrieved_at: datetime
    rules_manifest_sha256: str
    evidence_mode: str = EXPECTED_RULE_EVIDENCE_MODE
    limitations: tuple[str, ...] = ()
    source_evidence: tuple[object, ...] = ()

    @property
    def calendar_by_exchange(self) -> Mapping[str, ExchangeTradingCalendar]:
        return {item.exchange_id: item for item in self.trading_calendars}

    @property
    def session_calendar_by_exchange(self) -> Mapping[str, ExchangeSessionCalendar]:
        return {item.exchange_id: item for item in self.session_calendars}


def expected_2026_trading_days(calendar_port: object, venue: str) -> tuple[date, ...]:
    """Read the exact provider's explicitly supported 2026 day set.

    This compatibility helper does not carry a local trading-day algorithm.
    """

    if type(venue) is not str or not venue:
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_VENUE_INVALID")
    reader = getattr(calendar_port, "expected_trading_days", None)
    if not callable(reader):
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_PROVIDER_UNAVAILABLE")
    try:
        days = reader(venue, 2026)
    except Exception as error:
        code = getattr(error, "code", None)
        if code in (
            "FUTURES_EXPECTED_CALENDAR_YEAR_UNSUPPORTED",
            "FUTURES_EXPECTED_VENUE_UNSUPPORTED",
        ):
            raise ExpectedCalendarError(code) from None
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_PROVIDER_UNAVAILABLE") from None
    if type(days) is not tuple or any(type(item) is not date for item in days):
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_RESULT_INVALID")
    if tuple(sorted(set(days))) != days:
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_RESULT_INVALID")
    return days


def build_expected_daytime_calendars(
    snapshot: object,
    *,
    calendar_port: object,
) -> ExpectedCalendarBuild:
    """Project an SDK-issued complete calendar snapshot into generic BT DTOs."""

    try:
        from bt_api_py.futures_expected_calendar_contracts import (
            FuturesExpectedCalendarSnapshot,
        )
    except Exception:
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_CONTRACTS_UNAVAILABLE") from None
    if type(snapshot) is not FuturesExpectedCalendarSnapshot:
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_SNAPSHOT_INVALID")
    validator = getattr(calendar_port, "validate", None)
    if not callable(validator):
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_PROVIDER_INVALID")
    try:
        valid = validator(snapshot)
    except Exception:
        valid = False
    if valid is not True:
        raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_SNAPSHOT_NOT_ISSUED_HERE")
    if snapshot.complete is not True:
        raise ExpectedCalendarError(
            snapshot.blockers[0]
            if snapshot.blockers
            else "SDK_EXPECTED_CALENDAR_SCOPE_INCOMPLETE"
        )

    neutral_products = snapshot.request.products
    products = tuple(ProductKey(item.venue, item.product_id) for item in neutral_products)
    product_by_key = {
        (item.venue, item.product_id): ProductKey(item.venue, item.product_id)
        for item in neutral_products
    }
    source_by_venue = {item.venue: item for item in snapshot.sources}
    product_days_by_venue: dict[str, list[ProductTradingDaySessions]] = {
        item.venue: [] for item in snapshot.venue_calendars
    }
    for row in snapshot.product_days:
        product = product_by_key.get((row.product.venue, row.product.product_id))
        source = source_by_venue.get(row.product.venue)
        if product is None or source is None or row.source_id != source.source_id:
            raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_RESULT_BINDING_INVALID")
        windows = tuple(
            SessionWindow(
                session_id=window.session_id,
                session_date=window.session_date,
                start=window.start_at_utc.astimezone(CHINA_TIME),
                end=window.end_at_utc.astimezone(CHINA_TIME),
                source_id=row.source_id,
            )
            for window in row.windows
        )
        product_days_by_venue[row.product.venue].append(
            ProductTradingDaySessions(
                product=product,
                trading_day=row.trading_day,
                source_id=row.source_id,
                windows=windows,
                closed_reason=row.closed_reason,
            )
        )

    session_calendars = []
    trading_calendars = []
    for calendar in snapshot.venue_calendars:
        source = source_by_venue.get(calendar.venue)
        if source is None or calendar.source_id != source.source_id:
            raise ExpectedCalendarError("SDK_EXPECTED_CALENDAR_RESULT_BINDING_INVALID")
        products_for_venue = tuple(
            product for product in products if product.exchange_id == calendar.venue
        )
        evidence = ExpectedRuleEvidence(
            source_id=source.source_id,
            source_urls=source.source_urls,
            version=source.version,
            available_at=source.available_at_utc,
            retrieved_at=source.retrieved_at_utc,
            rules_manifest_sha256=snapshot.rules_manifest_sha256,
            limitations=source.limitations,
        )
        session_calendar = ExchangeSessionCalendar(
            exchange_id=calendar.venue,
            calendar_source_id=calendar.source_id,
            coverage_start=calendar.coverage_start,
            coverage_through=calendar.coverage_through,
            trading_days=calendar.trading_days,
            product_universe=products_for_venue,
            product_days=tuple(product_days_by_venue[calendar.venue]),
            sources=(evidence,),
            complete=calendar.complete,
            evidence_mode=EXPECTED_RULE_EVIDENCE_MODE,
        )
        session_calendars.append(session_calendar)
        trading_calendars.append(session_calendar.to_main_contract_calendar())

    return ExpectedCalendarBuild(
        target_products=products,
        current_trading_days=tuple(
            (item.venue, item.trading_day)
            for item in snapshot.request.current_trading_days
        ),
        session_calendars=tuple(session_calendars),
        trading_calendars=tuple(trading_calendars),
        fifth_future_trading_days=tuple(
            (item.venue, item.trading_day)
            for item in snapshot.fifth_future_trading_days
        ),
        as_of=snapshot.request.as_of_utc,
        retrieved_at=max(item.retrieved_at_utc for item in snapshot.sources),
        rules_manifest_sha256=snapshot.rules_manifest_sha256,
        limitations=tuple(
            sorted({limitation for item in snapshot.sources for limitation in item.limitations})
        ),
        source_evidence=snapshot.sources,
    )


__all__ = [
    "EXPECTED_RULE_EVIDENCE_MODE",
    "ExpectedCalendarBuild",
    "ExpectedCalendarError",
    "build_expected_daytime_calendars",
    "expected_2026_trading_days",
]
