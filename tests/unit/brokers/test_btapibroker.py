"""Unit tests for the unified BtApiBroker."""

import collections

import pytest
import backtrader as bt

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStoreError
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
    assert broker._orders_by_external_id == {}
    assert broker._orders_by_client_ref == {}


def test_sell_submits_sell_side_payload(started_stack):
    client, _store, data, broker = started_stack

    order = broker.sell(
        owner=None,
        data=data,
        size=1,
        price=100.5,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Accepted
    assert order.info["external_order_id"] == "btapi-1"
    assert client.submitted_orders[0]["symbol"] == DEFAULT_SYMBOL
    assert client.submitted_orders[0]["side"] == "sell"


def test_sell_accepts_close_today_offset_and_passes_it_to_store(started_stack):
    client, _store, data, broker = started_stack

    order = broker.sell(
        owner=None,
        data=data,
        size=1,
        price=100.5,
        exectype=bt.Order.Limit,
        offset="close_today",
    )

    assert order.status == bt.Order.Accepted
    assert order.info["offset"] == "close_today"
    assert client.submitted_orders[0]["offset"] == "close_today"


def test_buy_uses_store_create_order_alias_when_submit_order_is_unavailable():
    class CreateOrderOnlyClient:
        def __init__(self):
            self.connected = False
            self.created_orders = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_balance(self):
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            return []

        def create_order(self, **payload):
            self.created_orders.append(dict(payload))
            return {"order_ref": "alias-ref-1"}

    client = CreateOrderOnlyClient()
    store = make_store(
        api=client,
        historical_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
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
            price=101.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Accepted
        assert order.info["ctp_order_ref"] == "alias-ref-1"
        assert "external_order_id" not in order.info
        assert client.created_orders[0]["symbol"] == DEFAULT_SYMBOL
        assert client.created_orders[0]["price"] == pytest.approx(101.0)
    finally:
        broker.stop()


def test_ctp_style_submit_only_attaches_order_ref_until_server_id_arrives():
    class CtpStyleClient:
        def __init__(self):
            self.connected = False
            self.created_orders = []
            self.updates = collections.deque()

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_balance(self):
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            return []

        def create_order(self, **payload):
            self.created_orders.append(dict(payload))
            return {"order_ref": "ctp-ref-1"}

        def poll_broker_update(self):
            if not self.updates:
                return None
            return self.updates.popleft()

        def push_broker_update(self, update):
            self.updates.append(dict(update))

    client = CtpStyleClient()
    store = make_store(
        api=client,
        historical_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
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
            price=101.0,
            exectype=bt.Order.Limit,
        )

        assert order.info["ctp_order_ref"] == "ctp-ref-1"
        assert "external_order_id" not in order.info

        client.push_broker_update(
            {
                "kind": "order",
                "order_ref": "ctp-ref-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "accepted",
            }
        )
        broker.next()

        assert "external_order_id" not in order.info

        client.push_broker_update(
            {
                "kind": "order",
                "order_ref": "ctp-ref-1",
                "external_order_id": "sys-101",
                "data_name": DEFAULT_SYMBOL,
                "status": "partial",
                "filled": 1,
                "remaining": 0,
                "price": 101.0,
                "size": 1,
            }
        )
        broker.next()

        assert order.info["external_order_id"] == "sys-101"
    finally:
        broker.stop()


def test_buy_is_rejected_locally_when_trading_is_disabled(started_stack):
    client, _store, data, broker = started_stack

    broker.disable_trading(reason="test")

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "trading_disabled"
    assert client.submitted_orders == []


def test_buy_is_rejected_locally_when_strategy_is_paused(started_stack):
    client, _store, data, broker = started_stack

    broker.pause_strategy(reason="test")

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "strategy_paused"
    assert client.submitted_orders == []


def test_buy_submission_resumes_after_strategy_resume(started_stack):
    client, _store, data, broker = started_stack

    broker.pause_strategy(reason="test")
    paused_order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    broker.resume_strategy(reason="test")
    resumed_order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert paused_order.status == bt.Order.Rejected
    assert resumed_order.status == bt.Order.Accepted
    assert len(client.submitted_orders) == 1


def test_buy_raises_clear_error_when_broker_has_no_store(started_stack):
    _client, store, data, broker = started_stack

    broker.store = None
    try:
        with pytest.raises(ValueError, match="requires a BtApiStore instance"):
            broker.buy(
                owner=None,
                data=data,
                size=1,
                price=101.0,
                exectype=bt.Order.Limit,
            )

        order = list(broker.orders.values())[-1]
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "remote_submit_failed"
    finally:
        broker.store = store


def test_buy_raises_when_store_client_has_no_submit_api_and_marks_order_rejected():
    class NoSubmitClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_balance(self):
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            return []

    client = NoSubmitClient()
    store = make_store(
        api=client,
        historical_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        with pytest.raises(BtApiStoreError, match="does not support order submission"):
            broker.buy(
                owner=None,
                data=data,
                size=1,
                price=101.0,
                exectype=bt.Order.Limit,
            )

        order = list(broker.orders.values())[-1]
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "remote_submit_failed"
    finally:
        broker.stop()


def test_cancel_raises_when_store_client_has_no_cancel_api_and_leaves_order_alive():
    class NoCancelClient:
        def __init__(self):
            self.connected = False
            self.submitted_orders = []

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

        def get_balance(self):
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            return []

        def submit_order(self, payload):
            self.submitted_orders.append(dict(payload))
            return {"id": "alias-1"}

    client = NoCancelClient()
    store = make_store(
        api=client,
        historical_bars={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
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
            price=101.0,
            exectype=bt.Order.Limit,
        )

        with pytest.raises(BtApiStoreError, match="does not support order cancellation"):
            broker.cancel(order)

        assert order.alive() is True
        assert order.status == bt.Order.Accepted
        assert broker._orders_by_external_id == {"alias-1": order}
    finally:
        broker.stop()


def test_cancel_none_returns_none_without_remote_call(started_stack):
    client, _store, _data, broker = started_stack

    assert broker.cancel(None) is None
    assert client.cancelled_orders == []


def test_cancel_raises_clear_error_when_broker_has_no_store(started_stack):
    _client, store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    broker.store = None
    try:
        with pytest.raises(ValueError, match="requires a BtApiStore instance"):
            broker.cancel(order)
    finally:
        broker.store = store


def test_cancel_skips_non_alive_orders_without_duplicate_remote_call(started_stack):
    """Repeated cancel attempts should not re-issue remote cancel requests."""
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    broker.cancel(order)
    returned = broker.cancel(order)

    assert returned is order
    assert order.status == bt.Order.Canceled
    assert client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]


def test_cancel_preserves_local_order_state_when_remote_cancel_fails():
    """Remote cancel failures should leave the local order alive for later retry."""

    class FailingCancelClient(FakeBtApiClient):
        def cancel_order(self, order_ref, dataname=None):
            raise RuntimeError("remote cancel rejected")

    client = FailingCancelClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
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
            price=101.0,
            exectype=bt.Order.Limit,
        )

        with pytest.raises(RuntimeError, match="remote cancel rejected"):
            broker.cancel(order)

        assert order.status == bt.Order.Accepted
        assert client.cancelled_orders == []

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        event_types = [event["event_type"] for event in events]
        assert "order_cancel_request" in event_types
        assert "order_cancel_reject_remote" in event_types
        assert "order_cancel_submitted" not in event_types
    finally:
        broker.stop()


def test_cancel_wait_remote_keeps_order_alive_until_remote_cancel_confirmation():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(cancel_wait_remote=True)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )

        returned = broker.cancel(order)
        repeated = broker.cancel(order)

        assert returned is order
        assert repeated is order
        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info["cancel_requested_remote"] is True
        assert client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]
        assert broker._orders_by_external_id == {"btapi-1": order}

        client.push_broker_update(
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "canceled",
                "status_msg": "cancelled upstream",
            }
        )

        broker.next()

        assert order.status == bt.Order.Canceled
        assert broker._orders_by_external_id == {}
        assert broker._orders_by_client_ref == {}
    finally:
        broker.stop()


