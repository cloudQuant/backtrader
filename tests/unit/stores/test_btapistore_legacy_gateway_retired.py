"""Offline coverage for early rejection of retired Store gateway routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import backtrader.stores.btapistore as store_module
from backtrader.stores.btapistore import (
    BtApiStore,
    BtApiStoreError,
    LegacyGatewayMigrationRequiredError,
)


@pytest.mark.parametrize(
    ("provider", "backend"),
    [
        ("btapi", "forwarding"),
        ("btapi", "gateway"),
        ("forwarding", "direct"),
        ("gateway", "direct"),
        ("ctp_gateway", "direct"),
        ("mt5_gateway", None),
        ("ib_web_gateway", None),
        ("vendor_gateway", None),
    ],
)
def test_retired_backend_and_provider_routes_fail_before_api_construction(
    provider: str,
    backend: str | None,
) -> None:
    api_constructions: list[dict[str, object]] = []

    def api_factory(**kwargs):
        api_constructions.append(kwargs)
        raise AssertionError("retired Store route must fail before client construction")

    with pytest.raises(LegacyGatewayMigrationRequiredError) as raised:
        BtApiStore(provider=provider, backend=backend, api_cls=api_factory)

    assert raised.value.code == "MIGRATION_REVIEW_REQUIRED"
    assert "ServiceClientRuntime" in str(raised.value)
    assert "ServiceExecutionSession" in str(raised.value)
    assert api_constructions == []


@pytest.mark.parametrize("env_provider", ("forwarding", "gateway", "ctp_gateway"))
def test_gateway_provider_selected_by_environment_is_rejected_early(
    monkeypatch,
    env_provider: str,
) -> None:
    monkeypatch.setenv("BT_STORE_PROVIDER", env_provider)
    api_constructions: list[dict[str, object]] = []

    def api_factory(**kwargs):
        api_constructions.append(kwargs)
        raise AssertionError("retired Store route must fail before client construction")

    with pytest.raises(LegacyGatewayMigrationRequiredError) as raised:
        BtApiStore(provider="ctp", api_cls=api_factory)

    assert raised.value.target == f"provider={env_provider!r}"
    assert api_constructions == []


def test_direct_store_with_injected_api_remains_available() -> None:
    api = object()

    store = BtApiStore(provider="okx", api=api)

    assert store.backend == "direct"
    assert store._api is api


def test_mutated_legacy_backend_is_rejected_before_startup_work() -> None:
    store = BtApiStore(provider="okx", api=object())
    store.backend = "forwarding"

    with pytest.raises(LegacyGatewayMigrationRequiredError) as raised:
        store.start()

    assert raised.value.target == "backend='forwarding'"

    with pytest.raises(LegacyGatewayMigrationRequiredError) as raised:
        store._ensure_api_ready()

    assert raised.value.target == "backend='forwarding'"
    with pytest.raises(LegacyGatewayMigrationRequiredError) as raised:
        store._create_forwarding_client()

    assert raised.value.target == "backend='forwarding'"


def test_gateway_client_resolver_rejects_before_importing_sdk(monkeypatch) -> None:
    imported: list[str] = []

    def unexpected_import(name: str):
        imported.append(name)
        raise AssertionError("retired gateway route must fail before SDK import")

    monkeypatch.setattr(store_module.importlib, "import_module", unexpected_import)

    with pytest.raises(LegacyGatewayMigrationRequiredError) as raised:
        store_module._resolve_bt_api_client("vendor_gateway")

    assert raised.value.target == "provider='vendor_gateway'"
    assert imported == []


def test_gateway_environment_does_not_mutate_direct_store_configuration(monkeypatch) -> None:
    monkeypatch.setenv("BT_GATEWAY_ACCOUNT_ID", "legacy-account")
    monkeypatch.setenv("BT_GATEWAY_COMMAND_ENDPOINT", "ipc://legacy-command")
    api = object()

    store = BtApiStore(provider="okx", api=api)

    assert store.backend == "direct"
    assert store._api_kwargs == {}
    assert store.sdk_api is api


def test_injected_read_only_service_api_remains_on_direct_store() -> None:
    class ReadOnlyServiceApi:
        service_read_only = True
        exchange_kwargs = {"BINANCE___SPOT": {}}

        def __init__(self) -> None:
            self.connect_calls = 0
            self.disconnect_calls = 0
            self.write_calls = 0

        def connect(self) -> None:
            self.connect_calls += 1

        def disconnect(self) -> None:
            self.disconnect_calls += 1

        def get_balance(self) -> dict[str, float]:
            return {"cash": 100.0, "value": 100.0}

        def submit_order(self, *_args, **_kwargs) -> None:
            self.write_calls += 1

    api = ReadOnlyServiceApi()
    store = BtApiStore(provider="btapi", api=api)

    assert store.backend == "direct"
    assert store._service_read_only is True
    assert store.sdk_api is api
    assert store._ensure_api_ready() is api
    assert api.connect_calls == 1

    with pytest.raises(BtApiStoreError, match="read-only service proxy cannot submit orders"):
        store.submit_order(object())

    assert api.write_calls == 0
    store.stop()
    assert api.disconnect_calls == 1


def test_packaged_store_source_contains_no_gateway_runtime() -> None:
    source = Path(store_module.__file__).read_text(encoding="utf-8")

    for retired in (
        "_create_ctp_gateway_wrapper_class",
        "bt_api_py.gateway.client",
        "_gateway_timeframe_str",
        "_apply_env_gateway_overrides",
    ):
        assert retired not in source

    assert "def _legacy_gateway_entrypoint" in source
    assert "def _resolve_backend" in source
