"""Synthetic integration for BtApiStore's opt-in SDK event batch route.

These tests use the real SDK BtApi and EventIngressQueue with fake provider,
normalization, and Store projection leaves. They perform no account or network
operations.
"""

from __future__ import annotations

import importlib
import threading

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")

from bt_api_py import bt_api as bt_api_module  # noqa: E402
from bt_api_py.bt_api import BtApi  # noqa: E402
from bt_api_py.event_batch_handoff import EventIngressQueue  # noqa: E402

from backtrader import Cerebro  # noqa: E402
from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.service.store_event_batch import (  # noqa: E402
    StoreEventBatchCoordinator,
    StoreEventBatchError,
)
from backtrader.stores import btapistore as store_module  # noqa: E402
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError  # noqa: E402

ROUTE = "BINANCE___SPOT"
OTHER_ROUTE = "OKX___SWAP"


class _FakeFeed:
    def disconnect(self):
        return None


def _api(monkeypatch, routes=(ROUTE,)):
    monkeypatch.setattr(bt_api_module, "_plugins_loaded", True)
    producer_queues = []

    def create_feed(_name, producer_queue, **_kwargs):
        producer_queues.append(producer_queue)
        return _FakeFeed()

    monkeypatch.setattr(bt_api_module.ExchangeRegistry, "create_feed", create_feed)
    api = BtApi(exchange_kwargs={}, debug=False)
    api.log = lambda *_args, **_kwargs: None
    api._validate_required_environment = lambda *_args, **_kwargs: None
    for route in routes:
        api.add_exchange(route, {})
    assert all(isinstance(api.data_queues[route], EventIngressQueue) for route in routes)
    return api


def _normalizer(monkeypatch, callback):
    module = importlib.import_module("bt_api_py._normalization")
    monkeypatch.setattr(module, "normalize_event", callback)


def _store(monkeypatch, api, *, enabled=True, event_batch_size=1024, routes=(ROUTE,)):
    config = {
        "exchange_kwargs": {route: {} for route in routes},
        "event_batch_handoff": enabled,
        "event_batch_size": event_batch_size,
    }
    store = BtApiStore(api=api, config=config, autostart=False)
    # Keep the actual SDK facade and queue, while replacing only lifecycle
    # readiness that would otherwise issue unrelated account reads.
    monkeypatch.setattr(
        store_module,
        "_ensure_store_api_ready",
        lambda _store, **_kwargs: api,
    )
    return store


def _ensure_claimed(store):
    assert store._ensure_api_ready() is store._api
    assert store._sdk_event_batch_coordinator.state == "claimed"


def test_opt_in_claims_real_sdk_route_before_store_poll_and_dispatches_in_order(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]
    seen = []
    _normalizer(
        monkeypatch,
        lambda item, exchange_name, **_kwargs: {
            **item,
            "exchange_name": exchange_name,
        },
    )
    store = _store(monkeypatch, api)
    store._apply_sdk_account_push = lambda _venue, event: seen.append(event["sequence"])
    _ensure_claimed(store)
    assert api._event_batch_handoffs[ROUTE].ingress is source
    assert source.consumer_claimed is True

    def legacy_poll(*_args, **_kwargs):
        pytest.fail("opt-in Store must never use destructive legacy poll_events")

    monkeypatch.setattr(api, "poll_events", legacy_poll)
    source.put({"kind": "account", "sequence": 1})
    source.put({"kind": "account", "sequence": 2})
    store._drain_sdk_events()

    assert seen == [1, 2]
    assert store._sdk_event_batch_coordinator.state == "claimed"
    assert store._sdk_event_batch_coordinator.next_event_index == 0
    assert api._event_batch_handoffs[ROUTE].outstanding is None
    assert source.qsize() == 0


