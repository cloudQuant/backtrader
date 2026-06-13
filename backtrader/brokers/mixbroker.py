"""Mixed-mode broker for tick-driven mid-frequency coordination.

MixBroker keeps TickBroker as the only execution path for orders while
maintaining low-frequency bar state and high-frequency order book windows
for strategy-side queries.

Example:
    Using MixBroker with Cerebro:
        cerebro = bt.Cerebro()
        cerebro.setbroker(MixBroker(cash=100000))
"""

import collections
import copy

from backtrader.brokers.tickbroker import TickBroker
from backtrader.parameters import ParameterDescriptor

from ..utils.log_message import get_logger

logger = get_logger(__name__)

__all__ = ["MixBroker", "MidFreqContext"]


class MixBroker(TickBroker):
    """Experimental coordination broker for mid-frequency backtests.

    :class:`MixBroker` extends :class:`TickBroker` to maintain additional
    mid-frequency state on top of the tick-driven execution path. In
    particular it keeps:

    * a per-symbol rolling window of recent order book snapshots
      (size controlled by :attr:`max_ob_window`),
    * a per-symbol rolling buffer of completed bars
      (size controlled by :attr:`max_bar_history`),
    * an incrementally maintained simple moving average per symbol
      (period controlled by :attr:`default_sma_period`).

    Strategies read this state through the broker's
    :class:`MidFreqContext`, which exposes deep-copied views so the
    underlying buffers are never mutated by user code.

    Attributes:
        max_ob_window: Per-symbol order book window size (deque maxlen).
        max_bar_history: Per-symbol completed bar history size (deque maxlen).
        default_sma_period: Period of the incrementally maintained SMA.
    """

    max_ob_window = ParameterDescriptor(default=100, doc="Per-symbol order book window size")
    max_bar_history = ParameterDescriptor(default=200, doc="Per-symbol completed bar history size")
    default_sma_period = ParameterDescriptor(default=20, doc="Incrementally maintained SMA period")

    def __init__(self, **kwargs):
        """Initialize the broker and its mid-frequency state containers.

        Args:
            **kwargs: Forwarded to :class:`TickBroker`'s constructor.
        """
        super().__init__(**kwargs)
        self._reset_midfreq_state()

    def start(self):
        """Reset the mid-frequency state containers when the run starts.

        The base :class:`TickBroker` is started first; this method then
        rebuilds the per-symbol order book window, completed-bar
        history, and indicator buffers.
        """
        super().start()
        self._reset_midfreq_state()

    def _reset_midfreq_state(self):
        """(Re)create the per-symbol windows, history buffers and context.

        Allocates ``_ob_window`` and ``_completed_bars`` as defaultdicts
        of bounded deques sized by ``max_ob_window`` and
        ``max_bar_history`` respectively, plus per-symbol indicator
        dicts and the :class:`MidFreqContext` used by strategies.
        """
        self._ob_window = collections.defaultdict(
            lambda: collections.deque(maxlen=self.get_param("max_ob_window"))
        )
        self._completed_bars = collections.defaultdict(
            lambda: collections.deque(maxlen=self.get_param("max_bar_history"))
        )
        self._bar_indicators: dict = collections.defaultdict(dict)
        self._bar_indicator_state: dict = collections.defaultdict(dict)
        self._context = MidFreqContext(self)

    def process_tick(self, tick_event, data=None):
        """Forward the tick to :class:`TickBroker` for execution."""
        super().process_tick(tick_event, data)

    def process_orderbook(self, ob_event, data=None):
        """Forward the order-book update and append it to the per-symbol window.

        Args:
            ob_event: The order book event to record. Its ``symbol``
                attribute selects the per-symbol window.
            data: Optional feed reference forwarded to the base class.
        """
        super().process_orderbook(ob_event, data)
        self._ob_window[ob_event.symbol].append(copy.deepcopy(ob_event))

    def process_bar(self, bar_event, data=None):
        """Record the completed bar and refresh its rolling indicators.

        Args:
            bar_event: The completed bar to record. Its ``symbol`` and
                ``close`` attributes are used for window insertion and
                indicator maintenance.
            data: Optional feed reference (unused here, kept for
                signature parity with the base class).
        """
        symbol = bar_event.symbol
        self._completed_bars[symbol].append(copy.deepcopy(bar_event))
        self._update_bar_indicators(symbol)

    def _update_bar_indicators(self, symbol):
        """Incrementally maintain the SMA indicator for ``symbol``.

        Maintains a running sum of the last ``default_sma_period``
        closing prices per symbol, with a slide-in / slide-out rule
        based on ``bar_count``. Once the buffer is full the SMA is
        written to ``_bar_indicators[symbol][f"sma_{period}"]``; if
        not, the indicator is removed (if present) so callers see
        ``None`` until the buffer is warm.

        Args:
            symbol: The per-symbol indicator key to update.
        """
        bars = self._completed_bars.get(symbol)
        if not bars:
            return

        indicators = self._bar_indicators[symbol]
        indicator_state = self._bar_indicator_state[symbol]
        sma_period = int(self.get_param("default_sma_period"))
        if sma_period <= 0:
            return

        previous_sum = float(indicator_state.get("sma_sum", 0.0))
        previous_len = int(indicator_state.get("bar_count", 0))
        current_bar = bars[-1]
        rolling_sum = previous_sum + float(current_bar.close)
        if previous_len >= sma_period and len(bars) > sma_period:
            rolling_sum -= float(bars[-(sma_period + 1)].close)
        elif len(bars) <= sma_period:
            rolling_sum = sum(float(bar.close) for bar in bars)

        indicator_state["bar_count"] = len(bars)
        indicator_state["sma_sum"] = rolling_sum

        if len(bars) >= sma_period:
            indicators[f"sma_{sma_period}"] = rolling_sum / float(sma_period)
        else:
            indicators.pop(f"sma_{sma_period}", None)

    def get_context(self):
        """Return the singleton :class:`MidFreqContext` for strategy queries."""
        return self._context

    def get_ob_window(self, symbol, n=30):
        """Return a deep-copied list of the last ``n`` order book snapshots.

        Args:
            symbol: Symbol whose window to return.
            n: Maximum number of snapshots to return. ``None`` returns
                the entire stored window. The tail is preferred when the
                window is larger than ``n``.

        Returns:
            list: Deep-copied order book snapshots (independent of the
            broker's internal state).
        """
        window = list(self._ob_window.get(symbol, ()))
        if n is not None:
            window = window[-n:]
        return [copy.deepcopy(snapshot) for snapshot in window]

    def get_completed_bars(self, symbol, n=20):
        """Return a deep-copied list of the last ``n`` completed bars.

        Args:
            symbol: Symbol whose bars to return.
            n: Maximum number of bars to return. ``None`` returns the
                full buffer.

        Returns:
            list: Deep-copied bar events.
        """
        bars = list(self._completed_bars.get(symbol, ()))
        if n is not None:
            bars = bars[-n:]
        return [copy.deepcopy(bar) for bar in bars]

    def get_bar_indicator(self, symbol, indicator_name):
        """Return the value of a maintained per-symbol bar indicator.

        Args:
            symbol: Symbol the indicator is for.
            indicator_name: Indicator key (e.g. ``"sma_20"``).

        Returns:
            float | None: The indicator value, or ``None`` if the buffer
            has not warmed up or the indicator is unknown.
        """
        return self._bar_indicators.get(symbol, {}).get(indicator_name)

    def get_symbol_snapshot(self, symbol):
        """Return a deep-copied snapshot dict for ``symbol``.

        Args:
            symbol: Symbol to snapshot.

        Returns:
            dict: Snapshot produced by :meth:`MidFreqContext.snapshot`.
        """
        return self._context.snapshot(symbol)

    def get_symbol_snapshots(self, symbols=None):
        """Return deep-copied snapshots for one, many or all symbols.

        Args:
            symbols: Iterable of symbols to snapshot. ``None`` snapshots
                every symbol currently known to the broker.

        Returns:
            dict: The structure produced by
            :meth:`MidFreqContext.snapshot_all`.
        """
        return self._context.snapshot_all(symbols=symbols)


