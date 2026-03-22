import pytest

from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_mixbroker_uses_bar_fallback_and_cleans_pending_orders():
    data = DummyData()
    broker = MixBroker(cash=1000.0, tick_timeout=1.0, bar_fallback=True)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)

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
    assert broker.pending_orders == []
    assert broker.bar_matched_count == 1
    assert broker.order_history[-1]["source"] == "bar_fallback"
    assert broker.getposition(data).size == pytest.approx(1.0)