def test_concurrent_store_readiness_linearizes_one_irreversible_claim(monkeypatch):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    original_register = api.register_event_consumer
    entered_register = threading.Event()
    release_register = threading.Event()
    second_started = threading.Event()
    claim_calls = []
    errors = []

    def controlled_register(venue):
        claim_calls.append(venue)
        entered_register.set()
        assert release_register.wait(5)
        return original_register(venue)

    monkeypatch.setattr(api, "register_event_consumer", controlled_register)

    def ensure_ready(mark_started=None):
        try:
            if mark_started is not None:
                mark_started.set()
            store._ensure_api_ready()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=ensure_ready)
    second = threading.Thread(target=lambda: ensure_ready(second_started))
    first.start()
    assert entered_register.wait(5)
    second.start()
    assert second_started.wait(5)
    release_register.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert claim_calls == [ROUTE]
    assert store._sdk_event_batch_coordinator.state == "claimed"
    assert len(api._event_batch_handoffs) == 1


def test_stop_timeout_during_claim_keeps_restart_fence_sticky(monkeypatch):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    original_register = api.register_event_consumer
    entered_register = threading.Event()
    release_register = threading.Event()
    errors = []

    def controlled_register(venue):
        entered_register.set()
        assert release_register.wait(5)
        return original_register(venue)

    monkeypatch.setattr(api, "register_event_consumer", controlled_register)

    def ensure_ready():
        try:
            store._ensure_api_ready()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=ensure_ready)
    worker.start()
    assert entered_register.wait(5)

    with pytest.raises(BtApiStoreError, match="event_drain_wait_timeout"):
        store.stop(timeout=0)
    assert store._sdk_event_batch_stop_requested is True
    with pytest.raises(BtApiStoreError, match="producer_quiescence_unproven"):
        store.start()

    release_register.set()
    worker.join(5)
    assert not worker.is_alive()
    assert errors == []
    assert store._sdk_event_batch_coordinator.state == "claimed"
    assert api.data_queues[ROUTE].consumer_claimed is True


def test_legacy_default_keeps_destructive_poll_path(monkeypatch):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api, enabled=False)
    calls = []
    monkeypatch.setattr(api, "poll_events", lambda venue, **_kwargs: calls.append(venue) or [])

    store._drain_sdk_events()

    assert calls == [ROUTE]
    assert store._sdk_event_batch_coordinator is None
    assert api._event_batch_handoffs == {}


def test_route_and_execution_configuration_fail_before_irreversible_claim(monkeypatch):
    api = _api(monkeypatch, routes=(ROUTE, OTHER_ROUTE))
    with pytest.raises(BtApiStoreError, match="exactly one route"):
        _store(monkeypatch, api, routes=(ROUTE, OTHER_ROUTE))
    assert api._event_batch_handoffs == {}

    api = _api(monkeypatch)
    with pytest.raises(BtApiStoreError, match="execution configuration"):
        BtApiStore(
            api=api,
            config={
                "exchange_kwargs": {ROUTE: {}},
                "event_batch_handoff": True,
                "execution_config": {"market_data_only": True},
            },
            autostart=False,
        )
    assert api._event_batch_handoffs == {}


def test_live_facade_route_mismatch_fails_before_batch_claim(monkeypatch):
    api = _api(monkeypatch, routes=(ROUTE, OTHER_ROUTE))
    store = BtApiStore(
        api=api,
        config={
            "exchange_kwargs": {ROUTE: {}},
            "event_batch_handoff": True,
        },
        autostart=False,
    )

    with pytest.raises(BtApiStoreError):
        store._ensure_api_ready()

    assert api._event_batch_handoffs == {}
    assert store._sdk_event_batch_coordinator is None


def test_missing_dispatch_contract_fails_before_irreversible_claim(monkeypatch):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    readiness_calls = []
    monkeypatch.setattr(
        store_module,
        "_ensure_store_api_ready",
        lambda _store, **_kwargs: readiness_calls.append("ready") or api,
    )

    def missing_contract(**_kwargs):
        raise store_module.BtApiMissingDependencyError(
            "synthetic missing event dispatch dependency"
        )

    monkeypatch.setattr(store_module, "_require_store_event_dispatch_contracts", missing_contract)
    with pytest.raises(store_module.BtApiMissingDependencyError):
        store._ensure_api_ready()

    assert store._sdk_event_batch_coordinator is None
    assert readiness_calls == []
    assert api._event_batch_handoffs == {}
    assert api.data_queues[ROUTE].consumer_claimed is False


