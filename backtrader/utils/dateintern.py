#!/usr/bin/env python
import datetime
import math
import time as _time

import pytz

from .py3 import string_types

# from numba import jit

# 0的时间差
ZERO = datetime.timedelta(0)
# 使用time模块的timezone属性可以返回当地时区（未启动夏令时）距离格林威治的偏移秒数（>0，美洲<=0大部分欧洲，亚洲，非洲）
# STDOFFSET代表非夏令时时候的偏移量
STDOFFSET = datetime.timedelta(seconds=-_time.timezone)
# time.daylight为0的时候代表没有夏令时，非0代表是夏令时
if _time.daylight:
    # time.altzone 返回当地的DST时区的偏移，在UTC西部秒数(如果有一个定义)
    # DSTOFFSET 夏令时时的偏移量
    DSTOFFSET = datetime.timedelta(seconds=-_time.altzone)
else:
    DSTOFFSET = STDOFFSET
# DSTDIFF 代表夏令时与非夏令时的偏移量的差
DSTDIFF = DSTOFFSET - STDOFFSET

# To avoid rounding errors, taking dates to next day
# 为了避免四舍五入偏差导致日期进入下一天，设定TIME_MAX
TIME_MAX = datetime.time(23, 59, 59, 999990)

# To avoid rounding errors, taking dates to next day
# 为了避免四舍五入偏差导致日期进入下一天，设定TIME_MIN
TIME_MIN = datetime.time.min


