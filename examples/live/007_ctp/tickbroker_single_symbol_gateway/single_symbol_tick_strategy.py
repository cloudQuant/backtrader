"""SingleSymbolTickStrategy: Single-symbol long-only tick momentum strategy.

Self-contained: this file holds the configurable futures strategy base and
``SingleSymbolTickStrategy``, which ``run.py`` in this directory imports. The backtest example and
the live example of the same name carry identical copies of this file.
"""

from __future__ import annotations

import datetime as _dt
import math
import time
from collections import deque

import backtrader as bt


class _ScalarLine:
    """Simple scalar line implementation for placeholder data."""

    def __init__(self, value=0.0):
        """Initialize scalar line.

        Args:
            value: Initial value.
        """
        self.value = value

    def __getitem__(self, index):
        return self.value

    def __setitem__(self, index, value):
        self.value = value

    def datetime(self, index=0):
        """Get datetime value.

        Args:
            index: Line index (unused for scalar).

        Returns:
            Datetime value or epoch if conversion fails.
        """
        try:
            return bt.num2date(self.value)
        except Exception:
            return _dt.datetime.fromtimestamp(0.0)

    def date(self, index=0):
        """Get date value.

        Args:
            index: Line index (unused for scalar).

        Returns:
            Date portion of datetime.
        """
        return self.datetime(index).date()


class _PlaceholderParams:
    """Placeholder parameters for PlaceholderData."""

    def __init__(self):
        """Initialize with default session end time."""
        self.sessionend = _dt.time(23, 59, 59, 999990)


class PlaceholderData:
    """Placeholder data feed for testing without real data connection.

    This class provides a minimal data feed implementation that can be
    used for testing strategies in environments without real market data.
    """

    def __init__(self, symbol):
        """Initialize placeholder data feed.

        Args:
            symbol: Symbol name.
        """
        self._name = str(symbol)
        self.name = self._name
        self.symbol = self._name
        self._compensate = None
        self._len = 0
        self.p = _PlaceholderParams()
        self.datetime = _ScalarLine(0.0)
        self.close = _ScalarLine(0.0)

    def __len__(self):
        """Return data length."""
        return int(self._len)

    def __bool__(self):
        """Return True for truthiness check."""
        return True

    @staticmethod
    def date2num(value):
        """Convert datetime to backtrader numeric format."""
        return bt.date2num(value)

    @staticmethod
    def num2date(value):
        """Convert backtrader numeric format to datetime."""
        return bt.num2date(value)


BASE_FUTURES_STRATEGY_PARAMS = (
    ("printlog", True),
    ("enable_trading", True),
    ("stop_after_ticks", 0),
    ("open_offset", "open"),
    ("close_offset", "close_today"),
    ("force_entry_after_ticks", 0),
    ("force_exit_after_ticks", 0),
    ("cancel_pending_after_ticks", 0),
    # Iteration 62 live CTP (direct / Gateway) settings; the defaults keep the
    # backtest behaviour unchanged.  ``order_exectype="limit"`` sends marketable
    # limit orders priced ``slippage_ticks * price_tick`` through the last price
    # (D62-33); ``close_offset="auto"`` plans explicit close_today /
    # close_yesterday (SHFE/INE) or close orders from the broker's closable view
    # (D62-18/22/26) instead of a fixed offset.
    ("order_exectype", "market"),
    ("price_tick", 1.0),
    ("slippage_ticks", 2),
    ("reject_backoff_seconds", 3.0),
)