@pytest.mark.parametrize(
    "missing_method",
    ("register_event_consumer", "poll_event_batch", "ack_event_batch"),
)
def test_missing_batch_api_method_fails_before_claim_and_allows_normal_stop(
    monkeypatch, missing_method
):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    monkeypatch.setattr(api, missing_method, None)

    with pytest.raises(store_module.BtApiMissingDependencyError):
        store._ensure_api_ready()

    assert store._sdk_event_batch_coordinator is None
    assert api._event_batch_handoffs == {}
    assert api.data_queues[ROUTE].consumer_claimed is False

    health = store.stop()
    assert health["shutdown_state"] not in {"INCOMPLETE", "FAIL"}
    assert store._sdk_event_batch_stop_requested is False


def test_known_claim_blocked_without_register_call_does_not_retain_source(monkeypatch):
    api = _api(monkeypatch)
    api.register_event_consumer = None
    coordinator = StoreEventBatchCoordinator(api, ROUTE)
    with pytest.raises(StoreEventBatchError, match="batch_consumer_api_unavailable"):
        coordinator.claim()
    assert coordinator.state == "claim_blocked"
    assert api._event_batch_handoffs == {}
    assert api.data_queues[ROUTE].consumer_claimed is False

    store = _store(monkeypatch, api)
    store._sdk_event_batch_coordinator = coordinator
    health = store.stop()

    assert health["shutdown_state"] not in {"INCOMPLETE", "FAIL"}
    assert store._sdk_event_batch_stop_requested is False
    assert api._event_batch_handoffs == {}


def test_claim_outcome_unknown_never_falls_back_to_legacy_poll(monkeypatch):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    original_register = api.register_event_consumer

    def register_then_raise(venue):
        original_register(venue)
        raise RuntimeError("synthetic post-claim transport interruption")

    monkeypatch.setattr(api, "register_event_consumer", register_then_raise)
    with pytest.raises(BtApiStoreError, match="batch_consumer_claim_failed"):
        store._ensure_api_ready()
    assert store._sdk_event_batch_coordinator.state == "claim_unknown"
    assert ROUTE in api._event_batch_handoffs
    with pytest.raises(BtApiStoreError, match="consumer_unavailable"):
        store.start()

    def legacy_poll(*_args, **_kwargs):
        pytest.fail("unknown claim must not fall back to destructive polling")

    monkeypatch.setattr(api, "poll_events", legacy_poll)
    with pytest.raises(BtApiStoreError, match="consumer_unavailable"):
        store._drain_sdk_events()
    health = store.stop()
    assert health["shutdown_state"] == "INCOMPLETE"
    assert api._event_batch_handoffs[ROUTE].retired is False


def test_foreign_route_batch_fails_before_event_read_dispatch_or_ack(monkeypatch):
    class ForeignBatch:
        exchange_name = OTHER_ROUTE
        event_epoch = "foreign-epoch"
        batch_sequence = 1
        batch_id = "foreign-batch"
        blocked_error_code = None

        def __init__(self):
            self.events_reads = 0

        @property
        def events(self):
            self.events_reads += 1
            return ({"kind": "account", "sequence": 9},)

    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    _ensure_claimed(store)
    foreign = ForeignBatch()
    poll_calls = []
    ack_calls = []
    dispatched = []
    monkeypatch.setattr(
        api,
        "poll_event_batch",
        lambda venue, token, **kwargs: poll_calls.append((venue, token, kwargs)) or foreign,
    )
    monkeypatch.setattr(api, "ack_event_batch", lambda *args: ack_calls.append(args))
    store._apply_sdk_account_push = lambda *_args: dispatched.append("account")

    with pytest.raises(BtApiStoreError, match="batch_binding_invalid"):
        store._drain_sdk_events()

    assert foreign.events_reads == 0
    assert dispatched == []
    assert ack_calls == []
    assert len(poll_calls) == 1
    assert store._sdk_event_batch_coordinator.state == "batch_binding_blocked"


