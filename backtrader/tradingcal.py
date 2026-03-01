#!/usr/bin/env python
"""Trading Calendar Module - Market calendar and session handling.

This module provides trading calendar functionality for handling market
sessions, holidays, and trading days. It supports custom calendars
and pandas market calendar integration.

Classes:
    TradingCalendarBase: Base class for trading calendars.
    TradingCalendar: Standard trading calendar implementation.
    PandasMarketCalendar: Wrapper for pandas_market_cal calendars.

Constants:
    MONDAY-SUNDAY: Weekday constants.
    WEEKEND: Weekend days (Saturday, Sunday).
    ONEDAY: Timedelta of one day.

Example:
    Using a trading calendar:
    >>> cal = bt.TradingCalendar()
    >>> next_day = cal.nextday(datetime.date(2020, 1, 1))
"""

from datetime import datetime, time, timedelta

from backtrader.utils import UTC
from backtrader.utils.py3 import string_types

from .parameters import ParameterizedBase

# All classes that can be imported via "from tradingcal import *"
__all__ = ["TradingCalendarBase", "TradingCalendar", "PandasMarketCalendar"]

# Imprecision in the full time conversion to float would wrap over to next day
# if microseconds are 999,999 as defined in time.max
# Maximum time of the day
_time_max = time(hour=23, minute=59, second=59, microsecond=999990)

# Constants for seven days of the week, Monday is 0, Sunday is 6
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)
# Determine day of week, no date is 0, Monday is 1, Sunday is 7
ISONODAY, ISOMONDAY, ISOTUESDAY, ISOWEDNESDAY, ISOTHURSDAY, ISOFRIDAY, ISOSATURDAY, ISOSUNDAY = (
    range(8)
)
# Weekend is Saturday and Sunday
WEEKEND = [SATURDAY, SUNDAY]
# Whether it is weekend
ISOWEEKEND = [ISOSATURDAY, ISOSUNDAY]
# Time difference of one day
ONEDAY = timedelta(days=1)


# Trading calendar base class, defines specific methods - refactored to not use metaclass
class TradingCalendarBase(ParameterizedBase):
    """Base class for trading calendars.

    Provides methods for calculating trading days, session times,
    and determining if a day is the last trading day of a week or month.

    Methods:
        _nextday(day): Returns next trading day and isocalendar components.
        schedule(day): Returns opening and closing times for a day.
        nextday(day): Returns next trading day.
        last_weekday(day): Returns True if day is last trading day of week.
        last_monthday(day): Returns True if day is last trading day of month.
    """

    # Return the next trading day after day and calendar composition
    def _nextday(self, day):
        """
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance) and the isocalendar components

        The return value is a tuple with two parts: (nextday, (y, w, d))
        """
        raise NotImplementedError

    # Return opening and closing times of a day
    def schedule(self, day):
        """
        Returns a tuple with the opening and closing times (``datetime.time``)
        for the given ``date`` (``datetime/date`` instance)
        """
        raise NotImplementedError

    # Return the next trading day after day
    def nextday(self, day):
        """
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance)
        """
        return self._nextday(day)[0]  # 1st ret elem is next day

    # Return the week number of the next trading day after day
    def nextday_week(self, day):
        """
        Returns the iso week number of the next trading day, given a ``day``
        (datetime/date) instance
        """
        self._nextday(day)[1][1]  # 2 elem is isocal / 0 - y, 1 - wk, 2 - day

    # Calculate if the current day is the last day of this week
    def last_weekday(self, day):
        """
        Returns ``True`` if the given ``day`` (datetime/date) instance is the
        last trading day of this week
        """
        # Next day must be greater than day.
        # If the week changes are enough for
        # a week change even if the number is smaller (year change)
        return day.isocalendar()[1] != self._nextday(day)[1][1]

    # Determine if the current day is the last day of this month
    def last_monthday(self, day):
        """
        Returns ``True`` if the given ``day`` (datetime/date) instance is the
        last trading day of this month
        """
        # Next day must be greater than day.
        # If the week changes are enough for
        # a week change even if the number is smaller (year change)
        return day.month != self._nextday(day)[0].month

    # Determine if the current day is the last day of this year
    def last_yearday(self, day):
        """
        Returns ``True`` if the given ``day`` (datetime/date) instance is the
        last trading day of this month
        """
        # Next day must be greater than day.
        # If the week changes are enough for
        # a week change even if the number is smaller (year change)
        return day.year != self._nextday(day)[0].year


