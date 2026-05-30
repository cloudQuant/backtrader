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
    """Experimental coordination broker for mid-frequency backtests."""

    max_ob_window = ParameterDescriptor(default=100, doc="Per-symbol order book window size")
    max_bar_history = ParameterDescriptor(default=200, doc="Per-symbol completed bar history size")
    default_sma_period = ParameterDescriptor(default=20, doc="Incrementally maintained SMA period")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reset_midfreq_state()

    def start(self):
        super().start()
        self._reset_midfreq_state()

    def _reset_midfreq_state(self):
        self._ob_window = collections.defaultdict(
            lambda: collections.deque(maxlen=self.get_param("max_ob_window"))
        )
        self._completed_bars = collections.defaultdict(
            lambda: collections.deque(maxlen=self.get_param("max_bar_history"))
        )
        self._bar_indicators = collections.defaultdict(dict)
        self._bar_indicator_state = collections.defaultdict(dict)
        self._context = MidFreqContext(self)

    def process_tick(self, tick_event, data=None):
        super().process_tick(tick_event, data)

    def process_orderbook(self, ob_event, data=None):
        super().process_orderbook(ob_event, data)
        self._ob_window[ob_event.symbol].append(copy.deepcopy(ob_event))

    def process_bar(self, bar_event, data=None):
        symbol = bar_event.symbol
        self._completed_bars[symbol].append(copy.deepcopy(bar_event))
        self._update_bar_indicators(symbol)

    def _update_bar_indicators(self, symbol):
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
        return self._context

    def get_ob_window(self, symbol, n=30):
        window = list(self._ob_window.get(symbol, ()))
        if n is not None:
            window = window[-n:]
        return [copy.deepcopy(snapshot) for snapshot in window]

    def get_completed_bars(self, symbol, n=20):
        bars = list(self._completed_bars.get(symbol, ()))
        if n is not None:
            bars = bars[-n:]
        return [copy.deepcopy(bar) for bar in bars]

    def get_bar_indicator(self, symbol, indicator_name):
        return self._bar_indicators.get(symbol, {}).get(indicator_name)

    def get_symbol_snapshot(self, symbol):
        return self._context.snapshot(symbol)

    def get_symbol_snapshots(self, symbols=None):
        return self._context.snapshot_all(symbols=symbols)


class MidFreqContext:
    def __init__(self, broker):
        self._broker = broker

    def get_last_tick(self, symbol):
        tick = self._broker._last_tick.get(symbol)
        return copy.deepcopy(tick) if tick is not None else None

    def get_last_orderbook(self, symbol):
        orderbook = self._broker._last_orderbook.get(symbol)
        return copy.deepcopy(orderbook) if orderbook is not None else None

    def get_last_price(self, symbol):
        tick = self._broker._last_tick.get(symbol)
        return getattr(tick, "price", None)

    def get_ob_window(self, symbol, n=30):
        return self._broker.get_ob_window(symbol, n)

    def get_ob_ratio(self, symbol, levels=10, window=30):
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
        return self._broker.get_completed_bars(symbol, n)

    def get_sma(self, symbol, period=20):
        if period == 20:
            return self._broker.get_bar_indicator(symbol, "sma_20")

        bars = self._broker.get_completed_bars(symbol, period)
        if len(bars) < period:
            return None
        return sum(bar.close for bar in bars) / float(period)

    def get_last_bar(self, symbol):
        bars = self._broker.get_completed_bars(symbol, 1)
        return bars[0] if bars else None

    def get_cash(self):
        return self._broker.getcash()

    def get_position(self, symbol):
        position = self._broker._positions.get(symbol)
        return copy.deepcopy(position) if position is not None else None

    def get_portfolio_value(self):
        return self._broker.getvalue()

    def get_symbols(self):
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
        selected_symbols = self.get_symbols() if symbols is None else sorted(set(symbols))
        return {
            "cash": self.get_cash(),
            "portfolio_value": self.get_portfolio_value(),
            "symbols": {symbol: self.snapshot(symbol) for symbol in selected_symbols},
        }
