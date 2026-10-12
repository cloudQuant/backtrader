"""Contracts for the retired 013_1/013_2 CTP support compatibility shim."""

from __future__ import annotations

import builtins
import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest

from backtrader_runtime.errors import RuntimeConfigError

ROOT = Path(__file__).resolve().parents[2]
SUPPORT_PATHS = (
    ROOT / "examples" / "_support" / "ctp_legacy_example_support.py",
    ROOT
    / "examples"
    / "unified"
    / "013_1_midfreq_cross_arbitrage"
    / "ctp_example_support.py",
    ROOT
    / "examples"
    / "unified"
    / "013_2_highfreq_calendar_arbitrage"
    / "ctp_example_support.py",
)
COMPONENTS_PATH = (
    ROOT
    / "examples"
    / "live"
    / "000_live_certification"
    / "optional16"
    / "components.py"
)

RETIRED_CALLS = (
    ("load_dotenv_if_available", ()),
    ("get_simnow_credentials", ()),
    ("iter_simnow_env_candidates", ()),
    ("create_simnow_connection", ()),
    ("create_live_store", ({},)),
    ("create_live_broker", (object(), {})),
    ("add_live_feeds", (object(), object(), {})),
    ("run_cerebro_with_timeout", (object(),)),
)

PUBLIC_SUPPORT_NAMES = frozenset(
    {
        "AUTO_SIMNOW_ENV",
        "BASE_FUTURES_STRATEGY_PARAMS",
        "ConfigurableFuturesStrategyBase",
        "DEFAULT_APP_ID",
        "DEFAULT_AUTH_CODE",
        "DEFAULT_BROKER_ID",
        "DEFAULT_SIMNOW_ENV",
        "EXAMPLES_ROOT",
        "MemoryChannel",
        "PlaceholderData",
        "REPO_ROOT",
        "SIMNOW_ENVIRONMENTS",
        "SIMNOW_ENV_PRIORITY",
        "add_live_feeds",
        "attach_trade_logger",
        "create_live_broker",
        "create_live_store",
        "create_simnow_connection",
        "get_simnow_credentials",
        "iter_simnow_env_candidates",
        "load_config",
        "load_dotenv_if_available",
        "load_json_config",
        "parse_timeframe",
        "resolve_config_path",
        "run_cerebro_with_timeout",
    }
)


def _load_source(path: Path):
    name = "_iteration43_support_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return name, module


@pytest.mark.parametrize("support_path", SUPPORT_PATHS, ids=lambda path: path.parent.name)
def test_all_eight_retired_operations_fail_before_environment_or_provider_access(
    support_path: Path, monkeypatch
) -> None:
    """The old live helper names stop before environment/provider operations."""

    module_name, support = _load_source(support_path)
    assert PUBLIC_SUPPORT_NAMES.issubset(vars(support))
    monkeypatch.setattr(os, "getenv", lambda *_args, **_kwargs: pytest.fail("environment read"))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "dotenv" or name.startswith(
            ("backtrader.stores", "backtrader.feeds", "backtrader.brokers", "backtrader.channel")
        ):
            pytest.fail("provider or Backtrader data-path import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    provider_calls = []

    def forbidden_provider_call(name: str):
        def reject(*_args, **_kwargs):
            provider_calls.append(name)
            pytest.fail("provider construction or direct run")

        return reject

    for name in ("BtApiStore", "BtApiBroker", "BtApiFeed"):
        monkeypatch.setattr(support, name, forbidden_provider_call(name))
    monkeypatch.setattr(support.threading, "Timer", forbidden_provider_call("Timer"))
    try:
        for function_name, arguments in RETIRED_CALLS:
            with pytest.raises(RuntimeConfigError) as caught:
                getattr(support, function_name)(*arguments)
            assert caught.value.reason == "legacy_direct_execution_not_supported"
            assert caught.value.field_path == "legacy_entrypoint"
        assert provider_calls == []
    finally:
        sys.modules.pop(module_name, None)


def test_legacy_config_reader_only_reads_a_synthetic_fixture(tmp_path: Path) -> None:
    """The sole retained legacy helper reads the caller's offline fixture."""

    module_name, support = _load_source(SUPPORT_PATHS[0])
    config_path = tmp_path / "fixture.yaml"
    config_path.write_text("scenario: profitable\n", encoding="utf-8")
    try:
        config, resolved = support.load_config("fixture.yaml", tmp_path, "unused.yaml")
        assert config == {"scenario": "profitable"}
        assert resolved == config_path.resolve()
        assert support.load_json_config("fixture.yaml", tmp_path, "unused.yaml") == (
            config,
            config_path.resolve(),
        )
    finally:
        sys.modules.pop(module_name, None)


def test_optional_component_importerror_has_a_finite_category_without_provider_setup(
    tmp_path: Path, monkeypatch
) -> None:
    """Exercise the real optional16 wrapper while faking only its missing SDK import."""

    module_name, components = _load_source(COMPONENTS_PATH)
    attempted = []

    def missing_component(name: str) -> None:
        attempted.append(name)
        raise ImportError("synthetic optional SDK missing")

    monkeypatch.setattr(components, "_load_component", missing_component)
    run_dir = tmp_path / "optional16-run"
    try:
        with pytest.raises(components.ComponentError) as caught:
            components.wrap_client(
                object(),
                {"venue": "binance"},
                {"risk": True},
                {"OPTIONAL16_RUN_DIR": str(run_dir)},
            )
        assert str(caught.value) == "component_unavailable:risk"
        assert isinstance(caught.value.__cause__, ImportError)
        assert attempted == ["risk"]
        assert run_dir.is_dir()
    finally:
        sys.modules.pop(module_name, None)
