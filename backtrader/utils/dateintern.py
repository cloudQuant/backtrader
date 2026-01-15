#!/usr/bin/env python
"""Date Internal Module - Date/time conversion and timezone utilities.

This module provides internal utilities for date/time conversions,
timezone handling, and numeric date representations used throughout
backtrader.

Classes:
    _UTC: UTC timezone implementation.
    _LocalTimezone: Local timezone with DST support.

Functions:
    tzparse: Parse timezone specification.
    Localizer: Add localize method to timezone objects.
    num2date: Convert numeric date to datetime.
    num2dt: Convert numeric date to date.
    num2time: Convert numeric date to time.
    date2num: Convert datetime to numeric format.
    time2num: Convert time to numeric format.

Constants:
    UTC: Singleton UTC timezone instance.
    TZLocal: Singleton local timezone instance.
    TIME_MAX: Maximum time value (23:59:59.999990).
    TIME_MIN: Minimum time value (00:00:00).
"""
import datetime
import math
import time as _time

import pytz

from .py3 import string_types

# from numba import jit

# Time difference for 0
ZERO = datetime.timedelta(0)
# Use time module's timezone attribute to return local timezone's (without DST) offset seconds from Greenwich (>0 Americas, <=0 most Europe, Asia, Africa)
# STDOFFSET represents offset when not in DST
STDOFFSET = datetime.timedelta(seconds=-_time.timezone)
# time.daylight being 0 means no DST, non-zero means DST
if _time.daylight:
    # time.altzone returns local DST timezone offset, seconds west of UTC (if one is defined)
    # DSTOFFSET offset during DST
    DSTOFFSET = datetime.timedelta(seconds=-_time.altzone)
else:
    DSTOFFSET = STDOFFSET
# DSTDIFF represents difference between DST and non-DST offsets
DSTDIFF = DSTOFFSET - STDOFFSET

# To avoid rounding errors, taking dates to next day
# Set TIME_MAX to avoid rounding errors causing dates to enter next day
TIME_MAX = datetime.time(23, 59, 59, 999990)

# To avoid rounding errors, taking dates to next day
# Set TIME_MIN to avoid rounding errors causing dates to enter next day
TIME_MIN = datetime.time.min


# Get the most recent bar update time point
def get_last_timeframe_timestamp(timestamp, time_diff):
    """Get previous whole minute timestamp based on current timestamp
    :params timestamp int, calculate from int(time.time())
    :params time_diff int, e.g. 1m timeframe using 60
    :returns timestamp int
    """
    while True:
        if timestamp % time_diff == 0:
            return timestamp
        timestamp -= 1


def get_string_tz_time(tz="Asia/Singapore", string_format="%Y-%m-%d %H:%M:%S.%f"):
    """generate string timezone datetime in particular timezone
    param: tz (str): timezone in pytz.common_timezones
    param: string_format (str): string format

    Return: now (String): timestamp
    """
    tz = pytz.timezone(tz)
    now = datetime.datetime.now(tz).strftime(string_format)
    return now


def timestamp2datetime(timestamp):
    """Convert timestamp to datetime
    param: timestamp timestamp
    param: string_format (str): string format
    Return: formatted_time (Str): timestamp
    """
    # Convert timestamp to datetime object
    dt_object = datetime.datetime.fromtimestamp(timestamp)
    return dt_object


def timestamp2datestr(timestamp):
    """Convert timestamp to string time
    param: timestamp timestamp
    param: string_format (str): string format
    Return: formatted_time (Str): timestamp
    """
    # Convert timestamp to datetime object
    dt_object = datetime.datetime.fromtimestamp(timestamp)
    # Format datetime object as string
    formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S.%f")
    return formatted_time


def datetime2timestamp(time_date, string_format="%Y-%m-%d %H:%M:%S.%f"):
    """Convert datetime to timestamp
    param: datetime_string (str): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: timestamp
    """
    # Format datetime object as timestamp
    timestamp = time_date.timestamp()
    return timestamp


def datestr2timestamp(
    datetime_string="2023-06-01 09:30:00.0", string_format="%Y-%m-%d %H:%M:%S.%f"
):
    """Convert datetime to timestamp
    param: datetime_string (str): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: timestamp
    """
    # Convert timestamp to datetime object
    time_date = datetime.datetime.strptime(datetime_string, string_format)
    # Format datetime object as timestamp
    timestamp = time_date.timestamp()
    return timestamp


def str2datetime(datetime_string="2023-06-01 09:30:00.0", string_format="%Y-%m-%d %H:%M:%S.%f"):
    """Convert string format time to datetime
    param: datetime_string (str): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: datetime
    """
    return datetime.datetime.strptime(datetime_string, string_format)


def datetime2str(datetime_obj, string_format="%Y-%m-%d %H:%M:%S.%f"):
    """Convert datetime to string format time
    param: datetime_obj (datetime): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: datetime_str
    """
    return datetime_obj.strftime(string_format)