class MidFreqContext:
    """Read-only strategy-facing view over a :class:`MixBroker`.

    Exposes a curated set of per-symbol and per-account helpers
    (last tick, last order book, completed bars, simple indicators,
    position, portfolio value, full snapshots) without leaking the
    broker's internal mutable state. Returned values are always
    deep-copied so callers cannot accidentally mutate broker state.
    """

    def __init__(self, broker):
        """Bind the context to its owning broker.

        Args:
            broker: The :class:`MixBroker` instance this context will
                query.
        """
        self._broker = broker

    def get_last_tick(self, symbol):
        """Return a deep-copied last-tick event for ``symbol``.

        Args:
            symbol: Symbol whose last tick to return.

        Returns:
            object | None: Deep-copied tick event, or ``None`` if no
            tick has been seen for ``symbol`` yet.
        """
        tick = self._broker._last_tick.get(symbol)
        return copy.deepcopy(tick) if tick is not None else None

    def get_last_orderbook(self, symbol):
        """Return a deep-copied last order-book event for ``symbol``.

        Args:
            symbol: Symbol whose last order book to return.

        Returns:
            object | None: Deep-copied order book, or ``None`` if no
            order book update has been seen for ``symbol`` yet.
        """
        orderbook = self._broker._last_orderbook.get(symbol)
        return copy.deepcopy(orderbook) if orderbook is not None else None

    def get_last_price(self, symbol):
        """Return the price of the last tick for ``symbol`` (or ``None``).

        This is a convenience that avoids forcing callers to fetch the
        full tick event just to read ``tick.price``.

        Args:
            symbol: Symbol whose last-tick price to return.

        Returns:
            float | None: Last price, or ``None`` if no tick has been
            received or the stored tick lacks a ``price`` attribute.
        """
        tick = self._broker._last_tick.get(symbol)
        return getattr(tick, "price", None)

    def get_ob_window(self, symbol, n=30):
        """Delegate to :meth:`MixBroker.get_ob_window` (alias for symmetry)."""
        return self._broker.get_ob_window(symbol, n)

    def get_ob_ratio(self, symbol, levels=10, window=30):
        """Compute the bid/ask notional ratio over the recent book window.

        For each of the last ``window`` order book snapshots, sum the
        ``price * qty`` product of the first ``levels`` bid and ask
        entries. Returns ``bid_total / ask_total`` or ``None`` if there
        are no snapshots or the ask total is effectively zero.

        Args:
            symbol: Symbol to compute the ratio for.
            levels: Maximum depth level (per side) to include.
            window: Number of recent snapshots to fold over.

        Returns:
            float | None: Bid/ask notional ratio, or ``None`` if the
            denominator is too small to be meaningful.
        """
        snapshots = self._broker.get_ob_window(symbol, window)
        if not snapshots:
            return None

        total_bid_amount = 0.0
        total_ask_amount = 0.0
        for snapshot in snapshots:
            for level, (price, qty) in enumerate(snapshot.bids or []):
                if level >= levels:
                    break
                total_bid_amount += float(price) * float(qty)
            for level, (price, qty) in enumerate(snapshot.asks or []):
                if level >= levels:
                    break
                total_ask_amount += float(price) * float(qty)

        if total_ask_amount < 1e-12:
            return None
        return total_bid_amount / total_ask_amount

    def get_completed_bars(self, symbol, n=20):
        """Delegate to :meth:`MixBroker.get_completed_bars` (alias)."""
        return self._broker.get_completed_bars(symbol, n)

    def get_sma(self, symbol, period=20):
        """Return the simple moving average of the last ``period`` closes.

        Uses the maintained ``sma_{period}`` indicator when ``period ==
        20`` (the default and most common case) and falls back to
        computing a fresh average from the completed bars otherwise.
        Returns ``None`` when fewer than ``period`` bars are available.

        Args:
            symbol: Symbol to compute the SMA for.
            period: Lookback period in completed bars.

        Returns:
            float | None: Simple moving average, or ``None`` if the
            buffer is not yet warm.
        """
        if period == 20:
            return self._broker.get_bar_indicator(symbol, "sma_20")

        bars = self._broker.get_completed_bars(symbol, period)
        if len(bars) < period:
            return None
        return sum(bar.close for bar in bars) / float(period)

    def get_last_bar(self, symbol):
        """Return the most recent completed bar for ``symbol``.

        Args:
            symbol: Symbol whose last bar to return.

        Returns:
            object | None: Deep-copied bar, or ``None`` if no bar has
            completed for ``symbol`` yet.
        """
        bars = self._broker.get_completed_bars(symbol, 1)
        return bars[0] if bars else None

    def get_cash(self):
        """Return the broker's current available cash."""
        return self._broker.getcash()

    def get_position(self, symbol):
        """Return a deep-copied position for ``symbol``.

        Args:
            symbol: Symbol whose position to fetch.

        Returns:
            object | None: Deep-copied position, or ``None`` if no
            position is currently held for ``symbol``.
        """
        position = self._broker._positions.get(symbol)
        return copy.deepcopy(position) if position is not None else None

    def get_portfolio_value(self):
        """Return the broker's total portfolio value."""
        return self._broker.getvalue()

    def get_symbols(self):
        """Return the sorted union of every symbol known to the broker.

        The set is built from the keys of the last-tick, last-orderbook
        and completed-bars buffers, plus the symbols of all open
        positions. The result is sorted alphabetically for deterministic
        iteration.

        Returns:
            list[str]: Sorted list of known symbol identifiers.
        """
        symbols = set()
        symbols.update(self._broker._last_tick.keys())
        symbols.update(self._broker._last_orderbook.keys())
        symbols.update(self._broker._completed_bars.keys())
        symbols.update(
            symbol
            for symbol, position in self._broker._positions.items()
            if getattr(position, "size", 0)
        )
        return sorted(symbols)

    def snapshot(self, symbol):
        """Return a flat per-symbol snapshot dict.

        The returned dict includes the symbol identifier, the last tick
        and order book (deep-copied), the last completed bar, the
        ``sma_20`` indicator, the bid/ask ratio, and the current
        position. All values are deep-copied so the caller cannot
        mutate the broker's state.

        Args:
            symbol: Symbol to snapshot.

        Returns:
            dict: Per-symbol snapshot as described above.
        """
        return {
            "symbol": symbol,
            "last_tick": self.get_last_tick(symbol),
            "last_orderbook": self.get_last_orderbook(symbol),
            "last_bar": self.get_last_bar(symbol),
            "sma_20": self.get_sma(symbol, 20),
            "ob_ratio": self.get_ob_ratio(symbol),
            "position": self.get_position(symbol),
        }

    def snapshot_all(self, symbols=None):
        """Return a full portfolio snapshot including cash and per-symbol state.

        Args:
            symbols: Iterable of symbols to include. ``None`` includes
                every symbol returned by :meth:`get_symbols`. The list is
                deduped and sorted for deterministic output.

        Returns:
            dict: ``{"cash": float, "portfolio_value": float,
            "symbols": {symbol: snapshot_dict}}``.
        """
        selected_symbols = self.get_symbols() if symbols is None else sorted(set(symbols))
        return {
            "cash": self.get_cash(),
            "portfolio_value": self.get_portfolio_value(),
            "symbols": {symbol: self.snapshot(symbol) for symbol in selected_symbols},
        }
