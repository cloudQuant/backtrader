"""Offline tests for Store initialization of the completed-bar queue."""

import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.stores.btapistore import (
    BtApiMissingDependencyError,
    BtApiStore,
    BtApiStoreError,
)
from backtrader.stores import btapistore as store_module
from backtrader.service import service_read_proxy as proxy_module


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


class _FakeUnifiedApiFacade:
    def __init__(self, route="CTP___FUTURE"):
        self.route = route
        self.close_calls = 0
        self.poll_calls = []
        self.event_wakers = {}

    def list_exchanges(self):
        return [self.route]

    async def async_make_order(self, exchange_name, request, *, normalized=True, budget_capability=None):
        return {}

    async def async_cancel_order(self, exchange_name, request, *, normalized=True, budget_capability=None):
        return {}

    async def async_query_order(self, exchange_name, request, *, normalized=True):
        return {}

    def poll_events(self, exchange_name, **kwargs):
        self.poll_calls.append(exchange_name)
        return []

    def register_event_waker(self, callback):
        token = object()
        self.event_wakers[token] = callback
        return token

    def unregister_event_waker(self, token):
        return self.event_wakers.pop(token, None) is not None

    def notify_event_wakers(self):
        for callback in tuple(self.event_wakers.values()):
            callback()

    def get_execution_summary(self):
        return {}

    def close(self):
        self.close_calls += 1


class _QueueBacklogApi(_FakeUnifiedApiFacade):
    """Exercise the Store boundary with a real FIFO and explicit ownership."""

    def __init__(self, route="CTP___FUTURE"):
        super().__init__(route=route)
        self.event_queue = queue.Queue()

    def poll_events(self, exchange_name, **kwargs):
        self.poll_calls.append(exchange_name)
        events = []
        while True:
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                return events

    def queued_events(self):
        with self.event_queue.mutex:
            return tuple(self.event_queue.queue)


def _borrowed_api_store(api, *, config=None, live_bars=None):
    return BtApiStore(
        api=api,
        config=config or {"exchange_kwargs": {api.route: {}}},
        live_bars=live_bars,
        autostart=False,
        preserve_raw_bars=True,
    )


def _service_read_only_store(monkeypatch):
    """Build the exact production proxy type with inert transport leaves."""
    monkeypatch.setattr(
        proxy_module,
        "validate_service_account_client",
        lambda _client: (object(), ()),
    )
    monkeypatch.setattr(
        proxy_module, "validate_service_market_bindings", lambda *_args, **_kwargs: {}
    )
    api = proxy_module.ServiceReadProxy(
        SimpleNamespace(), {}, valuation_currency="USD", position_mode="net"
    )
    calls = {
        "connect": 0,
        "disconnect": 0,
        "balance": 0,
        "positions": 0,
        "history": 0,
        "orders": 0,
        "subscribe": 0,
        "wakers": {},
    }

    def connect():
        calls["connect"] += 1

    def disconnect():
        calls["disconnect"] += 1

    def get_balance():
        calls["balance"] += 1
        return {"cash": 10.0, "value": 12.0}

    def get_positions():
        calls["positions"] += 1
        return []

    def fetch_bars(*_args, **_kwargs):
        calls["history"] += 1
        return []

    def fetch_open_orders():
        calls["orders"] += 1
        return []

    def subscribe(_dataname):
        calls["subscribe"] += 1

    def register_event_waker(callback):
        token = object()
        calls["wakers"][token] = callback
        return token

    def unregister_event_waker(token):
        return calls["wakers"].pop(token, None) is not None

    api.connect = connect
    api.disconnect = disconnect
    api.get_balance = get_balance
    api.get_positions = get_positions
    api.fetch_bars = fetch_bars
    api.fetch_open_orders = fetch_open_orders
    api.subscribe = subscribe
    api.register_event_waker = register_event_waker
    api.unregister_event_waker = unregister_event_waker
    store = BtApiStore(
        api=api,
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        autostart=False,
        preserve_raw_bars=True,
    )
    monkeypatch.setattr(
        BtApiStore, "_begin_funding_refresh_generation", lambda _self: None
    )
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda _timeout: True)
    return store, api, calls


def _account_session_workflow_values(route):
    from bt_api_py.facade_protocol import (
        AccountPreflightRequest,
        AccountPreflightSnapshot,
        AccountSessionSnapshot,
        SettlementVerificationReceipt,
    )

    now = datetime.now(timezone.utc)
    deadline = now + timedelta(seconds=30)
    request = AccountPreflightRequest(
        exchange_name=route,
        symbol="BTC-USDT",
        operation="submit",
        deadline=deadline,
    )
    session = AccountSessionSnapshot(
        exchange_name=route,
        source_ref="source-1",
        generation="generation-1",
        session_ref="session-1",
        connected=True,
        authenticated=True,
        trading_enabled=True,
        business_day="20261120",
        settlement_status="confirmed",
        observed_at=now,
        available=True,
    )
    preflight = AccountPreflightSnapshot(
        request=request,
        source_ref="source-1",
        generation="generation-1",
        observed_at=now,
        ready=False,
        available=True,
        blockers=("execution_evidence_unavailable",),
    )
    settlement = SettlementVerificationReceipt(
        exchange_name=route,
        source_ref=None,
        generation=None,
        business_day=None,
        status="unknown",
        observed_at=None,
        complete=False,
        read_only_safe=True,
        receipt_ref=None,
        reason_code="readback_unavailable",
    )
    return request, deadline, session, preflight, settlement


def _started_account_session_store(monkeypatch):
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda _timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **_kwargs: None)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_ensure_api_ready", lambda: api)
        patch.setattr(store, "get_balance", lambda **_kwargs: {"cash": 0.0, "value": 0.0})
        patch.setattr(
            BtApiStore, "_begin_funding_refresh_generation", lambda _self: None
        )
        store.start()
    store._connected = True
    return store, api


def _bind_store_owned_api(store, api):
    store._api_cls = lambda **kwargs: api
    assembly = store._ensure_sdk_direct_api_assembly()
    assert assembly.owns_api is True
    store._api = assembly.ensure_api()
    assert store._api is api
    return assembly


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


def test_live_poll_activity_prevents_start_from_resetting_its_queue_generation(
    monkeypatch,
):
    store = _store()
    _start_without_external_io(monkeypatch, store)
    store._enqueue_live_bar("SA", {"close": 1})
    pop_entered = threading.Event()
    release_pop = threading.Event()
    poll_results = []
    thread_errors = []
    original_pop = store._pop_live_bar_for_generation

    def blocked_pop(dataname):
        pop_entered.set()
        if not release_pop.wait(2):
            raise AssertionError("timed out waiting to release live-bar FIFO pop")
        return original_pop(dataname)

    monkeypatch.setattr(store, "_pop_live_bar_for_generation", blocked_pop)

    def poll_old_bar():
        try:
            poll_results.append(store.poll_live("SA"))
        except BaseException as exc:
            thread_errors.append(exc)
    poll_thread = threading.Thread(target=poll_old_bar, daemon=True)
    poll_thread.start()
    try:
        assert pop_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        with pytest.raises(
            BtApiStoreError, match="store_sdk_api_activity_in_progress"
        ):
            store.start()
        assert store._stream_generation == 1
        assert store._live_bar_queue.snapshot("SA")[0] == 1
    finally:
        release_pop.set()
        poll_thread.join(2)

    assert not poll_thread.is_alive()
    assert not thread_errors
    assert len(poll_results) == 1
    assert poll_results[0]["close"] == 1
    assert store._stream_generation == 1
    assert store._live_bar_queue.snapshot("SA")[0] == 0


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


def test_new_sdk_stream_generation_fails_fast_during_inflight_event_drain(monkeypatch):
    store = _store()
    _start_without_external_io(monkeypatch, store)
    drain_entered = threading.Event()
    reset_started = threading.Event()
    reset_finished = threading.Event()
    reset_errors = []
    thread_errors = []
    allow_drain_to_enqueue = threading.Event()
    generation = store._stream_generation

    def blocked_old_event_drain():
        drain_entered.set()
        if not allow_drain_to_enqueue.wait(2):
            raise AssertionError("timed out waiting to release the old event drain")
        store._enqueue_live_bar("SA", {"close": 10})

    monkeypatch.setattr(store, "_drain_sdk_events_locked", blocked_old_event_drain)

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
            reset_errors.append(exc)
        finally:
            reset_finished.set()

    drain_thread = threading.Thread(target=drain_old_generation, daemon=True)
    reset_thread = threading.Thread(target=reset_generation, daemon=True)
    drain_thread.start()
    try:
        assert drain_entered.wait(1)
        reset_thread.start()
        assert reset_started.wait(1)
        reset_finished_before_release = reset_finished.wait(0.2)
    finally:
        allow_drain_to_enqueue.set()
        drain_thread.join(2)
        if reset_thread.ident is not None:
            reset_thread.join(2)

    assert not drain_thread.is_alive()
    assert not reset_thread.is_alive()
    assert not thread_errors
    assert reset_finished_before_release is True
    assert len(reset_errors) == 1
    assert isinstance(reset_errors[0], BtApiStoreError)
    assert str(reset_errors[0]) == "store_sdk_event_drain_in_progress"
    assert store._stream_generation == generation
    assert store._live_bar_queue.snapshot("SA")[0] == 1
    assert store.is_stream_ready("SA") is True

    store._reset_sdk_stream_generation()
    assert store._stream_generation == generation + 1
    assert store._live_bar_queue.snapshot("SA") == (0, 0, "")


