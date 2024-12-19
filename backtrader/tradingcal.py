#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)


from datetime import datetime, timedelta, time

from .metabase import MetaParams
from backtrader.utils.py3 import string_types, with_metaclass
from backtrader.utils import UTC

# from tradingcal import * 可以import到的所有的类
__all__ = ['TradingCalendarBase', 'TradingCalendar', 'PandasMarketCalendar']

# Imprecission in the full time conversion to float would wrap over to next day
# if microseconds is 999999 as defined in time.max
# 每天的最大时间
_time_max = time(hour=23, minute=59, second=59, microsecond=999990)

# 一周七天的常量,周一是0，周日是6
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)
# 判断是周几，没有日期是0，周一是1，周日是7
(ISONODAY, ISOMONDAY, ISOTUESDAY, ISOWEDNESDAY, ISOTHURSDAY, ISOFRIDAY,
 ISOSATURDAY, ISOSUNDAY) = range(8)
# 周末是周六和周日
WEEKEND = [SATURDAY, SUNDAY]
# 是否是周末
ISOWEEKEND = [ISOSATURDAY, ISOSUNDAY]
# 一天的时间差
ONEDAY = timedelta(days=1)

# 交易日历基类，定义了具体的方法
class TradingCalendarBase(with_metaclass(MetaParams, object)):
    # 返回day之后的下一个交易日和日历组成
    def _nextday(self, day):
        '''
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance) and the isocalendar components

        The return value is a tuple with 2 components: (nextday, (y, w, d))
        '''
        raise NotImplementedError

    # 返回一天的开盘和收盘时间
    def schedule(self, day):
        '''
        Returns a tuple with the opening and closing times (``datetime.time``)
        for the given ``date`` (``datetime/date`` instance)
        '''
        raise NotImplementedError

    # 返回day之后的下一个交易日
    def nextday(self, day):
        '''
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance)
        '''
        return self._nextday(day)[0]  # 1st ret elem is next day

    # 返回day之后下一个交易日所在的周数
    def nextday_week(self, day):
        '''
        Returns the iso week number of the next trading day, given a ``day``
        (datetime/date) instance
        '''
        self._nextday(day)[1][1]  # 2 elem is isocal / 0 - y, 1 - wk, 2 - day

    # 计算当前day是否是这周的最后一天
    def last_weekday(self, day):
        '''
        Returns ``True`` if the given ``day`` (datetime/date) instance is the
        last trading day of this week
        '''
        # Next day must be greater than day. If the week changes is enough for
        # a week change even if the number is smaller (year change)
        return day.isocalendar()[1] != self._nextday(day)[1][1]

    # 判断当天day是否是这个月的最后一天
    def last_monthday(self, day):
        '''
        Returns ``True`` if the given ``day`` (datetime/date) instance is the
        last trading day of this month
        '''
        # Next day must be greater than day. If the week changes is enough for
        # a week change even if the number is smaller (year change)
        return day.month != self._nextday(day)[0].month

    # 判断当天day是否是这一年的最后一天
    def last_yearday(self, day):
        '''
        Returns ``True`` if the given ``day`` (datetime/date) instance is the
        last trading day of this month
        '''
        # Next day must be greater than day. If the week changes is enough for
        # a week change even if the number is smaller (year change)
        return day.year != self._nextday(day)[0].year


# 交易日历类
class TradingCalendar(TradingCalendarBase):
    '''
    Wrapper of ``pandas_market_calendars`` for a trading calendar. The package
    ``pandas_market_calendar`` must be installed
    # 在这个类里面，目前来看，似乎没有必须要安装pandas_market_calendar
    Params:

      - ``open`` (default ``time.min``)

        Regular start of the session

        # open,交易日开始时间，默认是最小的时间

      - ``close`` (default ``time.max``)

        Regular end of the session
        # close,交易日结束时间，默认是最大时间

      - ``holidays`` (default ``[]``)

        List of non-trading days (``datetime.datetime`` instances)

        # holidays，节假日，一些datetime时间组成的列表

      - ``earlydays`` (default ``[]``)

        List of tuples determining the date and opening/closing times of days
        which do not conform to the regular trading hours where each tuple has
        (``datetime.datetime``, ``datetime.time``, ``datetime.time`` )
        # earlydays,交易时间不符合常规交易日开始和结束时间的交易日

      - ``offdays`` (default ``ISOWEEKEND``)

        A list of weekdays in ISO format (Monday: 1 -> Sunday: 7) in which the
        market doesn't trade. This is usually Saturday and Sunday and hence the
        default

        # offdays,周一到周日中不交易的日期，通常是周六和周日

    '''

    # 参数
    params = (
        ('open', time.min),
        ('close', _time_max),
        ('holidays', []),  # list of non trading days (date)
        ('earlydays', []),  # list of tuples (date, opentime, closetime)
        ('offdays', ISOWEEKEND),  # list of non trading (isoweekdays)
    )

    # 初始化，根据earlydays，获取这些日期，为了加快搜索的速度
    def __init__(self):
        self._earlydays = [x[0] for x in self.p.earlydays]  # speed up searches

    # 获取下一个交易日
    def _nextday(self, day):
        '''
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance) and the isocalendar components

        The return value is a tuple with 2 components: (nextday, (y, w, d))
        '''
        # while循环
        while True:
            # 下一个交易日
            day += ONEDAY
            # 获取day的日历信息
            isocal = day.isocalendar()
            # 如果day是周六、周日或者day是节假日，继续循环，得到下一日
            if isocal[2] in self.p.offdays or day in self.p.holidays:
                continue
            # 如果day不是周六周日和节假日，day就是想要的下一个交易日
            return day, isocal

    # 获取day的开盘和收盘时间
    def schedule(self, day, tz=None):
        '''
        Returns the opening and closing times for the given ``day``. If the
        method is called, the assumption is that ``day`` is an actual trading
        day

        The return value is a tuple with 2 components: opentime, closetime
        '''
        # while循环
        while True:
            # 获取day的日期
            dt = day.date()
            # 尝试获取交易日是否在earlydays里面，如果在，根据这个得到具体的开盘和收盘时间
            # 如果不在，开盘默认是当前最小的时间，收盘默认是当天最大的时间
            try:
                i = self._earlydays.index(dt)
                o, c = self.p.earlydays[i][1:]
            except ValueError:  # not found
                o, c = self.p.open, self.p.close
            # 合成收盘日期和时间
            closing = datetime.combine(dt, c)
            # 如果时区不是None,根据时区对收盘时间进行转换
            if tz is not None:
                closing = tz.localize(closing).astimezone(UTC)
                closing = closing.replace(tzinfo=None)
            # 如果day大于收盘时间，跳到下一个交易日，然后重头开始循环
            if day > closing:  # current time over eos
                day += ONEDAY
                continue
            # 开盘日期和时间
            opening = datetime.combine(dt, o)
            # 如果时区不是None,根据时区对收盘时间进行转换
            if tz is not None:
                opening = tz.localize(opening).astimezone(UTC)
                opening = opening.replace(tzinfo=None)

            return opening, closing


