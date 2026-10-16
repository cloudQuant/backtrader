from __future__ import annotations

import builtins
import importlib.util
import sys
import types
from pathlib import Path

import pytest


_CERTLIB_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "live"
    / "000_live_certification"
    / "binance_penetration"
    / "certlib"
    / "__init__.py"
)


def _load_certlib():
    module_name = "_scn01_binance_certlib_fail_closed_fixture"
    spec = importlib.util.spec_from_file_location(
        module_name,
        _CERTLIB_PATH,
        submodule_search_locations=[str(_CERTLIB_PATH.parent)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module_name, module


@pytest.mark.parametrize(
    ("topology", "expected_error"),
    [
        ({"transport": "gateway_zmq"}, "transport_not_implemented:gateway_zmq"),
        ({"execution": True}, "component_not_implemented:execution"),
        ({"risk": True}, "component_not_implemented:risk"),
        ({"monitor": True}, "component_not_implemented:monitor"),
        (
            {"transport": "gateway_zmq", "execution": True},
            "transport_not_implemented:gateway_zmq",
        ),
    ],
)
def test_retired_optional16_backends_fail_before_any_bridge_or_venue_import(
    monkeypatch, topology, expected_error
):
    module_name, certlib = _load_certlib()
    import_attempts = []
    original_import = builtins.__import__

    def reject_retired_or_provider_import(name, globals=None, locals=None, fromlist=(), level=0):
        package = (globals or {}).get("__package__")
        if name == "optional16" or name.startswith("optional16."):
            import_attempts.append(name)
            raise AssertionError("retired Optional16 bridge was imported")
        if package == module_name and name.endswith("binance_client"):
            import_attempts.append(name)
            raise AssertionError("venue client was imported before backend rejection")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_retired_or_provider_import)
    try:
        with pytest.raises(RuntimeError) as caught:
            certlib.make_client({}, {}, topology)

        assert str(caught.value) == expected_error
        assert import_attempts == []
    finally:
        sys.modules.pop(module_name, None)


def test_default_direct_entry_still_builds_the_existing_venue_client(monkeypatch):
    module_name, certlib = _load_certlib()
    calls = []
    client_module = types.ModuleType(f"{module_name}.binance_client")

    class FakeBinanceDemoClient:
        def __init__(self, api_key, secret, *, host, timeout):
            calls.append((api_key, secret, host, timeout))

    client_module.BinanceDemoClient = FakeBinanceDemoClient
    monkeypatch.setitem(sys.modules, client_module.__name__, client_module)
    config = {
        "credentials": {"api_key_env": "DEMO_KEY", "secret_env": "DEMO_SECRET"},
        "environment": {"base_url": "demo.invalid"},
        "timeouts": {"request_seconds": 7.5},
    }
    env = {"DEMO_KEY": "synthetic-key", "DEMO_SECRET": "synthetic-secret"}

    try:
        client = certlib.make_client(config, env, {})

        assert isinstance(client, FakeBinanceDemoClient)
        assert calls == [("synthetic-key", "synthetic-secret", "demo.invalid", 7.5)]
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop(client_module.__name__, None)