def test_stop_does_not_close_sdk_api_during_poll_and_keeps_returned_event_order(
    monkeypatch,
):
    import backtrader.stores.btapistore as btapistore_module

    store = _store()
    _start_without_external_io(monkeypatch, store)
    poll_entered = threading.Event()
    release_poll = threading.Event()
    poll_finished = threading.Event()
    api_closed = threading.Event()
    stop_finished = threading.Event()
    handoff = []
    poll_errors = []
    stop_errors = []
    stop_results = []
    stop_timeouts = []
    generation = store._stream_generation
    shutdown_state = store._shutdown_state
    original_stop_store = btapistore_module._stop_store

    def capture_stop_timeout(*args, **kwargs):
        stop_timeouts.append(args[1])
        return original_stop_store(*args, **kwargs)

    monkeypatch.setattr(btapistore_module, "_stop_store", capture_stop_timeout)

    class BlockingPollApi(_FakeUnifiedApiFacade):
        def poll_events(self, venue, **kwargs):
            poll_entered.set()
            if not release_poll.wait(2):
                raise AssertionError("timed out waiting to release SDK poll_events")
            return [
                {"kind": "order", "symbol": "SA", "sequence": 1},
                {"kind": "account", "symbol": "SA", "sequence": 2},
            ]

        def get_execution_summary(self):
            return {}

        def close(self):
            self.close_calls += 1
            api_closed.set()

    api = BlockingPollApi()
    _bind_store_owned_api(store, api)
    monkeypatch.setattr(
        store,
        "_sdk_broker_event",
        lambda venue, event: {"kind": event["kind"], "sequence": event["sequence"]},
    )
    monkeypatch.setattr(
        store,
        "_append_sdk_update",
        lambda update: handoff.append((update["kind"], update["sequence"])),
    )
    monkeypatch.setattr(
        store,
        "_apply_sdk_account_push",
        lambda venue, event: handoff.append((event["kind"], event["sequence"])),
    )
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    def drain():
        try:
            store._drain_sdk_events()
        except BaseException as exc:  # preserve worker failures for the test thread
            poll_errors.append(exc)
        finally:
            poll_finished.set()

    def stop():
        try:
            stop_results.append(store.stop(timeout=1.0))
        except BaseException as exc:  # preserve worker failures for the test thread
            stop_errors.append(exc)
        finally:
            stop_finished.set()

    drain_thread = threading.Thread(target=drain, daemon=True)
    stop_thread = threading.Thread(target=stop, daemon=True)
    drain_thread.start()
    try:
        assert poll_entered.wait(1)
        event_lock_available_during_poll = store._sdk_event_drain_lock.acquire(timeout=0.2)
        if event_lock_available_during_poll:
            store._sdk_event_drain_lock.release()
        with pytest.raises(BtApiStoreError, match="store_sdk_event_drain_in_progress"):
            store.start()
        with pytest.raises(BtApiStoreError, match="store_sdk_event_drain_wait_timeout"):
            store.stop(timeout=0)
        assert api_closed.is_set() is False
        assert store._started is True
        assert store._stream_generation == generation
        assert store._shutdown_state == shutdown_state
        stop_thread.start()
        stop_returned_before_poll = stop_finished.wait(0.2)
        closed_before_poll_release = api_closed.is_set() and not poll_finished.is_set()
        started_before_poll_release = store._started
        connected_before_poll_release = store._connected
        generation_before_poll_release = store._stream_generation
        shutdown_before_poll_release = store._shutdown_state
    finally:
        release_poll.set()
        drain_thread.join(2)
        if stop_thread.ident is not None:
            stop_thread.join(2)

    assert not drain_thread.is_alive()
    assert not stop_thread.is_alive()
    assert not poll_errors
    assert stop_returned_before_poll is False
    assert event_lock_available_during_poll is True
    assert handoff == [("order", 1), ("account", 2)]
    assert not stop_errors
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert len(stop_timeouts) == 1 and 0 < stop_timeouts[0] < 1.0
    assert closed_before_poll_release is False
    assert started_before_poll_release is True
    assert connected_before_poll_release is False
    assert generation_before_poll_release == generation
    assert shutdown_before_poll_release == shutdown_state
    assert store._stream_generation == generation

    assert api_closed.is_set()


def test_stop_drain_wait_timeout_is_bounded_and_preserves_resources(monkeypatch):
    import backtrader.stores.btapistore as btapistore_module

    store = _store()
    _start_without_external_io(monkeypatch, store)
    store._command_shutdown_timeout = 0.03
    poll_entered = threading.Event()
    release_poll = threading.Event()
    api_closed = threading.Event()
    poll_errors = []
    stop_timeouts = []
    original_stop_store = btapistore_module._stop_store

    def capture_stop_timeout(*args, **kwargs):
        stop_timeouts.append(args[1])
        return original_stop_store(*args, **kwargs)

    monkeypatch.setattr(btapistore_module, "_stop_store", capture_stop_timeout)

    class BlockingPollApi(_FakeUnifiedApiFacade):
        def poll_events(self, venue, **kwargs):
            poll_entered.set()
            if not release_poll.wait(2):
                raise AssertionError("timed out waiting to release SDK poll_events")
            return []

        def get_execution_summary(self):
            return {}

        def close(self):
            self.close_calls += 1
            api_closed.set()

    _bind_store_owned_api(store, BlockingPollApi())
    generation = store._stream_generation
    shutdown_state = store._shutdown_state

    def drain():
        try:
            store._drain_sdk_events()
        except BaseException as exc:
            poll_errors.append(exc)

    drain_thread = threading.Thread(target=drain, daemon=True)
    drain_thread.start()
    try:
        assert poll_entered.wait(1)
        started = time.monotonic()
        with pytest.raises(BtApiStoreError, match="store_sdk_event_drain_wait_timeout"):
            store.stop()
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        assert api_closed.is_set() is False
        assert store._started is True
        assert store._stream_generation == generation
        assert store._shutdown_state == shutdown_state
        assert store._sdk_stop_in_progress is False
        assert store._sdk_event_drain_in_progress is True
        assert stop_timeouts == []
    finally:
        release_poll.set()
        drain_thread.join(2)

    assert not drain_thread.is_alive()
    assert not poll_errors
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert api_closed.is_set()
    assert len(stop_timeouts) == 1


@pytest.mark.parametrize("caller", ["cerebro", "broker"])
def test_framework_stop_callers_report_drain_timeout_without_retry(monkeypatch, caller):
    store = _store()
    _start_without_external_io(monkeypatch, store)
    store._command_shutdown_timeout = 0.0
    shutdown_state = store._shutdown_state
    poll_entered = threading.Event()
    release_poll = threading.Event()
    api_closed = threading.Event()
    drain_errors = []

    class BlockingPollApi:
        def poll_events(self, venue, **kwargs):
            poll_entered.set()
            if not release_poll.wait(2):
                raise AssertionError("timed out waiting to release SDK poll_events")
            return []

        def get_execution_summary(self):
            return {}

        def close(self):
            api_closed.set()

    store._api = BlockingPollApi()
    store._connected = True

    def drain():
        try:
            store._drain_sdk_events()
        except BaseException as exc:
            drain_errors.append(exc)

    drain_thread = threading.Thread(target=drain, daemon=True)
    drain_thread.start()
    try:
        assert poll_entered.wait(1)
        if caller == "cerebro":
            from backtrader.cerebro import Cerebro

            cerebro = Cerebro()
            primary = RuntimeError("synthetic_startup_failure")
            attempts = {
                "stores": [store],
                "brokers": [],
                "feeds": [],
                "datas": [],
                "strategy_attempts": [],
                "started_strategies": [],
                "writers": [],
                "timers": [],
            }
            cerebro._cleanup_startup_attempts(attempts, primary, predata=False)
            incomplete = primary._backtrader_startup_cleanup_incomplete
            assert any(
                phase == "store[0].stop" and reason == "stop raised; state is unknown"
                for phase, _component, reason in incomplete
            )
        else:
            from backtrader.brokers.btapibroker import BtApiBroker

            broker = BtApiBroker(store=store)
            with pytest.raises(BtApiStoreError, match="store_sdk_event_drain_wait_timeout"):
                broker.stop()
            assert broker._shutdown_summary["status"] == "FAIL"
            assert broker._shutdown_summary["store_shutdown_state"] == "UNPROVEN"

        assert store._started is True
        assert store._connected is True
        assert store._shutdown_state == shutdown_state
        assert store._sdk_event_drain_in_progress is True
        assert store._sdk_stop_in_progress is False
        assert api_closed.is_set() is False
    finally:
        release_poll.set()
        drain_thread.join(2)

    assert not drain_thread.is_alive()
    assert not drain_errors
    assert api_closed.is_set() is False


def test_stop_slot_prevents_a_new_sdk_event_poll(monkeypatch):
    import backtrader.stores.btapistore as btapistore_module

    store = _store()
    _start_without_external_io(monkeypatch, store)
    stop_entered = threading.Event()
    release_stop = threading.Event()
    stop_finished = threading.Event()
    stop_errors = []
    poll_calls = []

    class PollCountingApi:
        def poll_events(self, venue, **kwargs):
            poll_calls.append(venue)
            return []

    store._api = PollCountingApi()

    def blocked_stop_store(*args, **kwargs):
        stop_entered.set()
        if not release_stop.wait(2):
            raise AssertionError("timed out waiting to release Store stop")
        return {"shutdown_state": "PASS"}

    monkeypatch.setattr(btapistore_module, "_stop_store", blocked_stop_store)

    def stop():
        try:
            store.stop(timeout=0.2)
        except BaseException as exc:  # preserve worker failures for the test thread
            stop_errors.append(exc)
        finally:
            stop_finished.set()

    stop_thread = threading.Thread(target=stop, daemon=True)
    stop_thread.start()
    try:
        assert stop_entered.wait(1)
        store._drain_sdk_events()
        assert poll_calls == []
        assert store._sdk_event_drain_in_progress is False
    finally:
        release_stop.set()
        stop_thread.join(2)

    assert not stop_thread.is_alive()
    assert stop_finished.is_set()
    assert not stop_errors
    assert poll_calls == []


