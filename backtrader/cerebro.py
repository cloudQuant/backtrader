#!/usr/bin/env python
"""Cerebro - The main engine of the Backtrader framework.

This module contains the Cerebro class, which is the central orchestrator for
backtesting and live trading operations. Cerebro manages data feeds, strategies,
brokers, analyzers, observers, and all other components of the trading system.

Key Features:
    - Data feed management and synchronization
    - Strategy instantiation and execution
    - Broker integration for order execution
    - Multi-core optimization support
    - Live trading and backtesting modes
    - Plotting and analysis capabilities

Example:
    Basic backtest setup::

        import backtrader as bt

        cerebro = bt.Cerebro()
        data = bt.feeds.GenericCSVData(dataname='data.csv')
        cerebro.adddata(data)
        cerebro.addstrategy(MyStrategy)
        cerebro.broker.setcash(100000)
        results = cerebro.run()
        cerebro.plot()

Classes:
    OptReturn: Lightweight result object for optimization runs.
    Cerebro: Main backtesting/trading engine.
"""
import collections
import datetime
import itertools
import multiprocessing
import traceback
from datetime import UTC

try:  # For new Python versions
    collectionsAbc = collections.abc  # collections.Iterable -> collections.abc.Iterable
except AttributeError:  # For old Python versions
    collectionsAbc = collections  # collections.Iterable

from . import errors, feeds, indicator, linebuffer, observers
from .brokers import BackBroker
from .dataseries import TimeFrame
from .metabase import OwnerContext
from .parameters import ParameterDescriptor, ParameterizedBase
from .strategy import SignalStrategy, Strategy
from .timer import Timer
from .tradingcal import PandasMarketCalendar, TradingCalendarBase
from .utils import OrderedDict, date2num, num2date, tzparse
from .utils.py3 import integer_types, map, range, string_types, zip
from .writer import WriterFile


class OptReturn:
    """Lightweight result container for optimization runs.

    This class is defined at module level to make it picklable for
    multiprocessing. It stores only essential information from strategy
    runs during optimization to reduce memory usage.

    Attributes:
        p: Alias for params.
        params: Strategy parameters used in this optimization run.
        analyzers: Analyzer results (if returned during optimization).

    Note:
        Additional attributes may be set dynamically via kwargs.
    """

    def __init__(self, params, **kwargs):
        """Initialize the OptReturn object.

        Args:
            params: Strategy parameters used in this optimization run.
            **kwargs: Additional keyword arguments to set as attributes.
        """
        self.p = self.params = params
        for k, v in kwargs.items():
            setattr(self, k, v)