def tzparse(tz):
    """Parse a timezone specification into a tzinfo object.

    Args:
        tz: Timezone specification (string, tzinfo object, or None).

    Returns:
        A tzinfo object. If pytz is available and tz is a string,
        returns the corresponding pytz timezone. Otherwise returns
        a Localizer-wrapped tz object.
    """
    # This function attempts to convert tz
    # If no object has been provided by the user and a timezone can be
    # found via contractdtails, then try to get it from pytz, which may or
    # may not be available.
    tzstr = isinstance(tz, string_types)
    if tz is None or not tzstr:
        return Localizer(tz)

    try:
        import pytz  # keep the import very local
    except ImportError:
        return Localizer(tz)  # nothing can be done

    tzs = tz
    if tzs == "CST":  # usual alias
        tzs = "CST6CDT"

    try:
        tz = pytz.timezone(tzs)
    except pytz.UnknownTimeZoneError:
        return Localizer(tz)  # nothing can be done

    return tz


def Localizer(tz):
    """Add a localize method to a timezone object.

    This function adds a localize method to tz objects that don't
    have one, allowing consistent timezone localization across
    different timezone implementations.

    Args:
        tz: Timezone object to add localize method to.

    Returns:
        The same timezone object with a localize method added.
    """
    # This function adds a localize method to tz, this localize method adds timezone info to dt
    # tzparse and Localizer are mainly for handling different timezones during live trading
    import types

    def localize(self, dt):
        return dt.replace(tzinfo=self)

    if tz is not None and not hasattr(tz, "localize"):
        # patch the tz instance with a bound method
        tz.localize = types.MethodType(localize, tz)

    return tz


# A UTC class, same as the one in the Python Docs
class _UTC(datetime.tzinfo):
    """UTC timezone implementation.

    A simple UTC timezone class that implements the tzinfo interface
    with zero offset (no DST).
    """

    # UTC class
    def utcoffset(self, dt):
        """Return UTC offset (always zero)."""
        return ZERO

    def tzname(self, dt):
        """Return timezone name (UTC)."""
        return "UTC"

    def dst(self, dt):
        """Return DST offset (always zero - UTC has no DST)."""
        return ZERO

    def localize(self, dt):
        """Localize a naive datetime to UTC.

        Args:
            dt: Naive datetime to localize.

        Returns:
            Datetime with UTC timezone info.
        """
        return dt.replace(tzinfo=self)


class _LocalTimezone(datetime.tzinfo):
    """Local timezone with DST support.

    Implements the local system timezone with automatic DST
    (daylight saving time) calculation.
    """

    # Timezone offset
    def utcoffset(self, dt):
        """Return the UTC offset for this timezone.

        Args:
            dt: Datetime to calculate offset for.

        Returns:
            Timedelta offset from UTC (includes DST if applicable).
        """
        if self._isdst(dt):
            return DSTOFFSET
        else:
            return STDOFFSET

    # DST offset, offset is 0 when not in DST
    def dst(self, dt):
        """Return the DST offset.

        Args:
            dt: Datetime to calculate DST offset for.

        Returns:
            Timedelta DST adjustment (zero if not in DST).
        """
        if self._isdst(dt):
            return DSTDIFF
        else:
            return ZERO

    # Possibly timezone name
    def tzname(self, dt):
        """Return the timezone name.

        Args:
            dt: Datetime to get name for.

        Returns:
            String timezone name (e.g., 'EST' or 'EDT').
        """
        return _time.tzname[self._isdst(dt)]

    # Determine if current time is DST
    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.weekday(), 0, 0)
        try:
            stamp = _time.mktime(tt)
        except (ValueError, OverflowError):
            return False  # Too far in the future, not relevant

        tt = _time.localtime(stamp)
        return tt.tm_isdst > 0

    # Add timezone info to dt
    def localize(self, dt):
        """Localize a naive datetime to this timezone.

        Args:
            dt: Naive datetime to localize.

        Returns:
            Datetime with local timezone info.
        """
        return dt.replace(tzinfo=self)


UTC = _UTC()
TZLocal = _LocalTimezone()

HOURS_PER_DAY = 24.0  # 24 hours in a day
MINUTES_PER_HOUR = 60.0  # 60 minutes in 1 hour
SECONDS_PER_MINUTE = 60.0  # 60 seconds in 1 minute
MUSECONDS_PER_SECOND = 1e6  # How many microseconds in 1 second
MINUTES_PER_DAY = MINUTES_PER_HOUR * HOURS_PER_DAY  # How many minutes in 1 day
SECONDS_PER_DAY = SECONDS_PER_MINUTE * MINUTES_PER_DAY  # How many seconds in 1 day
MUSECONDS_PER_DAY = MUSECONDS_PER_SECOND * SECONDS_PER_DAY  # How many microseconds in 1 day


