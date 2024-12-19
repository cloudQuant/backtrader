# python部分代码
import datetime
import math
import time as _time




# A UTC class, same as the one in the Python Docs
class _UTC(datetime.tzinfo):
    """UTC"""
    # UTC 类
    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return datetime.timedelta(0)

    def localize(self, dt):
        return dt.replace(tzinfo=self)





UTC = _UTC()



HOURS_PER_DAY = 24.0                                        # 一天24小时
MINUTES_PER_HOUR = 60.0                                     # 1小时60分钟
SECONDS_PER_MINUTE = 60.0                                   # 1分钟60秒
MUSECONDS_PER_SECOND = 1e6                                  # 1秒有多少微秒
MINUTES_PER_DAY = MINUTES_PER_HOUR * HOURS_PER_DAY          # 1天有多少分钟
SECONDS_PER_DAY = SECONDS_PER_MINUTE * MINUTES_PER_DAY      # 1天有多少秒
MUSECONDS_PER_DAY = MUSECONDS_PER_SECOND * SECONDS_PER_DAY  # 1天有多少微秒


# 下面这四个函数是经常使用的，注释完成之后，尝试使用cython进行改写，看能提高多少的运算速度
def num2date(x, tz=None, naive=True):
    # Same as matplotlib except if tz is None a naive datetime object
    # will be returned.
    """
    *x* is a float value which gives the number of days
    (fraction part represents hours, minutes, seconds) since
    0001-01-01 00:00:00 UTC *plus* *one*.
    The addition of one here is a historical artifact.  Also, note
    that the Gregorian calendar is assumed; this is not universal
    practice.  For details, see the module docstring.
    Return value is a :class:`datetime` instance in timezone *tz* (default to
    rcparams TZ value).
    If *x* is a sequence, a sequence of :class:`datetime` objects will
    be returned.
    """

    ix = int(x)                                                     # 对x进行取整数
    dt = datetime.datetime.fromordinal(ix)                          # 返回对应 Gregorian 日历时间对应的 datetime 对象
    remainder = float(x) - ix                                       # x的小数部分
    hour, remainder = divmod(HOURS_PER_DAY * remainder, 1)          # 小时
    minute, remainder = divmod(MINUTES_PER_HOUR * remainder, 1)     # 分钟
    second, remainder = divmod(SECONDS_PER_MINUTE * remainder, 1)   # 秒
    microsecond = int(MUSECONDS_PER_SECOND * remainder)             # 微妙
    # 如果微秒数小于10,舍去
    if microsecond < 10:
        microsecond = 0  # compensate for rounding errors
    # 这个写的不怎么样，True应该去掉的，没有意义
    # if True and tz is not None:
    if  tz is not None:
        # 合成时间
        dt = datetime.datetime(
            dt.year, dt.month, dt.day, int(hour), int(minute), int(second),
            microsecond, tzinfo=UTC)
        dt = dt.astimezone(tz)
        if naive:
            dt = dt.replace(tzinfo=None)
    else:
        # 如果没有传入tz信息，生成不包含时区信息的时间
        # If not tz has been passed return a non-timezoned dt
        dt = datetime.datetime(
            dt.year, dt.month, dt.day, int(hour), int(minute), int(second),
            microsecond)

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
    Convert :mod:`datetime` to the Gregorian date as UTC float days,
    preserving hours, minutes, seconds and microseconds.  Return value
    is a :func:`float`.
    """
    if tz is not None:
        dt = tz.localize(dt)

    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        delta = dt.tzinfo.utcoffset(dt)
        if delta is not None:
            dt -= delta

    base = float(dt.toordinal())
    if hasattr(dt, 'hour'):
        # base += (dt.hour / HOURS_PER_DAY +
        #          dt.minute / MINUTES_PER_DAY +
        #          dt.second / SECONDS_PER_DAY +
        #          dt.microsecond / MUSECONDS_PER_DAY
        #         )
        base = math.fsum(
            (base, dt.hour / HOURS_PER_DAY, dt.minute / MINUTES_PER_DAY,
             dt.second / SECONDS_PER_DAY, dt.microsecond / MUSECONDS_PER_DAY))

    return base

# 时间转成数字
def time2num(tm):
    """
    Converts the hour/minute/second/microsecond part of tm (datetime.datetime
    or time) to a num
    """
    num = (tm.hour / HOURS_PER_DAY +
           tm.minute / MINUTES_PER_DAY +
           tm.second / SECONDS_PER_DAY +
           tm.microsecond / MUSECONDS_PER_DAY)

    return num

if __name__=="__main__":
    pass 