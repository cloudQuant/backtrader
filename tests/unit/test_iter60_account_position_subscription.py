"""Direct snapshots without a shared stream watermark are not reconciliation proof."""

from types import SimpleNamespace
import threading

import pytest

from backtrader.stores._account_position_subscription import StoreAccountPositionSubscription


@pytest.mark.parametrize("during_read", ["position", "disconnect"])
def test_direct_snapshot_never_covers_event_or_disconnect_during_read(during_read):
    store = SimpleNamespace(_sdk_mode=True, provider="fake")
    subscription = StoreAccountPositionSubscription(store, "acct")

    def snapshot():
        if during_read == "position":
            subscription.on_position_event({"symbol": "X", "position_side": "net", "quantity": "1"})
        else:
            subscription.on_disconnect()
        return []

    store.get_positions = snapshot
    assert subscription.baseline() is False
    report = subscription.report()
    assert report.complete is False
    assert subscription.positions.interruption == "BASELINE_STREAM_CHANGED"
    if during_read == "position":
        assert report.positions["X"] == 1


def test_quiet_unwatermarked_snapshot_does_not_prove_continuity():
    store = SimpleNamespace(_sdk_mode=True, provider="fake", get_positions=lambda: [])
    subscription = StoreAccountPositionSubscription(store, "acct")
    assert subscription.baseline() is False
    assert subscription.report().complete is False
    assert subscription.positions.interruption == "BASELINE_CONTINUITY_UNPROVEN"


def test_concurrent_position_push_cannot_be_overwritten_by_inflight_snapshot():
    entered, release = threading.Event(), threading.Event()
    store = SimpleNamespace(_sdk_mode=True, provider="fake")
    subscription = StoreAccountPositionSubscription(store, "acct")

    def snapshot():
        entered.set()
        assert release.wait(5)
        return []

    store.get_positions = snapshot
    thread = threading.Thread(target=subscription.baseline)
    thread.start()
    try:
        assert entered.wait(5)
        subscription.on_position_event({"symbol": "X", "position_side": "net", "quantity": "1"})
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    report = subscription.report()
    assert not report.complete and report.positions["X"] == 1