# Trading calendar class - refactored to not use metaclass
class TradingCalendar(TradingCalendarBase):
    """
    Wrapper of ``pandas_market_calendars`` for a trading calendar. The package
    ``pandas_market_calendar`` must be installed
    # In this class, it seems that pandas_market_calendar is not strictly required
    Params:

      - ``open`` (default ``time.min``)

        Regular start of the session

        # open, trading day start time, default is minimum time

      - ``close`` (default ``time.max``)

        Regular end of the session
        # close, trading day end time, default is maximum time

      - ``holidays`` (default ``[]``)

        List of non-trading days (``datetime.datetime`` instances)

        # holidays, holidays, list of datetime times

      - ``earlydays`` (default ``[]``)

        List of tuples determining the date and opening/closing times of days
        which do not conform to the regular trading hours when each tuple has
        (``datetime.datetime``, ``datetime.time``, ``datetime.time``)
        # earlydays, trading days with non-standard trading start and end times

      - ``offdays`` (default ``ISOWEEKEND``)

        A list of weekdays in ISO format (Monday: 1 -> Sunday: 7) in which the
        market doesn't trade. This is usually Saturday and Sunday and hence the
        default

        # offdays, non-trading dates from Monday to Sunday, usually Saturday and Sunday

    """

    # Parameters
    params = (
        ("open", time.min),
        ("close", _time_max),
        ("holidays", []),  # list of non-trading days (date)
        ("earlydays", []),  # list of tuples (date, opentime, closetime)
        ("offdays", ISOWEEKEND),  # list of non-trading (isoweekdays)
    )

    # Initialize, get these dates based on earlydays to speed up searches
    def __init__(self, **kwargs):
        """Initialize the TradingCalendar.

        Args:
            **kwargs: Keyword arguments for calendar parameters.
        """
        super().__init__(**kwargs)
        self._earlydays = [x[0] for x in self.p.earlydays]  # speed up searches

    # Get the next trading day
    def _nextday(self, day):
        """
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance) and the isocalendar components

        The return value is a tuple with two parts: (nextday, (y, w, d))
        """
        # while loop
        while True:
            # Next trading day
            day += ONEDAY
            # Get calendar information of day
            isocal = day.isocalendar()
            # If day is Saturday, Sunday or a holiday, continue loop to get next day
            if isocal[2] in self.p.offdays or day in self.p.holidays:
                continue
            # If day is not Saturday, Sunday or holiday, day is the desired next trading day
            return day, isocal

    # Get opening and closing times of day
    def schedule(self, day, tz=None):
        """
        Returns the opening and closing times for the given ``day``. If the
        method is called, the assumption is that `day` is an actual trading
        day

        The return value is a tuple with 2 components: opentime, closetime
        """
        # while loop
        while True:
            # Get date of day
            dt = day.date()
            # Try to get if trading day is in earlydays, if so, get specific opening and closing times
            # If not, opening defaults to current minimum time, closing defaults to maximum time of the day
            try:
                i = self._earlydays.index(dt)
                o, c = self.p.earlydays[i][1:]
            except ValueError:  # not found
                o, c = self.p.open, self.p.close
            # Combine closing date and time
            closing = datetime.combine(dt, c)
            # If timezone is not None, convert closing time according to timezone
            if tz is not None:
                closing = tz.localize(closing).astimezone(UTC)
                closing = closing.replace(tzinfo=None)
            # If day is greater than closing time, skip to next trading day and restart loop
            if day > closing:  # current time over eos
                day += ONEDAY
                continue
            # Opening date and time
            opening = datetime.combine(dt, o)
            # If timezone is not None, convert closing time according to timezone
            if tz is not None:
                opening = tz.localize(opening).astimezone(UTC)
                opening = opening.replace(tzinfo=None)

            return opening, closing


