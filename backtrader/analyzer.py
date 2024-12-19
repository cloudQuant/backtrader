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

import calendar
from collections import OrderedDict
import datetime
import pprint as pp

import backtrader as bt
from backtrader import TimeFrame
from backtrader.utils.py3 import MAXINT, with_metaclass


# analyzer元类
class MetaAnalyzer(bt.MetaParams):
    def donew(cls, *args, **kwargs):
        '''
        Intercept the strategy parameter
        '''
        # Create the object and set the params in place
        _obj, args, kwargs = super(MetaAnalyzer, cls).donew(*args, **kwargs)

        _obj._children = list()
        # findowner用于发现_obj的父类，bt.Strategy的实例，如果没有找到，返回None
        _obj.strategy = strategy = bt.metabase.findowner(_obj, bt.Strategy)
        # findowner用于发现_obj的父类，属于Analyzer的实例,如果没有找到，返回None
        _obj._parent = bt.metabase.findowner(_obj, Analyzer)
        # Register with a master observer if created inside one
        # findowner用于发现_obj的父类，但是属于bt.Observer的实例,如果没有找到，返回None
        masterobs = bt.metabase.findowner(_obj, bt.Observer)
        # 如果有obs的话，就把analyzer注册到obs中
        if masterobs is not None:
            masterobs._register_analyzer(_obj)
        # analyzer的数据
        _obj.datas = strategy.datas

        # For each data add aliases: for first data: data and data0
        # 如果analyzer的数据不是None的话
        if _obj.datas:
            # analyzer的data就是第一个数据
            _obj.data = data = _obj.datas[0]
            # 对于数据里面的每条line
            for l, line in enumerate(data.lines):
                # 获取line的名字
                linealias = data._getlinealias(l)
                # 如果line的名字不是None的话，设置属性
                if linealias:
                    setattr(_obj, 'data_%s' % linealias, line)
                # 根据index设置line的名称
                setattr(_obj, 'data_%d' % l, line)
            # 循环数据，给数据设置不同的名称，可以通过data_d访问
            for d, data in enumerate(_obj.datas):
                # print("d",d)
                # print("data",data)
                # print("data.lines",data.lines)
                # print("data._getlinealias(l)",data._getlinealias(l))
                setattr(_obj, 'data%d' % d, data)
                # 对不同的数据设置具体的属性名，可以通过属性名访问line
                for l, line in enumerate(data.lines):
                    linealias = data._getlinealias(l)
                    if linealias:
                        setattr(_obj, 'data%d_%s' % (d, linealias), line)
                    setattr(_obj, 'data%d_%d' % (d, l), line)
        # 调用create_analysis方法
        _obj.create_analysis()

        # Return to the normal chain
        return _obj, args, kwargs

    # dopostint，如果analyzer._perent不是None的话，把_obj注册给analyzer._perent
    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaAnalyzer, cls).dopostinit(_obj, *args, **kwargs)

        if _obj._parent is not None:
            _obj._parent._register(_obj)

        # Return to the normal chain
        return _obj, args, kwargs

