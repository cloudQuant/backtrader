from __future__ import annotations

import asyncio
from collections import Counter
from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


class FakeApi:
    def __init__(self, routes=None):
        self.exchange_kwargs = dict(routes) if routes is not None else {}
        self.calls = []
        self.lookups = []

    def __getattribute__(self, name):
        if name in {"async_make_order", "async_cancel_order", "submit_order", "cancel_order"}:
            object.__getattribute__(self, "lookups").append(name)
        return object.__getattribute__(self, name)

    async def async_make_order(self, venue, request, **kwargs):
        self.calls.append(("submit", venue))
        return {"ok": True, "operation": "submit"}

    async def async_cancel_order(self, venue, request, **kwargs):
        self.calls.append(("cancel", venue))
        return {"ok": True, "operation": "cancel"}

    async def async_query_order(self, venue, request, **kwargs):
        self.calls.append(("query", venue))
        return {"ok": True, "operation": "query"}

    def submit_order(self, payload):
        self.calls.append(("direct_submit", payload))
        return {"ok": True}

    def cancel_order(self, order_ref, dataname=None):
        self.calls.append(("direct_cancel", order_ref))
        return {"ok": True}


class SlottedPropertyApi:
    __slots__ = ()
    route_reads = []
    calls = []
    lookups = []

    def __getattribute__(self, name):
        if name in {"submit_order", "cancel_order"}:
            type(self).lookups.append(name)
        return object.__getattribute__(self, name)

    @property
    def exchange_kwargs(self):
        type(self).route_reads.append("read")
        return {"CTP___TEST": {}}

    async def async_make_order(self, venue, request, **kwargs):
        type(self).calls.append(("submit", venue))
        return {"ok": True, "operation": "submit"}

    def submit_order(self, payload):
        type(self).calls.append(("submit", payload))
        return {"ok": True}

    def cancel_order(self, order_ref, dataname=None):
        type(self).calls.append(("cancel", order_ref))
        return {"ok": True}


class InvalidRoute:
    def __str__(self):
        raise ValueError("route conversion must not fail open")


class NoRouteApi:
    lookups = []
    calls = []

    def __getattribute__(self, name):
        if name in {"submit_order", "cancel_order"}:
            type(self).lookups.append(name)
        return object.__getattribute__(self, name)

    def submit_order(self, payload):
        type(self).calls.append(("submit", payload))
        return {"ok": True}

    def cancel_order(self, order_ref, dataname=None):
        type(self).calls.append(("cancel", order_ref))
        return {"ok": True}


class DynamicRouteApi:
    route_reads = []
    calls = []

    def __getattr__(self, name):
        if name == "exchange_kwargs":
            type(self).route_reads.append(name)
            return {"CTP___TEST": {}}
        raise AttributeError(name)

    async def async_make_order(self, venue, request, **kwargs):
        type(self).calls.append(("submit", venue))
        return {"ok": True, "operation": "submit"}


class Adapter:
    def __init__(self):
        self.calls = []

    def submit_order(self, order, dispatch):
        self.calls.append("submit")
        return dispatch(order)

    def cancel_order(self, order, dataname, dispatch):
        self.calls.append("cancel")
        return dispatch(order)


def make_store(*, provider="btapi", api=None, snapshot=None, backend="direct", adapter=None):
    store = object.__new__(BtApiStore)
    store.provider = provider
    store.backend = backend
    store._config = {}
    store._api_kwargs = {}
    store._sdk_exchanges = dict(snapshot or {})
    store._sdk_routes = {}
    store._api = api
    store._managed_execution_adapter = adapter
    store._sdk_mode = True
    store._sdk_execution_config = {"market_data_only": False}
    store._connected = True
    return store


def test_injected_ctp_api_route_mismatch_blocks_direct_submit_and_cancel():
    api = FakeApi({"CTP___TEST": {}})
    store = make_store(provider="binance", api=api, snapshot=api.exchange_kwargs)

    with pytest.raises(BtApiStoreError, match="route identity mismatch"):
        store.submit_order(SimpleNamespace(ref=1, info={}))
    with pytest.raises(BtApiStoreError, match="route identity mismatch"):
        store.cancel_order_ref("fake-order")

    assert api.calls == []
    assert api.lookups == []


