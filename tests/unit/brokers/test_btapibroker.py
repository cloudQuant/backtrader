"""Unit tests for the unified BtApiBroker."""

import collections

import pytest
import backtrader as bt

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStoreError, _normalise_contract_metadata
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


class _FakeBalanceContainer:
    def __init__(self, payload):
        self.payload = payload

    def get_all_data(self):
        return self.payload


class _FakeRequestData:
    def __init__(self, payload):
        self.payload = payload

    def get_data(self):
        return self.payload


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
    """Test that sell submits sell-side payload."""
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
    """Test that sell accepts close today offset and passes it to store."""
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


def test_ctp_net_sell_against_long_infers_close_offset():
    """CTP net-mode sell against an existing long position must close, not open short."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(api=client, provider="ctp_gateway")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Accepted
        assert order.info["offset"] == "close"
        assert client.submitted_orders[0]["offset"] == "close"
    finally:
        broker.stop()


def test_ctp_net_reversal_without_explicit_split_is_rejected():
    """CTP net-mode reversal must not be silently sent as a single open/close order."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(api=client, provider="ctp_gateway")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=2,
            price=4010.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "net_reversal_requires_split"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_buy_uses_store_create_order_alias_when_submit_order_is_unavailable():
    """Test that buy uses store create_order alias when submit_order is unavailable."""

    class CreateOrderOnlyClient:
        """Client that only supports create_order (alias for submit_order)."""

        def __init__(self):
            """Initialize the client."""
            self.connected = False
            self.created_orders = []

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

        def get_balance(self):
            """Get account balance."""
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            """Get positions."""
            return []

        def create_order(self, **payload):
            """Create an order using the alias method."""
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
    """Test that CTP style submit only attaches order ref until server ID arrives."""

    class CtpStyleClient:
        """Client with CTP-style order reference handling."""

        def __init__(self):
            """Initialize the CTP-style client."""
            self.connected = False
            self.created_orders = []
            self.updates = collections.deque()

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

        def get_balance(self):
            """Get account balance."""
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            """Get positions."""
            return []

        def create_order(self, **payload):
            """Create an order with CTP-style order reference."""
            self.created_orders.append(dict(payload))
            return {"order_ref": "ctp-ref-1"}

        def poll_broker_update(self):
            """Poll for broker updates."""
            if not self.updates:
                return None
            return self.updates.popleft()

        def push_broker_update(self, update):
            """Push a broker update to the queue."""
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
    """Test that buy is rejected locally when trading is disabled."""
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
    """Test that buy is rejected locally when strategy is paused."""
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
    """Test that buy submission resumes after strategy resume."""
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
    """Test that buy raises clear error when broker has no store."""
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
    """Test that buy raises when store client has no submit API and marks order rejected."""

    class NoSubmitClient:
        """Client without submit_order API."""

        def __init__(self):
            """Initialize the no-submit client."""
            self.connected = False

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

        def get_balance(self):
            """Get account balance."""
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            """Get positions."""
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


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"status": "error", "error": "market closed"}, "market closed"),
        (
            {"status": "ok", "data": {"retcode": 10030, "comment": "Invalid filling mode"}},
            "Invalid filling mode",
        ),
        ({"success": False, "message": "broker rejected"}, "broker rejected"),
        (False, "invalid remote submit response"),
        (None, "empty remote submit response"),
        ({}, "empty remote submit response"),
        ([], "invalid remote submit response"),
        ({"comment": "queued"}, "invalid remote submit response"),
    ],
)
def test_submit_error_response_marks_order_rejected(response, message):
    """Explicit remote submit failures must not become accepted live orders."""

    class RejectingClient(FakeBtApiClient):
        def submit_order(self, payload):
            self.submitted_orders.append(dict(payload))
            return dict(response) if isinstance(response, dict) else response

    client = RejectingClient(
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

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "remote_submit_rejected"
        assert order.info["error_msg"] == message
        assert client.submitted_orders
        assert broker.get_orders_open() == []
    finally:
        broker.stop()


def test_cancel_raises_when_store_client_has_no_cancel_api_and_leaves_order_alive():
    """Test that cancel raises when store client has no cancel API and leaves order alive."""

    class NoCancelClient:
        """Client without cancel_order API."""

        def __init__(self):
            """Initialize the no-cancel client."""
            self.connected = False
            self.submitted_orders = []

        def connect(self):
            """Connect to the client."""
            self.connected = True

        def disconnect(self):
            """Disconnect from the client."""
            self.connected = False

        def get_balance(self):
            """Get account balance."""
            return {"cash": 1000.0, "value": 1200.0}

        def get_positions(self):
            """Get positions."""
            return []

        def submit_order(self, payload):
            """Submit an order."""
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
    """Test that cancel None returns None without remote call."""
    client, _store, _data, broker = started_stack

    assert broker.cancel(None) is None
    assert client.cancelled_orders == []


def test_cancel_raises_clear_error_when_broker_has_no_store(started_stack):
    """Test that cancel raises clear error when broker has no store."""
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
        """Client that fails cancel_order to test error handling."""

        def cancel_order(self, order_ref, dataname=None):
            """Cancel order that always fails."""
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


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (False, "invalid remote cancel response"),
        ({}, "empty remote cancel response"),
        ({"status": "error", "error": "already filled"}, "already filled"),
        ({"comment": "queued"}, "invalid remote cancel response"),
    ],
)
def test_cancel_preserves_local_order_state_when_remote_cancel_returns_failure_payload(
    response,
    message,
):
    """Malformed cancel responses must not locally cancel a live order."""

    class RejectingCancelClient(FakeBtApiClient):
        """Client that returns a failed or ambiguous cancel response."""

        def cancel_order(self, order_ref, dataname=None):
            """Record and return the configured cancel response."""
            self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
            return dict(response) if isinstance(response, dict) else response

    client = RejectingCancelClient(
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

        with pytest.raises(BtApiStoreError, match=message):
            broker.cancel(order)

        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert broker._orders_by_external_id == {"btapi-1": order}
        assert client.cancelled_orders == [{"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL}]

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        event_types = [event["event_type"] for event in events]
        assert "order_cancel_request" in event_types
        assert "order_cancel_reject_remote" in event_types
        assert "order_cancel_submitted" not in event_types
    finally:
        broker.stop()


def test_cancel_wait_remote_keeps_order_alive_until_remote_cancel_confirmation():
    """Test that cancel wait remote keeps order alive until remote cancel confirmation."""
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


def test_cancel_wait_remote_allows_retry_after_remote_cancel_rejection():
    """Remote cancel rejection should clear only the pending-cancel flag."""
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

        broker.cancel(order)
        assert order.info["cancel_requested_remote"] is True

        client.push_broker_update(
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "cancel_rejected",
                "status_msg": "too late to cancel",
                "error_code": "TOO_LATE",
            }
        )

        broker.next()

        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info["cancel_requested_remote"] is False
        assert order.info["cancel_reject_msg"] == "too late to cancel"
        assert broker._orders_by_external_id == {"btapi-1": order}

        broker.cancel(order)

        assert order.info["cancel_requested_remote"] is True
        assert client.cancelled_orders == [
            {"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL},
            {"order_ref": "btapi-1", "dataname": DEFAULT_SYMBOL},
        ]
    finally:
        broker.stop()


def test_late_trade_update_after_local_cancel_recovers_completed_order():
    """Test that late trade update after local cancel recovers completed order."""
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


def test_sync_positions_filters_account_positions_to_registered_data():
    """Shared account position snapshots should not leak unrelated symbols."""
    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        positions=[
            {"instrument": "BTCUSDT", "volume": 2, "price": 99.5},
            {"instrument": "ETH/USDT", "volume": 7, "price": 2500.0},
        ],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        position = broker.getposition(data)

        assert position.size == pytest.approx(2.0)
        assert position.price == pytest.approx(99.5)
        assert DEFAULT_SYMBOL in broker.positions
        assert "BTCUSDT" not in broker.positions
        assert "ETH/USDT" not in broker.positions
    finally:
        broker.stop()


def test_sync_positions_accepts_raw_okx_position_aliases():
    """Raw OKX position snapshots must hydrate broker positions correctly."""
    symbol = "BTC-USDT-SWAP"
    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        positions=[
            {
                "instId": symbol,
                "posSide": "short",
                "pos": "2",
                "avgPx": "60125.5",
                "lever": "10",
            }
        ],
        history={symbol: [make_bar(0, 60000.0, 60200.0, 59900.0, 60100.0)]},
    )
    store = make_store(api=client, provider="okx")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        position = broker.getposition(data)

        assert position.size == pytest.approx(-2.0)
        assert position.price == pytest.approx(60125.5)
        assert broker.positions[symbol].size == pytest.approx(-2.0)
    finally:
        broker.stop()


def test_sync_positions_accepts_float_string_ctp_position_direction_codes():
    """CTP numeric-string position direction codes must not flip shorts long."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        positions=[
            {
                "instrument": symbol,
                "PosiDirection": "3.0",
                "Position": "2.0",
                "Price": "4010.5",
            }
        ],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(api=client, provider="ctp_gateway")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        position = broker.getposition(data)

        assert position.size == pytest.approx(-2.0)
        assert position.price == pytest.approx(4010.5)
        assert broker.positions[symbol].size == pytest.approx(-2.0)
    finally:
        broker.stop()


def test_getposition_returns_clone_by_default_and_cached_position_when_requested(started_stack):
    """Test that getposition returns clone by default and cached position when requested."""
    _client, _store, data, broker = started_stack

    cloned_position = broker.getposition(data)
    cached_position = broker.getposition(data, clone=False)

    assert cloned_position.size == pytest.approx(cached_position.size)
    assert cloned_position.price == pytest.approx(cached_position.price)
    assert cloned_position is not cached_position
    assert cached_position is broker.positions[DEFAULT_SYMBOL]


def test_getposition_returns_empty_position_for_untracked_data(started_stack):
    """Test that getposition returns empty position for untracked data."""
    _client, store, _data, broker = started_stack
    other_data = store.getdata(dataname="OTHER", backfill_start=False)

    position = broker.getposition(other_data)

    assert position.size == pytest.approx(0.0)
    assert position.price == pytest.approx(0.0)


def test_get_orders_open_returns_empty_lists_when_no_local_orders_exist():
    """Test that get_orders_open returns empty lists when no local orders exist."""
    broker = BtApiBroker(store=None)

    assert broker.get_orders_open() == []
    assert broker.get_orders_open(safe=True) == []


def test_get_orders_open_safe_returns_clones(started_stack):
    """Test that get_orders_open safe returns clones."""
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
    """Test that orderstatus supports order instance and reference lookup."""
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
    """Test that broker proxies remote open order queries."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
        open_orders=[
            {"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy", "price": 101.0, "size": 1.0},
            {
                "id": "btapi-2",
                "symbol": DEFAULT_SYMBOL,
                "side": "sell",
                "price": 102.0,
                "size": 1.0,
            },
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
    """Test that broker open order queries do not expose mutable snapshot."""
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
    """Test that remote order cancel updates clear cached identifier mappings."""
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
    """Test that remote error updates reject matching live orders."""
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


def test_order_status_partial_with_fill_details_updates_position(started_stack):
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=2,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    client.push_broker_update(
        {
            "kind": "order",
            "external_order_id": "btapi-1",
            "data_name": DEFAULT_SYMBOL,
            "status": "partial",
            "filled": 1,
            "remaining": 1,
            "price": 101.0,
        }
    )
    broker.next()

    assert order.status == bt.Order.Partial
    assert order.executed.size == pytest.approx(1.0)
    position = broker.positions[broker._position_key(data)]
    assert position.size == pytest.approx(3.0)


def test_trade_event_after_order_status_fill_is_not_counted_twice(started_stack):
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=2,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    client.push_broker_update(
        {
            "kind": "order",
            "external_order_id": "btapi-1",
            "data_name": DEFAULT_SYMBOL,
            "status": "partial",
            "filled": 1,
            "remaining": 1,
            "price": 101.0,
        }
    )
    broker.next()

    client.push_broker_update(
        {
            "kind": "trade",
            "external_order_id": "btapi-1",
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "size": 1,
            "price": 101.0,
            "trade_id": "duplicate-status-fill",
        }
    )
    broker.next()

    assert order.status == bt.Order.Partial
    assert order.executed.size == pytest.approx(1.0)
    position = broker.positions[broker._position_key(data)]
    assert position.size == pytest.approx(3.0)
    events = [kwargs["event"] for _msg, _args, kwargs in _store.get_notifications()]
    events = [event for event in events if event["event_type"] == "trade_update_ignored"]
    assert any(event["error_code"] == "duplicate_order_status_fill" for event in events)


def test_order_status_completed_with_fill_details_completes_order(started_stack):
    client, _store, data, broker = started_stack

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
            "data_name": DEFAULT_SYMBOL,
            "status": "completed",
            "filled": 1,
            "remaining": 0,
            "price": 101.0,
        }
    )
    broker.next()

    assert order.status == bt.Order.Completed
    assert order.executed.size == pytest.approx(1.0)
    assert broker._orders_by_external_id == {}


def test_order_status_done_with_fill_details_completes_order(started_stack):
    client, _store, data, broker = started_stack

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
            "data_name": DEFAULT_SYMBOL,
            "status": "done",
            "filled": 1,
            "remaining": 0,
            "price": 101.0,
        }
    )
    broker.next()

    assert order.status == bt.Order.Completed
    assert order.executed.size == pytest.approx(1.0)