# 获取最近的一个bar更新的时间点
def get_last_timeframe_timestamp(timestamp, time_diff):
    """根据当前时间戳，获取上一个整分钟的时间戳
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
    """把时间戳转化成时间
    param: timestamp 时间戳
    param: string_format (str): string format
    Return: formatted_time (Str): timestamp
    """
    # 将时间戳转换为datetime对象
    dt_object = datetime.datetime.fromtimestamp(timestamp)
    return dt_object


def timestamp2datestr(timestamp):
    """把时间戳转化成字符串时间
    param: timestamp 时间戳
    param: string_format (str): string format
    Return: formatted_time (Str): timestamp
    """
    # 将时间戳转换为datetime对象
    dt_object = datetime.datetime.fromtimestamp(timestamp)
    # 将datetime对象格式化为字符串形式
    formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S.%f")
    return formatted_time


def datetime2timestamp(time_date, string_format="%Y-%m-%d %H:%M:%S.%f"):
    """把时间转化成时间戳
    param: datetime_string (str): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: timestamp
    """
    # 将datetime对象格式化为时间戳
    timestamp = time_date.timestamp()
    return timestamp


def datestr2timestamp(
    datetime_string="2023-06-01 09:30:00.0", string_format="%Y-%m-%d %H:%M:%S.%f"
):
    """把时间转化成时间戳
    param: datetime_string (str): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: timestamp
    """
    # 将时间戳转换为datetime对象
    time_date = datetime.datetime.strptime(datetime_string, string_format)
    # 将datetime对象格式化为时间戳
    timestamp = time_date.timestamp()
    return timestamp


def str2datetime(datetime_string="2023-06-01 09:30:00.0", string_format="%Y-%m-%d %H:%M:%S.%f"):
    """把字符串格式时间转化成时间
    param: datetime_string (str): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: datetime
    """
    return datetime.datetime.strptime(datetime_string, string_format)


def datetime2str(datetime_obj, string_format="%Y-%m-%d %H:%M:%S.%f"):
    """把时间转化成字符串格式时间
    param: datetime_obj (datetime): timezone in pytz.common_timezones
    param: string_format (str): string format
    Return: datetime_str
    """
    return datetime_obj.strftime(string_format)


def tzparse(tz):
    # 这个函数尝试对tz进行转换
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
    # 这个函数是给tz增加一个localize的方法，这个localize的方法是给dt添加一个时区信息
    # tzparse和Localizer主要是实盘的时候处理不同的时区的时候考虑到的
    import types

    def localize(self, dt):
        return dt.replace(tzinfo=self)

    if tz is not None and not hasattr(tz, "localize"):
        # patch the tz instance with a bound method
        tz.localize = types.MethodType(localize, tz)

    return tz


# A UTC class, same as the one in the Python Docs
class _UTC(datetime.tzinfo):
    """UTC"""

    # UTC 类
    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO

    def localize(self, dt):
        return dt.replace(tzinfo=self)


class _LocalTimezone(datetime.tzinfo):
    """本地时区相关的处理"""

    # 时区的偏移量
    def utcoffset(self, dt):
        if self._isdst(dt):
            return DSTOFFSET
        else:
            return STDOFFSET

    # 夏令时的偏移量，不是夏令时，偏移量为0
    def dst(self, dt):
        if self._isdst(dt):
            return DSTDIFF
        else:
            return ZERO

    # 可能是时区名称
    def tzname(self, dt):
        return _time.tzname[self._isdst(dt)]

    # 判断当前时间是否是夏令时
    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.weekday(), 0, 0)
        try:
            stamp = _time.mktime(tt)
        except (ValueError, OverflowError):
            return False  # Too far in the future, not relevant

        tt = _time.localtime(stamp)
        return tt.tm_isdst > 0

    # 给dt增加一个时区信息
    def localize(self, dt):
        return dt.replace(tzinfo=self)


UTC = _UTC()
TZLocal = _LocalTimezone()

HOURS_PER_DAY = 24.0  # 一天24小时
MINUTES_PER_HOUR = 60.0  # 1小时60分钟
SECONDS_PER_MINUTE = 60.0  # 1分钟60秒
MUSECONDS_PER_SECOND = 1e6  # 1秒有多少微秒
MINUTES_PER_DAY = MINUTES_PER_HOUR * HOURS_PER_DAY  # 1天有多少分钟
SECONDS_PER_DAY = SECONDS_PER_MINUTE * MINUTES_PER_DAY  # 1天有多少秒
MUSECONDS_PER_DAY = MUSECONDS_PER_SECOND * SECONDS_PER_DAY  # 1天有多少微秒


# 下面这四个函数是经常使用的，注释完成之后，尝试使用cython进行改写，看能提高多少的运算速度


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

    ix = int(x)  # 对x进行取整数
    dt = datetime.datetime.fromordinal(ix)  # 返回对应 Gregorian 日历时间对应的 datetime 对象
    remainder = float(x) - ix  # x的小数部分
    hour, remainder = divmod(HOURS_PER_DAY * remainder, 1)  # 小时
    minute, remainder = divmod(MINUTES_PER_HOUR * remainder, 1)  # 分钟
    second, remainder = divmod(SECONDS_PER_MINUTE * remainder, 1)  # 秒
    microsecond = int(MUSECONDS_PER_SECOND * remainder)  # 微妙
    # 如果微秒数小于10,舍去
    if microsecond < 10:
        microsecond = 0  # compensate for rounding errors
    # 这个写的不怎么样，True应该去掉的，没有意义
    # if True and tz is not None:
    if tz is not None:
        # 合成时间
        dt = datetime.datetime(
            dt.year, dt.month, dt.day, int(hour), int(minute), int(second), microsecond, tzinfo=UTC
        )
        dt = dt.astimezone(tz)
        if naive:
            dt = dt.replace(tzinfo=None)
    else:
        # 如果没有传入tz信息，生成不包含时区信息的时间
        # If not tz has been passed return a non-timezoned dt
        dt = datetime.datetime(
            dt.year, dt.month, dt.day, int(hour), int(minute), int(second), microsecond
        )

    if microsecond > 999990:  # compensate for rounding errors
        dt += datetime.timedelta(microseconds=1e6 - microsecond)

    return dt


# 数字转换成日期


def num2dt(num, tz=None, naive=True):
    return num2date(num, tz=tz, naive=naive).date()


# 数字转换成时间


def num2time(num, tz=None, naive=True):
    return num2date(num, tz=tz, naive=naive).time()


# 日期时间转换成数字


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


# 时间转成数字


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
