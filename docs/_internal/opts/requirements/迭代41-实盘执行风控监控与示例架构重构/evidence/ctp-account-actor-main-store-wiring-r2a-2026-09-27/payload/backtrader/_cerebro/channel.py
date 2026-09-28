"""Cerebro channel event mode mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: channel event dispatch,
channel strategy wiring and the channel run loop.
"""

import datetime
import itertools
import logging
from datetime import timezone
from typing import Dict

from .. import errors
from ..channel import ChannelDataRef
from ..lineseries import LineSeries
from ..metabase import OwnerContext
from ..utils import date2num
from ..utils.log_message import _is_output_enabled_for, get_logger, throttled_warning

UTC = timezone.utc

# Keep the historical logger name (D28-04.6): routing/filters must not change.
logger = get_logger("backtrader.cerebro")


class ChannelMixin:
    """Channel event mode half of Cerebro (see module docstring)."""

    def dispatch_channel_event(self, event):
        """Dispatch a channel event to all running strategies.

        Routes tick, orderbook, funding, and bar events from the channel
        system (StreamingEventQueue / LiveEventQueue) to the appropriate
        ``notify_*`` callbacks on each strategy.

        Args:
            event: Event wrapper with ``.data`` and ``.channel_type`` attrs.
        """
        data = event.data
        channel_type = event.channel_type
        data_ref = getattr(event, "_source_feed", None)
        if data_ref is not None:
            # Feed events use the actual data object for native broker routing.
            # Channel-only events are matched separately by _run_channel().
            processor = getattr(self._broker, "process_" + channel_type, None)
            if processor is not None and channel_type in {"tick", "orderbook"}:
                processor(data, data=data_ref)
        else:
            data_ref = self._get_channel_data_ref(event)

        for strat in self.runningstrats:
            strat._event_count += 1
            if data_ref is not None and hasattr(strat, "_register_hft_data"):
                strat._register_hft_data(data_ref)

            if channel_type == "tick":
                strat._tick_count += 1
                strat._last_tick[getattr(data, "symbol", "")] = data
                strat.notify_tick(data)
                strat._notify_tick_to_observers(data)
            elif channel_type == "orderbook":
                strat._last_ob[getattr(data, "symbol", "")] = data
                strat.notify_orderbook(data)
            elif channel_type == "funding":
                strat._last_funding[getattr(data, "symbol", "")] = data
                strat.notify_funding(data)
            elif channel_type == "bar":
                strat.notify_bar(data)
                strat._notify_bar_to_observers(data)

    def _get_channel_data_ref(self, event):
        """Return a stable lightweight data reference for a channel event."""
        event_data = getattr(event, "data", None)
        symbol = getattr(event_data, "symbol", None) or getattr(event, "channel_name", None)
        if symbol is None:
            return None

        symbol = str(symbol)
        if not hasattr(self, "_channel_data_refs"):
            # Same shape as Cerebro.__init__'s typed mapping (iteration 28
            # note: minimal annotation so the mixin type-checks standalone).
            self._channel_data_refs: Dict[str, ChannelDataRef] = {}

        data_ref = self._channel_data_refs.get(symbol)
        if data_ref is None:
            data_ref = ChannelDataRef(
                symbol=symbol, channel_name=getattr(event, "channel_name", None)
            )
            self._channel_data_refs[symbol] = data_ref
        return data_ref

    def _start_channel_strategy(self, strat):
        """Start a channel-mode strategy without assuming bar datas exist."""
        if getattr(strat, "datas", None):
            strat._start()
            return

        for analyzer in itertools.chain(strat.analyzers, strat._slave_analyzers):
            analyzer._start()

        for observer in strat._get_all_observers():
            observer._start()

        strat.start()

    def _advance_channel_strategy_clock(self, strat, event):
        """Advance no-data channel strategies so observers can run per event."""
        if getattr(strat, "datas", None):
            return

        try:
            strat.forward()
        except Exception:
            throttled_warning(
                logger,
                "channel_strategy_forward",
                "Channel strategy forward() failed",
                exc_info=False,
            )

        timestamp = getattr(event, "timestamp", None)
        if timestamp is None:
            return

        try:
            event_dt = datetime.datetime.fromtimestamp(float(timestamp), UTC)
            event_num = date2num(event_dt)
            strat.lines.datetime[0] = event_num
            strat._last_valid_datetime = event_num
            # `placeholder_data` is an optional strategy-owned mapping. A
            # normal lookup for the standard Strategy path sends its missing
            # case through LineSeries fallback resolution on every event.
            # Bypass only that known fallback; a custom accessor may provide
            # the mapping dynamically and must retain normal getattr() rules.
            strategy_type = type(strat)
            strategy_getattribute = getattr(strategy_type, "__getattribute__", None)
            if (
                strategy_getattribute is object.__getattribute__
                and getattr(strategy_type, "__getattr__", None) is LineSeries.__getattr__
            ):
                try:
                    placeholder_map = object.__getattribute__(strat, "placeholder_data")
                except AttributeError:
                    placeholder_map = None
            else:
                placeholder_map = getattr(strat, "placeholder_data", None)
            if isinstance(placeholder_map, dict):
                symbol = getattr(getattr(event, "data", None), "symbol", None)
                placeholder = placeholder_map.get(str(symbol)) if symbol is not None else None
                if placeholder is not None:
                    try:
                        placeholder._len = max(int(getattr(placeholder, "_len", 0)), len(strat))
                    except Exception:
                        throttled_warning(
                            logger,
                            "channel_placeholder_length",
                            "Channel placeholder length update failed",
                            exc_info=False,
                        )

                    try:
                        placeholder.datetime[0] = event_num
                    except Exception:
                        throttled_warning(
                            logger,
                            "channel_placeholder_datetime",
                            "Channel placeholder datetime update failed",
                            exc_info=False,
                        )

                    try:
                        last_price = getattr(event.data, "price", None)
                        if last_price is None:
                            last_price = getattr(event.data, "close", None)
                        if last_price is not None:
                            placeholder.close[0] = float(last_price)
                    except Exception:
                        throttled_warning(
                            logger,
                            "channel_placeholder_price",
                            "Channel placeholder price update failed",
                            exc_info=False,
                        )
        except Exception:
            throttled_warning(
                logger,
                "channel_strategy_datetime",
                "Channel strategy datetime update failed",
                exc_info=False,
            )

    def _step_channel_strategy(self, strat):
        """Run channel-mode analyzers and observers once per event."""
        if getattr(strat, "datas", None):
            return

        for analyzer in itertools.chain(strat.analyzers, strat._slave_analyzers):
            analyzer._next()

        for observer in strat._get_all_observers():
            observer._next()

    def _stop_channel_strategy(self, strat):
        """Stop a channel-mode strategy without requiring bar datas."""
        if getattr(strat, "datas", None):
            strat._stop()
            return

        strat.stop()

        for analyzer in itertools.chain(strat.analyzers, strat._slave_analyzers):
            analyzer._stop()

        for observer in strat._get_all_observers():
            try:
                if hasattr(observer, "stop"):
                    observer.stop()
            except Exception:
                logger.warning(
                    "Observer %s.stop() raised an exception",
                    type(observer).__name__,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Channel mode implementation (called from run(channel=...))
    # ------------------------------------------------------------------
    def _run_channel(self, channel, **kwargs):
        """Internal: run strategies in channel event mode.

        ``channel`` may be:
        * An iterable of ``Event`` objects – events are processed in a
          loop, dispatched to broker and strategies.
        * ``True`` – strategies are instantiated and returned immediately
          without entering an event loop (for external async drivers).
        """
        # Override params
        pkeys = self.params._getkeys()
        for key, val in kwargs.items():
            if key in pkeys:
                setattr(self.params, key, val)

        # Channel-mode brokers emit simulated order notifications; force the
        # quick-notify path so strategy/observer callbacks receive them.
        self.p.quicknotify = True

        # --- strategy instantiation (simplified, no bar-data required) ---
        self._init_stcount()
        runstrats: list = []
        self.runningstrats = runstrats
        self._channel_data_refs = {}

        # Start broker
        self._broker.start()

        # The optional lifecycle summary must only read a broker after it has
        # entered its active state.  Do not make a channel run depend on an
        # informational accessor being available.
        if _is_output_enabled_for(logging.INFO):
            try:
                cash = self._broker.getcash()
            except Exception:
                logger.warning("channel broker cash unavailable for lifecycle logging")
                cash = "unavailable"
            logger.info(
                "channel run starting: strategies=%d datas=%d cash=%s",
                len(self.strats),
                len(self.datas),
                cash,
            )

        self._instantiate_channel_strategies(runstrats)
        self._wire_channel_strategies(runstrats)

        # If channel is just True, return strategies for external event loops
        if channel is True:
            self.runstrats = [runstrats]
            return runstrats

        # --- channel event loop ---
        for event in channel:
            if self._event_stop:
                break

            for strat in runstrats:
                self._advance_channel_strategy_clock(strat, event)

            # 1. Let the broker process the raw event data
            ch = event.channel_type
            evdata = event.data
            if ch == "tick" and hasattr(self._broker, "process_tick"):
                self._broker.process_tick(evdata)
            elif ch == "orderbook" and hasattr(self._broker, "process_orderbook"):
                self._broker.process_orderbook(evdata)
            elif ch == "bar" and hasattr(self._broker, "process_bar"):
                self._broker.process_bar(evdata)

            # 2. Deliver broker order-fill notifications to strategies
            while True:
                order = self._broker.get_notification()
                if order is None:
                    break
                owner = getattr(order, "owner", None)
                if owner is None:
                    owner = getattr(getattr(order, "p", None), "owner", None)
                if owner is None and runstrats:
                    owner = runstrats[0]
                if owner is not None:
                    owner._addnotification(order, quicknotify=True)

            # 3. Dispatch channel event to strategies
            self.dispatch_channel_event(event)

            # 4. Advance analyzers/observers that rely on next()-style hooks
            for strat in runstrats:
                self._step_channel_strategy(strat)

        # --- teardown ---
        self._teardown_channel(runstrats)
        return runstrats

    def _teardown_channel(self, runstrats):
        """Stop a channel session after its event loop or owner has finished."""
        for strat in runstrats:
            self._stop_channel_strategy(strat)

        self._broker.stop()
        self.runstrats = [runstrats]

    def _instantiate_channel_strategies(self, runstrats):
        """Instantiate strategy classes for channel mode and append to
        ``runstrats``.

        Extracted from ``_run_channel`` (instantiation phase); behavior
        unchanged. Honors ``StrategySkipError``, ``oldsync``,
        ``tradehistory`` and broker-provided context exactly as before.
        """
        # Instantiate each strategy class added via addstrategy()
        iterstrats = itertools.product(*self.strats)
        for iterstrat in iterstrats:
            for stratcls, sargs, skwargs in iterstrat:
                try:
                    with OwnerContext.set_owner(self):
                        if hasattr(stratcls, "_create_strategy_safely"):
                            strat = stratcls._create_strategy_safely(*sargs, **skwargs)
                        else:
                            strat = stratcls(*sargs, **skwargs)
                except errors.StrategySkipError:
                    logger.warning("channel:297 suppressed bare")
                    continue  # user requested skip, same as standard run() path
                if self.p.oldsync:
                    strat._oldsync = True
                if self.p.tradehistory:
                    strat.set_tradehistory()
                runstrats.append(strat)

        context_getter = getattr(self._broker, "get_context", None)
        if callable(context_getter):
            context = context_getter()
            for strat in runstrats:
                strat.context = context

    def _wire_channel_strategies(self, runstrats):
        """Attach observers, analyzers and sizers to channel strategies and
        start them.

        Extracted from ``_run_channel`` (setup phase); behavior unchanged.
        """
        # Channel mode still needs explicit observers/analyzers initialization.
        defaultsizer = self.sizers.get(None, (None, None, None))
        for idx, strat in enumerate(runstrats):
            for multi, obscls, obsargs, obskwargs in self.observers:
                strat._addobserver(multi, obscls, *obsargs, **obskwargs)

            for ancls, anargs, ankwargs in self.analyzers:
                strat._addanalyzer(ancls, *anargs, **ankwargs)

            sizer, sargs, skwargs = self.sizers.get(idx, defaultsizer)
            if sizer is not None:
                strat._addsizer(sizer, *sargs, **skwargs)

            self._start_channel_strategy(strat)