def test_order_status_with_exchange_order_id_alias_updates_local_order(started_stack):
    client, _store, data, broker = started_stack

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
            "orderId": "btapi-1",
            "data_name": DEFAULT_SYMBOL,
            "status": "filled",
            "filled": 1,
            "price": 101.0,
        }
    )
    broker.next()

    assert order.status == bt.Order.Completed
    assert order.executed.size == pytest.approx(1.0)
    position = broker.positions[broker._position_key(data)]
    assert position.size == pytest.approx(3.0)
    assert broker._orders_by_external_id == {}


def test_terminal_update_clears_all_cached_order_identifier_aliases():
    class MultiAliasClient(FakeBtApiClient):
        def submit_order(self, payload):
            self.submitted_orders.append(dict(payload))
            return {"id": "client-id-1", "order_ref": "local-ref-1"}

    client = MultiAliasClient(
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
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )

        assert broker._orders_by_external_id == {"client-id-1": order}
        assert broker._orders_by_client_ref == {"local-ref-1": order}

        client.push_broker_update(
            {
                "kind": "order",
                "OrderSysID": "exchange-sys-1",
                "order_ref": "local-ref-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "filled",
                "filled": 1,
                "price": 101.0,
            }
        )
        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert broker._orders_by_external_id == {}
        assert broker._orders_by_client_ref == {}
    finally:
        broker.stop()


def test_remote_trade_update_matches_binance_client_order_id_alias():
    """Binance-style client order ids must map fills back to the local order."""

    class BinanceClientIdOnlyClient(FakeBtApiClient):
        def submit_order(self, payload):
            self.submitted_orders.append(dict(payload))
            return {"newClientOrderId": "binance-client-1"}

    client = BinanceClientIdOnlyClient(
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

        assert broker._orders_by_client_ref == {"binance-client-1": order}

        client.push_broker_update(
            {
                "kind": "trade",
                "newClientOrderId": "binance-client-1",
                "trade_id": "fill-binance-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 1,
                "price": 101.25,
            }
        )
        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.25)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
    finally:
        broker.stop()