# Analyzer类
class Analyzer(with_metaclass(MetaAnalyzer, object)):
    '''Analyzer base class. All analyzers are subclass of this one

    An Analyzer instance operates in the frame of a strategy and provides an
    analysis for that strategy.

    # analyzer类，所有的analyzer都是这个类的基类，一个analyzer在策略框架内操作，并且提供策略运行的分析

    Automagically set member attributes:

      - ``self.strategy`` (giving access to the *strategy* and anything
        accessible from it)

        # 访问到strategy实例

      - ``self.datas[x]`` giving access to the array of data feeds present in
        the the system, which could also be accessed via the strategy reference

      - ``self.data``, giving access to ``self.datas[0]``

      - ``self.dataX`` -> ``self.datas[X]``

      - ``self.dataX_Y`` -> ``self.datas[X].lines[Y]``

      - ``self.dataX_name`` -> ``self.datas[X].name``

      - ``self.data_name`` -> ``self.datas[0].name``

      - ``self.data_Y`` -> ``self.datas[0].lines[Y]``

      # 访问数据的方法

    This is not a *Lines* object, but the methods and operation follow the same
    design

      - ``__init__`` during instantiation and initial setup

      - ``start`` / ``stop`` to signal the begin and end of operations

      - ``prenext`` / ``nextstart`` / ``next`` family of methods that follow
        the calls made to the same methods in the strategy

      - ``notify_trade`` / ``notify_order`` / ``notify_cashvalue`` /
        ``notify_fund`` which receive the same notifications as the equivalent
        methods of the strategy

    The mode of operation is open and no pattern is preferred. As such the
    analysis can be generated with the ``next`` calls, at the end of operations
    during ``stop`` and even with a single method like ``notify_trade``

    The important thing is to override ``get_analysis`` to return a *dict-like*
    object containing the results of the analysis (the actual format is
    implementation dependent)

    # 下面的不是line对象，但是方法和操作设计方法和strategy是类似的。最重要的事情是重写get_analysis,
    # 以返回一个字典形式的对象以保存分析的结果

    '''
    # 保存结果到csv中
    csv = True
    # 获取analyzer的长度的时候，其实是计算的策略的长度
    def __len__(self):
        '''Support for invoking ``len`` on analyzers by actually returning the
        current length of the strategy the analyzer operates on'''
        return len(self.strategy)

    # 添加一个child到self._children
    def _register(self, child):
        self._children.append(child)
    # 调用_prenext,对于每个child，调用_prenext
    def _prenext(self):
        for child in self._children:
            child._prenext()
        # 调用prenext
        self.prenext()

    # 通知cash和value
    def _notify_cashvalue(self, cash, value):
        for child in self._children:
            child._notify_cashvalue(cash, value)

        self.notify_cashvalue(cash, value)
    # 通知cash,value,fundvalue,shares
    def _notify_fund(self, cash, value, fundvalue, shares):
        for child in self._children:
            child._notify_fund(cash, value, fundvalue, shares)

        self.notify_fund(cash, value, fundvalue, shares)

    # 通知trade
    def _notify_trade(self, trade):
        for child in self._children:
            child._notify_trade(trade)

        self.notify_trade(trade)

    # 通知order
    def _notify_order(self, order):
        for child in self._children:
            child._notify_order(order)

        self.notify_order(order)

    # 调用_nextstart
    def _nextstart(self):
        for child in self._children:
            child._nextstart()

        self.nextstart()

    # 调用_next
    def _next(self):
        for child in self._children:
            child._next()

        self.next()

    # 调用_start
    def _start(self):
        for child in self._children:
            child._start()

        self.start()

    # 调用_stop
    def _stop(self):
        for child in self._children:
            child._stop()

        self.stop()

    # 通知cash 和 value
    def notify_cashvalue(self, cash, value):
        '''Receives the cash/value notification before each next cycle'''
        pass

    # 通知 fund
    def notify_fund(self, cash, value, fundvalue, shares):
        '''Receives the current cash, value, fundvalue and fund shares'''
        pass

    # 通知order
    def notify_order(self, order):
        '''Receives order notifications before each next cycle'''
        pass

    # 通知 trade
    def notify_trade(self, trade):
        '''Receives trade notifications before each next cycle'''
        pass

    # next
    def next(self):
        '''Invoked for each next invocation of the strategy, once the minum
        preiod of the strategy has been reached'''
        pass

    # prenext
    def prenext(self):
        '''Invoked for each prenext invocation of the strategy, until the minimum
        period of the strategy has been reached

        The default behavior for an analyzer is to invoke ``next``
        '''
        self.next()

    # nextstart
    def nextstart(self):
        '''Invoked exactly once for the nextstart invocation of the strategy,
        when the minimum period has been first reached
        '''
        self.next()

    # start
    def start(self):
        '''Invoked to indicate the start of operations, giving the analyzer
        time to setup up needed things'''
        pass

    # stop
    def stop(self):
        '''Invoked to indicate the end of operations, giving the analyzer
        time to shut down needed things'''
        pass

    # create_analysis 会创建一个有序字典
    def create_analysis(self):
        '''Meant to be overriden by subclasses. Gives a chance to create the
        structures that hold the analysis.

        The default behaviour is to create a ``OrderedDict`` named ``rets``
        '''
        self.rets = OrderedDict()

    # 获取分析结果，会返回self.rets
    def get_analysis(self):
        '''Returns a *dict-like* object with the results of the analysis

        The keys and format of analysis results in the dictionary is
        implementation dependent.

        It is not even enforced that the result is a *dict-like object*, just
        the convention

        The default implementation returns the default OrderedDict ``rets``
        created by the default ``create_analysis`` method

        '''
        return self.rets

    # print数据，通过writerfile打印相应的数据到标准输出
    def print(self, *args, **kwargs):
        '''Prints the results returned by ``get_analysis`` via a standard
        ``Writerfile`` object, which defaults to writing things to standard
        output
        '''
        # 创建一个writer
        writer = bt.WriterFile(*args, **kwargs)
        # writer开始
        writer.start()
        # pdct代表一个空字典
        pdct = dict()
        # 用类名作为key,保存分析的结果
        pdct[self.__class__.__name__] = self.get_analysis()
        # 把pdct保存到writer中
        writer.writedict(pdct)
        # writer结束
        writer.stop()
    # 使用pprint打印相关的信息
    def pprint(self, *args, **kwargs):
        '''Prints the results returned by ``get_analysis`` using the pretty
        print Python module (*pprint*)
        '''
        pp.pprint(self.get_analysis(), *args, **kwargs)


