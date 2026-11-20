"""Offline tests for Store initialization of the completed-bar queue."""

import threading

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


def _store(**kwargs):
    return BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}, "live_bar_queue_size": 2},
        autostart=False,
        preserve_raw_bars=True,
        **kwargs,
    )


def _start_without_external_io(monkeypatch, store):
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: None)
    monkeypatch.setattr(BtApiStore, "_begin_funding_refresh_generation", lambda self: None)
    store.start()


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
    assert store._has_successful_sdk_stream_generation is True
    assert store._live_bar_queue.snapshot("SA") == expected_snapshot
    assert store.is_stream_ready("SA") is (expected_snapshot[2] == "")
    assert [store.poll_live("SA")["close"] for _ in range(2)] == expected_closes


def test_failed_first_start_retry_preserves_constructor_seeded_live_bars(monkeypatch):
    store = _store(live_bars={"SA": [{"close": 1}, {"close": 2}]})
    monkeypatch.setattr(BtApiStore, "_begin_funding_refresh_generation", lambda self: None)
    ensure_calls = 0

    def fail_first_api_initialization():
        nonlocal ensure_calls
        ensure_calls += 1
        if ensure_calls == 1:
            raise RuntimeError("first_start_api_initialization_failed")

    monkeypatch.setattr(store, "_ensure_api_ready", fail_first_api_initialization)
    with pytest.raises(RuntimeError, match="first_start_api_initialization_failed"):
        store.start()

    assert store._started is False
    assert store._stream_generation == 1
    assert store._has_successful_sdk_stream_generation is False
    assert store._live_bar_queue.snapshot("SA") == (2, 0, "")

    store.start()

    assert store._started is True
    assert store._stream_generation == 2
    assert store._has_successful_sdk_stream_generation is True
    assert store._live_bar_queue.snapshot("SA") == (2, 0, "")


def test_failed_partial_first_start_does_not_leave_runtime_bar_with_seed(monkeypatch):
    seed = {"close": 1}
    runtime_bar = {"close": 1}
    store = _store(live_bars={"SA": [seed]})
    queued_seed = store._live_bar_queue.get("SA")[0]

    def ensure_api_ready():
        store._enqueue_live_bar("SA", runtime_bar)

    def fail_funding_generation():
        raise RuntimeError("funding_generation_failed")

    monkeypatch.setattr(store, "_ensure_api_ready", ensure_api_ready)
    monkeypatch.setattr(
        store, "_begin_funding_refresh_generation", fail_funding_generation
    )

    with pytest.raises(RuntimeError, match="funding_generation_failed"):
        store.start()

    assert store._started is True
    assert store._has_successful_sdk_stream_generation is False
    retained = store._live_bar_queue.get("SA")
    assert len(retained) == 1 and retained[0] is queued_seed
    assert retained[0] is not runtime_bar
    assert store._live_bar_queue.snapshot("SA") == (
        1,
        0,
        "store_live_bar_start_aborted",
    )
    assert store._sdk_partial_start_failed_generation == store._stream_generation

    late_bar = {"close": 2}
    store._enqueue_live_bar("SA", late_bar)
    assert store._live_bar_queue.get("SA") == (queued_seed,)
    with pytest.raises(
        BtApiStoreError, match="store_partial_sdk_start_requires_verified_stop"
    ):
        store.start()


def test_failed_start_does_not_restore_consumed_seed_or_concurrently_consumed_bar(
    monkeypatch,
):
    store = _store(live_bars={"SA": [{"close": 1}]})
    consumed_seed = store.poll_live("SA")
    assert consumed_seed["close"] == 1

    funding_entered = threading.Event()
    release_funding = threading.Event()
    start_errors = []
    consumed_runtime = []
    runtime_bar = {"close": 2}

    def ensure_api_ready():
        store._enqueue_live_bar("SA", runtime_bar)

    def fail_funding_generation():
        funding_entered.set()
        if not release_funding.wait(2):
            raise AssertionError("timed out waiting to release failed start")
        raise RuntimeError("funding_generation_failed")

    monkeypatch.setattr(store, "_ensure_api_ready", ensure_api_ready)
    monkeypatch.setattr(
        store, "_begin_funding_refresh_generation", fail_funding_generation
    )

    def run_start():
        try:
            store.start()
        except BaseException as exc:
            start_errors.append(exc)

    start_thread = threading.Thread(target=run_start, daemon=True)
    start_thread.start()
    try:
        assert funding_entered.wait(1)
        consumer_thread = threading.Thread(
            target=lambda: consumed_runtime.append(store.poll_live("SA")),
            daemon=True,
        )
        consumer_thread.start()
        consumer_thread.join(2)
        assert not consumer_thread.is_alive()
    finally:
        release_funding.set()
        start_thread.join(2)

    assert not start_thread.is_alive()
    assert len(start_errors) == 1
    assert isinstance(start_errors[0], RuntimeError)
    assert str(start_errors[0]) == "funding_generation_failed"
    assert len(consumed_runtime) == 1 and consumed_runtime[0] is runtime_bar
    assert store._live_bar_queue.get("SA") == ()
    assert store._live_bar_queue.stale_reason("SA") == "store_live_bar_start_aborted"


