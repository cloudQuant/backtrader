import backtrader as bt
import pytest

from backtrader.channel import DataChannel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent
from backtrader.feeds.mixed_channel import MixedChannel
from backtrader.order import Order


class MemoryChannel(DataChannel):
    def __init__(self, channel_type, symbol, events):
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = channel_type
        self._events = list(events)

    def load(self):
        for event in self._events:
            yield event


class MidFreqIntegrationStrategy(bt.Strategy):
    params = (("symbol", "BTC/USDT"),)

    def __init__(self):
        self.context_available = False
        self.completed_sides = []
        self.completed_refs = set()
        self.pending_order = None
        self._data_obj = type("Data", (), {"_name": self.p.symbol, "symbol": self.p.symbol})()

    def start(self):
        self.context_available = hasattr(self, "context")

    def notify_order(self, order):
        if order.status == order.Completed and order.ref not in self.completed_refs:
            self.completed_refs.add(order.ref)
            self.completed_sides.append("buy" if order.isbuy() else "sell")
        if not order.alive():
            self.pending_order = None

    def notify_tick(self, tick):
        if tick.symbol != self.p.symbol or self.pending_order is not None:
            return

        last_bar = self.context.get_last_bar(self.p.symbol)
        ratio = self.context.get_ob_ratio(self.p.symbol, levels=1, window=1)
        sma = self.context.get_sma(self.p.symbol, period=20)
        position = self.context.get_position(self.p.symbol)
        pos_size = position.size if position is not None else 0.0

        if last_bar is None or sma is None or ratio is None:
            return

        if pos_size <= 0.0 and ratio > 1.0 and last_bar.close > sma:
            self.pending_order = self.buy(data=self._data_obj, size=1, exectype=Order.Market)
        elif pos_size > 0.0 and ratio < 1.0 and last_bar.close < sma:
            self.pending_order = self.sell(data=self._data_obj, size=1, exectype=Order.Market)


def test_midfreq_single_symbol_channel_run_uses_context_and_tick_execution():
    symbol = "BTC/USDT"
    tick_channel = MemoryChannel(
        "tick",
        symbol,
        [
            TickEvent(timestamp=21.0, symbol=symbol, price=20.0, volume=1.0),
            TickEvent(timestamp=22.0, symbol=symbol, price=20.0, volume=1.0),
            TickEvent(timestamp=24.0, symbol=symbol, price=1.0, volume=1.0),
            TickEvent(timestamp=25.0, symbol=symbol, price=1.0, volume=1.0),
        ],
    )
    orderbook_channel = MemoryChannel(
        "orderbook",
        symbol,
        [
            OrderBookSnapshot(
                timestamp=20.1,
                symbol=symbol,
                bids=[(20.0, 5.0)],
                asks=[(21.0, 1.0)],
            ),
            OrderBookSnapshot(
                timestamp=23.1,
                symbol=symbol,
                bids=[(1.0, 1.0)],
                asks=[(2.0, 5.0)],
            ),
        ],
    )
    bars = [
        BarEvent(
            timestamp=float(close_idx),
            symbol=symbol,
            open=float(close_idx),
            high=float(close_idx) + 0.5,
            low=max(float(close_idx) - 0.5, 0.1),
            close=float(close_idx),
            volume=10.0,
        )
        for close_idx in range(1, 21)
    ]
    bars.append(
        BarEvent(
            timestamp=23.0,
            symbol=symbol,
            open=1.0,
            high=1.5,
            low=0.5,
            close=1.0,
            volume=10.0,
        )
    )

    queue = MixedChannel(
        tick_channels=[tick_channel],
        orderbook_channels=[orderbook_channel],
        bars=[bars],
        adaptive=False,
        preload_window=10.0,
    )

    cerebro = bt.Cerebro()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=symbol)
    cerebro.setbroker(broker)
    cerebro.addstrategy(MidFreqIntegrationStrategy, symbol=symbol)

    results = cerebro.run(channel=queue)
    strat = results[0]
    data_obj = type("Data", (), {"_name": symbol, "symbol": symbol})()

    assert strat.context_available is True
    assert strat.completed_sides == ["buy", "sell"]
    assert len(broker.order_history) == 2
    assert [record["source"] for record in broker.order_history] == ["tick", "tick"]
    assert broker.getposition(data_obj).size == pytest.approx(0.0)
