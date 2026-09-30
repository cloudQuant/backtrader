"""Explicit topology requests cannot fall back to the generic provider bridge."""

import importlib
import itertools
import json
import os
import sys

import pytest
import yaml

from tests.unit.live_certification.test_000_venue_entry_contracts import (
    portable_suite,  # noqa: F401 - parametrized fixture shared by both portable venues
)


ROUTES = tuple(
    itertools.product(("direct", "gateway_zmq"), (False, True), (False, True), (False, True))
)


def _write_config(suite, tmp_path, topology, backend):
    raw = yaml.safe_load((suite.root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["topology"] = topology
    if backend == "python_factory":
        raw["backend"] = {"kind": backend, "target": "unavailable_test_provider:create_backend"}
    path = tmp_path / "public-test-config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


@pytest.mark.parametrize("transport,execution,risk,monitor", ROUTES)
@pytest.mark.parametrize("backend", ("http_json", "python_factory"))
def test_explicit_topology_blocks_before_import_secrets_or_backend(
    portable_suite, tmp_path, monkeypatch, transport, execution, risk, monitor, backend
):
    suite = portable_suite
    path = _write_config(
        suite,
        tmp_path,
        {"transport": transport, "execution": execution, "risk": risk, "monitor": monitor},
        backend,
    )
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("topology guard must run before backend/import/secret access")

    class NoEnvironment(dict):
        get = forbidden
        __getitem__ = forbidden

    monkeypatch.setattr(os, "environ", NoEnvironment())
    monkeypatch.setattr(importlib, "import_module", forbidden)
    monkeypatch.setattr(suite.modules["runner"], "create_backend", forbidden)
    monkeypatch.setattr(suite.modules["config"].Config, "resolve_credentials", forbidden)
    config = suite.modules["config"].load_config(path, suite.venue)
    assert config.topology.transport == transport
    assert (config.topology.execution, config.topology.risk, config.topology.monitor) == (
        execution,
        risk,
        monitor,
    )
    evidence = tmp_path / "evidence"
    with pytest.raises(
        suite.modules["models"].CertificationError, match="selected topology unavailable"
    ):
        suite.modules["runner"].run_live(
            config, ["C01"], suite.modules["config"].Grants(), evidence
        )
    assert not calls
    assert not evidence.exists()


@pytest.mark.parametrize(
    "topology",
    (
        None,
        {},
        {"transport": "gateway", "execution": False, "risk": False, "monitor": False},
        {"transport": "direct", "execution": "false", "risk": False, "monitor": False},
        {"transport": "direct", "execution": False, "risk": False},
        {
            "transport": "direct",
            "execution": False,
            "risk": False,
            "monitor": False,
            "fallback": True,
        },
    ),
)
def test_topology_config_rejects_incomplete_or_ambiguous_selections(
    portable_suite, tmp_path, topology
):
    suite = portable_suite
    path = _write_config(suite, tmp_path, topology, "http_json")
    with pytest.raises(suite.modules["models"].CertificationError):
        suite.modules["config"].load_config(path, suite.venue)


def test_cli_reports_explicit_topology_block_without_backend(
    portable_suite, tmp_path, monkeypatch, capsys
):
    suite = portable_suite
    path = _write_config(
        suite,
        tmp_path,
        {
            "transport": "gateway_zmq",
            "execution": True,
            "risk": True,
            "monitor": True,
        },
        "python_factory",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "certification",
            "--config",
            str(path),
            "--case",
            "C01",
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ],
    )
    assert suite.modules["cli"].run_venue_cli(suite.venue) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"status": "BLOCKED", "error_type": "CertificationError"}
    assert "unavailable_test_provider" not in sys.modules


def test_omitted_topology_reports_legacy_bridge_identity(portable_suite, tmp_path):
    suite = portable_suite
    config = suite.modules["config"].load_config(suite.root / "config.example.yaml", suite.venue)
    assert config.topology is None
    results, summary_path = suite.modules["runner"].run_live(
        config,
        ["C01"],
        suite.modules["config"].Grants(),
        tmp_path / "evidence",
    )
    assert results[0].status == suite.modules["models"].Status.BLOCKED
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["summary"]["route_identity"] == "legacy_generic_bridge"
    records = [
        json.loads(line)
        for line in next(summary_path.parent.glob("*.jsonl")).read_text().splitlines()
    ]
    assert records[0]["kind"] == "run_start"
    assert records[0]["data"]["route_identity"] == "legacy_generic_bridge"
