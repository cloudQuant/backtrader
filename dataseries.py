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

import datetime as _datetime
from datetime import datetime
import inspect

from .utils.py3 import range, with_metaclass
from .lineseries import LineSeries
from .utils import AutoOrderedDict, OrderedDict, date2num


class TimeFrame(object):
    # 给TimeFrame这个类增加9个属性，用于区分交易的周期
    (Ticks, MicroSeconds, Seconds, Minutes,
     Days, Weeks, Months, Years, NoTimeFrame) = range(1, 10)
    # 增加一个names属性值
    Names = ['', 'Ticks', 'MicroSeconds', 'Seconds', 'Minutes',
             'Days', 'Weeks', 'Months', 'Years', 'NoTimeFrame']

    names = Names  # support old naming convention


    # 类方法，获取Timeframe的周期类型
    @classmethod 
    def getname(cls, tframe, compression=None):  # backtrader自带
        # 这里面compression的默认参数设置其实并不合理，如果直接传入了默认参数，在下面对比中会报错
        # 修改默认参数为1 或者增加对compression的判断，个人感觉改为1可能更恰当一些
    # @classmethod
    # def getname(cls, tframe, compression=1):
        tname = cls.Names[tframe]
        if compression > 1 or tname == cls.Names[-1]:
            return tname  # for plural or 'NoTimeFrame' return plain entry

        # return singular if compression is 1
        # 如果compression是1的话，会返回一个单数的交易周期
        return cls.Names[tframe][:-1]

    # 类方法，获取交易周期名字的值
    @classmethod
    def TFrame(cls, name):
        return getattr(cls, name)

    # 类方法，根据交易周期的值返回交易周期的名字
    @classmethod
    def TName(cls, tframe):
        return cls.Names[tframe]


class DataSeries(LineSeries):
    # 设置plotinfo相关的值
    plotinfo = dict(plot=True, plotind=True, plotylimited=True)

    # 设置dataseries的_name属性，通常在策略中可以直接使用data._name获取data具体的值
    _name = ''
    # todo 尝试增加一个name属性，和_name一样，便于使用data.name进行访问数据，避免pycharm提醒访问私有变量
    name = _name
    # 设置_compression属性，默认是1,意味着交易周期是单数的，比如1秒，1分钟，1天，1周这样的
    _compression = 1
    # 设置_timeframe属性，默认是天
    _timeframe = TimeFrame.Days

    # 给dataseries设置常用的7个属性及他们的值
    Close, Low, High, Open, Volume, OpenInterest, DateTime = range(7)
    # dataseries中line的顺序
    LineOrder = [DateTime, Open, High, Low, Close, Volume, OpenInterest]

    # 获取dataseries的header的变量名称，
    def getwriterheaders(self):
        headers = [self._name, 'len']

        for lo in self.LineOrder:
            headers.append(self._getlinealias(lo))

        morelines = self.getlinealiases()[len(self.LineOrder):]
        headers.extend(morelines)

        return headers

    # 获取values
    def getwritervalues(self):
        l = len(self)
        values = [self._name, l]

        if l:
            values.append(self.datetime.datetime(0))
            for line in self.LineOrder[1:]:
                values.append(self.lines[line][0])
            for i in range(len(self.LineOrder), self.lines.size()):
                values.append(self.lines[i][0])
        else:
            values.extend([''] * self.lines.size())  # no values yet

        return values

    # 获取写入的信息
    def getwriterinfo(self):
        # returns dictionary with information
        info = OrderedDict()
        info['Name'] = self._name
        info['Timeframe'] = TimeFrame.TName(self._timeframe)
        info['Compression'] = self._compression

        return info


class OHLC(DataSeries):
    # 继承DataSeries，lines剔除了datetime只剩下6条
    lines = ('close', 'low', 'high', 'open', 'volume', 'openinterest',)


class OHLCDateTime(OHLC):
    # 继承DataSeries，lines只保留了datetime
    lines = (('datetime'),)


class SimpleFilterWrapper(object):
    '''Wrapper for filters added via .addfilter to turn them
    into processors.

    Filters are callables which

      - Take a ``data`` as an argument
      - Return False if the current bar has not triggered the filter
      - Return True if the current bar must be filtered

    The wrapper takes the return value and executes the bar removal
    if needed be
    '''
    # 这是一个增加过滤器的类，可以根据过滤器的需要对数据进行一定的操作比如去除
    # 这个过滤器通常是类或者是函数
    def __init__(self, data, ffilter, *args, **kwargs):
        if inspect.isclass(ffilter):
            ffilter = ffilter(data, *args, **kwargs)
            args = []
            kwargs = {}

        self.ffilter = ffilter
        self.args = args
        self.kwargs = kwargs

    def __call__(self, data):
        if self.ffilter(data, *self.args, **self.kwargs):
            data.backwards()
            return True

        return False


class _Bar(AutoOrderedDict):
    '''
    This class is a placeholder for the values of the standard lines of a
    DataBase class (from OHLCDateTime)

    It inherits from AutoOrderedDict to be able to easily return the values as
    an iterable and address the keys as attributes

    Order of definition is important and must match that of the lines
    definition in DataBase (which directly inherits from OHLCDateTime)
    '''
    # 这个bar是具有标准line的DataBase的占位符,常用于把小周期K线合成大周期K线。
    replaying = False

    # Without - 1 ... converting back to time will not work
    # Need another -1 to support timezones which may move the time forward
    MAXDATE = date2num(_datetime.datetime.max) - 2

    def __init__(self, maxdate=False):
        super(_Bar, self).__init__()
        self.bstart(maxdate=maxdate)

    def bstart(self, maxdate=False):
        '''Initializes a bar to the default not-updated vaues'''
        # 准备开始前，先初始化
        # Order is important: defined in DataSeries/OHLC/OHLCDateTime
        self.close = float('NaN')
        self.low = float('inf')
        self.high = float('-inf')
        self.open = float('NaN')
        self.volume = 0.0
        self.openinterest = 0.0
        self.datetime = self.MAXDATE if maxdate else None

    def isopen(self):
        # 判断是否已经更新过了
        '''Returns if a bar has already been updated

        Uses the fact that NaN is the value which is not equal to itself
        and ``open`` is initialized to NaN
        '''
        o = self.open
        return o == o  # False if NaN, True in other cases

    def bupdate(self, data, reopen=False):
        # 更新具体的bar
        '''Updates a bar with the values from data

        Returns True if the update was the 1st on a bar (just opened)

        Returns False otherwise
        '''
        if reopen:
            self.bstart()

        self.datetime = data.datetime[0]

        self.high = max(self.high, data.high[0])
        self.low = min(self.low, data.low[0])
        self.close = data.close[0]

        self.volume += data.volume[0]
        self.openinterest = data.openinterest[0]

        o = self.open
        if reopen or not o == o:
            self.open = data.open[0]
            return True  # just opened the bar

        return False
