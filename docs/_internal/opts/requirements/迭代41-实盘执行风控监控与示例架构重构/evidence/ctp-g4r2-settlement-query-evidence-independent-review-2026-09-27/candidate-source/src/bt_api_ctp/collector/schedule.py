"""Trading calendar and session windows.

The local calendar is only a startup-time pre-check (is today a trading day,
does tonight have a night session).  Once connected, CTP's own
``GetTradingDay()`` is authoritative for the trading day actually written
into paths and records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

#: Night-session close times across domestic products, earliest to latest.
NIGHT_CLOSE_TIERS: tuple[str, ...] = ("23:00", "01:00", "02:30")

_DAY_FIRST_WEEKDAY = 0  # Monday
_DAY_LAST_WEEKDAY = 4  # Friday
_SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class Session:
    """One continuous trading window, in local exchange time."""

    start_hhmm: str
    end_hhmm: str
    crosses_midnight: bool = False


#: Continuous trading windows, deliberately wide enough to cover both
#: commodity and CFFEX products.  Breaks (10:15-10:30, 11:30-13:30) are
#: excluded so gap detection never counts a scheduled break as a gap.
TRADING_SESSIONS: tuple[Session, ...] = (
    Session("09:00", "10:15"),
    Session("10:30", "11:30"),
    Session("13:00", "15:15"),
    Session("21:00", "02:30", crosses_midnight=True),
)


def _hhmm_seconds(hhmm: str) -> int:
    hour, _, minute = hhmm.partition(":")
    return int(hour) * 3600 + int(minute) * 60


def _moment_seconds(moment: datetime) -> int:
    return moment.hour * 3600 + moment.minute * 60 + moment.second


def _in_session(moment: datetime, session: Session) -> bool:
    seconds = _moment_seconds(moment)
    start = _hhmm_seconds(session.start_hhmm)
    end = _hhmm_seconds(session.end_hhmm)
    if session.crosses_midnight:
        return seconds >= start or seconds <= end
    return start <= seconds <= end


def _session_start(day: date, session: Session) -> datetime:
    hour, _, minute = session.start_hhmm.partition(":")
    return datetime(day.year, day.month, day.day, int(hour), int(minute))


def _session_length_seconds(session: Session) -> float:
    start = _hhmm_seconds(session.start_hhmm)
    end = _hhmm_seconds(session.end_hhmm)
    if session.crosses_midnight:
        return float((end - start) % _SECONDS_PER_DAY)
    return float(end - start)


def covered_session_seconds(
    start: datetime, end: datetime, calendar: TradingCalendar | None = None
) -> float:
    """Total in-session seconds between two moments, breaks excluded.

    This is the denominator for a coverage score: how many seconds the
    instrument was actually expected to print snapshots.  Scheduled breaks, the
    close-to-open jump and non-trading days must not inflate it -- a Friday
    night session plus the following Monday spans a weekend whose "sessions"
    never happen.
    """
    if end <= start:
        return 0.0
    calendar = calendar or TradingCalendar()
    total = 0.0
    # 夜盘窗口可能从前一个自然日开始，因此多回看一天。
    day = start.date() - timedelta(days=1)
    last_day = end.date()
    while day <= last_day:
        day_key = _format_day(day)
        for session in TRADING_SESSIONS:
            if session.crosses_midnight:
                if not calendar.has_night_session(day_key):
                    continue
            elif not calendar.is_trading_day(day_key):
                continue
            window_start = _session_start(day, session)
            window_end = window_start + timedelta(seconds=_session_length_seconds(session))
            overlap_start = max(start, window_start)
            overlap_end = min(end, window_end)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds()
        day += timedelta(days=1)
    return total


#: Exchanges run a call auction in the five minutes before a session opens
#: (08:55 and 20:55) and CTP pushes those snapshots.  They are real market data.
_OPEN_AUCTION_LEAD = timedelta(minutes=5)


def is_quote_window(moment: datetime) -> bool:
    """Whether ``moment`` can carry a real quote.

    Wider than :func:`session_index` by the pre-open call auction, so that
    filtering "snapshots outside any session" does not throw away auction
    quotes.  A snapshot pushed at subscribe time (observed 20:18) still fails.
    """
    return (
        session_index(moment) is not None
        or session_index(moment + _OPEN_AUCTION_LEAD) is not None
    )


#: The two windows a scheduler starts: a day group and a night group.
DAY_SESSIONS: tuple[Session, ...] = TRADING_SESSIONS[:3]
NIGHT_SESSIONS: tuple[Session, ...] = TRADING_SESSIONS[3:]
SESSION_GROUPS: tuple[tuple[Session, ...], ...] = (DAY_SESSIONS, NIGHT_SESSIONS)


def session_index(moment: datetime) -> int | None:
    """Return the trading session containing ``moment``, else ``None``.

    Only the wall-clock time is considered, so a night session that spans
    midnight reports the same index on both sides of it.  Gap detection uses
    this: silence is a gap only between two ticks in the same session.
    """
    for index, session in enumerate(TRADING_SESSIONS):
        if _in_session(moment, session):
            return index
    return None


def group_index(moment: datetime) -> int | None:
    """Return the session group (0=day, 1=night) containing ``moment``."""
    for index, group in enumerate(SESSION_GROUPS):
        if any(_in_session(moment, session) for session in group):
            return index
    return None


def group_length_seconds(index: int) -> float:
    """Total span of one session group, breaks included."""
    group = SESSION_GROUPS[index]
    start = _hhmm_seconds(group[0].start_hhmm)
    end = _hhmm_seconds(group[-1].end_hhmm)
    if group[-1].crosses_midnight:
        return float((end - start) % _SECONDS_PER_DAY)
    return float(end - start)


def seconds_until_close(moment: datetime) -> float | None:
    """Seconds left until this session group closes, or ``None`` outside one.

    Starting mid-morning must run to the day close (15:15), not to the end of
    the current sub-session (10:15).
    """
    index = group_index(moment)
    if index is None:
        return None
    last = SESSION_GROUPS[index][-1]
    end = _hhmm_seconds(last.end_hhmm)
    seconds = _moment_seconds(moment)
    if last.crosses_midnight:
        return float(max((end - seconds) % _SECONDS_PER_DAY, 0))
    return float(max(end - seconds, 0))


def _group_of_session(number: int) -> int:
    return 0 if number < len(DAY_SESSIONS) else 1


def _next_open(moment: datetime) -> tuple[float, int] | None:
    """Return (seconds until the next session starts, its group index).

    The next start may be a later sub-session of the same group (the 13:00
    resume after the lunch break), not just a group boundary.
    """
    if group_index(moment) is not None:
        return None
    best: tuple[float, int] | None = None
    for offset in (0, 1):
        day = (moment + timedelta(days=offset)).date()
        for number, session in enumerate(TRADING_SESSIONS):
            start = _session_start(day, session)
            if start <= moment:
                continue
            delta = (start - moment).total_seconds()
            if best is None or delta < best[0]:
                best = (delta, _group_of_session(number))
    return best


def seconds_until_next_open(moment: datetime) -> float | None:
    """Seconds until the next session group opens, or ``None`` if already in one."""
    upcoming = _next_open(moment)
    return None if upcoming is None else upcoming[0]


def next_open_group_index(moment: datetime) -> int | None:
    """Index of the next session group to open, or ``None`` if already in one."""
    upcoming = _next_open(moment)
    return None if upcoming is None else upcoming[1]


def _parse_day(day: str) -> date:
    return date(int(day[0:4]), int(day[4:6]), int(day[6:8]))


def _format_day(value: date) -> str:
    return value.strftime("%Y%m%d")


@dataclass(frozen=True)
class TradingCalendar:
    """Weekday + holiday calendar for startup-time decisions."""

    holidays: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_file(cls, path: Path | str) -> TradingCalendar:
        """Load a JSON array of ``YYYYMMDD`` holidays."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(holidays=frozenset(str(item) for item in payload))

    def is_trading_day(self, day: str) -> bool:
        """Return whether ``day`` (``YYYYMMDD``) is a trading day."""
        parsed = _parse_day(day)
        if not _DAY_FIRST_WEEKDAY <= parsed.weekday() <= _DAY_LAST_WEEKDAY:
            return False
        return day not in self.holidays

    def has_night_session(self, calendar_day: str) -> bool:
        """Return whether ``calendar_day``'s evening opens a night session.

        A night session runs on the evening *before* its trading day, so:

        * Friday evening belongs to the following Monday (the weekend is a
          regular closure, not a suspended night session);
        * Saturday and Sunday evenings never trade;
        * the evening before a holiday break is suspended by the exchanges.

        Hence: the evening trades when the day itself is a trading day and
        only weekends separate it from the next trading day.  This is what a
        scheduler must ask before starting a night-session run.
        """
        if not self.is_trading_day(calendar_day):
            return False
        following = self.next_trading_day(calendar_day)
        cursor = _parse_day(calendar_day) + timedelta(days=1)
        while _format_day(cursor) < following:
            if _format_day(cursor) in self.holidays:
                return False
            cursor += timedelta(days=1)
        return True

    def previous_trading_day(self, day: str) -> str:
        """Return the nearest trading day strictly before ``day``."""
        cursor = _parse_day(day) - timedelta(days=1)
        for _ in range(366):
            candidate = _format_day(cursor)
            if self.is_trading_day(candidate):
                return candidate
            cursor -= timedelta(days=1)
        raise ValueError(f"no trading day found before {day}")

    def next_trading_day(self, day: str) -> str:
        """Return the nearest trading day strictly after ``day``."""
        cursor = _parse_day(day) + timedelta(days=1)
        for _ in range(366):
            candidate = _format_day(cursor)
            if self.is_trading_day(candidate):
                return candidate
            cursor += timedelta(days=1)
        raise ValueError(f"no trading day found after {day}")


__all__ = ["NIGHT_CLOSE_TIERS", "TradingCalendar"]
