from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


class SpyApi:
    def __init__(self):
        self.reads = []
        self.calls = []

    def __getattribute__(self, name):
        if name not in {"reads", "calls"} and not name.startswith("__"):
            object.__getattribute__(self, "reads").append(name)
        return object.__getattribute__(self, name)

    async def async_make_order(self, venue, request, **kwargs):
        self.calls.append(("submit", venue))
        return {"ok": True}

    async def async_cancel_order(self, venue, request, **kwargs):
        self.calls.append(("cancel", venue))
        return {"ok": True}

    async def async_query_order(self, venue, request, **kwargs):
        self.calls.append(("query", venue))
        return {"ok": True, "items": []}


class SpyAdapter:
    ctp_managed_execution_version = 1

    def __init__(self):
        self.lookups = []
        self.calls = 0

    def __getattribute__(self, name):
        if name in {"submit_order", "cancel_order"}:
            object.__getattribute__(self, "lookups").append(name)
        return object.__getattribute__(self, name)

    def submit_order(self, *args):
        return None

    def cancel_order(self, *args):
        self.calls += 1


def make_store(
    *,
    provider="ctp",
    backend="sdk",
    config=None,
    api_kwargs=None,
    sdk_exchanges=None,
    sdk_routes=None,
    market_data_only=False,
    managed_adapter=None,
):
    store = object.__new__(BtApiStore)
    store.provider = provider
    store.backend = backend
    store._config = dict(config or {})
    store._api_kwargs = dict(api_kwargs or {})
    store._sdk_exchanges = dict(sdk_exchanges or {})
    store._sdk_routes = dict(sdk_routes or {})
    store._managed_execution_adapter = managed_adapter
    store._sdk_mode = True
    store._sdk_execution_config = {"market_data_only": market_data_only}
    store._api = SpyApi()
    store._connected = True
    return store


@pytest.mark.parametrize(
    "provider,backend,config,api_kwargs,exchanges,routes",
    [
        pytest.param("ctp", "sdk", {}, {}, {}, {}, id="direct-ctp"),
        pytest.param("other", "gateway", {"exchange": "CTP"}, {}, {}, {}, id="gateway"),
        pytest.param(
            "other",
            "gateway",
            {},
            {"exchange_type": "CTP___TEST"},
            {},
            {},
            id="gateway-suffixed-route",
        ),
        pytest.param("other", "forwarding", {"exchange": "CTP"}, {}, {}, {}, id="forwarding"),
        pytest.param("btapi", "sdk", {}, {}, {"CTP___TEST": {}}, {}, id="btapi-snapshot"),
    ],
)
def test_ctp_submit_cancel_and_queues_fail_before_api_or_queue_sinks(
    provider, backend, config, api_kwargs, exchanges, routes
):
    store = make_store(
        provider=provider,
        backend=backend,
        config=config,
        api_kwargs=api_kwargs,
        sdk_exchanges=exchanges,
        sdk_routes=routes,
    )
    reached = []
    store._enqueue_order_command = lambda order: reached.append("submit")
    store._ensure_api_ready = lambda: reached.append("ensure")
    store._require_async_sdk_commands = lambda: reached.append("contract")
    store._start_command_worker = lambda: reached.append("worker")
    store._sdk_cancel_request = lambda *args: (
        "CTP___TEST",
        SimpleNamespace(client_order_id=None, symbol="FAKE"),
    )
    store._sdk_local_refs = {}
    store._sdk_client_refs = {}
    store._cancel_queued_opening_before_send = lambda *args: None
    store._enqueue_sdk_command = lambda *args, **kwargs: reached.append("cancel")
    command = {"venue": "CTP___TEST", "request": object()}

    for operation in ("submit", "cancel"):
        with pytest.raises(BtApiStoreError, match="direct CTP SDK command dispatch is disabled"):
            asyncio.run(store._invoke_sdk_command(operation, command))
    with pytest.raises(BtApiStoreError, match="direct CTP SDK order enqueue is disabled"):
        store.enqueue_order(SimpleNamespace(info={}))
    with pytest.raises(BtApiStoreError, match="direct CTP SDK cancel enqueue is disabled"):
        store.enqueue_cancel("fake-ref")

    assert store._api.reads == []
    assert store._api.calls == []
    assert reached == []