def test_sdk_event_drain_lease_is_released_after_poll_exception():
    store = _store()
    poll_calls = []

    class FailOncePollApi:
        def poll_events(self, venue, **kwargs):
            poll_calls.append(venue)
            if len(poll_calls) == 1:
                raise RuntimeError("synthetic_poll_failure")
            return []

    store._api = FailOncePollApi()

    with pytest.raises(RuntimeError, match="synthetic_poll_failure"):
        store._drain_sdk_events()

    assert store._sdk_event_drain_in_progress is False
    assert poll_calls == ["CTP___FUTURE"]

    store._drain_sdk_events()
    assert store._sdk_event_drain_in_progress is False
    assert poll_calls == ["CTP___FUTURE", "CTP___FUTURE"]


@pytest.mark.parametrize("contract_state", ["missing", "non_callable"])
def test_sdk_event_contract_is_preflighted_before_poll(monkeypatch, contract_state):
    import builtins

    import bt_api_py.market_stream_contracts as market_contracts

    store = _store()
    poll_calls = []

    class PollCountingApi:
        def poll_events(self, venue, **kwargs):
            poll_calls.append(venue)
            return [{"kind": "bar", "symbol": "SA"}]

    store._api = PollCountingApi()
    original_import = builtins.__import__
    if contract_state == "missing":

        def fail_market_contract_import(name, *args, **kwargs):
            if name == "bt_api_py.market_stream_contracts":
                raise ImportError("synthetic_missing_market_contract")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_market_contract_import)
    else:
        monkeypatch.setattr(market_contracts, "decode_market_event_continuity", None)

    with pytest.raises(BtApiMissingDependencyError, match="market event continuity contract"):
        store._drain_sdk_events()

    assert poll_calls == []
    assert store._sdk_event_drain_in_progress is False


def test_normal_stop_keeps_injected_shared_api_borrowed(monkeypatch):
    api = _FakeUnifiedApiFacade()
    first = _borrowed_api_store(api)
    second = _borrowed_api_store(api)

    for store in (first, second):
        assembly = store._ensure_sdk_direct_api_assembly()
        assert assembly.api is api
        assert assembly.owns_api is False
        store._started = True
        store._connected = True
        store._sdk_configured = True
        monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
        monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    first_wakes = []
    second_wakes = []
    first._register_live_bar_event_waker(lambda: first_wakes.append("wake"))
    second._register_live_bar_event_waker(lambda: second_wakes.append("wake"))
    assert len(api.event_wakers) == 2

    first_result = first.stop(timeout=0.2)
    assert first_result["shutdown_state"] == "PASS"
    assert first_result["sdk_api_ownership"] == "CALLER_BORROWED"
    assert first_result["sdk_api_close_state"] == "NOT_CLOSED_BY_STORE"
    assert api.close_calls == 0
    assert len(api.event_wakers) == 1
    assert second._started is True
    assert second._api is api
    first_wakes_after_stop = len(first_wakes)
    second_wakes_before_sdk_event = len(second_wakes)
    api.notify_event_wakers()
    assert len(first_wakes) == first_wakes_after_stop
    assert len(second_wakes) == second_wakes_before_sdk_event + 1

    second_result = second.stop(timeout=0.2)
    assert second_result["shutdown_state"] == "PASS"
    assert second_result["sdk_api_ownership"] == "CALLER_BORROWED"
    assert second_result["sdk_api_close_state"] == "NOT_CLOSED_BY_STORE"
    assert api.close_calls == 0
    assert api.poll_calls == []
    assert api.event_wakers == {}
    assert first._api is api and second._api is api


def test_injected_api_readiness_failure_does_not_close_borrowed_facade(monkeypatch):
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    survivor = _borrowed_api_store(api)
    failed_store_wakes = []
    survivor_wakes = []
    store._register_live_bar_event_waker(lambda: failed_store_wakes.append("wake"))
    survivor._register_live_bar_event_waker(lambda: survivor_wakes.append("wake"))
    assert len(api.event_wakers) == 2
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **kwargs: None)
    monkeypatch.setattr(store, "_recover_sdk_startup_journal", lambda: None)

    def fail_readiness():
        raise RuntimeError("synthetic_account_readiness_failure")

    monkeypatch.setattr(store, "get_balance", fail_readiness)

    with pytest.raises(RuntimeError, match="synthetic_account_readiness_failure"):
        store.start()

    assert store._sdk_direct_api_assembly is not None
    assert store._sdk_direct_api_assembly.api is api
    assert store._sdk_direct_api_assembly.owns_api is False
    assert store._sdk_owned_api is False
    assert api.close_calls == 0
    assert store._api is api
    assert store._connected is False
    assert store._started is False
    assert api.event_wakers
    assert len(api.event_wakers) == 1
    failed_store_wakes_after_failure = len(failed_store_wakes)
    survivor_wakes_before_sdk_event = len(survivor_wakes)
    api.notify_event_wakers()
    assert len(failed_store_wakes) == failed_store_wakes_after_failure
    assert len(survivor_wakes) == survivor_wakes_before_sdk_event + 1
    assert api.close_calls == 0
    health = store.get_command_health()
    assert health["sdk_api_ownership"] == "CALLER_BORROWED"
    assert health["sdk_api_close_state"] == "NOT_CLOSED_BY_STORE"


def test_synchronous_sdk_stop_does_not_close_injected_api(monkeypatch):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    survivor = _borrowed_api_store(api)
    assembly = store._ensure_sdk_direct_api_assembly()
    assert assembly.api is api and assembly.owns_api is False
    stopped_store_wakes = []
    survivor_wakes = []
    store._register_live_bar_event_waker(lambda: stopped_store_wakes.append("wake"))
    survivor._register_live_bar_event_waker(lambda: survivor_wakes.append("wake"))
    assert len(api.event_wakers) == 2
    store._started = True
    store._connected = True
    store._sdk_configured = True
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    result = store.stop(timeout=0.2)

    assert result["shutdown_state"] == "PASS"
    assert result["sdk_api_ownership"] == "CALLER_BORROWED"
    assert result["sdk_api_close_state"] == "NOT_CLOSED_BY_STORE"
    assert api.close_calls == 0
    assert len(api.event_wakers) == 1
    assert store._api is api
    stopped_store_wakes_after_stop = len(stopped_store_wakes)
    survivor_wakes_before_sdk_event = len(survivor_wakes)
    api.notify_event_wakers()
    assert len(stopped_store_wakes) == stopped_store_wakes_after_stop
    assert len(survivor_wakes) == survivor_wakes_before_sdk_event + 1


def test_stop_without_assembly_keeps_injected_api_borrowed(monkeypatch):
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    assert store._sdk_direct_api_assembly is None
    store._started = True
    store._connected = True
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    result = store.stop(timeout=0.2)

    assert result["shutdown_state"] == "PASS"
    assert result["sdk_api_ownership"] == "CALLER_BORROWED"
    assert result["sdk_api_close_state"] == "NOT_CLOSED_BY_STORE"
    assert api.close_calls == 0
    assert api.poll_calls == []
    assert store._api is api


def test_owned_factory_api_is_closed_by_direct_api_assembly(monkeypatch):
    api = _FakeUnifiedApiFacade()
    store = BtApiStore(
        api_cls=lambda **kwargs: api,
        config={"exchange_kwargs": {api.route: {}}},
        autostart=False,
    )
    assembly = store._ensure_sdk_direct_api_assembly()
    assert assembly.owns_api is True
    store._api = assembly.ensure_api()
    assert store._api is api
    assert assembly.owns_api is True
    store._started = True
    store._connected = True
    store._sdk_configured = True
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    result = store.stop(timeout=0.2)

    assert result["shutdown_state"] == "PASS"
    assert result["sdk_api_ownership"] == "STORE_OWNED"
    assert result["sdk_api_close_state"] == "CLOSED_BY_STORE"
    assert api.close_calls == 1
    assert store._api is None


def test_stopped_borrowed_api_fails_closed_without_consuming_order_account_backlog(
    monkeypatch,
):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _QueueBacklogApi()
    store = _borrowed_api_store(api, live_bars={"SA": [{"close": 9}]})
    ensure_calls = []
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: ensure_calls.append(api) or api)
    monkeypatch.setattr(BtApiStore, "_begin_funding_refresh_generation", lambda self: None)
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    store.start()
    assert store._has_successful_sdk_stream_generation is True
    generation = store._stream_generation

    pending = (
        {"kind": "order", "symbol": "SA", "sequence": 1},
        {"kind": "account", "symbol": "SA", "sequence": 2},
    )
    for event in pending:
        api.event_queue.put(event)

    health = store.stop()
    assert health["shutdown_state"] == "PASS"
    assert store._started is False
    assert store._api is api
    assert api.close_calls == 0
    assert api.poll_calls == []
    assert api.queued_events() == pending
    assert store._live_bar_queue.snapshot("SA")[0] == 1

    with pytest.raises(
        BtApiStoreError,
        match="store_borrowed_sdk_api_restart_requires_fresh_facade",
    ):
        store.start()
    with pytest.raises(
        BtApiStoreError,
        match="store_borrowed_sdk_api_restart_requires_fresh_facade",
    ):
        store.poll_execution_maintenance()
    with pytest.raises(
        BtApiStoreError,
        match="store_borrowed_sdk_api_restart_requires_fresh_facade",
    ):
        store.poll_live("SA")

    assert store._stream_generation == generation
    assert store._started is False
    assert store._api is api
    assert len(ensure_calls) == 1  # restart/live refusal preceded API readiness
    assert api.close_calls == 0
    assert api.poll_calls == []
    assert api.queued_events() == pending
    assert store._live_bar_queue.snapshot("SA")[0] == 1


