"""Route-scoped offline probe for the package-owned local-backtest fixture."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROBE_PATH = REPOSITORY_ROOT / "scripts" / "probe_iteration41_zero_write_path.py"


def test_local_backtest_runtime_trace_is_bounded_and_keeps_unexercised_paths() -> None:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "BACKTRADER_LIGHT_IMPORT",
        "BACKTRADER_USE_INSTALLED",
    ):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [sys.executable, str(PROBE_PATH)],
        cwd=str(REPOSITORY_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    report = json.loads(completed.stdout)

    assert report["status"] == "LOCAL_BACKTEST_TRACE_WITH_STUBS"
    assert report["acceptance_boundary"] == "CANDIDATE_EVIDENCE_ONLY_NOT_WRITER_CLOSURE"
    assert report["registered_route"] == {
        "runtime_id": "backtrader.iteration41.local_backtest_fixture",
        "strategy_id": "backtrader.iteration41.local_backtest_fixture",
        "registry_id": "backtrader.iteration41.local-backtest-fixture",
        "runtime_path": "backtrader_runtime/_iteration41_backtest_fixture/runtimes/local_backtest",
        "mode": "backtest",
        "preset": "local_backtest",
        "capabilities": [],
        "secrets_ref": "none",
    }

    runtime = report["runtime_observation"]
    assert runtime["runner_status"] == "LOCAL_BACKTEST_CEREBRO_PASS"
    assert runtime["data_bars"] == 4
    assert runtime["runner_network_requests"] == 0
    assert runtime["runner_external_write_requests"] == 0
    assert runtime["runner_provider_submissions"] == 0
    assert runtime["runner_actual_fills"] == 0
    assert runtime["provider_modules_loaded"] == []
    assert runtime["route_result_passed_under_stubs"] is True
    assert runtime["runtime_config"] == {
        "strategy_id": "backtrader.iteration41.local_backtest_fixture",
        "mode": "backtest",
        "preset": "local_backtest",
        "environment": "local",
        "allows_network": False,
        "allows_external_writes": False,
        "allows_production_writes": False,
    }
    assert runtime["platform_version_process_stub_installed"] is True
    assert runtime["platform_version_process_stub_invoked"] is False
    assert runtime["backtrader_import_profile"] == "1"
    assert {stub["module"] for stub in runtime["optional_import_stubs"]} == {
        "talib",
        "backtrader.feeds.GenericCSVData",
    }

    assert report["static_scope_source_recheck"]["matches_frozen_inventory"] is True
    assert report["static_scope_source_recheck"]["added_since_frozen_inventory"] == 0
    assert report["static_scope_source_recheck"]["missing_from_current_source"] == 0
    assert report["static_scope_source_recheck"]["parse_errors"] == 0

    assert set(report["guard_event_counts"].values()) == {0}
    difference = report["candidate_difference"]
    assert difference["writer_closure_established"] is False
    assert difference["static_writer_callsites_invoked"] == 0
    assert difference["static_candidates_outside_loaded_source_files"] > 0
    assert difference["not_exercised_paths"]
    assert {
        entry["status"] for entry in difference["not_exercised_paths"]
    } == {"NOT_EXERCISED_NOT_ADMITTED"}
    assert difference["static_candidates_outside_loaded_source_files"] == sum(
        entry["candidate_count"] for entry in difference["not_exercised_paths"]
    )
    assert difference["unexercised_candidate_count"] == report["static_inventory"][
        "candidate_count"
    ] - difference["static_candidate_callsites_invoked"]
    assert difference["unexercised_candidate_count"] == sum(
        entry["candidate_count"]
        for entry in difference["unexercised_candidate_paths"]
    )
    assert {
        entry["status"] for entry in difference["unexercised_candidate_paths"]
    } == {"NOT_EXERCISED_NOT_ADMITTED"}

    assert all(
        item["classification"] == "LOCAL_HOST_IDENTITY_QUERY_NO_NETWORK_IO"
        for item in report["local_system_observations"]
    )
    assert report["process_observations"] == []
    assert report["file_write_observations"] == []
    assert "runtime-ctp-private" not in completed.stdout.lower()
    assert ".env" not in completed.stdout.lower()
    assert str(REPOSITORY_ROOT).lower() not in completed.stdout.lower()
