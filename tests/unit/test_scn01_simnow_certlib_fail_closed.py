from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path

import pytest


_CERTLIB_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "live"
    / "000_live_certification"
    / "simnow_penetration"
    / "certlib"
    / "__init__.py"
)


def _load_certlib():
    module_name = "_scn01_simnow_certlib_fail_closed_fixture"
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
    ],
)
def test_missing_simnow_backend_is_rejected_before_ctp_import(
    monkeypatch, topology, expected_error
):
    module_name, certlib = _load_certlib()
    ctp_import_attempts = []
    original_import = builtins.__import__

    def reject_ctp_client_import(name, globals=None, locals=None, fromlist=(), level=0):
        package = (globals or {}).get("__package__")
        if package == module_name and name.endswith("ctp_client"):
            ctp_import_attempts.append(name)
            raise AssertionError("blocked backend imported the CTP provider client")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_ctp_client_import)
    try:
        with pytest.raises(RuntimeError) as caught:
            certlib.make_client({}, {}, topology)

        assert str(caught.value) == expected_error
        assert ctp_import_attempts == []
    finally:
        sys.modules.pop(module_name, None)
