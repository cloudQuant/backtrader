import pytest

from backtrader.brokers.hft.exchange import FillRole, QueueExchangeModel, SimpleExchangeModel
from backtrader.brokers.hft.queue import NoQueueModel, ProbQueueModel
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyExecuted:
    def __init__(self, remsize):
        self.remsize = remsize


class DummyOrder:
    def __init__(self, size, price, exectype, buy=True, tif="GTC"):
        self.size = size
        self.price = price
        self.exectype = exectype
        self.time_in_force = tif
        self.executed = DummyExecuted(size)
        self._buy = buy
        self._fill_role = None
        self._queue_ahead = 0.0

    def isbuy(self):
        return self._buy


def test_simple_exchange_model_matches_market_as_taker():
    model = SimpleExchangeModel()
    order = DummyOrder(size=2.0, price=0.0, exectype=Order.Market, buy=True)
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(99.0, 5.0)],
        asks=[(100.0, 1.0), (101.0, 5.0)],
    )

    result = model.on_new_order(order, snapshot)

    assert result.action == "FILL"
    assert result.fills == [(100.0, 1.0, FillRole.TAKER), (101.0, 1.0, FillRole.TAKER)]


def test_queue_exchange_model_puts_non_crossing_limit_into_queue():
    model = QueueExchangeModel(queue_model=ProbQueueModel())
    order = DummyOrder(size=2.0, price=100.0, exectype=Order.Limit, buy=True)
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(100.0, 3.0)],
        asks=[(101.0, 5.0)],
    )

    result = model.on_new_order(order, snapshot)

    assert result.action == "PENDING"
    assert order._fill_role == FillRole.MAKER
    assert order._queue_ahead == pytest.approx(3.0)


def test_queue_exchange_model_rejects_gtx_when_crossing():
    model = QueueExchangeModel(queue_model=NoQueueModel())
    order = DummyOrder(size=1.0, price=101.0, exectype=Order.Limit, buy=True, tif="GTX")
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(100.0, 3.0)],
        asks=[(101.0, 5.0)],
    )

    result = model.on_new_order(order, snapshot)

    assert result.action == "REJECT"
    assert result.reject_reason == "GTX_CROSSED"


def test_queue_exchange_model_fills_maker_after_queue_is_consumed():
    model = QueueExchangeModel(queue_model=ProbQueueModel())
    order = DummyOrder(size=2.0, price=100.0, exectype=Order.Limit, buy=True)
    order._fill_role = FillRole.MAKER
    order._queue_ahead = 1.0
    trade = TickEvent(timestamp=2.0, symbol="BTC/USDT", price=100.0, volume=2.0)

    fills = model.on_trade(trade, [order])

    assert fills == [(order, 100.0, 1.0, FillRole.MAKER)]
    assert order._queue_ahead == pytest.approx(0.0)
