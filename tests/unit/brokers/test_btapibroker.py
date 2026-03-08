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


def test_local_validation_rejects_invalid_tick_size():
    """Broker should reject locally invalid prices without hitting the API."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(
        api=client,
        contract_metadata={DEFAULT_SYMBOL: {"min_price_tick": 0.5}},
    )
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=100.3,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "invalid_price_tick"
        assert client.submitted_orders == []

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        assert any(
            event["event_type"] == "order_reject_local"
            and event["error_code"] == "invalid_price_tick"
            for event in events
        )
    finally:
        broker.stop()


def test_trading_controls_batch_cancel_and_force_logout():
    """Trading controls should reject new orders, cancel open ones, and disconnect cleanly."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        broker.disable_trading("risk")
        disabled_order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        assert disabled_order.status == bt.Order.Rejected

        broker.enable_trading("clear")
        order_a = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        order_b = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=99.0,
            exectype=bt.Order.Limit,
        )
        cancelled = broker.batch_cancel()
        assert [order.ref for order in cancelled] == [order_a.ref, order_b.ref]
        assert all(order.status == bt.Order.Canceled for order in cancelled)
        assert len(client.cancelled_orders) == 2

        broker.pause_strategy("manual")
        paused_order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        assert paused_order.status == bt.Order.Rejected

        broker.resume_strategy("manual")
        broker.force_logout("panic")
        assert client.connected is False
        assert store.is_connected is False

        events = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]
        assert "trading_disabled" in events
        assert "trading_enabled" in events
        assert "strategy_paused" in events
        assert "strategy_resumed" in events
        assert "force_logout_requested" in events
        assert "store_disconnected" in events
    finally:
        broker.stop()
