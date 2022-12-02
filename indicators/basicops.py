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

import functools
import math
import operator

from ..utils.py3 import map, range

from . import Indicator


# PeriodN这个类给整个系统增加了需要满足的最小的周期
class PeriodN(Indicator):
    '''
    Base class for indicators which take a period (__init__ has to be called
    either via super or explicitly)

    This class has no defined lines
    '''
    params = (('period', 1),)

    def __init__(self):
        super(PeriodN, self).__init__()
        self.addminperiod(self.p.period)


# 使用func计算过去N个周期的数据，func是一个可调用的函数
class OperationN(PeriodN):
    '''
    Calculates "func" for a given period

    Serves as a base for classes that work with a period and can express the
    logic in a callable object

    Note:
      Base classes must provide a "func" attribute which is a callable

    Formula:
      - line = func(data, period)
    '''
    def next(self):
        self.line[0] = self.func(self.data.get(size=self.p.period))

    def once(self, start, end):
        dst = self.line.array
        src = self.data.array
        period = self.p.period
        func = self.func

        for i in range(start, end):
            dst[i] = func(src[i - period + 1: i + 1])

# 设置计算指标的时候的可调用函数
class BaseApplyN(OperationN):
    '''
    Base class for ApplyN and others which may take a ``func`` as a parameter
    but want to define the lines in the indicator.

    Calculates ``func`` for a given period where func is given as a parameter,
    aka named argument or ``kwarg``

    Formula:
      - lines[0] = func(data, period)

    Any extra lines defined beyond the first (index 0) are not calculated
    '''
    params = (('func', None),)

    def __init__(self):
        self.func = self.p.func
        super(BaseApplyN, self).__init__()

# 根据设置的可调用函数计算具体的line
class ApplyN(BaseApplyN):
    '''
    Calculates ``func`` for a given period

    Formula:
      - line = func(data, period)
    '''
    lines = ('apply',)


# 计算过去N个周期的最高价
class Highest(OperationN):
    '''
    Calculates the highest value for the data in a given period

    Uses the built-in ``max`` for the calculation

    Formula:
      - highest = max(data, period)
    '''
    alias = ('MaxN',)
    lines = ('highest',)
    func = max


# 计算过去N个周期的最低价
class Lowest(OperationN):
    '''
    Calculates the lowest value for the data in a given period

    Uses the built-in ``min`` for the calculation

    Formula:
      - lowest = min(data, period)
    '''
    alias = ('MinN',)
    lines = ('lowest',)
    func = min


# 模仿python的reduce功能
class ReduceN(OperationN):
    '''
    Calculates the Reduced value of the ``period`` data points applying
    ``function``

    Uses the built-in ``reduce`` for the calculation plus the ``func`` that
    subclassess define

    Formula:
      - reduced = reduce(function(data, period)), initializer=initializer)

    Notes:

      - In order to mimic the python ``reduce``, this indicator takes a
        ``function`` non-named argument as the 1st argument, unlike other
        Indicators which take only named arguments
    '''
    lines = ('reduced',)
    func = functools.reduce

    def __init__(self, function, **kwargs):
        if 'initializer' not in kwargs:
            self.func = functools.partial(self.func, function)
        else:
            self.func = functools.partial(self.func, function,
                                          initializer=kwargs['initializer'])

        super(ReduceN, self).__init__()


# 求过去N周期的和
class SumN(OperationN):
    '''
    Calculates the Sum of the data values over a given period

    Uses ``math.fsum`` for the calculation rather than the built-in ``sum`` to
    avoid precision errors

    Formula:
      - sumn = sum(data, period)
    '''
    lines = ('sumn',)
    func = math.fsum


# 如果过去N周期有一个是True，就返回True
class AnyN(OperationN):
    '''
    Has a value of ``True`` (stored as ``1.0`` in the lines) if *any* of the
    values in the ``period`` evaluates to non-zero (ie: ``True``)

    Uses the built-in ``any`` for the calculation

    Formula:
      - anyn = any(data, period)
    '''
    lines = ('anyn',)
    func = any

