"""Offline coverage for early rejection of retired Store gateway routes."""

from __future__ import annotations

import pytest

from backtrader.stores.btapistore import (
    BtApiStore,
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
