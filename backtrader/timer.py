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


import bisect
import collections
from datetime import date, datetime, timedelta
from itertools import islice

from .feed import AbstractDataBase
from .metabase import MetaParams
from .utils import date2num, num2date
from .utils.py3 import integer_types, range, with_metaclass
from .utils import TIME_MAX


#  from timer import *  只能import这几个常量和类
__all__ = ['SESSION_TIME', 'SESSION_START', 'SESSION_END', 'Timer']

# 这三个常量的值
SESSION_TIME, SESSION_START, SESSION_END = range(3)


# Timer类
class Timer(with_metaclass(MetaParams, object)):
    # 参数，参数的含义大部分在strategy中的add_timer中进行过分析
    # 参考我的文章：https://yunjinqi.blog.csdn.net/article/details/124560191
    params = (
        ('tid', None),
        ('owner', None),
        ('strats', False),
        ('when', None),
        ('offset', timedelta()),
        ('repeat', timedelta()),
        ('weekdays', []),
        ('weekcarry', False),
        ('monthdays', []),
        ('monthcarry', True),
        ('allow', None),  # callable that allows a timer to take place
        ('tzdata', None),
        ('cheat', False),
    )

    # 这三个常量的值
    SESSION_TIME, SESSION_START, SESSION_END = range(3)

    # 初始化
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    # 开始
    def start(self, data):
        # write down the 'reset when' value
        # 如果参数when不是整数
        if not isinstance(self.p.when, integer_types):  # expect time/datetime
            # 重新设置when，并且设置时区数据
            self._rstwhen = self.p.when
            self._tzdata = self.p.tzdata
        # 如果参数when是整数的话
        else:
            # 如果时区数据是None的话，时区数据等于data,否则，时区数据就是tzdata
            self._tzdata = data if self.p.tzdata is None else self.p.tzdata
            # 如果when等于开盘时间，重新设置时间为开盘时间
            if self.p.when == SESSION_START:
                self._rstwhen = self._tzdata.p.sessionstart
            # 如果when等于收盘时间，重新设置时间为收盘时间
            elif self.p.when == SESSION_END:
                self._rstwhen = self._tzdata.p.sessionend
        # 判断时区数据是否是数据
        self._isdata = isinstance(self._tzdata, AbstractDataBase)
        # 重新设置when
        self._reset_when()
        # 这个交易日结束的时间
        self._nexteos = datetime.min
        # 当前时间
        self._curdate = date.min
        # 当前月份
        self._curmonth = -1  # non-existent month
        # 月面具
        self._monthmask = collections.deque()
        # 当前周
        self._curweek = -1  # non-existent week
        # 周面具
        self._weekmask = collections.deque()

    # 重新设置when，设置_when,_dtwhen,_dwhen,_lastcall
    def _reset_when(self, ddate=datetime.min):

        self._when = self._rstwhen
        self._dtwhen = self._dwhen = None

        self._lastcall = ddate

    # 检查月份
    def _check_month(self, ddate):
        # 如果没有设置在每月几号激活，返回True
        if not self.p.monthdays:
            return True
        # 月面具
        mask = self._monthmask
        # 如果是节假日，是否顺延到下个交易日
        daycarry = False
        # 日期的月份
        dmonth = ddate.month
        # 如果日期的月份不等于当前的月份
        if dmonth != self._curmonth:
            # 当前的月份等于传进来日期的月份
            self._curmonth = dmonth  # write down new month
            # 参数monthcarry为真的时候，同时mask为真的时候，顺延到下个交易日。否则，不顺延
            daycarry = self.p.monthcarry and bool(mask)
            # 月面具等于每个月激活的天数
            self._monthmask = mask = collections.deque(self.p.monthdays)
        # 日期的每个月的几日
        dday = ddate.day
        # 插入到激活日期中的index,index左边的元素都小于dday,index右边的元素都大于等于dday
        dc = bisect.bisect_left(mask, dday)  # "left" for days before dday
        # daycarry是否是True,如果原先是daycarry是True,或者月日期顺延并且dc大于0的话，daycarry的值是True,否则就是False
        daycarry = daycarry or (self.p.monthcarry and dc > 0)
        # 如果dc小于激活日期列表的长度
        if dc < len(mask):
            # 如果得到的新的index仍然是大于0的，那么就把dc增加1，否则，curday就是False
            curday = bisect.bisect_right(mask, dday, lo=dc) > 0  # check dday
            dc += curday
        else:
            curday = False
        # 当dc大于0的时候，每次从最左边删除一个数据，dc同时减去1
        while dc:
            mask.popleft()
            dc -= 1
        # 返回具体的daycarry的值或者curday的值
        return daycarry or curday

    # 检查周
    def _check_week(self, ddate=date.min):
        # 如果没有在周几激活定时器，返回True
        if not self.p.weekdays:
            return True
        # 计算当前时间是哪一年，多少周了，周几
        _, dweek, dwkday = ddate.isocalendar()
        # 周面具
        mask = self._weekmask
        # 不顺延到下个交易日
        daycarry = False
        # 如果时间的周数不等于当前的周数
        if dweek != self._curweek:
            # 当前周数等于传递时间的周数
            self._curweek = dweek  # write down new month
            # 参数weekcarry为真的时候，同时mask为真的时候，顺延到下个交易日。否则，不顺延
            daycarry = self.p.weekcarry and bool(mask)
            # 设置_weekmask为每周定时器激活的时间
            self._weekmask = mask = collections.deque(self.p.weekdays)
        # 获取当前星期几在激活日期列表中的index,使得列表左边的数字小于当前数字，列表右边的数字大于等于当前的数字
        dc = bisect.bisect_left(mask, dwkday)  # "left" for days before dday
        # daycarry为真的条件需要满足下面的两个之一：daycarry为真，或者同时满足节假日顺延，并且dc大于0
        daycarry = daycarry or (self.p.weekcarry and dc > 0)
        # 如果dc的值小于激活日期序列的长度
        if dc < len(mask):
            # 获取具体的index,如果index大于0，curday等于True
            curday = bisect.bisect_right(mask, dwkday, lo=dc) > 0  # check dday
            # dc加1
            dc += curday
        else:
            curday = False
        # 当dc大于0的时候，每次从最左边删除一个数据，dc同时减去1
        while dc:
            mask.popleft()
            dc -= 1
        # 返回具体的daycarry的值或者curday的值，两个有一个为真，就返回True，两个都是False的时候，回返回False
        return daycarry or curday

    # 检查时间
    def check(self, dt):
        # 当前日期和时间
        d = num2date(dt)
        # 当前日期
        ddate = d.date()
        # 如果上一次调用定时器等于当前日期，返回False
        if self._lastcall == ddate:  # not repeating, awaiting date change
            return False
        # 如果当前时间大于这个交易日结束的时间
        if d > self._nexteos:
            # 如果_tzdata是时区数据，调用_getnexteos()，返回具体的时间，否则，就把这个交易日最晚的时间作为结束时间
            if self._isdata:  # eos provided by data
                nexteos, _ = self._tzdata._getnexteos()
            # 如果_tzdata是时区的话，合成当前交易日最大的时间
            else:  # generic eos
                nexteos = datetime.combine(ddate, TIME_MAX)
            # 当天结束时间
            self._nexteos = nexteos
            # 重新设置定时器
            self._reset_when()
        # 如果日期传递的时间大于当前时间，把当前时间设置为日期传递的时间
        if ddate > self._curdate:  # day change
            self._curdate = ddate
            # 检查月日期，如果月日期检查返回是True,那么就检查周日期；如果月日期检查是True，
            # 并且allow不是None的情况下，调用allow(ddate)计算ret
            ret = self._check_month(ddate)
            if ret:
                ret = self._check_week(ddate)
            if ret and self.p.allow is not None:
                ret = self.p.allow(ddate)
            # 如果ret是False的时候，需要重新设置when,返回False
            if not ret:
                self._reset_when(ddate)  # this day won't make it
                return False  # timer target not met

        # no day change or passed month, week and allow filters on date change
        dwhen = self._dwhen
        dtwhen = self._dtwhen
        # 如果dtwhen是None的话
        if dtwhen is None:
            # dwhen代表当天最小的时间
            dwhen = datetime.combine(ddate, self._when)
            # 如果有时间补偿的话，dwhen是加上时间补偿后的当天最小时间
            if self.p.offset:
                dwhen += self.p.offset
            # 设置_dwhen
            self._dwhen = dwhen
            # 如果_tzdata是数据的话，把dwhen设置为dtwhen
            if self._isdata:
                self._dtwhen = dtwhen = self._tzdata.date2num(dwhen)
            # 否则，转换程时间的时候需要使用时区
            else:
                self._dtwhen = dtwhen = date2num(dwhen, tz=self._tzdata)
        # 如果时间小于dtwhen，返回False,没有满足定时器的目标
        if dt < dtwhen:
            return False  # timer target not met
        # 记录上次when是什么时间发生的
        self.lastwhen = dwhen  # record when the last timer "when" happened

        # 如果不重复的话，重置when
        if not self.p.repeat:  # cannot repeat
            self._reset_when(ddate)  # reset and mark as called on ddate
        # 如果需要重复的话
        else:
            # 如果日期的时间大于当前交易日最后的时间
            if d > self._nexteos:
                # 如果tzdata是数据的话，获取当前交易日最后的时间
                if self._isdata:  # eos provided by data
                    nexteos, _ = self._tzdata._getnexteos()
                # 如果_tzdata是时区的话，合成当前交易日最大的时间
                else:  # generic eos
                    nexteos = datetime.combine(ddate, TIME_MAX)
                # 当前交易日最后时间
                self._nexteos = nexteos
            # 如果日期时间还没有大于当前交易日的最后的时间，证明还在一个交易日内
            else:
                nexteos = self._nexteos
            # while循环
            while True:
                # 下个when开始的时间
                dwhen += self.p.repeat
                # 如果dwhen大于了当前交易日最后的时间，重设when，退出while循环
                if dwhen > nexteos:  # new schedule is beyone session
                    self._reset_when(ddate)  # reset to original point
                    break
                # 如果dwhen大于当前的时间
                if dwhen > d:  # gone over current datetime
                    # 把下个定时器的时间转化成时间戳
                    self._dtwhen = dtwhen = date2num(dwhen)  # float timestamp
                    # Get the localized expected next time
                    # 如果_tzdata是数据的话，计算下个定时器到的时间，如果_tzdata是时区的话，计算考虑时区之后的下个定时器到的时间。
                    if self._isdata:
                        self._dwhen = self._tzdata.num2date(dtwhen)
                    else:  # assume pytz compatible or None
                        self._dwhen = num2date(dtwhen, tz=self._tzdata)

                    break

        return True  # timer target was met
