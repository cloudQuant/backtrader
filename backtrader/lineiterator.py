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

import collections
import operator
import sys

from .utils.py3 import map, range, zip, with_metaclass, string_types
from .utils import DotDict

from .lineroot import LineRoot, LineSingle
from .linebuffer import LineActions, LineNum
from .lineseries import LineSeries, LineSeriesMaker
from .dataseries import DataSeries
from . import metabase


class MetaLineIterator(LineSeries.__class__):
    # 为LineIterator做一些处理工作
    def donew(cls, *args, **kwargs):
        # 创建类
        _obj, args, kwargs = \
            super(MetaLineIterator, cls).donew(*args, **kwargs)

        # Prepare to hold children that need to be calculated and
        # influence minperiod - Moved here to support LineNum below
        # 给_obj增加一个_lineiterators属性，这个是默认的字典，默认值是空列表
        _obj._lineiterators = collections.defaultdict(list)

        # Scan args for datas ... if none are found,
        # use the _owner (to have a clock)
        # 获取_obj的_mindatas值
        mindatas = _obj._mindatas
        # 最后一个参数0
        lastarg = 0
        # _obj.datas属性设置成一个空列表
        _obj.datas = []
        # 遍历args
        for arg in args:
            # 如果arg是line，使用LineSeriesMaker转化成LineSeries，增加到datas中
            if isinstance(arg, LineRoot):
                _obj.datas.append(LineSeriesMaker(arg))
            # 如果mindatas的值是0的话，直接break
            elif not mindatas:
                break  # found not data and must not be collected
            # 如果arg既不是line，mindatas还大于0的话，先对arg进行操作，尝试生成一个伪的array，然后生成一个LineDelay，添加到datas中，如果出现错误，就break
            else:
                try:
                    _obj.datas.append(LineSeriesMaker(LineNum(arg)))
                except:
                    # Not a LineNum and is not a LineSeries - bail out
                    break
            # mindatas减去1,mindatas保证要大于等于1
            mindatas = max(0, mindatas - 1)
            # lastarg加1
            lastarg += 1
        # 截取剩下的args
        newargs = args[lastarg:]

        # If no datas have been passed to an indicator ... use the
        # main datas of the owner, easing up adding "self.data" ...
        # 如果_obj的datas还是空列表，并且_obj是指标类或者观察类
        if not _obj.datas and isinstance(_obj, (IndicatorBase, ObserverBase)):
            # 直接调用父类的datas给它赋值
            _obj.datas = _obj._owner.datas[0:mindatas]

        # Create a dictionary to be able to check for presence
        # lists in python use "==" operator when testing for presence with "in"
        # which doesn't really check for presence but for equality
        # 创建一个ddatas的属性
        _obj.ddatas = {x: None for x in _obj.datas}

        # For each found data add access member -
        # for the first data 2 (data and data0)
        # 设置_obj的data属性，如果datas不是空的话，默认取出来的是第一个data
        if _obj.datas:
            _obj.data = data = _obj.datas[0]
            # 给data的line设置具体的别名
            for l, line in enumerate(data.lines):
                linealias = data._getlinealias(l)
                if linealias:
                    setattr(_obj, 'data_%s' % linealias, line)
                setattr(_obj, 'data_%d' % l, line)
            # 给data、以及data的line设置具体的别名
            for d, data in enumerate(_obj.datas):
                setattr(_obj, 'data%d' % d, data)

                for l, line in enumerate(data.lines):
                    linealias = data._getlinealias(l)
                    if linealias:
                        setattr(_obj, 'data%d_%s' % (d, linealias), line)
                    setattr(_obj, 'data%d_%d' % (d, l), line)

        # Parameter values have now been set before __init__
        # 设置dnames的值，如果d设置了_name属性
        _obj.dnames = DotDict([(d._name, d)
                               for d in _obj.datas if getattr(d, '_name', '')])

        return _obj, newargs, kwargs

    def dopreinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaLineIterator, cls).dopreinit(_obj, *args, **kwargs)

        # if no datas were found use, use the _owner (to have a clock)
        # 如果没有数据被使用到，为了能够有一个时间，使用_obj._owner
        _obj.datas = _obj.datas or [_obj._owner]

        # 1st data source is our ticking clock
        # 第一个数据是我们的基准数据，用作时钟，每次next进入下一个
        _obj._clock = _obj.datas[0]

        # To automatically set the period Start by scanning the found datas
        # No calculation can take place until all datas have yielded "data"
        # A data could be an indicator and it could take x bars until
        # something is produced
        # 获取_obj的最小周期
        _obj._minperiod = \
            max([x._minperiod for x in _obj.datas] or [_obj._minperiod])

        # The lines carry at least the same minperiod as
        # that provided by the datas
        # 给每条line增加一个最小周期
        for line in _obj.lines:
            line.addminperiod(_obj._minperiod)

        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaLineIterator, cls).dopostinit(_obj, *args, **kwargs)

        # my minperiod is as large as the minperiod of my lines
        # 获取各条line中最大的一个最小周期
        _obj._minperiod = max([x._minperiod for x in _obj.lines])

        # Recalc the period
        #######
        # 暂时没有理解，为啥能够调用子类的方法。。。元编程果然神奇，我看了几遍源代码都没看懂。。。
        # 这个地方标记起来，拿到语法里面具体去研究
        #######
        _obj._periodrecalc()

        # Register (my)self as indicator to owner once
        # _minperiod has been calculated
        # 如果_owner不是None的话，那么这个_obj就是创建的一个指标，调用addindicator增加进去
        if _obj._owner is not None:
            _obj._owner.addindicator(_obj)

        return _obj, args, kwargs