def test_late_trade_update_after_local_cancel_recovers_completed_order():
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
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )

        broker.cancel(order)

        assert order.status == bt.Order.Canceled
        assert client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]

        client.push_broker_update(
            {
                "kind": "trade",
                "order_ref": str(order.ref),
                "external_order_id": "server-ref-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 1,
                "price": 101.0,
                "trade_id": "trade-1",
            }
        )
        client.push_broker_update(
            {
                "kind": "order",
                "order_ref": str(order.ref),
                "external_order_id": "server-ref-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "canceled",
                "status_msg": "cancel arrived after fill",
            }
        )

        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        position = broker.positions[broker._position_key(data)]
        assert position.size == pytest.approx(1.0)
        assert broker._orders_by_external_id == {}
        assert broker._orders_by_client_ref == {}
    finally:
        broker.stop()


def test_getposition_reads_positions_from_store(started_stack):
    """Broker positions should reflect the unified store payload."""
    _client, _store, data, broker = started_stack

    position = broker.getposition(data)

    assert position.size == pytest.approx(2.0)
    assert position.price == pytest.approx(99.5)
    assert broker.getcash() == pytest.approx(1250.0)
    assert broker.getvalue() == pytest.approx(1450.0)
    assert broker.getvalue(datas=[data]) == pytest.approx(1450.0)