# 如果过去N周期所有的都是True，就返回True
class AllN(OperationN):
    '''
    Has a value of ``True`` (stored as ``1.0`` in the lines) if *all* of the
    values in the ``period`` evaluates to non-zero (ie: ``True``)

    Uses the built-in ``all`` for the calculation

    Formula:
      - alln = all(data, period)
    '''
    lines = ('alln',)
    func = all

# 返回满足条件的最早出现的数据
class FindFirstIndex(OperationN):
    '''
    Returns the index of the last data that satisfies equality with the
    condition generated by the parameter _evalfunc

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = first for which data[index] == _evalfunc(data)
    '''
    lines = ('index',)
    params = (('_evalfunc', None),)

    def func(self, iterable):
        m = self.p._evalfunc(iterable)
        return next(i for i, v in enumerate(reversed(iterable)) if v == m)

# 获取过去当中最早出现的最高的价格
class FindFirstIndexHighest(FindFirstIndex):
    '''
    Returns the index of the first data that is the highest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of first data which is the highest
    '''
    params = (('_evalfunc', max),)

# 获取过去当中最早出现的最低的价格
class FindFirstIndexLowest(FindFirstIndex):
    '''
    Returns the index of the first data that is the lowest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of first data which is the lowest
    '''
    params = (('_evalfunc', min),)


# 获取满足条件的最后一个的index
class FindLastIndex(OperationN):
    '''
    Returns the index of the last data that satisfies equality with the
    condition generated by the parameter _evalfunc

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = last for which data[index] == _evalfunc(data)
    '''
    lines = ('index',)
    params = (('_evalfunc', None),)

    def func(self, iterable):
        m = self.p._evalfunc(iterable)
        index = next(i for i, v in enumerate(iterable) if v == m)
        # The iterable goes from 0 -> period - 1. If the last element
        # which is the current bar is returned and without the -1 then
        # period - index = 1 ... and must be zero!
        return self.p.period - index - 1

# 获取过去当中最晚出现的最高的价格
class FindLastIndexHighest(FindLastIndex):
    '''
    Returns the index of the last data that is the highest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of last data which is the highest
    '''
    params = (('_evalfunc', max),)

# 获取过去当中最晚出现的最低的价格
class FindLastIndexLowest(FindLastIndex):
    '''
    Returns the index of the last data that is the lowest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of last data which is the lowest
    '''
    params = (('_evalfunc', min),)

# 计算累计值
class Accum(Indicator):
    '''
    Cummulative sum of the data values

    Formula:
      - accum += data
    '''
    alias = ('CumSum', 'CumulativeSum',)
    lines = ('accum',)
    params = (('seed', 0.0),)

    # xxxstart methods use the seed (starting value) and passed data to
    # construct the first value keeping the minperiod to 1 since no
    # initial look-back value is needed

    def nextstart(self):
        self.line[0] = self.p.seed + self.data[0]

    def next(self):
        self.line[0] = self.line[-1] + self.data[0]

    def oncestart(self, start, end):
        dst = self.line.array
        src = self.data.array
        prev = self.p.seed

        for i in range(start, end):
            dst[i] = prev = prev + src[i]

    def once(self, start, end):
        dst = self.line.array
        src = self.data.array
        prev = dst[start - 1]

        for i in range(start, end):
            dst[i] = prev = prev + src[i]

# 计算平均值
class Average(PeriodN):
    '''
    Averages a given data arithmetically over a period

    Formula:
      - av = data(period) / period

    See also:
      - https://en.wikipedia.org/wiki/Arithmetic_mean
    '''
    alias = ('ArithmeticMean', 'Mean',)
    lines = ('av',)

    def next(self):
        self.line[0] = \
            math.fsum(self.data.get(size=self.p.period)) / self.p.period

    def once(self, start, end):
        src = self.data.array
        dst = self.line.array
        period = self.p.period

        for i in range(start, end):
            dst[i] = math.fsum(src[i - period + 1:i + 1]) / period