def test_order_status_cancelled_variant_cancels_order(started_stack):
    client, _store, data, broker = started_stack

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
            "data_name": DEFAULT_SYMBOL,
            "status": "cancelled",
        }
    )
    broker.next()

    assert order.status == bt.Order.Canceled
    assert broker._orders_by_external_id == {}


def test_order_status_partial_canceled_applies_fill_then_cancels(started_stack):
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=2,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    client.push_broker_update(
        {
            "kind": "order",
            "external_order_id": "btapi-1",
            "data_name": DEFAULT_SYMBOL,
            "status": "partial-canceled",
            "filled": 1,
            "remaining": 1,
            "price": 101.0,
        }
    )
    broker.next()

    assert order.status == bt.Order.Canceled
    assert order.executed.size == pytest.approx(1.0)
    position = broker.positions[broker._position_key(data)]
    assert position.size == pytest.approx(3.0)
    assert broker._orders_by_external_id == {}


def test_order_status_exchange_partial_cancel_alias_applies_fill_then_cancels(started_stack):
    client, _store, data, broker = started_stack

    order = broker.buy(
        owner=None,
        data=data,
        size=2,
        price=101.0,
        exectype=bt.Order.Limit,
    )

    client.push_broker_update(
        {
            "kind": "order",
            "external_order_id": "btapi-1",
            "data_name": DEFAULT_SYMBOL,
            "status": "partially_filled_canceled",
            "VolumeTraded": 1,
            "Price": 101.0,
        }
    )
    broker.next()

    assert order.status == bt.Order.Canceled
    assert order.executed.size == pytest.approx(1.0)
    position = broker.positions[broker._position_key(data)]
    assert position.size == pytest.approx(3.0)
    assert broker._orders_by_external_id == {}


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
        """Strategy that does nothing and stops after first bar."""

        def __init__(self):
            """Initialize the strategy."""
            self.bar_count = 0

        def next(self):
            """Process each bar and stop."""
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
        """Client that counts balance and position calls."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(balance={"cash": 1000.0, "value": 1200.0}, positions=[])
            self.balance_calls = 0
            self.position_calls = 0

        def get_balance(self):
            """Get balance and count the call."""
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
            """Get positions and count the call."""
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
    """Test that force refresh queries can be disabled for hot read paths."""

    class CountingClient(FakeBtApiClient):
        """Client that counts balance and position calls for testing throttling."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                balance={"cash": 1000.0, "value": 1200.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
                history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
            )
            self.balance_calls = 0
            self.position_calls = 0

        def get_balance(self):
            """Get balance and count the call."""
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
            """Get positions and count the call."""
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
    """Test that next throttles remote open order sync and seeds snapshot on start."""

    class CountingClient(FakeBtApiClient):
        """Client that counts open order fetch calls."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]
            )
            self.open_order_calls = 0

        def fetch_open_orders(self):
            """Fetch open orders and count the call."""
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
        sync_events = [
            event for event in events if event["event_type"] == "open_orders_sync_completed"
        ]
        assert sync_events
        assert sync_events[-1]["details"]["open_order_count"] == 1
        assert [item["id"] for item in sync_events[-1]["details"]["orders"]] == ["btapi-2"]
    finally:
        broker.stop()


def test_next_ignores_transient_refresh_failures():
    """Transient store query failures during the live loop should keep cached state intact."""

    class FlakyClient(FakeBtApiClient):
        """Client that can simulate transient failures."""

        def __init__(self):
            """Initialize the flaky client."""
            super().__init__(balance={"cash": 800.0, "value": 900.0}, positions=[])
            self.fail = False

        def get_balance(self):
            """Get balance or raise if fail is True."""
            if self.fail:
                raise RuntimeError("temporary balance failure")
            return super().get_balance()

        def get_positions(self):
            """Get positions or raise if fail is True."""
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
    """Test that next falls back to cached remote open orders on sync failure."""

    class FlakyOpenOrdersClient(FakeBtApiClient):
        """Client that can simulate open order fetch failures."""

        def __init__(self):
            """Initialize the flaky open orders client."""
            super().__init__(
                open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}]
            )
            self.fail = False

        def fetch_open_orders(self):
            """Fetch open orders or raise if fail is True."""
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
        completed_events = [
            event for event in events if event["event_type"] == "open_orders_sync_completed"
        ]

        assert event_types.count("open_orders_sync_completed") >= 2
        assert "open_orders_sync_failed" not in event_types
        assert completed_events[-1]["details"]["open_order_count"] == 1
        assert [item["id"] for item in completed_events[-1]["details"]["orders"]] == ["btapi-1"]
    finally:
        broker.stop()


def test_broker_restart_rehydrates_account_positions_and_remote_open_orders():
    """Test that broker restart rehydrates account positions and remote open orders."""
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
    """Test that broker start tolerates initial open order sync failure."""

    class FlakyOpenOrdersClient(FakeBtApiClient):
        """Client that fails to fetch open orders for testing startup tolerance."""

        def fetch_open_orders(self):
            """Fetch open orders that always fails."""
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
        failed_event = next(
            event for event in events if event["event_type"] == "open_orders_sync_failed"
        )

        assert failed_event["error_code"] == "RuntimeError"
        assert failed_event["details"]["open_order_count"] == 0
    finally:
        broker.stop()


def test_broker_start_is_idempotent_while_store_remains_connected():
    """Test that broker start is idempotent while store remains connected."""

    class CountingClient(FakeBtApiClient):
        """Client that counts API calls for testing idempotency."""

        def __init__(self):
            """Initialize the counting client."""
            super().__init__(
                balance={"cash": 1000.0, "value": 1200.0},
                positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "price": 100.0}],
                open_orders=[{"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}],
            )
            self.balance_calls = 0
            self.position_calls = 0
            self.open_order_calls = 0

        def get_balance(self):
            """Get balance and count the call."""
            self.balance_calls += 1
            return super().get_balance()

        def get_positions(self):
            """Get positions and count the call."""
            self.position_calls += 1
            return super().get_positions()

        def fetch_open_orders(self):
            """Fetch open orders and count the call."""
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
    """Test that broker start raises clear error when store is missing."""
    broker = BtApiBroker(store=None)

    with pytest.raises(ValueError, match="requires a BtApiStore instance"):
        broker.start()


def test_broker_queries_return_seeded_values_before_start():
    """Test that broker queries return seeded values before start."""
    broker = BtApiBroker(store=None, cash=321.0, value=654.0)

    assert broker.getcash() == pytest.approx(321.0)
    assert broker.getvalue() == pytest.approx(654.0)
    assert broker.getvalue(datas=[object()]) == pytest.approx(654.0)


def test_broker_getposition_returns_seeded_position_before_start():
    """Test that broker getposition returns seeded position before start."""
    broker = BtApiBroker(store=None)
    data = type("SeededData", (), {"_name": DEFAULT_SYMBOL})()
    broker.positions[DEFAULT_SYMBOL] = bt.position.Position(size=2.0, price=99.5)

    position = broker.getposition(data)
    cached_position = broker.getposition(data, clone=False)

    assert position.size == pytest.approx(2.0)
    assert position.price == pytest.approx(99.5)
    assert position is not broker.positions[DEFAULT_SYMBOL]
    assert cached_position is broker.positions[DEFAULT_SYMBOL]


def test_contract_metadata_auto_materializes_futures_comminfo():
    """Live broker should derive futures multiplier and fee rate from metadata."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "IF2506": {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
                "close_fee_rate": 0.00003,
                "close_today_fee_rate": 0.000345,
                "close_yesterday_fee_rate": 0.000032,
            }
        },
    )
    data = type("FuturesData", (), {"_name": "CFFEX.IF2506"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesPercent)
    assert comminfo.get_param("mult") == pytest.approx(300.0)
    assert comminfo.get_margin(4000.0) == pytest.approx(144000.0)
    assert comminfo.getcommission(1, 4000.0) == pytest.approx(27.6)
    assert comminfo.getcommission(1, 4000.0, role="open") == pytest.approx(27.6)
    assert comminfo.getcommission(1, 4000.0, role="close") == pytest.approx(36.0)
    assert comminfo.getcommission(1, 4000.0, role="close_today") == pytest.approx(414.0)
    assert comminfo.getcommission(1, 4000.0, role="close_yesterday") == pytest.approx(38.4)


def test_broker_start_warms_comminfo_for_seeded_positions_from_store_metadata_alias():
    """Existing live positions need contract rules before the first new order."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        contract_metadata={
            "CFFEX.IF2506": {
                "symbol": symbol,
                "exchange_id": "CFFEX",
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
                "close_today_fee_rate": 0.000345,
            }
        },
    )
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    broker.start()
    try:
        comminfo = broker.comminfo[symbol]

        assert isinstance(comminfo, bt.ComminfoFuturesPercent)
        assert comminfo.get_param("mult") == pytest.approx(300.0)
        assert comminfo.get_margin(4000.0) == pytest.approx(144000.0)
        assert comminfo.getcommission(1, 4000.0, role="close_today") == pytest.approx(414.0)
    finally:
        broker.stop()


def test_contract_metadata_auto_materializes_maker_taker_rates():
    """Live broker should carry exchange maker/taker fee rates into comminfo."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "BTC-USDT-SWAP": {
                "contract_size": 0.01,
                "taker_commission_rate": 0.00045,
                "maker_commission_rate": -0.0001,
            }
        },
    )
    data = type("SwapData", (), {"_name": "BTC-USDT-SWAP"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesPercent)
    assert comminfo.get_param("mult") == pytest.approx(0.01)
    assert comminfo.getcommission(2, 60000.0) == pytest.approx(0.54)
    assert comminfo.getcommission(2, 60000.0, role="taker") == pytest.approx(0.54)
    assert comminfo.getcommission(2, 60000.0, role="maker") == pytest.approx(-0.12)


def test_contract_metadata_auto_materializes_inverse_comminfo():
    """Inverse contract metadata must use fixed contract value, not price * value."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "BTC-USD-SWAP": {
                "ctType": "inverse",
                "ctVal": 100,
                "ctMult": 1,
                "ctValCcy": "USD",
                "baseCcy": "BTC",
                "quoteCcy": "USD",
                "settleCcy": "BTC",
                "margin_rate": 0.1,
                "taker_commission_rate": 0.0005,
                "maker_commission_rate": -0.0001,
            }
        },
    )
    data = type("SwapData", (), {"_name": "BTC-USD-SWAP"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesInverse)
    assert comminfo.get_param("mult") == pytest.approx(100.0)
    assert comminfo.get_margin(50000.0) == pytest.approx(10.0)
    assert comminfo.getoperationcost(100, 50000.0) == pytest.approx(1000.0)
    assert comminfo.getcommission(100, 50000.0) == pytest.approx(5.0)
    assert comminfo.getcommission(100, 50000.0, role="maker") == pytest.approx(-1.0)
    assert comminfo.profitandloss(100, 50000.0, 55000.0) == pytest.approx(1000.0)


def test_contract_metadata_auto_materializes_fixed_per_lot_comminfo():
    """Fixed per-lot exchange fees must not be treated as percent fees."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "rb2601": {
                "contract_multiplier": 10,
                "margin_rate": 0.1,
                "commission_amount": 3.5,
                "close_fee_amount": 2.0,
                "close_today_fee_amount": 4.5,
                "close_yesterday_fee_amount": 2.5,
            }
        },
    )
    data = type("FuturesData", (), {"_name": "rb2601"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesFixed)
    assert comminfo.get_param("mult") == pytest.approx(10.0)
    assert comminfo.get_margin(3000.0) == pytest.approx(3000.0)
    assert comminfo.getcommission(2, 3000.0) == pytest.approx(7.0)
    assert comminfo.getcommission(2, 3000.0, role="close") == pytest.approx(4.0)
    assert comminfo.getcommission(2, 3000.0, role="close_today") == pytest.approx(9.0)
    assert comminfo.getcommission(2, 3000.0, role="close_yesterday") == pytest.approx(5.0)


def test_contract_metadata_auto_materializes_mixed_futures_comminfo():
    """Exchange metadata may contain both by-money and by-volume fee components."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "IF2506": {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
                "open_fee_amount": 1.2,
                "close_fee_rate": 0.00003,
                "close_fee_amount": 2.0,
                "close_today_fee_rate": 0.000345,
                "close_today_fee_amount": 4.5,
                "close_yesterday_fee_rate": 0.000032,
                "close_yesterday_fee_amount": 2.5,
            }
        },
    )
    data = type("FuturesData", (), {"_name": "CFFEX.IF2506"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesMixed)
    assert comminfo.get_param("mult") == pytest.approx(300.0)
    assert comminfo.get_margin(4000.0) == pytest.approx(144000.0)
    assert comminfo.getcommission(1, 4000.0, role="open") == pytest.approx(28.8)
    assert comminfo.getcommission(1, 4000.0, role="close") == pytest.approx(38.0)
    assert comminfo.getcommission(1, 4000.0, role="close_today") == pytest.approx(418.5)
    assert comminfo.getcommission(1, 4000.0, role="close_yesterday") == pytest.approx(40.9)


def test_contract_metadata_normalizes_ctp_percent_10k_commission_rate():
    """CTP OpenRatioByMoney may arrive as '0.23 per 10k', not 23%."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "IF2506": {
                "multiplier": 300,
                "margin_rate": 0.12,
                "OpenRatioByMoney": 0.23,
                "CloseYesterdayRatioByMoney": 0.23,
            }
        },
    )
    data = type("FuturesData", (), {"_name": "CFFEX.IF2506"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesPercent)
    assert comminfo.getcommission(1, 4000.0, role="open") == pytest.approx(27.6)
    assert comminfo.getcommission(1, 4000.0, role="close_yesterday") == pytest.approx(27.6)


def test_contract_metadata_uses_max_leverage_for_margin_rate():
    """Exchange max_leverage metadata should derive live broker margin rate."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "BTC-USDT-SWAP": {
                "contract_size": 0.01,
                "max_leverage": "20",
                "taker_commission_rate": 0.00045,
            }
        },
    )
    data = type("SwapData", (), {"_name": "BTC-USDT-SWAP"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesPercent)
    assert comminfo.get_param("mult") == pytest.approx(0.01)
    assert comminfo.get_margin(60000.0) == pytest.approx(30.0)


def test_store_contract_metadata_falls_back_to_exchange_info_payload():
    """Direct live stores must use exchange instrument APIs when symbol-info is absent."""

    class ExchangeInfoOnlyClient(FakeBtApiClient):
        def __init__(self):
            super().__init__()
            self.info_calls = []
            self.fee_calls = []

        def get_exchange_info(self, symbol=None):
            self.info_calls.append(symbol)
            return _FakeRequestData(
                {
                    "retCode": 0,
                    "result": {
                        "category": "linear",
                        "list": [
                            {"symbol": "ETHUSDT", "priceFilter": {"tickSize": "0.01"}},
                            {
                                "symbol": "BTCUSDT",
                                "contractType": "LinearPerpetual",
                                "baseCoin": "BTC",
                                "quoteCoin": "USDT",
                                "settleCoin": "USDT",
                                "priceFilter": {"tickSize": "0.10"},
                                "lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.001"},
                                "leverageFilter": {"maxLeverage": "50"},
                            },
                        ],
                    },
                }
            )

        def get_fee(self, symbol):
            self.fee_calls.append(symbol)
            if symbol != "BTCUSDT":
                raise ValueError("unknown symbol")
            return {
                "makerCommissionRate": "0.0002",
                "takerCommissionRate": "0.0006",
            }

    client = ExchangeInfoOnlyClient()
    store = make_store(api=client)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)
    data = type("SwapData", (), {"_name": "BTCUSDT"})()

    comminfo = broker.getcommissioninfo(data)

    assert client.info_calls[0] == "BTCUSDT"
    assert client.fee_calls[0] == "BTCUSDT"
    assert store.contract_metadata["BTCUSDT"]["source"] == "get_exchange_info"
    assert isinstance(comminfo, bt.ComminfoFuturesPercent)
    assert comminfo.get_param("mult") == pytest.approx(1.0)
    assert comminfo.get_margin(60000.0) == pytest.approx(1200.0)
    assert comminfo.getcommission(0.5, 60000.0) == pytest.approx(18.0)
    assert comminfo.getcommission(0.5, 60000.0, role="maker") == pytest.approx(6.0)


def test_contract_metadata_normalizes_okx_raw_fee_signs_without_touching_plain_rates():
    """OKX raw fee signs are opposite to internal commission signs."""
    okx_metadata = _normalise_contract_metadata(
        {
            "instType": "SWAP",
            "maker": "-0.0002",
            "taker": "-0.0005",
            "makerU": "0.00018",
            "takerU": "-0.00045",
        },
        "BTC-USDT-SWAP",
        source="okx_get_fee",
    )

    assert okx_metadata["maker_commission_rate"] == pytest.approx(-0.00018)
    assert okx_metadata["taker_commission_rate"] == pytest.approx(0.00045)
    assert okx_metadata["commission_rate"] == pytest.approx(0.00045)
    assert okx_metadata["open_commission_rate"] == pytest.approx(0.00045)

    plain_metadata = _normalise_contract_metadata(
        {"maker": "0.0002", "taker": "0.0006"},
        "BTCUSDT",
        source="get_fee",
    )

    assert plain_metadata["maker_commission_rate"] == pytest.approx(0.0002)
    assert plain_metadata["taker_commission_rate"] == pytest.approx(0.0006)


def test_contract_metadata_auto_materializes_fixed_margin_amount():
    """MT5-style per-lot initial margin must not be treated as a margin rate."""
    broker = BtApiBroker(
        store=None,
        contract_metadata={
            "XAUUSD": {
                "contract_size": 100,
                "margin_initial": 1950.0,
            }
        },
    )
    data = type("Mt5Data", (), {"_name": "XAUUSD"})()

    comminfo = broker.getcommissioninfo(data)

    assert isinstance(comminfo, bt.ComminfoFuturesPercent)
    assert comminfo.get_param("mult") == pytest.approx(100.0)
    assert comminfo.get_param("margin_amount") == pytest.approx(1950.0)
    assert comminfo.get_margin(2331.0) == pytest.approx(1950.0)
    assert comminfo.get_margin(2500.0) == pytest.approx(1950.0)


def test_broker_getposition_returns_empty_position_for_untracked_data_before_start():
    """Test that broker getposition returns empty position for untracked data before start."""
    broker = BtApiBroker(store=None)
    data = type("UntrackedData", (), {"_name": "OTHER"})()

    position = broker.getposition(data)

    assert position.size == pytest.approx(0.0)
    assert position.price == pytest.approx(0.0)


def test_broker_open_order_queries_return_cached_snapshot_before_start():
    """Test that broker open order queries return cached snapshot before start."""
    broker = BtApiBroker(store=None)
    broker._remote_open_orders_snapshot = [
        {"id": "btapi-1", "symbol": DEFAULT_SYMBOL, "side": "buy"}
    ]

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
    """Test that broker open order queries return empty list before start when snapshot is empty."""
    broker = BtApiBroker(store=None)

    assert broker.fetch_open_orders() == []
    assert broker.get_open_orders() == []
    assert broker.getopenorders() == []


def test_broker_stop_is_silent_noop_when_store_is_missing():
    """Test that broker stop is silent noop when store is missing."""
    broker = BtApiBroker(store=None)
    broker._live_started = True

    broker.stop()

    assert broker._live_started is False


def test_broker_stop_is_silent_noop_when_store_is_already_disconnected():
    """Test that broker stop is a silent noop when store is already disconnected."""

    class DisconnectedStore:
        """Store that is already disconnected."""

        def __init__(self):
            """Initialize the disconnected store."""
            self.is_connected = False
            self.stop_calls = 0

        def stop(self):
            """Stop the store."""
            self.stop_calls += 1

    store = DisconnectedStore()
    broker = BtApiBroker(store=store)
    broker._live_started = True

    broker.stop()

    assert broker._live_started is False
    assert store.stop_calls == 0


def test_broker_stop_does_not_disconnect_shared_live_store():
    """Cerebro broker teardown should not own the shared store lifecycle."""
    client = FakeBtApiClient()
    store = make_store(api=client)
    store._cerebro_managed_lifecycle = False
    store.start()
    broker = BtApiBroker(store=store)
    broker._live_started = True

    broker.stop()

    assert broker._live_started is False
    assert store.is_connected is True
    assert client.connected is True

    store.stop()


def test_broker_runtime_helpers_update_local_state_without_store():
    """Test that broker runtime helpers update local state without store."""
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
    """Test that get_notification returns None when queue is empty."""
    broker = BtApiBroker(store=None)

    assert broker.get_notification() is None


def test_get_notification_returns_queued_order_clone_and_drains_queue(started_stack):
    """Test that get_notification returns queued order clone and drains queue."""
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
    """Test that broker stop is idempotent and does not duplicate store disconnect events."""
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

    event_types = [
        kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()
    ]

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
        assert any(
            event["event_type"] == "order_validation_rejected"
            and event["error_code"] == "invalid_price_tick"
            for event in events
        )
    finally:
        broker.stop()


def test_local_validation_rejects_order_below_min_size():
    """Broker should reject orders below exchange minimum size before API submission."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(
        api=client,
        contract_metadata={
            DEFAULT_SYMBOL: {
                "min_order_size": 0.01,
                "order_size_step": 0.01,
            }
        },
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
            size=0.005,
            price=100.5,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "min_order_size_not_met"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_local_validation_rejects_order_size_step_mismatch():
    """Broker should reject quantities that do not align with exchange lot step."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(
        api=client,
        contract_metadata={
            DEFAULT_SYMBOL: {
                "min_order_size": 0.001,
                "order_size_step": 0.01,
            }
        },
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
            size=0.015,
            price=100.5,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "invalid_order_size_step"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_local_validation_reads_raw_okx_min_size_and_lot_step_aliases():
    """Raw OKX metadata aliases must be enforced before API submission."""
    symbol = "BTC-USDT-SWAP"
    client = FakeBtApiClient(
        history={symbol: [make_bar(0, 60000.0, 60100.0, 59900.0, 60050.0)]},
    )
    store = make_store(
        api=client,
        contract_metadata={
            symbol: {
                "minSz": "1",
                "lotSz": "1",
                "ctVal": "0.01",
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=0.5,
            price=60000.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "min_order_size_not_met"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_local_validation_uses_market_specific_max_size_alias():
    """Market orders must obey maxMktSz even when maxLmtSz is larger."""
    symbol = "BTC-USDT-SWAP"
    client = FakeBtApiClient(
        balance={"cash": 1_000_000.0, "value": 1_000_000.0},
        history={symbol: [make_bar(0, 60000.0, 60100.0, 59900.0, 60050.0)]},
    )
    store = make_store(
        api=client,
        contract_metadata={
            symbol: {
                "minSz": "1",
                "lotSz": "1",
                "maxLmtSz": "1000",
                "maxMktSz": "500",
                "ctVal": "0.01",
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker()

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=600,
            price=60000.0,
            exectype=bt.Order.Market,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "max_order_size_exceeded"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_local_validation_rejects_opening_order_when_margin_exceeds_cash():
    """Futures orders that cannot meet local margin requirements must not be submitted."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={"cash": 10_000.0, "value": 10_000.0},
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=4000.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "insufficient_cash"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_opening_order_rejects_when_pretrade_account_refresh_fails():
    """Opening exposure must not rely on stale cash when account refresh fails."""
    symbol = "IF2506"

    class FailingBalanceClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                balance={"cash": 1_000_000.0, "value": 1_000_000.0},
                history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
            )
            self.fail_balance = False

        def get_balance(self):
            if self.fail_balance:
                raise RuntimeError("account unavailable")
            return super().get_balance()

    client = FailingBalanceClient()
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    client.fail_balance = True
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=4000.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "pre_trade_state_refresh_failed"
        assert "account unavailable" in order.info["error_msg"]
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_opening_order_cash_validation_uses_margin_adjusted_account_cash():
    """Pre-trade cash checks must not treat account balance as available cash."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={
            "balance": 1_000_000.0,
            "equity": 200_000.0,
            "margin": 180_000.0,
        },
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=4000.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "insufficient_cash"
        assert "only 20000.00 is available" in order.info["error_msg"]
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_store_get_balance_unwraps_bybit_v5_result_list():
    """Store account refresh should consume raw Bybit wallet-balance wrappers."""
    client = FakeBtApiClient(
        balance={
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "accountType": "UNIFIED",
                        "totalEquity": "1,250.5",
                        "totalWalletBalance": "1,200.0",
                        "totalAvailableBalance": "950.25",
                        "totalInitialMargin": "300.25",
                    }
                ]
            },
        }
    )
    store = make_store(api=client)

    try:
        balance = store.get_balance(force=True)

        assert balance == {"cash": 950.25, "value": 1250.5}
    finally:
        store.stop()


def test_store_get_balance_unwraps_okx_account_data():
    """Store account refresh should consume raw OKX account wrappers."""
    client = FakeBtApiClient(
        balance={
            "code": "0",
            "msg": "",
            "data": [
                {
                    "totalEq": "2500",
                    "availEq": "2100",
                    "imr": "400",
                }
            ],
        }
    )
    store = make_store(api=client)

    try:
        balance = store.get_balance(force=True)

        assert balance == {"cash": 2100.0, "value": 2500.0}
    finally:
        store.stop()


def test_store_get_balance_reads_balance_container():
    """Store account refresh should consume bt_api_py container objects."""

    class ContainerBalanceClient(FakeBtApiClient):
        def get_balance(self):
            return _FakeBalanceContainer(
                {
                    "exchange_name": "OKX",
                    "total_margin": "2500",
                    "total_used_margin": "400",
                    "total_wallet_balance": "2500",
                }
            )

    client = ContainerBalanceClient()
    store = make_store(api=client)

    try:
        balance = store.get_balance(force=True)

        assert balance == {"cash": 2100.0, "value": 2500.0}
    finally:
        store.stop()


def test_ctp_offset_inference_rejects_when_pretrade_position_refresh_fails():
    """CTP net offset inference must not use stale positions when refresh fails."""
    symbol = "IF2506"

    class FailingPositionsClient(FakeBtApiClient):
        def __init__(self):
            super().__init__(
                balance={"cash": 1_000_000.0, "value": 1_000_000.0},
                positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
                history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
            )
            self.fail_positions = False

        def get_positions(self):
            if self.fail_positions:
                raise RuntimeError("positions unavailable")
            return super().get_positions()

    client = FailingPositionsClient()
    store = make_store(api=client, provider="ctp_gateway")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    client.fail_positions = True
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "pre_trade_state_refresh_failed"
        assert "positions unavailable" in order.info["error_msg"]
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_local_cash_validation_allows_flattening_existing_position():
    """Closing a futures position should not be blocked by low available cash."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={"cash": 100.0, "value": 500_000.0},
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Accepted
        assert order.info["offset"] == "close"
        assert client.submitted_orders[0]["offset"] == "close"
    finally:
        broker.stop()