def test_failed_start_overflow_does_not_resurrect_evicted_seed(monkeypatch):
    first_seed = {"close": 1}
    second_seed = {"close": 2}
    store = _store(live_bars={"SA": [first_seed, second_seed]})
    queued_second_seed = store._live_bar_queue.get("SA")[1]
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: store._enqueue_live_bar(
        "SA", {"close": 3}
    ))

    def fail_funding_generation():
        raise RuntimeError("funding_generation_failed")

    monkeypatch.setattr(
        store, "_begin_funding_refresh_generation", fail_funding_generation
    )
    with pytest.raises(RuntimeError, match="funding_generation_failed"):
        store.start()

    retained = store._live_bar_queue.get("SA")
    assert len(retained) == 1 and retained[0] is queued_second_seed
    assert all(bar["close"] != 1 for bar in retained)
    assert store._live_bar_queue.snapshot("SA") == (
        1,
        1,
        "store_live_bar_queue_overflow",
    )


def test_partial_start_fence_clears_only_after_verified_stop(monkeypatch):
    import backtrader.stores.btapistore as btapistore_module

    store = _store(live_bars={"SA": [{"close": 1}]})
    seed = store._live_bar_queue.get("SA")[0]
    runtime_bar = {"close": 2}

    def ensure_api_ready():
        store._enqueue_live_bar("SA", runtime_bar)

    monkeypatch.setattr(store, "_ensure_api_ready", ensure_api_ready)

    def fail_funding_generation():
        raise RuntimeError("funding_generation_failed")

    monkeypatch.setattr(
        store, "_begin_funding_refresh_generation", fail_funding_generation
    )
    with pytest.raises(RuntimeError, match="funding_generation_failed"):
        store.start()
    assert store._live_bar_queue.get("SA") == (seed,)
    assert store._live_bar_queue.stale_reason("SA") == "store_live_bar_start_aborted"

    original_stop_store = btapistore_module._stop_store
    monkeypatch.setattr(
        btapistore_module,
        "_stop_store",
        lambda *_args, **_kwargs: {"shutdown_state": "PASS"},
    )
    store.stop()
    assert store._sdk_partial_start_failed_generation is not None
    with pytest.raises(
        BtApiStoreError, match="store_partial_sdk_start_requires_verified_stop"
    ):
        store.start()

    monkeypatch.setattr(btapistore_module, "_stop_store", original_stop_store)
    health = store.stop()
    assert health["shutdown_state"] == "PASS"
    assert store._started is False and store._connected is False
    assert store._sdk_partial_start_failed_generation is None

    monkeypatch.setattr(store, "_ensure_api_ready", lambda: None)
    monkeypatch.setattr(store, "_begin_funding_refresh_generation", lambda: None)
    store.start()
    assert store._stream_generation == 2
    assert store._has_successful_sdk_stream_generation is True
    assert store._live_bar_queue.get("SA") == (seed,)
    assert store._live_bar_queue.snapshot("SA") == (
        1,
        0,
        "store_live_bar_start_aborted",
    )
    assert store.stop()["shutdown_state"] == "PASS"


def test_injected_api_start_failure_without_store_activity_can_retry(monkeypatch):
    import backtrader.stores.btapistore as btapistore_module

    api = object()
    monkeypatch.setattr(
        btapistore_module,
        "_is_supported_api_facade",
        lambda candidate: (candidate is api, False),
    )
    store = BtApiStore(
        api=api,
        config={"exchange_kwargs": {"CTP___FUTURE": {}}, "live_bar_queue_size": 2},
        autostart=False,
        live_bars={"SA": [{"close": 1}]},
        preserve_raw_bars=True,
    )
    assert store._sdk_owned_api is False

    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: True))
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: None)
    monkeypatch.setattr(store._sdk_correlated_order_adapter, "warm_command_types", lambda: None)
    monkeypatch.setattr(store, "_begin_funding_refresh_generation", lambda: None)

    def fail_command_worker_start():
        raise RuntimeError("command_worker_start_failed")

    monkeypatch.setattr(store, "_start_command_worker", fail_command_worker_start)
    with pytest.raises(RuntimeError, match="command_worker_start_failed"):
        store.start()

    assert store._started is False
    assert store._live_bar_queue.get("SA") is not None
    assert store._sdk_partial_start_failed_generation is None
    # This injected, not-yet-started API has no Store-owned activity to close;
    # stop_store takes its early-return path and does not claim PASS.
    assert store.stop()["shutdown_state"] != "PASS"
    assert store._sdk_partial_start_failed_generation is None

    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    store.start()
    assert store._started is True
    assert store._stream_generation == 2
    assert store._has_successful_sdk_stream_generation is True


