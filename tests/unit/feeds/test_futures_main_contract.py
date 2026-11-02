"""Exchange calendar behavior used by futures contract selection."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backtrader.futures import ExchangeTradingCalendar, ExchangeTradingDay

UTC = timezone.utc
CALENDAR_AVAILABLE_AT = datetime(2026, 10, 1, 0, tzinfo=UTC)


def _exchange_days(start=date(2026, 10, 1), through=date(2027, 1, 15)):
    holidays = {date(2026, 10, 20)}
    result = []
    day = start
    while day <= through:
        if day.weekday() < 5 and day not in holidays:
            result.append(day)
        day += timedelta(days=1)
    return tuple(result)


TRADING_DAYS = _exchange_days()


def _calendar(
    *, complete=True, available_at=CALENDAR_AVAILABLE_AT, retrieved_at=None, through=None
):
    coverage_through = through or TRADING_DAYS[-1]
    days = tuple(day for day in TRADING_DAYS if day <= coverage_through)
    retrieved = retrieved_at or (available_at + timedelta(hours=1))
    return ExchangeTradingCalendar(
        exchange_id="DCE",
        source_id="fixture.exchange-calendar",
        version="2026.10",
        available_at=available_at,
        retrieved_at=retrieved,
        coverage_start=TRADING_DAYS[0],
        coverage_through=coverage_through,
        trading_days=days,
        complete=complete,
    )


def test_calendar_uses_exchange_sessions_across_weekends_and_holidays():
    calendar = _calendar()
    assert calendar.previous_complete_trading_day(date(2026, 10, 21)) == date(2026, 10, 19)
    assert calendar.trading_days_to_expiry(date(2026, 10, 21), date(2026, 11, 16)) == sum(
        date(2026, 10, 21) < day <= date(2026, 11, 16) for day in TRADING_DAYS
    )
    with pytest.raises(ValueError, match="date, not a datetime"):
        ExchangeTradingDay("DCE", datetime(2026, 10, 21, tzinfo=UTC))
