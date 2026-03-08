"""Unit tests for TickBroker tick and order book matching."""

import pytest

from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    """Minimal data object for TickBroker order creation."""

    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.symbol = name


class DummyImpactModel:
    """Simple impact model used for deterministic assertions."""

    def __init__(self, impact):
        self.impact = impact

    def calculate_impact(self, price, size):
        _ = (price, size)
        return self.impact


@pytest.fixture
def data():
    """Provide a reusable minimal data object."""
    return DummyData()


def test_tickbroker_market_order_matches_on_tick(data):
    """Market orders should execute against ticks and record tick source metadata."""
    broker = TickBroker(cash=1000.0)
    order = broker.buy(owner=None, data=data, size=2, price=100.0, exectype=Order.Market)

    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=101.5, volume=3.0))

    assert order.status == Order.Completed
    assert broker.pending_orders == []
    assert broker.getcash() == pytest.approx(1000.0 - (101.5 * 2))
    assert broker.order_history[-1]["source"] == "tick"
    assert broker.order_history[-1]["reference_price"] == pytest.approx(101.5)


def test_tickbroker_orderbook_partial_fill_then_complete(data):
    """Order book matching should support partial fills and preserve remaining quantity."""
    broker = TickBroker(cash=5000.0, allow_partial=True)
    order = broker.buy(owner=None, data=data, size=10, price=101.0, exectype=Order.Limit)

    first_ob = OrderBookSnapshot(
        timestamp=1.0,
        symbol=data._name,
        bids=[(99.5, 5.0), (99.0, 5.0)],
        asks=[(100.0, 4.0), (101.5, 10.0)],
    )
    broker.process_orderbook(first_ob)

    assert order.status == Order.Partial
    assert broker.pending_orders == [order]
    assert order.executed.remsize == pytest.approx(6.0)
    assert broker.getposition(data).size == pytest.approx(4.0)

    second_ob = OrderBookSnapshot(
        timestamp=2.0,
        symbol=data._name,
        bids=[(99.5, 5.0), (99.0, 5.0)],
        asks=[(100.5, 3.0), (101.0, 10.0)],
    )
    broker.process_orderbook(second_ob)

    assert order.status == Order.Completed
    assert broker.pending_orders == []
    assert broker.getposition(data).size == pytest.approx(10.0)
    assert broker.order_history[-1]["source"] == "orderbook_depth"


def test_tickbroker_orderbook_applies_market_impact(data):
    """Market impact should adjust order book execution prices when enabled."""
    broker = TickBroker(
        cash=5000.0,
        allow_partial=True,
        enable_impact=True,
        impact_model=DummyImpactModel(impact=0.25),
    )
    order = broker.buy(owner=None, data=data, size=2, price=102.0, exectype=Order.Limit)

    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol=data._name,
        bids=[(99.0, 10.0)],
        asks=[(100.0, 5.0)],
    )
    broker.process_orderbook(snapshot)

    assert order.status == Order.Completed
    assert order.executed.price == pytest.approx(100.25)
    assert broker.order_history[-1]["price"] == pytest.approx(100.25)
