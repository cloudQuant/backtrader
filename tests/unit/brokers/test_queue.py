import pytest

from backtrader.brokers.hft.queue import NoQueueModel, ProbQueueModel
from backtrader.events import OrderBookSnapshot, TickEvent


class DummyExecuted:
    def __init__(self, remsize):
        self.remsize = remsize


class DummyOrder:
    def __init__(self, size=1.0, price=100.0, buy=True):
        self.size = size
        self.price = price
        self.executed = DummyExecuted(size)
        self._buy = buy
        self._queue_ahead = 0.0

    def isbuy(self):
        return self._buy


def test_noqueue_model_fills_from_trade_volume():
    model = NoQueueModel()
    order = DummyOrder(size=2.0)
    trade = TickEvent(timestamp=1.0, symbol="BTC/USDT", price=100.0, volume=1.5)

    assert model.estimate_queue_position(order, None) == pytest.approx(0.0)
    assert model.update_on_trade(order, trade) == pytest.approx(1.5)


def test_prob_queue_model_estimates_queue_and_waits_until_consumed():
    model = ProbQueueModel()
    order = DummyOrder(size=3.0, price=100.0)
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(100.0, 2.0), (99.5, 3.0)],
        asks=[(100.5, 1.0)],
    )
    trade = TickEvent(timestamp=2.0, symbol="BTC/USDT", price=100.0, volume=1.0)
    second_trade = TickEvent(timestamp=3.0, symbol="BTC/USDT", price=100.0, volume=4.0)

    order._queue_ahead = model.estimate_queue_position(order, snapshot)

    assert order._queue_ahead == pytest.approx(2.0)
    assert model.update_on_trade(order, trade) == pytest.approx(0.0)
    assert order._queue_ahead == pytest.approx(1.0)
    assert model.update_on_trade(order, second_trade) == pytest.approx(3.0)
    assert order._queue_ahead == pytest.approx(0.0)
