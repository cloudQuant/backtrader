"""Regression coverage for the packaged Iteration 41 fake-provider L2 fixture."""

from __future__ import annotations

import yaml
import pytest

from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.inventory import (
    PACKAGE_L2_FIXTURE_ROOT,
    iteration41_l2_fixture_registry,
)
from backtrader_runtime.registry import resolve_runtime_config


EXPECTED_RUNTIME_IDS = {
    "example.013_3.sa_midfreq_simnow.managed_replay_l2",
    "example.ctp_options_simnow.mechanical_managed_replay_l2",
}
EXPECTED_RUNNER_MODULES = {
    "backtrader_runtime._iteration41_l2_fixture.managed_013_3",
    "backtrader_runtime._iteration41_l2_fixture.mechanical_p1b",
}
EXPECTED_CONFIG_FIELDS = {
    "config_schema_version",
    "strategy",
    "runtime",
    "parameters",
}
EXPECTED_PACKAGE_FILES = (
    "__init__.py",
    "managed_013_3.py",
    "mechanical_cycle.py",
    "mechanical_p1b.py",
    "runtimes/managed_013_3/config.yaml",
    "runtimes/mechanical_p1b/config.yaml",
)


def test_packaged_l2_fixture_registry_and_configs_are_replay_only() -> None:
    """The package fixture stays a sealed two-route, credential-free test surface."""

    registry = iteration41_l2_fixture_registry()
    registrations = tuple(registry.registrations)

    assert registry.registry_id == "backtrader.iteration41.l2-wheel-fixture"
    assert tuple(item.name for item in registry.runtime_sets) == ("iteration41-l2-wheel-fixture",)
    assert {registration.runtime_id for registration in registrations} == EXPECTED_RUNTIME_IDS
    assert {registration.runner_module for registration in registrations} == EXPECTED_RUNNER_MODULES

    for relative_path in EXPECTED_PACKAGE_FILES:
        assert (PACKAGE_L2_FIXTURE_ROOT / relative_path).is_file()

    for registration in registrations:
        assert registration.runtime_dir.resolve().relative_to(PACKAGE_L2_FIXTURE_ROOT.resolve())
        assert registration.allowed_presets == ("replay",)
        assert registration.allowed_secrets_refs == ("none",)
        assert registration.offline_managed_execution is True

        source = yaml.safe_load((registration.runtime_dir / "config.yaml").read_text(encoding="utf-8"))
        assert set(source) == EXPECTED_CONFIG_FIELDS
        assert source["config_schema_version"] == 4
        assert source["strategy"] == {"id": registration.strategy_id}
        assert source["runtime"] == {"mode": "simulation", "preset": "replay"}
        assert source["parameters"] == {}

        config = load_runtime_config(registration.runtime_dir, registry=registry)
        effective = resolve_runtime_config(config, registry)
        assert config.strategy_id == registration.strategy_id
        assert config.mode == "simulation"
        assert config.preset == "replay"
        assert config.parameter_dict() == {}
        assert config.secrets_ref == "none"
        assert effective.registration is registration


@pytest.mark.parametrize("fixture_module", ("managed_013_3", "mechanical_p1b"))
def test_packaged_l2_fixture_pins_each_sdk_distribution_version(fixture_module: str) -> None:
    """The source-only SDK metadata must match each fixture's own exact pin."""

    from importlib import import_module

    fixture = import_module(f"backtrader_runtime._iteration41_l2_fixture.{fixture_module}")
    assert fixture._CAPABILITY_VERSIONS == {
        "bt_api_execution": "0.2.0",
        "bt_api_risk": "0.1.0",
        "bt_api_monitor": "0.1.0",
    }


def test_packaged_l2_capability_catalog_rejects_a_wrong_source_version() -> None:
    """A present but wrong distribution version still fails before module import."""

    runtime_plugins = pytest.importorskip("bt_api_py.runtime_plugins")
    catalog_module = pytest.importorskip("bt_api_py.runtime_plugins.catalog")
    contracts_module = pytest.importorskip("bt_api_py.runtime_plugins.contracts")
    contract = contracts_module.RuntimeCapabilityContract(
        strategy_id="example.013_3.sa_midfreq_simnow",
        mode="simulation",
        preset="replay",
        environment="offline",
        order_route="managed_execution",
        required_capabilities=(
            runtime_plugins.CAPABILITY_EXECUTION,
            runtime_plugins.CAPABILITY_RISK,
            runtime_plugins.CAPABILITY_MONITOR,
        ),
        effective_digest="a" * 64,
    )
    pins = (
        catalog_module.CapabilityPin(
            runtime_plugins.CAPABILITY_EXECUTION,
            "bt_api_execution",
            "bt_api_execution",
            "0.2.0",
        ),
        catalog_module.CapabilityPin(
            runtime_plugins.CAPABILITY_RISK,
            "bt_api_risk",
            "bt_api_risk",
            "0.1.0",
        ),
        catalog_module.CapabilityPin(
            runtime_plugins.CAPABILITY_MONITOR,
            "bt_api_monitor",
            "bt_api_monitor",
            "0.1.0",
        ),
    )
    catalog = catalog_module.CapabilityCatalog(
        pins,
        importer=lambda _module: pytest.fail("wrong distribution version imported a module"),
        version_getter=lambda _distribution: "999.0.0",
    )
    with pytest.raises(catalog_module.RuntimePluginError) as error:
        catalog.load(contract)
    assert error.value.code == "CAPABILITY_VERSION_MISMATCH"

