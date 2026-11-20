"""Backtrader handoff to explicit SDK Gateway market registration leases."""

from __future__ import annotations

import threading
import os
from types import SimpleNamespace

import pytest

from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
from bt_api_py.service_runtime_thread import OwnerOperationError, ThreadedRuntimeError
from tests.unit.feeds.test_iter63_gateway_market_feed import (
    _gateway_store,
    client_with,
    frame,
)
from tests.unit.feeds.test_market_tick_adapter_baseline import INSTRUMENT, SUBSCRIPTION


def _lease_client(client, *, close_error=None, close_result=True):
    # The projector intentionally requires the concrete SDK client type. Add
    # lease behavior to that real client instance rather than wrapping it.
    client.lease_closed = False
    client.lease_close_error = close_error
    client.lease_close_result = close_result
    client.lease_close_hook = None
    client.lease_calls = []
    for name in ("start", "status", "poll", "poll_with_receipt", "recover", "accept_resync"):
        original = getattr(client, name)

        def call(*args, _name=name, _original=original, **kwargs):
            if client.lease_closed:
                raise ThreadedRuntimeError("MARKET_LEASE_RELEASED")
            client.lease_calls.append(_name)
            return _original(*args, **kwargs)

        setattr(client, name, call)

    def close(*, timeout_seconds=5.0):
        client.lease_calls.append("close")
        if client.lease_close_hook is not None:
            client.lease_close_hook()
        if client.lease_close_error is not None:
            raise client.lease_close_error
        if client.lease_close_result is True:
            client.lease_closed = True
        return client.lease_close_result

    client.close = close
    return client


class _LeaseApi:
    def __init__(self, leases, errors=()):
        self.leases = list(leases)
        self.errors = list(errors)
        self.acquire_calls = []
        self.legacy_calls = []

    def acquire_market_subscription(self, route, name, *, timeout_seconds):
        self.acquire_calls.append((route, name, timeout_seconds))
        if self.errors:
            raise self.errors.pop(0)
        return self.leases.pop(0)

    def market_subscription(self, route, name):
        self.legacy_calls.append((route, name))
        raise AssertionError("lease-capable API must not use its legacy singleton")


class _LifecycleApi(_LeaseApi):
    """Small facade fake for the real Gateway config lifecycle functions."""

    def __init__(self, name, leases, *, trace=None, errors=()):
        super().__init__(leases, errors=errors)
        self.name = name
        self.trace = [] if trace is None else trace
        self.state = "running"
        self.close_error = None
        self.close_calls = []
        self.start_calls = []

    @property
    def lifecycle_state(self):
        return "closed" if self.state == "closed" else "running"

    @property
    def cleanup_confirmed(self):
        return self.state == "closed"

    def status(self):
        alive = self.state in ("starting", "running", "stopping")
        return SimpleNamespace(
            state=self.state,
            healthy=self.state == "running",
            thread_alive=alive,
            cleanup_failures=0,
            unregister_uncertainties=0,
            owner_cleanup_uncertainties=0,
        )

    def start(self, *, timeout_seconds):
        self.trace.append(("api-start", self.name, timeout_seconds))
        self.start_calls.append(timeout_seconds)
        self.state = "running"
        return self.status()

    def close(self, *, timeout_seconds):
        self.trace.append(("api-close", self.name, timeout_seconds))
        self.close_calls.append(timeout_seconds)
        if self.close_error is not None:
            raise self.close_error
        self.state = "closed"
        return self.status()

    def acquire_market_subscription(self, route, name, *, timeout_seconds):
        self.trace.append(("lease-acquire", self.name, route, name, timeout_seconds))
        return super().acquire_market_subscription(route, name, timeout_seconds=timeout_seconds)


class _LegacyLifecycleApi(_LifecycleApi):
    def __init__(self, name, client, *, trace=None):
        super().__init__(name, [], trace=trace)
        self.legacy_client = client

    @property
    def acquire_market_subscription(self):
        return None

    def market_subscription(self, route, name):
        self.legacy_calls.append((route, name))
        return self.legacy_client


