from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_CERTIFICATION_ROOT = _REPO / "examples/live/000_live_certification"


def _load_runner(venue: str):
    package_name = f"_scn01_{venue}_preflight_certlib"
    certlib_path = _CERTIFICATION_ROOT / f"{venue}_penetration/certlib/__init__.py"
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == package_name or name.startswith(package_name + ".")
    }
    for name in previous_modules:
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        package_name,
        certlib_path,
        submodule_search_locations=[str(certlib_path.parent)],
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = package
    spec.loader.exec_module(package)
    return package_name, importlib.import_module(f"{package_name}.runner"), previous_modules


@pytest.mark.parametrize("venue", ["okx", "simnow"])
def test_unsupported_transport_is_blocked_before_strategy_env_or_provider_io(
    venue, tmp_path, monkeypatch, capsys
):
    package_name, runner, previous_modules = _load_runner(venue)
    case_dir = _CERTIFICATION_ROOT / f"{venue}_penetration/cases/T01"
    env_loads = []
    strategy_loads = []
    client_builds = []

    def forbidden_client_factory(*args, **kwargs):
        client_builds.append((args, kwargs))
        raise AssertionError("unsupported transport reached client factory")

    monkeypatch.setattr(
        runner.envfile,
        "load_env",
        lambda names: (env_loads.append(tuple(names)) or ({}, [])),
    )
    monkeypatch.setattr(
        runner,
        "_load_strategy",
        lambda *args: (strategy_loads.append(args) or (None, "READ")),
    )
    monkeypatch.setattr(runner, "make_client", forbidden_client_factory)
    monkeypatch.setattr(sys, "argv", [str(case_dir / "run.py")])
    try:
        exit_code = runner.main_case(
            [
                "--live",
                "--allow-write",
                "--transport",
                "gateway_zmq",
                "--evidence-dir",
                str(tmp_path / f"{venue}-T01-evidence"),
            ]
        )
        output_lines = [
            line for line in capsys.readouterr().out.splitlines() if line.startswith("{")
        ]
        summary = json.loads(output_lines[-1])
        provider_module = "ctp_client" if venue == "simnow" else "okx_client"

        assert exit_code == 2, summary
        assert summary["venue"] == venue
        assert summary["case"] == "T01"
        assert summary["status"] == "BLOCKED"
        assert summary["reason"] == "transport_not_implemented"
        assert summary["facts"] == {
            "requested_backend": "gateway_zmq",
            "credential_lookup": "not_attempted",
            "provider_attempted": False,
        }
        assert env_loads == []
        assert strategy_loads == []
        assert client_builds == []
        assert f"{package_name}.{provider_module}" not in sys.modules
        evidence = json.loads(Path(summary["evidence"]).read_text(encoding="utf-8"))
        assert evidence["status"] == "BLOCKED"
        assert evidence["reason"] == "transport_not_implemented"
        assert evidence["facts"] == summary["facts"]
        assert evidence["client"] is None
        assert evidence["calls"] == []
    finally:
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