def test_stopped_borrowed_readiness_cannot_rebind_notifier_or_read_account(
    monkeypatch,
):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _QueueBacklogApi()
    store = _borrowed_api_store(api)
    pending = {"kind": "account", "symbol": "SA", "sequence": 1}
    api.event_queue.put(pending)

    # Establish a completed Store generation using the existing lifecycle
    # fixture, then bind the notifier as a live Store would before shutdown.
    with monkeypatch.context() as patch:
        patch.setattr(store, "_ensure_api_ready", lambda: api)
        patch.setattr(BtApiStore, "_begin_funding_refresh_generation", lambda self: None)
        patch.setattr(store, "get_balance", lambda **kwargs: {"cash": 0.0, "value": 0.0})
        store.start()
    store._connected = True
    store._bind_live_bar_event_notifier(api, store._signal_live_bar_event)
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert store._started is False
    assert api.event_wakers == {}
    assert store._event_notifier.has_sdk_binding is False

    readiness_calls = []
    monkeypatch.setattr(
        store,
        "_ensure_api_ready_under_activity",
        lambda: readiness_calls.append(True) or api,
    )
    with pytest.raises(
        BtApiStoreError,
        match="store_borrowed_sdk_api_restart_requires_fresh_facade",
    ):
        store.get_balance()

    assert readiness_calls == []
    assert store._event_notifier.has_sdk_binding is False
    assert api.event_wakers == {}
    assert api.close_calls == 0
    assert api.poll_calls == []
    assert api.queued_events() == (pending,)


@pytest.mark.parametrize(
    "operation",
    [
        "live",
        "broker",
        "tick",
        "orderbook",
        "pending_tick",
        "pending_orderbook",
        "supports_tick",
        "supports_orderbook",
        "source_exhausted",
        "watermark",
        "resync",
        "subscribe",
    ],
)
def test_stop_waits_for_sdk_activity_before_api_readiness(monkeypatch, operation):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _QueueBacklogApi()
    store = _borrowed_api_store(api)
    waker_token = store._register_live_bar_event_waker(lambda: None)
    _start_without_external_io(monkeypatch, store)
    store._unbind_live_bar_event_notifier()
    store._connected = True
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    if operation in {"tick", "orderbook", "pending_tick", "pending_orderbook"}:
        monkeypatch.setattr(store, "_poll_sdk_market_stream", lambda *args, **kwargs: None)
    if operation in {"supports_tick", "supports_orderbook"}:
        monkeypatch.setattr(
            store._market_stream_adapter,
            "supports_channel",
            lambda *args, **kwargs: False,
        )
    if operation == "resync":
        monkeypatch.setattr(
            store._market_stream_adapter,
            "accept_resync",
            lambda *args, **kwargs: (None, 0),
        )
        monkeypatch.setattr(store, "_record_market_stream_queue_state", lambda *args: None)
    if operation == "subscribe":
        store._market_channels = ("tick",)
        monkeypatch.setattr(
            store, "_start_sdk_market_stream_subscription", lambda *args, **kwargs: True
        )

    ensure_entered = threading.Event()
    release_ensure = threading.Event()
    operation_results = []
    operation_errors = []
    prior_generation = store._stream_generation
    prior_shutdown_state = store._shutdown_state

    def blocked_api_readiness():
        ensure_entered.set()
        if not release_ensure.wait(2):
            raise AssertionError("timed out waiting to release API readiness")
        store._bind_live_bar_event_notifier(api, store._signal_live_bar_event)
        return api

    monkeypatch.setattr(store, "_ensure_api_ready", blocked_api_readiness)

    def invoke_operation():
        try:
            if operation == "live":
                result = store.poll_live("SA")
            elif operation == "broker":
                result = store.poll_broker_update()
            elif operation == "tick":
                result = store.poll_tick("SA")
            elif operation == "orderbook":
                result = store.poll_orderbook("SA", depth=1)
            elif operation == "pending_tick":
                result = store.has_pending_tick("SA")
            elif operation == "pending_orderbook":
                result = store.has_pending_orderbook("SA")
            elif operation == "supports_tick":
                result = store.supports_live_ticks("SA")
            elif operation == "supports_orderbook":
                result = store.supports_live_orderbook("SA")
            elif operation == "source_exhausted":
                result = store.is_source_exhausted("SA")
            elif operation == "watermark":
                result = store.get_source_event_time_watermark("SA")
            elif operation == "resync":
                result = store.accept_market_stream_resync(
                    "SA", "tick", acknowledge_data_loss=True
                )
            else:
                result = store.subscribe("SA", channels=("tick",))
            operation_results.append(result)
        except BaseException as exc:
            operation_errors.append(exc)

    operation_thread = threading.Thread(target=invoke_operation, daemon=True)
    operation_thread.start()
    try:
        assert ensure_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        lock_available_during_readiness = store._sdk_start_state_lock.acquire(
            timeout=0.2
        )
        if lock_available_during_readiness:
            store._sdk_start_state_lock.release()
        with pytest.raises(
            BtApiStoreError, match="store_sdk_api_activity_in_progress"
        ):
            store.start()
        assert store._stream_generation == prior_generation

        with pytest.raises(
            BtApiStoreError, match="store_sdk_event_drain_wait_timeout"
        ):
            store.stop(timeout=0.03)
        assert store._started is True
        assert store._connected is True
        assert store._stream_generation == prior_generation
        assert store._shutdown_state == prior_shutdown_state
        assert store._sdk_stop_in_progress is False
        assert api.close_calls == 0
        assert api.event_wakers == {}
    finally:
        release_ensure.set()
        operation_thread.join(2)

    assert not operation_thread.is_alive()
    assert not operation_errors
    assert len(operation_results) == 1
    assert lock_available_during_readiness is True
    assert store._sdk_api_activity_count == 0
    assert len(api.event_wakers) == 1
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert store._started is False
    assert api.event_wakers == {}
    assert api.close_calls == 0
    store._unregister_live_bar_event_waker(waker_token)


def test_poll_live_fast_fifo_handoff_is_part_of_stop_activity(monkeypatch):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _QueueBacklogApi()
    seeded_bar = {"close": 12.5}
    store = BtApiStore(
        api=api,
        config={"exchange_kwargs": {api.route: {}}, "live_bar_queue_size": 2},
        live_bars={"SA": [seeded_bar]},
        autostart=False,
        preserve_raw_bars=True,
    )
    _start_without_external_io(monkeypatch, store)
    store._connected = True
    waker_token = store._register_live_bar_event_waker(lambda: None)
    store._bind_live_bar_event_notifier(api, store._signal_live_bar_event)
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    pop_entered = threading.Event()
    release_pop = threading.Event()
    polled_bars = []
    poll_errors = []
    original_pop = store._pop_live_bar_for_generation

    def blocked_pop(dataname):
        pop_entered.set()
        if not release_pop.wait(2):
            raise AssertionError("timed out waiting to release live-bar FIFO pop")
        return original_pop(dataname)

    monkeypatch.setattr(store, "_pop_live_bar_for_generation", blocked_pop)

    def poll_seeded_bar():
        try:
            polled_bars.append(store.poll_live("SA"))
        except BaseException as exc:
            poll_errors.append(exc)

    poll_thread = threading.Thread(target=poll_seeded_bar, daemon=True)
    poll_thread.start()
    try:
        assert pop_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        assert store._live_bar_queue.snapshot("SA")[0] == 1

        with pytest.raises(
            BtApiStoreError, match="store_sdk_event_drain_wait_timeout"
        ):
            store.stop(timeout=0.03)
        assert store._started is True
        assert store._connected is True
        assert store._shutdown_state != "PASS"
        assert store._sdk_stop_in_progress is False
        assert store._live_bar_queue.snapshot("SA")[0] == 1
        assert store._event_notifier.has_sdk_binding is True
        assert len(api.event_wakers) == 1
        assert api.close_calls == 0
    finally:
        release_pop.set()
        poll_thread.join(2)

    assert not poll_thread.is_alive()
    assert not poll_errors
    assert len(polled_bars) == 1
    assert polled_bars[0]["close"] == seeded_bar["close"]
    assert store._sdk_api_activity_count == 0
    assert store._live_bar_queue.snapshot("SA")[0] == 0

    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert store._started is False
    assert store._event_notifier.has_sdk_binding is False
    assert api.event_wakers == {}
    assert api.close_calls == 0
    store._unregister_live_bar_event_waker(waker_token)


def test_stop_reentry_from_sdk_activity_fails_without_deadlock(monkeypatch):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _QueueBacklogApi()
    store = _borrowed_api_store(api)
    _start_without_external_io(monkeypatch, store)
    store._connected = True
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    def readiness_with_reentrant_stop():
        with pytest.raises(
            BtApiStoreError, match="store_sdk_stop_from_active_api_activity"
        ):
            store.stop(timeout=0)
        return api

    monkeypatch.setattr(store, "_ensure_api_ready", readiness_with_reentrant_stop)
    assert store.poll_live("SA") is None
    assert store._started is True
    assert store._connected is True
    assert store._sdk_api_activity_count == 0
    assert store._sdk_stop_in_progress is False

    assert store._begin_sdk_event_drain() is True
    try:
        with pytest.raises(
            BtApiStoreError, match="store_sdk_stop_from_event_drain"
        ):
            store.stop(timeout=0)
    finally:
        store._finish_sdk_event_drain()

    assert store._sdk_stop_in_progress is False
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert api.close_calls == 0


