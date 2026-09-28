"""Fail-closed tests for CTP routes without a typed managed session."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


class _SelfDispatchingAdapter:
    """Model a generic adapter that need not use the Store callback port."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit_order(self, order: object, _dispatch: object) -> dict[str, str]:
        self.calls.append("submit")
        return {"status": "projected"}

    def cancel_order(
        self, order_or_ref: object, _dataname: object, _dispatch: object
    ) -> dict[str, str]:
        self.calls.append("cancel")
        return {"status": "projected"}


def _store(
    *,
    provider: str,
    backend: str,
    config: dict,
    api_kwargs: dict,
    adapter,
    sdk_exchanges: dict | None = None,
):
    store = object.__new__(BtApiStore)
    store.provider = provider
    store.backend = backend
    store._config = dict(config)
    store._api_kwargs = dict(api_kwargs)
    store._sdk_exchanges = dict(sdk_exchanges or {})
    store._sdk_routes = {}
    store._api = None
    store._managed_execution_adapter = adapter
    store._sdk_mode = False
    store._connected = True
    store.emit_runtime_event = lambda *_args, **_kwargs: None
    store._extract_dataname = lambda _data: "IF2506"
    return store


_CTP_ALIAS_ROUTES = (
    pytest.param(
        "btapi",
        "forwarding",
        {"exchange": "CTP"},
        {"exchange_type": "BINANCE"},
        id="forwarding-conflicting-ctp-signal",
    ),
    pytest.param(
        "btapi",
        "gateway",
        {"exchange_type": "CTP___SHFE"},
        {},
        id="gateway-ctp-route-alias",
    ),
    pytest.param(
        "btapi",
        "forwarding",
        {"exchange": "CTP"},
        {"exchange_type": "CTP"},
        id="forwarding-ctp-sdk-snapshot",
    ),
    pytest.param(
        "ctp",
        "forwarding",
        {"exchange": "CTP"},
        {"exchange_type": "CTP"},
        id="forwarding-ctp-provider",
    ),
    pytest.param(
        "ctp_gateway",
        "forwarding",
        {"exchange": "CTP"},
        {"exchange_type": "CTP"},
        id="forwarding-ctp-gateway-provider",
    ),
)


@pytest.mark.parametrize(("provider", "backend", "config", "api_kwargs"), _CTP_ALIAS_ROUTES)
@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_untyped_ctp_managed_alias_rejects_before_adapter_dispatch(
    provider, backend, config, api_kwargs, operation
):
    adapter = _SelfDispatchingAdapter()
    store = _store(
        provider=provider,
        backend=backend,
        config=config,
        api_kwargs=api_kwargs,
        adapter=adapter,
        sdk_exchanges={"CTP": {}}
        if backend == "forwarding" and api_kwargs.get("exchange_type") == "CTP"
        else None,
    )

    with pytest.raises(BtApiStoreError, match="generic managed execution adapter"):
        if operation == "submit":
            store.submit_order(SimpleNamespace(ref=1, info={}))
        else:
            store.cancel_order(SimpleNamespace(ref=1, info={}, data=None))

    assert adapter.calls == []


def test_non_ctp_forwarding_managed_adapter_remains_available():
    adapter = _SelfDispatchingAdapter()
    store = _store(
        provider="btapi",
        backend="forwarding",
        config={"exchange": "BINANCE"},
        api_kwargs={"exchange_type": "BINANCE"},
        adapter=adapter,
    )

    assert store.submit_order(SimpleNamespace(ref=2, info={})) == {"status": "projected"}
    assert store.cancel_order(
        SimpleNamespace(ref=2, info={}, data=SimpleNamespace(_name="BTC-USDT"))
    ) == {"status": "projected"}
    assert adapter.calls == ["submit", "cancel"]


@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_normal_forwarding_store_construction_cannot_dispatch_ctp_signal(operation):
    adapter = _SelfDispatchingAdapter()
    store = BtApiStore(
        provider="btapi",
        backend="forwarding",
        config={"exchange": "CTP"},
        api_kwargs={"exchange_type": "BINANCE"},
        managed_execution_adapter=adapter,
    )

    with pytest.raises(BtApiStoreError, match="generic managed execution adapter"):
        if operation == "submit":
            store.submit_order(SimpleNamespace(ref=3, info={}))
        else:
            store.cancel_order(SimpleNamespace(ref=3, info={}, data=None))

    assert adapter.calls == []