def test_getposition_returns_clone_by_default_and_cached_position_when_requested(started_stack):
    _client, _store, data, broker = started_stack

    cloned_position = broker.getposition(data)
    cached_position = broker.getposition(data, clone=False)

    assert cloned_position.size == pytest.approx(cached_position.size)
    assert cloned_position.price == pytest.approx(cached_position.price)
    assert cloned_position is not cached_position
    assert cached_position is broker.positions[DEFAULT_SYMBOL]


def test_getposition_returns_empty_position_for_untracked_data(started_stack):
    _client, store, _data, broker = started_stack
    other_data = store.getdata(dataname="OTHER", backfill_start=False)

    position = broker.getposition(other_data)

    assert position.size == pytest.approx(0.0)
    assert position.price == pytest.approx(0.0)


def test_get_orders_open_returns_empty_lists_when_no_local_orders_exist():
    broker = BtApiBroker(store=None)

    assert broker.get_orders_open() == []
    assert broker.get_orders_open(safe=True) == []


def test_get_orders_open_safe_returns_clones(started_stack):
    _client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    open_orders = broker.get_orders_open()
    safe_orders = broker.get_orders_open(safe=True)

    assert open_orders == [order]
    assert safe_orders[0] is not order
    assert safe_orders[0].ref == order.ref
    assert safe_orders[0].status == order.status


def test_orderstatus_supports_order_instance_and_reference_lookup(started_stack):
    _client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    assert broker.orderstatus(order) == bt.Order.Accepted
    assert broker.orderstatus(order.ref) == bt.Order.Accepted
    assert broker.orderstatus(None) is None
    assert broker.orderstatus(order.ref + 9999) is None


def test_broker_proxies_remote_open_order_queries():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
        open_orders=[
            {"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy", "price": 101.0, "size": 1.0},
            {"id": "btapi-2", "symbol": DEFAULT_SYMBOL, "side": "sell", "price": 102.0, "size": 1.0},
        ],
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        assert [item["id"] for item in broker.fetch_open_orders()] == ["btapi-1", "btapi-2"]
        assert [item["id"] for item in broker.get_open_orders()] == ["btapi-1", "btapi-2"]
        assert [item["id"] for item in broker.getopenorders()] == ["btapi-1", "btapi-2"]
    finally:
        broker.stop()


def test_broker_open_order_queries_do_not_expose_mutable_snapshot():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
        open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy", "price": 101.0}],
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        open_orders = broker.fetch_open_orders()
        alias_orders = broker.get_open_orders()
        compat_orders = broker.getopenorders()
        open_orders[0]["id"] = "mutated"
        alias_orders[0]["id"] = "mutated-alias"
        compat_orders[0]["id"] = "mutated-compat"

        assert broker.fetch_open_orders()[0]["id"] == "btapi-1"
        assert broker.get_open_orders()[0]["id"] == "btapi-1"
        assert broker.getopenorders()[0]["id"] == "btapi-1"
        assert broker._remote_open_orders_snapshot[0]["id"] == "btapi-1"
    finally:
        broker.stop()