def test_partial_borrowed_api_start_does_not_reuse_source_after_verified_stop(
    monkeypatch,
):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    api = _QueueBacklogApi()
    pending = {"kind": "account", "symbol": "SA", "sequence": 1}
    api.event_queue.put(pending)
    store = _borrowed_api_store(api)
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: api)
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    def fail_after_store_start():
        raise RuntimeError("funding_generation_failed")

    monkeypatch.setattr(
        store, "_begin_funding_refresh_generation", fail_after_store_start
    )
    with pytest.raises(RuntimeError, match="funding_generation_failed"):
        store.start()

    assert store._started is True
    assert store._has_successful_sdk_stream_generation is False
    assert store._sdk_partial_start_failed_generation == store._stream_generation
    assert store._sdk_borrowed_event_source_retired is True
    assert api.poll_calls == []
    assert api.queued_events() == (pending,)

    health = store.stop()
    assert health["shutdown_state"] == "PASS"
    assert store._started is False
    # PASS covers Store-owned work only; the borrowed facade still has an
    # unproven source lifecycle, so the partial-start restart fence remains.
    assert store._sdk_partial_start_failed_generation == store._stream_generation
    assert store._sdk_borrowed_event_source_retired is True

    with pytest.raises(
        BtApiStoreError,
        match="store_partial_sdk_start_requires_verified_stop",
    ):
        store.start()
    with pytest.raises(
        BtApiStoreError,
        match="store_borrowed_sdk_api_restart_requires_fresh_facade",
    ):
        store.poll_execution_maintenance()
    assert api.close_calls == 0
    assert api.poll_calls == []
    assert api.queued_events() == (pending,)


def test_service_first_start_leases_readiness_and_stopped_store_rejects_restart(
    monkeypatch,
):
    store, api, calls = _service_read_only_store(monkeypatch)
    waker_token = store._register_live_bar_event_waker(lambda: None)
    entered, release = threading.Event(), threading.Event()
    start_results, start_errors = [], []

    def blocked_initial_balance():
        calls["balance"] += 1
        entered.set()
        if not release.wait(2):
            raise AssertionError("timed out waiting to release initial service balance")
        return {"cash": 21.0, "value": 24.0}

    api.get_balance = blocked_initial_balance

    def start_store():
        try:
            start_results.append(store.start())
        except BaseException as exc:
            start_errors.append(exc)

    start_thread = threading.Thread(target=start_store, daemon=True)
    start_thread.start()
    try:
        assert entered.wait(1)
        assert store._sdk_start_in_progress is True
        assert store._sdk_api_activity_count >= 1
        assert calls["connect"] == 1
        assert store._event_notifier.has_sdk_binding is True
        with pytest.raises(
            BtApiStoreError, match="store_service_start_already_in_progress"
        ):
            store.stop(timeout=0.1)
        assert calls["disconnect"] == 0
        assert store._event_notifier.has_sdk_binding is True
    finally:
        release.set()
        start_thread.join(2)

    assert not start_thread.is_alive()
    assert not start_errors
    assert len(start_results) == 1
    assert store._started is True
    assert store._cash == 21.0
    assert store._value == 24.0
    assert store._sdk_api_activity_count == 0
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert calls["disconnect"] == 1
    assert calls["wakers"] == {}
    assert store._event_notifier.has_sdk_binding is False

    for refused in (lambda: store.start(), lambda: store.get_balance(),
                    lambda: store._ensure_api_ready()):
        with pytest.raises(
            BtApiStoreError,
            match="a stopped read-only service Store requires fresh client facades",
        ):
            refused()
    assert calls["connect"] == 1
    assert calls["disconnect"] == 1
    assert calls["wakers"] == {}
    assert store._event_notifier.has_sdk_binding is False
    store._unregister_live_bar_event_waker(waker_token)


def test_service_stop_waits_for_read_commit_before_unbind_and_disconnect(monkeypatch):
    store, api, calls = _service_read_only_store(monkeypatch)
    store.start()
    waker_token = store._register_live_bar_event_waker(lambda: None)
    entered, release = threading.Event(), threading.Event()
    read_results, read_errors = [], []
    stop_results, stop_errors = [], []

    def blocked_balance():
        calls["balance"] += 1
        entered.set()
        if not release.wait(2):
            raise AssertionError("timed out waiting to release service balance read")
        return {"cash": 31.0, "value": 37.0}

    def observed_disconnect():
        assert store._cash == 31.0
        assert store._value == 37.0
        assert store._last_balance_refresh is not None
        assert calls["wakers"] == {}
        calls["disconnect"] += 1

    api.get_balance = blocked_balance
    api.disconnect = observed_disconnect

    def read_balance():
        try:
            read_results.append(store.get_balance())
        except BaseException as exc:
            read_errors.append(exc)

    def stop_store():
        try:
            stop_results.append(store.stop(timeout=1.0))
        except BaseException as exc:
            stop_errors.append(exc)

    read_thread = threading.Thread(target=read_balance, daemon=True)
    read_thread.start()
    try:
        assert entered.wait(1)
        assert store._sdk_api_activity_count == 1
        stop_thread = threading.Thread(target=stop_store, daemon=True)
        stop_thread.start()
        with store._sdk_start_state_lock:
            assert store._sdk_start_state_lock.wait_for(
                lambda: store._sdk_stop_in_progress, timeout=1
            )
        assert store._sdk_api_activity_count == 1
        assert store._connected is True
        assert store._started is True
        assert store._event_notifier.has_sdk_binding is True
        assert len(calls["wakers"]) == 1
        assert calls["disconnect"] == 0
        with pytest.raises(
            BtApiStoreError, match="store_sdk_lifecycle_transition_in_progress"
        ):
            store.get_balance()
        assert calls["balance"] == 2  # first start read and this blocked read
        release.set()
        read_thread.join(2)
        stop_thread.join(2)
    finally:
        release.set()
        read_thread.join(2)
        if "stop_thread" in locals():
            stop_thread.join(2)

    assert not read_thread.is_alive()
    assert not stop_thread.is_alive()
    assert not read_errors
    assert not stop_errors
    assert read_results == [{"cash": 31.0, "value": 37.0}]
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert store._cash == 31.0
    assert store._value == 37.0
    assert store._connected is False
    assert store._started is False
    assert store._sdk_api_activity_count == 0
    assert calls["disconnect"] == 1
    assert calls["wakers"] == {}
    assert store._event_notifier.has_sdk_binding is False
    store._unregister_live_bar_event_waker(waker_token)


def test_service_close_failure_retires_store_but_allows_close_retry(monkeypatch):
    store, api, calls = _service_read_only_store(monkeypatch)
    store.start()
    waker_token = store._register_live_bar_event_waker(lambda: None)
    attempts = []

    def fail_once_then_close():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("service close failed")
        calls["disconnect"] += 1

    api.disconnect = fail_once_then_close
    balance_calls_before_close = calls["balance"]

    with pytest.raises(RuntimeError, match="service close failed"):
        store.stop(timeout=0.2)

    assert store._shutdown_state == "INCOMPLETE"
    assert store._service_read_only_stopped is True
    assert store._connected is True
    assert store._started is True
    assert store._event_notifier.has_sdk_binding is False
    assert calls["wakers"] == {}
    with pytest.raises(
        BtApiStoreError,
        match="a stopped read-only service Store requires fresh client facades",
    ):
        store.get_balance()
    with pytest.raises(
        BtApiStoreError,
        match="a stopped read-only service Store requires fresh client facades",
    ):
        store.start()
    assert calls["balance"] == balance_calls_before_close
    assert calls["connect"] == 1

    # The Store can retry its direct close operation without reopening the
    # retired facade or restoring this Store's notifier.
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert attempts == [True, True]
    assert calls["disconnect"] == 1
    assert store._connected is False
    assert store._started is False
    assert calls["wakers"] == {}
    assert store._event_notifier.has_sdk_binding is False
    store._unregister_live_bar_event_waker(waker_token)


def test_service_stop_reentry_from_active_getter_fails_without_deadlock(monkeypatch):
    store, api, calls = _service_read_only_store(monkeypatch)
    store.start()

    def getter_with_reentrant_stop():
        calls["balance"] += 1
        with pytest.raises(
            BtApiStoreError,
            match="store_service_stop_from_active_api_activity",
        ):
            store.stop(timeout=0)
        return {"cash": 41.0, "value": 43.0}

    api.get_balance = getter_with_reentrant_stop
    assert store.get_balance() == {"cash": 41.0, "value": 43.0}
    assert store._cash == 41.0
    assert store._value == 43.0
    assert store._sdk_api_activity_count == 0
    assert store._sdk_stop_in_progress is False
    assert calls["disconnect"] == 0

    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert calls["disconnect"] == 1


