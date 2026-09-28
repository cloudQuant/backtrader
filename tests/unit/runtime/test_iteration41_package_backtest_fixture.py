"""Acceptance for the shipped config-first local-backtest runtime fixture."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from backtrader_runtime.cli import main
from backtrader_runtime.inventory import (
    ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID,
    iteration41_backtest_fixture_registry,
    iteration41_runtime_registry,
)


def _payload(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue())


def test_package_backtest_fixture_is_explicitly_registered_without_capabilities() -> None:
    fixture_registry = iteration41_backtest_fixture_registry()
    registration = fixture_registry.registrations[0]

    assert registration.runtime_id == ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID
    assert registration.strategy_id == ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID
    assert registration.allowed_presets == ("local_backtest",)
    assert registration.capability_modules == ()
    assert registration.available_capabilities == ()
    assert registration.runtime_dir.joinpath("config.yaml").is_file()
    assert registration in iteration41_runtime_registry().registrations


def test_package_backtest_fixture_runs_cerebro_through_mandatory_config() -> None:
    fixture_registry = iteration41_backtest_fixture_registry()
    registration = fixture_registry.registrations[0]
    # The shipped CLI runs in a fresh process. Other tests may have imported
    # SDK packages into this pytest process, which the zero-capability fixture
    # correctly rejects as ambient, unregistered capability state.
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtrader_runtime.cli",
            "run",
            "--strategy-dir",
            str(registration.runtime_dir),
            "--full-report",
        ],
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    report = payload["report"]["result"]
    assert payload["mode"] == "backtest"
    assert payload["preset"] == "local_backtest"
    assert payload["allows_network"] is False
    assert payload["allows_external_writes"] is False
    assert report == {
        "status": "LOCAL_BACKTEST_CEREBRO_PASS",
        "external_network_requests": 0,
        "external_write_requests": 0,
        "actual_fills": 0,
        "provider_submissions": 0,
        "actual_pnl": "NOT_APPLICABLE",
        "pnl_source": "local_backtest_no_orders",
        "data_bars": 4,
        "network_guard_attempts": [],
        "runtime_config": {
            "strategy_id": ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID,
            "mode": "backtest",
            "preset": "local_backtest",
            "environment": "local",
            "allows_network": False,
            "allows_external_writes": False,
            "allows_production_writes": False,
        },
    }


def test_doctor_explains_the_backtest_as_a_local_zero_write_destination() -> None:
    fixture_registry = iteration41_backtest_fixture_registry()
    registration = fixture_registry.registrations[0]
    stdout = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(registration.runtime_dir)],
        registry=fixture_registry,
        environ={},
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert status == 0
    diagnostic = _payload(stdout)["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["operator_summary"] == {
        "mode": "backtest",
        "preset": "local_backtest",
        "destination": "local_runtime",
        "environment": "local",
        "write_boundary": "zero_external_writes",
        "pnl_source": "not_applicable_without_external_fills",
        "required_capabilities": [],
        "requires_approval": False,
    }
