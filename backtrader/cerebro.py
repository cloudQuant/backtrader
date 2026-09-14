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

# pylint: disable=unused-import
# ruff: noqa: F401
# NOTE (iteration 28): the module-level imports below are intentionally kept
# even where the facade no longer references every name: ``backtrader.cerebro``
# defines no ``__all__`` and ``from backtrader.cerebro import *`` has always
# exported these bindings. Narrowing them would be a breaking change
# (AC28-03 star-export parity).

import collections
import datetime
import functools
import itertools
import multiprocessing
import threading
from datetime import timezone
from typing import Dict

from . import errors, feeds, indicator, linebuffer, observers
from .brokers import BackBroker
from .channel import ChannelDataRef
from .dataseries import TimeFrame
from .feed import AbstractDataBase
from .metabase import OwnerContext
from .parameters import ParameterDescriptor, ParameterizedBase
from .strategy import SignalStrategy, Strategy
from .timer import Timer
from .tradingcal import PandasMarketCalendar, TradingCalendarBase
from .utils import OrderedDict, date2num, tzparse
from .utils.dateintern import _num2date_cached
from .utils.log_message import get_logger
from .utils.py3 import integer_types, map, range, string_types, zip
from .writer import WriterFile

# Iteration 28: implementation mixins (imported under private aliases so the
# star-export namespace of ``backtrader.cerebro`` stays unchanged).
from ._cerebro.channel import ChannelMixin as _ChannelMixin
from ._cerebro.execution import ExecutionMixin as _ExecutionMixin
from ._cerebro.lifecycle import RunLifecycleMixin as _RunLifecycleMixin
from ._cerebro.notifications import NotificationMixin as _NotificationMixin
from ._cerebro.presentation import PresentationMixin as _PresentationMixin
from ._cerebro.registry import RegistryMixin as _RegistryMixin
from ._cerebro.runnext import RunNextMixin as _RunNextMixin
from ._cerebro.runonce import RunOnceMixin as _RunOnceMixin

logger = get_logger(__name__)

# Python 3 always provides collections.abc (the only supported baseline).
collectionsAbc = collections.abc  # collections.Iterable -> collections.abc.Iterable

# Python 3.11+ has datetime.UTC, earlier versions use timezone.utc
UTC = timezone.utc


class _RunStopEvent(threading.Event):
    """A thread-safe stop signal that preserves the legacy bool checks."""

    def __bool__(self):
        return self.is_set()


def _runstop_scoped(run_method):
    """Publish an active run before its body and retire synchronous runs."""

    @functools.wraps(run_method)
    def _wrapped(self, *args, **kwargs):
        token = self._open_run_scope()
        retain_external_channel_scope = False
        try:
            result = run_method(self, *args, **kwargs)
            if kwargs.get("channel") is True:
                self._retain_external_channel_scope(token, result)
                retain_external_channel_scope = True
            return result
        finally:
            if not retain_external_channel_scope:
                self._end_run(token)

    return _wrapped


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


