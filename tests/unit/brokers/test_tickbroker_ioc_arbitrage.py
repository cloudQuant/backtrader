"""Native Strategy order flags and bounded futures IOC execution."""

from types import SimpleNamespace

import pytest

from backtrader.brokers.hft import QueueExchangeModel, SimpleExchangeModel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import OrderBookSnapshot
from backtrader.order import Order


def stack(model=SimpleExchangeModel):
    data = SimpleNamespace(_name="BTC-USDT-SWAP", symbol="BTC-USDT-SWAP")
    broker = MixBroker(cash=10000, exchange_model=model() if model else None)
    broker.setcommission(commission=0, name=data._name)
    return broker, data


def book(data, timestamp=1, qty=1, asks=None, bids=None):
    return OrderBookSnapshot(
        timestamp=timestamp,
        symbol=data._name,
        bids=bids if bids is not None else [(99, qty)],
        asks=asks if asks is not None else [(100, qty)],
    )


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("model", [SimpleExchangeModel, QueueExchangeModel, None])
def test_ioc_kwarg_partial_fill_cancels_remainder_and_cannot_fill_next_book(side, model):
    broker, data = stack(model)
    order = getattr(broker, side)(
        None,
        data,
        size=0.2,
        price=101 if side == "buy" else 98,
        exectype=Order.Limit,
        time_in_force="IOC",
        reduce_only=False,
        client_order_id="native-ioc",
    )
    assert order.time_in_force == "IOC"
    assert order.info.time_in_force == "IOC"
    assert order.info.client_order_id == "native-ioc"
    broker.process_orderbook(book(data, qty=0.1))
    assert order.status == Order.Canceled
    assert abs(order.executed.size) == pytest.approx(0.1)
    assert order.info.cancel_reason == "IOC_REMAINDER_CANCELLED"
    broker.process_orderbook(book(data, timestamp=2, qty=1))
    assert abs(order.executed.size) == pytest.approx(0.1)
    assert abs(broker.getposition(data).size) == pytest.approx(0.1)
    assert order not in broker._pending_orders


@pytest.mark.parametrize("model", [SimpleExchangeModel, QueueExchangeModel, None])
def test_non_crossing_ioc_is_canceled_without_resting(model):
    broker, data = stack(model)
    order = broker.buy(None, data, size=0.2, price=98, exectype=Order.Limit, time_in_force="ioc")
    broker.process_orderbook(book(data))
    assert order.status == Order.Canceled
    assert order.executed.size == 0
    broker.process_orderbook(book(data, timestamp=2, asks=[(97, 1)], bids=[(96, 1)]))
    assert order.executed.size == 0


def test_gtc_partial_uses_remaining_quantity_when_computing_next_depth_vwap():
    broker, data = stack()
    order = broker.buy(None, data, size=0.2, price=105, exectype=Order.Limit)
    broker.process_orderbook(book(data, asks=[(100, 0.1)]))
    assert order.status == Order.Partial
    broker.process_orderbook(book(data, timestamp=2, asks=[(102, 0.05), (104, 1)]))
    assert order.status == Order.Completed
    assert order.executed.size == pytest.approx(0.2)
    assert order.executed.price == pytest.approx(101.5)
    assert [bit.price for bit in order.executed.exbits] == pytest.approx([100, 103])


def test_broker_clamps_an_erroneous_model_fill_and_ignores_late_terminal_fills():
    broker, data = stack()
    order = broker.buy(None, data, size=0.2, price=101, exectype=Order.Limit)
    broker._execute(order, 100, 1.1, book(data))
    assert order.status == Order.Completed
    assert order.executed.size == pytest.approx(0.2)
    broker._execute(order, 100, 1.1, book(data, timestamp=2))
    assert order.executed.size == pytest.approx(0.2)
    assert broker.getposition(data).size == pytest.approx(0.2)


@pytest.mark.parametrize("opening_side", ["buy", "sell"])
def test_reduce_only_oversize_close_does_not_reverse_position(opening_side):
    broker, data = stack()
    closing_side = "sell" if opening_side == "buy" else "buy"
    getattr(broker, opening_side)(
        None, data, size=0.1, price=101 if opening_side == "buy" else 98, exectype=Order.Limit
    )
    broker.process_orderbook(book(data))
    order = getattr(broker, closing_side)(
        None,
        data,
        size=0.2,
        price=98 if closing_side == "sell" else 101,
        exectype=Order.Limit,
        time_in_force="IOC",
        reduce_only=True,
    )
    broker.process_orderbook(book(data, timestamp=2))
    assert order.status == Order.Canceled
    assert order.executed.size == pytest.approx(-0.1 if closing_side == "sell" else 0.1)
    assert broker.getposition(data).size == 0
    broker.process_orderbook(book(data, timestamp=3))
    assert broker.getposition(data).size == 0


def test_reduce_only_cannot_open_a_position_or_add_to_same_direction():
    broker, data = stack()
    flat_order = broker.sell(None, data, size=0.1, price=98, exectype=Order.Limit, reduce_only=True)
    broker.process_orderbook(book(data))
    assert flat_order.status == Order.Canceled
    assert flat_order.executed.size == 0
    broker.buy(None, data, size=0.1, price=101, exectype=Order.Limit)
    broker.process_orderbook(book(data, timestamp=2))
    same_direction = broker.buy(
        None,
        data,
        size=0.1,
        price=101,
        exectype=Order.Limit,
        reduce_only=True,
    )
    broker.process_orderbook(book(data, timestamp=3))
    assert same_direction.status == Order.Canceled
    assert same_direction.executed.size == 0
    assert broker.getposition(data).size == pytest.approx(0.1)


def test_two_pending_reduce_only_orders_share_the_remaining_position():
    broker, data = stack()
    broker.buy(None, data, size=0.3, price=101, exectype=Order.Limit)
    broker.process_orderbook(book(data))
    orders = [
        broker.sell(None, data, size=0.2, price=98, exectype=Order.Limit, reduce_only=True)
        for _ in range(2)
    ]
    broker.process_orderbook(book(data, timestamp=2))
    assert [order.status for order in orders] == [Order.Completed, Order.Canceled]
    assert sum(order.executed.size for order in orders) == pytest.approx(-0.3)
    assert broker.getposition(data).size == pytest.approx(0)


@pytest.mark.parametrize("model", [SimpleExchangeModel, None])
def test_reduce_only_price_uses_only_the_depth_needed_to_close_existing_position(model):
    broker, data = stack(model)
    broker.buy(None, data, size=0.1, price=101, exectype=Order.Limit)
    broker.process_orderbook(book(data))
    order = broker.sell(
        None, data, size=0.2, price=90, exectype=Order.Limit, reduce_only=True,
    )
    broker.process_orderbook(book(data, timestamp=2, bids=[(100, 0.05), (98, 0.15)]))
    assert order.status == Order.Canceled
    assert order.executed.size == pytest.approx(-0.1)
    assert order.executed.price == pytest.approx(99)
    assert broker.getposition(data).size == 0
