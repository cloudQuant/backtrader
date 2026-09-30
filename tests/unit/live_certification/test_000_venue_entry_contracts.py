"""Offline entry contracts for the portable Binance and OKX certification suites."""

import importlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import sys
from types import SimpleNamespace

import pytest


SUITES_ROOT = Path(__file__).resolve().parents[3] / "examples" / "000_live_certification"
CASE_IDS = frozenset(
    [
        "C01",
        "T01",
        "T02",
        "T03",
        "M01",
        "M02",
        "M03",
        "M04",
        "M05",
        "O01",
        "O02",
        "O03",
        "TH01",
        "TH02",
        "TH03",
        "TH04",
        "TH05",
        "TH06",
        "V01",
        "V02",
        "V03",
        "E01",
        "E02",
        "E03",
        "EM01",
        "EM02",
        "EM03",
        "B01",
        "B02",
        "L01",
        "L02",
        "L03",
        "L04",
    ]
)


@pytest.fixture(params=("binance", "okx"))
def portable_suite(request, tmp_path, monkeypatch):
    """Copy public sources only; isolate identically named per-venue modules."""
    venue = request.param
    source = SUITES_ROOT / f"{venue}_penetration"
    root = tmp_path / f"{venue}_penetration"
    for directory in ("_certification", "cases"):
        shutil.copytree(
            source / directory, root / directory, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copyfile(source / "config.example.yaml", root / "config.example.yaml")
    names = {f"{case_id}_strategy" for case_id in CASE_IDS}

    def belongs(name):
        return name in names or name == "_certification" or name.startswith("_certification.")

    previous = {name: module for name, module in sys.modules.items() if belongs(name)}
    for name in previous:
        sys.modules.pop(name)
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {})
    network_calls = []

    def deny_network(*args, **kwargs):
        network_calls.append(True)
        raise AssertionError("offline certification test attempted network access")

    for target, attribute in (
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket.socket, "sendto"),
    ):
        monkeypatch.setattr(target, attribute, deny_network)
    try:
        modules = {
            name: importlib.import_module(f"_certification.{name}")
            for name in ("cli", "config", "runner", "models", "cases")
        }
        yield SimpleNamespace(venue=venue, root=root, modules=modules)
    finally:
        for name in list(sys.modules):
            if belongs(name):
                sys.modules.pop(name)
        sys.modules.update(previous)
        assert not network_calls, "a blocked result must not conceal attempted network access"


def _run_entry(suite, case_id, monkeypatch, evidence_dir, *extra):
    entry = suite.root / "cases" / case_id / "run.py"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(entry),
            "--config",
            str(suite.root / "config.example.yaml"),
            "--evidence-dir",
            str(evidence_dir),
            *extra,
        ],
    )
    # Each entry adds its own case directory; retain test isolation afterwards.
    monkeypatch.setattr(sys, "path", sys.path[:])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(entry), run_name="__main__")
    return exit_info.value.code


def test_all_33_entries_bind_their_case_and_portable_venue(portable_suite, monkeypatch):
    suite = portable_suite
    actual = {path.name for path in (suite.root / "cases").iterdir() if path.is_dir()}
    assert actual == CASE_IDS
    assert set(suite.modules["cases"].CASES) == CASE_IDS
    for module in suite.modules.values():
        assert Path(module.__file__).resolve().is_relative_to(suite.root)
    calls = []

    def capture(venue, case_id, case_spec, proof_fields):
        calls.append((venue, case_id))
        assert case_spec == suite.modules["cases"].CASES[case_id]
        assert proof_fields == suite.modules["runner"].case_proof_fields(case_id)
        return 2

    monkeypatch.setattr(suite.modules["cli"], "run_case_cli", capture)
    for case_id in sorted(CASE_IDS):
        assert (suite.root / "cases" / case_id / f"{case_id}_strategy.py").is_file()
        assert _run_entry(suite, case_id, monkeypatch, suite.root / "evidence") == 2
    assert calls == [(suite.venue, case_id) for case_id in sorted(CASE_IDS)]


def test_c01_empty_environment_blocks_without_network_or_credentials(
    portable_suite, monkeypatch, tmp_path, capsys
):
    suite = portable_suite
    evidence_dir = tmp_path / "evidence"
    config = suite.modules["config"].load_config(suite.root / "config.example.yaml", suite.venue)
    assert config.cases["C01"].enabled
    assert suite.modules["cases"].CASES["C01"].risk == suite.modules["models"].Risk.READ
    assert _run_entry(suite, "C01", monkeypatch, evidence_dir) == 2
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["venue"] == suite.venue
    assert output["results"] == [
        {
            "case_id": "C01",
            "status": "BLOCKED",
            "reason": "v2 live attestation failed (CertificationError)",
        }
    ]
    assert captured.err == ""
    emitted = captured.out + "".join(path.read_text() for path in evidence_dir.iterdir())
    for env_name in (
        *config.credentials.values(),
        config.backend.endpoint_env,
        config.backend.token_env,
    ):
        assert env_name not in emitted


def test_disabled_t01_cli_grant_cannot_create_backend(
    portable_suite, monkeypatch, tmp_path, capsys
):
    suite = portable_suite
    backend_calls = []

    def forbidden_backend(config):
        backend_calls.append(config)
        raise AssertionError("disabled case reached backend creation")

    monkeypatch.setattr(suite.modules["runner"], "create_backend", forbidden_backend)
    assert (
        _run_entry(
            suite,
            "T01",
            monkeypatch,
            tmp_path / "evidence",
            "--allow-write",
            "--confirm",
            f"{suite.venue}:demo:WRITE",
        )
        == 2
    )
    assert not backend_calls
    assert json.loads(capsys.readouterr().out)["results"] == [
        {
            "case_id": "T01",
            "status": "BLOCKED",
            "reason": "case not configured or disabled",
        }
    ]


def test_portable_runtime_rejects_other_venue_config(portable_suite):
    suite = portable_suite
    other = "okx" if suite.venue == "binance" else "binance"
    with pytest.raises(
        suite.modules["models"].CertificationError, match="config venue does not match"
    ):
        suite.modules["config"].load_config(suite.root / "config.example.yaml", other)