def test_local_cash_validation_rejects_opening_order_without_risk_price():
    """Opening orders must not bypass margin checks when no current price is known."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={"cash": 1_000_000.0, "value": 1_000_000.0},
        history={symbol: [make_bar(0, 0.0, 0.0, 0.0, 0.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            exectype=bt.Order.Market,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "risk_price_unavailable"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_ctp_explicit_close_order_rejects_when_size_exceeds_position():
    """Explicit close orders must not bypass local position-size checks."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={"cash": 1_000_000.0, "value": 1_000_000.0},
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(api=client, provider="ctp_gateway")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=2,
            price=4010.0,
            exectype=bt.Order.Limit,
            offset="close",
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "close_size_exceeds_position"
        assert client.submitted_orders == []
    finally:
        broker.stop()


def test_ctp_live_broker_rejects_unsupported_order_type_locally():
    """Backtesting-only order types must not reach the CTP store and crash live routing."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        balance={"cash": 1_000_000.0, "value": 1_000_000.0},
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(api=client, provider="ctp_gateway")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            exectype=bt.Order.StopTrail,
            trailamount=10.0,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "unsupported_order_type"
        assert client.submitted_orders == []
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

        events = [
            kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()
        ]
        assert "trading_disabled" in events
        assert "account_trading_disabled" in events
        assert "trading_enabled" in events
        assert "strategy_paused" in events
        assert "strategy_trading_paused" in events
        assert "strategy_resumed" in events
        assert "gateway_force_logout_requested" in events
        assert "force_logout_requested" in events
        assert "store_disconnected" in events
    finally:
        broker.stop()


def test_batch_cancel_returns_empty_summary_when_no_orders_are_open(started_stack):
    """Test that batch cancel returns empty summary when no orders are open."""
    client, store, _data, broker = started_stack

    try:
        cancelled = broker.batch_cancel([])
        store.get_notifications()
        default_cancelled = broker.batch_cancel()

        assert cancelled == []
        assert default_cancelled == []
        assert client.cancelled_orders == []

        runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        matching = [
            event for event in runtime_events if event["event_type"] == "batch_cancel_completed"
        ]
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


def test_batch_cancel_cancels_remote_open_orders_after_restart():
    """Remote-only open orders from restart hydration must be cancellable."""
    client = FakeBtApiClient(
        open_orders=[
            {
                "id": "remote-1",
                "symbol": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 1,
                "price": 101.0,
                "status": "accepted",
            }
        ],
    )
    store = make_store(api=client)
    broker = store.getbroker(open_orders_refresh_interval=60.0)

    broker.start()
    try:
        store.get_notifications()

        cancelled = broker.batch_cancel()

        assert cancelled == client.open_orders
        assert client.cancelled_orders == [
            {"order_ref": "remote-1", "dataname": DEFAULT_SYMBOL}
        ]

        runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        matching = [
            event for event in runtime_events if event["event_type"] == "batch_cancel_completed"
        ]
        assert matching
        assert matching[-1]["details"]["requested_count"] == 1
        assert matching[-1]["details"]["cancelled_count"] == 1
        assert matching[-1]["details"]["cancelled_orders"][0]["source"] == "remote_open_orders"
    finally:
        broker.stop()


def test_batch_cancel_deduplicates_local_and_remote_open_order_ids(started_stack):
    """A local live order mirrored in remote open orders should only be cancelled once."""
    client, _store, data, broker = started_stack

    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
        )
        client.open_orders = [
            {
                "id": order.info["external_order_id"],
                "symbol": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 1,
                "price": 101.0,
            }
        ]

        cancelled = broker.batch_cancel()

        assert cancelled == [order]
        assert client.cancelled_orders == [
            {"order_ref": order.info["external_order_id"], "dataname": DEFAULT_SYMBOL}
        ]
    finally:
        broker.stop()


def test_batch_cancel_skips_non_alive_orders_without_remote_cancel(started_stack):
    """Test that batch cancel skips non-alive orders without remote cancel."""
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
        matching = [
            event for event in runtime_events if event["event_type"] == "batch_cancel_completed"
        ]
        assert matching
        assert matching[-1]["details"]["requested_count"] == 1
        assert matching[-1]["details"]["cancelled_count"] == 0
        assert matching[-1]["details"]["failure_count"] == 0
        assert matching[-1]["details"]["failed_orders"] == []
    finally:
        broker.stop()


def test_force_logout_followed_by_stop_does_not_duplicate_store_disconnect_events():
    """Test that force logout followed by stop does not duplicate store disconnect events."""
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

    event_types = [
        kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()
    ]

    assert event_types.count("store_disconnect_requested") == 1
    assert event_types.count("store_disconnected") == 1


def test_force_logout_is_noop_for_disconnected_store_but_still_emits_runtime_event():
    """Test that force logout is noop for disconnected store but still emits runtime event."""

    class DisconnectedStore:
        """Store that is disconnected for testing."""

        def __init__(self):
            """Initialize the disconnected store."""
            self.is_connected = False
            self.stop_calls = 0
            self.events = []

        def stop(self):
            """Stop the store."""
            self.stop_calls += 1

        def emit_runtime_event(self, event_type, **kwargs):
            """Emit a runtime event."""
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


def test_remote_trade_update_accepts_volume_and_fill_price_aliases():
    """Trade events may use volume/fill_price aliases instead of size/price."""
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
                "trade_id": "trade-alias-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "volume": 1,
                "fill_price": 101.5,
                "timestamp": "09:30:00",
            }
        )

        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.5)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert broker.positions[DEFAULT_SYMBOL].price == pytest.approx(101.5)
    finally:
        broker.stop()


def test_remote_trade_update_accepts_raw_okx_trade_aliases_and_fee():
    """Raw OKX trade events must match orders, book fills, and preserve fee signs."""
    symbol = "BTC-USDT-SWAP"
    client = FakeBtApiClient(
        history={symbol: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client, provider="okx")
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    broker.setcommission(
        commission=10.0,
        commtype=bt.CommInfoBase.COMM_FIXED,
    )
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
                "exchange": "OKX",
                "ordId": "btapi-1",
                "tradeId": "okx-trade-1",
                "instId": symbol,
                "side": "buy",
                "fillSz": "1",
                "fillPx": "101.5",
                "fee": "-0.25",
                "feeCcy": "USDT",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.5)
        assert broker.positions[symbol].size == pytest.approx(1.0)
        assert broker.positions[symbol].price == pytest.approx(101.5)
        assert exbit.openedcomm == pytest.approx(0.25)
        assert order.executed.comm == pytest.approx(0.25)
    finally:
        broker.stop()


def test_remote_trade_update_without_price_is_ignored_not_zero_filled():
    """Malformed fills must not execute locally at price zero."""
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
                "trade_id": "trade-missing-price-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "timestamp": "09:30:00",
            }
        )

        broker.next()

        assert order.status == bt.Order.Accepted
        assert order.executed.size == pytest.approx(0.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(0.0)

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        ignored = [event for event in events if event["event_type"] == "trade_update_ignored"]
        assert ignored
        assert ignored[-1]["error_code"] == "invalid_trade_price"
    finally:
        broker.stop()


def test_submit_response_with_immediate_fill_updates_order_and_position():
    """A synchronous live submit response with fill details must be booked immediately."""

    class ImmediateFillClient(FakeBtApiClient):
        def submit_order(self, payload):
            self.submitted_orders.append(dict(payload))
            return {
                "status": "completed",
                "retcode": 10009,
                "success": True,
                "deal": "deal-9001",
                "volume": payload["size"],
                "price": 101.25,
            }

    client = ImmediateFillClient(
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

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.25)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert broker.positions[DEFAULT_SYMBOL].price == pytest.approx(101.25)
    finally:
        broker.stop()


def test_submit_response_with_okx_data_list_maps_order_id_for_later_fill():
    """OKX-style submit wrappers must be accepted and map ordId for async fills."""

    class OkxWrappedSubmitClient(FakeBtApiClient):
        def submit_order(self, payload):
            self.submitted_orders.append(dict(payload))
            return {
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "ordId": "okx-order-1",
                        "clOrdId": "local-client-1",
                        "sCode": "0",
                        "sMsg": "",
                    }
                ],
            }

    client = OkxWrappedSubmitClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client, provider="okx")
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

        assert order.status == bt.Order.Accepted
        assert order.info["external_order_id"] == "okx-order-1"
        assert broker._orders_by_external_id == {"okx-order-1": order}

        client.push_broker_update(
            {
                "kind": "trade",
                "exchange": "OKX",
                "ordId": "okx-order-1",
                "tradeId": "okx-trade-1",
                "instId": DEFAULT_SYMBOL,
                "side": "buy",
                "fillSz": "1",
                "fillPx": "101.25",
                "fee": "-0.1",
                "feeCcy": "USDT",
            }
        )
        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(101.25)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert broker._orders_by_external_id == {}
    finally:
        broker.stop()


def test_remote_position_update_does_not_fill_open_order():
    """Provider position snapshots must not be treated as trade executions."""
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
                "kind": "position",
                "position_id": "pos-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 1,
                "volume": 1,
                "price": 101.0,
                "profit": 0.0,
                "commission": 0.0,
            }
        )

        broker.next()

        assert order.status == bt.Order.Accepted
        assert order.executed.size == pytest.approx(0.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(0.0)
        runtime_events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        assert any(event["event_type"] == "position_update" for event in runtime_events)
    finally:
        broker.stop()


def test_remote_trade_update_uses_exchange_reported_commission():
    """Live fills should book the exact commission reported by the exchange."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    broker.setcommission(
        commission=10.0,
        commtype=bt.CommInfoBase.COMM_FIXED,
    )
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
                "trade_id": "trade-commission-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "commission": -2.75,
                "timestamp": "09:30:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.openedcomm == pytest.approx(2.75)
        assert order.executed.comm == pytest.approx(2.75)
    finally:
        broker.stop()


