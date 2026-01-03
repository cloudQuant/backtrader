#!/usr/bin/env python
import calendar
import datetime
import pprint as pp
from collections import OrderedDict

from .dataseries import TimeFrame
from .metabase import findowner
from .observer import Observer
from .parameters import ParameterizedBase
from .strategy import Strategy
from .utils.py3 import MAXINT


# Analyzer类 - 重构为不使用元类
class Analyzer(ParameterizedBase):
    """Analyzer base class. All analyzers are subclass of this one

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

    """

    # 保存结果到csv中
    csv = True

    def __new__(cls, *args, **kwargs):
        """
        Custom __new__ to implement the functionality previously in MetaAnalyzer.donew
        """
        # Create the object using parent's __new__
        _obj = super().__new__(cls)

        # Initialize children list
        _obj._children = list()

        return _obj

    def __init__(self, *args, **kwargs):
        """
        Initialize Analyzer with basic functionality
        """
        # Initialize parent first
        super().__init__(*args, **kwargs)

        # findowner用于发现_obj的父类，Strategy的实例，如果没有找到，返回None
        self.strategy = strategy = findowner(self, Strategy)
        # findowner用于发现_obj的父类，属于Analyzer的实例,如果没有找到，返回None
        self._parent = findowner(self, Analyzer)
        # Register with a master observer if created inside one
        # findowner用于发现_obj的父类，但是属于Observer的实例,如果没有找到，返回None
        masterobs = findowner(self, Observer)
        # 如果有obs的话，就把analyzer注册到obs中
        if masterobs is not None:
            masterobs._register_analyzer(self)
        # analyzer的数据
        self.datas = strategy.datas if strategy is not None else []

        # For each data add aliases: for first data: data and data0
        # 如果analyzer的数据不是None的话
        if self.datas:
            # analyzer的data就是第一个数据
            self.data = data = self.datas[0]
            # 对于数据里面的每条line
            for line_index, line in enumerate(data.lines):
                # 获取line的名字
                linealias = data._getlinealias(line_index)
                # 如果line的名字不是None的话，设置属性
                if linealias:
                    setattr(self, "data_%s" % linealias, line)
                # 根据index设置line的名称
                setattr(self, "data_%d" % line_index, line)
            # 循环数据，给数据设置不同的名称，可以通过data_d访问
            for d, data in enumerate(self.datas):
                setattr(self, "data%d" % d, data)
                # 对不同的数据设置具体的属性名，可以通过属性名访问line
                for line_index, line in enumerate(data.lines):
                    linealias = data._getlinealias(line_index)
                    if linealias:
                        setattr(self, "data%d_%s" % (d, linealias), line)
                    setattr(self, "data%d_%d" % (d, line_index), line)

        # 调用create_analysis方法
        self.create_analysis()

        # Handle parent registration (previously in dopostinit)
        if self._parent is not None:
            self._parent._register(self)

    # 获取analyzer的长度的时候，其实是计算的策略的长度
    def __len__(self):
        """Support for invoking ``len`` on analyzers by actually returning the
        current length of the strategy the analyzer operates on"""
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

    # _start，对于所有的child进行_start调用
    def _start(self):
        for child in self._children:
            child._start()

        self.start()

    # _stop，对于所有的child进行_stop调用
    def _stop(self):
        for child in self._children:
            child._stop()

        self.stop()

    # 通知cash,value
    def notify_cashvalue(self, cash, value):
        pass

    # 通知fund
    def notify_fund(self, cash, value, fundvalue, shares):
        pass

    # 通知order，可以在子类中重写
    def notify_order(self, order):
        pass

    # 通知trade，可以在子类中重写
    def notify_trade(self, trade):
        pass

    # next，可以在子类中重写
    def next(self):
        pass

    # prenext如果等于next的话，在子类中重写prenext，
    # 一般情况下，prenext需要和next做同样的计算或者pass
    def prenext(self):
        # prenext and next until a minimum period of total_lines has been
        # reached
        # 默认调用next，除非是子类中特别重写了prenext，否则prenext调用next
        self.next()

    # nextstart，一般被下一类重写，或者调用next
    def nextstart(self):
        # Called once when the minimum period for all lines has been meet
        # It's default behavior is to call next
        # 默认调用next
        self.next()

    # start，可以在子类中重写
    def start(self):
        pass

    # stop，可以在子类中重写
    def stop(self):
        pass

    # 创建analysis，在子类中重写
    def create_analysis(self):
        # create a dict placeholder for the analysis
        # 创建一个字典分析结果的占位符
        # self.rets 可以通过get_analysis获取到
        self.rets = OrderedDict()

    # 获取analysis
    def get_analysis(self):
        """Returns a *dict-like* object with the results of the analysis

        The keys and format of analysis results in the dictionary is
        implementation dependent.

        It is not even enforced that the result is a *dict-like object*, just
        the convention

        The default implementation returns the default OrderedDict ``rets``
        created by the default ``create_analysis`` method

        # 返回字典形式的结果分析，具体的格式取决于实现
        """
        return self.rets

    # 打印analysis
    def print(self, *args, **kwargs):
        """Prints the results returned by ``get_analysis`` via a standard
        ``print`` call"""
        # print analysis 通过调用打印分析结果，这个内容可以通过get_analysis获取到
        print(self.get_analysis())

    # pprint analysis
    def pprint(self, *args, **kwargs):
        """Prints the results returned by ``get_analysis`` via a pretty print
        call"""
        # pretty print analysis，和上面类似
        pp.pprint(self.get_analysis(), *args, **kwargs)


