"""Focused contracts for the isolated BM57 fake-provider harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_iteration41_direct_benchmark.py"
SPEC = importlib.util.spec_from_file_location("iteration41_direct_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_nearest_rank_percentile_uses_one_based_rank() -> None:
    assert benchmark._nearest_rank([5, 1, 4, 2, 3], 50) == 3
    assert benchmark._nearest_rank([5, 1, 4, 2, 3], 99) == 5


def test_performance_gate_accepts_exact_five_percent_boundary() -> None:
    comparison = {
        operation: {
            percentile: {
                "per_round_candidate_over_baseline": [1.05] * 5,
                "median_ratio": 1.05,
            }
            for percentile in ("p50", "p99")
        }
        for operation in ("submit", "cancel")
    }

    result = benchmark._evaluate_performance_gate(comparison)

    assert result["ratio_limit"] == 1.05
    assert result["passed"] is True
    assert all(
        metric["passed"]
        for operation in result["operations"].values()
        for metric in operation.values()
    )


def test_performance_gate_rejects_any_metric_above_five_percent() -> None:
    comparison = {
        operation: {
            percentile: {
                "per_round_candidate_over_baseline": [1.0] * 5,
                "median_ratio": 1.0,
            }
            for percentile in ("p50", "p99")
        }
        for operation in ("submit", "cancel")
    }
    comparison["cancel"]["p99"]["median_ratio"] = 1.050001

    result = benchmark._evaluate_performance_gate(comparison)

    assert result["passed"] is False
    assert result["operations"]["cancel"]["p99"]["passed"] is False


def test_candidate_worker_calls_real_public_store_methods_fake_only(tmp_path: Path) -> None:
    result_path = tmp_path / "candidate-worker.json"
    result, process = benchmark._launch_worker(
        source_root=benchmark._PROJECT_ROOT,
        runtime_root=benchmark._PROJECT_ROOT,
        side="candidate",
        revision="test-working-tree",
        round_index=1,
        warmup=2,
        samples=3,
        result_file=result_path,
        cwd=tmp_path,
    )

    assert process["exit_code"] == 0, process
    assert result["result_checks_passed"] is True
    assert result["acceptance_status"] == "NOT_ACCEPTED_FULL_MATRIX"
    assert result["effective_mode"] == "simulation"
    assert result["effective_preset"] == "replay"
    assert result["effective_order_route"] is None
    assert result["effective_allows_network"] is False
    assert result["effective_allows_external_writes"] is False
    assert result["test_profile_execution_authorized"] is False
    assert result["test_profile_external_writes_started"] is False
    assert result["samples_per_operation"] == 3
    assert result["submit_distribution"]["count"] == 3
    assert result["cancel_distribution"]["count"] == 3
    assert result["fake_provider_calls"] == {"submit": 5, "cancel": 5}
    assert result["config_load_calls_before_hot_loop"] == 2
    assert result["config_load_calls_after_hot_loop"] == 2
    assert result["socket_api_attempts"] == []
    assert result["thread_api_attempts"] == []
    assert result["new_python_thread_ids"] == []
    assert result["new_python_thread_ids_hot_loop"] == []
    assert result["new_plugin_modules"] == []
    assert result["source_tree_stable"] is True
    if result["thread_count_before_hot_loop"] is not None:
        assert result["thread_count_after_hot_loop"] == result["thread_count_before_hot_loop"]
