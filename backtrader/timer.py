#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Timer Module - Time-based event scheduling.

This module provides the Timer class for scheduling time-based notifications
during backtesting. Timers can trigger at specific times, session start/end,
or at repeating intervals.

Constants:
    SESSION_TIME: Timer triggers at a specific time.
    SESSION_START: Timer triggers at session start.
    SESSION_END: Timer triggers at session end.

Example:
    Creating a timer that triggers at session start:
    >>> timer = bt.Timer(when=bt.Timer.SESSION_START, weekdays=[0, 1, 2, 3, 4])
    >>> cerebro.add_timer(timer)
"""
import bisect
import collections
from datetime import date, datetime, timedelta

from .feed import AbstractDataBase
from .parameters import ParameterDescriptor, ParameterizedBase
from .utils import TIME_MAX, date2num, num2date
from .utils.py3 import integer_types, range

#  from timer import * can only import these constants and classes
__all__ = ["SESSION_TIME", "SESSION_START", "SESSION_END", "Timer"]

# Values of these three constants
SESSION_TIME, SESSION_START, SESSION_END = range(3)


# Timer class - refactored to use new parameter system
class Timer(ParameterizedBase):
    """Timer class for scheduling time-based notifications in backtrader.

    Timers can trigger at specific times of day, session boundaries, or at
    repeating intervals. They can filter by weekdays and monthdays.

    Params:
        tid: Timer ID for identification.
        owner: Owner object of the timer.
        strats: Whether to notify strategies (default: False).
        when: When to trigger (time, SESSION_START, or SESSION_END).
        offset: Time offset for the trigger.
        repeat: Repeat interval for recurring timers.
        weekdays: List of weekdays when timer is active (0=Monday, 6=Sunday).
        weekcarry: Whether to carry over to next weekday if missed.
        monthdays: List of month days when timer is active.
        monthcarry: Whether to carry over to next month day if missed.
        allow: Callback function to allow/disallow timer on specific dates.
        tzdata: Timezone data for the timer.
        cheat: Whether timer can execute before broker.

    Example:
        >>> timer = bt.Timer(when=datetime.time(9, 30), weekdays=[0, 1, 2, 3, 4])
        >>> cerebro.add_timer(timer)
    """

    # Use new parameter descriptor system to define parameters
    tid = ParameterDescriptor(default=None, doc="Timer ID")
    owner = ParameterDescriptor(default=None, doc="Owner object of the timer")
    strats = ParameterDescriptor(default=False, type_=bool, doc="Whether to notify strategies")
    when = ParameterDescriptor(
        default=None, doc="When to trigger the timer (time, SESSION_START, or SESSION_END)"
    )
    offset = ParameterDescriptor(
        default=timedelta(), type_=timedelta, doc="Time offset for the timer"
    )
    repeat = ParameterDescriptor(
        default=timedelta(), type_=timedelta, doc="Repeat interval for the timer"
    )
    weekdays = ParameterDescriptor(
        default=[], type_=list, doc="List of weekdays when timer is active"
    )
    weekcarry = ParameterDescriptor(
        default=False, type_=bool, doc="Whether to carry over to next weekday if missed"
    )
    monthdays = ParameterDescriptor(
        default=[], type_=list, doc="List of month days when timer is active"
    )
    monthcarry = ParameterDescriptor(
        default=True, type_=bool, doc="Whether to carry over to next month day if missed"
    )
    allow = ParameterDescriptor(
        default=None, doc="Callback function to allow/disallow timer on specific dates"
    )
    tzdata = ParameterDescriptor(default=None, doc="Timezone data for the timer")
    cheat = ParameterDescriptor(
        default=False, type_=bool, doc="Whether timer can cheat (execute before broker)"
    )

    # Values of these three constants
    SESSION_TIME, SESSION_START, SESSION_END = range(3)

    # Initialize
    def __init__(self, *args, **kwargs):
        # Save passed parameters
        self.args = args
        self.kwargs = kwargs

        # Call parent class initialization
        super(Timer, self).__init__(**kwargs)

        # Initialize internal state variables
        self._weekmask = None
        self._dwhen = None
        self._dtwhen = None
        self.lastwhen = None
        self._curweek = None
        self._monthmask = None
        self._curmonth = None
        self._curdate = None
        self._nexteos = None
        self._isdata = None
        self._rstwhen = None
        self._tzdata = None

    # Start
    def start(self, data):
        # write down the 'reset when' value
        # If parameter when is not an integer
        if not isinstance(self.get_param("when"), integer_types):  # expect time/datetime
            # Reset when and set timezone data
            self._rstwhen = self.get_param("when")
            self._tzdata = self.get_param("tzdata")
        # If parameter when is an integer
        else:
            # If timezone data is None, timezone data equals data, otherwise timezone data is tzdata
            self._tzdata = data if self.get_param("tzdata") is None else self.get_param("tzdata")
            # If when equals session start time, reset time to session start time
            if self.get_param("when") == SESSION_START:
                self._rstwhen = self._tzdata.p.sessionstart
            # If when equals session end time, reset time to session end time
            elif self.get_param("when") == SESSION_END:
                self._rstwhen = self._tzdata.p.sessionend
        # Check if timezone data is data
        self._isdata = isinstance(self._tzdata, AbstractDataBase)
        # Reset when
        self._reset_when()
        # End time of this trading session
        self._nexteos = datetime.min
        # Current time
        self._curdate = date.min
        # Current month
        self._curmonth = -1  # non-existent month
        # Month mask
        self._monthmask = collections.deque()
        # Current week
        self._curweek = -1  # non-existent week
        # Week mask
        self._weekmask = collections.deque()

    # Reset when, set _when, _dtwhen, _dwhen, _lastcall
    def _reset_when(self, ddate=datetime.min):
        self._when = self._rstwhen
        self._dtwhen = self._dwhen = None
        self._lastcall = ddate

    # Check month
    def _check_month(self, ddate):
        # If no activation on specific day of month, return True
        if not self.get_param("monthdays"):
            return True
        # Month mask
        mask = self._monthmask
        # If it's a holiday, whether to carry over to next trading day
        daycarry = False
        # Month of date
        dmonth = ddate.month
        # If date's month is not equal to current month
        if dmonth != self._curmonth:
            # Current month equals passed date's month
            self._curmonth = dmonth  # write down new month
            # When parameter monthcarry is True and mask is True, carry over to next trading day. Otherwise, don't carry over
            daycarry = self.get_param("monthcarry") and bool(mask)
            # Month mask equals days activated each month
            self._monthmask = mask = collections.deque(self.get_param("monthdays"))
        # Day of month for date
        dday = ddate.day
        # Insert index in activation dates, elements left of index are less than dday, elements right of index are greater than or equal to dday
        dc = bisect.bisect_left(mask, dday)  # "left" for days before dday
        # Whether daycarry is True, if originally daycarry is True, or month date carry over and dc > 0, daycarry value is True, otherwise False
        daycarry = daycarry or (self.get_param("monthcarry") and dc > 0)
        # If dc is less than length of activation date list
        if dc < len(mask):
            # If new index is still greater than 0, increment dc by 1, otherwise curday is False
            curday = bisect.bisect_right(mask, dday, lo=dc) > 0  # check dday
            dc += curday
        else:
            curday = False
        # When dc > 0, delete one data from leftmost each time, dc decrements by 1
        while dc:
            mask.popleft()
            dc -= 1
        # Return specific daycarry value or curday value
        return daycarry or curday

    # Check week
    def _check_week(self, ddate=date.min):
        # If timer not activated on specific weekday, return True
        if not self.get_param("weekdays"):
            return True
        # Calculate current time's year, week number, weekday
        _, dweek, dwkday = ddate.isocalendar()
        # Week mask
        mask = self._weekmask
        # Don't carry over to next trading day
        daycarry = False
        # If time's week number is not equal to current week number
        if dweek != self._curweek:
            # Current week number equals passed time's week number
            self._curweek = dweek  # write down new month
            # When parameter weekcarry is True and mask is True, carry over to next trading day. Otherwise, don't carry over
            daycarry = self.get_param("weekcarry") and bool(mask)
            # Set _weekmask to weekly timer activation time
            self._weekmask = mask = collections.deque(self.get_param("weekdays"))
        # Get index of current weekday in activation date list, making numbers left of list less than current number, numbers right of list greater than or equal to current number
        dc = bisect.bisect_left(mask, dwkday)  # "left" for days before dday
        # Condition for daycarry to be True: daycarry is True, or both holiday carry over is True and dc > 0
        daycarry = daycarry or (self.get_param("weekcarry") and dc > 0)
        # If dc value is less than length of activation date sequence
        if dc < len(mask):
            # Get specific index, if index > 0, curday equals True
            curday = bisect.bisect_right(mask, dwkday, lo=dc) > 0  # check dday
            # Increment dc
            dc += curday
        else:
            curday = False
        # When dc > 0, delete one data from leftmost each time, dc decrements by 1
        while dc:
            mask.popleft()
            dc -= 1
        # Return specific daycarry value or curday value, return True if one is True, return False if both are False
        return daycarry or curday

    # Check time
    def check(self, dt):
        # Current date and time
        d = num2date(dt)
        # Current date
        ddate = d.date()
        # If last timer call equals current date, return False
        if self._lastcall == ddate:  # not repeating, awaiting date change
            return False
        # If current time is greater than this trading session's end time
        if d > self._nexteos:
            # If _tzdata is timezone data, call _getnexteos() to return specific time, otherwise use latest time of this trading session as end time
            if self._isdata:  # eos provided by data
                nexteos, _ = self._tzdata._getnexteos()
            # If _tzdata is timezone, compose current trading session's maximum time
            else:  # generic eos
                nexteos = datetime.combine(ddate, TIME_MAX)
            # End time of current day
            self._nexteos = nexteos
            # Reset timer
            self._reset_when()
        # If date's passed time is greater than current time, set current time to date's passed time
        if ddate > self._curdate:  # day change
            self._curdate = ddate
            # Check month date, if month date check returns True, check week date; if month date check is True,
            # and allow is not None, call allow(ddate) to calculate ret
            ret = self._check_month(ddate)
            if ret:
                ret = self._check_week(ddate)
            if ret and self.get_param("allow") is not None:
                ret = self.get_param("allow")(ddate)
            # If ret is False, need to reset when, return False
            if not ret:
                self._reset_when(ddate)  # this day won't make it
                return False  # timer target isn't met

        # no day change or passed month, week and allow filters on date change
        dwhen = self._dwhen
        dtwhen = self._dtwhen
        # If dtwhen is None
        if dtwhen is None:
            # dwhen represents minimum time of current day
            dwhen = datetime.combine(ddate, self._when)
            # If there is time offset, dwhen is minimum time of current day plus time offset
            if self.get_param("offset"):
                dwhen += self.get_param("offset")
            # Set _dwhen
            self._dwhen = dwhen
            # If _tzdata is data, set dwhen to dtwhen
            if self._isdata:
                self._dtwhen = dtwhen = self._tzdata.date2num(dwhen)
            # Otherwise, need to use timezone when converting to time
            else:
                self._dtwhen = dtwhen = date2num(dwhen, tz=self._tzdata)
        # If time is less than dtwhen, return False, timer target not met
        if dt < dtwhen:
            return False  # timer target isn't met
        # Record last time when occurred
        self.lastwhen = dwhen

        # If not repeating, reset when
        if not self.get_param("repeat"):  # cannot repeat
            self._reset_when(ddate)  # reset and mark as called on ddate
        # If need to repeat
        else:
            # If date's time is greater than current trading session's last time
            if d > self._nexteos:
                # If tzdata is data, get current trading session's last time
                if self._isdata:  # eos provided by data
                    nexteos, _ = self._tzdata._getnexteos()
                # If _tzdata is timezone, compose current trading session's maximum time
                else:  # generic eos
                    nexteos = datetime.combine(ddate, TIME_MAX)
                # Current trading session's last time
                self._nexteos = nexteos
            # If date time hasn't exceeded current trading day's last time, still within same trading day
            else:
                nexteos = self._nexteos
            # while loop
            while True:
                # Next when start time
                dwhen += self.get_param("repeat")
                # If dwhen exceeds current trading session's last time, reset when, exit while loop
                if dwhen > nexteos:  # if new schedule is beyond session
                    self._reset_when(ddate)  # reset to original point
                    break
                # If dwhen is greater than current time
                if dwhen > d:  # gone over current datetime
                    # Convert next timer's time to timestamp
                    self._dtwhen = dtwhen = date2num(dwhen)  # float timestamp
                    # Get the localized expected next time
                    # If _tzdata is data, calculate next timer arrival time; if _tzdata is timezone, calculate next timer arrival time considering timezone
                    if self._isdata:
                        self._dwhen = self._tzdata.num2date(dtwhen)
                    else:  # assume pytz compatible or None
                        self._dwhen = num2date(dtwhen, tz=self._tzdata)

                    break

        return True  # timer target was met
