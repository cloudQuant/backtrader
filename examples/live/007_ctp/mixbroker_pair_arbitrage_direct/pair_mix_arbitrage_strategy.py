"""PairMixArbitrageStrategy: Two-symbol arbitrage: rolling fair spread from bars, tick execution.

Self-contained: this file holds the configurable futures strategy base and
``PairMixArbitrageStrategy``, which ``run.py`` in this directory imports. The backtest example and
the live example of the same name carry identical copies of this file.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict, deque

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
            position = self.broker.getposition(data)
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

    def _limit_price(self, data, side):
        """Marketable limit price: ``slippage_ticks`` ticks through the last price.

        Tick callbacks can run while a feed is loading its next line, whose
        values are not written yet (``close[0]`` reads 0): the last written
        line is used then. Returns ``None`` when no valid last price is known.
        """
        last = None
        for ago in (0, -1):
            try:
                value = float(data.close[ago])
            except (IndexError, TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                last = value
                break
        if last is None:
            return None
        offset = float(self.p.slippage_ticks) * float(self.p.price_tick)
        price = last + offset if side == "buy" else last - offset
        return price if price > 0 else None

    def _close_plan(self, data, side, quantity):
        """Explicit close offsets for ``close_offset="auto"`` (never a fixed close_today).

        Uses the broker's closable view of the side being closed: separate
        close_yesterday / close_today orders on SHFE/INE, ``close`` elsewhere.
        Returns an empty plan when the split or the closable quantity is unknown.
        """
        reader = getattr(self.broker, "get_closable", None)
        if not callable(reader):
            return [("close", quantity)]
        view = reader(data, "short" if side == "buy" else "long")
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
        order = self.buy(**kwargs) if side == "buy" else self.sell(**kwargs)
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


class PairMixArbitrageStrategy(ConfigurableFuturesStrategyBase):
    """Pair arbitrage strategy using mixed bar+tick execution.

    This strategy monitors spread between two related futures contracts
    and executes arbitrage trades based on configurable entry/exit edges.
    """

    params = BASE_FUTURES_STRATEGY_PARAMS + (
        ("symbol_a", "rb2701"),
        ("symbol_b", "hc2701"),
        ("bar_window", 3),
        ("bar_source", "bars"),
        ("bar_seconds", 1),
        ("entry_edge", 5.0),
        ("exit_edge", 1.0),
        ("order_size", 1),
        ("max_roundtrips", 1),
        ("max_bar_history", 16),
    )

    def __init__(self):
        """Initialize pair mix arbitrage strategy."""
        super().__init__()
        self.latest_prices = {}
        self.bar_closes = defaultdict(
            lambda: deque(maxlen=max(int(self.p.max_bar_history), int(self.p.bar_window)))
        )
        self._observed_open_pair = False
        self._pair_open_tick_at = None
        self._forced_phase = "idle"
        self._forced_entry_terminal_refs = set()
        self._forced_exit_terminal_refs = set()
        self._tick_bar_state = {}

    def _use_tick_bars(self):
        return str(getattr(self.p, "bar_source", "bars") or "bars").strip().lower() == "ticks"

    def _tick_bucket_start(self, tick):
        tick_dt = getattr(tick, "datetime", None)
        if tick_dt is None:
            tick_dt = _dt.datetime.fromtimestamp(float(getattr(tick, "timestamp", 0.0) or 0.0))
        tick_dt = tick_dt.replace(microsecond=0)
        bar_seconds = max(int(getattr(self.p, "bar_seconds", 1) or 1), 1)
        second = (tick_dt.second // bar_seconds) * bar_seconds
        return tick_dt.replace(second=second)

    def _ingest_tick_bar(self, tick):
        symbol = str(tick.symbol)
        bucket_start = self._tick_bucket_start(tick)
        price = float(tick.price)
        current = self._tick_bar_state.get(symbol)
        if current is None:
            self._tick_bar_state[symbol] = {"bucket_start": bucket_start, "close": price}
            return
        if bucket_start == current["bucket_start"]:
            current["close"] = price
            return
        self.bar_closes[symbol].append(float(current["close"]))
        self._tick_bar_state[symbol] = {"bucket_start": bucket_start, "close": price}

    def notify_bar(self, bar):
        """Handle bar data from secondary feed.

        Args:
            bar: Bar data from secondary feed.
        """
        if self._use_tick_bars():
            return
        if bar.symbol not in (self.p.symbol_a, self.p.symbol_b):
            return
        self.bar_closes[bar.symbol].append(float(bar.close))

    def _pair_positions(self):
        pos_a = self._position_size(self.p.symbol_a)
        pos_b = self._position_size(self.p.symbol_b)
        return pos_a, pos_b

    def _pair_is_flat(self):
        pos_a, pos_b = self._pair_positions()
        return abs(pos_a) < 1e-12 and abs(pos_b) < 1e-12

    def _pair_is_open(self):
        pos_a, pos_b = self._pair_positions()
        return pos_a < -1e-12 and pos_b > 1e-12

    def _handle_forced_signals(self):
        force_entry_after_ticks = int(self.p.force_entry_after_ticks or 0)
        force_exit_after_ticks = int(self.p.force_exit_after_ticks or 0)

        if (
            self._forced_phase == "idle"
            and force_entry_after_ticks > 0
            and self._tick_count >= force_entry_after_ticks
            and len(self.latest_prices) >= 2
            and len(self.bar_closes[self.p.symbol_a]) >= int(self.p.bar_window)
            and len(self.bar_closes[self.p.symbol_b]) >= int(self.p.bar_window)
        ):
            order_a = self._submit_market(
                side="sell",
                symbol=self.p.symbol_a,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_mix_pair_open_short_a",
            )
            order_b = self._submit_market(
                side="buy",
                symbol=self.p.symbol_b,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_mix_pair_open_long_b",
            )
            if order_a is not None or order_b is not None:
                self._forced_phase = "entry_submitted"
            return True

        if (
            self._forced_phase == "open"
            and force_exit_after_ticks > 0
            and self._pair_open_tick_at is not None
            and self._tick_count - int(self._pair_open_tick_at) >= force_exit_after_ticks
        ):
            pos_a, pos_b = self._pair_positions()
            order_a = self._submit_market(
                side="buy",
                symbol=self.p.symbol_a,
                size=max(abs(pos_a), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_mix_pair_close_buy_a",
            )
            order_b = self._submit_market(
                side="sell",
                symbol=self.p.symbol_b,
                size=max(abs(pos_b), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_mix_pair_close_sell_b",
            )
            if order_a is not None or order_b is not None:
                self._forced_phase = "exit_submitted"
            return True

        return False

    def _fair_spread(self):
        if len(self.bar_closes[self.p.symbol_a]) < int(self.p.bar_window):
            return None
        if len(self.bar_closes[self.p.symbol_b]) < int(self.p.bar_window):
            return None

        window = int(self.p.bar_window)
        mean_a = sum(list(self.bar_closes[self.p.symbol_a])[-window:]) / float(window)
        mean_b = sum(list(self.bar_closes[self.p.symbol_b])[-window:]) / float(window)
        return mean_a - mean_b

    def notify_tick(self, tick):
        """Handle tick data from primary feed.

        Args:
            tick: Tick data from primary feed.
        """
        if tick.symbol not in (self.p.symbol_a, self.p.symbol_b):
            return

        self.latest_prices[tick.symbol] = float(tick.price)
        if self._use_tick_bars():
            self._ingest_tick_bar(tick)
        self.maybe_cancel_stale_orders()
        if self.maybe_stop_after_tick_limit():
            return
        if len(self.latest_prices) < 2:
            return

        if self._pair_is_open():
            self._observed_open_pair = True
            if self._pair_open_tick_at is None:
                self._pair_open_tick_at = int(self._tick_count)

        if self.forced_order_mode_enabled():
            if self.pending_refs:
                return
            self._handle_forced_signals()
            return

        fair_spread = self._fair_spread()
        if fair_spread is None:
            return

        if self._pair_is_open():
            self._observed_open_pair = True
        if self.pending_refs:
            return

        current_spread = self.latest_prices[self.p.symbol_a] - self.latest_prices[self.p.symbol_b]
        spread_edge = current_spread - fair_spread

        if (
            self._pair_is_flat()
            and (
                int(self.p.max_roundtrips or 0) <= 0
                or self.completed_roundtrips < int(self.p.max_roundtrips)
            )
            and spread_edge >= float(self.p.entry_edge)
        ):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol_a,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="mix_pair_open_short_a",
            )
            self._submit_market(
                side="buy",
                symbol=self.p.symbol_b,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="mix_pair_open_long_b",
            )
        elif self._pair_is_open() and spread_edge <= float(self.p.exit_edge):
            pos_a, pos_b = self._pair_positions()
            self._submit_market(
                side="buy",
                symbol=self.p.symbol_a,
                size=max(abs(pos_a), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="mix_pair_close_buy_a",
            )
            self._submit_market(
                side="sell",
                symbol=self.p.symbol_b,
                size=max(abs(pos_b), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="mix_pair_close_sell_b",
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
            if signal_tag.startswith("forced_mix_pair_open_"):
                self._forced_entry_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "idle"
                        self._forced_entry_terminal_refs.clear()
                    elif len(self._forced_entry_terminal_refs) >= 2:
                        self._observed_open_pair = True
                        self._pair_open_tick_at = int(getattr(self, "_tick_count", 0))
                        self._forced_phase = "open"
                return

            if signal_tag.startswith("forced_mix_pair_close_"):
                self._forced_exit_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "open"
                        self._forced_exit_terminal_refs.clear()
                    elif len(self._forced_exit_terminal_refs) >= 2:
                        self.completed_roundtrips += 1
                        self._observed_open_pair = False
                        self._pair_open_tick_at = None
                        self._forced_phase = "done"
                        self.log(f"mix pair roundtrip completed: {self.completed_roundtrips}")
                        self.stop_if_roundtrips_complete(self.p.max_roundtrips)
                return

        if self._pair_is_open():
            self._observed_open_pair = True
            if self._pair_open_tick_at is None:
                self._pair_open_tick_at = int(getattr(self, "_tick_count", 0))
            return

        if self._pair_is_flat() and self._observed_open_pair and not self.pending_refs:
            self.completed_roundtrips += 1
            self._observed_open_pair = False
            self._pair_open_tick_at = None
            self.log(f"mix pair roundtrip completed: {self.completed_roundtrips}")
            self.stop_if_roundtrips_complete(self.p.max_roundtrips)

    def get_summary(self):
        """Get strategy summary.

        Returns:
            dict: Summary including symbols, prices, and bar closes.
        """
        summary = super().get_summary()
        summary.update(
            {
                "symbols": [self.p.symbol_a, self.p.symbol_b],
                "latest_prices": {
                    key: float(value) for key, value in sorted(self.latest_prices.items())
                },
                "bar_closes": {
                    key: [float(item) for item in value]
                    for key, value in sorted(self.bar_closes.items())
                },
            }
        )
        return summary