class _LifecycleStore:
    def __init__(self, api, config):
        self._api = api
        self._gateway_strategy_config = config
        self.gateway_strategy_config = config
        self._gateway_mode = True
        self._gateway_pid = os.getpid()
        self._connected = True
        self._started = True
        self._gateway_closed = False
        self._gateway_start_attempted = True
        self._gateway_composition_uncertain = False
        self._gateway_run_lock = SimpleNamespace(held=True)
        self._gateway_owns_run_lock = False
        self._gateway_execution_db = None
        self._command_shutdown_timeout = 1.0
        self._gateway_reconnect_attempt = 0
        self._gateway_reconnect_next = 0.0
        self._gateway_reconnect_reason = None
        self._gateway_session_generation = 0
        self._shutdown_state = "RUNNING"

    @property
    def gateway_api(self):
        return self._api

    @property
    def gateway_session_generation(self):
        return self._gateway_session_generation

    @property
    def is_connected(self):
        if not self._connected or self._api is None:
            return False
        status = self._api.status()
        return status.state == "running" and status.healthy is True

    def gateway_session_state(self):
        if (not self._connected or not self._started or self._api is None
                or not self._gateway_run_lock.held):
            return "LOST"
        status = self._api.status()
        if status.state == "running" and status.healthy is True:
            return "CONNECTED"
        if status.state in ("starting", "running") and status.thread_alive is True:
            return "UNAVAILABLE"
        return "LOST"

    def get_command_health(self):
        return SimpleNamespace(shutdown_state=self._shutdown_state)


def _lifecycle_store(monkeypatch, api):
    base = _lease_store(monkeypatch, api)
    store = _LifecycleStore(api, base.gateway_strategy_config)
    store.start = lambda data=None: None
    store._data_feeds = []
    store._gateway_execution_db = None
    store._gateway_state = None
    return store


def _lease_store(monkeypatch, api):
    inner, _status = client_with(monkeypatch, [frame(1)])
    store = _gateway_store(inner)
    store.gateway_api = api
    store.gateway_session_generation = 0
    store.is_connected = True
    return store


def test_confirmed_sdk_release_allows_same_session_restart_with_fresh_lease(
    monkeypatch,
):
    first_inner, _ = client_with(monkeypatch, [frame(1)])
    second_inner, _ = client_with(monkeypatch, [frame(1)])
    first, second = _lease_client(first_inner), _lease_client(second_inner)
    api = _LeaseApi([first, second])
    store = _lease_store(monkeypatch, api)

    old = GatewayMarketAdapter(store, "SA609", object())
    old.start()
    assert old._projector._client is first
    assert old.poll().cursor.sequence == 1
    old.close()

    tombstone = store._gateway_market_feed_claim_tombstones["main"]
    assert tombstone[3] is True
    assert tombstone[4] is api
    assert store._gateway_market_feed_claims["main"] is None
    assert first.lease_closed
    assert old.poll() is None
    with pytest.raises(RuntimeError, match="GATEWAY_MARKET_ADAPTER_CLOSED"):
        old.start()
    with pytest.raises(ThreadedRuntimeError, match="MARKET_LEASE_RELEASED"):
        first.start()

    new = GatewayMarketAdapter(store, "SA609", object())
    new.start()
    assert new._projector._client is second
    assert new.poll().cursor.sequence == 1
    assert len(api.acquire_calls) == 2
    assert api.legacy_calls == []
    new.close()


def test_unconfirmed_sdk_release_keeps_local_claim_and_blocks_same_session_reopen(
    monkeypatch,
):
    inner, _ = client_with(monkeypatch, [])
    lease = _lease_client(
        inner, close_error=ThreadedRuntimeError("MARKET_LEASE_UNCERTAIN")
    )
    api = _LeaseApi([lease])
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()

    with pytest.raises(ThreadedRuntimeError, match="MARKET_LEASE_UNCERTAIN"):
        adapter.close()

    assert store._gateway_market_feed_claims["main"] is adapter
    assert "main" not in store._gateway_market_feed_claim_tombstones
    assert adapter._closed is False
    assert lease.lease_closed is False
    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", object())
    assert len(api.acquire_calls) == 1
    assert api.legacy_calls == []


def test_timed_out_sdk_claim_retries_same_adapter_without_legacy_fallback(
    monkeypatch,
):
    inner, _ = client_with(monkeypatch, [frame(1)])
    lease = _lease_client(inner)
    api = _LeaseApi(
        [lease], errors=[ThreadedRuntimeError("OWNER_TIMEOUT_RUNNING")]
    )
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())

    adapter.start()
    assert adapter.recovery_reason() == "OWNER_TIMEOUT_RUNNING"
    assert store._gateway_market_feed_claims["main"] is adapter
    assert len(api.acquire_calls) == 1
    assert api.legacy_calls == []

    adapter._next_retry = 0
    event = adapter.poll()
    assert event is not None and event.cursor.sequence == 1
    assert adapter.recovery_reason() is None
    assert len(api.acquire_calls) == 2
    adapter.close()


def test_timed_out_claim_is_reacquired_and_released_when_feed_stops(monkeypatch):
    inner, _ = client_with(monkeypatch, [])
    lease = _lease_client(inner)
    api = _LeaseApi([lease], errors=[ThreadedRuntimeError("OWNER_TIMEOUT_RUNNING")])
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()

    adapter.close()

    assert store._gateway_market_feed_claims["main"] is None
    assert store._gateway_market_feed_claim_tombstones["main"][3] is True
    assert lease.lease_closed
    assert len(api.acquire_calls) == 2
    assert api.legacy_calls == []


