#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import collections
import operator
import sys

from .utils.py3 import map, range, zip, string_types
from .utils import DotDict

from .lineroot import LineRoot, LineSingle
from .linebuffer import LineActions, LineNum
from .lineseries import LineSeries, LineSeriesMaker, MetaLineSeries
from .dataseries import DataSeries
from . import metabase


class MetaLineIterator(MetaLineSeries):
    """Metaclass for LineIterator that handles data argument processing"""
    
    def donew(cls, *args, **kwargs):
        """Process data arguments and filter them before instance creation"""
        # Process data arguments before creating instance
        mindatas = cls._mindatas
        lastarg = 0
        datas = []
        
        # Process args to extract data sources
        for arg in args:
            if isinstance(arg, LineRoot):
                datas.append(LineSeriesMaker(arg))
            elif not mindatas:
                break  # found not data and must not be collected
            else:
                try:
                    datas.append(LineSeriesMaker(LineNum(arg)))
                except:
                    # Not a LineNum and is not a LineSeries - bail out
                    break
            mindatas = max(0, mindatas - 1)
            lastarg += 1
        
        # Create the instance with filtered arguments
        remaining_args = args[lastarg:]
        _obj, remaining_args, kwargs = super(MetaLineIterator, cls).donew(*remaining_args, **kwargs)
        
        # Initialize _lineiterators
        _obj._lineiterators = collections.defaultdict(list)
        _obj.datas = datas

        # If no datas have been passed to an indicator, use owner's datas
        # Check for owner's existence more carefully to avoid __bool__ issues
        if not _obj.datas and hasattr(_obj, '_owner') and _obj._owner is not None:
            try:
                # Check if this is an indicator or observer by looking at class hierarchy
                class_name = _obj.__class__.__name__
                is_indicator_or_observer = ('Indicator' in class_name or 'Observer' in class_name or
                                          hasattr(_obj, '_mindatas'))
                if is_indicator_or_observer:
                    _obj.datas = _obj._owner.datas[0:_obj._mindatas]
            except (AttributeError, IndexError):
                pass

        # Create ddatas dictionary
        _obj.ddatas = {x: None for x in _obj.datas}

        # Set data aliases
        if _obj.datas:
            _obj.data = data = _obj.datas[0]
            # Set line aliases for first data
            for l, line in enumerate(data.lines):
                linealias = data._getlinealias(l)
                if linealias:
                    setattr(_obj, "data_%s" % linealias, line)
                setattr(_obj, "data_%d" % l, line)
            
            # Set aliases for all datas
            for d, data in enumerate(_obj.datas):
                setattr(_obj, "data%d" % d, data)
                for l, line in enumerate(data.lines):
                    linealias = data._getlinealias(l)
                    if linealias:
                        setattr(_obj, "data%d_%s" % (d, linealias), line)
                    setattr(_obj, "data%d_%d" % (d, l), line)

        # Set dnames
        _obj.dnames = DotDict([(d._name, d) for d in _obj.datas if getattr(d, "_name", "")])
        
        # Return with filtered arguments
        return _obj, remaining_args, kwargs
        
    def dopreinit(cls, _obj, *args, **kwargs):
        """Handle pre-initialization setup"""
        # if no datas were found, use the _owner (to have a clock)
        if not _obj.datas and hasattr(_obj, '_owner') and _obj._owner is not None:
            _obj.datas = [_obj._owner]
        elif not _obj.datas:
            _obj.datas = []
        
        # 1st data source is our ticking clock
        if _obj.datas and _obj.datas[0] is not None:
            _obj._clock = _obj.datas[0]
        elif hasattr(_obj, '_owner') and _obj._owner is not None:
            _obj._clock = _obj._owner
        else:
            _obj._clock = None

        # Calculate minimum period from datas
        if _obj.datas:
            data_minperiods = [getattr(x, '_minperiod', 1) for x in _obj.datas if x is not None]
            _obj._minperiod = max(data_minperiods + [getattr(_obj, '_minperiod', 1)])
        else:
            _obj._minperiod = getattr(_obj, '_minperiod', 1)

        # Add minperiod to lines
        if hasattr(_obj, 'lines'):
            for line in _obj.lines:
                if hasattr(line, 'addminperiod'):
                    line.addminperiod(_obj._minperiod)
                    
        return _obj, args, kwargs
        
    def dopostinit(cls, _obj, *args, **kwargs):
        """Handle post-initialization setup"""
        # Calculate minperiod from lines
        if hasattr(_obj, 'lines'):
            line_minperiods = [getattr(x, '_minperiod', 1) for x in _obj.lines]
            if line_minperiods:
                _obj._minperiod = max(line_minperiods)

        # Recalculate period
        _obj._periodrecalc()

        # Register self as indicator to owner
        if hasattr(_obj, '_owner') and _obj._owner is not None:
            if hasattr(_obj._owner, 'addindicator'):
                _obj._owner.addindicator(_obj)
                
        return _obj, args, kwargs


class LineIterator(LineSeries, metaclass=MetaLineIterator):
    # _nextforce默认是False
    _nextforce = False  # force cerebro to run in next mode (runonce=False)
    # 最小的数据数目是1
    _mindatas = 1
    # _ltype代表line的index的值，目前默认应该是0
    _ltype = LineSeries.IndType

    # plotinfo具体的信息
    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname="",
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
        plotmaster=None,
    )

    def __init__(self, *args, **kwargs):
        # Initialize parent class
        super(LineIterator, self).__init__(*args, **kwargs)

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
        return [
            x
            for x in self._lineiterators[LineIterator.IndType]
            if hasattr(x.lines, "getlinealiases")
        ]

    def getobservers(self):
        # 获取观察者
        return self._lineiterators[LineIterator.ObsType]

    def addindicator(self, indicator):
        # store in right queue
        # 增加指标
        self._lineiterators[indicator._ltype].append(indicator)

        # use getattr because line buffers don't have this attribute
        if getattr(indicator, "_nextforce", False):
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
        """
        This method will be called before the minimum period of all
        datas/indicators have been meet for the strategy to start executing
        """
        pass

    def nextstart(self):
        """
        This method will be called once, exactly when the minimum period for
        all datas/indicators have been meet. The default behavior is to call
        next
        """

        # Called once for 1st full calculation - defaults to regular next
        self.next()

    def next(self):
        """
        This method will be called for all remaining data points when the
        minimum period for all datas/indicators have been meet.
        """
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
        self.val = float("NaN")

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
        self.dvals = [float("NaN")] * self.dsize

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
    nclsname = str("LinesCoupler_%d" % LinesCoupler.counter)
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
        clock = getattr(cdata, "_clock", None)
        if clock is not None:
            nclock = getattr(clock, "_clock", None)
            if nclock is not None:
                clock = nclock
            else:
                nclock = getattr(clock, "data", None)
                if nclock is not None:
                    clock = nclock

        if clock is None:
            clock = obj._owner

    obj._clock = clock
    return obj


# Add an alias (which seems a lot more sensible for "Single Line" lines
LineCoupler = LinesCoupler
