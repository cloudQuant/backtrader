"""Tests for HFT channel notify callbacks on bt.Strategy."""

import backtrader as bt

from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import Event
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


def _event(channel_type, data, sequence):
    return Event(
        timestamp=data.timestamp,
        sequence=sequence,
        channel_type=channel_type,
        channel_name=data.symbol,
        data=data,
    )


class NotifyOrderbookBuyStrategy(bt.Strategy):
    """Submit a market order from notify_orderbook using get_hft_data."""

    params = (("symbol", "BTC/USDT"),)

    def __init__(self):
        self.data_ref = None
        self.completed = []
        self.orderbook_seen = 0
        self.tick_seen = 0
        self.completed_inside_orderbook = 0
        self.last_orderbook_seen = None
        self.last_tick_seen = None

    def notify_order(self, order):
        if order.status == order.Completed:
            self.completed.append(order)

    def notify_orderbook(self, orderbook):
        if orderbook.symbol != self.p.symbol:
            return
        self.orderbook_seen += 1
        self.last_orderbook_seen = self.get_last_orderbook(self.p.symbol)
        self.data_ref = self.get_hft_data(self.p.symbol)
        self.completed_inside_orderbook = len(self.completed)
        self.buy(data=self.data_ref, size=1.0, exectype=Order.Market)

    def notify_tick(self, tick):
        if tick.symbol != self.p.symbol:
            return
        self.tick_seen += 1
        self.last_tick_seen = self.get_last_tick(self.p.symbol)


def test_notify_orderbook_get_hft_data_can_submit_order_and_fill_on_next_tick():
    """A notify_orderbook order uses channel data and fills on a later event."""
    symbol = "BTC/USDT"
    orderbook = OrderBookSnapshot(
        timestamp=1.0,
        symbol=symbol,
        bids=[(99.0, 10.0)],
        asks=[(101.0, 10.0)],
    )
    tick = TickEvent(timestamp=2.0, symbol=symbol, price=100.0, volume=2.0)

    cerebro = bt.Cerebro()
    broker = TickBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=symbol)
    cerebro.setbroker(broker)
    cerebro.addstrategy(NotifyOrderbookBuyStrategy, symbol=symbol)

    result = cerebro.run(
        channel=[
            _event("orderbook", orderbook, 1),
            _event("tick", tick, 2),
        ]
    )
    strategy = result[0]

    assert strategy.orderbook_seen == 1
    assert strategy.tick_seen == 1
    assert strategy.data_ref.symbol == symbol
    assert strategy.data_ref._name == symbol
    assert strategy.data_ref.name == symbol
    assert strategy.completed_inside_orderbook == 0
    assert len(strategy.completed) == 1
    assert strategy.completed[0].data is strategy.data_ref
    assert strategy.last_orderbook_seen is orderbook
    assert strategy.last_tick_seen is tick
    assert broker.getposition(strategy.data_ref).size == 1.0
    assert broker.get_last_orderbook(symbol) is orderbook
    assert broker.get_last_tick(symbol) is tick


class MultiSymbolDataRefStrategy(bt.Strategy):
    """Record per-symbol HFT data references from notify_tick."""

    def __init__(self):
        self.refs = {}

    def notify_tick(self, tick):
        self.refs[tick.symbol] = self.get_hft_data(tick.symbol)


def test_notify_tick_get_hft_data_returns_stable_per_symbol_references():
    """Each channel symbol gets a stable and distinct HFT data reference."""
    btc_tick_1 = TickEvent(timestamp=1.0, symbol="BTC/USDT", price=100.0, volume=1.0)
    eth_tick = TickEvent(timestamp=2.0, symbol="ETH/USDT", price=10.0, volume=1.0)
    btc_tick_2 = TickEvent(timestamp=3.0, symbol="BTC/USDT", price=101.0, volume=1.0)

    cerebro = bt.Cerebro()
    cerebro.setbroker(TickBroker(cash=1000.0))
    cerebro.addstrategy(MultiSymbolDataRefStrategy)

    result = cerebro.run(
        channel=[
            _event("tick", btc_tick_1, 1),
            _event("tick", eth_tick, 2),
            _event("tick", btc_tick_2, 3),
        ]
    )
    strategy = result[0]

    assert set(strategy.refs) == {"BTC/USDT", "ETH/USDT"}
    assert strategy.refs["BTC/USDT"].symbol == "BTC/USDT"
    assert strategy.refs["ETH/USDT"].symbol == "ETH/USDT"
    assert strategy.refs["BTC/USDT"] is not strategy.refs["ETH/USDT"]
    assert strategy.get_hft_data("BTC/USDT") is strategy.refs["BTC/USDT"]
    assert strategy.get_last_tick("BTC/USDT") is btc_tick_2
