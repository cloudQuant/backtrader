"""Cerebro run orchestration mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: strategy instantiation
preparation, runstrategies orchestration, writers and shared helpers.
"""

import itertools
import logging
import time
import traceback
from contextvars import ContextVar

from .. import errors, observers
from ..metabase import OwnerContext
from ..utils import OrderedDict, tzparse
from ..utils.log_message import _is_output_enabled_for, get_logger
from ..utils.py3 import integer_types
from .lifecycle import _capture_startup_observer_stop_errors

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")
_STARTUP_ATTEMPTS = ContextVar("backtrader_cerebro_startup_attempts", default=None)


def _record_startup_attempt(phase, component):
    """Record a component before entering its start method, when a run is active."""
    startup_attempts = _STARTUP_ATTEMPTS.get()
    if startup_attempts is not None:
        startup_attempts[phase].append(component)


class ExecutionMixin:
    """Run orchestration half of Cerebro (see module docstring)."""

    def _read_broker_lifecycle_value(self, accessor):
        """Read an optional broker summary without changing the run outcome.

        Lifecycle INFO logging is opt-in.  A custom broker can legitimately
        expose cash/value only after ``start()`` or before ``stop()``.  The
        summary is diagnostic data, so an unavailable accessor must not make
        a backtest fail.
        """
        try:
            return getattr(self._broker, accessor)()
        except Exception:
            # Broker implementations can raise third-party exceptions carrying
            # account or transport details.  This optional summary must never
            # copy that unknown payload into a framework log.
            logger.warning("broker %s unavailable for lifecycle logging", accessor)
            return None

    def _read_data_lifecycle_length(self, data):
        """Read a data length only while its lifecycle is still active."""
        try:
            return len(data)
        except Exception:
            # ``data`` can be a live feed whose ``stop()`` releases buffers.
            # Keep the event useful without writing a third-party traceback.
            logger.warning("data length unavailable for lifecycle logging")
            return None

    @staticmethod
    def _read_lifecycle_count(values):
        """Read an optional count without consuming iterable strategy input."""
        try:
            return len(values)
        except Exception:
            return None

    # Initialize count
    def _init_stcount(self):
        self.stcount = itertools.count(0)

    # Call next count
    def _next_stid(self):
        return next(self.stcount)

    def _cleanup_startup_attempts(self, startup_attempts, primary, predata):
        """Best-effort cleanup for a failed ordinary run startup.

        Only methods whose start was attempted are stopped.  Strategies are
        stopped only after their complete ``_start`` returned: that method
        starts analyzers and observers incrementally, so the child lifecycle
        state of the strategy that raised cannot be inferred safely here.
        Feed containers own the stop of child data, avoiding a second direct
        ``data.stop()`` call for those children.

        Secondary failures are attached to the original exception as finite
        ``(phase, component_type, exception_type, traceback_locations)``
        records.  Exception messages and locals are omitted.
        """
        cleanup_errors = []
        incomplete = []
        stopped = set()

        def record_cleanup_error(phase, component, exc):
            locations = tuple(
                (frame.filename, frame.lineno, frame.name)
                for frame in traceback.extract_tb(exc.__traceback__)
            )
            cleanup_errors.append((phase, type(component).__name__, type(exc).__name__, locations))

        def stop_many(phase, components, method, incomplete_reason=None, invoke=None):
            failed = set()
            for index, component in enumerate(components):
                key = (id(component), method)
                if key in stopped:
                    continue
                stopped.add(key)
                try:
                    if invoke is None:
                        getattr(component, method)()
                    else:
                        invoke(component, method)
                except BaseException as exc:
                    failed.add(id(component))
                    location = "%s[%d].%s" % (phase, index, method)
                    record_cleanup_error(location, component, exc)
                    reason = incomplete_reason or "stop raised; component state is unknown"
                    incomplete.append((location, type(component).__name__, reason))
            return failed

        # Match the ordinary teardown order, excluding final writer reporting
        # because startup did not reach the point where reports are complete.
        observer_stop_errors = {}

        def stop_strategy(strategy, method):
            with _capture_startup_observer_stop_errors(strategy) as captured:
                observer_stop_errors[id(strategy)] = captured
                getattr(strategy, method)()

        strategy_stop_failed = stop_many(
            "strategy",
            startup_attempts["started_strategies"],
            "_stop",
            "_stop raised; analyzer/observer teardown completion is unknown",
            invoke=stop_strategy,
        )
        for index, strategy in enumerate(startup_attempts["started_strategies"]):
            for observer_index, observer, exc in observer_stop_errors.get(id(strategy), ()):
                location = "strategy[%d]._stop.observer[%d].stop" % (index, observer_index)
                record_cleanup_error(location, observer, exc)
                incomplete.append(
                    (
                        location,
                        type(observer).__name__,
                        "observer.stop raised and was suppressed; observer state is unknown",
                    )
                )
            if id(strategy) in strategy_stop_failed:
                continue
            try:
                if strategy.stats.items:
                    incomplete.append(
                        (
                            "strategy[%d]._stop.observers" % index,
                            type(strategy).__name__,
                            "Strategy._stop suppresses observer.stop exceptions; outcome is unobservable",
                        )
                    )
            except BaseException as exc:
                record_cleanup_error("strategy[%d].observers" % index, strategy, exc)
                incomplete.append(
                    (
                        "strategy[%d]._stop.observers" % index,
                        type(strategy).__name__,
                        "observer set is unreadable; observer cleanup outcome is unknown",
                    )
                )
        stop_many("writer", startup_attempts["writers"], "stop")
        stop_many("broker", startup_attempts["brokers"], "stop")

        # data._feed identifies the feed whose stop owns this data object's
        # teardown.  If ownership cannot be read, do not risk a duplicate stop.
        attempted_feed_ids = {id(feed) for feed in startup_attempts["feeds"]}
        direct_datas = []
        missing_feed_owner = object()
        if not predata:
            for data in startup_attempts["datas"]:
                try:
                    data_owner = vars(data).get("_feed", missing_feed_owner)
                except BaseException as exc:
                    record_cleanup_error("data.feed_owner", data, exc)
                    data_owner = missing_feed_owner
                if data_owner is missing_feed_owner:
                    if attempted_feed_ids:
                        incomplete.append(
                            (
                                "data.stop",
                                type(data).__name__,
                                "feed ownership is unknown; direct stop was skipped to avoid a duplicate",
                            )
                        )
                        continue
                if data_owner is None or id(data_owner) not in attempted_feed_ids:
                    direct_datas.append(data)
            stop_many("data", direct_datas, "stop")

        stop_many("feed", startup_attempts["feeds"], "stop")
        for index, store in enumerate(startup_attempts["stores"]):
            try:
                managed = getattr(store, "_cerebro_managed_lifecycle", True)
            except BaseException as exc:
                record_cleanup_error("store[%d].stop" % index, store, exc)
                incomplete.append(
                    (
                        "store[%d].stop" % index,
                        type(store).__name__,
                        "lifecycle ownership could not be read; stop was skipped",
                    )
                )
                continue
            if managed is False:
                incomplete.append(
                    (
                        "store[%d].stop" % index,
                        type(store).__name__,
                        "unmanaged Store remains under its external lifecycle owner",
                    )
                )
                continue
            key = (id(store), "stop")
            if key in stopped:
                continue
            stopped.add(key)
            try:
                store.stop()
            except BaseException as exc:
                record_cleanup_error("store[%d].stop" % index, store, exc)
                incomplete.append(
                    ("store[%d].stop" % index, type(store).__name__, "stop raised; state is unknown")
                )

        completed_strategies = {id(strategy) for strategy in startup_attempts["started_strategies"]}
        for strategy in startup_attempts["strategy_attempts"]:
            if id(strategy) not in completed_strategies:
                incomplete.append(
                    (
                        "strategy._start",
                        type(strategy).__name__,
                        "_start did not return; child completion is unknown, so _stop was skipped",
                    )
                )
        for timer in startup_attempts["timers"]:
            incomplete.append(
                (
                    "timer.start",
                    type(timer).__name__,
                    "runstrategies has no timer stop step; start state may be partial",
                )
            )

        if cleanup_errors or incomplete:
            try:
                previous_errors = getattr(primary, "_backtrader_startup_cleanup_errors", ())
                setattr(
                    primary,
                    "_backtrader_startup_cleanup_errors",
                    tuple(previous_errors) + tuple(cleanup_errors),
                )
                previous_incomplete = getattr(primary, "_backtrader_startup_cleanup_incomplete", ())
                setattr(
                    primary,
                    "_backtrader_startup_cleanup_incomplete",
                    tuple(previous_incomplete) + tuple(incomplete),
                )
            except BaseException:
                # Diagnostics must never replace the primary startup exception.
                pass
            for phase, component_type, exception_type, _locations in cleanup_errors:
                try:
                    logger.warning(
                        "startup cleanup failed: %s on %s (%s)",
                        phase,
                        component_type,
                        exception_type,
                    )
                except BaseException:
                    # A logging handler is not allowed to mask the primary error.
                    pass

    def _prepare_run(self, predata=False):
        """Start components and (optionally) preload data before strategies run.

        Extracted from runstrategies() to keep that method readable. Starts
        stores, applies cheat-on-open/fund/order-history settings, starts the
        broker and feeds, writes CSV writer headers, and resets/preloads each
        data feed unless ``predata`` is True.
        """
        # Iterate stores and start
        for store in self.stores:
            _record_startup_attempt("stores", store)
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
        _record_startup_attempt("brokers", self._broker)
        self._broker.start()
        # Feed start
        for feed in self.feeds:
            _record_startup_attempt("feeds", feed)
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
                _record_startup_attempt("datas", data)
                data._start()
                if self._dopreload:
                    data.preload()

    # Run strategy
    def runstrategies(self, iterstrat, predata=False):
        """
        Internal method invoked by ``run``` to run a set of strategies
        """
        # Lifecycle diagnostics are opt-in and must not probe broker state
        # before start()/after stop().  Some live/custom brokers deliberately
        # reject those accessors outside their active lifecycle window.
        log_lifecycle = _is_output_enabled_for(logging.INFO)
        t0 = time.time() if log_lifecycle else None
        initial_cash = None
        self._init_stcount()
        # Initialize running strategy as empty list
        self.runningstrats = runstrats = []
        startup_attempts = {
            "stores": [],
            "brokers": [],
            "feeds": [],
            "datas": [],
            "strategy_attempts": [],
            "started_strategies": [],
            "writers": [],
            "timers": [],
        }
        startup_token = _STARTUP_ATTEMPTS.set(startup_attempts)
        try:
            # Start stores/broker/feeds, apply fund + order history, write headers
            # and (optionally) preload data. Extracted for readability.
            self._prepare_run(predata)
            if log_lifecycle:
                initial_cash = self._read_broker_lifecycle_value("getcash")
                strategy_count = self._read_lifecycle_count(iterstrat)
                logger.info(
                    "run starting: runonce=%s oldsync=%s strategies=%s datas=%d initial cash=%s",
                    self.p.runonce,
                    self.p.oldsync,
                    strategy_count if strategy_count is not None else "unavailable",
                    len(self.datas),
                    initial_cash if initial_cash is not None else "unavailable",
                )
                for data in self.datas:
                    name = getattr(data, "_name", "")
                    bars = self._read_data_lifecycle_length(data)
                    logger.info(
                        "data loaded: name=%s bars=%s",
                        name,
                        bars if bars is not None else "unavailable",
                    )
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
                    logger.warning("execution:122 suppressed bare")
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
        except BaseException as startup_error:
            try:
                self._cleanup_startup_attempts(startup_attempts, startup_error, predata)
            except BaseException as cleanup_error:
                try:
                    logger.warning(
                        "startup cleanup coordinator failed (%s)", type(cleanup_error).__name__
                    )
                except BaseException:
                    pass
            raise
        finally:
            _STARTUP_ATTEMPTS.reset(startup_token)

        # StrategySkipError may exclude every strategy; cleanup still runs.
        run_exception = None
        # If runstrats is not empty list
        if runstrats:
            try:
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
                    startup_attempts["strategy_attempts"].append(strat)
                    strat._start()
                    startup_attempts["started_strategies"].append(strat)
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
                    startup_attempts["writers"].append(writer)
                    writer.start()

                # Prepare timers
                self._timers = []
                self._timerscheat = []
                # Loop timers
                for timer in self._pretimers:
                    # preprocess tzdata if needed
                    # Start timer
                    startup_attempts["timers"].append(timer)
                    timer.start(self.datas[0])
                    # If timer parameter cheat is True, add timer to self._timerscheat, otherwise add to self._timers
                    if timer.params.cheat:
                        self._timerscheat.append(timer)
                    else:
                        self._timers.append(timer)
            except BaseException as startup_error:
                try:
                    self._cleanup_startup_attempts(startup_attempts, startup_error, predata)
                except BaseException as cleanup_error:
                    try:
                        logger.warning(
                            "startup cleanup coordinator failed (%s)",
                            type(cleanup_error).__name__,
                        )
                    except BaseException:
                        pass
                raise
            # Run the main loop; keep cleanup deterministic, but never turn a
            # strategy/runtime exception into a successful empty backtest.
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
        # Capture the final value while the broker is still active.  This is
        # only diagnostic data, so a custom broker may decline the accessor.
        final_value = None
        final_bars = None
        if run_exception is None and log_lifecycle:
            final_value = self._read_broker_lifecycle_value("getvalue")
            final_bars = self._read_data_lifecycle_length(self.datas[0]) if self.datas else 0

        # Final reports may read live broker/feed state. Preserve virtual writer
        # dispatch while those resources are open, and clean up even on failure.
        try:
            try:
                self.stop_writers(runstrats)
            except Exception as exc:
                if run_exception is None:
                    run_exception = exc
                else:
                    logger.warning("writer report unavailable after failed run")
        finally:
            self._broker.stop()
            if not predata:
                for data in self.datas:
                    data.stop()
            for feed in self.feeds:
                feed.stop()
            for store in self.stores:
                if getattr(store, "_cerebro_managed_lifecycle", True) is False:
                    continue
                store.stop()
        if run_exception is None and log_lifecycle:
            if final_value is None or initial_cash is None:
                pnl = "unavailable"
            else:
                try:
                    pnl = final_value - initial_cash
                except Exception:
                    logger.warning("broker pnl unavailable for lifecycle logging")
                    pnl = "unavailable"
            logger.info(
                "run finished: final value=%s pnl=%s bars=%d elapsed=%.2fs",
                final_value if final_value is not None else "unavailable",
                pnl,
                final_bars if final_bars is not None else 0,
                time.time() - t0,
            )
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
        first_error = None
        try:
            self._write_final_info(runstrats)
        except BaseException as exc:
            first_error = exc
        finally:
            for writer in self.runwriters:
                try:
                    writer.stop()
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    def _write_final_info(self, runstrats):
        """Collect and emit final reports before broker/feed resources close."""
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