# TimeFrameAnalyzerBase类 - 重构为不使用元类
class TimeFrameAnalyzerBase(Analyzer):
    # 参数
    params = (
        ("timeframe", None),
        ("compression", None),
        ("_doprenext", True),
    )

    def __init__(self, *args, **kwargs):
        """Initialize with functionality previously in MetaTimeFrameAnalyzerBase"""
        super().__init__(*args, **kwargs)

        # Hack to support original method name - add on_dt_over_orig if on_dt_over_orig exists
        if hasattr(self, "on_dt_over_orig") and not hasattr(self, "on_dt_over"):
            self.on_dt_over = self.on_dt_over_orig

    def _start(self):
        # Override to add specific attributes
        # 设置交易周期，比如分钟
        # 设置交易周期 - use data's timeframe if not specified
        self.timeframe = self.p.timeframe or self.data._timeframe
        # 设置压缩 - use data's compression if not specified
        self.compression = self.p.compression or self.data._compression
        # CRITICAL FIX: Initialize dtcmp with datetime.min to match master branch behavior
        # This ensures first _dt_over() call detects a change and counts correctly
        self.dtcmp, self.dtkey = self._get_dt_cmpkey(datetime.datetime.min)
        super()._start()

    def _prenext(self):
        # Match master branch: call children, check _dt_over, then prenext
        for child in self._children:
            child._prenext()

        if self._dt_over():
            self.on_dt_over()

        if self.p._doprenext:
            self.prenext()

    def _nextstart(self):
        # Match master branch: call children, check _dt_over or not doprenext, then nextstart
        for child in self._children:
            child._nextstart()

        if self._dt_over() or not self.p._doprenext:
            self.on_dt_over()

        self.nextstart()

    def _next(self):
        # Match master branch: call children, check _dt_over, then next
        for child in self._children:
            child._next()

        if self._dt_over():
            self.on_dt_over()

        self.next()

    # 这个方法子类一般需要重写
    def on_dt_over(self):
        pass

    # CRITICAL FIX: Match master branch - return boolean and update dtcmp atomically
    def _dt_over(self):
        # 如果交易周期等于没有时间周期，dtcmp等于最大整数，dtkey等于最大时间
        if self.timeframe == TimeFrame.NoTimeFrame:
            dtcmp, dtkey = MAXINT, datetime.datetime.max
        else:
            # Get current datetime from strategy
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
        dtcmp = dt.replace(hour=int(ph), minute=int(pm), second=int(ps), microsecond=int(pus))
        # 对dtcmp进行调整
        dtcmp -= tadjust
        # dtkey等于dtcmp
        dtkey = dtcmp

        return dtcmp, dtkey