def test_ack_unknown_after_real_sdk_ack_never_replays_dispatched_event(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]
    _normalizer(
        monkeypatch,
        lambda item, exchange_name, **_kwargs: {
            **item,
            "exchange_name": exchange_name,
        },
    )
    store = _store(monkeypatch, api)
    seen = []
    store._apply_sdk_account_push = lambda _venue, event: seen.append(event["sequence"])
    _ensure_claimed(store)
    source.put({"kind": "account", "sequence": 42})

    original_poll = api.poll_event_batch
    original_ack = api.ack_event_batch
    poll_calls = []

    def counted_poll(*args, **kwargs):
        poll_calls.append(args[0])
        return original_poll(*args, **kwargs)

    def ack_then_raise(*args):
        original_ack(*args)
        raise RuntimeError("synthetic ACK response loss after SDK ACK")

    monkeypatch.setattr(api, "poll_event_batch", counted_poll)
    monkeypatch.setattr(api, "ack_event_batch", ack_then_raise)

    with pytest.raises(BtApiStoreError, match="ack_unknown"):
        store._drain_sdk_events()
    assert store._sdk_event_batch_coordinator.state == "ack_unknown"
    assert seen == [42]
    assert api._event_batch_handoffs[ROUTE].outstanding is None

    with pytest.raises(BtApiStoreError, match="consumer_unavailable"):
        store._drain_sdk_events()
    assert poll_calls == [ROUTE]
    assert seen == [42]


def test_process_control_exception_is_preserved_after_unknown_dispatch(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]
    _normalizer(
        monkeypatch,
        lambda item, exchange_name, **_kwargs: {
            **item,
            "exchange_name": exchange_name,
        },
    )
    store = _store(monkeypatch, api)
    _ensure_claimed(store)
    source.put({"kind": "account", "sequence": 5})

    def interrupt_dispatch(_venue, _event):
        raise SystemExit(9)

    store._apply_sdk_account_push = interrupt_dispatch
    with pytest.raises(SystemExit) as caught:
        store._drain_sdk_events()

    assert caught.value.code == 9
    assert store._sdk_event_batch_coordinator.state == "dispatch_unknown"
    assert store._shutdown_state == "INCOMPLETE"
    assert api._event_batch_handoffs[ROUTE].outstanding is not None


def test_partial_dispatch_is_unknown_and_stop_retains_api_queue_and_waker(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]
    _normalizer(
        monkeypatch,
        lambda item, exchange_name, **_kwargs: {
            **item,
            "exchange_name": exchange_name,
        },
    )
    store = _store(monkeypatch, api)
    attempts = []
    store._started = True
    store._connected = True
    store._sdk_configured = True

    def apply(_venue, event):
        attempts.append(event["sequence"])
        if event["sequence"] == 2:
            raise RuntimeError("synthetic projection failure after possible effect")

    store._apply_sdk_account_push = apply
    _ensure_claimed(store)
    wake_events = []
    waiter_token = store._register_live_bar_event_waker(lambda: wake_events.append("wake"))
    source.put({"kind": "account", "sequence": 1})
    source.put({"kind": "account", "sequence": 2})
    wake_events.clear()

    with pytest.raises(BtApiStoreError, match="dispatch_unknown_event_dispatch_failed"):
        store._drain_sdk_events()
    coordinator = store._sdk_event_batch_coordinator
    assert coordinator.state == "dispatch_unknown"
    assert coordinator.next_event_index == 1
    assert api._event_batch_handoffs[ROUTE].outstanding is not None
    assert api._event_batch_handoffs[ROUTE].outstanding.batch_sequence == 1
    assert attempts == [1, 2]
    assert api._event_batch_handoffs[ROUTE].outstanding is not None

    close_calls = []
    monkeypatch.setattr(api, "close", lambda: close_calls.append("closed"))
    health = store.stop()
    assert health["shutdown_state"] == "INCOMPLETE"
    assert health["shutdown_blocked_by_event_batch_producer_quiescence"] is True
    assert close_calls == []
    assert store._api is api
    assert store._started is True and store._connected is True
    assert api.data_queues[ROUTE] is source
    assert source.event_waker_bound is True
    assert store._event_notifier.has_sdk_binding is True
    direct_lifecycle_health = store_module._stop_store(store, 0.0, safe_log=lambda *_args: None)
    assert direct_lifecycle_health["shutdown_state"] == "INCOMPLETE"
    assert close_calls == []
    assert store._started is True and store._connected is True
    with pytest.raises(BtApiStoreError, match="producer_quiescence_unproven"):
        store.start()

    source.put({"kind": "account", "sequence": 3})
    assert wake_events == ["wake"]
    assert source.qsize() == 1  # The unacknowledged lease and late item both remain.
    assert len(api._event_batch_handoffs[ROUTE].outstanding.events) == 2
    store._unregister_live_bar_event_waker(waiter_token)


