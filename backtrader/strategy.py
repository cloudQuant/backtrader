#!/usr/bin389/env python
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
import copy
import datetime
import inspect
import itertools
import operator

from .utils.py3 import (filter, keys, integer_types, iteritems, itervalues,
                        map, MAXINT, string_types, with_metaclass)

import backtrader as bt
from .lineiterator import LineIterator, StrategyBase
from .lineroot import LineSingle
from .lineseries import LineSeriesStub
from .metabase import ItemCollection, findowner
from .trade import Trade
from .utils import OrderedDict, AutoOrderedDict, AutoDictList

# 策略元类，用于策略创建的时候进行一些处理
class MetaStrategy(StrategyBase.__class__):
    _indcol = dict()
    # 支持notify_order和notify_trade的原生方法
    def __new__(meta, name, bases, dct):
        # Hack to support original method name for notify_order
        if 'notify' in dct:
            # rename 'notify' to 'notify_order'
            dct['notify_order'] = dct.pop('notify')
        if 'notify_operation' in dct:
            # rename 'notify' to 'notify_order'
            dct['notify_trade'] = dct.pop('notify_operation')

        return super(MetaStrategy, meta).__new__(meta, name, bases, dct)
    # 注册次级类
    def __init__(cls, name, bases, dct):
        '''
        Class has already been created ... register subclasses
        '''
        # Initialize the class
        super(MetaStrategy, cls).__init__(name, bases, dct)

        if not cls.aliased and \
           name != 'Strategy' and not name.startswith('_'):
            cls._indcol[name] = cls
    # 注册环境和id
    def donew(cls, *args, **kwargs):
        _obj, args, kwargs = super(MetaStrategy, cls).donew(*args, **kwargs)

        # Find the owner and store it
        # findowner用于发现_obj的父类，但是属于bt.Cerebro的实例
        _obj.env = _obj.cerebro = cerebro = findowner(_obj, bt.Cerebro)
        _obj._id = cerebro._next_stid()

        return _obj, args, kwargs
    # 初始化broker,_sizer,_orders,_orderspending,_trades,_tradespending,stats,analyzers,_alnames,writers
    # _slave_analyzers,_tradehistoryon
    def dopreinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaStrategy, cls).dopreinit(_obj, *args, **kwargs)
        _obj.broker = _obj.env.broker
        _obj._sizer = bt.sizers.FixedSize()
        _obj._orders = list()
        _obj._orderspending = list()
        _obj._trades = collections.defaultdict(AutoDictList)
        _obj._tradespending = list()

        _obj.stats = _obj.observers = ItemCollection()
        _obj.analyzers = ItemCollection()
        _obj._alnames = collections.defaultdict(itertools.count)
        _obj.writers = list()

        _obj._slave_analyzers = list()

        _obj._tradehistoryon = False

        return _obj, args, kwargs
    # 给_sizer设置策略和broker
    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaStrategy, cls).dopostinit(_obj, *args, **kwargs)

        _obj._sizer.set(_obj, _obj.broker)

        return _obj, args, kwargs