def test_btapi_route_classification_never_reads_api_properties():
    store = make_store(provider="btapi", sdk_exchanges={"CTP___TEST": {}})
    assert store._is_ctp_write_provider() is True
    assert store._api.reads == []


def test_unknown_btapi_route_fails_closed_without_api_property_read():
    store = make_store(provider="btapi")
    assert store._is_ctp_write_provider() is True
    assert store._api.reads == []


def test_managed_btapi_ctp_enqueue_rejects_without_api_or_adapter_lookup():
    adapter = SpyAdapter()
    store = make_store(provider="btapi", sdk_exchanges={"CTP___TEST": {}}, managed_adapter=adapter)
    with pytest.raises(BtApiStoreError, match="managed CTP orders"):
        store.enqueue_order(SimpleNamespace(info={}))
    with pytest.raises(BtApiStoreError, match="managed CTP cancellations"):
        store.enqueue_cancel("fake-ref")
    assert store._api.reads == []
    assert adapter.lookups == []


def test_market_data_only_keeps_local_rejection_before_ctp_guard():
    store = make_store(market_data_only=True)
    rejected = []
    store._reject_market_data_only_command = lambda operation, **kwargs: (
        rejected.append(operation) or {"status": "rejected", "operation": operation}
    )
    store._enqueue_order_command = lambda order: pytest.fail("submit queue reached")
    store._ensure_api_ready = lambda: pytest.fail("cancel startup reached")

    assert store.enqueue_order(SimpleNamespace(ref=7, info={})) == {
        "status": "rejected",
        "operation": "submit",
    }
    assert store.enqueue_cancel("fake-ref") == {"status": "rejected", "operation": "cancel"}
    assert rejected == ["submit", "cancel"]
    assert store._api.reads == []


def test_ctp_query_remains_read_only_and_dispatchable():
    store = make_store(provider="ctp")
    result = asyncio.run(
        store._invoke_sdk_command("query", {"venue": "CTP___TEST", "request": object()})
    )
    assert result == {"ok": True, "items": []}
    assert store._api.reads == ["async_query_order"]
    assert [item[0] for item in store._api.calls] == ["query"]


def test_non_ctp_fake_submit_cancel_and_enqueue_remain_available():
    store = make_store(provider="binance", backend="sdk")
    command = {"venue": "BINANCE", "request": object()}
    assert asyncio.run(store._invoke_sdk_command("submit", command)) == {"ok": True}
    assert asyncio.run(store._invoke_sdk_command("cancel", command)) == {"ok": True}

    hooks = []
    store._enqueue_order_command = lambda order: {"queued": True, "op": "submit"}
    store._ensure_api_ready = lambda: hooks.append("ensure")
    store._require_async_sdk_commands = lambda: hooks.append("contract")
    store._start_command_worker = lambda: hooks.append("worker")
    store._sdk_cancel_request = lambda *args: (
        "BINANCE",
        SimpleNamespace(client_order_id=None, symbol="FAKE"),
    )
    store._sdk_local_refs = {}
    store._sdk_client_refs = {}
    store._cancel_queued_opening_before_send = lambda *args: None
    store._enqueue_sdk_command = lambda *args, **kwargs: {"queued": True, "op": "cancel"}
    assert store.enqueue_order(SimpleNamespace(info={})) == {"queued": True, "op": "submit"}
    assert store.enqueue_cancel("fake-ref") == {"queued": True, "op": "cancel"}
    assert hooks == ["ensure", "contract", "worker"]
    assert [item[0] for item in store._api.calls] == ["submit", "cancel"]


def test_ctp_managed_cancel_rejects_before_adapter_method_lookup():
    adapter = SpyAdapter()
    store = make_store(provider="ctp", managed_adapter=adapter)
    events = []
    store.emit_runtime_event = lambda *args, **kwargs: events.append(args[0])

    with pytest.raises(BtApiStoreError, match="managed_execution_cancel_not_supported"):
        store._cancel_managed("fake-ref")

    assert adapter.lookups == []
    assert adapter.calls == 0
    assert events == ["managed_execution_cancel_requested", "managed_execution_cancel_rejected"]
    assert store._api.reads == []