@pytest.mark.parametrize(
    "operation,api_method",
    [
        ("balance", "get_balance"),
        ("positions", "get_positions"),
        ("history", "fetch_bars"),
        ("open_orders", "fetch_open_orders"),
        ("live", "poll_bar"),
        ("tick", "poll_tick"),
        ("orderbook", "poll_orderbook"),
        ("pending_tick", "has_pending_tick"),
        ("pending_orderbook", "has_pending_orderbook"),
        ("supports_tick", "supports_live_ticks"),
        ("supports_orderbook", "supports_live_orderbook"),
        ("source_exhausted", "is_source_exhausted"),
        ("watermark", "get_source_event_time_watermark"),
        ("broker_update", "poll_broker_update"),
        ("subscribe", "subscribe"),
    ],
)
def test_service_direct_api_operations_hold_activity_through_call(
    monkeypatch, operation, api_method
):
    store, api, calls = _service_read_only_store(monkeypatch)
    store.start()
    waker_token = store._register_live_bar_event_waker(lambda: None)
    entered, release = threading.Event(), threading.Event()
    results, errors = [], []

    def blocked_api_call(*_args, **_kwargs):
        entered.set()
        if not release.wait(2):
            raise AssertionError(f"timed out waiting to release {operation} service call")
        return {
            "balance": {"cash": 10.0, "value": 12.0},
            "positions": [],
            "history": [],
            "open_orders": [],
            "live": None,
            "tick": None,
            "orderbook": None,
            "pending_tick": False,
            "pending_orderbook": False,
            "supports_tick": False,
            "supports_orderbook": False,
            "source_exhausted": False,
            "watermark": None,
            "broker_update": None,
            "subscribe": None,
        }[operation]

    setattr(api, api_method, blocked_api_call)

    def invoke():
        try:
            if operation == "balance":
                result = store.get_balance()
            elif operation == "positions":
                result = store.get_positions()
            elif operation == "history":
                result = store.fetch_history("SA")
            elif operation == "open_orders":
                result = store.fetch_open_orders()
            elif operation == "live":
                result = store.poll_live("SA")
            elif operation == "tick":
                result = store.poll_tick("SA")
            elif operation == "orderbook":
                result = store.poll_orderbook("SA")
            elif operation == "pending_tick":
                result = store.has_pending_tick("SA")
            elif operation == "pending_orderbook":
                result = store.has_pending_orderbook("SA")
            elif operation == "supports_tick":
                result = store.supports_live_ticks("SA")
            elif operation == "supports_orderbook":
                result = store.supports_live_orderbook("SA")
            elif operation == "source_exhausted":
                result = store.is_source_exhausted("SA")
            elif operation == "watermark":
                result = store.get_source_event_time_watermark("SA")
            elif operation == "broker_update":
                result = store.poll_broker_update()
            else:
                result = store.subscribe("SA")
            results.append(result)
        except BaseException as exc:
            errors.append(exc)

    operation_thread = threading.Thread(target=invoke, daemon=True)
    operation_thread.start()
    try:
        assert entered.wait(1)
        assert store._sdk_api_activity_count == 1
        assert len(calls["wakers"]) == 1
        with pytest.raises(
            BtApiStoreError, match="store_service_api_activity_wait_timeout"
        ):
            store.stop(timeout=0.02)
        assert store._connected is True
        assert store._started is True
        assert store._shutdown_state != "PASS"
        assert store._sdk_stop_in_progress is False
        assert store._event_notifier.has_sdk_binding is True
        assert len(calls["wakers"]) == 1
        assert calls["disconnect"] == 0
    finally:
        release.set()
        operation_thread.join(2)

    assert not operation_thread.is_alive()
    assert not errors
    assert len(results) == 1
    assert store._sdk_api_activity_count == 0
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert calls["disconnect"] == 1
    assert calls["wakers"] == {}
    assert store._event_notifier.has_sdk_binding is False
    store._unregister_live_bar_event_waker(waker_token)


@pytest.mark.parametrize(
    "operation,api_method",
    [
        ("session", "account_session_snapshot"),
        ("preflight", "account_preflight"),
        ("settlement_readback", "verify_account_settlement"),
    ],
)
@pytest.mark.parametrize("stop_timeout", [False, True])
def test_account_session_readers_hold_activity_through_api_projection(
    monkeypatch, operation, api_method, stop_timeout
):
    from bt_api_py.facade_protocol import AccountSessionWorkflowFacade

    store, api = _started_account_session_store(monkeypatch)
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **_kwargs: None)
    request, deadline, session, preflight, settlement = (
        _account_session_workflow_values(api.route)
    )
    responses = {
        "session": session,
        "preflight": preflight,
        "settlement_readback": settlement,
    }
    api.account_session_snapshot = lambda _route: session
    api.account_preflight = lambda _request: preflight
    api.verify_account_settlement = lambda _route, *, deadline: settlement
    assert isinstance(api, AccountSessionWorkflowFacade)

    entered, release = threading.Event(), threading.Event()
    calls, results, errors = [], [], []
    stop_results, stop_errors = [], []
    store._cash = 17.25
    store._value = 21.5
    account_cache_before = (store._cash, store._value)

    def blocked_read(*args, **kwargs):
        calls.append((args, kwargs))
        entered.set()
        if not release.wait(2):
            raise AssertionError(f"timed out waiting to release {operation}")
        return responses[operation]

    setattr(api, api_method, blocked_read)
    waker_token = store._register_live_bar_event_waker(lambda: None)

    def invoke():
        try:
            if operation == "session":
                result = store.account_session_snapshot(api.route)
            elif operation == "preflight":
                result = store.account_preflight(request)
            else:
                result = store.verify_account_settlement(api.route, deadline=deadline)
            results.append(result)
        except BaseException as exc:
            errors.append(exc)

    operation_thread = threading.Thread(target=invoke, daemon=True)
    operation_thread.start()
    stop_thread = None
    try:
        assert entered.wait(1)
        assert store._sdk_api_activity_count == 1
        assert store._event_notifier.has_sdk_binding is True
        assert len(api.event_wakers) == 1
        if stop_timeout:
            with pytest.raises(
                BtApiStoreError, match="store_sdk_event_drain_wait_timeout"
            ):
                store.stop(timeout=0.02)
        else:
            def stop_store():
                try:
                    stop_results.append(store.stop(timeout=1.0))
                except BaseException as exc:
                    stop_errors.append(exc)

            stop_thread = threading.Thread(target=stop_store, daemon=True)
            stop_thread.start()
            with store._sdk_start_state_lock:
                assert store._sdk_start_state_lock.wait_for(
                    lambda: store._sdk_stop_in_progress, timeout=1
                )
        assert store._connected is True
        assert store._started is True
        assert store._sdk_stop_in_progress is (not stop_timeout)
        assert store._sdk_api_activity_count == 1
        assert store._cash == account_cache_before[0]
        assert store._value == account_cache_before[1]
        assert store._event_notifier.has_sdk_binding is True
        assert len(api.event_wakers) == 1
        assert api.close_calls == 0
    finally:
        release.set()
        operation_thread.join(2)
        if stop_thread is not None:
            stop_thread.join(2)

    assert not operation_thread.is_alive()
    assert stop_thread is None or not stop_thread.is_alive()
    assert not errors
    assert not stop_errors
    assert len(calls) == 1
    assert len(results) == 1
    assert results[0] is responses[operation]
    assert store._sdk_api_activity_count == 0
    if stop_timeout:
        stop_results.append(store.stop(timeout=0.2))
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert store._started is False
    assert store._connected is False
    assert (store._cash, store._value) == account_cache_before
    assert store._event_notifier.has_sdk_binding is False
    assert api.event_wakers == {}
    assert api.close_calls == 0
    store._unregister_live_bar_event_waker(waker_token)


@pytest.mark.parametrize(
    "operation,api_method",
    [
        ("session", "account_session_snapshot"),
        ("preflight", "account_preflight"),
        ("settlement_readback", "verify_account_settlement"),
    ],
)
def test_account_session_readers_preserve_api_exceptions_and_release_activity(
    monkeypatch, operation, api_method
):
    store, api = _started_account_session_store(monkeypatch)
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **_kwargs: None)
    request, deadline, _session, _preflight, _settlement = (
        _account_session_workflow_values(api.route)
    )
    marker = RuntimeError(f"{operation} failed")
    calls = []

    def fail_read(*_args, **_kwargs):
        calls.append(True)
        raise marker

    api.account_session_snapshot = lambda _route: None
    api.account_preflight = lambda _request: None
    api.verify_account_settlement = lambda _route, *, deadline: None
    setattr(api, api_method, fail_read)

    with pytest.raises(RuntimeError) as exc:
        if operation == "session":
            store.account_session_snapshot(api.route)
        elif operation == "preflight":
            store.account_preflight(request)
        else:
            store.verify_account_settlement(api.route, deadline=deadline)

    assert exc.value is marker
    assert calls == [True]
    assert store._sdk_api_activity_count == 0


def test_account_session_input_validation_precedes_readiness(monkeypatch):
    store, _api = _started_account_session_store(monkeypatch)
    readiness_calls = []
    monkeypatch.setattr(
        store,
        "_ensure_api_ready",
        lambda: readiness_calls.append(True),
    )

    with pytest.raises(TypeError, match="exact AccountPreflightRequest"):
        store.account_preflight(object())
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        store.verify_account_settlement(
            "CTP___FUTURE", deadline=datetime.now()
        )

    assert readiness_calls == []
    assert store._sdk_api_activity_count == 0


def test_account_session_reader_is_admitted_from_start_owner_thread(monkeypatch):
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **_kwargs: None)
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda _timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    request, deadline, session, _preflight, _settlement = (
        _account_session_workflow_values(api.route)
    )
    calls = []
    api.account_session_snapshot = lambda route: calls.append(route) or session
    api.account_preflight = lambda _request: None
    api.verify_account_settlement = lambda _route, *, deadline: None
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: api)

    def start_bridge(actual_store, *_args, **_kwargs):
        actual_store._connected = True
        actual_store._started = True
        return actual_store.account_session_snapshot(api.route)

    monkeypatch.setattr(store_module, "_start_store", start_bridge)
    result = store.start()

    assert result is session
    assert calls == [api.route]
    assert store._sdk_api_activity_count == 0
    assert store._sdk_start_in_progress is False
    assert store._started is True
    assert store._connected is True
    assert request.exchange_name == api.route
    assert deadline > datetime.now(timezone.utc)


