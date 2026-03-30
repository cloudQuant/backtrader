import pytest

from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_tickbroker_dual_side_positions_keep_net_view_compatible():
    data = DummyData()
    broker = TickBroker(cash=1000.0, position_mode="dual_side")
    broker.setcommission(commission=0.0, name=data.name)

    broker.buy(
        owner=None,
        data=data,
        size=2,
        price=100.0,
        exectype=Order.Market,
        position_side="long",
        offset="open",
    )
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data.symbol, price=100.0, volume=2.0))

    broker.sell(
        owner=None,
        data=data,
        size=1,
        price=100.0,
        exectype=Order.Market,
        position_side="short",
        offset="open",
    )
    broker.process_tick(TickEvent(timestamp=2.0, symbol=data.symbol, price=100.0, volume=2.0))

    close_short = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=100.0,
        exectype=Order.Market,
        position_side="short",
        offset="close",
    )
    broker.process_tick(TickEvent(timestamp=3.0, symbol=data.symbol, price=100.0, volume=2.0))

    assert broker.getposition(data).size == pytest.approx(2.0)
    assert broker.getposition(data, side="long").size == pytest.approx(2.0)
    assert broker.getposition(data, side="short").size == pytest.approx(0.0)
    assert close_short.info.position_side == "short"
    assert close_short.info.offset == "close"
    assert broker.order_history[-1]["position_side"] == "short"
    assert broker.order_history[-1]["offset"] == "close"


def test_tickbroker_net_mode_still_accepts_offset_metadata_without_orderparam_regression():
    data = DummyData()
    broker = TickBroker(cash=1000.0)
    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=100.0,
        exectype=Order.Market,
        offset="open",
    )

    broker.process_tick(TickEvent(timestamp=1.0, symbol=data.symbol, price=100.0, volume=1.0))

    assert order.status == Order.Completed
    assert order.info.offset == "open"