def test_post_init_binance_to_ctp_route_mutation_blocks_all_generic_write_sinks():
    api = FakeApi({"BINANCE": {}})
    store = make_store(provider="btapi", api=api, snapshot=api.exchange_kwargs)
    queue_calls = []
    store._enqueue_order_command = lambda order: queue_calls.append(("submit", order))
    store._ensure_api_ready = lambda: queue_calls.append(("ensure",))
    store._require_async_sdk_commands = lambda: queue_calls.append(("contract",))
    store._start_command_worker = lambda: queue_calls.append(("worker",))
    store._sdk_cancel_request = lambda *args: pytest.fail("cancel request builder reached")

    api.exchange_kwargs.clear()
    api.exchange_kwargs["CTP___TEST"] = {}

    with pytest.raises(BtApiStoreError, match="route identity changed"):
        store.enqueue_order(SimpleNamespace(ref=2, info={}))
    with pytest.raises(BtApiStoreError, match="route identity changed"):
        store.enqueue_cancel("fake-order")
    with pytest.raises(BtApiStoreError, match="route identity changed"):
        asyncio.run(store._invoke_sdk_command("submit", {"venue": "CTP___TEST", "request": object()}))
    with pytest.raises(BtApiStoreError, match="route identity changed"):
        asyncio.run(store._invoke_sdk_command("cancel", {"venue": "CTP___TEST", "request": object()}))

    assert queue_calls == []
    assert api.calls == []
    assert api.lookups == []


def test_managed_adapter_is_not_called_for_store_api_identity_mismatch():
    api = FakeApi({"CTP___TEST": {}})
    adapter = Adapter()
    store = make_store(
        provider="binance",
        api=api,
        snapshot=api.exchange_kwargs,
        adapter=adapter,
    )

    with pytest.raises(BtApiStoreError, match="route identity mismatch"):
        store.submit_order(SimpleNamespace(ref=3, info={}))
    with pytest.raises(BtApiStoreError, match="route identity mismatch"):
        store.cancel_order_ref(SimpleNamespace(ref=3, info={}))

    assert adapter.calls == []
    assert api.calls == []


def test_managed_worker_rechecks_identity_before_dispatch_port():
    api = FakeApi({"BINANCE": {}})
    store = make_store(provider="btapi", api=api, snapshot=api.exchange_kwargs)
    store._command_health = Counter()
    store._command_last_error = ""
    store._latch_risk_state_unknown = lambda _code: None
    store.sanitize_exception = lambda _error: None
    store._safe_exception_code = lambda error, _fallback: str(error)
    dispatches = []
    command = {
        "operation": "submit",
        "managed_ctp": True,
        "managed_ctp_dispatcher": lambda binding: dispatches.append(binding),
        "receipt_id": "receipt-1",
        "priority": "open",
        "request": object(),
    }
    api.exchange_kwargs.clear()
    api.exchange_kwargs["CTP___TEST"] = {}

    completion = asyncio.run(store._execute_sdk_command(command))

    assert completion["status"] == "unknown"
    assert "route identity changed" in completion["error_code"]
    assert dispatches == []
    assert api.calls == []
    assert api.lookups == []


def test_matching_non_ctp_identity_keeps_generic_sdk_submit_cancel_and_query():
    api = FakeApi({"BINANCE___SPOT": {}})
    store = make_store(provider="binance", api=api, snapshot=api.exchange_kwargs)

    for operation in ("submit", "cancel", "query"):
        result = asyncio.run(
            store._invoke_sdk_command(
                operation,
                {"venue": "BINANCE___SPOT", "request": object()},
            )
        )
        assert result == {"ok": True, "operation": operation}

    assert [operation for operation, _venue in api.calls] == ["submit", "cancel", "query"]



def test_ctp_route_suffix_mutation_is_detected_even_when_provider_root_matches():
    api = FakeApi({"CTP___FUTURE": {}})
    store = make_store(provider="btapi", api=api, snapshot=api.exchange_kwargs)
    api.exchange_kwargs.clear()
    api.exchange_kwargs["CTP___SIM"] = {}

    with pytest.raises(BtApiStoreError, match="route identity changed"):
        store.enqueue_order(SimpleNamespace(ref=4, info={}))

    assert api.calls == []
    assert api.lookups == []


def test_recovery_exit_route_mismatch_aborts_before_raising():
    api = FakeApi({"BINANCE": {}})
    store = make_store(provider="btapi", api=api, snapshot=api.exchange_kwargs)
    abort_calls = []
    queue_calls = []
    store.abort_execution_recovery = lambda reason: abort_calls.append(reason)
    store._enqueue_order_command = lambda order: queue_calls.append(order)
    api.exchange_kwargs.clear()
    api.exchange_kwargs["CTP___TEST"] = {}
    order = SimpleNamespace(ref=5, info={"execution_role": "recovery_exit"})

    with pytest.raises(BtApiStoreError, match="route identity changed"):
        store.enqueue_order(order)

    assert abort_calls == ["execution_recovery_dispatch_failed"]
    assert queue_calls == []
    assert api.calls == []
    assert api.lookups == []