class LineIterator(with_metaclass(MetaLineIterator, LineSeries)):
    # _nextforce默认是False
    _nextforce = False  # force cerebro to run in next mode (runonce=False)
    # 最小的数据数目是1
    _mindatas = 1
    # _ltype代表line的index的值，目前默认应该是0
    _ltype = LineSeries.IndType

    # plotinfo具体的信息
    plotinfo = dict(plot=True,
                    subplot=True,
                    plotname='',
                    plotskip=False,
                    plotabove=False,
                    plotlinelabels=False,
                    plotlinevalues=True,
                    plotvaluetags=True,
                    plotymargin=0.0,
                    plotyhlines=[],
                    plotyticks=[],
                    plothlines=[],
                    plotforce=False,
                    plotmaster=None,)

    def _periodrecalc(self):
        # last check in case not all lineiterators were assigned to
        # lines (directly or indirectly after some operations)
        # An example is Kaufman's Adaptive Moving Average
        # 指标
        indicators = self._lineiterators[LineIterator.IndType]
        # 指标的周期
        indperiods = [ind._minperiod for ind in indicators]
        # 指标需要满足的最小周期(这个是各个指标的最小周期都能满足)
        indminperiod = max(indperiods or [self._minperiod])
        # 更新指标的最小周期
        self.updateminperiod(indminperiod)

    def _stage2(self):
        # 设置_stage2状态
        super(LineIterator, self)._stage2()

        for data in self.datas:
            data._stage2()

        for lineiterators in self._lineiterators.values():
            for lineiterator in lineiterators:
                lineiterator._stage2()

    def _stage1(self):
        # 设置_stage1状态
        super(LineIterator, self)._stage1()

        for data in self.datas:
            data._stage1()

        for lineiterators in self._lineiterators.values():
            for lineiterator in lineiterators:
                lineiterator._stage1()

    def getindicators(self):
        # 获取指标
        return self._lineiterators[LineIterator.IndType]

    def getindicators_lines(self):
        # 获取指标的lines
        return [x for x in self._lineiterators[LineIterator.IndType]
                if hasattr(x.lines, 'getlinealiases')]

    def getobservers(self):
        # 获取观察者
        return self._lineiterators[LineIterator.ObsType]

    def addindicator(self, indicator):
        # store in right queue
        # 增加指标
        self._lineiterators[indicator._ltype].append(indicator)

        # use getattr because line buffers don't have this attribute
        if getattr(indicator, '_nextforce', False):
            # the indicator needs runonce=False
            o = self
            while o is not None:
                if o._ltype == LineIterator.StratType:
                    o.cerebro._disable_runonce()
                    break

                o = o._owner  # move up the hierarchy

    def bindlines(self, owner=None, own=None):
        # 给从own获取到的line的bindings中添加从owner获取到的line
        
        if not owner:
            owner = 0

        if isinstance(owner, string_types):
            owner = [owner]
        elif not isinstance(owner, collections.Iterable):
            owner = [owner]

        if not own:
            own = range(len(owner))

        if isinstance(own, string_types):
            own = [own]
        elif not isinstance(own, collections.Iterable):
            own = [own]

        for lineowner, lineown in zip(owner, own):
            if isinstance(lineowner, string_types):
                lownerref = getattr(self._owner.lines, lineowner)
            else:
                lownerref = self._owner.lines[lineowner]
            
            if isinstance(lineown, string_types):
                lownref = getattr(self.lines, lineown)
            else:
                lownref = self.lines[lineown]
            # lownref是从own属性获取到的line,lownerref是从owner获取到的属性
            lownref.addbinding(lownerref)

        return self

    # Alias which may be more readable
    # 给同一个变量设置不同的变量名称，方便调用
    bind2lines = bindlines
    bind2line = bind2lines

    def _next(self):
        # _next方法
        # 当前时间数据的长度
        clock_len = self._clk_update()
        # indicator调用_next
        for indicator in self._lineiterators[LineIterator.IndType]:
            indicator._next()

        # 调用_notify函数，目前是空函数
        self._notify()

        # 如果这个_ltype是策略类型
        if self._ltype == LineIterator.StratType:
            # supporting datas with different lengths
            # 获取minperstatus，如果小于0,就调用next,如果等于0,就调用nextstart,如果大于0,就调用prenext
            minperstatus = self._getminperstatus()
            if minperstatus < 0:
                self.next()
            elif minperstatus == 0:
                self.nextstart()  # only called for the 1st value
            else:
                self.prenext()
        # 如果line类型不是策略，那么就通过clock_len和self._minperiod来判断，大于调用next,等于调用nextstart,小于调用clock_len
        else:
            # assume indicators and others operate on same length datas
            # although the above operation can be generalized
            if clock_len > self._minperiod:
                self.next()
            elif clock_len == self._minperiod:
                self.nextstart()  # only called for the 1st value
            elif clock_len:
                self.prenext()

    def _clk_update(self):
        # 更新当前的时间的line，并返回长度
        clock_len = len(self._clock)
        if clock_len != len(self):
            self.forward()

        return clock_len

    def _once(self):
        # 调用once的相关操作
        
        self.forward(size=self._clock.buflen())

        for indicator in self._lineiterators[LineIterator.IndType]:
            indicator._once()

        for observer in self._lineiterators[LineIterator.ObsType]:
            observer.forward(size=self.buflen())

        for data in self.datas:
            data.home()

        for indicator in self._lineiterators[LineIterator.IndType]:
            indicator.home()

        for observer in self._lineiterators[LineIterator.ObsType]:
            observer.home()

        self.home()

        # These 3 remain empty for a strategy and therefore play no role
        # because a strategy will always be executed on a next basis
        # indicators are each called with its min period
        self.preonce(0, self._minperiod - 1)
        self.oncestart(self._minperiod - 1, self._minperiod)
        self.once(self._minperiod, self.buflen())

        for line in self.lines:
            line.oncebinding()

    def preonce(self, start, end):
        pass

    def oncestart(self, start, end):
        self.once(start, end)

    def once(self, start, end):
        pass

    def prenext(self):
        '''
        This method will be called before the minimum period of all
        datas/indicators have been meet for the strategy to start executing
        '''
        pass

    def nextstart(self):
        '''
        This method will be called once, exactly when the minimum period for
        all datas/indicators have been meet. The default behavior is to call
        next
        '''

        # Called once for 1st full calculation - defaults to regular next
        self.next()

    def next(self):
        '''
        This method will be called for all remaining data points when the
        minimum period for all datas/indicators have been meet.
        '''
        pass

    def _addnotification(self, *args, **kwargs):
        pass

    def _notify(self):
        pass

    def _plotinit(self):
        pass

    def qbuffer(self, savemem=0):
        # 缓存相关操作
        if savemem:
            for line in self.lines:
                line.qbuffer()

        # If called, anything under it, must save
        for obj in self._lineiterators[self.IndType]:
            obj.qbuffer(savemem=1)

        # Tell datas to adjust buffer to minimum period
        for data in self.datas:
            data.minbuffer(self._minperiod)