# 周期分析元类
class MetaTimeFrameAnalyzerBase(Analyzer.__class__):
    # 如果存在_on_dt_over，改成on_dt_over
    def __new__(meta, name, bases, dct):
        # Hack to support original method name
        if '_on_dt_over' in dct:
            dct['on_dt_over'] = dct.pop('_on_dt_over')  # rename method

        return super(MetaTimeFrameAnalyzerBase, meta).__new__(meta, name,
                                                              bases, dct)

# 周期分析基类
class TimeFrameAnalyzerBase(with_metaclass(MetaTimeFrameAnalyzerBase,
                                           Analyzer)):
    # 参数
    params = (
        ('timeframe', None),
        ('compression', None),
        ('_doprenext', True),
    )

    # 开始
    def _start(self):
        # Override to add specific attributes
        # 设置交易周期，比如分钟
        self.timeframe = self.p.timeframe or self.data._timeframe
        # 设置周期的数目，比如5，
        self.compression = self.p.compression or self.data._compression

        self.dtcmp, self.dtkey = self._get_dt_cmpkey(datetime.datetime.min)
        super(TimeFrameAnalyzerBase, self)._start()

    # 调用_prenext
    def _prenext(self):
        for child in self._children:
            child._prenext()

        if self._dt_over():
            self.on_dt_over()

        if self.p._doprenext:
            self.prenext()

    # 调用_nextstart
    def _nextstart(self):
        for child in self._children:
            child._nextstart()

        if self._dt_over() or not self.p._doprenext:  # exec if no prenext
            self.on_dt_over()

        self.nextstart()

    # 调用_next
    def _next(self):
        for child in self._children:
            child._next()

        if self._dt_over():
            self.on_dt_over()

        self.next()

    # 调用on_dt_over
    def on_dt_over(self):
        pass

    # _dt_over
    def _dt_over(self):
        # 如果交易周期等于没有时间周期，dtcmp等于最大整数，dtkey等于最大时间
        if self.timeframe == TimeFrame.NoTimeFrame:
            dtcmp, dtkey = MAXINT, datetime.datetime.max
        # 否则，就调用_get_dt_cmpkey(dt)获取dtcmp, dtkey
        else:
            # With >= 1.9.x the system datetime is in the strategy
            dt = self.strategy.datetime.datetime()
            dtcmp, dtkey = self._get_dt_cmpkey(dt)
        # 如果dtcmp是None，或者dtcmp大于self.dtcmp的话
        if self.dtcmp is None or dtcmp > self.dtcmp:
            # 设置dtkey，dtkey1，dtcmp，dtcmp1返回True
            self.dtkey, self.dtkey1 = dtkey, self.dtkey
            self.dtcmp, self.dtcmp1 = dtcmp, self.dtcmp
            return True
        # 返回False
        return False

    # 获取dtcmp, dtkey
    def _get_dt_cmpkey(self, dt):
        # 如果当前的交易周期是没有时间周期的话，返回两个None
        if self.timeframe == TimeFrame.NoTimeFrame:
            return None, None
        # 如果当前的交易周期是年的话
        if self.timeframe == TimeFrame.Years:
            dtcmp = dt.year
            dtkey = datetime.date(dt.year, 12, 31)
        # 如果交易周期是月的话
        elif self.timeframe == TimeFrame.Months:
            dtcmp = dt.year * 100 + dt.month
            # 获取最后一天
            _, lastday = calendar.monthrange(dt.year, dt.month)
            # 获取每月最后一天
            dtkey = datetime.datetime(dt.year, dt.month, lastday)
        # 如果交易周期是星期的话
        elif self.timeframe == TimeFrame.Weeks:
            # 对日期返回年、周数和周几
            isoyear, isoweek, isoweekday = dt.isocalendar()
            # todo 推测这个里面乘以的数应该是1000，乘以100，有可能和months相等
            # dtcmp = isoyear * 100 + isoweek
            dtcmp = isoyear * 1000 + isoweek
            # 周末
            sunday = dt + datetime.timedelta(days=7 - isoweekday)
            # 获取每周的最后一天
            dtkey = datetime.datetime(sunday.year, sunday.month, sunday.day)
        # 如果交易周期是天的话，计算具体的dtcmp，dtkey
        elif self.timeframe == TimeFrame.Days:
            dtcmp = dt.year * 10000 + dt.month * 100 + dt.day
            dtkey = datetime.datetime(dt.year, dt.month, dt.day)
        # 如果交易周期小于天的话，调用_get_subday_cmpkey来获取
        else:
            dtcmp, dtkey = self._get_subday_cmpkey(dt)

        return dtcmp, dtkey

    # 如果交易周期小于天
    def _get_subday_cmpkey(self, dt):
        # Calculate intraday position
        # 计算当前的分钟数目
        point = dt.hour * 60 + dt.minute
        # 如果当前的交易周期小于分钟，point转换成秒
        if self.timeframe < TimeFrame.Minutes:
            point = point * 60 + dt.second
        # 如果当前的交易周期小于秒，point转变为毫秒
        if self.timeframe < TimeFrame.Seconds:
            point = point * 1e6 + dt.microsecond

        # Apply compression to update point position (comp 5 -> 200 // 5)
        # 根据周期的数目，计算当前的point
        point = point // self.compression

        # Move to next boundary
        # 移动到下个
        point += 1

        # Restore point to the timeframe units by de-applying compression
        # 计算下个point结束的点位
        point *= self.compression

        # Get hours, minutes, seconds and microseconds
        # 如果交易周期等于分钟，得到ph,pm
        if self.timeframe == TimeFrame.Minutes:
            ph, pm = divmod(point, 60)
            ps = 0
            pus = 0
        # 如果交易周期等于秒，得到ph,pm,ps
        elif self.timeframe == TimeFrame.Seconds:
            ph, pm = divmod(point, 60 * 60)
            pm, ps = divmod(pm, 60)
            pus = 0
        # 如果是毫秒，得到ph,pm,ps,pus
        elif self.timeframe == TimeFrame.MicroSeconds:
            ph, pm = divmod(point, 60 * 60 * 1e6)
            pm, psec = divmod(pm, 60 * 1e6)
            ps, pus = divmod(psec, 1e6)
        # 是否是下一天
        extradays = 0
        #  小时大于23，整除，计算是不是下一天了
        if ph > 23:  # went over midnight:
            extradays = ph // 24
            ph %= 24

        # moving 1 minor unit to the left to be in the boundary
        # pm -= self.timeframe == TimeFrame.Minutes
        # ps -= self.timeframe == TimeFrame.Seconds
        # pus -= self.timeframe == TimeFrame.MicroSeconds
        # 需要调整的时间
        tadjust = datetime.timedelta(
            minutes=self.timeframe == TimeFrame.Minutes,
            seconds=self.timeframe == TimeFrame.Seconds,
            microseconds=self.timeframe == TimeFrame.MicroSeconds)

        # Add extra day if present
        # 如果下一天是True的话，把时间调整到下一天
        if extradays:
            dt += datetime.timedelta(days=extradays)

        # Replace intraday parts with the calculated ones and update it
        # 计算dtcmp
        dtcmp = dt.replace(hour=ph, minute=pm, second=ps, microsecond=pus)
        # 对dtcmp进行调整
        dtcmp -= tadjust
        # dtkey等于dtcmp
        dtkey = dtcmp

        return dtcmp, dtkey