def test_owned_factory_restart_uses_a_fresh_sdk_facade(monkeypatch):
    monkeypatch.setattr(BtApiStore, "uses_async_commands", property(lambda _self: False))
    first = _FakeUnifiedApiFacade()
    second = _FakeUnifiedApiFacade()
    created = []

    def api_factory(**kwargs):
        api = (first, second)[len(created)]
        created.append(api)
        return api

    store = BtApiStore(
        api_cls=api_factory,
        config={"exchange_kwargs": {first.route: {}}},
        autostart=False,
    )
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **kwargs: None)
    monkeypatch.setattr(store, "_recover_sdk_startup_journal", lambda: None)
    monkeypatch.setattr(store, "get_balance", lambda: {})
    monkeypatch.setattr(store, "_begin_funding_refresh_generation", lambda: None)
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    monkeypatch.setattr(store, "_configure_owned_facade_calendar", lambda api: None)
    monkeypatch.setattr(store, "_attach_configured_instrument_status_ports", lambda api: None)

    store.start()
    assert store._api is first
    assert store._sdk_owned_api is True
    assert store.stop()["shutdown_state"] == "PASS"
    assert first.close_calls == 1
    assert store._api is None

    store.start()
    assert store._api is second
    assert second is not first
    assert created == [first, second]
    assert second.close_calls == 0
    assert store.stop()["shutdown_state"] == "PASS"
    assert second.close_calls == 1


@pytest.mark.parametrize("mismatch", ["ownership", "api_identity"])
def test_api_close_fails_closed_when_assembly_ownership_disagrees(monkeypatch, mismatch):
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    assembly = store._ensure_sdk_direct_api_assembly()
    assert assembly.owns_api is False
    mismatched_api = None
    if mismatch == "ownership":
        store._sdk_owned_api = True
    else:
        mismatched_api = _FakeUnifiedApiFacade()
        store._api = mismatched_api
    store._started = True
    store._connected = True
    store._sdk_configured = True
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    result = store.stop(timeout=0.2)

    assert result["shutdown_state"] == "INCOMPLETE"
    assert result["sdk_api_ownership"] == "UNPROVEN"
    assert result["sdk_api_close_state"] == "OWNERSHIP_MISMATCH"
    assert store._api is (api if mismatched_api is None else mismatched_api)
    assert api.close_calls == 0
    assert api.poll_calls == []
    if mismatched_api is not None:
        assert mismatched_api.close_calls == 0
        assert mismatched_api.poll_calls == []


def test_managed_runtime_health_fails_closed_on_api_identity_mismatch():
    api = _FakeUnifiedApiFacade()
    store = _borrowed_api_store(api)
    store._bind_managed_runtime_api(api)

    matching_health = store.get_command_health()
    assert matching_health["sdk_api_ownership"] == "MANAGED_RUNTIME_BORROWED"
    assert matching_health["sdk_api_close_state"] == "NOT_CLOSED_BY_STORE"

    store._api = _FakeUnifiedApiFacade()
    mismatch_health = store.get_command_health()

    assert mismatch_health["sdk_api_ownership"] == "UNPROVEN"
    assert mismatch_health["sdk_api_close_state"] == "OWNERSHIP_MISMATCH"


def _owned_active_store_for_read_activity(monkeypatch, api, *, on_close=None):
    store = _store()
    if on_close is not None:
        original_close = api.close

        def observed_close():
            on_close()
            original_close()

        api.close = observed_close
    _bind_store_owned_api(store, api)
    store._started = True
    store._connected = True
    store._sdk_configured = True
    store._shutdown_state = "RUNNING"
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    return store


def _start_stop_thread_waiting_for_api_activity(store):
    entered = threading.Event()
    results = []
    errors = []

    def stop_store():
        entered.set()
        try:
            results.append(store.stop(timeout=1.5))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=stop_store, daemon=True)
    thread.start()
    assert entered.wait(1)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with store._sdk_start_state_lock:
            stop_in_progress = store._sdk_stop_in_progress
        if stop_in_progress:
            break
        time.sleep(0.001)
    assert stop_in_progress is True
    return thread, results, errors


def test_get_balance_activity_covers_io_projection_and_cache_before_stop(monkeypatch):
    api = _FakeUnifiedApiFacade()
    close_snapshots = []
    store = _owned_active_store_for_read_activity(
        monkeypatch,
        api,
        on_close=lambda: close_snapshots.append((store._cash, store._value)),
    )
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: api)
    monkeypatch.setattr(store, "_facade_exchange_names", lambda _api: [api.route])
    monkeypatch.setattr(
        store,
        "_sdk_balance_snapshot_for_route",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "backtrader.stores.btapistore._require_single_balance_currency",
        lambda *args, **kwargs: None,
    )
    projection_entered = threading.Event()
    release_projection = threading.Event()

    def blocked_projection(*args, **kwargs):
        projection_entered.set()
        if not release_projection.wait(2):
            raise AssertionError("timed out waiting to release balance projection")
        return {"cash": 31.0, "value": 42.0}

    monkeypatch.setattr(
        "backtrader.stores.btapistore._project_account_balance_snapshot",
        blocked_projection,
    )
    results = []
    errors = []

    def read_balance():
        try:
            results.append(store.get_balance())
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=read_balance, daemon=True)
    reader.start()
    try:
        assert projection_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        prior_cash = store._cash
        prior_value = store._value
        with pytest.raises(
            BtApiStoreError, match="store_sdk_event_drain_wait_timeout"
        ):
            store.stop(timeout=0.03)
        assert store._started is True
        assert store._connected is True
        assert store._shutdown_state == "RUNNING"
        assert store._sdk_stop_in_progress is False
        assert store._api is api
        assert api.close_calls == 0
        assert (store._cash, store._value) == (prior_cash, prior_value)

        stopper, stop_results, stop_errors = _start_stop_thread_waiting_for_api_activity(
            store
        )
        assert api.close_calls == 0
        assert store._api is api
        release_projection.set()
        reader.join(2)
        stopper.join(2)
    finally:
        release_projection.set()
        reader.join(2)

    assert not reader.is_alive()
    assert not stopper.is_alive()
    assert not errors
    assert not stop_errors
    assert results == [{"cash": 31.0, "value": 42.0}]
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert close_snapshots == [(31.0, 42.0)]
    assert api.close_calls == 1
    assert store._api is None
    assert store._sdk_api_activity_count == 0


def test_sdk_start_owner_can_run_first_balance_read_with_activity_lease(monkeypatch):
    api = _FakeUnifiedApiFacade()
    store = _store()
    _bind_store_owned_api(store, api)
    monkeypatch.setattr(store, "_assert_write_route_identity", lambda **kwargs: None)
    monkeypatch.setattr(store, "_recover_sdk_startup_journal", lambda: None)
    monkeypatch.setattr(store, "_begin_funding_refresh_generation", lambda: None)
    monkeypatch.setattr(store, "_configure_owned_facade_calendar", lambda _api: None)
    monkeypatch.setattr(
        store, "_attach_configured_instrument_status_ports", lambda _api: None
    )
    monkeypatch.setattr(
        store,
        "_sdk_balance_snapshot_for_route",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "backtrader.stores.btapistore._require_single_balance_currency",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backtrader.stores.btapistore._project_account_balance_snapshot",
        lambda *args, **kwargs: {"cash": 7.0, "value": 9.0},
    )
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)

    store.start()

    assert store._started is True
    assert store._connected is True
    assert store._cash == 7.0
    assert store._value == 9.0
    assert store._sdk_api_activity_count == 0
    assert store._has_successful_sdk_stream_generation is True
    assert store.stop(timeout=0.2)["shutdown_state"] == "PASS"
    assert api.close_calls == 1


def test_get_positions_activity_keeps_owned_api_open_through_snapshot(monkeypatch):
    read_entered = threading.Event()
    release_read = threading.Event()
    read_finished = threading.Event()
    close_observations = []
    api = _FakeUnifiedApiFacade()
    store = _owned_active_store_for_read_activity(
        monkeypatch,
        api,
        on_close=lambda: close_observations.append(read_finished.is_set()),
    )

    def blocked_positions_read():
        read_entered.set()
        if not release_read.wait(2):
            raise AssertionError("timed out waiting to release position snapshot")
        read_finished.set()
        return [{"symbol": "SA", "size": 2.0}]

    monkeypatch.setattr(store, "_get_sdk_account_positions", blocked_positions_read)
    results = []
    errors = []

    def read_positions():
        try:
            results.append(store.get_positions())
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=read_positions, daemon=True)
    reader.start()
    try:
        assert read_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        stopper, stop_results, stop_errors = _start_stop_thread_waiting_for_api_activity(
            store
        )
        assert api.close_calls == 0
        assert store._api is api
        release_read.set()
        reader.join(2)
        stopper.join(2)
    finally:
        release_read.set()
        reader.join(2)

    assert not reader.is_alive()
    assert not stopper.is_alive()
    assert not errors
    assert not stop_errors
    assert results == [[{"symbol": "SA", "size": 2.0}]]
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert close_observations == [True]
    assert api.close_calls == 1
    assert store._api is None
    assert store._sdk_api_activity_count == 0


def test_get_account_risk_snapshot_activity_covers_sdk_cache_commit(monkeypatch):
    read_entered = threading.Event()
    release_read = threading.Event()
    close_observations = []
    api = _FakeUnifiedApiFacade()
    store = _owned_active_store_for_read_activity(
        monkeypatch,
        api,
        on_close=lambda: close_observations.append(
            store._account_risk_state.cached_snapshot(store._stream_generation)
        ),
    )
    expected = store._cached_account_risk_unavailable()

    def blocked_risk_read(_api):
        read_entered.set()
        if not release_read.wait(2):
            raise AssertionError("timed out waiting to release account-risk read")
        return store._cache_account_risk_snapshot(expected)

    monkeypatch.setattr(store, "_read_account_risk_snapshot", blocked_risk_read)
    results = []
    errors = []

    def read_risk_snapshot():
        try:
            results.append(store.get_account_risk_snapshot())
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=read_risk_snapshot, daemon=True)
    reader.start()
    try:
        assert read_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        stopper, stop_results, stop_errors = _start_stop_thread_waiting_for_api_activity(
            store
        )
        assert api.close_calls == 0
        assert store._api is api
        release_read.set()
        reader.join(2)
        stopper.join(2)
    finally:
        release_read.set()
        reader.join(2)

    assert not reader.is_alive()
    assert not stopper.is_alive()
    assert not errors
    assert not stop_errors
    assert results == [expected]
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert close_observations == [expected]
    assert api.close_calls == 1
    assert store._api is None
    assert store._sdk_api_activity_count == 0