# This 3 subclasses can be used for identification purposes within LineIterator
# or even outside (like in LineObservers)
# for the 3 subbranches without generating circular import references

class DataAccessor(LineIterator):
    # 数据接口类
    PriceClose = DataSeries.Close
    PriceLow = DataSeries.Low
    PriceHigh = DataSeries.High
    PriceOpen = DataSeries.Open
    PriceVolume = DataSeries.Volume
    PriceOpenInteres = DataSeries.OpenInterest
    PriceDateTime = DataSeries.DateTime


class IndicatorBase(DataAccessor):
    pass


class ObserverBase(DataAccessor):
    pass


class StrategyBase(DataAccessor):
    pass


# Utility class to couple lines/lineiterators which may have different lengths
# Will only work when runonce=False is passed to Cerebro

class SingleCoupler(LineActions):
    # 单条line的操作
    def __init__(self, cdata, clock=None):
        super(SingleCoupler, self).__init__()
        self._clock = clock if clock is not None else self._owner

        self.cdata = cdata
        self.dlen = 0
        self.val = float('NaN')

    def next(self):
        if len(self.cdata) > self.dlen:
            self.val = self.cdata[0]
            self.dlen += 1

        self[0] = self.val


class MultiCoupler(LineIterator):
    # 多条line的操作
    _ltype = LineIterator.IndType

    def __init__(self):
        super(MultiCoupler, self).__init__()
        self.dlen = 0
        self.dsize = self.fullsize()  # shorcut for number of lines
        self.dvals = [float('NaN')] * self.dsize

    def next(self):
        if len(self.data) > self.dlen:
            self.dlen += 1

            for i in range(self.dsize):
                self.dvals[i] = self.data.lines[i][0]

        for i in range(self.dsize):
            self.lines[i][0] = self.dvals[i]


