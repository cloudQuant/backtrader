from __future__ import annotations

from types import SimpleNamespace

from backtrader.stores.btapistore import BtApiStore


class SnapshotSpoofApi:
    """Static state says BINANCE; dynamic route reads say CTP."""

    def __init__(self):
        self.exchange_kwargs = {"BINANCE": {}}
        self.calls = []
        self.lookups = []

    def __getattribute__(self, name):
        if name == "exchange_kwargs":
            return {"CTP___TEST": {}}
        if name in {"submit_order", "cancel_order"}:
            object.__getattribute__(self, "lookups").append(name)
        return object.__getattribute__(self, name)

    def submit_order(self, payload):
        route = next(iter(self.exchange_kwargs))
        self.calls.append(("submit", route, payload["ref"]))
        return {"ok": True}

    def cancel_order(self, order_ref, dataname=None):
        route = next(iter(self.exchange_kwargs))
        self.calls.append(("cancel", route, order_ref))
        return {"ok": True}


def make_store(api):
    store = object.__new__(BtApiStore)
    store.provider = "binance"
    store.backend = "direct"
    store._config = {}
    store._api_kwargs = {}
    store._sdk_exchanges = {"BINANCE": {}}
    store._sdk_routes = {}
    store._managed_execution_adapter = None
    store._sdk_mode = False
    store._sdk_execution_config = {"market_data_only": False}
    store._api = api
    store._connected = True
    store._ensure_api_ready = lambda: api
    store._order_to_payload = lambda order: {"symbol": "FAKE", "ref": order.ref}
    store._extract_external_order_id = lambda response: None
    store._submit_response_looks_accepted = lambda response: response.get("ok") is True
    store._cancel_response_error = lambda response: None
    store.emit_runtime_event = lambda *_args, **_kwargs: None
    store.sanitize_exception = lambda _error: None
    store._safe_exception_code = lambda _error, fallback: fallback
    return store


def test_candidate_still_reaches_fake_ctp_sinks_when_static_snapshot_says_binance():
    api = SnapshotSpoofApi()
    store = make_store(api)

    assert store.submit_order(SimpleNamespace(ref=17, info={})) == {"ok": True}
    assert store.cancel_order_ref("fake-17") == {"ok": True}

    assert api.calls == [
        ("submit", "CTP___TEST", 17),
        ("cancel", "CTP___TEST", "fake-17"),
    ]
    assert api.lookups == ["submit_order", "submit_order", "cancel_order", "cancel_order"]