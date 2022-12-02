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

import datetime
import collections
import itertools
import multiprocessing

import backtrader as bt
from .utils.py3 import (map, range, zip, with_metaclass, string_types,
                        integer_types)

from . import linebuffer
from . import indicator
from .brokers import BackBroker
from .metabase import MetaParams
from . import observers
from .writer import WriterFile
from .utils import OrderedDict, tzparse, num2date, date2num
from .strategy import Strategy, SignalStrategy
from .tradingcal import (TradingCalendarBase, TradingCalendar,
                         PandasMarketCalendar)
from .timer import Timer

# Defined here to make it pickable. Ideally it could be defined inside Cerebro
class OptReturn(object):
    def __init__(self, params, **kwargs):
        self.p = self.params = params
        for k, v in kwargs.items():
            setattr(self, k, v)


class Cerebro(with_metaclass(MetaParams, object)):
    '''Params:

      - ``preload`` (default: ``True``)

        Whether to preload the different ``data feeds`` passed to cerebro for
        the Strategies

        # preload这个参数默认的是True，就意味着，在回测的时候，默认是先把数据加载之后传给cerebro，在内存中调用，
        # 这个步骤导致的结果就是，加载数据会浪费一部分时间，但是，在回测的时候，速度会快一些，总体上的速度还是有所提高的
        # 所以，建议这个值，使用默认值。

      - ``runonce`` (default: ``True``)

        Run ``Indicators`` in vectorized mode to speed up the entire system.
        Strategies and Observers will always be run on an event based basis

         # 如果runonce设置为True，在计算指标的时候，将会按照向量的方式进行.策略和observers将会按照事件驱动的模式进行

      - ``live`` (default: ``False``)

        If no data has reported itself as *live* (via the data's ``islive``
        method but the end user still want to run in ``live`` mode, this
        parameter can be set to true

        This will simultaneously deactivate ``preload`` and ``runonce``. It
        will have no effect on memory saving schemes.

        # 默认情况是False，意味着，如果我们没有给数据传入"islive"这个方法，默认的就是回测了。
        # 如果把live设置成True了，那么，默认就会不使用preload 和 runonce,这样，一般回测速度就会变慢。

      - ``maxcpus`` (default: None -> all available cores)

         How many cores to use simultaneously for optimization
        # 优化参数的时候使用的参数，我一般不用这个优化功能，使用的我自己写的多进程回测的模式，优化参数这个地方有bug，有的策略正常，有的策略出错
        # 不建议使用，如果要使用的时候，建议把maxcpus设置成自己电脑的cpu数目减去一，要不然，可能容易死机。

      - ``stdstats`` (default: ``True``)

        If True default Observers will be added: Broker (Cash and Value),
        Trades and BuySell
         # 控制是否会加载observer的参数，默认是True，加载Broker的Cash和Value，Trades and BuySell
        # 我一般默认的都是True,画图的时候用的，我其实可以取消，因为不怎么用cerebro.plot()画出来图形来观察买卖点

      - ``oldbuysell`` (default: ``False``)

        If ``stdstats`` is ``True`` and observers are getting automatically
        added, this switch controls the main behavior of the ``BuySell``
        observer

        - ``False``: use the modern behavior in which the buy / sell signals
          are plotted below / above the low / high prices respectively to avoid
          cluttering the plot

        - ``True``: use the deprecated behavior in which the buy / sell signals
          are plotted where the average price of the order executions for the
          given moment in time is. This will of course be on top of an OHLC bar
          or on a Line on Cloe bar, difficulting the recognition of the plot.
           # 如果stdstats设置成True了，那么，oldbuysell的默认值就无关紧要了，都是使用的``BuySell``

        # 如果stdstats设置成True了，如果``oldbuysell``是默认值False，画图的时候，买卖点的位置就会画在K线的
        # 最高点和最低点之外，避免画到K线上

        # 如果stdstats设置成True了，如果``oldbuysell``是True,就会把买卖信号画在成交时候的平均价的地方，会在K线上
        # 比较难辨认。

      - ``oldtrades`` (default: ``False``)

        If ``stdstats`` is ``True`` and observers are getting automatically
        added, this switch controls the main behavior of the ``Trades``
        observer

        - ``False``: use the modern behavior in which trades for all datas are
          plotted with different markers

        - ``True``: use the old Trades observer which plots the trades with the
          same markers, differentiating only if they are positive or negative

        # 也和画图相关，oldtrades是True的时候，同一方向的交易没有区别，oldtrades是False的时候,
        # 不同的交易使用不同的标记


      - ``exactbars`` (default: ``False``)

        With the default value each and every value stored in a line is kept in
        memory

        Possible values:
          - ``True`` or ``1``: all "lines" objects reduce memory usage to the
            automatically calculated minimum period.

            If a Simple Moving Average has a period of 30, the underlying data
            will have always a running buffer of 30 bars to allow the
            calculation of the Simple Moving Average

            - This setting will deactivate ``preload`` and ``runonce``
            - Using this setting also deactivates **plotting**

          - ``-1``: datafreeds and indicators/operations at strategy level will
            keep all data in memory.

            For example: a ``RSI`` internally uses the indicator ``UpDay`` to
            make calculations. This subindicator will not keep all data in
            memory

            - This allows to keep ``plotting`` and ``preloading`` active.

            - ``runonce`` will be deactivated

          - ``-2``: data feeds and indicators kept as attributes of the
            strategy will keep all points in memory.

            For example: a ``RSI`` internally uses the indicator ``UpDay`` to
            make calculations. This subindicator will not keep all data in
            memory

            If in the ``__init__`` something like
            ``a = self.data.close - self.data.high`` is defined, then ``a``
            will not keep all data in memory

            - This allows to keep ``plotting`` and ``preloading`` active.

            - ``runonce`` will be deactivated

             # 储存多少个K线的数据在记忆中

        # 当exactbars的值是True或者是1的时候，只保存满足最小需求的K线的数据，这会取消preload,runonce,plotting

        # 当exactbars的值是-1的时候，数据、指标、运算结果会保存下来，但是指标运算内的中间变量不会保存，这个会取消掉runonce

        # 当exactbars的值是-2的时候，数据、指标、运算结果会保存下来，但是指标内的，指标间的变量，如果没有使用self进行保存，就会消失
        # 可以验证下，-2的结果是否是对的

      - ``objcache`` (default: ``False``)

        Experimental option to implement a cache of lines objects and reduce
        the amount of them. Example from UltimateOscillator::

          bp = self.data.close - TrueLow(self.data)
          tr = TrueRange(self.data)  # -> creates another TrueLow(self.data)

        If this is ``True`` the 2nd ``TrueLow(self.data)`` inside ``TrueRange``
        matches the signature of the one in the ``bp`` calculation. It will be
        reused.

        Corner cases may happen in which this drives a line object off its
        minimum period and breaks things and it is therefore disabled.
         # 缓存，如果设置成True了，在指标计算的过程中，如果上面已经计算过了，形成了一个line，
        # 下面要用到指标是同样名字的,就不再计算，而是使用上面缓存中的指标

      - ``writer`` (default: ``False``)

        If set to ``True`` a default WriterFile will be created which will
        print to stdout. It will be added to the strategy (in addition to any
        other writers added by the user code)
         # writer 如果设置成True，输出的信息将会保存到一个默认的文件中
        # 没怎么用过这个功能，每次写策略，都是在strategy中，按照自己需求定制的信息

      - ``tradehistory`` (default: ``False``)

        If set to ``True``, it will activate update event logging in each trade
        for all strategies. This can also be accomplished on a per strategy
        basis with the strategy method ``set_tradehistory``
         # 如果tradehistory设置成了True，这将会激活这样一个功能，在所有策略中，每次交易的信息将会被log
        # 这个也可以在每个策略层面上，使用set_tradehistory来实现。

      - ``optdatas`` (default: ``True``)

        If ``True`` and optimizing (and the system can ``preload`` and use
        ``runonce``, data preloading will be done only once in the main process
        to save time and resources.

        The tests show an approximate ``20%`` speed-up moving from a sample
        execution in ``83`` seconds to ``66``
         # optdatas设置成True，如果preload和runonce也是True的话，数据的预加载将会只进行一次，在
        # 优化参数的时候，可以节省很多的时间


      - ``optreturn`` (default: ``True``)

        If ``True`` the optimization results will not be full ``Strategy``
        objects (and all *datas*, *indicators*, *observers* ...) but and object
        with the following attributes (same as in ``Strategy``):

          - ``params`` (or ``p``) the strategy had for the execution
          - ``analyzers`` the strategy has executed

        In most occassions, only the *analyzers* and with which *params* are
        the things needed to evaluate a the performance of a strategy. If
        detailed analysis of the generated values for (for example)
        *indicators* is needed, turn this off

        The tests show a ``13% - 15%`` improvement in execution time. Combined
        with ``optdatas`` the total gain increases to a total speed-up of
        ``32%`` in an optimization run.
         # optreturn,设置成True之后，在优化参数的时候，返回的结果中，只包含参数和analyzers,为了提高速度，
        # 舍弃了数据，指标，observers,这可以提高优化的速度。

      - ``oldsync`` (default: ``False``)

        Starting with release 1.9.0.99 the synchronization of multiple datas
        (same or different timeframes) has been changed to allow datas of
        different lengths.

        If the old behavior with data0 as the master of the system is wished,
        set this parameter to true
         # 当这个参数设置成False的时候，可以允许数据有不同的长度。如果想要返回旧版本那种，
        # 用data0作为主数据的方式，就可以把这个参数设置成True

      - ``tz`` (default: ``None``)

        Adds a global timezone for strategies. The argument ``tz`` can be

          - ``None``: in this case the datetime displayed by strategies will be
            in UTC, which has been always the standard behavior

          - ``pytz`` instance. It will be used as such to convert UTC times to
            the chosen timezone

          - ``string``. Instantiating a ``pytz`` instance will be attempted.

          - ``integer``. Use, for the strategy, the same timezone as the
            corresponding ``data`` in the ``self.datas`` iterable (``0`` would
            use the timezone from ``data0``)
            # 给策略添加时区
        # 如果忽略的话，tz就是None，就默认使用的是UTC时区
        # 如果是pytz的实例，是一个时区的话，就会把UTC时区转变为选定的新的时区
        # 如果是一个字符串，将会尝试转化为一个pytz实例
        # 如果是一个整数，将会使用某个数据的时区作为时区，如0代表第一个加载进去的数据的时区

      - ``cheat_on_open`` (default: ``False``)

        The ``next_open`` method of strategies will be called. This happens
        before ``next`` and before the broker has had a chance to evaluate
        orders. The indicators have not yet been recalculated. This allows
        issuing an orde which takes into account the indicators of the previous
        day but uses the ``open`` price for stake calculations

        For cheat_on_open order execution, it is also necessary to make the
        call ``cerebro.broker.set_coo(True)`` or instantite a broker with
        ``BackBroker(coo=True)`` (where *coo* stands for cheat-on-open) or set
        the ``broker_coo`` parameter to ``True``. Cerebro will do it
        automatically unless disabled below.
        # 为了方便使用开盘价计算手数设计的，默认是false，我们下单的时候不知道下个bar的open的开盘价，
        # 如果要下特定金额的话，只能用收盘价替代，如果下个交易日开盘之后高开或者低开，成交的金额可能离
        # 我们的目标金额很大。
        # 如果设置成True的话，我们就可以实现这个功能。在每次next之后，在next_open中进行下单，在next_open的时候
        # 还没有到next,系统还没有机会执行订单，指标还未能够重新计算，但是我们已经可以获得下个bar的开盘价了，并且可以
        # 更加精确的计算相应的手数了。
        # 使用这个功能，同时还需要设置cerebro.broker.set_coo(True)，或者加载broker的时候使用BackBroker(coo=True)，或者
        # cerebro的参数额外传入一个broker_coo=True

      - ``broker_coo`` (default: ``True``)

        This will automatically invoke the ``set_coo`` method of the broker
        with ``True`` to activate ``cheat_on_open`` execution. Will only do it
        if ``cheat_on_open`` is also ``True``
        # 这个参数是和上个参数cheat_on_open一块使用的

      - ``quicknotify`` (default: ``False``)

        Broker notifications are delivered right before the delivery of the
        *next* prices. For backtesting this has no implications, but with live
        brokers a notification can take place long before the bar is
        delivered. When set to ``True`` notifications will be delivered as soon
        as possible (see ``qcheck`` in live feeds)

        Set to ``False`` for compatibility. May be changed to ``True``
        # quicknotify，控制broker发送通知的时间，如果设置成False，那么，只有在next的时候才会发送
        # 设置成True的时候，产生就会立刻发送。

    '''
    # 参数
    params = (
        ('preload', True),
        ('runonce', True),
        ('maxcpus', None),
        ('stdstats', True),
        ('oldbuysell', False),
        ('oldtrades', False),
        ('lookahead', 0),
        ('exactbars', False),
        ('optdatas', True),
        ('optreturn', True),
        ('objcache', False),
        ('live', False),
        ('writer', False),
        ('tradehistory', False),
        ('oldsync', False),
        ('tz', None),
        ('cheat_on_open', False),
        ('broker_coo', True),
        ('quicknotify', False),
    )

    # 初始化
    def __init__(self):
        # 是否是实盘，初始化的时候，默认不是实盘
        self._dolive = False
        # 是否replay,初始化的时候，默认不replay
        self._doreplay = False
        # 是否优化，初始化的时候，默认不优化
        self._dooptimize = False
        # 保存store
        self.stores = list()
        # 保存feed
        self.feeds = list()
        # 保存data
        self.datas = list()
        # 默认有序字典，根据名字保存数据
        self.datasbyname = collections.OrderedDict()
        # 保存策略
        self.strats = list()
        # 保存待优化的策略
        self.optcbs = list()  # holds a list of callbacks for opt strategies
        # 保存observer
        self.observers = list()
        # 保存analyzer
        self.analyzers = list()
        # 保存indicator
        self.indicators = list()
        # 初始化sizer
        self.sizers = dict()
        # 保存writer
        self.writers = list()
        # 保存storecb
        self.storecbs = list()
        # 保存datacb
        self.datacbs = list()
        # 保存信号
        self.signals = list()
        # 信号策略
        self._signal_strat = (None, None, None)
        # 是否允许在有信号没有成交的时候继续执行新的信号，默认不允许
        self._signal_concurrent = False
        # 是否允许在有持仓的时候，继续执行信号，默认不允许
        self._signal_accumulate = False
        # data的标示号，dataid
        self._dataid = itertools.count(1)
        # 使用哪一个broker
        self._broker = BackBroker()
        # 给broker设置cerebro属性值
        self._broker.cerebro = self
        # 交易日历，默认是None
        self._tradingcal = None  # TradingCalendar()
        # 保存pretimer
        self._pretimers = list()
        # 保存历史order
        self._ohistory = list()
        # fund历史默认是None
        self._fhistory = None

    # 这个函数会把可迭代对象中的每个元素变成都是可迭代的
    @staticmethod
    def iterize(iterable):
        '''Handy function which turns things into things that can be iterated upon
        including iterables
        '''
        niterable = list()
        for elem in iterable:
            if isinstance(elem, string_types):
                elem = (elem,)
            elif not isinstance(elem, collections.Iterable):
                elem = (elem,)

            niterable.append(elem)

        return niterable

    # 设置fund历史，其中fund是一个可迭代对象，每个元素包含三个元素，时间，每份价值，净资产价值
    def set_fund_history(self, fund):
        '''
        Add a history of orders to be directly executed in the broker for
        performance evaluation

          - ``fund``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also an iterable (with length) with
            the following sub-elements (2 formats are possible)

            ``[datetime, share_value, net asset value]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``share_value`` is an float/integer
              - ``net_asset_value`` is a float/integer
        '''
        self._fhistory = fund

    # 增加order历史，orders是一个可迭代对象，每个元素是包含时间、大小、价格三个变量，还可以额外加入data变量
    # data可能是第一个数据，也可能是一个整数，代表在datas中的index,也可能是一个字符串，代表添加数据的名字
    # notify如果设置的是True的话，cerebro中添加的第一个策略将会通知订单信息
    def add_order_history(self, orders, notify=True):
        '''
        Add a history of orders to be directly executed in the broker for
        performance evaluation

          - ``orders``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also an iterable (with length) with
            the following sub-elements (2 formats are possible)

            ``[datetime, size, price]`` or ``[datetime, size, price, data]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``size`` is an integer (positive to *buy*, negative to *sell*)
              - ``price`` is a float/integer
              - ``data`` if present can take any of the following values

                - *None* - The 1st data feed will be used as target
                - *integer* - The data with that index (insertion order in
                  **Cerebro**) will be used
                - *string* - a data with that name, assigned for example with
                  ``cerebro.addata(data, name=value)``, will be the target

          - ``notify`` (default: *True*)

            If ``True`` the 1st strategy inserted in the system will be
            notified of the artificial orders created following the information
            from each order in ``orders``

        **Note**: Implicit in the description is the need to add a data feed
          which is the target of the orders. This is for example needed by
          analyzers which track for example the returns
        '''
        self._ohistory.append((orders, notify))

    # 定时器信息通知
    def notify_timer(self, timer, when, *args, **kwargs):
        '''Receives a timer notification where ``timer`` is the timer which was
        returned by ``add_timer``, and ``when`` is the calling time. ``args``
        and ``kwargs`` are any additional arguments passed to ``add_timer``

        The actual ``when`` time can be later, but the system may have not be
        able to call the timer before. This value is the timer value and no the
        system time.
        '''
        pass

    # 添加定时器
    def _add_timer(self, owner, when,
                   offset=datetime.timedelta(), repeat=datetime.timedelta(),
                   weekdays=[], weekcarry=False,
                   monthdays=[], monthcarry=True,
                   allow=None,
                   tzdata=None, strats=False, cheat=False,
                   *args, **kwargs):
        '''Internal method to really create the timer (not started yet) which
        can be called by cerebro instances or other objects which can access
        cerebro'''

        timer = Timer(
            tid=len(self._pretimers),
            owner=owner, strats=strats,
            when=when, offset=offset, repeat=repeat,
            weekdays=weekdays, weekcarry=weekcarry,
            monthdays=monthdays, monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata, cheat=cheat,
            *args, **kwargs
        )

        self._pretimers.append(timer)
        return timer

    # 添加定时器，参数的含义可以参考：
    # https://yunjinqi.blog.csdn.net/article/details/124560191
    # https://yunjinqi.blog.csdn.net/article/details/124652096
    def add_timer(self, when,
                  offset=datetime.timedelta(), repeat=datetime.timedelta(),
                  weekdays=[], weekcarry=False,
                  monthdays=[], monthcarry=True,
                  allow=None,
                  tzdata=None, strats=False, cheat=False,
                  *args, **kwargs):
        '''
        Schedules a timer to invoke ``notify_timer``

        Arguments:

          - ``when``: can be

            - ``datetime.time`` instance (see below ``tzdata``)
            - ``bt.timer.SESSION_START`` to reference a session start
            - ``bt.timer.SESSION_END`` to reference a session end

         - ``offset`` which must be a ``datetime.timedelta`` instance

           Used to offset the value ``when``. It has a meaningful use in
           combination with ``SESSION_START`` and ``SESSION_END``, to indicated
           things like a timer being called ``15 minutes`` after the session
           start.

          - ``repeat`` which must be a ``datetime.timedelta`` instance

            Indicates if after a 1st call, further calls will be scheduled
            within the same session at the scheduled ``repeat`` delta

            Once the timer goes over the end of the session it is reset to the
            original value for ``when``

          - ``weekdays``: a **sorted** iterable with integers indicating on
            which days (iso codes, Monday is 1, Sunday is 7) the timers can
            be actually invoked

            If not specified, the timer will be active on all days

          - ``weekcarry`` (default: ``False``). If ``True`` and the weekday was
            not seen (ex: trading holiday), the timer will be executed on the
            next day (even if in a new week)

          - ``monthdays``: a **sorted** iterable with integers indicating on
            which days of the month a timer has to be executed. For example
            always on day *15* of the month

            If not specified, the timer will be active on all days

          - ``monthcarry`` (default: ``True``). If the day was not seen
            (weekend, trading holiday), the timer will be executed on the next
            available day.

          - ``allow`` (default: ``None``). A callback which receives a
            `datetime.date`` instance and returns ``True`` if the date is
            allowed for timers or else returns ``False``

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

          - ``strats`` (default: ``False``) call also the ``notify_timer`` of
            strategies

          - ``cheat`` (default ``False``) if ``True`` the timer will be called
            before the broker has a chance to evaluate the orders. This opens
            the chance to issue orders based on opening price for example right
            before the session starts
          - ``*args``: any extra args will be passed to ``notify_timer``

          - ``**kwargs``: any extra kwargs will be passed to ``notify_timer``

        Return Value:

          - The created timer

        '''
        return self._add_timer(
            owner=self, when=when, offset=offset, repeat=repeat,
            weekdays=weekdays, weekcarry=weekcarry,
            monthdays=monthdays, monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata, strats=strats, cheat=cheat,
            *args, **kwargs)

    # 添加时区,参数含义参考
    # tz的参数和add_timer中比较类似
    def addtz(self, tz):
        '''
        This can also be done with the parameter ``tz``

        Adds a global timezone for strategies. The argument ``tz`` can be

          - ``None``: in this case the datetime displayed by strategies will be
            in UTC, which has been always the standard behavior

          - ``pytz`` instance. It will be used as such to convert UTC times to
            the chosen timezone

          - ``string``. Instantiating a ``pytz`` instance will be attempted.

          - ``integer``. Use, for the strategy, the same timezone as the
            corresponding ``data`` in the ``self.datas`` iterable (``0`` would
            use the timezone from ``data0``)

        '''
        self.p.tz = tz

    # 增加日历，具体参数可以参考
    # https://blog.csdn.net/qq_26948675/article/details/124652314
    # cal可以是字符串，TradingCalendar的实例，pandas_market_calendars的实例，或者TradingCalendar的子类
    def addcalendar(self, cal):
        '''Adds a global trading calendar to the system. Individual data feeds
        may have separate calendars which override the global one

        ``cal`` can be an instance of ``TradingCalendar`` a string or an
        instance of ``pandas_market_calendars``. A string will be will be
        instantiated as a ``PandasMarketCalendar`` (which needs the module
        ``pandas_market_calendar`` installed in the system.

        If a subclass of `TradingCalendarBase` is passed (not an instance) it
        will be instantiated
        '''
        # 如果是字符串或者具有valid_days属性，使用PandasMarketCalendar实例化
        if isinstance(cal, string_types):
            cal = PandasMarketCalendar(calendar=cal)
        elif hasattr(cal, 'valid_days'):
            cal = PandasMarketCalendar(calendar=cal)
        # 如果是TradingCalendarBase的子类，直接实例化，如果已经是一个实例，忽略
        else:
            try:
                if issubclass(cal, TradingCalendarBase):
                    cal = cal()
            except TypeError:  # already an instance
                pass
        # 给_tradingcal赋值
        self._tradingcal = cal

    # 增加信号，这些信号会在后面添加到SignalStrategy中
    def add_signal(self, sigtype, sigcls, *sigargs, **sigkwargs):
        '''Adds a signal to the system which will be later added to a
        ``SignalStrategy``'''
        self.signals.append((sigtype, sigcls, sigargs, sigkwargs))

    # 信号策略及其参数
    def signal_strategy(self, stratcls, *args, **kwargs):
        '''Adds a SignalStrategy subclass which can accept signals'''
        self._signal_strat = (stratcls, args, kwargs)

    # 是否允许在订单没有成交的时候执行新的信号或者订单
    def signal_concurrent(self, onoff):
        '''If signals are added to the system and the ``concurrent`` value is
        set to True, concurrent orders will be allowed'''
        self._signal_concurrent = onoff

    # 是否允许在有持仓的情况下执行新的订单
    def signal_accumulate(self, onoff):
        '''If signals are added to the system and the ``accumulate`` value is
        set to True, entering the market when already in the market, will be
        allowed to increase a position'''
        self._signal_accumulate = onoff

    # 增加新的store
    def addstore(self, store):
        '''Adds an ``Store`` instance to the if not already present'''
        if store not in self.stores:
            self.stores.append(store)

    # 增加新的writer
    def addwriter(self, wrtcls, *args, **kwargs):
        '''Adds an ``Writer`` class to the mix. Instantiation will be done at
        ``run`` time in cerebro
        '''
        self.writers.append((wrtcls, args, kwargs))

    # 设置sizer,sizer只能有一个
    def addsizer(self, sizercls, *args, **kwargs):
        '''Adds a ``Sizer`` class (and args) which is the default sizer for any
        strategy added to cerebro
        '''
        self.sizers[None] = (sizercls, args, kwargs)

    # 根据策略的顺序添加sizer,策略和sizer是根据idx对应的，各个sizer会应用到对应的策略中
    def addsizer_byidx(self, idx, sizercls, *args, **kwargs):
        '''Adds a ``Sizer`` class by idx. This idx is a reference compatible to
        the one returned by ``addstrategy``. Only the strategy referenced by
        ``idx`` will receive this size
        '''
        self.sizers[idx] = (sizercls, args, kwargs)

    # 添加指标
    def addindicator(self, indcls, *args, **kwargs):
        '''
        Adds an ``Indicator`` class to the mix. Instantiation will be done at
        ``run`` time in the passed strategies
        '''
        self.indicators.append((indcls, args, kwargs))

    # 添加analyzer
    def addanalyzer(self, ancls, *args, **kwargs):
        '''
        Adds an ``Analyzer`` class to the mix. Instantiation will be done at
        ``run`` time
        '''
        self.analyzers.append((ancls, args, kwargs))

    # 添加observer
    def addobserver(self, obscls, *args, **kwargs):
        '''
        Adds an ``Observer`` class to the mix. Instantiation will be done at
        ``run`` time
        '''
        self.observers.append((False, obscls, args, kwargs))

    # 给每个数据都增加一个observer
    def addobservermulti(self, obscls, *args, **kwargs):
        '''

        It will be added once per "data" in the system. A use case is a
        buy/sell observer which observes individual datas.

        A counter-example is the CashValue, which observes system-wide values
        '''
        self.observers.append((True, obscls, args, kwargs))

    # 增加一个callback用于获取notify_store方法处理的信息
    def addstorecb(self, callback):
        '''Adds a callback to get messages which would be handled by the
        notify_store method

        The signature of the callback must support the following:

          - callback(msg, \*args, \*\*kwargs)

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        '''
        self.storecbs.append(callback)

    # 通知store的信息
    def _notify_store(self, msg, *args, **kwargs):
        for callback in self.storecbs:
            callback(msg, *args, **kwargs)

        self.notify_store(msg, *args, **kwargs)

    # 通知store的信息，可以在cerebro的子类中重写
    def notify_store(self, msg, *args, **kwargs):
        '''Receive store notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        '''
        pass

    # 对store中的信息进行通知，并传递到每个运行的策略中
    def _storenotify(self):
        for store in self.stores:
            for notif in store.get_notifications():
                msg, args, kwargs = notif

                self._notify_store(msg, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.notify_store(msg, *args, **kwargs)

    # 增加一个callable用于获取notify_data通知的信息
    def adddatacb(self, callback):
        '''Adds a callback to get messages which would be handled by the
        notify_data method

        The signature of the callback must support the following:

          - callback(data, status, \*args, \*\*kwargs)

        The actual ``*args`` and ``**kwargs`` received are implementation
        defined (depend entirely on the *data/broker/store*) but in general one
        should expect them to be *printable* to allow for reception and
        experimentation.
        '''
        self.datacbs.append(callback)

    # 数据信息通知
    def _datanotify(self):
        for data in self.datas:
            for notif in data.get_notifications():
                status, args, kwargs = notif
                self._notify_data(data, status, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.notify_data(data, status, *args, **kwargs)

    # 通知数据信息
    def _notify_data(self, data, status, *args, **kwargs):
        for callback in self.datacbs:
            callback(data, status, *args, **kwargs)

        self.notify_data(data, status, *args, **kwargs)

    # 通知数据信息
    def notify_data(self, data, status, *args, **kwargs):
        '''Receive data notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        '''
        pass

    # 增加数据，这个是比较常用的功能
    def adddata(self, data, name=None):
        '''
        Adds a ``Data Feed`` instance to the mix.

        If ``name`` is not None it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.
        '''
        # 如果name不是None的话，就把name赋值给data._name
        if name is not None:
            data._name = name
            # todo 下面是修改的代码，能够直接通过data.name访问data的名称
            data.name = name
        # data._id每次增加一个数据，就会增加一个
        data._id = next(self._dataid)
        # 设置data的环境
        data.setenvironment(self)
        # 把data追加到self.datas
        self.datas.append(data)
        # 根据data._name和data分别作为字典的key和value
        self.datasbyname[data._name] = data
        # 从data中得到feed
        feed = data.getfeed()
        # 如果feed不是None,并且feed没有在feeds中
        if feed and feed not in self.feeds:
            # 把feed追加到self.feeds中
            self.feeds.append(feed)
        # 如果data是实时数据，把_dolive的值变为True
        if data.islive():
            self._dolive = True

        return data

    # chaindata的使用方法，把几个数据拼接起来
    # https://blog.csdn.net/qq_26948675/article/details/124461126
    def chaindata(self, *args, **kwargs):
        '''
        Chains several data feeds into one

        If ``name`` is passed as named argument and is not None it will be put
        into ``data._name`` which is meant for decoration/plotting purposes.

        If ``None``, then the name of the 1st data will be used
        '''
        dname = kwargs.pop('name', None)
        if dname is None:
            dname = args[0]._dataname
        d = bt.feeds.Chainer(dataname=dname, *args)
        self.adddata(d, name=dname)

        return d

    # rollover的用法，满足一定条件之后，在不同数据之间切换
    def rolloverdata(self, *args, **kwargs):
        '''Chains several data feeds into one

        If ``name`` is passed as named argument and is not None it will be put
        into ``data._name`` which is meant for decoration/plotting purposes.

        If ``None``, then the name of the 1st data will be used

        Any other kwargs will be passed to the RollOver class

        '''
        dname = kwargs.pop('name', None)
        if dname is None:
            dname = args[0]._dataname
        d = bt.feeds.RollOver(dataname=dname, *args, **kwargs)
        self.adddata(d, name=dname)

        return d

    # replay的使用
    def replaydata(self, dataname, name=None, **kwargs):
        '''
        Adds a ``Data Feed`` to be replayed by the system

        If ``name`` is not None it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the replay filter will be passed transparently
        '''
        if any(dataname is x for x in self.datas):
            dataname = dataname.clone()

        dataname.replay(**kwargs)
        self.adddata(dataname, name=name)
        self._doreplay = True

        return dataname

    # resample的使用
    def resampledata(self, dataname, name=None, **kwargs):
        '''
        Adds a ``Data Feed`` to be resample by the system

        If ``name`` is not None it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the resample filter will be passed transparently
        '''
        if any(dataname is x for x in self.datas):
            dataname = dataname.clone()

        dataname.resample(**kwargs)
        self.adddata(dataname, name=name)
        self._doreplay = True

        return dataname

    # 优化的callback
    def optcallback(self, cb):
        '''
        Adds a *callback* to the list of callbacks that will be called with the
        optimizations when each of the strategies has been run

        The signature: cb(strategy)
        '''
        self.optcbs.append(cb)

    # 优化策略，不推荐使用这个方法，大家考虑忽略
    def optstrategy(self, strategy, *args, **kwargs):
        '''
        Adds a ``Strategy`` class to the mix for optimization. Instantiation
        will happen during ``run`` time.

        args and kwargs MUST BE iterables which hold the values to check.

        Example: if a Strategy accepts a parameter ``period``, for optimization
        purposes the call to ``optstrategy`` looks like:

          - cerebro.optstrategy(MyStrategy, period=(15, 25))

        This will execute an optimization for values 15 and 25. Whereas

          - cerebro.optstrategy(MyStrategy, period=range(15, 25))

        will execute MyStrategy with ``period`` values 15 -> 25 (25 not
        included, because ranges are semi-open in Python)

        If a parameter is passed but shall not be optimized the call looks
        like:

          - cerebro.optstrategy(MyStrategy, period=(15,))

        Notice that ``period`` is still passed as an iterable ... of just 1
        element

        ``backtrader`` will anyhow try to identify situations like:

          - cerebro.optstrategy(MyStrategy, period=15)

        and will create an internal pseudo-iterable if possible
        '''
        self._dooptimize = True
        args = self.iterize(args)
        optargs = itertools.product(*args)

        optkeys = list(kwargs)

        vals = self.iterize(kwargs.values())
        optvals = itertools.product(*vals)

        okwargs1 = map(zip, itertools.repeat(optkeys), optvals)

        optkwargs = map(dict, okwargs1)

        it = itertools.product([strategy], optargs, optkwargs)
        self.strats.append(it)

    # 添加策略
    def addstrategy(self, strategy, *args, **kwargs):
        '''
        Adds a ``Strategy`` class to the mix for a single pass run.
        Instantiation will happen during ``run`` time.

        args and kwargs will be passed to the strategy as they are during
        instantiation.

        Returns the index with which addition of other objects (like sizers)
        can be referenced
        '''
        self.strats.append([(strategy, args, kwargs)])
        return len(self.strats) - 1

    # 设置broker
    def setbroker(self, broker):
        '''
        Sets a specific ``broker`` instance for this strategy, replacing the
        one inherited from cerebro.
        '''
        self._broker = broker
        broker.cerebro = self
        return broker

    # 获取broker
    def getbroker(self):
        '''
        Returns the broker instance.

        This is also available as a ``property`` by the name ``broker``
        '''
        return self._broker

    broker = property(getbroker, setbroker)

    # 画图，backtrader的画图主要是基于matplotlib,需要考虑升级换代，
    # todo 后续准备考虑使用pyqt,pyechart,plotly,boken中的一个进行升级
    # 所以，plot部分相关的代码就不在解读
    def plot(self, plotter=None, numfigs=1, iplot=True, start=None, end=None,
             width=16, height=9, dpi=300, tight=True, use=None,
             **kwargs):
        '''
        Plots the strategies inside cerebro

        If ``plotter`` is None a default ``Plot`` instance is created and
        ``kwargs`` are passed to it during instantiation.

        ``numfigs`` split the plot in the indicated number of charts reducing
        chart density if wished

        ``iplot``: if ``True`` and running in a ``notebook`` the charts will be
        displayed inline

        ``use``: set it to the name of the desired matplotlib backend. It will
        take precedence over ``iplot``

        ``start``: An index to the datetime line array of the strategy or a
        ``datetime.date``, ``datetime.datetime`` instance indicating the start
        of the plot

        ``end``: An index to the datetime line array of the strategy or a
        ``datetime.date``, ``datetime.datetime`` instance indicating the end
        of the plot

        ``width``: in inches of the saved figure

        ``height``: in inches of the saved figure

        ``dpi``: quality in dots per inches of the saved figure

        ``tight``: only save actual content and not the frame of the figure
        '''
        if self._exactbars > 0:
            return

        if not plotter:
            from . import plot
            if self.p.oldsync:
                plotter = plot.Plot_OldSync(**kwargs)
            else:
                plotter = plot.Plot(**kwargs)

        # pfillers = {self.datas[i]: self._plotfillers[i]
        # for i, x in enumerate(self._plotfillers)}

        # pfillers2 = {self.datas[i]: self._plotfillers2[i]
        # for i, x in enumerate(self._plotfillers2)}

        figs = []
        for stratlist in self.runstrats:
            for si, strat in enumerate(stratlist):
                rfig = plotter.plot(strat, figid=si * 100,
                                    numfigs=numfigs, iplot=iplot,
                                    start=start, end=end, use=use)
                # pfillers=pfillers2)

                figs.append(rfig)

            plotter.show()

        return figs

    # 在优化的时候传递给cerebro多进程的模块
    def __call__(self, iterstrat):
        '''
        Used during optimization to pass the cerebro over the multiprocesing
        module without complains
        '''

        predata = self.p.optdatas and self._dopreload and self._dorunonce
        return self.runstrategies(iterstrat, predata=predata)

    # 删除runstrats,
    def __getstate__(self):
        '''
        Used during optimization to prevent optimization result `runstrats`
        from being pickled to subprocesses
        '''

        rv = vars(self).copy()
        if 'runstrats' in rv:
            del(rv['runstrats'])
        return rv

    # 当在策略内部或者其他地方调用这个函数的时候，将会很快停止执行
    def runstop(self):
        '''If invoked from inside a strategy or anywhere else, including other
        threads the execution will stop as soon as possible.'''
        self._event_stop = True  # signal a stop has been requested

    # 执行回测的核心方法，任何传递的参数将会影响cerebro中的标准参数，如果没有添加数据，将会立即停止
    # 根据是否是优化参数，返回的结果不同
    def run(self, **kwargs):
        '''The core method to perform backtesting. Any ``kwargs`` passed to it
        will affect the value of the standard parameters ``Cerebro`` was
        instantiated with.

        If ``cerebro`` has not datas the method will immediately bail out.

        It has different return values:

          - For No Optimization: a list contanining instances of the Strategy
            classes added with ``addstrategy``

          - For Optimization: a list of lists which contain instances of the
            Strategy classes added with ``addstrategy``
        '''
        self._event_stop = False  # Stop is requested
        # 如果没有数据，直接返回空的列表
        if not self.datas:
            return []  # nothing can be run
        # 用传递过来的关键字参数覆盖标准参数
        pkeys = self.params._getkeys()
        for key, val in kwargs.items():
            if key in pkeys:
                setattr(self.params, key, val)

        # Manage activate/deactivate object cache
        # 管理对象的缓存
        linebuffer.LineActions.cleancache()  # clean cache
        indicator.Indicator.cleancache()  # clean cache

        linebuffer.LineActions.usecache(self.p.objcache)
        indicator.Indicator.usecache(self.p.objcache)

        # 是否是_dorunonce,_dopreload,_exactbars
        self._dorunonce = self.p.runonce
        self._dopreload = self.p.preload
        self._exactbars = int(self.p.exactbars)
        # 如果_exactbars的值不是0的话，_dorunonce需要是False,如果_dopreload是True,并且_exactbars小于1的话，_dopreload设置成True
        if self._exactbars:
            self._dorunonce = False  # something is saving memory, no runonce
            self._dopreload = self._dopreload and self._exactbars < 1
        # 如果_doreplay是True或者数据中有任何一个具有replaying属性值是True的话，就把_doreplay设置成True
        self._doreplay = self._doreplay or any(x.replaying for x in self.datas)
        # 如果_doreplay,需要把_dopreload设置成False
        if self._doreplay:
            # preloading is not supported with replay. full timeframe bars
            # are constructed in realtime
            self._dopreload = False
        # 如果_dolive或者live,需要把_dorunonce和_dopreload设置成False
        if self._dolive or self.p.live:
            # in this case both preload and runonce must be off
            self._dorunonce = False
            self._dopreload = False

        # writer的列表
        self.runwriters = list()

        # Add the system default writer if requested
        # 如果writer参数是True的话，增加默认的writer
        if self.p.writer is True:
            wr = WriterFile()
            self.runwriters.append(wr)

        # Instantiate any other writers
        # 如果具有其他的writer的话，实例化之后添加到runwriters中
        for wrcls, wrargs, wrkwargs in self.writers:
            wr = wrcls(*wrargs, **wrkwargs)
            self.runwriters.append(wr)

        # Write down if any writer wants the full csv output
        # 如果那个writer需要全部的csv的输出，把结果保存到文件中
        self.writers_csv = any(map(lambda x: x.p.csv, self.runwriters))

        # 运行的策略列表
        self.runstrats = list()
        # 如果signals不是None等，处理signalstrategy相关的问题
        if self.signals:  # allow processing of signals
            signalst, sargs, skwargs = self._signal_strat
            if signalst is None:
                # Try to see if the 1st regular strategy is a signal strategy
                try:
                    signalst, sargs, skwargs = self.strats.pop(0)
                except IndexError:
                    pass  # Nothing there
                else:
                    if not isinstance(signalst, SignalStrategy):
                        # no signal ... reinsert at the beginning
                        self.strats.insert(0, (signalst, sargs, skwargs))
                        signalst = None  # flag as not presetn

            if signalst is None:  # recheck
                # Still None, create a default one
                signalst, sargs, skwargs = SignalStrategy, tuple(), dict()

            # Add the signal strategy
            self.addstrategy(signalst,
                             _accumulate=self._signal_accumulate,
                             _concurrent=self._signal_concurrent,
                             signals=self.signals,
                             *sargs,
                             **skwargs)
        # 如果策略列表是空的话，添加策略
        if not self.strats:  # Datas are present, add a strategy
            self.addstrategy(Strategy)
        # 迭代策略
        iterstrats = itertools.product(*self.strats)
        # 如果不是优化参数，或者使用的cpu核数是1
        if not self._dooptimize or self.p.maxcpus == 1:
            # If no optimmization is wished ... or 1 core is to be used
            # let's skip process "spawning"
            # 遍历策略
            for iterstrat in iterstrats:
                # 运行策略
                runstrat = self.runstrategies(iterstrat)
                # 把运行的策略添加到运行策略的列表中
                self.runstrats.append(runstrat)
                # 如果是优化参数
                if self._dooptimize:
                    # 遍历所有的optcbs，以便返回停止策略的结果
                    for cb in self.optcbs:
                        cb(runstrat)  # callback receives finished strategy
        # 如果是优化参数
        else:
            # 如果optdatas是True,并且_dopreload，并且_dorunonce
            if self.p.optdatas and self._dopreload and self._dorunonce:
                # 遍历每个data,进行reset,如果_exactbars小于1，对数据进行extend处理
                # 开始数据
                # 如果数据_dopreload的话，对数据调用preload
                for data in self.datas:
                    data.reset()
                    if self._exactbars < 1:  # datas can be full length
                        data.extend(size=self.params.lookahead)
                    data._start()
                    # todo 这个里面重新判断self._dopreload好像是没有什么道理，因为前面已经保证self._dopreload是True了，尝试注释掉，提高效率
                    # if self._dopreload:
                    #     data.preload()
                    data.preload()
            # 开启进程池
            pool = multiprocessing.Pool(self.p.maxcpus or None)
            for r in pool.imap(self, iterstrats):
                self.runstrats.append(r)
                for cb in self.optcbs:
                    cb(r)  # callback receives finished strategy
            # 关闭进程词
            pool.close()
            # 如果optdatas是True,并且_dopreload，并且_dorunonce，遍历数据，并停止数据
            if self.p.optdatas and self._dopreload and self._dorunonce:
                for data in self.datas:
                    data.stop()
        # 如果不是参数优化
        if not self._dooptimize:
            # avoid a list of list for regular cases
            return self.runstrats[0]

        return self.runstrats

    # 初始化计数
    def _init_stcount(self):
        self.stcount = itertools.count(0)

    # 调用下个计数
    def _next_stid(self):
        return next(self.stcount)

    # 运行策略
    def runstrategies(self, iterstrat, predata=False):
        '''
        Internal method invoked by ``run``` to run a set of strategies
        '''
        # 初始化计数
        self._init_stcount()
        # 初始化运行的策略为空列表
        self.runningstrats = runstrats = list()
        # 遍历store，并开始
        for store in self.stores:
            store.start()
        # 如果cheat_on_open和broker_coo，给broker进行相应的设置
        if self.p.cheat_on_open and self.p.broker_coo:
            # try to activate in broker
            if hasattr(self._broker, 'set_coo'):
                self._broker.set_coo(True)
        # 如果fund历史不是None的话，需要设置fund history
        if self._fhistory is not None:
            self._broker.set_fund_history(self._fhistory)
        # 遍历order的历史
        for orders, onotify in self._ohistory:
            self._broker.add_order_history(orders, onotify)
        # broker开始
        self._broker.start()
        # feed开始
        for feed in self.feeds:
            feed.start()
        # 如果需要保存writer中的数据
        if self.writers_csv:
            # headers
            wheaders = list()
            # 遍历数据，如果数据的csv属性值是True的话，获取数据中的需要保存的headers
            for data in self.datas:
                if data.csv:
                    wheaders.extend(data.getwriterheaders())
            # 保存writer中的headers
            for writer in self.runwriters:
                if writer.p.csv:
                    writer.addheaders(wheaders)

        # self._plotfillers = [list() for d in self.datas]
        # self._plotfillers2 = [list() for d in self.datas]
        # 如果没有predata的话，需要提前预处理数据，和run中预处理数据的方法很相似
        if not predata:
            for data in self.datas:
                data.reset()
                if self._exactbars < 1:  # datas can be full length
                    data.extend(size=self.params.lookahead)
                data._start()
                if self._dopreload:
                    data.preload()
        # 循环策略
        for stratcls, sargs, skwargs in iterstrat:
            # 把数据添加到策略参数
            sargs = self.datas + list(sargs)
            # 实例化策略
            try:
                strat = stratcls(*sargs, **skwargs)
            except bt.errors.StrategySkipError:
                continue  # do not add strategy to the mix
            # 旧的数据同步方法
            if self.p.oldsync:
                strat._oldsync = True  # tell strategy to use old clock update
            # 是否保存交易历史数据
            if self.p.tradehistory:
                strat.set_tradehistory()
            # 添加策略
            runstrats.append(strat)
        # 获取时区信息，如果时区信息是整数，那么就获取该整数对应的index的时区，如果不是整数，就使用tzparse解析时区
        tz = self.p.tz
        if isinstance(tz, integer_types):
            tz = self.datas[tz]._tz
        else:
            tz = tzparse(tz)
        # 如果runstrats不是空的列表的话
        if runstrats:
            # loop separated for clarity
            # 获取默认的sizer
            defaultsizer = self.sizers.get(None, (None, None, None))
            # 对于每个策略
            for idx, strat in enumerate(runstrats):
                # 如果stdstats是True的话，会增加几个observer
                if self.p.stdstats:
                    # 增加observer的broker
                    strat._addobserver(False, observers.Broker)
                    # 增加observers.BuySell,
                    if self.p.oldbuysell:
                        strat._addobserver(True, observers.BuySell)
                    else:
                        strat._addobserver(True, observers.BuySell,
                                           barplot=True)
                    # 增加observer的trade
                    if self.p.oldtrades or len(self.datas) == 1:
                        strat._addobserver(False, observers.Trades)
                    else:
                        strat._addobserver(False, observers.DataTrades)
                # 把observers中的observer及其参数增加到策略中
                for multi, obscls, obsargs, obskwargs in self.observers:
                    strat._addobserver(multi, obscls, *obsargs, **obskwargs)
                # 把indicators中的indicator增加到策略中
                for indcls, indargs, indkwargs in self.indicators:
                    strat._addindicator(indcls, *indargs, **indkwargs)
                # 把analyzers中的analyzer增加到策略中
                for ancls, anargs, ankwargs in self.analyzers:
                    strat._addanalyzer(ancls, *anargs, **ankwargs)
                # 获取具体的sizer,如果sizer不是None,添加到策略中
                sizer, sargs, skwargs = self.sizers.get(idx, defaultsizer)
                if sizer is not None:
                    strat._addsizer(sizer, *sargs, **skwargs)
                # 设置时区
                strat._settz(tz)
                # 策略开始
                strat._start()
                # 对于正在运行的writer来说，如果csv参数是True的话，把策略中需要保存的数据保存到writer中
                for writer in self.runwriters:
                    if writer.p.csv:
                        writer.addheaders(strat.getwriterheaders())
            # 如果predata是False，没有提前加载数据
            if not predata:
                # 循环每个策略，调用qbuffer缓存数据
                for strat in runstrats:
                    strat.qbuffer(self._exactbars, replaying=self._doreplay)
            # 循环每个writer,开始writer
            for writer in self.runwriters:
                writer.start()

            # Prepare timers
            # 准备timers
            self._timers = []
            self._timerscheat = []
            # 循环timer
            for timer in self._pretimers:
                # preprocess tzdata if needed
                # 启动timer
                timer.start(self.datas[0])
                # 如果timer的参数cheat是True的话，就把timer增加到self._timerscheat，否则就增加到self._timers
                if timer.params.cheat:
                    self._timerscheat.append(timer)
                else:
                    self._timers.append(timer)
            # 如果_dopreload 和 _dorunonce是True的话
            if self._dopreload and self._dorunonce:
                # 如果是旧的数据对齐和同步方式，使用_runonce_old，否则使用_runonce
                if self.p.oldsync:
                    self._runonce_old(runstrats)
                else:
                    self._runonce(runstrats)
            # 如果_dopreload 和 _dorunonce并不都是True的话
            else:
                # 如果是旧的数据对齐和同步方式，使用_runnext_old，否则使用_runnext
                if self.p.oldsync:
                    self._runnext_old(runstrats)
                else:
                    self._runnext(runstrats)
            # 遍历策略并停止运行
            for strat in runstrats:
                strat._stop()
        # 停止broker
        self._broker.stop()
        # 如果predata是False的话，遍历数据并停止每个数据
        if not predata:
            for data in self.datas:
                data.stop()
        # 遍历每个feed,并停止feed
        for feed in self.feeds:
            feed.stop()
        # 遍历每个store,并停止store
        for store in self.stores:
            store.stop()
        # 停止writer
        self.stop_writers(runstrats)
        # 如果是做参数优化，并且optreturn是True的话，获取策略运行后的结果，并添加到results,返回该结果
        if self._dooptimize and self.p.optreturn:
            # Results can be optimized
            results = list()
            for strat in runstrats:
                for a in strat.analyzers:
                    a.strategy = None
                    a._parent = None
                    for attrname in dir(a):
                        if attrname.startswith('data'):
                            setattr(a, attrname, None)

                oreturn = OptReturn(strat.params, analyzers=strat.analyzers, strategycls=type(strat))
                results.append(oreturn)

            return results

        return runstrats

    # 停止writer
    def stop_writers(self, runstrats):
        # cerebro信息
        cerebroinfo = OrderedDict()
        # data信息
        datainfos = OrderedDict()
        # 获取每个数据的信息，保存到datainfos中，然后保存到cerebroinfo
        for i, data in enumerate(self.datas):
            datainfos['Data%d' % i] = data.getwriterinfo()

        cerebroinfo['Datas'] = datainfos
        # 获取策略信息，并保存到stratinfos和cerebroinfo
        stratinfos = dict()
        for strat in runstrats:
            stname = strat.__class__.__name__
            stratinfos[stname] = strat.getwriterinfo()

        cerebroinfo['Strategies'] = stratinfos
        # 把cerebroinfo写入文件中
        for writer in self.runwriters:
            writer.writedict(dict(Cerebro=cerebroinfo))
            writer.stop()

    # 通知broker信息
    def _brokernotify(self):
        '''
        Internal method which kicks the broker and delivers any broker
        notification to the strategy
        '''
        # 调用broker的next
        self._broker.next()
        while True:
            # 获取要通知的order信息，如果order是None,跳出循环，如果不是None,获取order的owner.如果owner是None的话，默认是第一个策略
            order = self._broker.get_notification()
            if order is None:
                break

            owner = order.owner
            if owner is None:
                owner = self.runningstrats[0]  # default
            # 通过第一个策略通知order信息
            owner._addnotification(order, quicknotify=self.p.quicknotify)

    # 就得runnext方法，和runnext很相似
    def _runnext_old(self, runstrats):
        '''
        Actual implementation of run in full next mode. All objects have its
        ``next`` method invoke on each data arrival
        '''
        data0 = self.datas[0]
        d0ret = True
        while d0ret or d0ret is None:
            lastret = False
            # Notify anything from the store even before moving datas
            # because datas may not move due to an error reported by the store
            self._storenotify()
            if self._event_stop:  # stop if requested
                return
            self._datanotify()
            if self._event_stop:  # stop if requested
                return

            d0ret = data0.next()
            if d0ret:
                for data in self.datas[1:]:
                    if not data.next(datamaster=data0):  # no delivery
                        data._check(forcedata=data0)  # check forcing output
                        data.next(datamaster=data0)  # retry

            elif d0ret is None:
                # meant for things like live feeds which may not produce a bar
                # at the moment but need the loop to run for notifications and
                # getting resample and others to produce timely bars
                data0._check()
                for data in self.datas[1:]:
                    data._check()
            else:
                lastret = data0._last()
                for data in self.datas[1:]:
                    lastret += data._last(datamaster=data0)

                if not lastret:
                    # Only go extra round if something was changed by "lasts"
                    break

            # Datas may have generated a new notification after next
            self._datanotify()
            if self._event_stop:  # stop if requested
                return

            self._brokernotify()
            if self._event_stop:  # stop if requested
                return

            if d0ret or lastret:  # bars produced by data or filters
                for strat in runstrats:
                    strat._next()
                    if self._event_stop:  # stop if requested
                        return

                    self._next_writers(runstrats)

        # Last notification chance before stopping
        self._datanotify()
        if self._event_stop:  # stop if requested
            return
        self._storenotify()
        if self._event_stop:  # stop if requested
            return

    # 旧的runonce方法，和runonce差不多
    def _runonce_old(self, runstrats):
        '''
        Actual implementation of run in vector mode.
        Strategies are still invoked on a pseudo-event mode in which ``next``
        is called for each data arrival
        '''
        for strat in runstrats:
            strat._once()

        # The default once for strategies does nothing and therefore
        # has not moved forward all datas/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        data0 = self.datas[0]
        datas = self.datas[1:]
        for i in range(data0.buflen()):
            data0.advance()
            for data in datas:
                data.advance(datamaster=data0)

            self._brokernotify()
            if self._event_stop:  # stop if requested
                return

            for strat in runstrats:
                # data0.datetime[0] for compat. w/ new strategy's oncepost
                strat._oncepost(data0.datetime[0])
                if self._event_stop:  # stop if requested
                    return

                self._next_writers(runstrats)

    # 运行writer的next
    def _next_writers(self, runstrats):
        if not self.runwriters:
            return

        if self.writers_csv:
            wvalues = list()
            for data in self.datas:
                if data.csv:
                    wvalues.extend(data.getwritervalues())

            for strat in runstrats:
                wvalues.extend(strat.getwritervalues())

            for writer in self.runwriters:
                if writer.p.csv:
                    writer.addvalues(wvalues)

                    writer.next()

    # 禁止runonce
    def _disable_runonce(self):
        '''API for lineiterators to disable runonce (see HeikinAshi)'''
        self._dorunonce = False

    # runnext方法
    def _runnext(self, runstrats):
        '''
        Actual implementation of run in full next mode. All objects have its
        ``next`` method invoke on each data arrival
        '''
        # 对数据的时间周期进行排序
        datas = sorted(self.datas,
                       key=lambda x: (x._timeframe, x._compression))
        # 其他数据
        datas1 = datas[1:]
        # 主数据
        data0 = datas[0]
        d0ret = True
        # resample的index
        rs = [i for i, x in enumerate(datas) if x.resampling]
        # replaying的index
        rp = [i for i, x in enumerate(datas) if x.replaying]
        # 仅仅只做resample,不做replay得index
        rsonly = [i for i, x in enumerate(datas) if x.resampling and not x.replaying]
        # 判断是否仅仅做resample
        onlyresample = len(datas) == len(rsonly)
        # 判断是否没有需要resample的数据
        noresample = not rsonly
        # 克隆的数据量
        clonecount = sum(d._clone for d in datas)
        # 数据的数量
        ldatas = len(datas)
        # 没有克隆的数据量
        ldatas_noclones = ldatas - clonecount
        lastqcheck = False
        # 默认dt0在最大时间
        dt0 = date2num(datetime.datetime.max) - 2  # default at max
        # while循环
        while d0ret or d0ret is None:
            # if any has live data in the buffer, no data will wait anything
            # 如果有任何实时数据的话，newqcheck是False
            newqcheck = not any(d.haslivedata() for d in datas)
            # 如果存在实时数据
            if not newqcheck:
                # If no data has reached the live status or all, wait for
                # the next incoming data
                # livecount是实时数据的量
                livecount = sum(d._laststatus == d.LIVE for d in datas)
                # todo 这个判断没有任何意义
                newqcheck = not livecount or livecount == ldatas_noclones

            lastret = False
            # Notify anything from the store even before moving datas
            # because datas may not move due to an error reported by the store
            # 通知store相关的信息
            self._storenotify()
            if self._event_stop:  # stop if requested
                return
            # 通知data相关的信息
            self._datanotify()
            if self._event_stop:  # stop if requested
                return

            # record starting time and tell feeds to discount the elapsed time
            # from the qcheck value
            # 记录开始的时间，并且通知feed从qcheck中减去qlapse的时间
            drets = []
            qstart = datetime.datetime.utcnow()
            for d in datas:
                qlapse = datetime.datetime.utcnow() - qstart
                d.do_qcheck(newqcheck, qlapse.total_seconds())
                drets.append(d.next(ticks=False))
            # 遍历drets,如果d0ret是False,并且存在dret是None的话，d0ret是None
            d0ret = any((dret for dret in drets))
            if not d0ret and any((dret is None for dret in drets)):
                d0ret = None
            # 如果d0ret不是None的话
            if d0ret:
                # 获取时间
                dts = []
                for i, ret in enumerate(drets):
                    dts.append(datas[i].datetime[0] if ret else None)

                # Get index to minimum datetime
                # 获取最小的时间
                if onlyresample or noresample:
                    dt0 = min((d for d in dts if d is not None))
                else:
                    dt0 = min((d for i, d in enumerate(dts)
                               if d is not None and i not in rsonly))
                # 获取主数据，及时间
                dmaster = datas[dts.index(dt0)]  # and timemaster
                self._dtmaster = dmaster.num2date(dt0)
                self._udtmaster = num2date(dt0)

                # slen = len(runstrats[0])
                # Try to get something for those that didn't return
                # 循环drets
                for i, ret in enumerate(drets):
                    # 如果ret不是None的话，继续下一个ret
                    if ret:  # dts already contains a valid datetime for this i
                        continue

                    # try to get a data by checking with a master
                    # 获取数据，并尝试给dts设置时间
                    d = datas[i]
                    d._check(forcedata=dmaster)  # check to force output
                    if d.next(datamaster=dmaster, ticks=False):  # retry
                        dts[i] = d.datetime[0]  # good -> store
                        # self._plotfillers2[i].append(slen)  # mark as fill
                    else:
                        # self._plotfillers[i].append(slen)  # mark as empty
                        pass

                # make sure only those at dmaster level end up delivering
                # 遍历dts
                for i, dti in enumerate(dts):
                    # 如果dti不是None
                    if dti is not None:
                        # 获取数据
                        di = datas[i]
                        # todo 代码写的很多余，rpi一定是返回的False,可以考虑注销
                        # rpi = False and di.replaying   # to check behavior
                        if dti > dt0:
                            # todo 此处rpi是False,not rpi是True,考虑注销，直接运行
                            # if not rpi:  # must see all ticks ...
                            di.rewind()  # cannot deliver yet
                            # self._plotfillers[i].append(slen)
                        # 如果不是replay
                        elif not di.replaying:
                            # Replay forces tick fill, else force here
                            di._tick_fill(force=True)

                        # self._plotfillers2[i].append(slen)  # mark as fill
            # 如果d0ret是None的话，遍历每个数据，调用_check()
            elif d0ret is None:
                # meant for things like live feeds which may not produce a bar
                # at the moment but need the loop to run for notifications and
                # getting resample and others to produce timely bars
                for data in datas:
                    data._check()
            # 如果是其他情况
            else:
                lastret = data0._last()
                for data in datas1:
                    lastret += data._last(datamaster=data0)

                if not lastret:
                    # Only go extra round if something was changed by "lasts"
                    break

            # Datas may have generated a new notification after next
            # 通知数据信息
            self._datanotify()
            if self._event_stop:  # stop if requested
                return
            # 检查timer和遍历策略并调用_next_open()进行运行
            if d0ret or lastret:  # if any bar, check timers before broker
                self._check_timers(runstrats, dt0, cheat=True)
                if self.p.cheat_on_open:
                    for strat in runstrats:
                        strat._next_open()
                        if self._event_stop:  # stop if requested
                            return
            # 通知broker
            self._brokernotify()
            if self._event_stop:  # stop if requested
                return
            # 通知timer,并且遍历策略并运行
            if d0ret or lastret:  # bars produced by data or filters
                self._check_timers(runstrats, dt0, cheat=False)
                for strat in runstrats:
                    strat._next()
                    if self._event_stop:  # stop if requested
                        return

                    self._next_writers(runstrats)

        # Last notification chance before stopping
        # 通知数据信息
        self._datanotify()
        if self._event_stop:  # stop if requested
            return
        # 通知store信息
        self._storenotify()
        if self._event_stop:  # stop if requested
            return

    # runonce
    def _runonce(self, runstrats):
        '''
        Actual implementation of run in vector mode.

        Strategies are still invoked on a pseudo-event mode in which ``next``
        is called for each data arrival
        '''
        # 遍历策略，调用_once和reset
        for strat in runstrats:
            strat._once()
            strat.reset()  # strat called next by next - reset lines

        # The default once for strategies does nothing and therefore
        # has not moved forward all datas/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        # 对数据进行排序，从小周期开始到大周期
        datas = sorted(self.datas,
                       key=lambda x: (x._timeframe, x._compression))

        while True:
            # Check next incoming date in the datas
            # 对于每个数据调用advance_peek(),取得最小的一个时间作为第一个
            dts = [d.advance_peek() for d in datas]
            dt0 = min(dts)
            if dt0 == float('inf'):
                break  # no data delivers anything

            # Timemaster if needed be
            # dmaster = datas[dts.index(dt0)]  # and timemaster
            # 第一个策略现在的长度slen
            slen = len(runstrats[0])
            # 对于每个数据的时间，如果时间小于即将到来的最小的时间，数据向前一位，否则，忽略
            for i, dti in enumerate(dts):
                if dti <= dt0:
                    datas[i].advance()
                    # self._plotfillers2[i].append(slen)  # mark as fill
                else:
                    # self._plotfillers[i].append(slen)
                    pass
            # 检查timer
            self._check_timers(runstrats, dt0, cheat=True)
            # 如果是cheat_on_open，对于每个策略调用_oncepost_open()
            if self.p.cheat_on_open:
                for strat in runstrats:
                    strat._oncepost_open()
                    # 如果调用了stop，就停止
                    if self._event_stop:  # stop if requested
                        return
            # 调用_brokernotify()
            self._brokernotify()
            # 如果调用了stop，就停止
            if self._event_stop:  # stop if requested
                return
            # 检查timer
            self._check_timers(runstrats, dt0, cheat=False)

            for strat in runstrats:
                strat._oncepost(dt0)
                if self._event_stop:  # stop if requested
                    return
                self._next_writers(runstrats)

    # 检查timer
    def _check_timers(self, runstrats, dt0, cheat=False):
        # 如果cheat是False的话，timers等于self._timers，否则就等于self._timerscheat
        timers = self._timers if not cheat else self._timerscheat
        # 对于timers中的timer
        for t in timers:
            # 使用timer.check(dt0),如果返回是True,就进入下面，否则，检查下个timer
            if not t.check(dt0):
                continue
            # 通知timer
            t.params.owner.notify_timer(t, t.lastwhen, *t.args, **t.kwargs)
            # 如果需要策略使用timer(t.params.strats是True）的时候，循环策略，调用notify_timer
            if t.params.strats:
                for strat in runstrats:
                    strat.notify_timer(t, t.lastwhen, *t.args, **t.kwargs)
