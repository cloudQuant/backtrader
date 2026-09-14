"""Cerebro run orchestration mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: strategy instantiation
preparation, runstrategies orchestration, writers and shared helpers.
"""

import itertools

from .. import errors, observers
from ..metabase import OwnerContext
from ..utils import OrderedDict, tzparse
from ..utils.log_message import get_logger
from ..utils.py3 import integer_types

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")


class ExecutionMixin:
    """Run orchestration half of Cerebro (see module docstring)."""

    # Initialize count
    def _init_stcount(self):
        self.stcount = itertools.count(0)

    # Call next count
    def _next_stid(self):
        return next(self.stcount)

    def _prepare_run(self, predata=False):
        """Start components and (optionally) preload data before strategies run.

        Extracted from runstrategies() to keep that method readable. Starts
        stores, applies cheat-on-open/fund/order-history settings, starts the
        broker and feeds, writes CSV writer headers, and resets/preloads each
        data feed unless ``predata`` is True.
        """
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
            wheaders = []
            # Iterate data, if data csv attribute is True, get headers that need saving
            for data in self.datas:
                if data.csv:
                    wheaders.extend(data.getwriterheaders())
            # Save writer headers
            for writer in self.runwriters:
                if writer.p.csv:
                    writer.addheaders(wheaders)

        # If no predata, need to pre-process data, similar to run method preprocessing
        if not predata:
            for data in self.datas:
                data.reset()
                if self._exactbars < 1:  # datas can be a full length
                    data.extend(size=self.params.lookahead)
                data._start()
                if self._dopreload:
                    data.preload()

    # Run strategy
    def runstrategies(self, iterstrat, predata=False):
        """
        Internal method invoked by ``run``` to run a set of strategies
        """
        self._init_stcount()
        # Initialize running strategy as empty list
        self.runningstrats = runstrats = []
        # Start stores/broker/feeds, apply fund + order history, write headers
        # and (optionally) preload data. Extracted for readability.
        self._prepare_run(predata)
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
            # Run the main loop; keep cleanup deterministic, but never turn a
            # strategy/runtime exception into a successful empty backtest.
            run_exception = None
            try:
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
            except Exception as exc:
                run_exception = exc
                logger.exception("Unhandled exception in run loop, cleaning up before re-raising")
            finally:
                # Iterate strategies and stop running (always runs)
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
            if getattr(store, "_cerebro_managed_lifecycle", True) is False:
                continue
            store.stop()
        # Stop writer
        self.stop_writers(runstrats)
        if run_exception is not None:
            raise run_exception
        # If doing parameter optimization and optreturn is True, build lightweight
        # OptReturn results (detached from data) instead of full strategy objects.
        if self._dooptimize and self.p.optreturn:
            return self._build_optreturn_results(runstrats)

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
        stratinfos = {}
        for strat in runstrats:
            stname = strat.__class__.__name__
            stratinfos[stname] = strat.getwriterinfo()

        cerebroinfo["Strategies"] = stratinfos
        # Write cerebroinfo to file
        for writer in self.runwriters:
            writer.writedict({"Cerebro": cerebroinfo})
            writer.stop()

    # Run writer's next
    def _next_writers(self, runstrats):
        if not self.runwriters:
            return

        if self.writers_csv:
            wvalues = []
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