def test_remote_order_cancel_updates_clear_cached_identifier_mappings():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )

        client.push_broker_update(
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "order_ref": "server-ref-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "canceled",
                "status_msg": "cancelled upstream",
            }
        )

        broker.next()

        assert order.status == bt.Order.Canceled
        assert broker._orders_by_external_id == {}
        assert broker._orders_by_client_ref == {}
    finally:
        broker.stop()


def test_remote_error_updates_reject_matching_live_orders():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )

        client.push_broker_update(
            {
                "kind": "error",
                "error_code": "ORDER_REJECTED",
                "error_msg": "exchange rejected the order",
                "details": {"OrderSysID": "btapi-1"},
            }
        )

        broker.next()

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "ORDER_REJECTED"
        assert order.info["error_msg"] == "exchange rejected the order"
        assert broker._orders_by_external_id == {}
        assert broker._orders_by_client_ref == {}
    finally:
        broker.stop()


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
        def __init__(self):
            self.bar_count = 0

        def next(self):
            self.bar_count += 1
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(NoOpStrategy)

    results = cerebro.run()

    assert len(results) == 1
    assert results[0].bar_count == 1
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


def test_force_refresh_queries_can_be_disabled_for_hot_read_paths():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                balance={"cash": 1000.0, "value": 1200.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
                history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
            )
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
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        force_refresh_queries=False,
    )

    data._start()
    assert data.load() is True
    broker.start()
    try:
        assert client.balance_calls == 2
        assert client.position_calls == 1

        assert broker.getcash() == pytest.approx(1000.0)
        assert broker.getvalue() == pytest.approx(1200.0)
        assert broker.getposition(data).size == pytest.approx(2.0)
        assert broker.getposition(data).price == pytest.approx(99.5)
        assert client.balance_calls == 2
        assert client.position_calls == 1

        broker._last_account_refresh = 0.0
        broker._last_positions_refresh = 0.0

        assert broker.getcash() == pytest.approx(1000.0)
        assert broker.getvalue() == pytest.approx(1200.0)
        assert broker.getposition(data).size == pytest.approx(2.0)
        assert client.balance_calls == 3
        assert client.position_calls == 2
    finally:
        broker.stop()


def test_next_throttles_remote_open_order_sync_and_seeds_snapshot_on_start():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.open_order_calls = 0

        def fetch_open_orders(self):
            self.open_order_calls += 1
            return super().fetch_open_orders()

    client = CountingClient()
    store = make_store(api=client)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        open_orders_refresh_interval=60.0,
    )

    broker.start()
    try:
        assert client.open_order_calls == 1
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-1"]

        client.open_orders = [{"id": "btapi-2", "symbol": DEFAULT_SYMBOL, "side": "sell"}]
        broker.next()
        broker.next()

        assert client.open_order_calls == 1
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-1"]

        assert [item["id"] for item in broker.fetch_open_orders()] == ["btapi-2"]
        assert [item["id"] for item in broker.get_open_orders()] == ["btapi-2"]
        assert [item["id"] for item in broker.getopenorders()] == ["btapi-2"]
        assert client.open_order_calls == 4
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-2"]

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        sync_events = [event for event in events if event["event_type"] == "open_orders_sync_completed"]
        assert sync_events
        assert sync_events[-1]["details"]["open_order_count"] == 1
        assert [item["id"] for item in sync_events[-1]["details"]["orders"]] == ["btapi-2"]
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