def LinesCoupler(cdata, clock=None, **kwargs):
    # 如果是单条line，返回SingleCoupler
    if isinstance(cdata, LineSingle):
        return SingleCoupler(cdata, clock)  # return for single line

    # 如果不是单条line，就进入下面
    cdatacls = cdata.__class__  # copy important structures before creation
    try:
        LinesCoupler.counter += 1  # counter for unique class name
    except AttributeError:
        LinesCoupler.counter = 0

    # Prepare a MultiCoupler subclass
    # 准备创建一个MultiCoupler的子类，并把cdatascls相关的信息转移到这个类上
    nclsname = str('LinesCoupler_%d' % LinesCoupler.counter)
    ncls = type(nclsname, (MultiCoupler,), {})
    thismod = sys.modules[LinesCoupler.__module__]
    setattr(thismod, ncls.__name__, ncls)
    # Replace lines et al., to get a sensible clone
    ncls.lines = cdatacls.lines
    ncls.params = cdatacls.params
    ncls.plotinfo = cdatacls.plotinfo
    ncls.plotlines = cdatacls.plotlines
    # 把这个MultiCoupler的子类实例化，
    obj = ncls(cdata, **kwargs)  # instantiate
    # The clock is set here to avoid it being interpreted as a data by the
    # LineIterator background scanning code
    # 设置clock
    if clock is None:
        clock = getattr(cdata, '_clock', None)
        if clock is not None:
            nclock = getattr(clock, '_clock', None)
            if nclock is not None:
                clock = nclock
            else:
                nclock = getattr(clock, 'data', None)
                if nclock is not None:
                    clock = nclock

        if clock is None:
            clock = obj._owner

    obj._clock = clock
    return obj


# Add an alias (which seems a lot more sensible for "Single Line" lines
LineCoupler = LinesCoupler