def test_remote_okx_positive_fee_is_treated_as_rebate():
    """OKX reports positive fee values as rebates, not transaction costs."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    broker.setcommission(
        commission=10.0,
        commtype=bt.CommInfoBase.COMM_FIXED,
    )
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
                "exchange": "OKX",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "trade_id": "trade-okx-rebate-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "trade_fee": 0.25,
                "fee_currency": "USDT",
                "timestamp": "09:30:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.openedcomm == pytest.approx(-0.25)
        assert order.executed.comm == pytest.approx(-0.25)
    finally:
        broker.stop()


def test_remote_trade_update_uses_fill_role_commission_when_fee_missing():
    """Live fills should fall back to maker/taker fees when no exact fee arrives."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    broker.setcommission(
        commission=0.001,
        maker_commission=-0.0001,
        taker_commission=0.0005,
        commtype=bt.CommInfoBase.COMM_PERC,
        percabs=True,
    )
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
                "trade_id": "trade-maker-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "liquidity": "maker",
                "timestamp": "09:30:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.openedcomm == pytest.approx(-0.0101)
        assert order.executed.comm == pytest.approx(-0.0101)
    finally:
        broker.stop()


def test_unmatched_trade_update_is_retried_after_order_identifier_arrives():
    """A fill that arrives before its server id is mapped must not be lost."""
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
                "external_order_id": "server-ref-1",
                "trade_id": "trade-before-order-map-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "timestamp": "09:30:00",
            }
        )
        client.push_broker_update(
            {
                "kind": "order",
                "order_ref": str(order.ref),
                "external_order_id": "server-ref-1",
                "data_name": DEFAULT_SYMBOL,
                "status": "accepted",
            }
        )

        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)
        assert list(broker._pending_trade_updates) == []

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        assert any(event["event_type"] == "trade_update_deferred" for event in events)
    finally:
        broker.stop()


