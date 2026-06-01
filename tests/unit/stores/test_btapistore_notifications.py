"""Notification-focused unit tests for BtApiStore."""

import pytest

from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


def _event_types(store):
    return [kwargs["event"]["event_type"] for _msg, _args, kwargs in store.get_notifications()]


def test_store_emits_lifecycle_runtime_events():
    """Starting and stopping the store should emit structured lifecycle events."""
    client = FakeBtApiClient()
    store = make_store(api=client, provider="okx")

    store.start()
    store.stop()

    event_types = _event_types(store)

    assert "store_connecting" in event_types
    assert "store_connected" in event_types
    assert "store_ready" in event_types
    assert "store_disconnect_requested" in event_types
    assert "store_disconnected" in event_types


def test_store_emits_reconnect_success_after_restart():
    """Restarting the same store instance should emit a reconnect-success event."""
    client = FakeBtApiClient()
    store = make_store(api=client, provider="okx")

    store.start()
    store.stop()
    store.get_notifications()

    store.start()

    event_types = _event_types(store)

    assert "store_reconnect_success" in event_types
    assert "store_connected" in event_types
    assert "store_ready" in event_types


def test_store_stop_is_idempotent_and_does_not_emit_duplicate_disconnect_events():
    client = FakeBtApiClient()
    store = make_store(api=client, provider="okx")

    store.start()
    store.stop()
    store.stop()

    event_types = _event_types(store)

    assert event_types.count("store_disconnect_requested") == 1
    assert event_types.count("store_disconnected") == 1


def test_store_exposes_contract_metadata_lookup():
    """Configured contract metadata should be queryable by symbol."""
    store = make_store(
        api=FakeBtApiClient(),
        contract_metadata={"rb2610": {"min_price_tick": 1.0, "max_order_size": 5}},
    )

    metadata = store.get_contract_metadata("rb2610")
    all_metadata = store.get_contract_metadata()
    missing_metadata = store.get_contract_metadata("missing")

    assert metadata == {
        "min_price_tick": 1.0,
        "max_order_size": 5,
    }
    assert "rb2610" in all_metadata
    assert missing_metadata == {}

    metadata["min_price_tick"] = 9.0
    all_metadata["rb2610"]["max_order_size"] = 99
    missing_metadata["unexpected"] = True

    assert store.get_contract_metadata("rb2610") == {
        "min_price_tick": 1.0,
        "max_order_size": 5,
    }
    assert store.get_contract_metadata()["rb2610"] == {
        "min_price_tick": 1.0,
        "max_order_size": 5,
    }
    assert store.get_contract_metadata("missing") == {}


def test_store_emits_runtime_events_for_broker_updates():
    """Remote broker updates should be translated into runtime notifications."""
    client = FakeBtApiClient(
        broker_updates=[
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "status": "accepted",
                "data_name": "rb2610",
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 3500.0,
            },
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "trade_id": "trade-1",
                "data_name": "rb2610",
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 3500.0,
            },
        ]
    )
    store = make_store(api=client)
    store.start()

    assert store.poll_broker_update()["kind"] == "order"
    assert store.poll_broker_update()["kind"] == "trade"
    notifications = store.get_notifications()
    event_types = [kwargs["event"]["event_type"] for _msg, _args, kwargs in notifications]

    assert store.poll_broker_update() is None
    assert store.get_notifications() == []

    assert "order_status_accepted" in event_types
    assert "trade_execution" in event_types


def test_store_poll_broker_update_returns_none_before_start():
    client = FakeBtApiClient(
        broker_updates=[
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "status": "accepted",
            }
        ]
    )
    store = make_store(api=client)

    assert store.is_connected is False
    assert store.poll_broker_update() is None
    assert store.is_connected is False
    assert _event_types(store) == []


def test_store_poll_broker_update_returns_none_when_api_does_not_support_it():
    class NoBrokerUpdateClient:
        def __init__(self):
            self.connected = False

        def connect(self):
            self.connected = True

        def disconnect(self):
            self.connected = False

    store = make_store(api=NoBrokerUpdateClient())
    store.start()
    store.get_notifications()

    assert store.poll_broker_update() is None
    assert _event_types(store) == []


def test_store_emits_store_error_runtime_event_for_error_broker_update():
    client = FakeBtApiClient(
        broker_updates=[
            {
                "kind": "error",
                "error_code": "TEST_ERR",
                "error_msg": "simulated broker failure",
                "data_name": "rb2610",
            }
        ]
    )
    store = make_store(api=client)
    store.start()

    update = store.poll_broker_update()

    assert update["kind"] == "error"
    notifications = store.get_notifications()
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in notifications]
    matching = [event for event in runtime_events if event["event_type"] == "store_error"]
    assert matching
    assert matching[-1]["error_code"] == "TEST_ERR"
    assert matching[-1]["error_msg"] == "simulated broker failure"


def test_store_emits_order_reject_remote_runtime_event_for_rejected_broker_update():
    client = FakeBtApiClient(
        broker_updates=[
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "status": "rejected",
                "status_msg": "price limit exceeded",
                "data_name": "rb2610",
            }
        ]
    )
    store = make_store(api=client)
    store.start()

    update = store.poll_broker_update()

    assert update["status"] == "rejected"
    notifications = store.get_notifications()
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in notifications]
    matching = [event for event in runtime_events if event["event_type"] == "order_reject_remote"]
    assert matching
    assert matching[-1]["status"] == "rejected"
    assert matching[-1]["error_msg"] == "price limit exceeded"


@pytest.mark.parametrize(
    ("status", "expected_event_type"),
    [
        ("partial", "order_status_partial"),
        ("completed", "order_status_completed"),
        ("canceled", "order_status_canceled"),
    ],
)
def test_store_emits_runtime_event_for_additional_order_status_broker_updates(status, expected_event_type):
    client = FakeBtApiClient(
        broker_updates=[
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "status": status,
                "data_name": "rb2610",
            }
        ]
    )
    store = make_store(api=client)
    store.start()

    update = store.poll_broker_update()

    assert update["status"] == status
    notifications = store.get_notifications()
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in notifications]
    matching = [event for event in runtime_events if event["event_type"] == expected_event_type]
    assert matching
    assert matching[-1]["status"] == status


@pytest.mark.parametrize(
    ("status", "expected_event_type"),
    [
        ("submitted", "order_status_submitted"),
        ("pending_review", "order_status_update"),
    ],
)
def test_store_emits_runtime_event_for_submitted_and_fallback_order_status_broker_updates(
    status, expected_event_type
):
    client = FakeBtApiClient(
        broker_updates=[
            {
                "kind": "order",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "status": status,
                "data_name": "rb2610",
            }
        ]
    )
    store = make_store(api=client)
    store.start()

    update = store.poll_broker_update()

    assert update["status"] == status
    notifications = store.get_notifications()
    runtime_events = [kwargs["event"] for _msg, _args, kwargs in notifications]
    matching = [event for event in runtime_events if event["event_type"] == expected_event_type]
    assert matching
    assert matching[-1]["status"] == status
