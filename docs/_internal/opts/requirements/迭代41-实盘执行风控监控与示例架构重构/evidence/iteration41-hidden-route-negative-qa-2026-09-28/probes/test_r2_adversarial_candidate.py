from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


class RouteApi:
    def __init__(self, routes):
        self.exchange_kwargs = dict(routes)
        self.calls = []
        self.lookups = []

    def __getattribute__(self, name):
        if name in {"submit_order", "cancel_order", "async_make_order", "async_cancel_order"}:
            object.__getattribute__(self, "lookups").append(name)
        return object.__getattribute__(self, name)

    def submit_order(self, payload):
        self.calls.append(("submit", payload))
        return {"ok": True, "order_id": "fake-order"}

    def cancel_order(self, order_ref, dataname=None):
        self.calls.append(("cancel", order_ref))
        return {"ok": True}

    async def async_make_order(self, venue, request, **kwargs):
        self.calls.append(("async_submit", venue))
        return {"ok": True}

    async def async_cancel_order(self, venue, request, **kwargs):
        self.calls.append(("async_cancel", venue))
        return {"ok": True}


class HiddenRouteApi:
    """Deliberately hides exchange_kwargs from static lookup."""
    def __init__(self):
        self.calls = []
        self.lookups = []

    def __getattribute__(self, name):
        if name == "exchange_kwargs":
            return {"CTP___TEST": {}}
        if name in {"submit_order", "cancel_order"}:
            object.__getattribute__(self, "lookups").append(name)
        return object.__getattribute__(self, name)

    def submit_order(self, payload):
        self.calls.append(("submit", payload))
        return {"ok": True, "order_id": "hidden-route-fake"}

    def cancel_order(self, order_ref, dataname=None):
        self.calls.append(("cancel", order_ref))
        return {"ok": True}


class NoRouteApi:
    def __init__(self):
        self.calls = []

    def submit_order(self, payload):
        self.calls.append(("submit", payload))
        return {"ok": True, "order_id": "ordinary-fake"}

    def cancel_order(self, order_ref, dataname=None):
        self.calls.append(("cancel", order_ref))
        return {"ok": True}


def make_store(provider, api, snapshot, sdk_mode=False):
    store = object.__new__(BtApiStore)
    store.provider = provider
    store.backend = "direct"
    store._config = {}
    store._api_kwargs = {}
    store._sdk_exchanges = dict(snapshot)
    store._sdk_routes = {}
    store._managed_execution_adapter = None
    store._sdk_mode = sdk_mode
    store._sdk_execution_config = {"market_data_only": False}
    store._api = api
    store._connected = True
    store._ensure_api_ready = lambda: api
    store._order_to_payload = lambda order: {"symbol": "FAKE", "ref": getattr(order, "ref", None)}
    store._extract_external_order_id = lambda response: response.get("order_id")
    store._submit_response_looks_accepted = lambda response: response.get("ok") is True
    store._cancel_response_error = lambda response: None
    store.emit_runtime_event = lambda *_args, **_kwargs: None
    store.sanitize_exception = lambda _error: None
    store._safe_exception_code = lambda _error, fallback: fallback
    return store


def test_historical_direct_mismatched_injected_ctp_api_is_now_denied():
    api = RouteApi({"CTP___TEST": {}})
    store = make_store("binance", api, {})

    with pytest.raises(BtApiStoreError, match="route identity (mismatch|changed)"):
        store.submit_order(SimpleNamespace(ref=1, info={}))
    with pytest.raises(BtApiStoreError, match="route identity (mismatch|changed)"):
        store.cancel_order_ref("fake-order")

    assert api.calls == []
    assert api.lookups == []


def test_historical_mutable_sdk_snapshot_to_ctp_is_now_denied():
    api = RouteApi({"BINANCE": {}})
    store = make_store("btapi", api, api.exchange_kwargs, sdk_mode=True)
    queue_calls = []
    store._enqueue_order_command = lambda order: queue_calls.append(("submit", order))
    store._sdk_cancel_request = lambda *_args: pytest.fail("cancel request builder reached")
    store._enqueue_sdk_command = lambda *_args, **_kwargs: pytest.fail("SDK queue reached")
    api.exchange_kwargs.clear()
    api.exchange_kwargs["CTP___TEST"] = {}

    assert store._is_ctp_write_provider() is False
    assert store._is_ctp_session_provider() is True

    with pytest.raises(BtApiStoreError, match="route identity changed"):
        store.enqueue_order(SimpleNamespace(ref=2, info={}))
    with pytest.raises(BtApiStoreError, match="route identity changed"):
        store.enqueue_cancel("fake-order")
    with pytest.raises(BtApiStoreError, match="route identity changed"):
        import asyncio
        asyncio.run(store._invoke_sdk_command("submit", {"venue": "CTP___TEST", "request": object()}))

    assert queue_calls == []
    assert api.calls == []
    assert api.lookups == []


def test_hidden_getattribute_route_is_denied_before_fake_direct_sinks():
    api = HiddenRouteApi()
    store = make_store("binance", api, {})

    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        store.submit_order(SimpleNamespace(ref=3, info={}))
    with pytest.raises(BtApiStoreError, match="route identity is unavailable"):
        store.cancel_order_ref("hidden-route-fake")

    assert api.calls == []
    assert api.lookups == []


def test_explicit_ctp_provider_keeps_its_direct_dispatch_rejection():
    import asyncio

    api = HiddenRouteApi()
    store = make_store("ctp", api, {})

    with pytest.raises(BtApiStoreError, match="direct CTP SDK command dispatch is disabled"):
        asyncio.run(
            store._invoke_sdk_command(
                "submit", {"venue": "CTP___TEST", "request": object()}
            )
        )

    assert api.calls == []
    assert api.lookups == []


def test_injected_api_without_route_metadata_keeps_legacy_nonctp_compatibility():
    api = NoRouteApi()
    store = make_store("binance", api, {})

    assert store.submit_order(SimpleNamespace(ref=4, info={}))["ok"] is True
    assert store.cancel_order_ref("ordinary-fake")["ok"] is True
    assert [op for op, _payload in api.calls] == ["submit", "cancel"]