# The following four functions are frequently used, after comments are completed,
# try using cython to rewrite, see how much speed can be improved


def num2date(x, tz=None, naive=True):
    # Same as matplotlib except if tz is None, a naive datetime object
    # will be returned.
    """
    *x* is a float value that gives the number of days
    (fraction part represents hours, minutes, seconds) since
    0001-01-01 00:00:00 UTC *plus* *one*.
    The addition of one here is a historical artifact.  Also, note
    that the Gregorian calendar is assumed; this is not universal
    practice.  For details, see the module docstring.
    Return value is a: class:`datetime` instance in timezone *tz* (default to
    rcparams TZ value).
    If *x* is a sequence, a sequence of: class:`datetime` objects will
    be returned.
    """
    # CRITICAL FIX: Handle invalid datetime values (0, NaN, negative)
    # ordinal must be >= 1 for datetime.fromordinal()
    if x != x or x <= 0:  # NaN check (NaN != NaN) or invalid value
        return datetime.datetime(1970, 1, 1)  # Return epoch as fallback

    ix = int(x)  # Take integer of x
    if ix < 1:
        ix = 1  # Minimum valid ordinal
    dt = datetime.datetime.fromordinal(
        ix
    )  # Return datetime object corresponding to Gregorian calendar time
    remainder = float(x) - ix  # Fractional part of x
    hour, remainder = divmod(HOURS_PER_DAY * remainder, 1)  # Hours
    minute, remainder = divmod(MINUTES_PER_HOUR * remainder, 1)  # Minutes
    second, remainder = divmod(SECONDS_PER_MINUTE * remainder, 1)  # Seconds
    microsecond = int(MUSECONDS_PER_SECOND * remainder)  # Microseconds
    # If microseconds less than 10, discard
    if microsecond < 10:
        microsecond = 0  # compensate for rounding errors
    # This is not well written, True should be removed, meaningless
    # if True and tz is not None:
    if tz is not None:
        # Compose time
        dt = datetime.datetime(
            dt.year, dt.month, dt.day, int(hour), int(minute), int(second), microsecond, tzinfo=UTC
        )
        dt = dt.astimezone(tz)
        if naive:
            dt = dt.replace(tzinfo=None)
    else:
        # If no tz info passed, generate time without timezone info
        # If not tz has been passed return a non-timezoned dt
        dt = datetime.datetime(
            dt.year, dt.month, dt.day, int(hour), int(minute), int(second), microsecond
        )

    if microsecond > 999990:  # compensate for rounding errors
        dt += datetime.timedelta(microseconds=1e6 - microsecond)

    return dt


# Convert number to date


def num2dt(num, tz=None, naive=True):
    """Convert numeric date to date object.

    Args:
        num: Numeric date value (days since 0001-01-01 UTC + 1).
        tz: Timezone for the result (optional).
        naive: If True, return naive date without timezone info.

    Returns:
        date: Date object extracted from the datetime.
    """
    return num2date(num, tz=tz, naive=naive).date()


# Convert number to time


def num2time(num, tz=None, naive=True):
    """Convert numeric date to time object.

    Args:
        num: Numeric date value (days since 0001-01-01 UTC + 1).
        tz: Timezone for the result (optional).
        naive: If True, return naive time without timezone info.

    Returns:
        time: Time object extracted from the datetime.
    """
    return num2date(num, tz=tz, naive=naive).time()


# Convert datetime to number


def date2num(dt, tz=None):
    """
    Convert: mod:`datetime` to the Gregorian date as UTC float days,
    preserving hours, minutes, seconds and microseconds.  Return value
    is a: func:`float`.
    """
    if tz is not None:
        dt = tz.localize(dt)

    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        delta = dt.tzinfo.utcoffset(dt)
        if delta is not None:
            dt -= delta

    base = float(dt.toordinal())
    if hasattr(dt, "hour"):
        # base += (dt.hour / HOURS_PER_DAY +
        #          dt.minute / MINUTES_PER_DAY +
        #          dt.second / SECONDS_PER_DAY +
        #          dt.microsecond / MUSECONDS_PER_DAY)
        base = math.fsum(
            (
                base,
                dt.hour / HOURS_PER_DAY,
                dt.minute / MINUTES_PER_DAY,
                dt.second / SECONDS_PER_DAY,
                dt.microsecond / MUSECONDS_PER_DAY,
            )
        )

    return base


# Convert time to number


def time2num(tm):
    """
    Converts the hour/minute/second/microsecond part of tm (datetime.datetime
    or time) to a num
    """
    num = (
        tm.hour / HOURS_PER_DAY
        + tm.minute / MINUTES_PER_DAY
        + tm.second / SECONDS_PER_DAY
        + tm.microsecond / MUSECONDS_PER_DAY
    )

    return num