def test_repeated_claim_timeout_keeps_local_claim_until_same_candidate_is_resolved(
    monkeypatch,
):
    inner, _ = client_with(monkeypatch, [])
    lease = _lease_client(inner)
    api = _LeaseApi(
        [lease], errors=[ThreadedRuntimeError("OWNER_TIMEOUT_RUNNING")] * 2
    )
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()

    with pytest.raises(RuntimeError, match="GATEWAY_MARKET_LEASE_UNCONFIRMED"):
        adapter.close()

    assert store._gateway_market_feed_claims["main"] is adapter
    assert "main" not in store._gateway_market_feed_claim_tombstones
    assert len(api.acquire_calls) == 2
    assert api.legacy_calls == []

    adapter.close()
    assert store._gateway_market_feed_claims["main"] is None
    assert lease.lease_closed
    assert len(api.acquire_calls) == 3


def test_explicit_owner_no_send_releases_only_local_claim_without_retry(monkeypatch):
    error = ThreadedRuntimeError("QUEUE_FULL")
    error._owner_call_not_submitted = True
    api = _LeaseApi([], errors=[error])
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())

    adapter.start()
    assert adapter.recovery_reason() == "QUEUE_FULL"
    adapter.close()

    assert store._gateway_market_feed_claims["main"] is None
    assert store._gateway_market_feed_claim_tombstones["main"][3] is True
    assert len(api.acquire_calls) == 1
    assert api.legacy_calls == []


def test_sdk_owner_claim_refusal_has_no_live_lease_to_hold_local_claim(
    monkeypatch,
):
    api = _LeaseApi([], errors=[OwnerOperationError("MARKET_LEASE_ALREADY_CLAIMED")])
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())

    adapter.start()
    adapter.close()

    assert store._gateway_market_feed_claims["main"] is None
    assert store._gateway_market_feed_claim_tombstones["main"][3] is True
    assert len(api.acquire_calls) == 1


def test_facade_preflight_rejection_is_no_lease_but_arbitrary_runtime_error_is_unknown(
    monkeypatch,
):
    api = _LeaseApi([], errors=[RuntimeError("GATEWAY_FACADE_CLOSED")])
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    adapter.close()
    assert store._gateway_market_feed_claims["main"] is None

    api = _LeaseApi([], errors=[RuntimeError("other failure")])
    store = _lease_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    with pytest.raises(RuntimeError, match="GATEWAY_MARKET_LEASE_UNCONFIRMED"):
        adapter.close()
    assert store._gateway_market_feed_claims["main"] is adapter
    assert api.legacy_calls == []


def test_btapi_feed_stop_then_same_session_start_uses_a_new_sdk_lease(monkeypatch):
    import backtrader as bt
    from backtrader.feeds.btapifeed import BtApiFeed

    first_inner, _ = client_with(monkeypatch, [frame(1)])
    second_inner, _ = client_with(monkeypatch, [frame(1)])
    first, second = _lease_client(first_inner), _lease_client(second_inner)
    api = _LeaseApi([first, second])
    store = _lease_store(monkeypatch, api)
    store._gateway_strategy_config = store.gateway_strategy_config
    store.start = lambda data=None: None

    first_feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
    )
    first_feed._start()
    first_adapter = first_feed._gateway_market_adapter
    first_feed.stop()
    assert first.lease_closed
    assert "_gateway_market_adapter" not in first_feed.__dict__

    second_feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
    )
    second_feed._start()
    assert second_feed._gateway_market_adapter is not first_adapter
    assert second_feed._gateway_market_adapter._projector._client is second
    assert len(api.acquire_calls) == 2
    assert api.legacy_calls == []
    second_feed.stop()


def test_btapi_feed_stop_keeps_adapter_and_local_claim_when_release_is_unknown(
    monkeypatch,
):
    import backtrader as bt
    from backtrader.feeds.btapifeed import BtApiFeed

    inner, _ = client_with(monkeypatch, [])
    lease = _lease_client(
        inner, close_error=ThreadedRuntimeError("MARKET_LEASE_UNCERTAIN")
    )
    api = _LeaseApi([lease])
    store = _lease_store(monkeypatch, api)
    store._gateway_strategy_config = store.gateway_strategy_config
    store.start = lambda data=None: None
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
    )
    feed._start()
    adapter = feed._gateway_market_adapter

    with pytest.raises(ThreadedRuntimeError, match="MARKET_LEASE_UNCERTAIN"):
        feed.stop()

    assert feed._gateway_market_adapter is adapter
    assert store._gateway_market_feed_claims["main"] is adapter
    assert "main" not in store._gateway_market_feed_claim_tombstones
    assert not lease.lease_closed
    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", object())


