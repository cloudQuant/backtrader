import pytest

from backtrader.brokers.hft import QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_tickbroker_ioc_cancels_remainder_after_partial_fill():
    data = DummyData()
    broker = TickBroker(cash=1000.0, exchange_model=QueueExchangeModel())
    broker.setcommission(commission=0.0, name=data.name)
    order = broker.buy(owner=None, data=data, size=3, price=101.0, exectype=Order.Limit)
    order.time_in_force = "IOC"

    broker.process_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol=data._name,
            bids=[(100.0, 5.0)],
            asks=[(101.0, 1.0)],
        )
    )

    assert order.status == Order.Canceled
    assert order.executed.size == pytest.approx(1.0)
    assert order.info.cancel_reason == "IOC_REMAINDER_CANCELLED"
    assert broker.order_history[-1]["reason"] == "IOC_REMAINDER_CANCELLED"


def test_tickbroker_fok_rejects_when_liquidity_is_insufficient():
    data = DummyData()
    broker = TickBroker(cash=1000.0, exchange_model=QueueExchangeModel())
    order = broker.buy(owner=None, data=data, size=3, price=101.0, exectype=Order.Limit)
    order.time_in_force = "FOK"

    broker.process_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol=data._name,
            bids=[(100.0, 5.0)],
            asks=[(101.0, 1.0)],
        )
    )

    assert order.status == Order.Rejected
    assert order.info.reject_reason == "FOK_INSUFFICIENT"


def test_tickbroker_modify_replaces_pending_order():
    data = DummyData()
    broker = TickBroker(cash=1000.0)
    order = broker.buy(owner=None, data=data, size=1, price=99.0, exectype=Order.Limit)

    replacement = broker.modify(order, price=101.0)
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=100.0, volume=2.0))

    assert order.status == Order.Canceled
    assert order.info.cancel_reason == "MODIFY_REPLACED"
    assert replacement.status == Order.Completed
    assert replacement.info.modified_from == order.ref


def test_tickbroker_stop_and_stoplimit_paths_execute():
    data = DummyData()
    broker = TickBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=data.name)

    stop_order = broker.buy(owner=None, data=data, size=1, price=101.0, exectype=Order.Stop)
    stop_limit_order = broker.sell(
        owner=None,
        data=data,
        size=1,
        price=99.0,
        plimit=98.5,
        exectype=Order.StopLimit,
    )

    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=101.5, volume=2.0))
    broker.process_tick(TickEvent(timestamp=2.0, symbol=data._name, price=98.5, volume=2.0))

    assert stop_order.status == Order.Completed
    assert stop_limit_order.status == Order.Completed
    assert stop_order.comminfo is not None
    assert stop_limit_order.comminfo is not None


def test_tickbroker_recorder_tracks_fill_timeline():
    data = DummyData()
    broker = TickBroker(cash=1000.0)
    broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=100.0, volume=1.0))

    events = broker.recorder.snapshot()

    assert len(events) == 1
    assert events[0]["symbol"] == data._name
    assert events[0]["payload"]["status"] == "Completed"