def test_next_falls_back_to_cached_remote_open_orders_on_sync_failure():
    class FlakyOpenOrdersClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}])
            self.fail = False

        def fetch_open_orders(self):
            if self.fail:
                raise RuntimeError("temporary open order failure")
            return super().fetch_open_orders()

    client = FlakyOpenOrdersClient()
    store = make_store(api=client)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        open_orders_refresh_interval=0.0,
    )

    broker.start()
    try:
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-1"]

        client.fail = True
        broker.next()

        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-1"]
        open_orders = broker.fetch_open_orders()
        alias_orders = broker.get_open_orders()
        compat_orders = broker.getopenorders()

        assert [item["id"] for item in open_orders] == ["btapi-1"]
        assert [item["id"] for item in alias_orders] == ["btapi-1"]
        assert [item["id"] for item in compat_orders] == ["btapi-1"]

        open_orders[0]["id"] = "mutated"
        alias_orders[0]["id"] = "mutated-alias"
        compat_orders[0]["id"] = "mutated-compat"

        assert broker._remote_open_orders_snapshot[0]["id"] == "btapi-1"
        assert broker.fetch_open_orders()[0]["id"] == "btapi-1"
        assert broker.get_open_orders()[0]["id"] == "btapi-1"
        assert broker.getopenorders()[0]["id"] == "btapi-1"

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        event_types = [event["event_type"] for event in events]
        completed_events = [event for event in events if event["event_type"] == "open_orders_sync_completed"]

        assert event_types.count("open_orders_sync_completed") >= 2
        assert "open_orders_sync_failed" not in event_types
        assert completed_events[-1]["details"]["open_order_count"] == 1
        assert [item["id"] for item in completed_events[-1]["details"]["orders"]] == ["btapi-1"]
    finally:
        broker.stop()