class PandasMarketCalendar(TradingCalendarBase):
    '''
    Wrapper of ``pandas_market_calendars`` for a trading calendar. The package
    ``pandas_market_calendar`` must be installed
    # 必须要安装pandas_market_calendar
    Params:

      - ``calendar`` (default ``None``)

        The param ``calendar`` accepts the following:

        - string: the name of one of the calendars supported, for example
          `NYSE`. The wrapper will attempt to get a calendar instance

        - calendar instance: as returned by ``get_calendar('NYSE')``

        # calendar信息，可以是字符串，也可以是calendar的实例

      - ``cachesize`` (default ``365``)

        Number of days to cache in advance for lookup

        # 提前缓存多少的日期用于方便查找

    See also:

      - https://github.com/rsheftel/pandas_market_calendars

      - http://pandas-market-calendars.readthedocs.io/

    '''
    # 参数
    params = (
        ('calendar', None),  # A pandas_market_calendars instance or exch name
        ('cachesize', 365),  # Number of days to cache in advance
    )
    # 初始化
    def __init__(self):
        self._calendar = self.p.calendar
        # 如果self._calendar是字符串，使用get_calendar转换成calendar实例
        if isinstance(self._calendar, string_types):  # use passed mkt name
            import pandas_market_calendars as mcal
            self._calendar = mcal.get_calendar(self._calendar)
        # 创建self.dcache，self.dcache，self.csize
        import pandas as pd  # guaranteed because of pandas_market_calendars
        self.dcache = pd.DatetimeIndex([0.0])
        self.idcache = pd.DataFrame(index=pd.DatetimeIndex([0.0]))
        self.csize = timedelta(days=self.p.cachesize)

    # 获取下一个交易日
    def _nextday(self, day):
        '''
        Returns the next trading day (datetime/date instance) after ``day``
        (datetime/date instance) and the isocalendar components

        The return value is a tuple with 2 components: (nextday, (y, w, d))
        '''
        day += ONEDAY
        while True:
            # 获取day所在的index
            i = self.dcache.searchsorted(day)
            # 如果index等于self.dcache的长度，代表日期已经使用完了，需要进行更新了
            if i == len(self.dcache):
                # keep a cache of 1 year to speed up searching
                self.dcache = self._calendar.valid_days(day, day + self.csize)
                continue
            # 如果能够从self.dcache获取到day所在的index，然后转换成时间
            d = self.dcache[i].to_pydatetime()
            return d, d.isocalendar()

    # 获取具体的开盘和收盘时间
    def schedule(self, day, tz=None):
        '''
        Returns the opening and closing times for the given ``day``. If the
        method is called, the assumption is that ``day`` is an actual trading
        day

        The return value is a tuple with 2 components: opentime, closetime
        '''
        while True:
            # 获取交易日所在的index,然后判断是否需要更新日历数据
            i = self.idcache.index.searchsorted(day.date())
            if i == len(self.idcache):
                # keep a cache of 1 year to speed up searching
                self.idcache = self._calendar.schedule(day, day + self.csize)
                continue
            # 对日历信息进行转换，生成开盘时间和收盘时间的元组
            st = (x.tz_localize(None) for x in self.idcache.iloc[i, 0:2])
            opening, closing = st  # Get utc naive times
            # 如果当前的day已经大于收盘时间了，就要跳到下一日，然后更新最新的开盘时间和收盘时间，然后返回
            if day > closing:  # passed time is over the sessionend
                day += ONEDAY  # wrap over to next day
                continue

            return opening.to_pydatetime(), closing.to_pydatetime()