# pylint: disable=too-many-ancestors
# The eight implementation mixins keep the single public Cerebro class under
# the 900-line file budget (iteration 28); see backtrader/_cerebro/.
class Cerebro(
    _RegistryMixin,
    _NotificationMixin,
    _RunLifecycleMixin,
    _ChannelMixin,
    _ExecutionMixin,
    _RunNextMixin,
    _RunOnceMixin,
    _PresentationMixin,
    ParameterizedBase,
):
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
        self.runningstrats: list = []
        self.runstrats = None
        self.writers_csv = None
        self.runwriters = None
        self._dopreload = None
        self._dorunonce = None
        self._exactbars = 0
        # ``runstop`` may be called by a Timer or another thread while the
        # engine is running.  The event publishes that request safely; the
        # lock defines the start/end boundary so stop requests made between
        # runs cannot leak into a later run.
        self._event_stop = _RunStopEvent()
        self._runstop_lock = threading.RLock()
        self._run_active = False
        self._run_scope_token = 0
        self._run_scope_owner = None
        self._external_channel_token = None
        self._external_channel_runstrats = None
        self._external_channel_closing = False
        self._dolive = False  # Live trading mode flag
        self._doreplay = False  # Data replay mode flag
        self._dooptimize = False  # Optimization mode flag

        # Component containers
        self.stores = []  # Data stores
        self.feeds = []  # Data feeds
        self.datas = []  # Data objects
        self.datasbyname = collections.OrderedDict()  # Data lookup by name
        self._channel_data_refs: Dict[str, ChannelDataRef] = {}
        self.strats = []  # Strategy classes/instances
        self.optcbs = []  # Optimization callbacks
        self.observers = []  # Observer classes
        self.analyzers = []  # Analyzer classes
        self.indicators = []  # Indicator classes
        self.sizers = {}  # Position sizers
        self.writers = []  # Output writers
        self.storecbs = []  # Store callbacks
        self.datacbs = []  # Data callbacks
        self.signals = []  # Signal definitions

        # Signal strategy configuration
        self._signal_strat = (None, None, None)
        self._signal_concurrent = False  # Allow concurrent signals
        self._signal_accumulate = False  # Allow accumulating positions

        # Internal counters and references
        self._dataid = itertools.count(1)  # Data ID counter
        self._broker = BackBroker()  # Default broker
        self._broker.cerebro = self  # Back-reference to cerebro
        self._tradingcal = None  # Trading calendar
        self._pretimers = []  # Pre-run timers
        self._ohistory = []  # Order history
        self._fhistory = None  # Fund history

        # Override parameters from kwargs
        pkeys = self.params._getkeys()
        for key, val in kwargs.items():
            if key in pkeys:
                setattr(self.params, key, val)

    def setbroker(self, broker):
        """
        Sets a specific ``broker`` instance for this strategy, replacing the
        one inherited from cerebro.
        """
        self._broker = broker
        broker.cerebro = self
        self._maybe_add_store(broker)
        return broker

    def getbroker(self):
        """
        Returns the broker instance.

        This is also available as a ``property`` by the name ``broker``
        """
        return self._broker

    # Module passed to cerebro for multiprocessing during optimization
    def __call__(self, iterstrat):
        """
        Used during optimization to pass the cerebro over the multiprocessing
        module without complaints
        """
        token = self._open_run_scope()
        try:
            predata = self.p.optdatas and self._dopreload and self._dorunonce
            return self.runstrategies(iterstrat, predata=predata)
        finally:
            self._end_run(token)

    # Delete runstrats when pickling
    def __getstate__(self):
        """
        Used during optimization to prevent optimization result `runstrats`
        from being pickled to subprocesses
        """

        rv = vars(self).copy()
        if "runstrats" in rv:
            del rv["runstrats"]
        # ``threading.Event`` and ``RLock`` are intentionally process-local.
        # Optimization workers create a fresh inactive scope in ``__setstate__``.
        rv.pop("_event_stop", None)
        rv.pop("_runstop_lock", None)
        rv["_run_active"] = False
        rv["_run_scope_owner"] = None
        rv.pop("_external_channel_token", None)
        rv.pop("_external_channel_runstrats", None)
        rv.pop("_external_channel_closing", None)
        return rv

    def __setstate__(self, state):
        """Restore process-local run-stop state after multiprocessing pickle."""
        self.__dict__.update(state)
        self._event_stop = _RunStopEvent()
        self._runstop_lock = threading.RLock()
        self._run_active = False
        self._run_scope_token = 0
        self._run_scope_owner = None
        self._external_channel_token = None
        self._external_channel_runstrats = None
        self._external_channel_closing = False

    # Core method for backtesting. Any passed kwargs affect cerebro standard parameters.
    # If no data added, will stop immediately. Return value differs based on optimization.
    def _resolve_run_flags(self):
        """Resolve runonce/preload/exactbars/replay/live flags and build writers.

        Extracted from run() to keep that method readable. Sets the private
        execution-mode flags on self and populates self.runwriters /
        self.writers_csv. No behavior change.
        """
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
        self.runwriters = []

        # Add the system default writer if requested
        if self.p.writer is True:
            wr = WriterFile()
            self.runwriters.append(wr)

        # Instantiate any other writers
        for wrcls, wrargs, wrkwargs in self.writers:
            wr = wrcls(*wrargs, **wrkwargs)
            self.runwriters.append(wr)

        # Write down if any writer wants the full csv output
        self.writers_csv = any(map(lambda x: x.p.csv, self.runwriters))

    @_runstop_scoped
    def run(self, **kwargs) -> list:
        """The core method to perform backtesting. Any ``kwargs`` passed to it
        will affect the value of the standard parameters ``Cerebro`` was
        instantiated with.

        If `cerebro` has no data **and** no ``channel`` is given, the method
        will immediately bail out.

        Extra keyword arguments
        -----------------------
        channel : iterable or True, optional
            When provided the engine runs in **channel mode** instead of the
            traditional bar-based mode.

            * *iterable* – an ``Event`` stream (``StreamingEventQueue``,
              ``LiveEventQueue``, or any iterable yielding ``Event``
              objects).  Events are dispatched to the broker and then to
              every strategy via their ``notify_*`` callbacks.
            * ``True`` – strategies are instantiated and returned
              immediately **without** entering an event loop.  This is
              useful when an external async loop drives the data (e.g.
              external market-data watchers calling ``strategy.notify_tick()``
              directly).  Call ``cerebro.close_channel()`` from the same
              thread when that external loop is done to tear down brokers and
              strategies.

        It has different return values:

          - For No Optimization: a list contanining instances of the Strategy
            classes added with ``addstrategy``

          - For Optimization: a list of lists which contain instances of the
            Strategy classes added with ``addstrategy``
        """
        # --- channel mode ---------------------------------------------------
        channel = kwargs.pop("channel", None)
        if channel is not None:
            # _run_channel is dynamically typed; run() advertises -> list.
            return self._run_channel(channel, **kwargs)

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

        # Resolve runonce/preload/exactbars/replay/live execution flags + writers
        self._resolve_run_flags()

        # Running strategy list
        self.runstrats = []
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
                signalst, sargs, skwargs = SignalStrategy, (), {}

            # sargs/skwargs always come from a (args, kwargs) pair or the
            # tuple()/dict() defaults above; normalize for safe unpacking.
            sargs = sargs or ()
            skwargs = skwargs or {}

            # Add the signal strategy
            self.addstrategy(
                signalst,
                *sargs,
                _accumulate=self._signal_accumulate,
                _concurrent=self._signal_concurrent,
                signals=self.signals,
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

    def _build_optreturn_results(self, runstrats):
        """Build OptReturn results for an optimization run.

        Detaches analyzers from their strategy/data references (so the result
        is lightweight and picklable across process boundaries) and wraps each
        strategy's params + analyzers in an OptReturn.
        """
        results = []
        for strat in runstrats:
            for a in strat.analyzers:
                a.strategy = None
                a._parent = None
                # OPTIMIZED: Use __dict__ instead of dir() for better performance
                for attrname in list(a.__dict__.keys()):
                    if attrname.startswith("data"):
                        setattr(a, attrname, None)

            oreturn = OptReturn(strat.params, analyzers=strat.analyzers, strategycls=type(strat))
            results.append(oreturn)

        return results

    broker = property(getbroker, setbroker)