def test_reconnect_adopts_new_lease_through_real_store_preclose_order(monkeypatch):
    from backtrader.service import gateway_config

    trace = []
    old_inner, _ = client_with(monkeypatch, [frame(1)])
    new_inner, _ = client_with(monkeypatch, [frame(1)])
    old_lease, new_lease = _lease_client(old_inner), _lease_client(new_inner)
    old_api = _LifecycleApi("old", [old_lease], trace=trace)
    new_api = _LifecycleApi("new", [new_lease], trace=trace)
    old_lease.lease_close_hook = lambda: trace.append(("lease-close", "old"))
    store = _lifecycle_store(monkeypatch, old_api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    assert adapter.poll().cursor.sequence == 1
    old_poll_count = old_lease.lease_calls.count("poll_with_receipt")

    old_api.state = "failed"
    monkeypatch.setattr(gateway_config, "_verify_gateway_execution_parents", lambda *_: None)
    monkeypatch.setattr(gateway_config, "_create_gateway_api", lambda _store: new_api)
    assert gateway_config.reconnect_gateway_store(store, timeout=2.0) is True
    assert store.gateway_api is new_api and store.gateway_session_generation == 1
    event = adapter.poll()

    assert event is not None and event.cursor.sequence == 1
    assert adapter._projector._client is new_lease
    assert old_lease.lease_calls.count("poll_with_receipt") == old_poll_count
    assert old_api.legacy_calls == [] and new_api.legacy_calls == []
    assert [item[:2] for item in trace if item[0] in ("lease-close", "api-close", "api-start")] == [
        ("lease-close", "old"), ("api-close", "old"), ("api-start", "new")
    ]
    adapter.close()
    assert old_lease.lease_closed and new_lease.lease_closed


def test_reconnect_drain_refusal_does_not_close_old_api_or_drop_claim(monkeypatch):
    from backtrader.service import gateway_config

    inner, _ = client_with(monkeypatch, [])
    lease = _lease_client(inner, close_result=False)
    api = _LifecycleApi("old", [lease])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    api.state = "failed"

    assert gateway_config.reconnect_gateway_store(store, timeout=1.0) is False
    assert api.close_calls == []
    assert store._api is api
    assert store._gateway_market_feed_claims["main"] is adapter
    assert adapter._lease_client is lease and not lease.lease_closed
    assert "_gateway_market_session_draining" not in store.__dict__


def test_failed_old_api_close_keeps_lost_adapter_pending_until_retry(monkeypatch):
    from backtrader.service import gateway_config

    inner, _ = client_with(monkeypatch, [frame(1)])
    next_inner, _ = client_with(monkeypatch, [frame(1)])
    lease, next_lease = _lease_client(inner), _lease_client(next_inner)
    old_api = _LifecycleApi("old", [lease])
    new_api = _LifecycleApi("new", [next_lease])
    store = _lifecycle_store(monkeypatch, old_api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    old_api.state = "failed"
    old_api.close_error = RuntimeError("synthetic close failure")
    monkeypatch.setattr(gateway_config, "_verify_gateway_execution_parents", lambda *_: None)
    monkeypatch.setattr(gateway_config, "_create_gateway_api", lambda _store: new_api)

    assert gateway_config.reconnect_gateway_store(store, timeout=1.0) is False
    assert old_api.close_calls and old_api.state == "failed"
    assert adapter._lease_drain_pending and adapter._lease_client is None
    acquire_count = len(old_api.acquire_calls)
    assert adapter.poll() is None
    assert len(old_api.acquire_calls) == acquire_count

    old_api.close_error = None
    store._gateway_reconnect_next = 0.0
    assert gateway_config.reconnect_gateway_store(store, timeout=1.0) is True
    assert store.gateway_api is new_api and store.gateway_session_generation == 1
    assert adapter.poll().cursor.sequence == 1
    assert adapter._projector._client is next_lease
    adapter.close()


def test_connected_reconnect_cancellation_resumes_same_session_lease(monkeypatch):
    from backtrader.service import gateway_config

    inner, _ = client_with(monkeypatch, [frame(1)])
    resumed_inner, _ = client_with(monkeypatch, [frame(1)])
    first, resumed = _lease_client(inner), _lease_client(resumed_inner)
    api = _LifecycleApi("same", [first, resumed])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    api.state = "failed"
    first.lease_close_hook = lambda: setattr(api, "state", "running")

    assert gateway_config.reconnect_gateway_store(store, timeout=1.0) is True
    assert api.close_calls == []
    assert store.gateway_session_generation == 0
    assert adapter._projector._client is resumed
    assert not adapter._lease_drain_pending
    assert api.legacy_calls == []
    adapter.close()


def test_connected_fast_path_resolves_previous_pending_lease_drain(monkeypatch):
    from backtrader.service import gateway_config

    first_inner, _ = client_with(monkeypatch, [frame(1)])
    resumed_inner, _ = client_with(monkeypatch, [frame(1)])
    first, resumed = _lease_client(first_inner), _lease_client(resumed_inner)
    api = _LifecycleApi("connected-retry", [first, resumed])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    assert adapter.prepare_session_reconnect(api) is True
    assert adapter._lease_drain_pending and first.lease_closed

    assert gateway_config.reconnect_gateway_store(store, timeout=1.0) is True
    assert store.gateway_api is api and store.gateway_session_generation == 0
    assert adapter._projector._client is resumed
    assert not adapter._lease_drain_pending
    adapter.close()


def test_empty_store_drain_gates_new_adapter_under_claim_lock(monkeypatch):
    from backtrader.service.gateway_market_adapter import (
        begin_gateway_market_session_drain,
        end_gateway_market_session_drain,
    )

    inner, _ = client_with(monkeypatch, [])
    api = _LifecycleApi("empty", [_lease_client(inner)])
    store = _lifecycle_store(monkeypatch, api)
    drain = begin_gateway_market_session_drain(store, api)
    assert drain is not None and drain[5] is True and drain[4] == ()
    assert store.__dict__["_gateway_market_session_draining"] is drain[2]
    with pytest.raises(ValueError, match="GATEWAY_MARKET_SESSION_RECONNECTING"):
        GatewayMarketAdapter(store, "SA609", object())
    end_gateway_market_session_drain(drain)
    assert "_gateway_market_session_draining" not in store.__dict__


def test_snapshot_gate_rejects_constructor_after_claim_snapshot(monkeypatch):
    from backtrader.service.gateway_market_adapter import begin_gateway_market_session_drain

    inner, _ = client_with(monkeypatch, [])
    api = _LifecycleApi("gate", [_lease_client(inner)])
    store = _lifecycle_store(monkeypatch, api)
    existing = GatewayMarketAdapter(store, "SA609", object())
    preparing = threading.Event()
    proceed = threading.Event()

    def blocked_prepare(_api, *, force=True, deadline=None):
        preparing.set()
        assert proceed.wait(2)
        return True

    existing.prepare_session_reconnect = blocked_prepare
    result = []
    worker = threading.Thread(
        target=lambda: result.append(begin_gateway_market_session_drain(store, api)),
        daemon=True,
    )
    worker.start()
    assert preparing.wait(2)
    try:
        with pytest.raises(ValueError, match="GATEWAY_MARKET_SESSION_RECONNECTING"):
            GatewayMarketAdapter(store, "SA609", object())
    finally:
        proceed.set()
        worker.join(2)
    assert not worker.is_alive() and result and result[0][5] is True


def test_baseexception_during_drain_clears_gate_and_propagates(monkeypatch):
    from backtrader.service.gateway_market_adapter import begin_gateway_market_session_drain

    inner, _ = client_with(monkeypatch, [])
    api = _LifecycleApi("base-exception", [_lease_client(inner)])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.prepare_session_reconnect = lambda *_a, **_kw: (_ for _ in ()).throw(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        begin_gateway_market_session_drain(store, api)
    assert "_gateway_market_session_draining" not in store.__dict__


def test_stop_gateway_store_refuses_unknown_claim_and_preserves_runtime(monkeypatch):
    from backtrader.service import gateway_config

    class DerivedAdapter(GatewayMarketAdapter):
        pass

    inner, _ = client_with(monkeypatch, [])
    api = _LifecycleApi("unsupported", [_lease_client(inner)])
    store = _lifecycle_store(monkeypatch, api)
    adapter = DerivedAdapter(store, "SA609", object())

    gateway_config.stop_gateway_store(store, timeout=1.0)
    assert api.close_calls == []
    assert store._gateway_market_feed_claims["main"] is adapter
    assert store._shutdown_state == "INCOMPLETE"
    assert "_gateway_market_session_draining" not in store.__dict__


def test_unknown_acquire_then_feed_close_timeout_blocks_store_stop(monkeypatch):
    import backtrader as bt
    from backtrader.service import gateway_config
    from backtrader.feeds.btapifeed import BtApiFeed

    inner, _ = client_with(monkeypatch, [])
    errors = [ThreadedRuntimeError("OWNER_TIMEOUT_RUNNING") for _ in range(3)]
    api = _LifecycleApi("unknown-acquire", [_lease_client(inner)], errors=errors)
    store = _lifecycle_store(monkeypatch, api)
    store._gateway_strategy_config = store.gateway_strategy_config
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
    )
    feed._start()
    adapter = feed._gateway_market_adapter
    with pytest.raises(RuntimeError, match="GATEWAY_MARKET_LEASE_UNCONFIRMED"):
        feed.stop()

    gateway_config.stop_gateway_store(store, timeout=1.0)
    assert api.close_calls == []
    assert store._gateway_market_feed_claims["main"] is adapter
    assert adapter._lease_acquire_state == "unknown"
    assert store._shutdown_state == "INCOMPLETE"


def test_feed_binding_qualification_and_status_use_the_leased_client(monkeypatch):
    import os
    import time
    import backtrader as bt
    from backtrader.feeds.btapifeed import BtApiFeed
    from backtrader.service.gateway_instrument_status import unavailable
    from backtrader.stores.btapistore import BtApiStore
    from bt_api_py.clock_verification import GatewayTradeClockQualification
    from bt_api_py.gateway_strategy_market import GatewayMarketReceivedEvent
    from bt_api_py.service_market import MarketReceiveReceipt

    event = frame(1)
    now = time.monotonic_ns()
    receipt = MarketReceiveReceipt(
        "pub", event.header.stream_id, event.header.stream_epoch,
        event.header.sequence, event.header.message_id, time.time_ns(),
        now, os.getpid(), threading.get_ident(),
    )
    inner, _ = client_with(monkeypatch, [])
    monkeypatch.setattr(
        inner, "poll_with_receipt",
        lambda **_kwargs: GatewayMarketReceivedEvent(event, receipt),
    )
    lease = _lease_client(inner)
    api = _LifecycleApi("qualification", [lease])
    base_store = _lease_store(monkeypatch, api)
    store = object.__new__(BtApiStore)
    store.__dict__.update({
        "_gateway_mode": True,
        "_gateway_pid": os.getpid(),
        "_connected": True,
        "_started": True,
        "_gateway_closed": False,
        "_gateway_session_generation": 0,
        "_gateway_run_lock": SimpleNamespace(held=True),
        "_api": api,
        "_gateway_strategy_config": base_store.gateway_strategy_config,
        "_calendar_status_lock": threading.RLock(),
    })
    store.start = lambda data=None: None
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
    )
    feed._start()
    adapter = feed._gateway_market_adapter
    delivered = adapter.poll()
    assert delivered is not None
    feed._gateway_last_data_event = delivered
    assert adapter.matches(store, feed, INSTRUMENT)

    status_calls = []
    status = unavailable(INSTRUMENT)
    monkeypatch.setattr(
        BtApiStore, "gateway_instrument_status",
        lambda self, route, instrument, *, timeout_seconds: (
            status_calls.append((self, route, instrument, timeout_seconds)) or status
        ),
    )
    observed = feed.instrument_status_observation(timeout_seconds=1.0)
    assert status_calls and status_calls[0][0] is store
    assert observed.code == status.code

    feed._live_notified = True
    feed._continuity_degraded = False
    qualification = GatewayTradeClockQualification(
        True, None, "2026-11-02T02:00:00Z", now,
        "2026-11-02T02:00:00Z", 0.1, 1.0, 1.0,
        now + 10_000_000_000,
    )
    adapter._qualifier = SimpleNamespace(qualify=lambda _event, _receipt: qualification)
    result = feed.gateway_trade_qualification(
        expected_store=store, expected_instrument=INSTRUMENT
    )
    assert result.ok and "GATEWAY_FEED_BINDING_MISMATCH" not in result.reasons
    assert lease.lease_calls.count("poll_with_receipt") == 1
    feed.stop()


def test_owned_clock_refresh_restarts_only_after_new_lease_adoption(monkeypatch):
    from backtrader.service import gateway_config
    from bt_api_py.clock_verification import GatewayClockVerifier

    trace = []
    old_inner, _ = client_with(monkeypatch, [frame(1)])
    new_inner, _ = client_with(monkeypatch, [frame(1)])
    old_lease, new_lease = _lease_client(old_inner), _lease_client(new_inner)
    old_api = _LifecycleApi("old-clock", [old_lease], trace=trace)
    new_api = _LifecycleApi("new-clock", [new_lease], trace=trace)
    store = _lifecycle_store(monkeypatch, old_api)
    feed = SimpleNamespace(p=SimpleNamespace(
        event_time_max_age=2.0, allow_stale_market_feed=False
    ))
    monkeypatch.setattr(
        GatewayClockVerifier, "start_background_refresh",
        lambda self, interval: trace.append(("clock-start", interval)),
    )
    monkeypatch.setattr(
        GatewayClockVerifier, "stop_background_refresh",
        lambda self, *, timeout_seconds: trace.append(("clock-stop", timeout_seconds)) or True,
    )
    adapter = GatewayMarketAdapter(
        store,
        "SA609",
        feed,
        clock_verification={"servers": ["synthetic.invalid"], "refresh_interval_seconds": 10},
    )
    adapter.start()
    old_api.state = "failed"
    monkeypatch.setattr(gateway_config, "_verify_gateway_execution_parents", lambda *_: None)
    monkeypatch.setattr(gateway_config, "_create_gateway_api", lambda _store: new_api)

    assert gateway_config.reconnect_gateway_store(store, timeout=2.0) is True
    assert adapter.poll().cursor.sequence == 1
    new_acquire = next(i for i, item in enumerate(trace)
                       if item[:3] == ("lease-acquire", "new-clock", "test"))
    clock_starts = [i for i, item in enumerate(trace) if item[0] == "clock-start"]
    assert len(clock_starts) == 2
    assert new_acquire < clock_starts[-1]
    assert any(item[0] == "clock-stop" for item in trace)
    adapter.close()


def test_resume_and_feed_close_serialize_without_leaking_a_new_lease(monkeypatch):
    inner, _ = client_with(monkeypatch, [frame(1)])
    resumed_inner, _ = client_with(monkeypatch, [])
    first, resumed = _lease_client(inner), _lease_client(resumed_inner)
    api = _LifecycleApi("resume-close-race", [first, resumed])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    adapter.start()
    assert adapter.prepare_session_reconnect(api) is True

    entered = threading.Event()
    proceed = threading.Event()
    original_ensure = adapter._ensure_market_client

    def blocked_ensure(*args, **kwargs):
        entered.set()
        assert proceed.wait(2)
        return original_ensure(*args, **kwargs)

    adapter._ensure_market_client = blocked_ensure
    resume_result = []
    resume_thread = threading.Thread(
        target=lambda: resume_result.append(adapter.resume_session_reconnect(api)),
        daemon=True,
    )
    resume_thread.start()
    assert entered.wait(2)
    close_started = threading.Event()

    def close():
        close_started.set()
        adapter.close()

    close_thread = threading.Thread(target=close, daemon=True)
    close_thread.start()
    assert close_started.wait(2)
    proceed.set()
    resume_thread.join(2)
    close_thread.join(2)

    assert not resume_thread.is_alive() and not close_thread.is_alive()
    assert resume_result == [True]
    assert adapter._closed and resumed.lease_closed
    assert store._gateway_market_feed_claims["main"] is None
    assert len(api.acquire_calls) == 2


def test_store_stop_zero_timeout_keeps_nonwaiting_facade_fence(monkeypatch):
    from backtrader.service import gateway_config

    api = _LifecycleApi("zero", [])
    store = _lifecycle_store(monkeypatch, api)
    monkeypatch.setattr(gateway_config, "_close_gateway_execution_db", lambda _store: None)
    monkeypatch.setattr(gateway_config, "_release_owned_gateway_lock", lambda _store: None)

    gateway_config.stop_gateway_store(store, timeout=0)

    assert len(api.close_calls) == 1
    assert 0 < api.close_calls[0] <= 1e-9
    assert store._api is None and store._shutdown_state == "PASS"


def test_store_stop_stops_owned_clock_for_legacy_market_api(monkeypatch):
    from backtrader.service import gateway_config
    from bt_api_py.clock_verification import GatewayClockVerifier

    trace = []
    client, _ = client_with(monkeypatch, [])
    api = _LegacyLifecycleApi("legacy-clock", client, trace=trace)
    store = _lifecycle_store(monkeypatch, api)
    feed = SimpleNamespace(p=SimpleNamespace(
        event_time_max_age=2.0, allow_stale_market_feed=False
    ))
    monkeypatch.setattr(
        GatewayClockVerifier, "start_background_refresh",
        lambda self, interval: trace.append(("clock-start", interval)),
    )
    monkeypatch.setattr(
        GatewayClockVerifier, "stop_background_refresh",
        lambda self, *, timeout_seconds: trace.append(("clock-stop", timeout_seconds)) or True,
    )
    adapter = GatewayMarketAdapter(
        store,
        "SA609",
        feed,
        clock_verification={"servers": ["synthetic.invalid"]},
    )
    adapter.start()
    assert adapter._clock_started
    monkeypatch.setattr(gateway_config, "_close_gateway_execution_db", lambda _store: None)
    monkeypatch.setattr(gateway_config, "_release_owned_gateway_lock", lambda _store: None)

    gateway_config.stop_gateway_store(store, timeout=1.0)

    assert not adapter._clock_started
    assert [item[0] for item in trace] == ["clock-start", "clock-stop", "api-close"]
    adapter.close()


def test_store_stop_shares_one_deadline_across_multiple_market_leases(monkeypatch):
    from dataclasses import replace
    from backtrader.service import gateway_config
    from bt_api_py.gateway_strategy_market import GatewayMarketSubscriptionSettings

    api = _LifecycleApi("budget", [])
    store = _lifecycle_store(monkeypatch, api)
    config = store.gateway_strategy_config
    second_instrument = replace(INSTRUMENT, instrument_id="SA610", native_symbol="SA610")
    second_key = replace(SUBSCRIPTION, instrument=second_instrument)
    second_setting = GatewayMarketSubscriptionSettings(
        second_key, require_source_descriptor=True
    )
    first_setting = config.market_settings.subscriptions["main"]
    config.market_settings = SimpleNamespace(
        subscriptions={"main": first_setting, "second": second_setting}
    )
    config.instruments_by_ref = {"main": INSTRUMENT, "second": second_instrument}
    adapters = (
        GatewayMarketAdapter(store, "SA609", object()),
        GatewayMarketAdapter(store, "SA610", object()),
    )
    now = [100.0]
    monkeypatch.setattr(gateway_config.time, "monotonic", lambda: now[0])
    close_budgets = []
    for index, adapter in enumerate(adapters):
        client = SimpleNamespace()

        def close(*, timeout_seconds, _index=index):
            close_budgets.append(timeout_seconds)
            now[0] += min(0.6, timeout_seconds)
            return True

        client.close = close
        adapter._lease_client = client
        adapter._lease_api = api
        adapter._lease_attempted = True
        adapter._lease_acquire_state = "acquired"

    monkeypatch.setattr(gateway_config, "_close_gateway_execution_db", lambda _store: None)
    monkeypatch.setattr(gateway_config, "_release_owned_gateway_lock", lambda _store: None)
    gateway_config.stop_gateway_store(store, timeout=1.0)

    assert close_budgets == pytest.approx([1.0, 0.4])
    assert now[0] == pytest.approx(101.0)
    assert api.close_calls == []
    assert store._shutdown_state == "INCOMPLETE"


@pytest.mark.parametrize("timeout", [0.0, 0.05])
def test_store_stop_budget_bounds_adapter_lifecycle_lock_wait(monkeypatch, timeout):
    import time
    from backtrader.service import gateway_config

    inner, _ = client_with(monkeypatch, [])
    api = _LifecycleApi("lock-budget", [_lease_client(inner)])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    held = threading.Event()
    release = threading.Event()

    def lock_holder():
        with adapter._lifecycle_lock:
            held.set()
            release.wait(2)

    worker = threading.Thread(target=lock_holder, daemon=True)
    worker.start()
    assert held.wait(2)
    started = time.monotonic()
    try:
        gateway_config.stop_gateway_store(store, timeout=timeout)
    finally:
        release.set()
        worker.join(2)

    assert not worker.is_alive()
    assert time.monotonic() - started < 0.5
    assert api.close_calls == []
    assert store._gateway_market_feed_claims["main"] is adapter
    assert store._shutdown_state == "INCOMPLETE"


@pytest.mark.parametrize("timeout", [0.0, 0.05])
def test_store_stop_budget_bounds_claim_lock_wait(monkeypatch, timeout):
    import time
    from backtrader.service import gateway_config

    inner, _ = client_with(monkeypatch, [])
    api = _LifecycleApi("claim-lock-budget", [_lease_client(inner)])
    store = _lifecycle_store(monkeypatch, api)
    adapter = GatewayMarketAdapter(store, "SA609", object())
    lock = store.__dict__.setdefault(
        "_gateway_market_feed_claim_lock", threading.Lock()
    )
    held = threading.Event()
    release = threading.Event()

    def lock_holder():
        with lock:
            held.set()
            release.wait(2)

    worker = threading.Thread(target=lock_holder, daemon=True)
    worker.start()
    assert held.wait(2)
    started = time.monotonic()
    try:
        gateway_config.stop_gateway_store(store, timeout=timeout)
    finally:
        release.set()
        worker.join(2)

    assert not worker.is_alive()
    assert time.monotonic() - started < 0.5
    assert api.close_calls == []
    assert store._shutdown_state == "INCOMPLETE"
    assert store._gateway_market_feed_claims["main"] is adapter
    with pytest.raises(RuntimeError, match="GATEWAY_STORE_STOPPED"):
        adapter.start()
    adapter._latest_event, adapter._latest_receipt = object(), object()
    assert adapter.latest_realtime() is None
    assert adapter.qualify_latest() is None
    assert not adapter.matches(store, adapter._feed, INSTRUMENT)
    assert api.acquire_calls == []
