"""Notification-focused unit tests for BtApiStore."""

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


def test_store_exposes_contract_metadata_lookup():
    """Configured contract metadata should be queryable by symbol."""
    store = make_store(
        api=FakeBtApiClient(),
        contract_metadata={"rb2610": {"min_price_tick": 1.0, "max_order_size": 5}},
    )

    assert store.get_contract_metadata("rb2610") == {
        "min_price_tick": 1.0,
        "max_order_size": 5,
    }
    assert "rb2610" in store.get_contract_metadata()