def test_duplicate_trade_update_without_trade_id_does_not_overfill_completed_order():
    """Duplicate anonymous fills must not push a completed order past its size."""
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
        update = {
            "kind": "trade",
            "order_ref": str(order.ref),
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "offset": "open",
            "size": 1,
            "price": 101.0,
            "timestamp": "09:30:00",
        }
        client.push_broker_update(update)
        client.push_broker_update(update)

        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.remsize == pytest.approx(0.0)
        assert len(order.executed.exbits) == 1
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        ignored = [event for event in events if event["event_type"] == "trade_update_ignored"]
        assert ignored
        assert ignored[-1]["error_code"] == "no_order_remaining"
    finally:
        broker.stop()


def test_oversized_trade_update_is_clipped_to_order_remaining():
    """A remote fill larger than remaining local size must not overstate exposure."""
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
                "order_ref": str(order.ref),
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 2,
                "price": 101.0,
                "timestamp": "09:30:00",
            }
        )

        broker.next()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.remsize == pytest.approx(0.0)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1.0)

        events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
        clipped = [
            event for event in events if event["event_type"] == "trade_update_size_clipped"
        ]
        assert clipped
        assert clipped[-1]["error_code"] == "trade_size_exceeds_remaining"
        assert clipped[-1]["details"]["requested_fill_qty"] == pytest.approx(2.0)
        assert clipped[-1]["details"]["applied_fill_qty"] == pytest.approx(1.0)
    finally:
        broker.stop()


