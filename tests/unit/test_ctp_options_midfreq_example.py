"""Black-box checks for the self-contained Iteration 24 replay example."""

import ast
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "014_2_ctp_options_midfreq"
RUNNER = EXAMPLE / "run.py"
CONFIG = EXAMPLE / "config.yaml"


def _run(*arguments: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    return subprocess.run(
        [sys.executable, str(RUNNER), *arguments],
        cwd=str(EXAMPLE),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _report(result: subprocess.CompletedProcess) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def test_direct_subprocess_runs_actual_cerebro_with_no_external_side_effects() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    report = _report(result)
    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["cerebro"] == {
        "broker_class": "BackBroker",
        "feed_count": 3,
        "strategy": "CTPOptionsMidFrequencyStrategy",
    }
    assert report["ordinary_decision_path"] == "closed minute bar next() only"
    assert report["history_window_bars"] == 60
    assert report["ordinary_decision_count"] == 1
    assert report["ordinary_decisions"][0]["outcome"] == "NO_EDGE"
    assert report["ordinary_decisions"][0]["tradable"] is False
    assert report["ordinary_decisions"][0]["signal_scope"] == "fq2_frozen_features"
    assert report["external_network_requests"] == 0
    assert report["external_trade_writes"] == 0
    assert report["orders_submitted"] == 0
    assert report["actual_pnl"] is None
    assert report["actual_pnl_status"] == "NOT_AVAILABLE"
    assert report["gates"]["G3_first_set_read_only"] == "NOT_RUN"
    assert report["barrier"]["quote_cutoff"] == "frozen_at_bar_seal"
    assert report["barrier"]["tick_feature_scope"] == "full_5s_60s_window"
    assert report["feature_history"][-1]["short_window_covered_ms"] == 5000
    assert report["feature_history"][-1]["long_window_covered_ms"] == 60000
    assert report["feature_history"][-1]["short_window_complete"] is True
    assert report["feature_history"][-1]["long_window_complete"] is True
    assert report["actual_order_permission"] == "NOT_PROVEN"


def test_runtime_import_graph_has_no_other_example_dependency_or_path_injection() -> None:
    for source in (RUNNER, EXAMPLE / "ctp_options_midfreq_strategy.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        assert all(
            module != "examples" and not module.startswith("examples.")
            for module in imported_modules
        )
        source_text = source.read_text(encoding="utf-8")
        assert "sys.path" not in source_text
        assert "importlib" not in source_text
        assert "pkgutil" not in source_text

    result = _run("--scenario", "edge")
    assert result.returncode == 0, result.stderr
    report = _report(result)
    assert report["self_contained_runtime"] is True
    assert report["contracts"] == {
        "call": "C_LOCAL_1000",
        "future": "F_LOCAL_1000",
        "put": "P_LOCAL_1000",
    }


def test_tick_callback_cannot_submit_an_ordinary_trade_and_rejects_cutoff_boundary(
    tmp_path: Path,
) -> None:
    no_edge = _run("--inject-cutoff-tick")
    assert no_edge.returncode == 0, no_edge.stderr
    no_edge_report = _report(no_edge)
    assert no_edge_report["ordinary_decision_count_before_tick"] == 1
    assert no_edge_report["ordinary_decision_count"] == 1
    assert no_edge_report["accepted_cutoff_tick_features"]
    assert no_edge_report["orders_submitted"] == 0
    assert all(decision["origin"] == "next" for decision in no_edge_report["ordinary_decisions"])

    boundary = _run("--inject-at-cutoff-tick")
    assert boundary.returncode == 0, boundary.stderr
    boundary_report = _report(boundary)
    assert boundary_report["accepted_cutoff_tick_features"] == []
    assert boundary_report["rejected_tick_count"] == 1
    assert boundary_report["orders_submitted"] == 0

    external_config = tmp_path / "budget-rejected.yaml"
    external_config.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    blocked = _run("--config", str(external_config), "--scenario", "edge")
    assert blocked.returncode == 2, blocked.stderr
    blocked_report = _report(blocked)
    assert blocked_report["status"] == "REJECTED"
    assert blocked_report["error_code"] == "CONFIG_PATH"
    assert blocked_report["external_trade_writes"] == 0


def test_fixed_budget_boundaries_and_timezone_qualified_ticks_fail_closed(tmp_path: Path) -> None:
    module_name = "iter24_config_contract"
    spec = importlib.util.spec_from_file_location(
        module_name, EXAMPLE / "ctp_options_midfreq_strategy.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    for field, value, expected_code in (
        ("capital_limit_cny", 10001, "CAPITAL_CAP"),
        ("working_limit_cny", 8001, "WORKING_CAP"),
        ("recovery_reserve_cny", 1999, "RECOVERY_RESERVE"),
    ):
        invalid = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        invalid["budget"][field] = value
        with pytest.raises(module.ConfigurationError) as captured:
            module.validate_config(invalid)
        assert captured.value.code == expected_code

    module_name = "iter24_timezone_contract"
    spec = importlib.util.spec_from_file_location(
        module_name, EXAMPLE / "ctp_options_midfreq_strategy.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    assert module._parse_datetime("2026-01-05T02:00:00-08:00") is None
    assert module._parse_datetime("2026-01-05T02:00:00Z") is None
    assert module._parse_datetime("2026-01-05T02:00:00") == datetime(2026, 1, 5, 2, 0)


def test_non_replay_mode_fails_closed_before_any_external_action() -> None:
    for mode, error_code in (
        ("shadow", "MODE_NOT_SUPPORTED_OFFLINE"),
        ("simnow", "MODE_NOT_SUPPORTED_OFFLINE"),
        ("production", "PRODUCTION_DISABLED"),
    ):
        result = _run("--mode", mode)
        assert result.returncode == 2
        report = _report(result)
        assert report["status"] == "REJECTED"
        assert report["error_code"] == error_code
        assert report["external_network_requests"] == 0
        assert report["external_trade_writes"] == 0
