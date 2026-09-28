"""Black-box checks for the self-contained Iteration 24 replay example."""

import ast
import copy
import importlib
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "014_2_ctp_options_midfreq"
RUNNER = EXAMPLE / "run.py"
CONFIG = EXAMPLE / "config.yaml"


def _runner():
    """Load the retained fixture API without invoking its retired script CLI."""

    return importlib.import_module("examples.014_2_ctp_options_midfreq.run")


def test_imported_replay_fixture_runs_actual_cerebro_with_no_external_side_effects() -> None:
    runner = _runner()
    report = runner.run_replay(runner.load_config())
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


def test_runtime_import_graph_has_no_other_example_dependency_and_a_pre_framework_gate() -> None:
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
        assert "importlib" not in source_text
        assert "pkgutil" not in source_text
        if source == RUNNER:
            assert "backtrader_runtime.legacy" in source_text
            assert source_text.index('if __name__ == "__main__":') < source_text.index(
                "import backtrader"
            )
        else:
            assert "sys.path" not in source_text

    runner = _runner()
    report = runner.run_replay(runner.load_config(), scenario="edge")
    assert report["self_contained_runtime"] is True
    assert report["contracts"] == {
        "call": "C_LOCAL_1000",
        "future": "F_LOCAL_1000",
        "put": "P_LOCAL_1000",
    }


def test_tick_callback_cannot_submit_an_ordinary_trade_and_rejects_cutoff_boundary(
    tmp_path: Path,
) -> None:
    runner = _runner()
    raw_config = runner.load_config()
    no_edge_report = runner.run_replay(raw_config, inject_cutoff_tick=True)
    assert no_edge_report["ordinary_decision_count_before_tick"] == 1
    assert no_edge_report["ordinary_decision_count"] == 1
    assert no_edge_report["accepted_cutoff_tick_features"]
    assert no_edge_report["orders_submitted"] == 0
    assert all(decision["origin"] == "next" for decision in no_edge_report["ordinary_decisions"])

    boundary_report = runner.run_replay(raw_config, inject_at_cutoff_tick=True)
    assert boundary_report["accepted_cutoff_tick_features"] == []
    assert boundary_report["rejected_tick_count"] == 1
    assert boundary_report["orders_submitted"] == 0

    external_config = tmp_path / "budget-rejected.yaml"
    external_config.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(runner.ConfigurationError) as failure:
        runner.load_config(external_config)
    assert failure.value.code == "CONFIG_PATH"


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
    runner = _runner()
    raw_config = runner.load_config()
    for mode, error_code in (
        ("shadow", "MODE_NOT_SUPPORTED_OFFLINE"),
        ("simnow", "MODE_NOT_SUPPORTED_OFFLINE"),
        ("production", "PRODUCTION_DISABLED"),
    ):
        invalid = copy.deepcopy(raw_config)
        invalid["mode"] = mode
        with pytest.raises(runner.ConfigurationError) as failure:
            runner.run_replay(invalid)
        assert failure.value.code == error_code