class ConfigurableFuturesStrategyBase(bt.Strategy):
    """Base strategy class for configurable futures trading.

    This base class provides common functionality for futures trading
    strategies including order management, position tracking, and
    configurable trading parameters.
    """

    params = BASE_FUTURES_STRATEGY_PARAMS

    def __init__(self):
        """Initialize strategy state."""
        self.pending_refs = set()
        self.pending_orders = {}
        self.pending_order_submitted_ticks = {}
        self.position_cache = {}
        self.placeholder_data = {}
        self.signal_count = 0
        self.completed_roundtrips = 0
        self.data_status = {}
        self._last_order_status = {}

    def log(self, message):
        """Log message if printlog parameter is enabled.

        Args:
            message: Message to log.
        """
        if self.p.printlog:
            print(f"[{self.__class__.__name__}] {message}")

    def notify_data(self, data, status, *args, **kwargs):
        """Handle data feed status changes.

        Args:
            data: Data feed that changed status.
            status: New status value.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        status_name = data._getstatusname(status)
        self.data_status[getattr(data, "_name", "")] = status_name
        self.log(f"data {getattr(data, '_name', '')} -> {status_name}")

    def _resolve_data(self, symbol):
        """Resolve data feed by symbol name.

        Args:
            symbol: Symbol name to resolve.

        Returns:
            Data feed for the symbol, or a PlaceholderData if not found.
        """
        symbol = str(symbol)
        resolved_data = None
        if getattr(self, "datas", None):
            try:
                resolved_data = self.getdatabyname(symbol)
            except Exception:
                resolved_data = None

            if resolved_data is None:
                for data in self.datas:
                    if getattr(data, "_name", None) == symbol:
                        resolved_data = data
                        break
                    if getattr(data, "_dataname", None) == symbol:
                        resolved_data = data
                        break

        if resolved_data is not None:
            try:
                if len(resolved_data) > 0:
                    return resolved_data
            except Exception:
                return resolved_data

        data = self.placeholder_data.get(symbol)
        if data is None:
            data = PlaceholderData(symbol)
            self.placeholder_data[symbol] = data
        return data

    def _refresh_position(self, symbol):
        """Refresh and cache position size for symbol.

        Args:
            symbol: Symbol name.

        Returns:
            Current position size.
        """
        symbol = str(symbol)
        data = self._resolve_data(symbol)
        try:
            # Gateway mode: several strategies share the account, so only this
            # strategy's own position (the Gateway's ledger of it) counts. The
            # account-scope broker.getposition() is not available here.
            position = self.get_strategy_position(data)
            size = float(getattr(position, "size", 0.0) or 0.0)
        except Exception:
            size = float(self.position_cache.get(symbol, 0.0))
        self.position_cache[symbol] = size
        return size

    def _position_size(self, symbol):
        """Get cached position size for symbol.

        Args:
            symbol: Symbol name.

        Returns:
            Cached position size.
        """
        symbol = str(symbol)
        if symbol not in self.position_cache:
            return self._refresh_position(symbol)
        return float(self.position_cache[symbol])

    def start(self):
        """Take over orders restored by a direct-mode live broker (R-6/7).

        A direct ``BtApiBroker`` recovers this strategy directory's working
        venue orders and waiting orders at startup; they are tracked like
        orders submitted by this run.  Other brokers have no restored orders.
        """
        take_over = getattr(self.broker, "take_over_restored_orders", None)
        if not callable(take_over):
            return
        for order in take_over(self):
            self.pending_refs.add(order.ref)
            self.pending_orders[order.ref] = order
            self.pending_order_submitted_ticks[order.ref] = int(getattr(self, "_tick_count", 0))
            self.log(f"took over restored order {order.ref} offset={order.info.get('offset')}")

    def _refusal_backoff(self):
        """Per-instrument monotonic time until which new orders wait after a refusal."""
        backoff = getattr(self, "_refusal_backoff_until", None)
        if backoff is None:
            backoff = self._refusal_backoff_until = {}
        return backoff

    def _limit_price(self, data, side):
        """Marketable limit price: ``slippage_ticks`` ticks through the last price.

        The last price is the strategy's latest tick of the instrument when it
        tracks one, else the feed line: tick callbacks can run while a feed is
        loading its next line, whose values are not written yet (``close[0]``
        reads 0), so the last written line follows. Returns ``None`` when no
        valid last price is known.
        """
        last = None
        for value in self._last_price_candidates(data):
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                last = value
                break
        if last is None:
            return None
        offset = float(self.p.slippage_ticks) * float(self.p.price_tick)
        price = last + offset if side == "buy" else last - offset
        return price if price > 0 else None

    def _last_price_candidates(self, data):
        """Most recent first: tracked tick prices, then the feed lines."""
        symbol = str(getattr(data, "_name", None) or getattr(data, "_dataname", None) or "")
        latest = getattr(self, "latest_prices", None)
        if isinstance(latest, dict):
            yield latest.get(symbol)
        bars = getattr(self, "_tick_bars", None)
        if isinstance(bars, dict) and isinstance(bars.get(symbol), dict):
            yield bars[symbol].get("close")
        if symbol and symbol == str(getattr(self.p, "symbol", "") or ""):
            yield getattr(self, "latest_tick_price", None)
            prices = getattr(self, "prices", None)
            if prices:
                yield prices[-1]
        for ago in (0, -1):
            try:
                yield data.close[ago]
            except (IndexError, TypeError, ValueError):
                continue

    def _close_plan(self, data, side, quantity):
        """Explicit close offsets for ``close_offset="auto"`` (never a fixed close_today).

        Uses the broker's closable view of the side being closed: separate
        close_yesterday / close_today orders on SHFE/INE, ``close`` elsewhere.
        Returns an empty plan when the split or the closable quantity is unknown.
        """
        reader = getattr(self.broker, "get_closable", None)
        if not callable(reader):
            return [("close", quantity)]
        try:
            view = reader(data, "short" if side == "buy" else "long")
        except RuntimeError as exc:
            # Not answerable now (Gateway restarting, ledger not ready): no close.
            self.log(f"closable view unavailable ({exc}): no close planned")
            return []
        if view.get("venue") in ("SHFE", "INE"):
            today, yesterday = view.get("closable_today"), view.get("closable_yesterday")
            if today is None or yesterday is None:
                return []
            plan = []
            if yesterday:
                plan.append(("close_yesterday", min(int(yesterday), quantity)))
            rest = quantity - sum(qty for _, qty in plan)
            if rest > 0 and today:
                plan.append(("close_today", min(int(today), rest)))
            return plan
        closable = int(view.get("closable") or 0)
        return [("close", min(closable, quantity))] if closable else []

    def _submit_market(self, side, symbol, size, offset, signal_tag):
        """Submit an order for a signal (market by default, see ``order_exectype``).

        Args:
            side: Order side ('buy' or 'sell').
            symbol: Symbol name.
            size: Order size.
            offset: Order offset ('open', 'close', 'close_today', 'close_yesterday'
                or 'auto' to plan explicit close offsets).
            signal_tag: Signal identifier tag.

        Returns:
            The last submitted order instance, or None.
        """
        quantity = int(round(abs(float(size or 0.0))))
        if quantity <= 0:
            return None
        backoff = self._refusal_backoff().get(str(symbol), 0.0) - time.monotonic()
        if backoff > 0:
            self.log(f"refusal backoff for {symbol}: {signal_tag} skipped ({backoff:.1f}s left)")
            return None

        if not self.p.enable_trading:
            self.log(
                f"signal only {signal_tag}: {side.upper()} {symbol} size={quantity} offset={offset}"
            )
            return None

        data = self._resolve_data(symbol)
        if offset != "auto":
            return self._submit_one(side, symbol, data, quantity, offset, signal_tag)
        plan = self._close_plan(data, side, quantity)
        if not plan:
            self.log(f"no closable position for {signal_tag}: {side.upper()} {symbol}")
            return None
        order = None
        for close_offset, close_size in plan:
            order = self._submit_one(side, symbol, data, close_size, close_offset, signal_tag)
        return order

    def _submit_one(self, side, symbol, data, quantity, offset, signal_tag):
        kwargs = {"data": data, "size": quantity}
        if str(self.p.order_exectype).lower() == "limit":
            price = self._limit_price(data, side)
            if price is None:
                self.log(f"no valid price for {symbol}: {signal_tag} skipped")
                return None
            kwargs["exectype"] = bt.Order.Limit
            kwargs["price"] = price
        else:
            kwargs["exectype"] = bt.Order.Market
        extra_info = {"offset": offset, "signal_tag": signal_tag}
        broker_module = str(type(self.broker).__module__ or "").lower()
        is_live_btapi_broker = (
            broker_module.endswith("btapibroker") or "btapibroker" in broker_module
        )
        if is_live_btapi_broker:
            kwargs.update(extra_info)
        try:
            order = self.buy(**kwargs) if side == "buy" else self.sell(**kwargs)
        except RuntimeError as exc:
            # The Gateway-mode broker refuses, before anything is sent, an order
            # it cannot stand behind (feed not tradable, more than this strategy
            # can close, Gateway unreachable). Wait as after a rejection.
            self.log(f"{signal_tag}: {side.upper()} {symbol} refused before sending ({exc})")
            self._refusal_backoff()[str(symbol)] = time.monotonic() + float(
                self.p.reject_backoff_seconds or 0.0
            )
            return None
        if order is not None:
            if not is_live_btapi_broker:
                order.addinfo(**extra_info)
            self.pending_refs.add(order.ref)
            self.pending_orders[order.ref] = order
            self.pending_order_submitted_ticks[order.ref] = int(getattr(self, "_tick_count", 0))
            self.signal_count += 1
            self.log(
                f"submit {side.upper()} {symbol} size={quantity} offset={offset} ref={order.ref}"
            )
        return order

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: Order instance.
        """
        symbol = (
            getattr(order.data, "_name", None) or getattr(order.data, "symbol", None) or "UNKNOWN"
        )
        status_name = order.getstatusname()
        previous_status = self._last_order_status.get(order.ref)
        if previous_status == order.status:
            return
        self._last_order_status[order.ref] = order.status

        if order.info.get("restored") and order.alive() and order.ref not in self.pending_refs:
            # A working or waiting order restored by a direct-mode broker after
            # start(): track it like the orders of this run (R-6/7).
            self.pending_refs.add(order.ref)
            self.pending_orders[order.ref] = order
            self.pending_order_submitted_ticks[order.ref] = int(getattr(self, "_tick_count", 0))
            self.log(f"took over restored order {order.ref} offset={order.info.get('offset')}")

        if order.status in (order.Submitted, order.Accepted):
            self.log(f"order {order.ref} {status_name} {symbol}")
            return

        if order.status in (order.Partial, order.Completed):
            self._refresh_position(symbol)
            self.log(
                f"order {order.ref} {status_name} {symbol} "
                f"price={float(order.executed.price or 0.0):.2f} "
                f"size={float(order.executed.size or 0.0):.0f}"
            )
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            error_msg = getattr(order.info, "error_msg", "")
            suffix = f" error={error_msg}" if error_msg else ""
            self.log(f"order {order.ref} {status_name} {symbol}{suffix}")
            if order.status == order.Rejected:
                # A refusal (e.g. stale or unqualified data) usually holds for
                # the next ticks too: pause new orders for this instrument.
                self._refusal_backoff()[str(symbol)] = time.monotonic() + float(
                    self.p.reject_backoff_seconds or 0.0
                )

        if not order.alive():
            self.pending_refs.discard(order.ref)
            self.pending_orders.pop(order.ref, None)
            self.pending_order_submitted_ticks.pop(order.ref, None)
            self._refresh_position(symbol)
            self.after_terminal_order(order)

    def after_terminal_order(self, order):
        """Hook called after a terminal order (filled/canceled/rejected).

        Args:
            order: Terminal order instance.
        """

    def forced_order_mode_enabled(self):
        """Check if forced order mode is enabled.

        Returns:
            True if force entry or force exit after tick limits are set.
        """
        return (
            int(self.p.force_entry_after_ticks or 0) > 0
            or int(self.p.force_exit_after_ticks or 0) > 0
        )

    def reconcile_pending_order_states(self):
        """Reconcile all pending order states by calling notify_order."""
        for order in list(self.pending_orders.values()):
            self.notify_order(order)

    def maybe_cancel_stale_orders(self):
        """Cancel stale orders that have exceeded tick threshold.

        Returns:
            True if any orders were canceled.
        """
        cancel_after_ticks = int(self.p.cancel_pending_after_ticks or 0)
        if cancel_after_ticks <= 0:
            return False

        current_tick = int(getattr(self, "_tick_count", 0))
        canceled_any = False
        for ref in list(self.pending_refs):
            order = self.pending_orders.get(ref)
            submitted_tick = self.pending_order_submitted_ticks.get(ref)
            if order is None or submitted_tick is None:
                continue
            if current_tick - int(submitted_tick) < cancel_after_ticks:
                continue
            self.log(
                f"cancel stale order ref={ref} after {current_tick - int(submitted_tick)} ticks"
            )
            self.cancel(order)
            canceled_any = True
        return canceled_any

    def maybe_stop_after_tick_limit(self):
        """Stop strategy if tick limit is reached and no pending orders.

        Returns:
            True if strategy was stopped.
        """
        limit = int(self.p.stop_after_ticks or 0)
        if limit > 0 and self._tick_count >= limit and not self.pending_refs:
            self.log(f"tick limit reached ({limit}), stopping")
            self.cerebro.runstop()
            return True
        return False

    def stop_if_roundtrips_complete(self, target_roundtrips):
        """Stop strategy if target roundtrips reached and no pending orders.

        Args:
            target_roundtrips: Target number of completed roundtrips.

        Returns:
            True if strategy was stopped.
        """
        target = int(target_roundtrips or 0)
        if target > 0 and self.completed_roundtrips >= target and not self.pending_refs:
            self.log(f"roundtrip target reached ({target}), stopping")
            self.cerebro.runstop()
            return True
        return False

    def get_summary(self):
        """Get strategy execution summary.

        Returns:
            Dictionary with strategy statistics.
        """
        return {
            "strategy": self.__class__.__name__,
            "tick_count": int(getattr(self, "_tick_count", 0)),
            "event_count": int(getattr(self, "_event_count", 0)),
            "signals": int(self.signal_count),
            "roundtrips": int(self.completed_roundtrips),
            "positions": {key: float(value) for key, value in sorted(self.position_cache.items())},
            "pending_refs": sorted(self.pending_refs),
        }