# Strategy类，用户编写策略的时候可以继承这个类
class Strategy(with_metaclass(MetaStrategy, StrategyBase)):
    '''
    Base class to be subclassed for user defined strategies.
    '''
    # line类型是策略类型
    _ltype = LineIterator.StratType
    # csv默认是True
    csv = True
    # 旧的更新时间的方法，默认是False
    _oldsync = False  # update clock using old methodology : data 0

    # keep the latest delivered data date in the line
    # 保存最新的数据的日期
    lines = ('datetime',)
    # 缓存数据
    def qbuffer(self, savemem=0, replaying=False):
        '''Enable the memory saving schemes. Possible values for ``savemem``:

          0: No savings. Each lines object keeps in memory all values

          1: All lines objects save memory, using the strictly minimum needed

        Negative values are meant to be used when plotting is required:

          -1: Indicators at Strategy Level and Observers do not enable memory
              savings (but anything declared below it does)

          -2: Same as -1 plus activation of memory saving for any indicators
              which has declared *plotinfo.plot* as False (will not be plotted)
        # 根据savemem的值执行不同的数据保存方案
        # 如果savemem等于0的话，那么所有line的数据都会被保存到内存中
        # 如果savemem等于1的话，执行保存所需要的最小的数据量，节省内存
        # 如果savemen等于-1的话，那么策略和观察者里面的指标需要保存所有的数据，但是指标里面声明的line会节省内存
        # 如果savemen等于-2的话，除了等于-1里面的，还要加上plotinfo.plot设置成False的也会节省内存
        '''
        # 如果savemem小于0
        if savemem < 0:
            # Get any attribute which labels itself as Indicator
            # 循环所有的指标
            for ind in self._lineiterators[self.IndType]:
                # 判断这个ind是否是单个line
                subsave = isinstance(ind, (LineSingle,))
                # 如果不是单个line，并且savemen等于-2,如果plotinfo.plot还是False的话，这个ind就会节省内存
                if not subsave and savemem < -1:
                    subsave = not ind.plotinfo.plot
                # 根据subsave决定是否节省内存
                ind.qbuffer(savemem=subsave)
        # 如果savemem大于0
        elif savemem > 0:
            # 对所有的数据执行节省内存计划
            for data in self.datas:
                data.qbuffer(replaying=replaying)
            # 对所有的line执行节省内存计划
            for line in self.lines:
                line.qbuffer(savemem=1)
            # Save in all object types depending on the strategy
            # 对所有的可迭代对象执行缓存计划
            for itcls in self._lineiterators:
                for it in self._lineiterators[itcls]:
                    it.qbuffer(savemem=1)
        # 其实应该还有一个等于0的时候，不操作，作者忽略了，写上去吧，逻辑上更严谨
        else:
            pass
    # 获取并设置策略运行需要的数据的最小周期
    def _periodset(self):
        # 数据的id
        dataids = [id(data) for data in self.datas]
        # 数据的最小周期
        _dminperiods = collections.defaultdict(list)
        # 循环所有的指标
        for lineiter in self._lineiterators[LineIterator.IndType]:
            # if multiple datas are used and multiple timeframes the larger
            # timeframe may place larger time constraints in calling next.
            # 获取指标的_clock属性
            clk = getattr(lineiter, '_clock', None)
            # 如果属性值是None的话
            if clk is None:
                # 获取指标父类的_clock属性值，如果还是None的话，循环下个指标
                clk = getattr(lineiter._owner, '_clock', None)
                if clk is None:
                    continue
            # 如果clk不是None的话
            while True:
                # 如果clk是数据的话，中断
                if id(clk) in dataids:
                    break  # already top-level clock (data feed)

                # See if the current clock has higher level clocks
                # 看下当前的clk是否具有进一步的_clock属性
                clk2 = getattr(clk, '_clock', None)
                # 如果clk2是None的话，获取clk父类的_clock属性值，如果这个属性值也是None的话，中断while
                if clk2 is None:
                    clk2 = getattr(clk._owner, '_clock', None)
                if clk2 is None:
                    break  # if no clock found, bail out
                # 如果clk2不是None的话，就让clk等于clk2
                clk = clk2  # keep the ref and try to go up the hierarchy
            # 这个判断似乎没有用处，能够到这里，clk肯定不是None
            if clk is None:
                continue  # no clock found, go to next

            # LineSeriesStup wraps a line and the clock is the wrapped line and
            # no the wrapper itself.
            # 如果clk是LineSeriesStub多条line对象，获取第一条line作为clk
            if isinstance(clk, LineSeriesStub):
                clk = clk.lines[0]
            # 保存最小周期
            _dminperiods[clk].append(lineiter._minperiod)
        # 最小周期设置成空列表
        self._minperiods = list()
        # 循环所有的数据
        for data in self.datas:

            # Do not only consider the data as clock but also its lines which
            # may have been individually passed as clock references and
            # discovered as clocks above

            # Initialize with data min period if any
            # 数据产生指标的line的时候需要的最小周期
            dlminperiods = _dminperiods[data]
            # 循环数据的每条line,如果line在_dminperiods中，dlminperiods需要增加一定的值
            for l in data.lines:  # search each line for min periods
                if l in _dminperiods:
                    dlminperiods += _dminperiods[l]  # found, add it

            # keep the reference to the line if any was found
            # 如果dlminperiods不是空列表，就计算最大的值最为_dminperiods[data]的值，否则就是空的列表
            _dminperiods[data] = [max(dlminperiods)] if dlminperiods else []
            # 数据的最小周期
            dminperiod = max(_dminperiods[data] or [data._minperiod])
            # 把最小周期保存到dminperiod中
            self._minperiods.append(dminperiod)

        # Set the minperiod
        # 指标的最小周期
        minperiods = \
            [x._minperiod for x in self._lineiterators[LineIterator.IndType]]
        # 把指标的最小周期和数据的最小周期的最大值作为策略运行需要的最小周期
        self._minperiod = max(minperiods or [self._minperiod])

    # 增加writer
    def _addwriter(self, writer):
        '''
        Unlike the other _addxxx functions this one receives an instance
        because the writer works at cerebro level and is only passed to the
        strategy to simplify the logic
        # 不像其他的_addxxx的函数，这个函数直接接收的是一个实例，是在cerebro中工作的，为了简化逻辑
        # 直接传送给了策略
        '''
        self.writers.append(writer)

    # 增加指标
    def _addindicator(self, indcls, *indargs, **indkwargs):
        indcls(*indargs, **indkwargs)

    # 增加analyzer,主要给observers使用，这些analyzer并不是用户添加的，和用户添加的analyzer保持分离
    def _addanalyzer_slave(self, ancls, *anargs, **ankwargs):
        '''Like _addanalyzer but meant for observers (or other entities) which
        rely on the output of an analyzer for the data. These analyzers have
        not been added by the user and are kept separate from the main
        analyzers

        Returns the created analyzer
        '''
        analyzer = ancls(*anargs, **ankwargs)
        self._slave_analyzers.append(analyzer)
        return analyzer

    # 获取analyzer_slave，todo 感觉这个语法写的有问题
    def _getanalyzer_slave(self, idx):
        return self._slave_analyzers.append[idx]

    # 增加analyzer
    def _addanalyzer(self, ancls, *anargs, **ankwargs):
        anname = ankwargs.pop('_name', '') or ancls.__name__.lower()
        nsuffix = next(self._alnames[anname])
        anname += str(nsuffix or '')  # 0 (first instance) gets no suffix
        analyzer = ancls(*anargs, **ankwargs)
        self.analyzers.append(analyzer, anname)

    # 增加observer
    def _addobserver(self, multi, obscls, *obsargs, **obskwargs):
        obsname = obskwargs.pop('obsname', '')
        if not obsname:
            obsname = obscls.__name__.lower()

        if not multi:
            newargs = list(itertools.chain(self.datas, obsargs))
            obs = obscls(*newargs, **obskwargs)
            self.stats.append(obs, obsname)
            return

        setattr(self.stats, obsname, list())
        l = getattr(self.stats, obsname)

        for data in self.datas:
            obs = obscls(data, *obsargs, **obskwargs)
            l.append(obs)
    # 检查最小周期是否满足，返回的是最小周期减去每个数据长度的最大值
    def _getminperstatus(self):
        # check the min period status connected to datas
        dlens = map(operator.sub, self._minperiods, map(len, self.datas))
        self._minperstatus = minperstatus = max(dlens)
        return minperstatus

    # 准备开始prenext
    def prenext_open(self):
        pass

    # 准备开始nextstart
    def nextstart_open(self):
        self.next_open()

    # 准备开始next
    def next_open(self):
        pass

    # 准备开始_oncepost,根据数据的状态调用不同的函数，minperstatus小于0,代表所有数据都满足了最小周期，调用next_open
    # 如果minperstatus=0,代表数据刚准备齐全，调用self.nextstart_open
    # 如果minperstatus<0,代表数据还没有准备全，调用self.prenext_open
    def _oncepost_open(self):

        minperstatus = self._minperstatus
        if minperstatus < 0:
            self.next_open()
        elif minperstatus == 0:
            self.nextstart_open()  # only called for the 1st value
        else:
            self.prenext_open()

    # _oncepost
    def _oncepost(self, dt):
        # 循环指标，如果指标数据的长度大于指标的长度了，继续运行指标
        for indicator in self._lineiterators[LineIterator.IndType]:
            if len(indicator._clock) > len(indicator):
                indicator.advance()
        # 如果是旧的数据处理方式，调用advance;如果不是旧的数据处理方式，代表策略已经初始化了，调用advance
        if self._oldsync:
            # Strategy has not been reset, the line is there
            self.advance()
        else:
            # strategy has been reset to beginning. advance step by step
            self.forward()
        # 设置时间
        self.lines.datetime[0] = dt
        # 通知
        self._notify()
        # 获取当前最小周期状态，如果所有数据都满足了，调用next
        # 如果正好所有数据都满足了，调用nextstart
        # 如果不是所有的数据都满足了，调用prenext
        minperstatus = self._getminperstatus()
        if minperstatus < 0:
            self.next()
        elif minperstatus == 0:
            self.nextstart()  # only called for the 1st value
        else:
            self.prenext()
        # 对analyzer增加最小周期状态
        self._next_analyzers(minperstatus, once=True)
        # 对observer增加最小周期状态
        self._next_observers(minperstatus, once=True)
        # 清除
        self.clear()
    # 更新数据
    def _clk_update(self):
        # 如果是旧的数据管理方法
        if self._oldsync:
            # 调用策略的_clk_uddate()方法
            clk_len = super(Strategy, self)._clk_update()
            # 设置时间
            self.lines.datetime[0] = max(d.datetime[0]
                                         for d in self.datas if len(d))
            # 返回数据长度
            return clk_len
        # 当前最新的数据长度
        newdlens = [len(d) for d in self.datas]
        # 如果新的数据长度大于旧的数据长度，就forward
        if any(nl > l for l, nl in zip(self._dlens, newdlens)):
            self.forward()
        # 设置时间，当前数据中的最大的时间
        self.lines.datetime[0] = max(d.datetime[0]
                                     for d in self.datas if len(d))
        # 旧的数据长度等于新的数据长度
        self._dlens = newdlens

        return len(self)

    # _next_open方法，这个和_once_post_open方法一样
    def _next_open(self):
        minperstatus = self._minperstatus
        if minperstatus < 0:
            self.next_open()
        elif minperstatus == 0:
            self.nextstart_open()  # only called for the 1st value
        else:
            self.prenext_open()

    # _next方法,获取最小数据周期状态，并且添加给analyzer和observer中，然后clear
    def _next(self):
        super(Strategy, self)._next()

        minperstatus = self._getminperstatus()
        self._next_analyzers(minperstatus)
        self._next_observers(minperstatus)

        self.clear()

    # 把最小周期状态传递给observer
    def _next_observers(self, minperstatus, once=False):
        # 循环observer
        for observer in self._lineiterators[LineIterator.ObsType]:
            # 对于每个observer中的每个analyzer
            for analyzer in observer._analyzers:
                # 根据最小周期状态，给analyzer使用不同的方法
                if minperstatus < 0:
                    analyzer._next()
                elif minperstatus == 0:
                    analyzer._nextstart()  # only called for the 1st value
                else:
                    analyzer._prenext()
            # 如果是once的话
            if once:
                # 如果当前数据长度大于observer的长度
                if len(self) > len(observer):
                    # 如果是使用的旧的数据管理方法，调用advance，如果不是旧的，调用forward
                    if self._oldsync:
                        observer.advance()
                    else:
                        observer.forward()
                # 根据最小周期的状态，调用不同的方法
                if minperstatus < 0:
                    observer.next()
                elif minperstatus == 0:
                    observer.nextstart()  # only called for the 1st value
                elif len(observer):
                    observer.prenext()
            # 如果不是once的话，调用_next方法
            else:
                observer._next()
    # 把最小周期状态传递到analyzer中
    def _next_analyzers(self, minperstatus, once=False):
        for analyzer in self.analyzers:
            if minperstatus < 0:
                analyzer._next()
            elif minperstatus == 0:
                analyzer._nextstart()  # only called for the 1st value
            else:
                analyzer._prenext()

    # 给时间设置具体的时区
    def _settz(self, tz):
        self.lines.datetime._settz(tz)

    # 开始
    def _start(self):
        # 获取并设置需要的最小周期
        self._periodset()
        # analyzer开始
        for analyzer in itertools.chain(self.analyzers, self._slave_analyzers):
            analyzer._start()
        # observer开始
        for obs in self.observers:
            if not isinstance(obs, list):
                obs = [obs]  # support of multi-data observers

            for o in obs:
                o._start()

        # change operators to stage 2
        # 把操作转变到第二种状态
        self._stage2()
        # 当前每个数据的长度
        self._dlens = [len(data) for data in self.datas]
        # 当前最小周期状态默认是最大的整数
        self._minperstatus = MAXINT  # start in prenext
        # 调用开始
        self.start()

    # 开始方法，可以在策略实例中重写
    def start(self):
        '''Called right before the backtesting is about to be started.'''
        pass

    # 获取writer的列名称
    def getwriterheaders(self):
        # indicator和observer是否保存到csv
        self.indobscsv = [self]
        # 对indiicator和observer进行过滤，如果它的属性csv值是True的话，代表准备进行保存
        indobs = itertools.chain(
            self.getindicators_lines(), self.getobservers())
        self.indobscsv.extend(filter(lambda x: x.csv, indobs))
        # 把headers初始化空列表
        headers = list()

        # prepare the indicators/observers data headers
        # 循环indicator和observer中需要保存的
        for iocsv in self.indobscsv:
            # 指标名称或者类名称
            name = iocsv.plotinfo.plotname or iocsv.__class__.__name__
            # 把名称，长度，和line或者line的名称添加到headers中
            headers.append(name)
            headers.append('len')
            headers.extend(iocsv.getlinealiases())
        # 返回headers
        return headers

    # 获取writer的value值
    def getwritervalues(self):
        values = list()
        # 循环indicator或者observer
        for iocsv in self.indobscsv:
            name = iocsv.plotinfo.plotname or iocsv.__class__.__name__
            values.append(name)
            lio = len(iocsv)
            values.append(lio)
            # 如果长度大于0,就获取每一个值
            if lio:
                values.extend(map(lambda l: l[0], iocsv.lines.itersize()))
            else:
                values.extend([''] * iocsv.lines.size())

        return values

    # 获取writerinfo的信息
    def getwriterinfo(self):
        # 初始化writer info为一个自动有序字典
        wrinfo = AutoOrderedDict()
        # 设置参数
        wrinfo['Params'] = self.p._getkwargs()

        sections = [
            ['Indicators', self.getindicators_lines()],
            ['Observers', self.getobservers()]
        ]
        # 循环indicator和observer
        for sectname, sectitems in sections:
            # 设置具体的值
            sinfo = wrinfo[sectname]
            for item in sectitems:
                itname = item.__class__.__name__
                sinfo[itname].Lines = item.lines.getlinealiases() or None
                sinfo[itname].Params = item.p._getkwargs() or None
        # 设置analyzer的值
        ainfo = wrinfo.Analyzers

        # Internal Value Analyzer
        ainfo.Value.Begin = self.broker.startingcash
        ainfo.Value.End = self.broker.getvalue()

        # no slave analyzers for writer
        for aname, analyzer in self.analyzers.getitems():
            ainfo[aname].Params = analyzer.p._getkwargs() or None
            ainfo[aname].Analysis = analyzer.get_analysis()

        return wrinfo

    # 结束运行
    def _stop(self):
        # 结束策略，可以在策略实例中重写
        self.stop()
        # 结束analyzer和observer的analyzer
        for analyzer in itertools.chain(self.analyzers, self._slave_analyzers):
            analyzer._stop()

        # change operators back to stage 1 - allows reuse of datas
        # 把操作状态转变为状态1,允许重新使用数据
        self._stage1()

    # 策略结束
    def stop(self):
        '''Called right before the backtesting is about to be stopped'''
        pass

    # 设置是否保存历史交易数据
    def set_tradehistory(self, onoff=True):
        self._tradehistoryon = onoff

    # 清空_orders、_orderspending,_tradespending
    def clear(self):
        self._orders.extend(self._orderspending)
        self._orderspending = list()
        self._tradespending = list()

    # 增加通知
    def _addnotification(self, order, quicknotify=False):
        # 如果不是模拟交易，把order添加到self._orderspending中
        if not order.p.simulated:
            self._orderspending.append(order)
        # 如果是快速通知状态,qorders就等于[orders],qtrades等于空列表
        if quicknotify:
            qorders = [order]
            qtrades = []
        # 如果订单成交量是0
        if not order.executed.size:
            # 如果是快速通知模式，调用_notify传递信息
            if quicknotify:
                self._notify(qorders=qorders, qtrades=qtrades)
            return
        # 获取交易的数据,如果order.data._compensate是None的话，那么tradedata就是order.data，否则就是order.data._compensate
        tradedata = order.data._compensate
        if tradedata is None:
            tradedata = order.data
        # 获取交易数据，如果能从_trades中获取交易数据，就使用最后一个作为trade，如果不能，就创建一个trade，保存到datatrades中
        datatrades = self._trades[tradedata][order.tradeid]
        if not datatrades:
            trade = Trade(data=tradedata, tradeid=order.tradeid,
                          historyon=self._tradehistoryon)
            datatrades.append(trade)
        else:
            trade = datatrades[-1]
        # 对订单的执行信息进行循环
        for exbit in order.executed.iterpending():
            # 如果执行信息是None的话，跳出循环
            if exbit is None:
                break
            # 如果执行信息是closed的
            if exbit.closed:
                # 更新trade
                trade.update(order,
                             exbit.closed,
                             exbit.price,
                             exbit.closedvalue,
                             exbit.closedcomm,
                             exbit.pnl,
                             comminfo=order.comminfo)
                # 如果trade是isclosed
                if trade.isclosed:
                    # 把trade进行复制，并添加到_tradespending
                    self._tradespending.append(copy.copy(trade))
                    # 如果需要快速通知，把trade进行复制，并添加到qtrades中
                    if quicknotify:
                        qtrades.append(copy.copy(trade))

            # Update it if needed
            # 如果订单执行信息是opened
            if exbit.opened:
                # 如果trade是关闭的，初始化一个trade，并保存到datatrades中
                if trade.isclosed:
                    trade = Trade(data=tradedata, tradeid=order.tradeid,
                                  historyon=self._tradehistoryon)
                    datatrades.append(trade)
                # 更新trade
                trade.update(order,
                             exbit.opened,
                             exbit.price,
                             exbit.openedvalue,
                             exbit.openedcomm,
                             exbit.pnl,
                             comminfo=order.comminfo)

                # This extra check covers the case in which different tradeid
                # orders have put the position down to 0 and the next order
                # "opens" a position but "closes" the trade
                # 如果trade是关闭的
                if trade.isclosed:
                    # 把trade进行复制，并添加到_tradespending
                    self._tradespending.append(copy.copy(trade))
                    # 如果需要快速通知，把trade进行复制，并添加到qtrades中
                    if quicknotify:
                        qtrades.append(copy.copy(trade))
            # 如果trade刚刚开仓
            if trade.justopened:
                # 把trade进行复制，并添加到_tradespending
                self._tradespending.append(copy.copy(trade))
                # 如果需要快速通知，把trade进行复制，并添加到qtrades中
                if quicknotify:
                    qtrades.append(copy.copy(trade))
        # 如果需要快速通知，就调用_notify
        if quicknotify:
            self._notify(qorders=qorders, qtrades=qtrades)

    # 通知
    def _notify(self, qorders=[], qtrades=[]):
        # 如果快速通知是真的话
        if self.cerebro.p.quicknotify:
            # need to know if quicknotify is on, to not reprocess pendingorders
            # and pendingtrades, which have to exist for things like observers
            # which look into it
            # 待处理的订单和交易就是qorders和qtrades
            procorders = qorders
            proctrades = qtrades
        # 否则就是保存到self._orderspending和self._tradespending中的订单和交易
        else:
            procorders = self._orderspending
            proctrades = self._tradespending

        # 循环待处理的订单
        for order in procorders:
            # 如果订单执行类型不是历史或者histnotify，通知order
            if order.exectype != order.Historical or order.histnotify:
                self.notify_order(order)
            # 对于analyzer和observer中的analyzer，通知order
            for analyzer in itertools.chain(self.analyzers,
                                            self._slave_analyzers):
                analyzer._notify_order(order)
        # 循环待处理的trade，进行通知，并对于analyzer和observer中的analyzer进行通知
        for trade in proctrades:
            self.notify_trade(trade)
            for analyzer in itertools.chain(self.analyzers,
                                            self._slave_analyzers):
                analyzer._notify_trade(trade)
        # 如果qorders是空的话，通知结束
        if qorders:
            return  # cash is notified on a regular basis
        # 如果qordes不是空的话，获取cash,value,fundvalue,fundshares
        cash = self.broker.getcash()
        value = self.broker.getvalue()
        fundvalue = self.broker.fundvalue
        fundshares = self.broker.fundshares
        # 给cashvalue通知cash和value的值，并对于analyzer和observer中的analyzer进行通知
        self.notify_cashvalue(cash, value)
        # 给fund通知cash,value，fundvalue,fundshares，并对于analyzer和observer中的analyzer进行通知
        self.notify_fund(cash, value, fundvalue, fundshares)
        for analyzer in itertools.chain(self.analyzers, self._slave_analyzers):
            analyzer._notify_cashvalue(cash, value)
            analyzer._notify_fund(cash, value, fundvalue, fundshares)

    # 增加计时器
    def add_timer(self, when,
                  offset=datetime.timedelta(), repeat=datetime.timedelta(),
                  weekdays=[], weekcarry=False,
                  monthdays=[], monthcarry=True,
                  allow=None,
                  tzdata=None, cheat=False,
                  *args, **kwargs):
        """
        **Note**: can be called during ``__init__`` or ``start``

        Schedules a timer to invoke either a specified callback or the
        ``notify_timer`` of one or more strategies.
        # 注意：可以在__init__或者start中调用，设置一个具体的计时器用于唤醒一个特定的回调或者一个或者多个策略的notify_timer
        Arguments:

          - ``when``: can be

            - ``datetime.time`` instance (see below ``tzdata``)
            - ``bt.timer.SESSION_START`` to reference a session start
            - ``bt.timer.SESSION_END`` to reference a session end

          # 可以是一个时间格式，或者timer的SESSION_START或者SESSION_END

         - ``offset`` which must be a ``datetime.timedelta`` instance

           Used to offset the value ``when``. It has a meaningful use in
           combination with ``SESSION_START`` and ``SESSION_END``, to indicated
           things like a timer being called ``15 minutes`` after the session
           start.
           # 时间补偿，必须是一个时间差的实例，用于对when进行时间补偿，比如想要在开盘15分钟的时候这样
           # 的计时器，就可以结合SESSION_START和SESSION_END进行设置

          - ``repeat`` which must be a ``datetime.timedelta`` instance

            Indicates if after a 1st call, further calls will be scheduled
            within the same session at the scheduled ``repeat`` delta

            Once the timer goes over the end of the session it is reset to the
            original value for ``when``
            # 重复，必须是一个时间差的实例；这个参数用于设置在第一次调用计时器之后，在同一个session中
            # 将会按照设置时间差不断重复；一旦session结束了之后，会重新从when开始

          - ``weekdays``: a **sorted** iterable with integers indicating on
            which days (iso codes, Monday is 1, Sunday is 7) the timers can
            be actually invoked

            If not specified, the timer will be active on all days

            # 用于设置在星期几激活，这个参数是一个排列好的可迭代的对象，用1-7的数字代表是星期几
            # 如果没有指定，任何一天都会被激活

          - ``weekcarry`` (default: ``False``). If ``True`` and the weekday was
            not seen (ex: trading holiday), the timer will be executed on the
            next day (even if in a new week)

            # 如果设置成True了，如果weekdays因为节假日的原因导致没有，将会在下一个交易日激活

          - ``monthdays``: a **sorted** iterable with integers indicating on
            which days of the month a timer has to be executed. For example
            always on day *15* of the month

            If not specified, the timer will be active on all days

            # 用于设置在几号激活，这个参数是一个排列好的可迭代的对象，用1-31的数字代表是几号
            # 如果没有指定，任何一天都会被激活

          - ``monthcarry`` (default: ``True``). If the day was not seen
            (weekend, trading holiday), the timer will be executed on the next
            available day.

            # 如果设置成True了，如果monthdays因为节假日的原因导致没有，将会在下一个交易日激活

          - ``allow`` (default: ``None``). A callback which receives a
            `datetime.date`` instance and returns ``True`` if the date is
            allowed for timers or else returns ``False``
            # 一个接收时间格式的回调在这个时间是计时器允许的时候返回True,在计时器不允许的时候，返回False

          - ``tzdata`` which can be either ``None`` (default), a ``pytz``
            instance or a ``data feed`` instance.

            ``None``: ``when`` is interpreted at face value (which translates
            to handling it as if it where UTC even if it's not)

            ``pytz`` instance: ``when`` will be interpreted as being specified
            in the local time specified by the timezone instance.

            ``data feed`` instance: ``when`` will be interpreted as being
            specified in the local time specified by the ``tz`` parameter of
            the data feed instance.

            **Note**: If ``when`` is either ``SESSION_START`` or
              ``SESSION_END`` and ``tzdata`` is ``None``, the 1st *data feed*
              in the system (aka ``self.data0``) will be used as the reference
              to find out the session times.

            # 时区数据，可以是None，或者pytz实例，或者datafeed实例
            # 当时区数据是None的时候，when将会按照字面意思处理，即使不是utc时间，也会当成是
            # 当时区数据是pytz实例的时候，when将会被pytz时区处理之后转换成本地时间
            # 当时区数据是datafeed实例的时候，when将会被datafeed的tz参数转换成本地时间
            # 如果when是SESSION_START或者SESSION_END，并且tzdata是None的时候，将会使用系统的第一个数据
            # 用于找到具体的时间

          - ``cheat`` (default ``False``) if ``True`` the timer will be called
            before the broker has a chance to evaluate the orders. This opens
            the chance to issue orders based on opening price for example right
            before the session starts
            #

          - ``*args``: any extra args will be passed to ``notify_timer``

          - ``**kwargs``: any extra kwargs will be passed to ``notify_timer``

        Return Value:

          - The created timer

        """
        return  self.cerebro._add_timer(owner=self, when=when, offset=offset, repeat=repeat,
                                        weekdays=weekdays, weekcarry=weekcarry,
                                        monthdays=monthdays, monthcarry=monthcarry,
                                        allow=allow,tzdata=tzdata, strats=False, cheat=cheat,
                                        *args, **kwargs)

    # 通知定时器
    def notify_timer(self, timer, when, *args, **kwargs):
        """
        Receives a timer notification where ``timer`` is the timer which was
        returned by ``add_timer``, and ``when`` is the calling time. ``args``
        and ``kwargs`` are any additional arguments passed to ``add_timer``

        The actual ``when`` time can be later, but the system may have not be
        able to call the timer before. This value is the timer value and no the
        system time.
        # 收到一个定时器的通知，这个定时器是通过add_timer添加的，并且在when的时候发出，args和kwargs是添加到add_timer的其他参数
        # 实际的when时间可以是晚的，但是这个系统可能不能在这之前调用定时器，这个值是定时器的值而不是系统的时间
        """
        pass

    # 通知现金价值
    def notify_cashvalue(self, cash, value):
        '''
        Receives the current fund value, value status of the strategy's broker
        '''
        pass

    # 通知fund
    def notify_fund(self, cash, value, fundvalue, shares):
        '''
        Receives the current cash, value, fundvalue and fund shares
        '''
        pass

    # 通知order
    def notify_order(self, order):
        '''
        Receives an order whenever there has been a change in one
        '''
        pass

    # 通知trade
    def notify_trade(self, trade):
        '''
        Receives a trade whenever there has been a change in one
        '''
        pass

    # 通知store
    def notify_store(self, msg, *args, **kwargs):
        '''Receives a notification from a store provider'''
        pass

    # 通知数据
    def notify_data(self, data, status, *args, **kwargs):
        '''Receives a notification from data'''
        pass

    # 获取存在的数据名称
    def getdatanames(self):
        '''
        Returns a list of the existing data names
        '''
        return keys(self.env.datasbyname)

    # 根据名称获取数据
    def getdatabyname(self, name):
        '''
        Returns a given data by name using the environment (cerebro)
        '''
        return self.env.datasbyname[name]

    # 取消订单
    def cancel(self, order):
        '''Cancels the order in the broker'''
        self.broker.cancel(order)

    # 买入下单
    def buy(self, data=None,
            size=None, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            parent=None, transmit=True,
            **kwargs):
        """
          Create a buy (long) order and send it to the broker

          - ``data`` (default: ``None``)

            For which data the order has to be created. If ``None`` then the
            first data in the system, ``self.datas[0] or self.data0`` (aka
            ``self.data``) will be used
            # 用于在那个数据上进行下单，如果是None的话，将会默认使用第一个数据

          - ``size`` (default: ``None``)

            Size to use (positive) of units of data to use for the order.

            If ``None`` the ``sizer`` instance retrieved via ``getsizer`` will
            be used to determine the size.
            # size是下单的数量，如果size是None的话，就使用getsizer获取需要的下单量

          - ``price`` (default: ``None``)

            Price to use (live brokers may place restrictions on the actual
            format if it does not comply to minimum tick size requirements)

            ``None`` is valid for ``Market`` and ``Close`` orders (the market
            determines the price)

            For ``Limit``, ``Stop`` and ``StopLimit`` orders this value
            determines the trigger point (in the case of ``Limit`` the trigger
            is obviously at which price the order should be matched)

            # 使用的价格（如果是实盘的时候，如果它不满足最小价格变动，可能需要对实际的格式进行限制
            # 如果price是None的话，对于市价单和收盘价订单是有效的
            # 对于限价单，止损单和止损限价单，这个price用于决定在那个点触发

          - ``plimit`` (default: ``None``)

            Only applicable to ``StopLimit`` orders. This is the price at which
            to set the implicit *Limit* order, once the *Stop* has been
            triggered (for which ``price`` has been used)

            # 仅仅能应用于止损限价单，price已经使用了，止损已经被触发了，plimit用于设定止损价格

          - ``trailamount`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is an
            absolute amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop
            # 移动止损量，默认是None，如果这个order的类型是移动止损，移动止损限价单，这是一个完全绝对的量
            # 用于决定在什么地方止损

          - ``trailpercent`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is a
            percentage amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop (if ``trailamount`` is also specified it will be used)

            # 移动百分比止损，默认是None,如果这个order是移动止损或者移动止损限价单，用价格的百分比来决定在哪个地方止损

          - ``exectype`` (default: ``None``)
            # 不同的执行类型
            Possible values:

            - ``Order.Market`` or ``None``. A market order will be executed
              with the next available price. In backtesting it will be the
              opening price of the next bar

                # 市价单，默认情况下是使用市价单，当使用市价单的时候将会在下一个可以利用的价格的时候执行
                # 在回测的时候使用下一个bar的开盘价

            - ``Order.Limit``. An order which can only be executed at the given
              ``price`` or better
                # 限价单，一个订单可以在限价执行或者更好的价格执行

            - ``Order.Stop``. An order which is triggered at ``price`` and
              executed like an ``Order.Market`` order
                # 止损单，会在price的时候触发这个止损单，并且以市价单成交

            - ``Order.StopLimit``. An order which is triggered at ``price`` and
              executed as an implicit *Limit* order with price given by
              ``pricelimit``
                # 止损限价单  在price的时候触发止损限价单，并且下一个pricelimit的限价单

            - ``Order.Close``. An order which can only be executed with the
              closing price of the session (usually during a closing auction)
                # 收盘价订单

            - ``Order.StopTrail``. An order which is triggered at ``price``
              minus ``trailamount`` (or ``trailpercent``) and which is updated
              if the price moves away from the stop
                # 移动止损单

            - ``Order.StopTrailLimit``. An order which is triggered at
              ``price`` minus ``trailamount`` (or ``trailpercent``) and which
              is updated if the price moves away from the stop
                # 移动止损限价单

          - ``valid`` (default: ``None``)

            Possible values:

              - ``None``: this generates an order that will not expire (aka
                *Good till cancel*) and remain in the market until matched or
                canceled. In reality brokers tend to impose a temporal limit,
                but this is usually so far away in time to consider it as not
                expiring

              - ``datetime.datetime`` or ``datetime.date`` instance: the date
                will be used to generate an order valid until the given
                datetime (aka *good till date*)

              - ``Order.DAY`` or ``0`` or ``timedelta()``: a day valid until
                the *End of the Session* (aka *day* order) will be generated

              - ``numeric value``: This is assumed to be a value corresponding
                to a datetime in ``matplotlib`` coding (the one used by
                ``backtrader``) and will used to generate an order valid until
                that time (*good till date*)

            # 有效期

          - ``tradeid`` (default: ``0``)

            This is an internal value applied by ``backtrader`` to keep track
            of overlapping trades on the same asset. This ``tradeid`` is sent
            back to the *strategy* when notifying changes to the status of the
            orders.

            # tradeid是一个backtrader内部的值用于跟踪同一个资产上的不同的trade,当通知订单的变化的时候，
            # 这个tradeid被送到了strategy

          - ``oco`` (default: ``None``)

            Another ``order`` instance. This order will become part of an OCO
            (Order Cancel Others) group. The execution of one of the orders,
            immediately cancels all others in the same group

            # oco订单，这个订单将会变为oco的一部分，其中一个订单执行，立即取消这个组里面其他的

          - ``parent`` (default: ``None``)

            Controls the relationship of a group of orders, for example a buy
            which is bracketed by a high-side limit sell and a low side stop
            sell. The high/low side orders remain inactive until the parent
            order has been either executed (they become active) or is
            canceled/expires (the children are also canceled) bracket orders
            have the same size

            # parent用于控制一组订单之间的关系，比如一个一个买单，同时有一个更高价格的限价卖单，
            # 同时有一个更低价格的止损卖单，这个止盈单和止损单只有在这个买单成交之后才会激活
            # 或者等到这个买单到期或者取消，止盈单和止损单也会取消
            # 这几个订单具有相同的size

          - ``transmit`` (default: ``True``)

            Indicates if the order has to be **transmitted**, ie: not only
            placed in the broker but also issued. This is meant for example to
            control bracket orders, in which one disables the transmission for
            the parent and 1st set of children and activates it for the last
            children, which triggers the full placement of all bracket orders.

            # 这个订单将会被转移，用于控制一篮子订单
            # todo 对于这个参数的含义并不是完全理解

          - ``**kwargs``: additional broker implementations may support extra
            parameters. ``backtrader`` will pass the *kwargs* down to the
            created order objects

            Example: if the 4 order execution types directly supported by
            ``backtrader`` are not enough, in the case of for example
            *Interactive Brokers* the following could be passed as *kwargs*::

              orderType='LIT', lmtPrice=10.0, auxPrice=9.8

            This would override the settings created by ``backtrader`` and
            generate a ``LIMIT IF TOUCHED`` order with a *touched* price of 9.8
            and a *limit* price of 10.0.

            # 一些其他的关键字参数，backtrader可以把这些参数传递到下面用于创建订单，可以用于创建一些
            # 超出现有订单类型的订单

        Returns:
          - the submitted order

        """
        # 如果data是字符串格式，获取具体的data
        if isinstance(data, string_types):
            data = self.getdatabyname(data)
        # 如果data不是None的时候，使用data，否则就使用第一个数据
        data = data if data is not None else self.datas[0]
        # 如果size不是None的时候，size等于size,否则就通过getsizing获取size
        size = size if size is not None else self.getsizing(data, isbuy=True)
        # 如果size不同于0
        if size:
            return self.broker.buy(
                self, data,
                size=abs(size), price=price, plimit=plimit,
                exectype=exectype, valid=valid, tradeid=tradeid, oco=oco,
                trailamount=trailamount, trailpercent=trailpercent,
                parent=parent, transmit=transmit,
                **kwargs)

        return None

    # 卖出订单，和买入订单比较类似
    def sell(self, data=None,
             size=None, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             parent=None, transmit=True,
             **kwargs):
        '''
        To create a selll (short) order and send it to the broker

        See the documentation for ``buy`` for an explanation of the parameters

        Returns: the submitted order
        '''
        if isinstance(data, string_types):
            data = self.getdatabyname(data)

        data = data if data is not None else self.datas[0]
        size = size if size is not None else self.getsizing(data, isbuy=False)

        if size:
            return self.broker.sell(
                self, data,
                size=abs(size), price=price, plimit=plimit,
                exectype=exectype, valid=valid, tradeid=tradeid, oco=oco,
                trailamount=trailamount, trailpercent=trailpercent,
                parent=parent, transmit=transmit,
                **kwargs)

        return None

    # 关闭
    def close(self, data=None, size=None, **kwargs):
        """
        Counters a long/short position closing it

        See the documentation for ``buy`` for an explanation of the parameters

        Note:

          - ``size``: automatically calculated from the existing position if
            not provided (default: ``None``) by the caller

        Returns: the submitted order
        """
        # 获取数据
        if isinstance(data, string_types):
            data = self.getdatabyname(data)
        elif data is None:
            data = self.data
        # 获取数据的持仓大小
        possize = self.getposition(data, self.broker).size
        # 如果size是None的时候，就把当前持仓全部平掉，如果size不是None的话，就会平掉size的
        size = abs(size if size is not None else possize)
        # 如果possize大于0的话，卖出平仓
        if possize > 0:
            return self.sell(data=data, size=size, **kwargs)
        # 如果possize小于0的话，买入平仓
        elif possize < 0:
            return self.buy(data=data, size=size, **kwargs)

        return None

    # 买入一篮子订单
    def buy_bracket(self, data=None, size=None, price=None, plimit=None,
                    exectype=bt.Order.Limit, valid=None, tradeid=0,
                    trailamount=None, trailpercent=None, oargs={},
                    stopprice=None, stopexec=bt.Order.Stop, stopargs={},
                    limitprice=None, limitexec=bt.Order.Limit, limitargs={},
                    **kwargs):
        '''
        Create a bracket order group (low side - buy order - high side). The
        default behavior is as follows:

          - Issue a **buy** order with execution ``Limit``

          - Issue a *low side* bracket **sell** order with execution ``Stop``

          - Issue a *high side* bracket **sell** order with execution
            ``Limit``.
        # 创建一个一篮子订单，默认行为将会按照下面的方式：
        # 以limit的价格发放一个限价单
        # 以更低价格的一个止损单
        # 更高价格的一个限价止盈单
        See below for the different parameters

          - ``data`` (default: ``None``)

            For which data the order has to be created. If ``None`` then the
            first data in the system, ``self.datas[0] or self.data0`` (aka
            ``self.data``) will be used

          - ``size`` (default: ``None``)

            Size to use (positive) of units of data to use for the order.

            If ``None`` the ``sizer`` instance retrieved via ``getsizer`` will
            be used to determine the size.

            **Note**: The same size is applied to all 3 orders of the bracket

          - ``price`` (default: ``None``)

            Price to use (live brokers may place restrictions on the actual
            format if it does not comply to minimum tick size requirements)

            ``None`` is valid for ``Market`` and ``Close`` orders (the market
            determines the price)

            For ``Limit``, ``Stop`` and ``StopLimit`` orders this value
            determines the trigger point (in the case of ``Limit`` the trigger
            is obviously at which price the order should be matched)

          - ``plimit`` (default: ``None``)

            Only applicable to ``StopLimit`` orders. This is the price at which
            to set the implicit *Limit* order, once the *Stop* has been
            triggered (for which ``price`` has been used)

          - ``trailamount`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is an
            absolute amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop

          - ``trailpercent`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is a
            percentage amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop (if ``trailamount`` is also specified it will be used)

          - ``exectype`` (default: ``bt.Order.Limit``)

            Possible values: (see the documentation for the method ``buy``

          - ``valid`` (default: ``None``)

            Possible values: (see the documentation for the method ``buy``

          - ``tradeid`` (default: ``0``)

            Possible values: (see the documentation for the method ``buy``

            # 上面参数含义和buy函数比较类似

          - ``oargs`` (default: ``{}``)

            Specific keyword arguments (in a ``dict``) to pass to the main side
            order. Arguments from the default ``**kwargs`` will be applied on
            top of this.

            # 给mainside设置关键字参数

          - ``**kwargs``: additional broker implementations may support extra
            parameters. ``backtrader`` will pass the *kwargs* down to the
            created order objects

            Possible values: (see the documentation for the method ``buy``

            **Note**: this ``kwargs`` will be applied to the 3 orders of a
            bracket. See below for specific keyword arguments for the low and
            high side orders

            # 是三个订单的关键字参数

          - ``stopprice`` (default: ``None``)

            Specific price for the *low side* stop order

            # 用于触发止损单的止损价

          - ``stopexec`` (default: ``bt.Order.Stop``)

            Specific execution type for the *low side* order

            # 止损单的类型，比如是限价止损，还是市价止损

          - ``stopargs`` (default: ``{}``)

            Specific keyword arguments (in a ``dict``) to pass to the low side
            order. Arguments from the default ``**kwargs`` will be applied on
            top of this.

            # 止损单的关键字参数

          - ``limitprice`` (default: ``None``)

            Specific price for the *high side* stop order

            # 止盈单的止盈价

          - ``limitexec`` (default: ``bt.Order.Limit``)

            Specific execution type for the *high side* order。
            # 止盈单的类型

          - ``limitargs`` (default: ``{}``)

            Specific keyword arguments (in a ``dict``) to pass to the high side
            order. Arguments from the default ``**kwargs`` will be applied on
            top of this.
            # 止盈单的参数

        High/Low Side orders can be suppressed by using:

          - ``limitexec=None`` to suppress the *high side*

          - ``stopexec=None`` to suppress the *low side*

        Returns:

          - A list containing the 3 orders [order, stop side, limit side]

          - If high/low orders have been suppressed the return value will still
            contain 3 orders, but those suppressed will have a value of
            ``None``
        '''
        # 参数字典
        kargs = dict(size=size,
                     data=data, price=price, plimit=plimit, exectype=exectype,
                     valid=valid, tradeid=tradeid,
                     trailamount=trailamount, trailpercent=trailpercent)
        # 更新主订单的参数
        kargs.update(oargs)
        # 更新关键字参数
        kargs.update(kwargs)
        # 如果limitexec和stopexec，两个都是None的话
        kargs['transmit'] = limitexec is None and stopexec is None
        # 买入订单
        o = self.buy(**kargs)

        # 止损
        if stopexec is not None:
            # low side / stop
            kargs = dict(data=data, price=stopprice, exectype=stopexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(stopargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = limitexec is None
            kargs['size'] = o.size
            ostop = self.sell(**kargs)
        else:
            ostop = None

        # 止盈
        if limitexec is not None:
            # high side / limit
            kargs = dict(data=data, price=limitprice, exectype=limitexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(limitargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = True
            kargs['size'] = o.size
            olimit = self.sell(**kargs)
        else:
            olimit = None

        return [o, ostop, olimit]

    # 卖出一篮子订单，和买入一篮子订单相似
    def sell_bracket(self, data=None,
                     size=None, price=None, plimit=None,
                     exectype=bt.Order.Limit, valid=None, tradeid=0,
                     trailamount=None, trailpercent=None,
                     oargs={},
                     stopprice=None, stopexec=bt.Order.Stop, stopargs={},
                     limitprice=None, limitexec=bt.Order.Limit, limitargs={},
                     **kwargs):
        '''
        Create a bracket order group (low side - buy order - high side). The
        default behavior is as follows:

          - Issue a **sell** order with execution ``Limit``

          - Issue a *high side* bracket **buy** order with execution ``Stop``

          - Issue a *low side* bracket **buy** order with execution ``Limit``.

        See ``bracket_buy`` for the meaning of the parameters

        High/Low Side orders can be suppressed by using:

          - ``stopexec=None`` to suppress the *high side*

          - ``limitexec=None`` to suppress the *low side*

        Returns:

          - A list containing the 3 orders [order, stop side, limit side]

          - If high/low orders have been suppressed the return value will still
            contain 3 orders, but those suppressed will have a value of
            ``None``
        '''

        kargs = dict(size=size,
                     data=data, price=price, plimit=plimit, exectype=exectype,
                     valid=valid, tradeid=tradeid,
                     trailamount=trailamount, trailpercent=trailpercent)
        kargs.update(oargs)
        kargs.update(kwargs)
        kargs['transmit'] = limitexec is None and stopexec is None
        o = self.sell(**kargs)

        if stopexec is not None:
            # high side / stop
            kargs = dict(data=data, price=stopprice, exectype=stopexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(stopargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = limitexec is None  # transmit if last
            kargs['size'] = o.size
            ostop = self.buy(**kargs)
        else:
            ostop = None

        if limitexec is not None:
            # low side / limit
            kargs = dict(data=data, price=limitprice, exectype=limitexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(limitargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = True
            kargs['size'] = o.size
            olimit = self.buy(**kargs)
        else:
            olimit = None

        return [o, ostop, olimit]

    # 目标大小订单
    def order_target_size(self, data=None, target=0, **kwargs):
        """

        Place an order to rebalance a position to have final size of ``target``

        The current ``position`` size is taken into account as the start point
        to achieve ``target``

          - If ``target`` > ``pos.size`` -> buy ``target - pos.size``

          - If ``target`` < ``pos.size`` -> sell ``pos.size - target``

        It returns either:

          - The generated order

          or
          - ``None`` if no order has been issued (``target == position.size``)

        # 下一个订单用于平衡现有的持仓大小，以便达到目标订单的大小

        """
        # 获取具体的data
        if isinstance(data, string_types):
            data = self.getdatabyname(data)
        elif data is None:
            data = self.data

        # 获取现有的持仓
        possize = self.getposition(data, self.broker).size
        # 如果target等于0，并且possize不等于0，平仓
        if not target and possize:
            return self.close(data=data, size=possize, **kwargs)
        # 如果目标大于现有的持仓，买入
        elif target > possize:
            return self.buy(data=data, size=target - possize, **kwargs)
        # 如果目标小于现有的持仓，卖出
        elif target < possize:
            return self.sell(data=data, size=possize - target, **kwargs)

        return None  # no execution target == possize

    # 目标金额订单，跟目标大小订单比较类似
    def order_target_value(self, data=None, target=0.0, price=None, **kwargs):
        '''
        Place an order to rebalance a position to have final value of
        ``target``

        The current ``value`` is taken into account as the start point to
        achieve ``target``

          - If no ``target`` then close postion on data
          - If ``target`` > ``value`` then buy on data
          - If ``target`` < ``value`` then sell on data

        It returns either:

          - The generated order

          or

          - ``None`` if no order has been issued
        '''
        # 获取数据
        if isinstance(data, string_types):
            data = self.getdatabyname(data)
        elif data is None:
            data = self.data
        # 获取持仓
        possize = self.getposition(data, self.broker).size
        # 如果target等于0，并且possize不等于0，平仓
        if not target and possize:  # closing a position
            return self.close(data=data, size=possize, price=price, **kwargs)
        # 如果是其他情况
        else:
            # 获取当前data的价值
            value = self.broker.getvalue(datas=[data])
            # 获取佣金信息
            comminfo = self.broker.getcommissioninfo(data)
            # 获取price，如果price不是None的话，就用price,否则就用数据的收盘价
            # Make sure a price is there
            price = price if price is not None else data.close[0]
            # 如果目标价值大于value，就计算需要buy的size大小，发出buy订单
            if target > value:
                size = comminfo.getsize(price, target - value)
                # print(f"buy: name:{data.name},size:{size}")
                return self.buy(data=data, size=size, price=price, **kwargs)
            # 如果目标价值小于value，就计算需要sell的size大小，发出sell订单
            elif target < value:
                size = comminfo.getsize(price, value - target)
                # print(f"sell: name:{data.name},size:{size}")
                return self.sell(data=data, size=size, price=price, **kwargs)

        return None  # no execution size == possize

    # 目标百分比订单，会下一个订单再平衡当前的仓位，以确保仓位价值占现在账户价值的target百分比
    def order_target_percent(self, data=None, target=0.0, **kwargs):
        '''
        Place an order to rebalance a position to have final value of
        ``target`` percentage of current portfolio ``value``

        ``target`` is expressed in decimal: ``0.05`` -> ``5%``

        It uses ``order_target_value`` to execute the order.

        Example:
          - ``target=0.05`` and portfolio value is ``100``

          - The ``value`` to be reached is ``0.05 * 100 = 5``

          - ``5`` is passed as the ``target`` value to ``order_target_value``

        The current ``value`` is taken into account as the start point to
        achieve ``target``

        The ``position.size`` is used to determine if a position is ``long`` /
        ``short``

          - If ``target`` > ``value``
            - buy if ``pos.size >= 0`` (Increase a long position)
            - sell if ``pos.size < 0`` (Increase a short position)

          - If ``target`` < ``value``
            - sell if ``pos.size >= 0`` (Decrease a long position)
            - buy if ``pos.size < 0`` (Decrease a short position)

        It returns either:

          - The generated order

          or

          - ``None`` if no order has been issued (``target == position.size``)
        '''
        # 获取数据
        if isinstance(data, string_types):
            data = self.getdatabyname(data)
        elif data is None:
            data = self.data
        # 计算持仓和目标价值，todo 此处没有必要获取持仓的大小，可以考虑注释掉
        # possize = self.getposition(data, self.broker).size
        target *= self.broker.getvalue()

        return self.order_target_value(data=data, target=target, **kwargs)

    # 获取数据的持仓，如果数据是None的话，将会获取第一个数据的持仓，如果broker是None的话，使用默认的broker
    def getposition(self, data=None, broker=None):
        '''
        Returns the current position for a given data in a given broker.

        If both are None, the main data and the default broker will be used

        A property ``position`` is also available
        '''
        data = data if data is not None else self.datas[0]
        broker = broker or self.broker
        return broker.getposition(data)

    # 也可以通过属性position来获取数据持仓
    position = property(getposition)

    # 根据数据的名字来获取持仓大小，如果数据是None的话，默认获取第一个数据的持仓，如果不是None,获取具体的数据
    # 如果broker不是None，使用参数传递的broker，否则使用默认的broker
    def getpositionbyname(self, name=None, broker=None):
        '''
        Returns the current position for a given name in a given broker.

        If both are None, the main data and the default broker will be used

        A property ``positionbyname`` is also available
        '''
        data = self.datas[0] if not name else self.getdatabyname(name)
        broker = broker or self.broker
        return broker.getposition(data)
    # 设置了positionbyname属性，可以通过这个根据名字获取属性
    positionbyname = property(getpositionbyname)

    # 获取某个broker的持仓
    def getpositions(self, broker=None):
        '''
        Returns the current by data positions directly from the broker

        If the given ``broker`` is None, the default broker will be used

        A property ``positions`` is also available
        '''
        broker = broker or self.broker
        return broker.positions
    # 可以通过positions属性来获取broker的持仓
    positions = property(getpositions)

    # 返回broker中的以持仓的名字为key,position为value形成的字典
    def getpositionsbyname(self, broker=None):
        '''
        Returns the current by name positions directly from the broker

        If the given ``broker`` is None, the default broker will be used

        A property ``positionsbyname`` is also available
        '''
        broker = broker or self.broker
        positions = broker.positions

        posbyname = collections.OrderedDict()
        for name, data in iteritems(self.env.datasbyname):
            posbyname[name] = positions[data]

        return posbyname

    # 可以通过属性访问
    positionsbyname = property(getpositionsbyname)

    # 增加sizer,如果sizer是None的话，默认使用固定的sizer，如果不是None的话，就实例化sizer,并设置到broker中
    def _addsizer(self, sizer, *args, **kwargs):
        if sizer is None:
            self.setsizer(bt.sizers.FixedSize())
        else:
            self.setsizer(sizer(*args, **kwargs))

    # 设置sizer
    def setsizer(self, sizer):
        '''
        Replace the default (fixed stake) sizer
        '''
        self._sizer = sizer
        sizer.set(self, self.broker)
        return sizer

    # 获取sizer
    def getsizer(self):
        '''
        Returns the sizer which is in used if automatic statke calculation is
        used

        Also available as ``sizer``
        '''
        return self._sizer

    sizer = property(getsizer, setsizer)

    # 根据sizer获取要下单的大小
    def getsizing(self, data=None, isbuy=True):
        '''
        Return the stake calculated by the sizer instance for the current
        situation
        '''
        data = data if data is not None else self.datas[0]
        return self._sizer.getsizing(data, isbuy=isbuy)


# 信号策略元类，
class MetaSigStrategy(Strategy.__class__):

    def __new__(meta, name, bases, dct):
        # map user defined next to custom to be able to call own method before
        # 如果有next，就使用_next_custom替代
        if 'next' in dct:
            dct['_next_custom'] = dct.pop('next')

        cls = super(MetaSigStrategy, meta).__new__(meta, name, bases, dct)

        # after class creation remap _next_catch to be next
        # 信号策略类的next等于_next_catch
        cls.next = cls._next_catch
        return cls

    def dopreinit(cls, _obj, *args, **kwargs):

        _obj, args, kwargs = \
            super(MetaSigStrategy, cls).dopreinit(_obj, *args, **kwargs)
        # 初始化_signals为一个默认字典
        _obj._signals = collections.defaultdict(list)
        # 设置下单的数据
        _data = _obj.p._data
        if _data is None:
            _obj._dtarget = _obj.data0
        elif isinstance(_data, integer_types):
            _obj._dtarget = _obj.datas[_data]
        elif isinstance(_data, string_types):
            _obj._dtarget = _obj.getdatabyname(_data)
        elif isinstance(_data, bt.LineRoot):
            _obj._dtarget = _data
        else:
            _obj._dtarget = _obj.data0

        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaSigStrategy, cls).dopostinit(_obj, *args, **kwargs)
        # 把信号数据保存到signals中
        for sigtype, sigcls, sigargs, sigkwargs in _obj.p.signals:
            _obj._signals[sigtype].append(sigcls(*sigargs, **sigkwargs))

        # Record types of signals
        # 根据_signals中的信号，保存不同类型的对象到具体的属性中
        _obj._longshort = bool(_obj._signals[bt.SIGNAL_LONGSHORT])

        _obj._long = bool(_obj._signals[bt.SIGNAL_LONG])
        _obj._short = bool(_obj._signals[bt.SIGNAL_SHORT])

        _obj._longexit = bool(_obj._signals[bt.SIGNAL_LONGEXIT])
        _obj._shortexit = bool(_obj._signals[bt.SIGNAL_SHORTEXIT])

        return _obj, args, kwargs

# 信号策略类，使用信号可以自动操作的策略的子类
class SignalStrategy(with_metaclass(MetaSigStrategy, Strategy)):
    '''This subclass of ``Strategy`` is meant to to auto-operate using
    **signals**.

    *Signals* are usually indicators and the expected output values:

      - ``> 0`` is a ``long`` indication

      - ``< 0`` is a ``short`` indication

    There are 5 types of *Signals*, broken in 2 groups.

    # 信号通常是指标并且具有下面的输出值：大于0代表一个多头意向，小于0代表一个空头意向，下面具有5种类型的信号，分成2组

    **Main Group**:

      - ``LONGSHORT``: both ``long`` and ``short`` indications from this signal
        are taken

        # 多头意向和空头意向同时在这个信号中

      - ``LONG``:
        - ``long`` indications are taken to go long
        - ``short`` indications are taken to *close* the long position. But:

          - If a ``LONGEXIT`` (see below) signal is in the system it will be
            used to exit the long

          - If a ``SHORT`` signal is available and no ``LONGEXIT`` is available
            , it will be used to close a ``long`` before opening a ``short``
        # 多头情况下：
            # long意向将会开多
            # short意向将会平多，如果有LONGEXIT，多头将会被平掉，如果没有LONGEXIT，会在开空之前平掉多头

      - ``SHORT``:
        - ``short`` indications are taken to go short
        - ``long`` indications are taken to *close* the short position. But:

          - If a ``SHORTEXIT`` (see below) signal is in the system it will be
            used to exit the short

          - If a ``LONG`` signal is available and no ``SHORTEXIT`` is available
            , it will be used to close a ``short`` before opening a ``long``
        # 空头情况
            # 如果是short信号，将会继续开空
            # 如果是long信号，如果是SHORTEXIT，将会结束空头，如果没有SHORTEXIT，在开多之前会先平掉空头

    **Exit Group**:

      This 2 signals are meant to override others and provide criteria for
      exitins a ``long``/``short`` position

      - ``LONGEXIT``: ``short`` indications are taken to exit ``long``
        positions

      - ``SHORTEXIT``: ``long`` indications are taken to exit ``short``
        positions

     # 分别用于结束多头和空头

    **Order Issuing**

      Orders execution type is ``Market`` and validity is ``None`` (*Good until
      Canceled*)

    # 下单，将会下一个有效期直到取消前都有效的市价单

    Params:

      - ``signals`` (default: ``[]``): a list/tuple of lists/tuples that allows
        the instantiation of the signals and allocation to the right type

        This parameter is expected to be managed through ``cerebro.add_signal``
        # 信号，列表或者元组，其中的元素也是列表或者元组，可以用于信号的实例化，并且格式分配的正确
        #这个参数是通过cerebro.add_signal来添加的

      - ``_accumulate`` (default: ``False``): allow to enter the market
        (long/short) even if already in the market
        # 累计，是否允许已经有持仓的情况下，仍然可以开仓，默认是不允许

      - ``_concurrent`` (default: ``False``): allow orders to be issued even if
        orders are already pending execution
        # 多个订单，在有没有成交的订单的时候是否允许开仓，默认情况下是不允许

      - ``_data`` (default: ``None``): if multiple datas are present in the
        system which is the target for orders. This can be

        - ``None``: The first data in the system will be used

        - An ``int``: indicating the data that was inserted at that position

        - An ``str``: name given to the data when creating it (parameter
          ``name``) or when adding it cerebro with ``cerebro.adddata(...,
          name=)``

        - A ``data`` instance

        # 数据，默认是None，数据可以是下面的值：
        # None，将会默认使用第一个数据
        # int,将会获取datas[int]这个数据
        # str，将会使用getdatabyname获取data
        # data实例，直接使用

    '''
    # 参数
    params = (
        ('signals', []),
        ('_accumulate', False),
        ('_concurrent', False),
        ('_data', None),
    )
    # 开始
    def _start(self):
        self._sentinel = None  # sentinel for order concurrency
        super(SignalStrategy, self)._start()
    # 增加信号
    def signal_add(self, sigtype, signal):
        self._signals[sigtype].append(signal)
    # 通知
    def _notify(self, qorders=[], qtrades=[]):
        # Nullify the sentinel if done
        procorders = qorders or self._orderspending
        if self._sentinel is not None:
            for order in procorders:
                if order == self._sentinel and not order.alive():
                    self._sentinel = None
                    break

        super(SignalStrategy, self)._notify(qorders=qorders, qtrades=qtrades)

    # 匹配信号
    def _next_catch(self):
        self._next_signal()
        if hasattr(self, '_next_custom'):
            self._next_custom()

    # 下一个信号
    def _next_signal(self):
        # 如果不允许同时下单，并且已经下过单了，返回
        if self._sentinel is not None and not self.p._concurrent:
            return  # order active and more than 1 not allowed
        # 信号
        sigs = self._signals
        # 没有信号
        nosig = [[0.0]]

        # Calculate current status of the signals
        # 计算信号的当前状态
        # sigs[bt.SIGNAL_LONGSHORT]如果是空得到话，就循环nosig，返回False
        # longshort的信号
        ls_long = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONGSHORT] or nosig)
        ls_short = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONGSHORT] or nosig)
        # 多头进场信号
        l_enter0 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONG] or nosig)
        l_enter1 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONG_INV] or nosig)
        l_enter2 = all(x[0] for x in sigs[bt.SIGNAL_LONG_ANY] or nosig)
        l_enter = l_enter0 or l_enter1 or l_enter2
        # 空头进场信号
        s_enter0 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_SHORT] or nosig)
        s_enter1 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_SHORT_INV] or nosig)
        s_enter2 = all(x[0] for x in sigs[bt.SIGNAL_SHORT_ANY] or nosig)
        s_enter = s_enter0 or s_enter1 or s_enter2
        # 多头出场信号
        l_ex0 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONGEXIT] or nosig)
        l_ex1 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONGEXIT_INV] or nosig)
        l_ex2 = all(x[0] for x in sigs[bt.SIGNAL_LONGEXIT_ANY] or nosig)
        l_exit = l_ex0 or l_ex1 or l_ex2
        # 空头出场信号
        s_ex0 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_SHORTEXIT] or nosig)
        s_ex1 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_SHORTEXIT_INV] or nosig)
        s_ex2 = all(x[0] for x in sigs[bt.SIGNAL_SHORTEXIT_ANY] or nosig)
        s_exit = s_ex0 or s_ex1 or s_ex2

        # Use oppossite signales to start reversal (by closing)
        # but only if no "xxxExit" exists
        # 不是多头结束并且空头信号，代表多头反转
        l_rev = not self._longexit and s_enter
        # 不是空头结束并且多头信号，代表空头反转
        s_rev = not self._shortexit and l_enter

        # Opposite of individual long and short
        # 多头离场
        l_leav0 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONG] or nosig)
        l_leav1 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONG_INV] or nosig)
        l_leav2 = all(x[0] for x in sigs[bt.SIGNAL_LONG_ANY] or nosig)
        l_leave = l_leav0 or l_leav1 or l_leav2
        # 空头离场
        s_leav0 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_SHORT] or nosig)
        s_leav1 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_SHORT_INV] or nosig)
        s_leav2 = all(x[0] for x in sigs[bt.SIGNAL_SHORT_ANY] or nosig)
        s_leave = s_leav0 or s_leav1 or s_leav2

        # Invalidate long leave if longexit signals are available
        # 如果longexit是False的话，l_leave，如果是True的话，l_leave是False
        l_leave = not self._longexit and l_leave
        # Invalidate short leave if shortexit signals are available
        # 如果shortexit是False的话，返回s_leave，如果是True的话，s_leave是False
        s_leave = not self._shortexit and s_leave

        # Take size and start logic
        # 获取持仓
        size = self.getposition(self._dtarget).size
        # 如果没有持仓
        if not size:
            # 下单
            if ls_long or l_enter:
                self._sentinel = self.buy(self._dtarget)

            elif ls_short or s_enter:
                self._sentinel = self.sell(self._dtarget)

        # 如果当前持仓大于0
        elif size > 0:  # current long position
            if ls_short or l_exit or l_rev or l_leave:
                # closing position - not relevant for concurrency
                self.close(self._dtarget)

            if ls_short or l_rev:
                self._sentinel = self.sell(self._dtarget)

            if ls_long or l_enter:
                if self.p._accumulate:
                    self._sentinel = self.buy(self._dtarget)
        # 如果当前持仓小于0
        elif size < 0:  # current short position
            if ls_long or s_exit or s_rev or s_leave:
                # closing position - not relevant for concurrency
                self.close(self._dtarget)

            if ls_long or s_rev:
                self._sentinel = self.buy(self._dtarget)

            if ls_short or s_enter:
                if self.p._accumulate:
                    self._sentinel = self.sell(self._dtarget)