# 计算指数平均值
class ExponentialSmoothing(Average):
    '''
    Averages a given data over a period using exponential smoothing

    A regular ArithmeticMean (Average) is used as the seed value considering
    the first period values of data

    Formula:
      - av = prev * (1 - alpha) + data * alpha

    See also:
      - https://en.wikipedia.org/wiki/Exponential_smoothing
    '''
    alias = ('ExpSmoothing',)
    params = (('alpha', None),)

    def __init__(self):
        self.alpha = self.p.alpha
        if self.alpha is None:
            self.alpha = 2.0 / (1.0 + self.p.period)  # def EMA value

        self.alpha1 = 1.0 - self.alpha

        super(ExponentialSmoothing, self).__init__()

    def nextstart(self):
        # Fetch the seed value from the base class calculation
        super(ExponentialSmoothing, self).next()

    def next(self):
        self.line[0] = self.line[-1] * self.alpha1 + self.data[0] * self.alpha

    def oncestart(self, start, end):
        # Fetch the seed value from the base class calculation
        super(ExponentialSmoothing, self).once(start, end)

    def once(self, start, end):
        darray = self.data.array
        larray = self.line.array
        alpha = self.alpha
        alpha1 = self.alpha1

        # Seed value from SMA calculated with the call to oncestart
        prev = larray[start - 1]
        for i in range(start, end):
            larray[i] = prev = prev * alpha1 + darray[i] * alpha

# 动态指数移动平均值
class ExponentialSmoothingDynamic(ExponentialSmoothing):
    '''
    Averages a given data over a period using exponential smoothing

    A regular ArithmeticMean (Average) is used as the seed value considering
    the first period values of data

    Note:
      - alpha is an array of values which can be calculated dynamically

    Formula:
      - av = prev * (1 - alpha) + data * alpha

    See also:
      - https://en.wikipedia.org/wiki/Exponential_smoothing
    '''
    alias = ('ExpSmoothingDynamic',)

    def __init__(self):
        super(ExponentialSmoothingDynamic, self).__init__()

        # Hack: alpha is a "line" and carries a minperiod which is not being
        # considered because this indicator makes no line assignment. It has
        # therefore to be considered manually
        minperioddiff = max(0, self.alpha._minperiod - self.p.period)
        self.lines[0].incminperiod(minperioddiff)

    def next(self):
        self.line[0] = \
            self.line[-1] * self.alpha1[0] + self.data[0] * self.alpha[0]

    def once(self, start, end):
        darray = self.data.array
        larray = self.line.array
        alpha = self.alpha.array
        alpha1 = self.alpha1.array

        # Seed value from SMA calculated with the call to oncestart
        prev = larray[start - 1]
        for i in range(start, end):
            larray[i] = prev = prev * alpha1[i] + darray[i] * alpha[i]

# 加权移动平均值
class WeightedAverage(PeriodN):
    '''
    Calculates the weighted average of the given data over a period

    The default weights (if none are provided) are linear to assigne more
    weight to the most recent data

    The result will be multiplied by a given "coef"

    Formula:
      - av = coef * sum(mul(data, period), weights)

    See:
      - https://en.wikipedia.org/wiki/Weighted_arithmetic_mean
    '''
    alias = ('AverageWeighted',)
    lines = ('av',)
    params = (('coef', 1.0), ('weights', tuple()),)

    def __init__(self):
        super(WeightedAverage, self).__init__()

    def next(self):
        data = self.data.get(size=self.p.period)
        dataweighted = map(operator.mul, data, self.p.weights)
        self.line[0] = self.p.coef * math.fsum(dataweighted)

    def once(self, start, end):
        darray = self.data.array
        larray = self.line.array
        period = self.p.period
        coef = self.p.coef
        weights = self.p.weights

        for i in range(start, end):
            data = darray[i - period + 1: i + 1]
            larray[i] = coef * math.fsum(map(operator.mul, data, weights))