def test_live_bar_poll_pop_waits_for_successful_restart_generation_reset(
    monkeypatch,
):
    store = _store()
    _start_without_external_io(monkeypatch, store)
    store._enqueue_live_bar("SA", {"close": 1})

    pop_entered = threading.Event()
    release_pop = threading.Event()
    restart_started = threading.Event()
    restart_finished = threading.Event()
    poll_results = []
    thread_errors = []
    original_pop_entry = store._live_bar_queue.pop_entry

    def blocked_pop_entry(symbol):
        result = original_pop_entry(symbol)
        pop_entered.set()
        if not release_pop.wait(2):
            raise AssertionError("timed out waiting to release live-bar poll")
        return result

    monkeypatch.setattr(store._live_bar_queue, "pop_entry", blocked_pop_entry)

    def poll_old_bar():
        try:
            poll_results.append(store.poll_live("SA"))
        except BaseException as exc:
            thread_errors.append(exc)

    def restart_store():
        try:
            restart_started.set()
            store.stop()
            store.start()
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            restart_finished.set()

    poll_thread = threading.Thread(target=poll_old_bar, daemon=True)
    restart_thread = threading.Thread(target=restart_store, daemon=True)
    poll_thread.start()
    try:
        assert pop_entered.wait(1)
        restart_thread.start()
        assert restart_started.wait(1)
        restart_completed_before_pop_release = restart_finished.wait(0.1)
    finally:
        release_pop.set()
        poll_thread.join(2)
        if restart_thread.ident is not None:
            restart_thread.join(2)

    assert not poll_thread.is_alive()
    assert not restart_thread.is_alive()
    assert not thread_errors
    assert restart_completed_before_pop_release is False
    assert store._stream_generation == 2
    assert store._live_bar_queue.get("SA") is None


def test_live_poll_drops_old_bar_when_restart_wins_after_queue_pop(monkeypatch):
    store = _store()
    _start_without_external_io(monkeypatch, store)
    store._enqueue_live_bar("SA", {"close": 1})
    reset_completed = threading.Event()
    poll_release_waiting_for_reset = threading.Event()
    poll_thread_id = None

    class PollReleaseBarrier:
        def __init__(self):
            self._lock = threading.Lock()
            self._poll_release_waited = False

        def __enter__(self):
            self._lock.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            wait_for_reset = (
                threading.get_ident() == poll_thread_id
                and not self._poll_release_waited
            )
            if wait_for_reset:
                self._poll_release_waited = True
            self._lock.release()
            if wait_for_reset:
                poll_release_waiting_for_reset.set()
                if not reset_completed.wait(2):
                    raise AssertionError("timed out waiting for the next Store generation")
            return False

    store._sdk_event_drain_lock = PollReleaseBarrier()
    original_reset = store._reset_sdk_stream_generation
    poll_started = threading.Event()

    def reset_and_signal():
        original_reset()
        reset_completed.set()

    monkeypatch.setattr(store, "_reset_sdk_stream_generation", reset_and_signal)
    monkeypatch.setattr(store, "_drain_sdk_events", lambda: None)
    poll_results = []
    thread_errors = []

    def poll_old_bar():
        nonlocal poll_thread_id
        poll_thread_id = threading.get_ident()
        poll_started.set()
        try:
            poll_results.append(store.poll_live("SA"))
        except BaseException as exc:
            thread_errors.append(exc)

    def restart_store():
        try:
            store.stop()
            store.start()
        except BaseException as exc:
            thread_errors.append(exc)

    poll_thread = threading.Thread(target=poll_old_bar, daemon=True)
    restart_thread = threading.Thread(target=restart_store, daemon=True)
    poll_thread.start()
    try:
        assert poll_started.wait(1)
        assert poll_thread_id is not None
        assert poll_release_waiting_for_reset.wait(1)
        restart_thread.start()
        assert reset_completed.wait(1)
    finally:
        poll_thread.join(2)
        if restart_thread.ident is not None:
            restart_thread.join(2)

    assert not poll_thread.is_alive()
    assert not restart_thread.is_alive()
    assert not thread_errors
    assert poll_results == [None]
    assert store._stream_generation == 2
    assert store._live_bar_queue.get("SA") == ()
    assert (
        store._live_bar_queue.stale_reason("SA")
        == "store_live_bar_generation_changed_during_poll"
    )


