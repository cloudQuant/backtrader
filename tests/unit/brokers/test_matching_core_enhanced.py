from types import SimpleNamespace

import pytest

from backtrader.brokers.hft import MatchingCore, QueueExchangeModel
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


class DummyExecuted:
    def __init__(self, remsize):
        self.remsize = remsize


class DummyOrder:
    def __init__(self, name="BTC/USDT", exectype=Order.Market, price=100.0, plimit=None, size=1.0, buy=True):
        self.data = DummyData(name)
        self.exectype = exectype
        self.price = price
        self.pricelimit = plimit
        self.size = size
        self.executed = DummyExecuted(size)
        self._buy = buy
        self._stop_triggered = False

    def isbuy(self):
        return self._buy


def test_matching_core_on_tick_handles_stop_and_stoplimit():
    stop_order = DummyOrder(exectype=Order.Stop, price=101.0, size=1.0, buy=True)
    stop_limit_order = DummyOrder(exectype=Order.StopLimit, price=101.0, plimit=102.0, size=1.0, buy=True)
    core = MatchingCore()
    core.submit_order(stop_order)
    core.submit_order(stop_limit_order)

    result = core.on_tick(TickEvent(timestamp=1.0, symbol="BTC/USDT", price=101.5, volume=2.0))

    assert result.action == "FILL"
    assert len(result.fills) == 2
    assert all(fill.fill_size == pytest.approx(1.0) for fill in result.fills)


def test_matching_core_on_orderbook_uses_exchange_model_and_modify():
    core = MatchingCore(exchange_model=QueueExchangeModel())
    order = DummyOrder(exectype=Order.Limit, price=101.0, size=1.0, buy=True)
    replacement = DummyOrder(exectype=Order.Limit, price=99.0, size=1.0, buy=True)
    order.time_in_force = "GTX"
    core.submit_order(order)

    reject_result = core.on_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol="BTC/USDT",
            bids=[(100.0, 1.0)],
            asks=[(101.0, 2.0)],
        )
    )
    modify_result = core.modify_order(order, replacement, current_ts=2.0)

    assert reject_result.action == "REJECT"
    assert reject_result.reject_reason == "GTX_CROSSED"
    assert modify_result.action in {"REJECT", "MODIFIED", "CANCELED"}


def test_matching_core_on_tick_supports_maker_queue_trade_fill():
    core = MatchingCore(exchange_model=QueueExchangeModel())
    order = DummyOrder(exectype=Order.Limit, price=100.0, size=1.0, buy=True)
    core.submit_order(order)
    core.on_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol="BTC/USDT",
            bids=[(100.0, 1.0)],
            asks=[(101.0, 2.0)],
        )
    )

    result = core.on_tick(TickEvent(timestamp=2.0, symbol="BTC/USDT", price=100.0, volume=2.0))

    assert result.action == "FILL"
    assert result.fills[-1].role == "maker"
