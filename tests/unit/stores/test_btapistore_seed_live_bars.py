"""Offline tests for Store initialization of the completed-bar queue."""

import threading

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.stores.btapistore import BtApiStore


def _store(**kwargs):
    return BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}, "live_bar_queue_size": 2},
        autostart=False,
        preserve_raw_bars=True,
        **kwargs,
    )


@pytest.mark.parametrize("live_bars", [None, {}, {"SA": []}])
def test_construct_without_live_bars_leaves_queue_empty(live_bars):
    store = _store(live_bars=live_bars)
    assert store._live_bar_queue.snapshot("SA") == (0, 0, "")
    assert store.is_connected is False


def test_seeded_bars_use_bounded_fifo_and_detach_inputs():
    bars = [{"close": 1}, {"close": 2}, {"close": 3}]
    store = _store(live_bars={"SA": iter(bars), "TA": [{"close": 4}]})
    depth, evictions, stale = store._live_bar_queue.snapshot("SA")
    assert (depth, evictions, stale) == (2, 1, "store_live_bar_queue_overflow")
    assert store._live_bar_queue.snapshot("TA") == (1, 0, "")
    assert store.poll_live("SA")["close"] == 2
    retained = store.poll_live("SA")
    assert retained["close"] == 3 and retained["stale"] is True
    assert "stale" not in bars[2]
    assert store.poll_live("TA")["close"] == 4


def test_seeded_bars_use_normal_projection_by_default():
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        autostart=False,
        live_bars={"SA": [["2026-11-03T09:00:00Z", 1, 3, 1, 2, 5]]},
    )
    bar = store.poll_live("SA")
    assert bar["close"] == 2.0 and bar["volume"] == 5.0
    assert bar["datetime"].isoformat() == "2026-11-03T09:00:00"


@pytest.mark.parametrize(
    ("seed_count", "expected_snapshot", "expected_closes"),
    [
        (2, (2, 0, ""), [1, 2]),
        (3, (2, 1, "store_live_bar_queue_overflow"), [2, 3]),
    ],
)
def test_autostart_preserves_constructor_seeded_live_bars(
    monkeypatch, seed_count, expected_snapshot, expected_closes
):
    monkeypatch.setattr(BtApiStore, "_ensure_api_ready", lambda self: None)
    monkeypatch.setattr(BtApiStore, "_begin_funding_refresh_generation", lambda self: None)
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}, "live_bar_queue_size": 2},
        autostart=True,
        live_bars={"SA": [{"close": close} for close in range(1, seed_count + 1)]},
        preserve_raw_bars=True,
    )

    assert store._stream_generation == 1
    assert store._live_bar_queue.snapshot("SA") == expected_snapshot
    assert store.is_stream_ready("SA") is (expected_snapshot[2] == "")
    assert [store.poll_live("SA")["close"] for _ in range(2)] == expected_closes


def test_new_sdk_stream_generation_discards_previous_bar_queue_state():
    store = _store()
    store._reset_sdk_stream_generation()  # establish the initial Store generation
    store._enqueue_live_bar("SA", {"close": 1})
    store._enqueue_live_bar("SA", {"close": 2})
    store._enqueue_live_bar("SA", {"close": 3})

    assert store._live_bar_queue.snapshot("SA") == (
        2,
        1,
        "store_live_bar_queue_overflow",
    )
    assert store.is_stream_ready("SA") is False

    previous_generation = store._stream_generation
    store._reset_sdk_stream_generation()

    assert store._stream_generation == previous_generation + 1
    assert store._live_bar_queue.symbols() == ()
    assert store._live_bar_queue.snapshot("SA") == (0, 0, "")
    assert store.is_stream_ready("SA") is True


def test_new_sdk_stream_generation_waits_for_inflight_old_event_drain(monkeypatch):
    store = _store()
    store._reset_sdk_stream_generation()  # the queued event belongs to generation one
    drain_entered = threading.Event()
    allow_drain_to_enqueue = threading.Event()
    reset_started = threading.Event()
    reset_finished = threading.Event()
    thread_errors = []

    class ObservedDrainLock:
        def __init__(self):
            self._lock = threading.Lock()
            self._entries_lock = threading.Lock()
            self._entries = 0
            self.second_entry = threading.Event()

        def __enter__(self):
            with self._entries_lock:
                self._entries += 1
                if self._entries == 2:
                    self.second_entry.set()
            self._lock.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self._lock.release()
            return False

    def blocked_old_event_drain():
        drain_entered.set()
        if not allow_drain_to_enqueue.wait(2):
            raise AssertionError("timed out waiting to release the old event drain")
        store._enqueue_live_bar("SA", {"close": 10})

    monkeypatch.setattr(store, "_drain_sdk_events_locked", blocked_old_event_drain)
    observed_drain_lock = ObservedDrainLock()
    store._sdk_event_drain_lock = observed_drain_lock

    def drain_old_generation():
        try:
            store._drain_sdk_events()
        except BaseException as exc:  # preserve thread failures for the test thread
            thread_errors.append(exc)

    def reset_generation():
        try:
            reset_started.set()
            store._reset_sdk_stream_generation()
        except BaseException as exc:  # preserve thread failures for the test thread
            thread_errors.append(exc)
        finally:
            reset_finished.set()

    drain_thread = threading.Thread(target=drain_old_generation, daemon=True)
    reset_thread = threading.Thread(target=reset_generation, daemon=True)
    drain_thread.start()
    try:
        assert drain_entered.wait(1)
        reset_thread.start()
        assert reset_started.wait(1)
        reset_waited_for_drain = observed_drain_lock.second_entry.wait(1)
        reset_finished_before_release = reset_finished.wait(0.05)
    finally:
        allow_drain_to_enqueue.set()
        drain_thread.join(2)
        if reset_thread.ident is not None:
            reset_thread.join(2)

    assert not drain_thread.is_alive()
    assert not reset_thread.is_alive()
    assert not thread_errors
    assert reset_waited_for_drain is True
    assert reset_finished_before_release is False
    assert store._live_bar_queue.snapshot("SA") == (0, 0, "")
    assert store.is_stream_ready("SA") is True