def test_concurrent_start_is_rejected_without_waiting_or_advancing_generation(
    monkeypatch,
):
    store = _store()
    api_initialization_entered = threading.Event()
    release_api_initialization = threading.Event()
    start_errors = []
    ensure_calls = 0

    def blocked_api_initialization():
        nonlocal ensure_calls
        ensure_calls += 1
        api_initialization_entered.set()
        if not release_api_initialization.wait(2):
            raise AssertionError("timed out waiting to release API initialization")

    monkeypatch.setattr(store, "_ensure_api_ready", blocked_api_initialization)
    monkeypatch.setattr(store, "_begin_funding_refresh_generation", lambda: None)

    def run_first_start():
        try:
            store.start()
        except BaseException as exc:
            start_errors.append(exc)

    start_thread = threading.Thread(target=run_first_start, daemon=True)
    start_thread.start()
    try:
        assert api_initialization_entered.wait(1)
        with pytest.raises(BtApiStoreError, match="store_sdk_start_already_in_progress"):
            store.start()
        with pytest.raises(BtApiStoreError, match="store_sdk_start_already_in_progress"):
            store.stop()
    finally:
        release_api_initialization.set()
        start_thread.join(2)

    assert not start_thread.is_alive()
    assert not start_errors
    assert ensure_calls == 1
    assert store._stream_generation == 1
    assert store._has_successful_sdk_stream_generation is True
    assert store._sdk_start_in_progress is False
    assert store.stop()["shutdown_state"] == "PASS"


def test_start_is_rejected_while_stop_is_in_progress(monkeypatch):
    import backtrader.stores.btapistore as btapistore_module

    store = _store()
    _start_without_external_io(monkeypatch, store)
    stop_entered = threading.Event()
    release_stop = threading.Event()
    stop_results = []
    stop_errors = []
    original_stop_store = btapistore_module._stop_store

    def blocked_stop_store(*args, **kwargs):
        stop_entered.set()
        if not release_stop.wait(2):
            raise AssertionError("timed out waiting to release Store stop")
        return original_stop_store(*args, **kwargs)

    monkeypatch.setattr(btapistore_module, "_stop_store", blocked_stop_store)

    def run_stop():
        try:
            stop_results.append(store.stop())
        except BaseException as exc:
            stop_errors.append(exc)

    stop_thread = threading.Thread(target=run_stop, daemon=True)
    stop_thread.start()
    try:
        assert stop_entered.wait(1)
        with pytest.raises(BtApiStoreError, match="store_sdk_stop_already_in_progress"):
            store.start()
    finally:
        release_stop.set()
        stop_thread.join(2)

    assert not stop_thread.is_alive()
    assert not stop_errors
    assert len(stop_results) == 1 and stop_results[0]["shutdown_state"] == "PASS"
    assert store._started is False and store._connected is False
    assert store._sdk_stop_in_progress is False
    store.start()
    assert store._stream_generation == 2
    assert store._started is True
    assert store.stop()["shutdown_state"] == "PASS"


def test_new_sdk_stream_generation_discards_previous_bar_queue_state():
    store = _store()
    # Establish a successfully started generation before publishing its bars.
    # API readiness/funding are isolated so this stays a no-network lifecycle test.
    store._ensure_api_ready = lambda: None
    store._begin_funding_refresh_generation = lambda: None
    store.start()
    store._enqueue_live_bar("SA", {"close": 1})
    store._enqueue_live_bar("SA", {"close": 2})
    store._enqueue_live_bar("SA", {"close": 3})

    assert store._live_bar_queue.snapshot("SA") == (
        2,
        1,
        "store_live_bar_queue_overflow",
    )
    assert store.is_stream_ready("SA") is False

    store.stop()
    assert store._started is False
    store.start()

    assert store._stream_generation == 2
    assert store._live_bar_queue.symbols() == ()
    assert store._live_bar_queue.snapshot("SA") == (0, 0, "")
    assert store.is_stream_ready("SA") is True


def test_new_sdk_stream_generation_waits_for_inflight_old_event_drain(monkeypatch):
    store = _store()
    _start_without_external_io(monkeypatch, store)
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