class SingleSymbolTickStrategy(ConfigurableFuturesStrategyBase):
    """Single-symbol strategy using pure tick-level data.

    This strategy executes trades based on tick-level price movements
    with configurable entry/exit biases.
    """

    params = BASE_FUTURES_STRATEGY_PARAMS + (
        ("symbol", "rb2701"),
        ("tick_window", 4),
        ("entry_bias", 1.0),
        ("exit_bias", 0.5),
        ("order_size", 1),
        ("max_roundtrips", 1),
    )

    def __init__(self):
        """Initialize single symbol tick strategy."""
        super().__init__()
        self.prices = deque(maxlen=max(2, int(self.p.tick_window)))
        self._observed_open_position = False
        self._open_tick_at = None
        self._forced_phase = "idle"
        self._forced_entry_terminal_refs = set()
        self._forced_exit_terminal_refs = set()

    def _handle_forced_signals(self, position):
        force_entry_after_ticks = int(self.p.force_entry_after_ticks or 0)
        force_exit_after_ticks = int(self.p.force_exit_after_ticks or 0)

        if (
            self._forced_phase == "idle"
            and force_entry_after_ticks > 0
            and self._tick_count >= force_entry_after_ticks
        ):
            order = self._submit_market(
                side="buy",
                symbol=self.p.symbol,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_single_entry",
            )
            if order is not None:
                # Only a submitted order advances the phase: a skipped one
                # (refusal backoff, no valid price) is retried on a later call.
                self._forced_phase = "entry_submitted"
            return True

        if (
            self._forced_phase == "open"
            and force_exit_after_ticks > 0
            and self._open_tick_at is not None
            and self._tick_count - int(self._open_tick_at) >= force_exit_after_ticks
        ):
            order = self._submit_market(
                side="sell",
                symbol=self.p.symbol,
                size=max(abs(position), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_single_exit",
            )
            if order is not None:
                # Only a submitted order advances the phase: a skipped one
                # (refusal backoff, no valid price) is retried on a later call.
                self._forced_phase = "exit_submitted"
            return True

        return False

    def notify_tick(self, tick):
        """Handle tick data from primary feed.

        Args:
            tick: Tick data from primary feed.
        """
        if tick.symbol != self.p.symbol:
            return

        self.reconcile_pending_order_states()
        self.prices.append(float(tick.price))
        position = self._position_size(self.p.symbol)
        if position > 0:
            self._observed_open_position = True
            if self._open_tick_at is None:
                self._open_tick_at = int(self._tick_count)

        self.maybe_cancel_stale_orders()
        if self.maybe_stop_after_tick_limit():
            return
        if self.pending_refs:
            return
        if self.forced_order_mode_enabled():
            self._handle_forced_signals(position)
            return
        if len(self.prices) < int(self.p.tick_window):
            return
        if int(self.p.max_roundtrips or 0) > 0 and self.completed_roundtrips >= int(
            self.p.max_roundtrips
        ):
            return

        rolling_mean = sum(self.prices) / float(len(self.prices))
        price = float(tick.price)
        if position <= 0 and price >= rolling_mean + float(self.p.entry_bias):
            self._submit_market(
                side="buy",
                symbol=self.p.symbol,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="single_entry",
            )
        elif position > 0 and price <= rolling_mean - float(self.p.exit_bias):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol,
                size=max(abs(position), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="single_exit",
            )

    def after_terminal_order(self, order):
        """Handle terminal order completion.

        Args:
            order: Order that reached terminal state.
        """
        info = getattr(order, "info", None)
        signal_tag = (
            info.get("signal_tag", "") if hasattr(info, "get") else getattr(info, "signal_tag", "")
        )
        if self.forced_order_mode_enabled():
            if signal_tag == "forced_single_entry":
                self._forced_entry_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "idle"
                        self._forced_entry_terminal_refs.clear()
                    elif self._forced_entry_terminal_refs:
                        self._observed_open_position = True
                        self._open_tick_at = int(getattr(self, "_tick_count", 0))
                        self._forced_phase = "open"
                return

            if signal_tag == "forced_single_exit":
                self._forced_exit_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "open"
                        self._forced_exit_terminal_refs.clear()
                    elif self._forced_exit_terminal_refs:
                        self.completed_roundtrips += 1
                        self._observed_open_position = False
                        self._open_tick_at = None
                        self._forced_phase = "done"
                        self.log(f"single-symbol roundtrip completed: {self.completed_roundtrips}")
                        self.stop_if_roundtrips_complete(self.p.max_roundtrips)
                return

        position = self._position_size(self.p.symbol)
        if position > 0:
            self._observed_open_position = True
            if self._open_tick_at is None:
                self._open_tick_at = int(getattr(self, "_tick_count", 0))
            return

        if abs(position) < 1e-12 and self._observed_open_position and not self.pending_refs:
            self.completed_roundtrips += 1
            self._observed_open_position = False
            self._open_tick_at = None
            self.log(f"single-symbol roundtrip completed: {self.completed_roundtrips}")
            self.stop_if_roundtrips_complete(self.p.max_roundtrips)

    def get_summary(self):
        """Get strategy summary.

        Returns:
            dict: Summary including symbol, window size, and prices.
        """
        summary = super().get_summary()
        summary.update(
            {
                "symbol": self.p.symbol,
                "window_size": int(self.p.tick_window),
                "latest_prices": [float(price) for price in self.prices],
            }
        )
        return summary
