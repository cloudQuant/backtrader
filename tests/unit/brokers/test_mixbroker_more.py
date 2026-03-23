import pytest

from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_mixbroker_prefers_tick_over_bar_and_no_double_fill():
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=data.name)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)

    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=100.0, volume=1.0))
    broker.process_bar(
        BarEvent(
            timestamp=2.0,
            symbol=data._name,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=10.0,
        )
    )

    assert order.status == Order.Completed
    assert len(broker.order_history) == 1
    assert broker.order_history[0]["source"] == "tick"


def test_mixbroker_bar_does_not_act_as_timeout_fallback():
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Limit)

    broker.process_bar(
        BarEvent(
            timestamp=2.0,
            symbol=data._name,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=5.0,
        )
    )

    assert order.status != Order.Completed
    assert broker.pending_orders == [order]
    assert broker.order_history == []
