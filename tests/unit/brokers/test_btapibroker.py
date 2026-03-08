"""Unit tests for the unified BtApiBroker."""

import pytest
import backtrader as bt

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


@pytest.fixture
def started_stack():
    """Create a started store, feed, and broker with one loaded bar."""
    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()

    yield client, store, data, broker

    broker.stop()


def test_buy_and_cancel_order_roundtrip(started_stack):
    """Broker should submit and cancel orders through BtApiStore."""
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Accepted
    assert order.info["external_order_id"] == "btapi-1"
    assert client.submitted_orders[0]["symbol"] == DEFAULT_SYMBOL
    assert client.submitted_orders[0]["side"] == "buy"

    broker.cancel(order)

    assert order.status == bt.Order.Canceled
    assert client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]


def test_getposition_reads_positions_from_store(started_stack):
    """Broker positions should reflect the unified store payload."""
    _client, _store, data, broker = started_stack

    position = broker.getposition(data)

    assert position.size == pytest.approx(2.0)
    assert position.price == pytest.approx(99.5)
    assert broker.getcash() == pytest.approx(1250.0)
    assert broker.getvalue() == pytest.approx(1450.0)


def test_cerebro_run_uses_broker_startingcash_for_writer_output():
    """BtApiBroker should expose startingcash during a full Cerebro run."""
    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
            ]
        },
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class NoOpStrategy(bt.Strategy):
        pass

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(NoOpStrategy)

    results = cerebro.run()

    assert len(results) == 1
    assert broker.startingcash == pytest.approx(1250.0)
    assert broker.startingvalue == pytest.approx(1450.0)
    assert client.connected is False


def test_next_throttles_live_account_queries():
    """BtApiBroker.next should not spam balance/position queries in the live loop."""

    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(balance={"cash": 1000.0, "value": 1200.0}, positions=[])
            self.balance_calls = 0
            self.position_calls = 0

        def get_balance(self):
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
            self.position_calls += 1
            return super().get_positions()

    client = CountingClient()
    store = make_store(api=client)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    broker.start()
    try:
        assert client.balance_calls == 2
        assert client.position_calls == 1

        broker.next()
        broker.next()
        broker.next()

        assert client.balance_calls == 2
        assert client.position_calls == 1

        assert broker.getcash() == pytest.approx(1000.0)
        assert broker.getvalue() == pytest.approx(1200.0)
        assert client.balance_calls == 4
    finally:
        broker.stop()


def test_next_ignores_transient_refresh_failures():
    """Transient store query failures during the live loop should keep cached state intact."""

    class FlakyClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(balance={"cash": 800.0, "value": 900.0}, positions=[])
            self.fail = False

        def get_balance(self):
            if self.fail:
                raise RuntimeError("temporary balance failure")
            return super().get_balance()

        def get_positions(self):
            if self.fail:
                raise RuntimeError("temporary positions failure")
            return super().get_positions()

    client = FlakyClient()
    store = make_store(api=client)
    broker = store.getbroker(account_refresh_interval=0.0, positions_refresh_interval=0.0)

    broker.start()
    try:
        client.fail = True
        broker.next()

        assert broker._cash == pytest.approx(800.0)
        assert broker._value == pytest.approx(900.0)
    finally:
        broker.stop()