def test_running_cerebro_store_broker_feed_start_sequence_can_attach(monkeypatch):
    api = _api(monkeypatch)
    store = _store(monkeypatch, api)
    store._connected = True
    monkeypatch.setattr(store, "register", lambda _feed: None)
    monkeypatch.setattr(store, "subscribe", lambda *_args, **_kwargs: None)

    broker = BtApiBroker(store=store, market_data_only=True)
    monkeypatch.setattr(broker, "_refresh_account", lambda **_kwargs: None)
    monkeypatch.setattr(broker, "_sync_positions", lambda **_kwargs: None)
    monkeypatch.setattr(broker, "_sync_remote_open_orders", lambda **_kwargs: [])
    feed = BtApiFeed(
        dataname="BTC-USDT",
        store=store,
        backfill_start=False,
    )
    cerebro = Cerebro(preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(feed)

    calls = []
    real_store_start = store.start

    def observed_store_start(data=None, broker=None):
        calls.append((data, broker))
        return real_store_start(data=data, broker=broker)

    monkeypatch.setattr(store, "start", observed_store_start)
    # This executes Cerebro's actual startup order, including DataBase._start
    # for a top-level BtApiFeed (which is not nested under FeedBase).
    cerebro._prepare_run(predata=False)

    assert len(calls) == 3
    assert calls[0] == (None, None)
    assert calls[1] == (None, broker)
    assert calls[2] == (feed, None)
    assert store._sdk_event_batch_coordinator.state == "claimed"
    assert api.data_queues[ROUTE].consumer_claimed is True
    assert store._started is True
    assert store._broker is broker
    assert feed in store._data_feeds
    assert feed._session_active is True
    assert store._sdk_event_batch_stop_requested is False


def test_ack_backlog_reschedules_after_snapshot_consumed_the_initial_wake(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]
    _normalizer(
        monkeypatch,
        lambda item, exchange_name, **_kwargs: {
            **item,
            "exchange_name": exchange_name,
        },
    )
    store = _store(monkeypatch, api, event_batch_size=1)
    seen = []
    store._apply_sdk_account_push = lambda _venue, event: seen.append(event["sequence"])
    _ensure_claimed(store)
    wake_events = []
    waiter_token = store._register_live_bar_event_waker(lambda: wake_events.append("wake"))
    source.put({"kind": "account", "sequence": 1})
    source.put({"kind": "account", "sequence": 2})
    wake_events.clear()
    consumed_generation = store._live_bar_event_snapshot()

    coordinator = store._sdk_event_batch_coordinator
    real_drain_once = coordinator.drain_once
    result_ready = threading.Event()
    release_result = threading.Event()
    results = []

    def hold_result_after_ack(*args, **kwargs):
        result = real_drain_once(*args, **kwargs)
        if results:
            return result
        assert result.continuation_required is True
        assert result.backlog_visible is True
        results.append(result)
        result_ready.set()
        assert release_result.wait(5)
        return result

    monkeypatch.setattr(coordinator, "drain_once", hold_result_after_ack)
    errors = []

    def drain_first_batch():
        try:
            store._drain_sdk_events()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=drain_first_batch)
    worker.start()
    assert result_ready.wait(5)
    # Advance the waiter snapshot after the initial ingress wake and ACK have
    # both occurred, then let Store finish its drain lease.  The Store must
    # emit a new bounded wake for the visible SDK backlog after lease release.
    consumed_after_ack = store._live_bar_event_snapshot()
    assert consumed_after_ack >= consumed_generation
    wake_events.clear()
    release_result.set()
    worker.join(5)

    assert not worker.is_alive()
    assert errors == []
    assert results and results[0].continuation_required is True
    assert seen == [1]
    assert source.qsize() == 1
    assert wake_events == ["wake"]
    assert store._wait_live_bar_event(consumed_after_ack, timeout=0) is True

    store._drain_sdk_events()
    assert seen == [1, 2]
    assert source.qsize() == 0
    assert store._sdk_event_batch_coordinator.state == "claimed"
    store._unregister_live_bar_event_waker(waiter_token)