def test_remote_trade_updates_split_commission_when_a_fill_reverses_position():
    """Test that remote trade updates split commission when a fill reverses position."""
    client = FakeBtApiClient(
        positions=[
            {"instrument": DEFAULT_SYMBOL, "direction": "short", "volume": 1, "price": 100.0}
        ],
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


def test_remote_trade_updates_split_exchange_commission_when_a_fill_reverses_position():
    """Exchange-reported fill commission is split across closed/opened portions."""
    client = FakeBtApiClient(
        positions=[
            {"instrument": DEFAULT_SYMBOL, "direction": "short", "volume": 1, "price": 100.0}
        ],
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
                "trade_id": "trade-reversal-commission-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "size": 2,
                "price": 101.0,
                "commission": 9.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(1.0)
        assert exbit.opened == pytest.approx(1.0)
        assert exbit.closedcomm == pytest.approx(4.5)
        assert exbit.openedcomm == pytest.approx(4.5)
        assert order.executed.comm == pytest.approx(9.0)
    finally:
        broker.stop()


def test_remote_trade_update_net_futures_pnl_uses_contract_multiplier():
    """Net-mode live fills must use comminfo multiplier for futures PnL and value."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(api=client)
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    broker.addcommissioninfo(
        bt.ComminfoFuturesPercent(commission=0.0, margin=0.12, mult=300),
        name=symbol,
    )
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Market,
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "trade_id": "trade-fut-close-1",
                "data_name": symbol,
                "side": "sell",
                "offset": "close",
                "size": 1,
                "price": 4010.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(-1.0)
        assert exbit.pnl == pytest.approx(3000.0)
        assert exbit.closedvalue == pytest.approx(144000.0)
        assert broker.positions[symbol].size == pytest.approx(0.0)
    finally:
        broker.stop()


def test_remote_trade_update_net_inverse_futures_uses_contract_value():
    """Inverse live fills must use contract value for PnL, value and fees."""
    symbol = "BTC-USD-SWAP"
    client = FakeBtApiClient(
        positions=[
            {"instrument": symbol, "direction": "long", "volume": 100, "price": 50000.0}
        ],
        history={symbol: [make_bar(0, 50000.0, 50100.0, 49900.0, 50010.0)]},
    )
    store = make_store(
        api=client,
        contract_metadata={
            symbol: {
                "ctType": "inverse",
                "ctVal": 100,
                "ctMult": 1,
                "ctValCcy": "USD",
                "baseCcy": "BTC",
                "quoteCcy": "USD",
                "settleCcy": "BTC",
                "margin_rate": 0.1,
                "taker_commission_rate": 0.0005,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=100,
            price=55000.0,
            exectype=bt.Order.Market,
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "trade_id": "trade-inverse-close-1",
                "data_name": symbol,
                "side": "sell",
                "offset": "close",
                "size": 100,
                "price": 55000.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(-100.0)
        assert exbit.pnl == pytest.approx(1000.0)
        assert exbit.closedvalue == pytest.approx(1000.0)
        assert exbit.closedcomm == pytest.approx(5.0)
        assert broker.positions[symbol].size == pytest.approx(0.0)
    finally:
        broker.stop()


def test_remote_trade_update_uses_close_today_commission_rate():
    """CTP close-today fills must use close-today fees, not opening fees."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
                "close_fee_rate": 0.00003,
                "close_today_fee_rate": 0.000345,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Market,
            offset="close_today",
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "trade_id": "trade-fut-close-today-1",
                "data_name": symbol,
                "side": "sell",
                "offset": "close_today",
                "size": 1,
                "price": 4010.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(-1.0)
        assert exbit.pnl == pytest.approx(3000.0)
        assert exbit.closedcomm == pytest.approx(415.035)
        assert order.executed.comm == pytest.approx(415.035)
        assert broker.positions[symbol].size == pytest.approx(0.0)
    finally:
        broker.stop()


def test_remote_trade_update_uses_close_yesterday_commission_rate():
    """CTP close-yesterday fills must use close-yesterday fees when provided."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
                "close_fee_rate": 0.00003,
                "close_yesterday_fee_rate": 0.000032,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Market,
            offset="close_yesterday",
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "trade_id": "trade-fut-close-yesterday-1",
                "data_name": symbol,
                "side": "sell",
                "offset": "close_yesterday",
                "size": 1,
                "price": 4010.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(-1.0)
        assert exbit.pnl == pytest.approx(3000.0)
        assert exbit.closedcomm == pytest.approx(38.496)
        assert order.executed.comm == pytest.approx(38.496)
        assert broker.positions[symbol].size == pytest.approx(0.0)
    finally:
        broker.stop()


def test_remote_trade_update_uses_mixed_close_today_commission_when_missing_remote_fee():
    """Fallback CTP close-today fees must include both ratio and per-lot components."""
    symbol = "IF2506"
    client = FakeBtApiClient(
        positions=[{"instrument": symbol, "direction": "long", "volume": 1, "price": 4000.0}],
        history={symbol: [make_bar(0, 4000.0, 4010.0, 3990.0, 4005.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            symbol: {
                "multiplier": 300,
                "margin_rate": 0.12,
                "open_fee_rate": 0.000023,
                "open_fee_amount": 1.2,
                "close_today_fee_rate": 0.000345,
                "close_today_fee_amount": 4.5,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(account_refresh_interval=60.0, positions_refresh_interval=60.0)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=4010.0,
            exectype=bt.Order.Market,
            offset="close_today",
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "trade_id": "trade-fut-close-today-mixed-1",
                "data_name": symbol,
                "side": "sell",
                "offset": "close_today",
                "size": 1,
                "price": 4010.0,
                "timestamp": "09:31:00",
            }
        )

        broker.next()
        exbit = order.executed.exbits[0]

        assert order.status == bt.Order.Completed
        assert exbit.closed == pytest.approx(-1.0)
        assert exbit.pnl == pytest.approx(3000.0)
        assert exbit.closedcomm == pytest.approx(419.535)
        assert order.executed.comm == pytest.approx(419.535)
        assert broker.positions[symbol].size == pytest.approx(0.0)
    finally:
        broker.stop()