def test_broker_restart_rehydrates_account_positions_and_remote_open_orders():
    client = FakeBtApiClient(
        balance={"cash": 1000.0, "value": 1200.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
        open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}],
    )
    store = make_store(api=client)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        open_orders_refresh_interval=60.0,
    )

    broker.start()
    try:
        assert broker.getcash() == pytest.approx(1000.0)
        assert broker.getvalue() == pytest.approx(1200.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-1"]

        broker.stop()
        store.get_notifications()

        client.balance = {"cash": 1500.0, "value": 1700.0}
        client.positions = [{"instrument": DEFAULT_SYMBOL, "volume": 3, "price": 105.0}]
        client.open_orders = [{"id": "btapi-2", "symbol": DEFAULT_SYMBOL, "side": "sell"}]

        broker.start()

        assert broker.getcash() == pytest.approx(1500.0)
        assert broker.getvalue() == pytest.approx(1700.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(3.0)
        assert broker.positions[DEFAULT_SYMBOL].price == pytest.approx(105.0)
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-2"]

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        event_types = [event["event_type"] for event in events]

        assert "store_reconnect_success" in event_types
        assert "open_orders_sync_completed" in event_types
    finally:
        broker.stop()


def test_broker_start_tolerates_initial_open_order_sync_failure():
    class FlakyOpenOrdersClient(FakeBtApiClient):
        def fetch_open_orders(self):
            raise RuntimeError("open orders unavailable during startup")

    client = FlakyOpenOrdersClient(
        balance={"cash": 900.0, "value": 1100.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 101.0}],
    )
    store = make_store(api=client)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        open_orders_refresh_interval=60.0,
    )

    broker.start()
    try:
        assert broker.getcash() == pytest.approx(900.0)
        assert broker.getvalue() == pytest.approx(1100.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(2.0)
        assert broker.positions[DEFAULT_SYMBOL].price == pytest.approx(101.0)
        assert broker._remote_open_orders_snapshot == []

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        failed_event = next(event for event in events if event["event_type"] == "open_orders_sync_failed")

        assert failed_event["error_code"] == "RuntimeError"
        assert failed_event["details"]["open_order_count"] == 0
    finally:
        broker.stop()


def test_broker_start_is_idempotent_while_store_remains_connected():
    class CountingClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                balance={"cash": 1000.0, "value": 1200.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
                open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}],
            )
            self.balance_calls = 0
            self.position_calls = 0
            self.open_order_calls = 0

        def get_balance(self):
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
            self.position_calls += 1
            return super().get_positions()

        def fetch_open_orders(self):
            self.open_order_calls += 1
            return super().fetch_open_orders()

    client = CountingClient()
    store = make_store(api=client)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        open_orders_refresh_interval=60.0,
    )

    broker.start()
    broker.start()
    try:
        assert client.balance_calls == 2
        assert client.position_calls == 1
        assert client.open_order_calls == 1
        assert broker.getcash() == pytest.approx(1000.0)
        assert broker.getvalue() == pytest.approx(1200.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert [item["id"] for item in broker._remote_open_orders_snapshot] == ["btapi-1"]
    finally:
        broker.stop()


def test_broker_start_raises_clear_error_when_store_is_missing():
    broker = BtApiBroker(store=None)

    with pytest.raises(ValueError, match="requires a BtApiStore instance"):
        broker.start()


def test_broker_queries_return_seeded_values_before_start():
    broker = BtApiBroker(store=None, cash=321.0, value=654.0)

    assert broker.getcash() == pytest.approx(321.0)
    assert broker.getvalue() == pytest.approx(654.0)
    assert broker.getvalue(datas=[object()]) == pytest.approx(654.0)


def test_broker_getposition_returns_seeded_position_before_start():
    broker = BtApiBroker(store=None)
    data = type("SeededData", (), {"_name": DEFAULT_SYMBOL})()
    broker.positions[DEFAULT_SYMBOL] = bt.position.Position(size=2.0, price=99.5)

    position = broker.getposition(data)
    cached_position = broker.getposition(data, clone=False)

    assert position.size == pytest.approx(2.0)
    assert position.price == pytest.approx(99.5)
    assert position is not broker.positions[DEFAULT_SYMBOL]
    assert cached_position is broker.positions[DEFAULT_SYMBOL]


def test_broker_getposition_returns_empty_position_for_untracked_data_before_start():
    broker = BtApiBroker(store=None)
    data = type("UntrackedData", (), {"_name": "OTHER"})()

    position = broker.getposition(data)

    assert position.size == pytest.approx(0.0)
    assert position.price == pytest.approx(0.0)


def test_broker_open_order_queries_return_cached_snapshot_before_start():
    broker = BtApiBroker(store=None)
    broker._remote_open_orders_snapshot = [{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]

    snapshot = broker.fetch_open_orders()
    alias_snapshot = broker.get_open_orders()
    compat_snapshot = broker.getopenorders()

    assert [item["id"] for item in snapshot] == ["btapi-1"]
    assert [item["id"] for item in alias_snapshot] == ["btapi-1"]
    assert [item["id"] for item in compat_snapshot] == ["btapi-1"]
    assert snapshot is not broker._remote_open_orders_snapshot
    assert alias_snapshot is not broker._remote_open_orders_snapshot
    assert compat_snapshot is not broker._remote_open_orders_snapshot


def test_broker_open_order_queries_return_empty_list_before_start_when_snapshot_is_empty():
    broker = BtApiBroker(store=None)

    assert broker.fetch_open_orders() == []
    assert broker.get_open_orders() == []
    assert broker.getopenorders() == []


def test_broker_stop_is_silent_noop_when_store_is_missing():
    broker = BtApiBroker(store=None)
    broker._live_started = True

    broker.stop()

    assert broker._live_started is False


def test_broker_stop_is_silent_noop_when_store_is_already_disconnected():
    class DisconnectedStore:
        def __init__(self):
            self.is_connected = False
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    store = DisconnectedStore()
    broker = BtApiBroker(store=store)
    broker._live_started = True

    broker.stop()

    assert broker._live_started is False
    assert store.stop_calls == 0


def test_broker_runtime_helpers_update_local_state_without_store():
    broker = BtApiBroker(store=None)
    broker._live_started = True

    assert broker._trading_enabled is True
    assert broker._strategy_paused is False

    assert broker.data_started(object()) is None

    broker.disable_trading("risk")
    broker.pause_strategy("manual")

    assert broker._trading_enabled is False
    assert broker._strategy_paused is True

    broker.enable_trading("clear")
    broker.resume_strategy("resume")
    broker.force_logout("panic")

    assert broker._trading_enabled is True
    assert broker._strategy_paused is False
    assert broker._live_started is False


def test_get_notification_returns_none_when_queue_is_empty():
    broker = BtApiBroker(store=None)

    assert broker.get_notification() is None


def test_get_notification_returns_queued_order_clone_and_drains_queue(started_stack):
    _client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    notification = broker.get_notification()

    assert notification is not None
    assert notification is not order
    assert notification.ref == order.ref
    assert notification.status == order.status
    assert broker.get_notification() is None


def test_broker_stop_is_idempotent_and_does_not_duplicate_store_disconnect_events():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()

    broker.stop()
    broker.stop()

    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]

    assert event_types.count("store_disconnect_requested") == 1
    assert event_types.count("store_disconnected") == 1


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


def test_batch_cancel_returns_empty_summary_when_no_orders_are_open(started_stack):
    client, store, _data, broker = started_stack

    try:
        cancelled = broker.batch_cancel([])
        store.get_notifications()
        default_cancelled = broker.batch_cancel()

        assert cancelled == []
        assert default_cancelled == []
        assert client.cancelled_orders == []

        runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        matching = [event for event in runtime_events if event["event_type"] == "batch_cancel_completed"]
        assert matching
        assert matching[-1]["details"] == {
            "requested_count": 0,
            "cancelled_count": 0,
            "failure_count": 0,
            "cancelled_orders": [],
            "failed_orders": [],
        }
    finally:
        broker.stop()


def test_batch_cancel_skips_non_alive_orders_without_remote_cancel(started_stack):
    client, store, data, broker = started_stack

    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        order.cancel()
        store.get_notifications()

        cancelled = broker.batch_cancel([order])

        assert cancelled == []
        assert client.cancelled_orders == []

        runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        matching = [event for event in runtime_events if event["event_type"] == "batch_cancel_completed"]
        assert matching
        assert matching[-1]["details"]["requested_count"] == 1
        assert matching[-1]["details"]["cancelled_count"] == 0
        assert matching[-1]["details"]["failure_count"] == 0
        assert matching[-1]["details"]["failed_orders"] == []
    finally:
        broker.stop()


def test_force_logout_followed_by_stop_does_not_duplicate_store_disconnect_events():
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()

    broker.force_logout("panic")
    broker.stop()

    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]

    assert event_types.count("store_disconnect_requested") == 1
    assert event_types.count("store_disconnected") == 1