def test_overlapping_drain_cannot_steal_prior_continuation_wake(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]
    _normalizer(
        monkeypatch,
        lambda item, exchange_name, **_kwargs: {
            **item,
            "exchange_name": exchange_name,
        },
    )
    store = _store(monkeypatch, api, event_batch_size=1)
    seen = []
    store._apply_sdk_account_push = lambda _venue, event: seen.append(event["sequence"])
    _ensure_claimed(store)
    wake_events = []
    waiter_token = store._register_live_bar_event_waker(lambda: wake_events.append("wake"))
    source.put({"kind": "account", "sequence": 1})
    source.put({"kind": "account", "sequence": 2})
    wake_events.clear()
    store._live_bar_event_snapshot()

    real_finish = store._finish_sdk_event_drain
    first_finish_returned = threading.Event()
    release_first_drain = threading.Event()
    first_finish_values = []

    def hold_first_after_atomic_finish():
        continuation_pending = real_finish()
        if threading.current_thread().name == "first-batch-drain":
            first_finish_values.append(continuation_pending)
            first_finish_returned.set()
            assert release_first_drain.wait(5)
        return continuation_pending

    monkeypatch.setattr(store, "_finish_sdk_event_drain", hold_first_after_atomic_finish)
    errors = []

    def drain_first_batch():
        try:
            store._drain_sdk_events()
        except BaseException as exc:
            errors.append(exc)

    first_drain = threading.Thread(target=drain_first_batch, name="first-batch-drain")
    first_drain.start()
    assert first_finish_returned.wait(5)
    assert first_finish_values == [True]
    assert store._sdk_event_batch_continuation_pending is False

    # The first lease is released but its after-lease wake is paused. The next
    # drain consumes the tail and has no continuation of its own; its fresh
    # lease must not clear the first drain's detached wake.
    store._drain_sdk_events()
    assert seen == [1, 2]
    assert source.qsize() == 0
    assert store._sdk_event_batch_continuation_pending is False
    wake_events.clear()
    before_first_wake = store._live_bar_event_snapshot()

    release_first_drain.set()
    first_drain.join(5)

    assert not first_drain.is_alive()
    assert errors == []
    assert wake_events == ["wake"]
    assert store._wait_live_bar_event(before_first_wake, timeout=0) is True
    store._unregister_live_bar_event_waker(waiter_token)


def test_none_heavy_scan_budget_signals_bounded_continuation(monkeypatch):
    api = _api(monkeypatch)
    source = api.data_queues[ROUTE]

    def normalize(item, exchange_name, **_kwargs):
        if item.get("skip"):
            return None
        return {**item, "exchange_name": exchange_name}

    _normalizer(monkeypatch, normalize)
    store = _store(monkeypatch, api, event_batch_size=8)
    store._sdk_event_batch_scan_limit = 2
    observed = []
    store._apply_sdk_account_push = lambda _venue, event: observed.append(event["sequence"])
    _ensure_claimed(store)
    wake_events = []
    waiter_token = store._register_live_bar_event_waker(lambda: wake_events.append("wake"))
    source.put({"skip": True})
    source.put({"skip": True})
    source.put({"kind": "account", "sequence": 7})
    wake_events.clear()

    store._drain_sdk_events()

    assert observed == []
    assert source.qsize() == 1
    assert wake_events == ["wake"]
    assert store._sdk_event_batch_coordinator.state == "claimed"
    assert store._sdk_event_batch_continuation_pending is False

    wake_events.clear()
    store._drain_sdk_events()
    assert observed == [7]
    assert source.qsize() == 0
    assert store._sdk_event_batch_coordinator.state == "claimed"
    store._unregister_live_bar_event_waker(waiter_token)