def test_stopped_borrowed_account_risk_read_uses_only_local_state(monkeypatch):
    api = _QueueBacklogApi()
    pending_order_event = {"kind": "order", "sequence": 1}
    api.event_queue.put(pending_order_event)
    store = _borrowed_api_store(api)
    store._started = False
    store._connected = False
    store._shutdown_state = "PASS"
    store._has_successful_sdk_stream_generation = False
    monkeypatch.setattr(
        store,
        "_read_account_risk_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "stopped borrowed Store must not read its caller-owned facade"
        ),
    )

    cached = store._cache_account_risk_snapshot(
        store._cached_account_risk_unavailable()
    )
    stopped = store.get_account_risk_snapshot()
    assert stopped["evidence_complete"] is False
    assert stopped["blocked_reasons"] == ["account_risk_cache_unavailable"]
    assert store._account_risk_state.cached_snapshot(store._stream_generation) == cached
    store._account_risk_state.reset_generation()
    unavailable = store.get_account_risk_snapshot()

    assert unavailable["evidence_complete"] is False
    assert unavailable["blocked_reasons"] == ["account_risk_cache_unavailable"]
    assert api.poll_calls == []
    assert api.queued_events() == (pending_order_event,)
    assert api.close_calls == 0


def _owned_active_store_for_shutdown_risk_cache(
    monkeypatch, *, async_commands=True
):
    api = _FakeUnifiedApiFacade()
    store = _store()
    _bind_store_owned_api(store, api)
    store._started = True
    store._connected = True
    store._sdk_configured = True
    store._shutdown_state = "RUNNING"
    monkeypatch.setattr(
        BtApiStore,
        "uses_async_commands",
        property(lambda _self: async_commands),
    )
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    return store, api


@pytest.mark.parametrize("async_commands", [True, False])
def test_stop_without_risk_cache_does_not_start_sdk_risk_read(
    monkeypatch, async_commands
):
    store, api = _owned_active_store_for_shutdown_risk_cache(
        monkeypatch, async_commands=async_commands
    )
    read_entered = threading.Event()
    release_read = threading.Event()
    read_calls = []

    def blocking_risk_read(candidate):
        read_calls.append(candidate)
        read_entered.set()
        if not release_read.wait(2):
            raise AssertionError("shutdown entered a blocking SDK risk read")
        return store._cached_account_risk_unavailable()

    monkeypatch.setattr(store, "_read_account_risk_snapshot", blocking_risk_read)
    results = []
    errors = []

    def stop_store():
        try:
            results.append(store.stop(timeout=0.1))
        except BaseException as exc:
            errors.append(exc)

    stopper = threading.Thread(target=stop_store, daemon=True)
    stopper.start()
    try:
        reader_was_called = read_entered.wait(0.2)
        if reader_was_called:
            release_read.set()
        stopper.join(1.5)
    finally:
        release_read.set()
        stopper.join(1.5)

    assert not stopper.is_alive()
    assert reader_was_called is False
    assert read_calls == []
    assert not errors
    assert len(results) == 1
    assert results[0]["shutdown_state"] == "PASS"
    assert api.close_calls == 1
    assert store._api is None


@pytest.mark.parametrize("async_commands", [True, False])
def test_stop_preserves_existing_account_risk_cache_without_refresh(
    monkeypatch, async_commands
):
    store, api = _owned_active_store_for_shutdown_risk_cache(
        monkeypatch, async_commands=async_commands
    )
    expected = store._cached_account_risk_unavailable()
    cached = store._cache_account_risk_snapshot(expected)
    monkeypatch.setattr(
        store,
        "_read_account_risk_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "shutdown must preserve an existing cache without refreshing"
        ),
    )

    result = store.stop(timeout=0.2)

    assert result["shutdown_state"] == "PASS"
    assert api.close_calls == 1
    assert store._api is None
    assert store._account_risk_state.cached_snapshot(store._stream_generation) == cached
    assert store.get_account_risk_snapshot() == cached


def _patch_market_history_shape(monkeypatch):
    import bt_api_py.facade_protocol as facade_protocol
    import bt_api_py.market_history_composition as history_composition

    monkeypatch.setattr(facade_protocol, "is_market_history_facade", lambda _api: True)
    monkeypatch.setattr(
        history_composition, "market_history_collection_invalid", lambda _bars: False
    )


def _fake_market_bar(close):
    opened = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        open_time_utc=opened,
        close_time_utc=opened,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        open_interest=0.0,
    )


def test_history_cache_miss_activity_covers_sdk_read_and_cache_commit(monkeypatch):
    _patch_market_history_shape(monkeypatch)
    read_entered = threading.Event()
    release_read = threading.Event()
    api = _FakeUnifiedApiFacade()
    bar = _fake_market_bar(23.0)
    store = BtApiStore(
        config={"exchange_kwargs": {api.route: {}}},
        autostart=False,
        preserve_raw_bars=False,
    )
    close_observations = []
    original_close = api.close

    def observed_close():
        hit, _key, _default, cached = store._history_cache.lookup(
            "SA", None, 1, None, None
        )
        close_observations.append((hit, cached))
        original_close()

    api.close = observed_close
    _bind_store_owned_api(store, api)
    store._started = True
    store._connected = True
    store._sdk_configured = True
    store._shutdown_state = "RUNNING"
    monkeypatch.setattr(store, "_stop_funding_refresh_worker", lambda timeout: True)
    monkeypatch.setattr(store, "_cache_account_risk_snapshot_before_shutdown", lambda: None)
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: api)
    monkeypatch.setattr(store, "get_market_instrument_key", lambda _symbol: object())

    def blocking_fetch(*args, **kwargs):
        read_entered.set()
        if not release_read.wait(2):
            raise AssertionError("timed out waiting to release SDK history read")
        return (bar,)

    api.fetch_market_history = blocking_fetch
    results = []
    errors = []

    def fetch_history():
        try:
            results.append(store.fetch_history("SA"))
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=fetch_history, daemon=True)
    reader.start()
    try:
        assert read_entered.wait(1)
        assert store._sdk_api_activity_count == 1
        with pytest.raises(
            BtApiStoreError, match="store_sdk_event_drain_wait_timeout"
        ):
            store.stop(timeout=0.03)
        assert store._started is True
        assert store._connected is True
        assert store._shutdown_state == "RUNNING"
        assert store._sdk_stop_in_progress is False
        assert store._api is api
        assert api.close_calls == 0
        assert store._history_cache.lookup("SA", None, 1, None, None)[0] is False

        stopper, stop_results, stop_errors = _start_stop_thread_waiting_for_api_activity(
            store
        )
        assert api.close_calls == 0
        assert store._api is api
        release_read.set()
        reader.join(2)
        stopper.join(2)
    finally:
        release_read.set()
        reader.join(2)

    assert not reader.is_alive()
    assert not stopper.is_alive()
    assert not errors
    assert not stop_errors
    assert len(results) == 1
    assert results[0][0]["close"] == 23.0
    assert len(stop_results) == 1
    assert stop_results[0]["shutdown_state"] == "PASS"
    assert len(close_observations) == 1
    assert close_observations[0][0] is True
    assert close_observations[0][1][0]["close"] == 23.0
    assert api.close_calls == 1
    assert store._api is None
    assert store._sdk_api_activity_count == 0


def test_stopped_history_cache_hit_does_not_enter_sdk_activity(monkeypatch):
    api = _QueueBacklogApi()
    pending_order_event = {"kind": "order", "sequence": 1}
    api.event_queue.put(pending_order_event)
    store = _borrowed_api_store(api)
    source = {"close": 17.0}
    store._history_cache.set_history("SA", [source])
    store._started = False
    store._connected = False
    store._shutdown_state = "PASS"
    store._has_successful_sdk_stream_generation = True
    monkeypatch.setattr(
        store,
        "_ensure_api_ready",
        lambda: pytest.fail("a local history cache hit must not ensure the SDK"),
    )

    rows = store.fetch_history("SA")

    assert rows == [source]
    assert rows[0] is not source
    assert store._sdk_api_activity_count == 0
    assert api.poll_calls == []
    assert api.queued_events() == (pending_order_event,)
    assert api.close_calls == 0


def test_history_cache_miss_activity_allows_store_start_owner(monkeypatch):
    _patch_market_history_shape(monkeypatch)
    api = _FakeUnifiedApiFacade()
    bar = _fake_market_bar(29.0)
    store = BtApiStore(
        api=api,
        config={"exchange_kwargs": {api.route: {}}},
        autostart=False,
        preserve_raw_bars=False,
    )
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: api)
    monkeypatch.setattr(store, "get_market_instrument_key", lambda _symbol: object())
    api.fetch_market_history = lambda *args, **kwargs: (bar,)
    store._sdk_start_in_progress = True
    store._sdk_start_owner_thread_id = threading.get_ident()

    rows = store.fetch_history("SA")

    assert rows[0]["close"] == 29.0
    assert store._history_cache.lookup("SA", None, 1, None, None)[0] is True
    assert store._sdk_api_activity_count == 0
    with store._sdk_start_state_lock:
        store._sdk_start_in_progress = False
        store._sdk_start_owner_thread_id = None