class Cerebro(ParameterizedBase):
    """Params:

    - ``preload`` (default: ``True``)

      Whether to preload the different ``data feeds`` passed to cerebro for
      the Strategies

      Note: When True (default), data is loaded into memory before backtesting,
      which uses more memory but significantly improves execution speed.

    - ``runonce`` (default: ``True``)

      Run `Indicators` in vectorized mode to speed up the entire system.
      Strategies and Observers will always be run on an event-based basis

      Note: When True, indicators are calculated using vectorized operations
      for better performance. Strategies and observers still run event-by-event.

    - ``live`` (default: ``False``)

      If no data has reported itself as *live* (via the data's ``islive``
      method but the end user still wants to run in ``live`` mode, this
      parameter can be set to true

      This will simultaneously deactivate ``preload`` and ``runonce``. It
      will have no effect on memory saving schemes.

      Note: Setting to True forces live mode behavior, disabling preload and
      runonce optimizations, which slows down backtesting.

    - ``maxcpus`` (default: None -> all available cores)

       How many cores to use simultaneously for optimization

      Note: Set to number of CPU cores minus 1 to avoid system overload.
      Use None (default) to use all available cores.

    - ``stdstats`` (default: ``True``)

      If True, default Observers will be added: Broker (Cash and Value),
      Trades and BuySell

      Note: These observers are used for plotting. Set to False if not needed.

    - ``oldbuysell`` (default: ``False``)

      If ``stdstats`` is ``True`` and observers are getting automatically
      added, this switch controls the main behavior of the ``BuySell``
      observer

      - ``False``: use the modern behavior in which the buy / sell signals
        are plotted below / above the low / high prices respectively to avoid
        cluttering the plot

      - ``True``: use the deprecated behavior in which the buy / sell signals
        are plotted where the average price of the order executions for the
        given moment in time is. This will, of course, be on top of an OHLC bar
        or on a Line on Cloe bar, difficult the recognition of the plot.

      Note: False (modern) plots signals outside the price bars for clarity.
      True (old) plots signals at execution price, overlapping with bars.

    - ``oldtrades`` (default: ``False``)

      If ``stdstats`` is ``True`` and observers are getting automatically
      added, this switch controls the main behavior of the ``Trades``
      observer

      - ``False``: use the modern behavior in which trades for all datas are
        plotted with different markers

      - ``True``: use the old Trades observer which plots the trades with the
        same markers, differentiating only if they are positive or negative

      Note: False uses different markers for different trades.
      True uses same markers, only distinguishing positive/negative.


    - ``exactbars`` (default: ``False``)

      With the default value, each and every value stored in a line is kept in
      memory

      Possible values:
        - ``True`` or ``1``: all "lines" objects reduce memory usage to the
          automatically calculated minimum period.

          If a Simple Moving Average has a period of 30, the underlying data
          will have always a running buffer of 30 bars to allow the
          calculation of the Simple Moving Average

          - This setting will deactivate ``preload`` and ``runonce``
          - Using this setting also deactivates **plotting**

        - ``-1``: datafeeds and indicators/operations at strategy level will
          keep all data in memory.

          For example: a ``RSI`` internally uses the indicator ``UpDay`` to
          make calculations. This subindicator will not keep all data in
          memory

          - This allows keeping ``plotting`` and ``preloading`` active.

          - ``runonce`` will be deactivated

        - ``-2``: data feeds and indicators kept as attributes of the
          strategy will keep all points in memory.

          For example: a ``RSI`` internally uses the indicator ``UpDay`` to
          make calculations. This subindicator will not keep all data in
          memory

          If in the ``__init__`` something like
          ``a = self.data.close - self.data.high`` is defined, then ``a``
          will not keep all data in memory

          - This allows keeping ``plotting`` and ``preloading`` active.

          - ``runonce`` will be deactivated

      Note on exactbars values:
        - True/1: Minimum memory, disables preload/runonce/plotting
        - -1: Keeps data/indicators but not sub-indicator internals, disables runonce
        - -2: Keeps strategy-level data/indicators, sub-indicators not using self are discarded

    - ``objcache`` (default: ``False``)

      Experimental option to implement a cache of lines objects and reduce
      the amount of them. Example from UltimateOscillator:

        bp = self.data.close - TrueLow(self.data)
        tr = TrueRange(self.data) # -> creates another TrueLow(self.data)

      If this is `True`, the second ``TrueLow(self.data)`` inside ``TrueRange``
      matches the signature of the one in the ``bp`` calculation. It will be
      reused.

      Corner cases may happen in which this drives a line object off its
      minimum period and breaks things, and it is therefore disabled.

      Note: When True, identical indicator calculations are cached and reused
      to reduce computation. Disabled by default due to edge cases.

    - ``writer`` (default: ``False``)

      If set to ``True`` a default WriterFile will be created which will
      print to stdout. It will be added to the strategy (in addition to any
      other writers added by the user code)

      Note: Outputs trading information to stdout. Custom logging in strategy
      is usually preferred for more control.

    - ``tradehistory`` (default: ``False``)

      If set to ``True``, it will activate update event logging in each trade
      for all strategies. This can also be achieved on a per-strategy
      basis with the strategy method ``set_tradehistory``

      Note: Enables trade update logging for all strategies. Can also be
      enabled per-strategy using set_tradehistory method.

    - ``optdatas`` (default: ``True``)

      If ``True`` and optimizing (and the system can ``preload`` and use
      ``runonce``, data preloading will be done only once in the main process
      to save time and resources.

      The tests show an approximate ``20%`` speed-up moving from a sample
      execution in ``83`` seconds to ``66``

      Note: When True with preload/runonce, data is preloaded once in the
      main process and shared across optimization workers (~20% speedup).


    - ``optreturn`` (default: ``True``)

      If `True`, the optimization results will not be full ``Strategy``
      objects (and all *datas*, *indicators*, *observers* ...) but object
      with the following attributes (same as in ``Strategy``):

        - ``params`` (or ``p``) the strategy had for the execution
        - ``analyzers`` the strategy has executed

      On most occasions, only the *analyzers* and with which *params* are
      the things needed to evaluate the performance of a strategy. If
      detailed analysis of the generated values for (for example)
      *indicators* is needed, turn this off

      The tests show a 13% - 15% improvement in execution time. Combined
      with `optdatas` the total gain increases to a total speed-up of
      `32%` in an optimization run.

      Note: Returns only params and analyzers during optimization, discarding
      data/indicators/observers for ~15% speedup (32% combined with optdatas).

    - ``oldsync`` (default: ``False``)

      Starting with release 1.9.0.99, the synchronization of multiple datas
      (same or different timeframes) has been changed to allow datas of
      different lengths.

      If the old behavior with data0 as the master of the system is wished,
      set this parameter to true

      Note: False allows data feeds of different lengths.
      True uses data0 as master (legacy behavior).

    - ``tz`` (default: ``None``)

      Adds a global timezone for strategies. The argument ``tz`` can be

        - ``None``: in this case the datetime displayed by strategies will be
          in UTC, which has always been the standard behavior

        - ``pytz`` instance. It will be used as such to convert UTC times to
          the chosen timezone

        - ``string``. Instantiating a ``pytz`` instance will be attempted.

        - ``integer``. Use, for the strategy, the same timezone as the
          corresponding ``data`` in the ``self.datas`` iterable (``0`` would
          use the timezone from ``data0``)

      Note: None=UTC, pytz instance converts from UTC, string creates pytz,
      integer uses timezone from corresponding data feed index.

    - ``cheat_on_open`` (default: ``False``)

      The ``next_open`` method of strategies will be called. This happens
      before ``next`` and before the broker has had a chance to evaluate
      orders. The indicators have not yet been recalculated. This allows
      issuing an order which takes into account the indicators of the previous
      day but uses the ``open`` price for stake calculations

      For cheat_on_open order execution, it is also necessary to make the
      call ``cerebro.broker.set_coo(True)`` or instantiate a broker with
      ``BackBroker(coo=True)`` (where *coo* stands for cheat-on-open) or set
      the ``broker_coo`` parameter to ``True``. Cerebro will do it
      automatically unless disabled below.

      Note: Enables using next bar's open price for position sizing.
      Useful for precise capital allocation. Requires broker_coo=True.

    - ``broker_coo`` (default: ``True``)

      This will automatically invoke the ``set_coo`` method of the broker
      with ``True`` to activate ``cheat_on_open`` execution. Will only do it
      if ``cheat_on_open`` is also ``True``

      Note: Works together with cheat_on_open parameter.

    - ``quicknotify`` (default: ``False``)

      Broker notifications are delivered right before the delivery of the
      *next* prices. For backtesting, this has no implications, but with live
       brokers, a notification can take place long before the bar is
      delivered. When set to ``True`` notifications will be delivered as soon
      as possible (see ``qcheck`` in live feeds)

      Set to ``False`` for compatibility. May be changed to ``True``

      Note: False delays notifications until next bar. True sends immediately.
      Mainly relevant for live trading.

    """

    # Parameter descriptors using new system
    preload = ParameterDescriptor(
        default=True, type_=bool, doc="Whether to preload the different data feeds"
    )
    runonce = ParameterDescriptor(default=True, type_=bool, doc="Run Indicators in vectorized mode")
    maxcpus = ParameterDescriptor(default=None, doc="How many cores to use for optimization")
    stdstats = ParameterDescriptor(default=True, type_=bool, doc="Add default Observers")
    oldbuysell = ParameterDescriptor(
        default=False, type_=bool, doc="Use old BuySell observer behavior"
    )
    oldtrades = ParameterDescriptor(
        default=False, type_=bool, doc="Use old Trades observer behavior"
    )
    lookahead = ParameterDescriptor(default=0, type_=int, doc="Lookahead parameter")
    exactbars = ParameterDescriptor(default=False, doc="Memory usage control for lines objects")
    optdatas = ParameterDescriptor(
        default=True, type_=bool, doc="Optimize data preloading during optimization"
    )
    optreturn = ParameterDescriptor(
        default=True, type_=bool, doc="Return simplified objects during optimization"
    )
    objcache = ParameterDescriptor(
        default=False, type_=bool, doc="Cache lines objects to reduce memory"
    )
    live = ParameterDescriptor(default=False, type_=bool, doc="Run in live mode")
    writer = ParameterDescriptor(default=False, type_=bool, doc="Add a default WriterFile")
    tradehistory = ParameterDescriptor(
        default=False, type_=bool, doc="Activate trade history logging"
    )
    oldsync = ParameterDescriptor(default=False, type_=bool, doc="Use old synchronization behavior")
    tz = ParameterDescriptor(default=None, doc="Global timezone for strategies")
    cheat_on_open = ParameterDescriptor(
        default=False, type_=bool, doc="Enable cheat-on-open execution"
    )
    broker_coo = ParameterDescriptor(
        default=True, type_=bool, doc="Auto-activate broker cheat-on-open"
    )
    quicknotify = ParameterDescriptor(
        default=False, type_=bool, doc="Deliver broker notifications quickly"
    )

    def __init__(self, **kwargs):
        """Initialize Cerebro with optional parameter overrides.

        Args:
            **kwargs: Parameter overrides (preload, runonce, maxcpus, etc.)
        """
        super().__init__(**kwargs)

        # Internal state flags
        self._timerscheat = None
        self._timers = None
        self.runningstrats = None
        self.runstrats = None
        self.writers_csv = None
        self.runwriters = None
        self._dopreload = None
        self._dorunonce = None
        self._exactbars = None
        self._event_stop = None
        self._dolive = False  # Live trading mode flag
        self._doreplay = False  # Data replay mode flag
        self._dooptimize = False  # Optimization mode flag

        # Component containers
        self.stores = list()  # Data stores
        self.feeds = list()  # Data feeds
        self.datas = list()  # Data objects
        self.datasbyname = collections.OrderedDict()  # Data lookup by name
        self.strats = list()  # Strategy classes/instances
        self.optcbs = list()  # Optimization callbacks
        self.observers = list()  # Observer classes
        self.analyzers = list()  # Analyzer classes
        self.indicators = list()  # Indicator classes
        self.sizers = dict()  # Position sizers
        self.writers = list()  # Output writers
        self.storecbs = list()  # Store callbacks
        self.datacbs = list()  # Data callbacks
        self.signals = list()  # Signal definitions

        # Signal strategy configuration
        self._signal_strat = (None, None, None)
        self._signal_concurrent = False  # Allow concurrent signals
        self._signal_accumulate = False  # Allow accumulating positions

        # Internal counters and references
        self._dataid = itertools.count(1)  # Data ID counter
        self._broker = BackBroker()  # Default broker
        self._broker.cerebro = self  # Back-reference to cerebro
        self._tradingcal = None  # Trading calendar
        self._pretimers = list()  # Pre-run timers
        self._ohistory = list()  # Order history
        self._fhistory = None  # Fund history

        # Override parameters from kwargs
        pkeys = self.params._getkeys()
        for key, val in kwargs.items():
            if key in pkeys:
                setattr(self.params, key, val)

    @staticmethod
    def iterize(iterable):
        """Convert each element in iterable to be iterable itself.

        Args:
            iterable: Input iterable whose elements may not be iterable.

        Returns:
            list: New list where each element is guaranteed to be iterable.
        """
        niterable = list()
        for elem in iterable:
            if isinstance(elem, string_types):
                elem = (elem,)
            # elif not isinstance(elem, collections.Iterable):
            elif not isinstance(
                elem, collectionsAbc.Iterable
            ):  # Different functions will be called for different Python versions
                elem = (elem,)

            niterable.append(elem)

        return niterable

    def set_fund_history(self, fund):
        """
        Add a history of orders to be directly executed in the broker for
        performance evaluation

          - ``fund``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also iterable (with length) with
            the following sub-elements (two formats are possible)

            ``[datetime, share_value, net asset value]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``share_value`` is a float/integer
              - ``net_asset_value`` is a float/integer
        """
        self._fhistory = fund

    def add_order_history(self, orders, notify=True):
        """
        Add a history of orders to be directly executed in the broker for
        performance evaluation

          - ``orders``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also iterable (with length) with
            the following sub-elements (two formats are possible)

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

            If ``True``, the first strategy inserted in the system will be
            notified of the artificial orders created following the information
            from each order in ``orders``

        **Note**: Implicit in the description is the need to add a data feed
          which is the target of the orders.This is, for example, needed by
          analyzers which track, for example, the returns
        """
        self._ohistory.append((orders, notify))

    def notify_timer(self, timer, when, *args, **kwargs):
        """Receives a timer notification where ``timer`` is the timer that was
        returned by ``add_timer``, and ``when`` is the calling time. ``args``
        and ``kwargs`` are any additional arguments passed to ``add_timer``

        The actual `when` time can be later, but the system may have not been
        able to call the timer before. This value is the timer value and no the
        system time.
        """
        pass

    def _add_timer(
        self,
        owner,
        when,
        offset=datetime.timedelta(),
        repeat=datetime.timedelta(),
        weekdays=[],
        weekcarry=False,
        monthdays=[],
        monthcarry=True,
        allow=None,
        tzdata=None,
        strats=False,
        cheat=False,
        *args,
        **kwargs,
    ):
        """Internal method to really create the timer (not started yet) which
        can be called by cerebro instances or other objects which can access
        cerebro"""

        timer = Timer(
            tid=len(self._pretimers),
            owner=owner,
            strats=strats,
            when=when,
            offset=offset,
            repeat=repeat,
            weekdays=weekdays,
            weekcarry=weekcarry,
            monthdays=monthdays,
            monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata,
            cheat=cheat,
            *args,
            **kwargs,
        )

        self._pretimers.append(timer)
        return timer

    def add_timer(
        self,
        when,
        offset=datetime.timedelta(),
        repeat=datetime.timedelta(),
        weekdays=[],
        weekcarry=False,
        monthdays=[],
        monthcarry=True,
        allow=None,
        tzdata=None,
        strats=False,
        cheat=False,
        *args,
        **kwargs,
    ):
        """
        Schedules a timer to invoke ``notify_timer``

        Arguments:

          - ``when``: can be

            - ``datetime.time`` instance (see below ``tzdata``)
            - ``bt.timer.SESSION_START`` to reference a session start
            - ``bt.timer.SESSION_END`` to reference a session end

         - ``offset`` which must be a ``datetime.timedelta`` instance

           Used to offset the value ``when``. It has a meaningful use in
           combination with ``SESSION_START`` and ``SESSION_END``, to indicate
           things like a timer being called ``15 minutes`` after the session
            starts.

          - ``repeat`` which must be a ``datetime.timedelta`` instance

            Indicates if after a first call, further calls will be scheduled
            within the same session at the scheduled `repeat` delta

            Once the timer goes over the end of the session, it is reset to the
            original value for ``when``

          - ``weekdays``: a **sorted** iterable with integers indicating on
            which days (iso codes, Monday is 1, Sunday is 7) the timers can
            be actually invoked

            If not specified, the timer will be active on all days

          - ``weekcarry`` (default: ``False``). If ``True`` and the weekday was
            not seen (ex: trading holiday), the timer will be executed on the
            next day (even if in a new week)

          - ``monthdays``: a **sorted** iterable with integers indicating on
            which days of the month a timer has to be executed. For example,
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
            to handling it as if it is UTC even if it's not)

            ``pytz`` instance: ``when`` will be interpreted as being specified
            in the local time specified by the timezone instance.

            ``data feed`` instance: ``when`` will be interpreted as being
            specified in the local time specified by the ``tz`` parameter of
            the data feed instance.

            **Note**: If ``when`` is either ``SESSION_START`` or
              ``SESSION_END`` and ``tzdata`` is ``None``, the first *data feed*
              in the system (aka ``self.data0``) will be used as the reference
              to find out the session times.

          - ``strats`` (default: ``False``) call also the ``notify_timer`` of strategies

          - ``cheat`` (default ``False``) if ``True`` the timer will be called
            before the broker has a chance to evaluate the orders. This opens
            the chance to issue orders based on opening price, for example, right
            before the session starts
          - ``*args``: any extra args will be passed to ``notify_timer``

          - ``**kwargs``: any extra kwargs will be passed to ``notify_timer``

        Return Value:

          - The created timer

        """
        return self._add_timer(
            owner=self,
            when=when,
            offset=offset,
            repeat=repeat,
            weekdays=weekdays,
            weekcarry=weekcarry,
            monthdays=monthdays,
            monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata,
            strats=strats,
            cheat=cheat,
            *args,
            **kwargs,
        )

    def addtz(self, tz):
        """This can also be done with the parameter ``tz``

        Adds a global timezone for strategies. The argument ``tz`` can be

          - ``None``: in this case the datetime displayed by strategies will be
            in UTC, which has always been the standard behavior

          - ``pytz`` instance. It will be used as such to convert UTC times to
            the chosen timezone

          - ``string``. Instantiating a ``pytz`` instance will be attempted.

          - ``integer``. Use, for the strategy, the same timezone as the
            corresponding ``data`` in the ``self.datas`` iterable (``0`` would
            use the timezone from ``data0``)

        """
        self.p.tz = tz

    def addcalendar(self, cal):
        """Adds a global trading calendar to the system. Individual data feeds
        may have separate calendars which override the global one

        ``cal`` can be an instance of ``TradingCalendar`` a string or an
        instance of ``pandas_market_calendars``. A string will be
        instantiated as a ``PandasMarketCalendar`` (which needs the module
        ``pandas_market_calendar`` installed in the system).

        If a subclass of `TradingCalendarBase` is passed (not an instance), it
        will be instantiated
        """
        # Handle string or pandas calendar with valid_days attribute
        if isinstance(cal, string_types):
            cal = PandasMarketCalendar(calendar=cal)
        elif hasattr(cal, "valid_days"):
            cal = PandasMarketCalendar(calendar=cal)
        # Handle TradingCalendarBase subclass or instance
        else:
            try:
                if issubclass(cal, TradingCalendarBase):
                    cal = cal()
            except TypeError:  # already an instance
                pass
        self._tradingcal = cal

    def add_signal(self, sigtype, sigcls, *sigargs, **sigkwargs):
        """Add a signal to be used with SignalStrategy."""
        self.signals.append((sigtype, sigcls, sigargs, sigkwargs))

    def signal_strategy(self, stratcls, *args, **kwargs):
        """Set a SignalStrategy subclass to receive signals."""
        self._signal_strat = (stratcls, args, kwargs)

    def signal_concurrent(self, onoff):
        """Allow concurrent orders when signals are pending."""
        self._signal_concurrent = onoff

    def signal_accumulate(self, onoff):
        """If signals are added to the system and the `accumulate` value is
        set to True, entering the market when already in the market, will be
        allowed to increase a position"""
        self._signal_accumulate = onoff

    def addstore(self, store):
        """Add a Store instance to the system."""
        if store not in self.stores:
            self.stores.append(store)

    def addwriter(self, wrtcls, *args, **kwargs):
        """Adds an ``Writer`` class to the mix. Instantiation will be done at
        ``run`` time in cerebro"""
        self.writers.append((wrtcls, args, kwargs))

    def addsizer(self, sizercls, *args, **kwargs):
        """Adds a ``Sizer`` class (and args) which is the default sizer for any
        strategy added to cerebro
        """
        self.sizers[None] = (sizercls, args, kwargs)

    def addsizer_byidx(self, idx, sizercls, *args, **kwargs):
        """Adds a ``Sizer`` class by idx. This idx is a reference compatible to
        the one returned by ``addstrategy``. Only the strategy referenced by
        ``idx`` will receive this size
        """
        self.sizers[idx] = (sizercls, args, kwargs)

    def addindicator(self, indcls, *args, **kwargs):
        """Add an Indicator class to be instantiated at run time."""
        self.indicators.append((indcls, args, kwargs))

    def addanalyzer(self, ancls, *args, **kwargs):
        """Add an Analyzer class to be instantiated at run time."""
        self.analyzers.append((ancls, args, kwargs))

    def addobserver(self, obscls, *args, **kwargs):
        """
        Adds an ``Observer`` class to the mix. Instantiation will be done at
        ``run`` time
        """
        self.observers.append((False, obscls, args, kwargs))

    def addobservermulti(self, obscls, *args, **kwargs):
        """

        It will be added once per "data" in the system. A use case is a
        buy/sell observer that observes individual data.

        A counter-example is the CashValue, which observes system-wide values
        """
        self.observers.append((True, obscls, args, kwargs))

    def addstorecb(self, callback):
        """Adds a callback to get messages which would be handled by the
        notify_store method

        The signature of the callback must support the following:

          - callback(msg, *args, *kwargs)

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        """
        self.storecbs.append(callback)

    def _notify_store(self, msg, *args, **kwargs):
        """Internal method to dispatch store notifications."""
        for callback in self.storecbs:
            callback(msg, *args, **kwargs)

        self.notify_store(msg, *args, **kwargs)

    def notify_store(self, msg, *args, **kwargs):
        """Receive store notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        """
        pass

    def _storenotify(self):
        """Process and dispatch store notifications to strategies."""
        for store in self.stores:
            for notif in store.get_notifications():
                msg, args, kwargs = notif

                self._notify_store(msg, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.notify_store(msg, *args, **kwargs)

    def adddatacb(self, callback):
        """Adds a callback to get messages which would be handled by the
        notify_data method

        The signature of the callback must support the following:

          - callback(data, status, *args, *kwargs)

        The actual ``*args`` and ``**kwargs`` received are implementation
        defined (depend entirely on the *data/broker/store*), but in general one
        should expect them to be *printable* to allow for reception and
        experimentation.
        """
        self.datacbs.append(callback)

    def _datanotify(self):
        """Process and dispatch data notifications to strategies."""
        for data in self.datas:
            for notif in data.get_notifications():
                status, args, kwargs = notif
                self._notify_data(data, status, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.notify_data(data, status, *args, **kwargs)

    def _notify_data(self, data, status, *args, **kwargs):
        """Internal method to dispatch data notifications."""
        for callback in self.datacbs:
            callback(data, status, *args, **kwargs)

        self.notify_data(data, status, *args, **kwargs)

    def notify_data(self, data, status, *args, **kwargs):
        """Receive data notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*), but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        """
        pass

    def adddata(self, data, name=None):
        """
        Adds a ``Data Feed`` instance to the mix.

        If ``name`` is not None, it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.
        """
        # Set data name if provided
        if name is not None:
            data._name = name
            data.name = name
        # Assign unique ID to each data feed
        data._id = next(self._dataid)
        # Set data's environment to this cerebro
        data.setenvironment(self)
        # Add to data list
        self.datas.append(data)
        # Store in name lookup dictionary
        self.datasbyname[data._name] = data
        # Get feed from data
        feed = data.getfeed()
        # Add feed if not already present
        if feed and feed not in self.feeds:
            self.feeds.append(feed)
        # Set live mode if data is live
        if data.islive():
            self._dolive = True

        return data

    def chaindata(self, *args, **kwargs):
        """
        Chains several data feeds into one

        If ``name`` is passed as named argument and not `None`, it will be put
        into ``data._name`` which is meant for decoration/plotting purposes.

        If `None`, then the name of the first data will be used
        """
        dname = kwargs.pop("name", None)
        if dname is None:
            dname = args[0]._dataname
        d = feeds.Chainer(dataname=dname, *args)
        self.adddata(d, name=dname)

        return d

    def rolloverdata(self, *args, **kwargs):
        """Chains several data feeds into one

        If ``name`` is passed as named argument and is not None, it will be put
        into ``data._name`` which is meant for decoration/plotting purposes.

        If `None`, then the name of the first data will be used

        Any other kwargs will be passed to the RollOver class

        """
        dname = kwargs.pop("name", None)
        if dname is None:
            dname = args[0]._dataname
        d = feeds.RollOver(dataname=dname, *args, **kwargs)
        self.adddata(d, name=dname)

        return d

    def replaydata(self, dataname, name=None, **kwargs):
        """
        Adds a ``Data Feed`` to be replayed by the system

        If ``name`` is not None, it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the replay filter will be passed transparently
        """
        if any(dataname is x for x in self.datas):
            dataname = dataname.clone()

        dataname.replay(**kwargs)
        self.adddata(dataname, name=name)
        self._doreplay = True

        return dataname

    def resampledata(self, dataname, name=None, **kwargs):
        """
        Adds a ``Data Feed`` to be resample by the system

        If ``name`` is not None, it will be put into ``data._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the resample filter will be passed transparently
        """
        if any(dataname is x for x in self.datas):
            dataname = dataname.clone()

        dataname.resample(**kwargs)
        self.adddata(dataname, name=name)
        self._doreplay = True

        return dataname

    def optcallback(self, cb):
        """
        Adds a *callback* to the list of callbacks that will be called with the
        optimizations when each of the strategies has been run

        The signature: cb(strategy)
        """
        self.optcbs.append(cb)

    def optstrategy(self, strategy, *args, **kwargs):
        """
        Adds a ``Strategy`` class to the mix for optimization. Instantiation
        will happen during ``run`` time.

        args and kwargs MUST BE iterables that hold the values to check.

        Example: if a Strategy accepts a parameter `period`, for optimization
        purposes, the call to ``optstrategy`` looks like:

          - cerebro.optstrategy(MyStrategy, period=(15, 25))

        This will execute an optimization for values 15 and 25. Whereas

          - cerebro.optstrategy(MyStrategy, period=range(15, 25))

        will execute MyStrategy with ``period`` values 15 -> 25 (25 not
        included, because ranges are semi-open in Python)

        If a parameter is passed but shall not be optimized, the call looks
        like:

          - cerebro.optstrategy(MyStrategy, period=(15,))

        Notice that `period` is still passed as an iterable ... of just one element

        ``backtrader`` will anyhow try to identify situations like:

          - cerebro.optstrategy(MyStrategy, period=15)

        and will create an internal pseudo-iterable if possible
        """
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

    def addstrategy(self, strategy, *args, **kwargs):
        """
        Adds a ``Strategy`` class to the mix for a single pass run.
        Instantiation will happen during ``run`` time.

        Args and kwargs will be passed to the strategy as they are during
        instantiation.

        Returns the index with which addition of other objects (like sizers)
        can be referenced
        """
        self.strats.append([(strategy, args, kwargs)])
        return len(self.strats) - 1

    def setbroker(self, broker):
        """
        Sets a specific ``broker`` instance for this strategy, replacing the
        one inherited from cerebro.
        """
        self._broker = broker
        broker.cerebro = self
        return broker

    def getbroker(self):
        """
        Returns the broker instance.

        This is also available as a ``property`` by the name ``broker``
        """
        return self._broker

    broker = property(getbroker, setbroker)

    def plot(
        self,
        plotter=None,
        numfigs=1,
        iplot=True,
        start=None,
        end=None,
        width=16,
        height=9,
        dpi=300,
        tight=True,
        use=None,
        backend="matplotlib",
        **kwargs,
    ):
        """
        Plots the strategies inside cerebro

        If ``plotter`` is None, a default ``Plot`` instance is created and
        ``kwargs`` are passed to it during instantiation.

        ``numfigs`` split the plot in the indicated number of charts reducing
        chart density if wished

        ``iplot``: if ``True`` and running in a ``notebook`` the charts will be
        displayed inline

        ``use``: set it to the name of the desired matplotlib backend. It will
        take precedence over ``iplot``

        ``backend``: plotting backend to use. Options:
            - 'matplotlib': traditional matplotlib plotting (default)
            - 'plotly': interactive Plotly charts (better for large data)

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
        """
        if self._exactbars > 0:
            return

        # For plotly backend, ensure Transactions analyzer exists for buy/sell signals
        if backend == "plotly":
            for stratlist in self.runstrats:
                for strat in stratlist:
                    # Check if Transactions analyzer already exists
                    has_txn = any(
                        a.__class__.__name__ == "Transactions" 
                        for a in strat.analyzers
                    )
                    if not has_txn:
                        # Add Transactions analyzer retroactively is not possible
                        # So we'll rely on broker.orders instead
                        pass

        if not plotter:
            from . import plot

            if backend == "plotly":
                plotter = plot.PlotlyPlot(**kwargs)
            elif self.p.oldsync:
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
                rfig = plotter.plot(
                    strat,
                    figid=si * 100,
                    numfigs=numfigs,
                    iplot=iplot,
                    start=start,
                    end=end,
                    use=use,
                )
                # pfillers=pfillers2)

                figs.append(rfig)

            plotter.show()

        return figs

    # Module passed to cerebro for multiprocessing during optimization
    def __call__(self, iterstrat):
        """
        Used during optimization to pass the cerebro over the multiprocessing
        module without complaints
        """

        predata = self.p.optdatas and self._dopreload and self._dorunonce
        return self.runstrategies(iterstrat, predata=predata)

    # Delete runstrats when pickling
    def __getstate__(self):
        """
        Used during optimization to prevent optimization result `runstrats`
        from being pickled to subprocesses
        """

        rv = vars(self).copy()
        if "runstrats" in rv:
            del rv["runstrats"]
        return rv

    # When called from within a strategy or elsewhere, stops execution quickly
    def runstop(self):
        """If invoked from inside a strategy or anywhere else, including other
        threads, the execution will stop as soon as possible."""
        self._event_stop = True  # signal a stop has been requested

    # Core method for backtesting. Any passed kwargs affect cerebro standard parameters.
    # If no data added, will stop immediately. Return value differs based on optimization.
    def run(self, **kwargs):
        """The core method to perform backtesting. Any ``kwargs`` passed to it
        will affect the value of the standard parameters ``Cerebro`` was
        instantiated with.

        If `cerebro` has no data, the method will immediately bail out.

        It has different return values:

          - For No Optimization: a list contanining instances of the Strategy
            classes added with ``addstrategy``

          - For Optimization: a list of lists which contain instances of the
            Strategy classes added with ``addstrategy``
        """
        self._event_stop = False  # Stop is requested
        # If no data, return empty list immediately
        if not self.datas:
            return []  # nothing can be run
        # Override standard parameters with passed kwargs
        pkeys = self.params._getkeys()
        for key, val in kwargs.items():
            if key in pkeys:
                setattr(self.params, key, val)

        # Manage activate/deactivate object cache
        # Manage object cache
        linebuffer.LineActions.cleancache()  # clean cache
        indicator.Indicator.cleancache()  # clean cache

        linebuffer.LineActions.usecache(self.p.objcache)
        indicator.Indicator.usecache(self.p.objcache)

        # Check if _dorunonce, _dopreload, _exactbars
        self._dorunonce = self.p.runonce
        self._dopreload = self.p.preload
        self._exactbars = int(self.p.exactbars)
        # If _exactbars is not 0, _dorunonce must be False; if _dopreload is True and _exactbars < 1, set _dopreload to True
        if self._exactbars:
            self._dorunonce = False  # something is saving memory, no runonce
            self._dopreload = self._dopreload and self._exactbars < 1
        # If _doreplay is True or any data has replaying attribute True, set _doreplay to True
        self._doreplay = self._doreplay or any(x.replaying for x in self.datas)
        # If _doreplay, need to set _dopreload to False
        if self._doreplay:
            # preloading is not supported with replay. full timeframe bars
            # are constructed in realtime
            self._dopreload = False
        # If _dolive or live, need to set _dorunonce and _dopreload to False
        if self._dolive or self.p.live:
            # in this case, both preload and runonce must be off
            self._dorunonce = False
            self._dopreload = False

        # Writer list
        self.runwriters = list()

        # Add the system default writer if requested
        # If writer parameter is True, add default writer
        if self.p.writer is True:
            wr = WriterFile()
            self.runwriters.append(wr)

        # Instantiate any other writers
        # If there are other writers, instantiate and add to runwriters
        for wrcls, wrargs, wrkwargs in self.writers:
            wr = wrcls(*wrargs, **wrkwargs)
            self.runwriters.append(wr)

        # Write down if any writer wants the full csv output
        # If that writer needs full csv output, save results to file
        self.writers_csv = any(map(lambda x: x.p.csv, self.runwriters))

        # Running strategy list
        self.runstrats = list()
        # If signals is not None, handle signalstrategy related issues
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
                        signalst = None  # flag as not present

            if signalst is None:  # recheck
                # Still None, create a default one
                signalst, sargs, skwargs = SignalStrategy, tuple(), dict()

            # Add the signal strategy
            self.addstrategy(
                signalst,
                _accumulate=self._signal_accumulate,
                _concurrent=self._signal_concurrent,
                signals=self.signals,
                *sargs,
                **skwargs,
            )
        # If strategy list is empty, add strategy
        if not self.strats:  # Datas are present, add a strategy
            self.addstrategy(Strategy)
        # Iterate strategies
        iterstrats = itertools.product(*self.strats)
        # If not optimization parameters, or using 1 cpu core
        if not self._dooptimize or self.p.maxcpus == 1:
            # If no optimmization is wished ... or 1 core is to be used
            # let's skip process "spawning"
            # Iterate through strategies
            for iterstrat in iterstrats:
                # Run strategy
                runstrat = self.runstrategies(iterstrat)
                # Add running strategy to running strategy list
                self.runstrats.append(runstrat)
                # If optimization parameters
                if self._dooptimize:
                    # Iterate all optcbs to return stopped strategy results
                    for cb in self.optcbs:
                        cb(runstrat)  # callback receives finished strategy
        # If optimization parameters
        else:
            # If optdatas is True, and _dopreload, and _dorunonce
            if self.p.optdatas and self._dopreload and self._dorunonce:
                # Iterate each data, reset, if _exactbars < 1, extend data
                # Start data
                # If data _dopreload, call preload on data
                for data in self.datas:
                    data.reset()
                    if self._exactbars < 1:  # datas can be a full length
                        data.extend(size=self.params.lookahead)
                    data._start()
                    # TODO: Re-checking self._dopreload here seems unnecessary since we already guaranteed it's True
                    # if self._dopreload:
                    #     data.preload()
                    data.preload()
            # Start process pool
            pool = multiprocessing.Pool(self.p.maxcpus or None)
            for r in pool.imap(self, iterstrats):
                self.runstrats.append(r)
                for cb in self.optcbs:
                    cb(r)  # callback receives finished strategy
            # Close process pool
            pool.close()
            # If optdatas is True, and _dopreload, and _dorunonce, iterate data and stop data
            if self.p.optdatas and self._dopreload and self._dorunonce:
                for data in self.datas:
                    data.stop()
        # If not optimization parameters
        if not self._dooptimize:
            # avoid a list of list for regular cases
            return self.runstrats[0]

        return self.runstrats

    # Initialize count
    def _init_stcount(self):
        self.stcount = itertools.count(0)

    # Call next count
    def _next_stid(self):
        return next(self.stcount)

    # Run strategy
    def runstrategies(self, iterstrat, predata=False):
        """
        Internal method invoked by ``run``` to run a set of strategies
        """
        # Initialize count
        self._init_stcount()
        # Initialize running strategy as empty list
        self.runningstrats = runstrats = list()
        # Iterate stores and start
        for store in self.stores:
            store.start()
        # If cheat_on_open and broker_coo, set broker accordingly
        if self.p.cheat_on_open and self.p.broker_coo:
            # try to activate in broker
            if hasattr(self._broker, "set_coo"):
                self._broker.set_coo(True)
        # If fund history is not None, need to set fund history
        if self._fhistory is not None:
            self._broker.set_fund_history(self._fhistory)
        # Iterate order history
        for orders, onotify in self._ohistory:
            self._broker.add_order_history(orders, onotify)
        # Broker start
        self._broker.start()
        # Feed start
        for feed in self.feeds:
            feed.start()
        # If need to save writer data
        if self.writers_csv:
            # headers
            wheaders = list()
            # Iterate data, if data csv attribute is True, get headers that need saving
            for data in self.datas:
                if data.csv:
                    wheaders.extend(data.getwriterheaders())
            # Save writer headers
            for writer in self.runwriters:
                if writer.p.csv:
                    writer.addheaders(wheaders)

        # self._plotfillers = [list() for d in self.datas]
        # self._plotfillers2 = [list() for d in self.datas]
        # If no predata, need to pre-process data, similar to run method preprocessing
        if not predata:
            for data in self.datas:
                data.reset()
                if self._exactbars < 1:  # datas can be a full length
                    data.extend(size=self.params.lookahead)
                data._start()
                if self._dopreload:
                    data.preload()
        # Loop through strategies
        for stratcls, sargs, skwargs in iterstrat:
            # Add data to strategy parameters
            sargs = self.datas + list(sargs)
            # Instantiate strategy with OwnerContext so findowner() can find Cerebro
            try:
                # Use OwnerContext so Strategy.__new__ can find Cerebro via findowner()
                with OwnerContext.set_owner(self):
                    # Use safe strategy creation to handle parameter filtering
                    if hasattr(stratcls, "_create_strategy_safely"):
                        strat = stratcls._create_strategy_safely(*sargs, **skwargs)
                    else:
                        # Fallback to direct instantiation
                        strat = stratcls(*sargs, **skwargs)
            except errors.StrategySkipError:
                continue  # do not add strategy to the mix
            # Old data synchronization method
            if self.p.oldsync:
                strat._oldsync = True  # tell strategy to use old clock update
            # Whether to save trade history data
            if self.p.tradehistory:
                strat.set_tradehistory()
            # Add strategy
            runstrats.append(strat)
        # Get timezone info, if tz is integer, get tz at that index; otherwise use tzparse
        tz = self.p.tz
        if isinstance(tz, integer_types):
            tz = self.datas[tz]._tz
        else:
            tz = tzparse(tz)
        # If runstrats is not empty list
        if runstrats:
            # loop separated for clarity
            # Get default sizer
            defaultsizer = self.sizers.get(None, (None, None, None))
            # For each strategy
            for idx, strat in enumerate(runstrats):
                # If stdstats is True, add several observers
                if self.p.stdstats:
                    # Add observer broker
                    strat._addobserver(False, observers.Broker)
                    # Add observers.BuySell
                    if self.p.oldbuysell:
                        strat._addobserver(True, observers.BuySell)
                    else:
                        strat._addobserver(True, observers.BuySell, barplot=True)
                    # Add observer trade
                    if self.p.oldtrades or len(self.datas) == 1:
                        strat._addobserver(False, observers.Trades)
                    else:
                        strat._addobserver(False, observers.DataTrades)
                # Add observers and their parameters to strategy
                for multi, obscls, obsargs, obskwargs in self.observers:
                    strat._addobserver(multi, obscls, *obsargs, **obskwargs)
                # Add indicators to strategy
                for indcls, indargs, indkwargs in self.indicators:
                    strat._addindicator(indcls, *indargs, **indkwargs)
                # Add analyzers to strategy
                for ancls, anargs, ankwargs in self.analyzers:
                    strat._addanalyzer(ancls, *anargs, **ankwargs)
                # Get specific sizer, if sizer is not None, add to strategy
                sizer, sargs, skwargs = self.sizers.get(idx, defaultsizer)
                if sizer is not None:
                    strat._addsizer(sizer, *sargs, **skwargs)
                # Set timezone
                strat._settz(tz)
                # Strategy start
                strat._start()
                # For running writers, if csv parameter is True, save strategy data to writer
                for writer in self.runwriters:
                    if writer.p.csv:
                        writer.addheaders(strat.getwriterheaders())
            # If predata is False, data not preloaded
            if not predata:
                # Loop each strategy, call qbuffer to cache data
                for strat in runstrats:
                    strat.qbuffer(self._exactbars, replaying=self._doreplay)
            # Loop each writer, start writer
            for writer in self.runwriters:
                writer.start()

            # Prepare timers
            self._timers = []
            self._timerscheat = []
            # Loop timers
            for timer in self._pretimers:
                # preprocess tzdata if needed
                # Start timer
                timer.start(self.datas[0])
                # If timer parameter cheat is True, add timer to self._timerscheat, otherwise add to self._timers
                if timer.params.cheat:
                    self._timerscheat.append(timer)
                else:
                    self._timers.append(timer)
            # If _dopreload and _dorunonce are True
            if self._dopreload and self._dorunonce:
                # If old data alignment and sync method, use _runonce_old, otherwise use _runonce
                if self.p.oldsync:
                    self._runonce_old(runstrats)
                else:
                    self._runonce(runstrats)
            # If _dopreload and _dorunonce are not both True
            else:
                # If old data alignment and sync method, use _runnext_old, otherwise use _runnext
                if self.p.oldsync:
                    self._runnext_old(runstrats)
                else:
                    self._runnext(runstrats)
            # Iterate strategies and stop running
            for strat in runstrats:
                strat._stop()
        # Stop broker
        self._broker.stop()
        # If predata is False, iterate data and stop each data
        if not predata:
            for data in self.datas:
                data.stop()
        # Iterate each feed and stop feed
        for feed in self.feeds:
            feed.stop()
        # Iterate each store and stop store
        for store in self.stores:
            store.stop()
        # Stop writer
        self.stop_writers(runstrats)
        # If doing parameter optimization and optreturn is True, get strategy results and add to results
        if self._dooptimize and self.p.optreturn:
            # Results can be optimized
            results = list()
            for strat in runstrats:
                for a in strat.analyzers:
                    a.strategy = None
                    a._parent = None
                    # OPTIMIZED: Use __dict__ instead of dir() for better performance
                    for attrname in list(a.__dict__.keys()):
                        if attrname.startswith("data"):
                            setattr(a, attrname, None)

                oreturn = OptReturn(
                    strat.params, analyzers=strat.analyzers, strategycls=type(strat)
                )
                results.append(oreturn)

            return results

        return runstrats

    # Stop writer
    def stop_writers(self, runstrats):
        """Stop all writers and write final information.

        Args:
            runstrats: List of strategy instances that were run.

        Collects information from data feeds and strategies, writes
        the information to all registered writers, and stops them.
        """
        # Cerebro info
        cerebroinfo = OrderedDict()
        # Data info
        datainfos = OrderedDict()
        # Get info for each data, save to datainfos, then save to cerebroinfo
        for i, data in enumerate(self.datas):
            datainfos["Data%d" % i] = data.getwriterinfo()

        cerebroinfo["Datas"] = datainfos
        # Get strategy info and save to stratinfos and cerebroinfo
        stratinfos = dict()
        for strat in runstrats:
            stname = strat.__class__.__name__
            stratinfos[stname] = strat.getwriterinfo()

        cerebroinfo["Strategies"] = stratinfos
        # Write cerebroinfo to file
        for writer in self.runwriters:
            writer.writedict(dict(Cerebro=cerebroinfo))
            writer.stop()

    # Notify broker info
    def _brokernotify(self):
        """
        Internal method which kicks the broker and delivers any broker
        notification to the strategy
        """
        # Call broker's next
        self._broker.next()
        while True:
            # Get order info to notify, if order is None break loop, otherwise get order's owner.
            # If owner is None, default to first strategy
            order = self._broker.get_notification()
            if order is None:
                break

            owner = order.owner
            if owner is None:
                owner = self.runningstrats[0]  # default
            # Notify order info through first strategy
            owner._addnotification(order, quicknotify=self.p.quicknotify)

    # Old runnext method, similar to runnext
    def _runnext_old(self, runstrats):
        """
        Actual implementation of run in full next mode. All objects have its
        `next` method invoked on each data arrival
        """
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

    # Old runonce method, similar to runonce
    def _runonce_old(self, runstrats):
        """
        Actual implementation of run in vector mode.
        Strategies are still invoked on a pseudo-event mode in which `next`
        is called for each data arrival
        """

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

    # Run writer's next
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

    # Disable runonce
    def _disable_runonce(self):
        """API for lineiterators to disable runonce (see HeikinAshi)"""
        self._dorunonce = False

    # runnext method, core of the framework, event-driven core for data execution
    def _runnext(self, runstrats):
        """
        Actual implementation of run in full next mode. All objects have its
         `next` method invoked on each data arrival
        """
        try:
            # Sort data by time period
            datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))
            # Other data
            datas1 = datas[1:]
            # Main data
            data0 = datas[0]
            d0ret = True
            # TODO: rs and rp are not used, commented out
            # resample index
            _rs = [i for i, x in enumerate(datas) if x.resampling]
            # replaying index
            _rp = [i for i, x in enumerate(datas) if x.replaying]
            # index for resample only, not replay
            rsonly = [i for i, x in enumerate(datas) if x.resampling and not x.replaying]
            # Check if only doing resample
            onlyresample = len(datas) == len(rsonly)
            # Check if no data needs resample
            noresample = not rsonly
            # Number of cloned data
            clonecount = sum(d._clone for d in datas)
            # Number of data
            ldatas = len(datas)
            # Number of non-cloned data
            ldatas_noclones = ldatas - clonecount
            # TODO: lastqcheck not used, commented out
            # lastqcheck = False
            # Default dt0 at max time
            dt0 = date2num(datetime.datetime.max) - 2  # default at max
            # while loop
            my_num = 0
            # TODO: Modify while loop condition to avoid premature exit
            # while d0ret or d0ret is None:
            while True:
                my_num += 1
                # if any has live data in the buffer, no data will wait anything
                # If any live data exists, newqcheck is False
                newqcheck = not any(d.haslivedata() for d in datas)
                # If live data exists
                if not newqcheck:
                    # If no data has reached the live status or all, wait for
                    # the next incoming data
                    # livecount is the number of live data
                    livecount = sum(d._laststatus == d.LIVE for d in datas)
                    # TODO: This check has no meaning
                    newqcheck = not livecount or livecount == ldatas_noclones

                lastret = False
                # Notify anything from the store even before moving datas
                # because datas may not move due to an error reported by the store
                # Notify store related info
                self._storenotify()
                if self._event_stop:  # stop if requested
                    return
                # Notify data related info
                self._datanotify()
                if self._event_stop:  # stop if requested
                    return

                # record starting time and tell feeds to discount the elapsed time
                # from the qcheck value
                # Record start time and notify feed to subtract elapsed time from qcheck
                drets = []
                qstart = datetime.datetime.now(UTC)
                for d in datas:
                    qlapse = datetime.datetime.now(UTC) - qstart
                    d.do_qcheck(newqcheck, qlapse.total_seconds())
                    d_next = d.next(ticks=False)
                    drets.append(d_next)
                    # TODO: Debug code, try printing
                    # if d_next:
                    #     print(drets)
                # Iterate drets, if d0ret is False and any dret is None, d0ret is None
                d0ret = any(dret for dret in drets)
                if not d0ret and any(dret is None for dret in drets):
                    d0ret = None
                # If d0ret is not None
                if d0ret:
                    # Get time
                    dts = []
                    for i, ret in enumerate(drets):
                        dts.append(datas[i].datetime[0] if ret else None)
                    # Get index to minimum datetime
                    # Get minimum time
                    if onlyresample or noresample:
                        dt0 = min(d for d in dts if d is not None)
                    else:
                        dt0 = min(
                            (d for i, d in enumerate(dts) if d is not None and i not in rsonly)
                        )
                    # TODO: dt0 < 1 is wrong, needs modification
                    if dt0 < 1:
                        return
                    # Get master data and time
                    dmaster = datas[dts.index(dt0)]  # and timemaster
                    self._dtmaster = dmaster.num2date(dt0)
                    self._udtmaster = num2date(dt0)

                    # slen = len(runstrats[0])
                    # Try to get something for those that didn't return
                    # Loop through drets
                    for i, ret in enumerate(drets):
                        # If ret is not None, continue to next ret
                        if ret:  # dts already contains a valid datetime for this i
                            continue

                        # try to get data by checking with a master
                        # Get data and try to set time for dts
                        d = datas[i]
                        d._check(forcedata=dmaster)  # check to force output
                        if d.next(datamaster=dmaster, ticks=False):  # retry
                            dts[i] = d.datetime[0]  # good -> store
                            # self._plotfillers2[i].append(slen)  # mark as fill
                        else:
                            # self._plotfillers[i].append(slen)  # mark as empty
                            pass

                    # make sure only those at dmaster level end up delivering
                    # Iterate dts
                    for i, dti in enumerate(dts):
                        # If dti is not None
                        if dti is not None:
                            # Get data
                            di = datas[i]
                            # TODO: Code is redundant, rpi always returns False, can be removed
                            # rpi = False and di.replaying   # to check behavior
                            if dti > dt0:
                                # TODO: rpi is False here, not rpi is True, consider removing and run directly
                                # if not rpi:  # must see all ticks ...
                                di.rewind()  # cannot deliver yet
                                # self._plotfillers[i].append(slen)
                            # If not replay
                            elif not di.replaying:
                                # Replay forces tick fill, else force here
                                di._tick_fill(force=True)

                            # self._plotfillers2[i].append(slen)  # mark as fill
                # If d0ret is None, iterate each data and call _check()
                elif d0ret is None:
                    # meant for things like live feeds which may not produce a bar
                    # at the moment but need the loop to run for notifications and
                    # getting resample and others to produce timely bars
                    for data in datas:
                        data._check()
                # If other case
                else:
                    lastret = data0._last()
                    for data in datas1:
                        lastret += data._last(datamaster=data0)
                    if not lastret:
                        # Only go extra round if something was changed by "lasts"
                        break

                # Datas may have generated a new notification after next
                # Notify data info
                self._datanotify()
                if self._event_stop:  # stop if requested
                    return
                # Check timer and iterate strategies, call _next_open() to run
                if d0ret or lastret:  # if any bar, check timers before broker
                    self._check_timers(runstrats, dt0, cheat=True)
                    if self.p.cheat_on_open:
                        for strat in runstrats:
                            strat._next_open()
                            if self._event_stop:  # stop if requested
                                return
                # Notify broker
                self._brokernotify()
                if self._event_stop:  # stop if requested
                    return

                # Notify timer and iterate strategies to run
                if d0ret or lastret:  # bars produced by data or filters
                    # print("begin go to the strategy next")
                    self._check_timers(runstrats, dt0, cheat=False)
                    for strat in runstrats:
                        strat._next()
                        if self._event_stop:  # stop if requested
                            return

                        self._next_writers(runstrats)
            #     if my_num % 1000000 == 0:
            #         print("end_runnext")
            # print("exit_runnext")
            # Last notification chance before stopping
            # Notify data info
            self._datanotify()
            if self._event_stop:  # stop if requested
                return
            # Notify store info
            self._storenotify()
            if self._event_stop:  # stop if requested
                return
        except Exception as e:
            _error_info = traceback.format_exception(e)
            # print(_error_info)  # Removed for performance - can be re-enabled for debugging

    # runonce
    def _runonce(self, runstrats):
        """
        Actual implementation of run in vector mode.

        Strategies are still invoked on a pseudo-event mode in which `next`
        is called for each data arrival
        """
        # Iterate strategies, call _once and reset
        for strat in runstrats:
            strat._once()
            strat.reset()  # strat called next by next - reset lines

        # The default once for strategies does nothing and therefore
        # has not moved forward all datas/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        # Sort data from small period to large period
        datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))

        while True:
            # Check the next incoming date in the datas
            # For each data call advance_peek(), get minimum time as the first one
            dts = [d.advance_peek() for d in datas]
            dt0 = min(dts)
            if dt0 == float("inf"):
                break  # no data delivers anything

            # Timemaster if needed be
            # dmaster = datas[dts.index(dt0)]  # and timemaster
            # First strategy current length slen
            # TODO: Variable slen not used, commented out
            # slen = len(runstrats[0])
            # For each data time, if time <= minimum time, advance data, otherwise ignore
            for i, dti in enumerate(dts):
                if dti <= dt0:
                    datas[i].advance()
                    # self._plotfillers2[i].append(slen)  # mark as fill
                else:
                    # self._plotfillers[i].append(slen)
                    pass
            # Check timer
            self._check_timers(runstrats, dt0, cheat=True)
            # If cheat_on_open, call _oncepost_open() for each strategy
            if self.p.cheat_on_open:
                for strat in runstrats:
                    strat._oncepost_open()
                    # If stop was called, stop
                    if self._event_stop:  # stop if requested
                        return
            # Call _brokernotify()
            self._brokernotify()
            # If stop was called, stop
            if self._event_stop:  # stop if requested
                return
            # Check timer
            self._check_timers(runstrats, dt0, cheat=False)

            for strat in runstrats:
                strat._oncepost(dt0)
                if self._event_stop:  # stop if requested
                    return
                self._next_writers(runstrats)

        # CRITICAL FIX: Process any pending orders that were submitted in the last iteration
        # In runonce mode, orders submitted in the last _oncepost() call (which calls next())
        # need to be processed before calling stop(), otherwise they won't be executed and trades won't be counted
        # However, we need to ensure data index positions are correct before calling _brokernotify()
        # The issue is that after the loop ends, data may have advanced beyond the last valid point,
        # so we need to ensure data positions are set to the last valid datetime before processing orders
        try:
            # Get the last valid datetime from the strategy
            if runstrats and len(runstrats) > 0:
                strat = runstrats[0]
                if hasattr(strat, "_last_valid_datetime") and strat._last_valid_datetime > 0:
                    last_dt = strat._last_valid_datetime
                    # For each data, find the index where datetime matches last_dt and set _idx accordingly
                    # This ensures broker can access data correctly when executing orders
                    for data in self.datas:
                        try:
                            if hasattr(data, "lines") and hasattr(data.lines, "datetime"):
                                # In runonce mode, data has an array of datetime values
                                # We need to find the index where datetime matches last_dt
                                if hasattr(data.lines.datetime, "array"):
                                    dt_array = data.lines.datetime.array
                                    # Find the last index where datetime <= last_dt
                                    # This ensures we're at or before the last valid datetime
                                    for i in range(len(dt_array) - 1, -1, -1):
                                        if dt_array[i] <= last_dt and dt_array[i] > 0:
                                            # Set _idx to this position so data.datetime[0] returns the correct value
                                            if hasattr(data, "_idx"):
                                                data._idx = i
                                            if hasattr(data.lines.datetime, "_idx"):
                                                data.lines.datetime._idx = i
                                            # Also set _idx for all other lines in the data
                                            if hasattr(data.lines, "lines"):
                                                for line in data.lines.lines:
                                                    if hasattr(line, "_idx") and hasattr(
                                                        line, "array"
                                                    ):
                                                        if i < len(line.array):
                                                            line._idx = i
                                            break
                        except Exception:
                            pass
        except Exception:
            pass

        # Now call _brokernotify() to process pending orders
        # _brokernotify() internally calls broker.next() to process pending orders and then delivers notifications
        # This ensures all orders submitted during the strategy execution are processed
        self._brokernotify()

        # print("end_runonce")  # Removed for performance - called frequently during tests

    # Check timer
    def _check_timers(self, runstrats, dt0, cheat=False):
        # If cheat is False, timers equals self._timers, otherwise equals self._timerscheat
        timers = self._timers if not cheat else self._timerscheat
        # For timer in timers
        for t in timers:
            # Use timer.check(dt0), if returns True, enter below, otherwise check next timer
            if not t.check(dt0):
                continue
            # CRITICAL FIX: Remove 'when' from kwargs to avoid conflict with position argument
            # when is already passed as t.lastwhen (2nd argument)
            timer_kwargs = {k: v for k, v in t.kwargs.items() if k != "when"}
            # Notify timer
            t.params.owner.notify_timer(t, t.lastwhen, *t.args, **timer_kwargs)
            # If strategy needs to use timer (t.params.strats is True), iterate strategies and call notify_timer
            if t.params.strats:
                for strat in runstrats:
                    strat.notify_timer(t, t.lastwhen, *t.args, **timer_kwargs)

    def add_report_analyzers(self, riskfree_rate=0.01):
        """自动添加报告所需的分析器
        
        添加以下分析器：
        - SharpeRatio: 夏普比率
        - DrawDown: 回撤分析
        - TradeAnalyzer: 交易分析
        - SQN: 系统质量数
        - AnnualReturn: 年化收益
        
        Args:
            riskfree_rate: 无风险利率，默认 0.01 (1%)
        """
        from . import analyzers
        
        self.addanalyzer(analyzers.SharpeRatio,
                        _name="sharperatio",
                        riskfreerate=riskfree_rate,
                        timeframe=TimeFrame.Months)
        self.addanalyzer(analyzers.DrawDown,
                        _name="drawdown")
        self.addanalyzer(analyzers.TradeAnalyzer,
                        _name="tradeanalyzer")
        self.addanalyzer(analyzers.SQN,
                        _name="sqn")
        self.addanalyzer(analyzers.AnnualReturn,
                        _name="annualreturn")
        self.addanalyzer(analyzers.TimeReturn,
                        _name="timereturn",
                        timeframe=TimeFrame.Days)
    
    def generate_report(self, output_path, format='html', template='default',
                       user=None, memo=None, **kwargs):
        """生成回测报告
        
        Args:
            output_path: 输出文件路径
            format: 报告格式 ('html', 'pdf', 'json')
            template: 模板名称或路径（仅 HTML/PDF 有效）
            user: 用户名
            memo: 备注
            **kwargs: 额外参数
            
        Returns:
            str: 输出文件路径
            
        Raises:
            RuntimeError: 如果尚未运行策略
            
        使用示例:
            cerebro = bt.Cerebro()
            cerebro.addstrategy(MyStrategy)
            cerebro.adddata(data)
            cerebro.run()
            cerebro.generate_report('report.html')
        """
        if not self.runstrats:
            raise RuntimeError("No strategy has been run. Call cerebro.run() first.")
        
        # 获取第一个策略
        strategy = self.runstrats[0][0]
        
        from .reports import ReportGenerator
        
        report = ReportGenerator(strategy, template=template)
        
        format_lower = format.lower()
        if format_lower == 'html':
            return report.generate_html(output_path, user=user, memo=memo, **kwargs)
        elif format_lower == 'pdf':
            return report.generate_pdf(output_path, user=user, memo=memo, **kwargs)
        elif format_lower == 'json':
            return report.generate_json(output_path, **kwargs)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'html', 'pdf', or 'json'.")
