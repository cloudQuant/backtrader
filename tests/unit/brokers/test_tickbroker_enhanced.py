import pytest

from backtrader.brokers.hft import ConstantLatencyModel, QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_tickbroker_delays_order_visibility_with_latency_model():
    data = DummyData()
    broker = TickBroker(cash=1000.0, latency_model=ConstantLatencyModel(order_entry_latency_ms=500))
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)

    assert broker.pending_orders == []

    broker.process_tick(TickEvent(timestamp=0.25, symbol=data._name, price=100.0, volume=1.0))
    assert order.status == Order.Submitted
    assert broker.pending_orders == []

    broker.process_tick(TickEvent(timestamp=0.75, symbol=data._name, price=101.0, volume=1.0))

    assert order.status == Order.Completed
    assert broker.pending_orders == []
    assert broker.order_history[-1]["price"] == pytest.approx(101.0)


def test_tickbroker_tracks_state_values_and_realized_pnl():
    data = DummyData()
    broker = TickBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=data.name)

    buy_order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=100.0, volume=1.0))

    sell_order = broker.sell(owner=None, data=data, size=1, price=110.0, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=2.0, symbol=data._name, price=110.0, volume=1.0))

    state = broker.state_values(data)

    assert buy_order.status == Order.Completed
    assert sell_order.status == Order.Completed
    assert broker.getcash() == pytest.approx(1010.0)
    assert broker.order_history[-1]["pnl"] == pytest.approx(10.0)
    assert state["position"] == pytest.approx(0.0)
    assert state["balance"] == pytest.approx(1010.0)
    assert state["num_trades"] == 2
    assert state["trading_volume"] == pytest.approx(2.0)
    assert state["trading_value"] == pytest.approx(210.0)
    assert state["equity"] == pytest.approx(1010.0)


def test_tickbroker_rejects_open_when_margin_is_insufficient():
    data = DummyData("FUTURES")
    broker = TickBroker(cash=100.0)
    broker.setcommission(commission=0.0, margin=1000.0, mult=1.0, leverage=1.0, name=data.name)

    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=100.0, volume=1.0))

    assert order.status == Order.Margin
    assert broker.pending_orders == []
    assert broker.getposition(data).size == pytest.approx(0.0)
    assert broker.order_history == []


def test_tickbroker_rejects_gtx_limit_order_with_queue_exchange_model():
    data = DummyData()
    broker = TickBroker(cash=1000.0, exchange_model=QueueExchangeModel())
    order = broker.buy(owner=None, data=data, size=1, price=101.0, exectype=Order.Limit)
    order.time_in_force = "GTX"

    broker.process_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol=data._name,
            bids=[(100.0, 3.0)],
            asks=[(101.0, 5.0)],
        )
    )

    assert order.status == Order.Rejected
    assert broker.pending_orders == []
    assert broker.order_history[-1]["status"] == "rejected"
    assert broker.order_history[-1]["reason"] == "GTX_CROSSED"


def test_tickbroker_fills_maker_limit_after_trade_consumes_queue():
    data = DummyData()
    broker = TickBroker(cash=1000.0, exchange_model=QueueExchangeModel())
    broker.setcommission(commission=0.0, name=data.name)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Limit)

    broker.process_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol=data._name,
            bids=[(100.0, 1.0)],
            asks=[(101.0, 5.0)],
        )
    )

    assert order.status == Order.Submitted
    assert order in broker.pending_orders

    broker.process_tick(TickEvent(timestamp=2.0, symbol=data._name, price=100.0, volume=2.0))

    assert order.status == Order.Completed
    assert broker.pending_orders == []
    assert broker.getposition(data).size == pytest.approx(1.0)
    assert broker.order_history[-1]["source"] == "maker"