def test_force_logout_is_noop_for_disconnected_store_but_still_emits_runtime_event():
    class DisconnectedStore:
        def __init__(self):
            self.is_connected = False
            self.stop_calls = 0
            self.events = []

        def stop(self):
            self.stop_calls += 1

        def emit_runtime_event(self, event_type, **kwargs):
            self.events.append((event_type, kwargs))

    store = DisconnectedStore()
    broker = BtApiBroker(store=store)
    broker._live_started = True

    broker.force_logout("manual")

    assert broker._live_started is False
    assert store.stop_calls == 0
    assert store.events
    assert store.events[-1][0] == "force_logout_requested"
    assert store.events[-1][1]["details"]["reason"] == "manual"
    assert store.events[-1][1]["status"] == "disconnecting"


def test_remote_trade_updates_complete_orders_and_positions():
    """Broker.next should consume remote fills and advance local order/position state."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "trade_id": "trade-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "timestamp": "09:30:00",
            }
        )

        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert broker._orders_by_external_id == {}
        assert broker._orders_by_client_ref == {}

        notifications = []
        while True:
            notif = broker.get_notification()
            if notif is None:
                break
            notifications.append(notif)

        assert notifications[-1].status == bt.Order.Completed
    finally:
        broker.stop()


def test_remote_trade_updates_split_commission_when_a_fill_reverses_position():
    client = FakeBtApiClient(
        positions=[{"instrument": DEFAULT_SYMBOL, "direction": "short", "volume": 1, "price": 100.0}],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    broker.setcommission(
        commission=1.0,
        commtype=bt.CommInfoBase.COMM_FIXED,
    )
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=2,
            price=101.0,
            exectype=bt.Order.Market,
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "trade_id": "trade-reversal-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 2,
                "price": 101.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(1.0)
        assert exbit.opened == pytest.approx(1.0)
        assert exbit.closedcomm == pytest.approx(1.0)
        assert exbit.openedcomm == pytest.approx(1.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert broker.positions[DEFAULT_SYMBOL].price == pytest.approx(101.0)
    finally:
        broker.stop()