def test_malformed_sdk_routes_fail_closed_with_store_error():
    api = FakeApi({"BINANCE": {}})
    store = make_store(provider="btapi", api=api, snapshot=api.exchange_kwargs)
    store._sdk_routes = []
    queue_calls = []
    store._enqueue_order_command = lambda order: queue_calls.append(order)

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        store.enqueue_order(SimpleNamespace(ref=6, info={}))

    assert queue_calls == []
    assert api.calls == []
    assert api.lookups == []


def test_slotted_exchange_kwargs_property_is_rejected_without_evaluation():
    SlottedPropertyApi.route_reads.clear()
    SlottedPropertyApi.calls.clear()
    SlottedPropertyApi.lookups.clear()
    api = SlottedPropertyApi()
    store = make_store(provider="binance", api=api, snapshot={})

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        asyncio.run(
            store._invoke_sdk_command(
                "submit", {"venue": "CTP___TEST", "request": object()}
            )
        )

    assert SlottedPropertyApi.route_reads == []
    assert SlottedPropertyApi.calls == []


def test_dynamic_exchange_kwargs_without_store_snapshot_fails_closed():
    DynamicRouteApi.route_reads.clear()
    DynamicRouteApi.calls.clear()
    api = DynamicRouteApi()
    store = make_store(provider="binance", api=api, snapshot={})

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        asyncio.run(
            store._invoke_sdk_command(
                "submit", {"venue": "CTP___TEST", "request": object()}
            )
        )

    assert DynamicRouteApi.route_reads == []
    assert DynamicRouteApi.calls == []


@pytest.mark.parametrize("operation", ["submit", "cancel"])
def test_lazy_api_route_mismatch_is_rechecked_before_direct_sink_lookup(operation):
    SlottedPropertyApi.route_reads.clear()
    SlottedPropertyApi.calls.clear()
    SlottedPropertyApi.lookups.clear()
    api = SlottedPropertyApi()
    store = make_store(provider="binance", api=None, snapshot={})
    store._sdk_mode = False

    def ensure_api_ready():
        store._api = api
        return api

    store._ensure_api_ready = ensure_api_ready
    store._order_to_payload = lambda _order: {"symbol": "FAKE"}
    store.emit_runtime_event = lambda *_args, **_kwargs: None
    store.sanitize_exception = lambda _error: None
    store._safe_exception_code = lambda _error, fallback: fallback

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        if operation == "submit":
            store.submit_order(SimpleNamespace(ref=9, info={}))
        else:
            store.cancel_order_ref("fake-order")

    assert SlottedPropertyApi.route_reads == []
    assert SlottedPropertyApi.lookups == []
    assert SlottedPropertyApi.calls == []


@pytest.mark.parametrize("operation", ["submit", "cancel"])
def test_lazy_api_without_route_identity_fails_before_direct_sink_lookup(operation):
    NoRouteApi.lookups.clear()
    NoRouteApi.calls.clear()
    api = NoRouteApi()
    store = make_store(provider="binance", api=None, snapshot={})
    store._sdk_mode = False
    readiness_calls = []

    def ensure_api_ready():
        readiness_calls.append("ready")
        store._api = api
        return api

    store._ensure_api_ready = ensure_api_ready
    store._order_to_payload = lambda _order: {"symbol": "FAKE"}
    store.emit_runtime_event = lambda *_args, **_kwargs: None
    store.sanitize_exception = lambda _error: None
    store._safe_exception_code = lambda _error, fallback: fallback

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        if operation == "submit":
            store.submit_order(SimpleNamespace(ref=10, info={}))
        else:
            store.cancel_order_ref("fake-order")

    assert readiness_calls == ["ready"]
    assert NoRouteApi.lookups == []
    assert NoRouteApi.calls == []


def test_unconvertible_sdk_route_fails_closed_with_store_error():
    api = FakeApi({"BINANCE": {}})
    store = make_store(provider="btapi", api=api, snapshot=api.exchange_kwargs)
    store._sdk_routes = {"symbol": InvalidRoute()}

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        store.enqueue_order(SimpleNamespace(ref=8, info={}))

    assert api.calls == []
    assert api.lookups == []


def test_matching_ctp_route_still_rejects_normal_direct_store_enqueue():
    api = FakeApi({"CTP___SIM": {}})
    store = make_store(provider="ctp", api=api, snapshot=api.exchange_kwargs)
    queue_calls = []
    store._enqueue_order_command = lambda order: queue_calls.append(order)

    with pytest.raises(BtApiStoreError, match="direct CTP SDK order enqueue is disabled"):
        store.enqueue_order(SimpleNamespace(ref=7, info={}))

    assert queue_calls == []
    assert api.calls == []
    assert api.lookups == []