class PandasMarketCalendar(TradingCalendarBase):
    """
    Wrapper of ``pandas_market_calendars`` for a trading calendar. The package
    ``pandas_market_calendar`` must be installed
    # pandas_market_calendar must be installed
    Params:

      - ``calendar`` (default ``None``)

        The param ``calendar`` accepts the following:

        - string: the name of one of the calendars supported, for example,
          `NYSE`. The wrapper will attempt to get a calendar instance

        - Calendar instance: as returned by ``get_calendar('NYSE')``

        # calendar information, can be string or calendar instance

      - ``cachesize`` (default ``365``)

        Number of days to cache in advance for lookup

        # How many dates to cache in advance for convenient lookup

    See also:

      - https://github.com/rsheftel/pandas_market_calendars

      - http://pandas-market-calendars.readthedocs.io/

    """

    # Parameters
    params = (
        ("calendar", None),  # A pandas_market_calendars instance or exch name
        ("cachesize", 365),  # Number of days to cache in advance
    )

    # Initialize
    def __init__(self, **kwargs):
        """Initialize the PandasMarketCalendar.

        Args:
            **kwargs: Keyword arguments for calendar parameters.
        """
        super().__init__(**kwargs)
        self._calendar = self.p.calendar
        # If self._calendar is a string, use get_calendar to convert to calendar instance
        if isinstance(self._calendar, string_types):  # use passed mkt name
            import pandas_market_calendars as mcal

            self._calendar = mcal.get_calendar(self._calendar)
        # Create self.dcache, self.idcache, self.csize
        import pandas as pd  # guaranteed because of pandas_market_calendars

        self.dcache = pd.DatetimeIndex([0.0])
        self.idcache = pd.DataFrame(index=pd.DatetimeIndex([0.0]))
        self.csize = timedelta(days=self.p.cachesize)

    # Get the next trading day
    def _nextday(self, day):
        """
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance) and the isocalendar components

        The return value is a tuple with two parts: (nextday, (y, w, d))
        """
        day += ONEDAY
        while True:
            # Get the index where day is located
            i = self.dcache.searchsorted(day)
            # If index equals self.dcache length, dates have been used up and need to be updated
            if i == len(self.dcache):
                # keep a cache of 1 year to speed up searching
                self.dcache = self._calendar.valid_days(day, day + self.csize)
                continue
            # If can get the index where day is located from self.dcache, then convert to time
            d = self.dcache[i].to_pydatetime()
            return d, d.isocalendar()

    # Get specific opening and closing times
    def schedule(self, day, tz=None):
        """
        Returns the opening and closing times for the given ``day``. If the
        method is called, the assumption is that `day` is an actual trading
        day

        The return value is a tuple with 2 components: opentime, closetime
        """
        while True:
            # Get the index where trading day is located, then determine if calendar data needs to be updated
            i = self.idcache.index.searchsorted(day.date())
            if i == len(self.idcache):
                # keep a cache of 1 year to speed up searching
                self.idcache = self._calendar.schedule(day, day + self.csize)
                continue
            # Convert calendar information to generate tuple of opening and closing times
            st = (x.tz_localize(None) for x in self.idcache.iloc[i, 0:2])
            opening, closing = st  # Get utc naive times
            # If current day is already greater than closing time, skip to next day, update latest opening and closing times, then return
            if day > closing:  # passed time is over the sessionend
                day += ONEDAY  # wrap over to next day
                continue

            return opening.to_pydatetime(), closing.to_pydatetime()
