"""CLI smoke and fail-closed contracts for the Iteration 50 long-stream tool."""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "run_iteration50_live_factor_benchmark.py"


def _load_benchmark_module():
    spec = importlib.util.spec_from_file_location("iteration50_live_factor_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ("native", "build"))
def test_live_alpha003_smoke_runs_real_composition_and_writes_bounded_noop_evidence(tmp_path, mode):
    output = tmp_path / (mode + ".json")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            mode,
            "--smoke",
            "--warmup-bars",
            "64",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert output.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["evidence_level"] == "COMPOSITION_SYNTHETIC_SOURCE_STREAM_ONLY"
    assert report["formal_acceptance_claimed"] is False
    assert report["account_or_execution_claimed"] is False
    assert report["profile"]["mode"] == mode
    assert report["profile"]["target_count"] == 20
    assert report["profile"]["evaluation_grids"] == 24
    assert report["profile"]["warmup_bars"] == 64
    assert report["source"]["full_event_tape_materialized"] is False
    assert report["source"]["all_output_arrays_materialized"] is False
    assert report["source"]["raw_numeric_fields"] == [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
    ]
    assert report["source"]["factor_extra_line_fields"] == []
    assert (
        report["source"]["line_fields_registered_per_member"]
        == report["source"]["raw_numeric_fields"]
    )
    assert report["source"]["events_returned"] == 20 * (24 + 64)
    assert report["runtime"]["strategy_next_calls"] == 24 + 64
    assert report["oracle"]["finite_factor_values"] == 20 * 24
    assert report["oracle"]["open_rank_changed_grids"] > 0
    assert report["oracle"]["volume_rank_changed_grids"] > 0
    assert report["oracle"]["distinct_finite_factor_values"] >= 2
    assert report["oracle"]["rank_reason_failures"] == 0
    assert report["oracle"]["correlation_reason_failures"] == 0
    alpha003 = report["oracle"]["per_factor"]["alpha003"]
    assert alpha003["comparisons"] > 0
    assert alpha003["finite_factor_values"] == 20 * 24
    assert alpha003["distinct_finite_factor_values"] >= 2
    assert alpha003["output_reason_failures"] == 0
    assert alpha003["output_unavailable_grids"] == 0
    assert report["durable_noop_journal"]["noop_rows"] == 24
    assert report["durable_noop_journal"]["new_grid_rows"] == 24
    assert report["durable_noop_journal"]["cursor_ordinal"] == 24
    assert report["durable_noop_journal"]["intent_count"] == 0
    assert report["latency"]["sample_count"] == 24
    assert math.isfinite(report["latency"]["max_ms"])
    assert math.isfinite(report["latency"]["p99_upper_bound_ms"])
    assert report["latency"]["max_ms"] <= 500
    assert report["latency"]["p99_upper_bound_ms"] <= 100
    phases = report["latency"]["monotonic_phases"]
    assert phases["first_member_available_to_last_member_available"]["sample_count"] == 24
    assert phases["last_member_available_to_factor_snapshot"]["sample_count"] == 24
    assert phases["record_grid_decision_call"]["sample_count"] == 24
    assert report["latency"]["source_clock_bar_close_to_available"]["max_ms"] == 0.0
    assert report["latency"]["rpc"] == {
        "called": False,
        "sample_count": 0,
        "latency_ms": None,
    }
    assert report["environment"]["python_version"]
    assert report["environment"]["os_system"]
    assert type(report["environment"]["logical_cpu_count"]) is int
    assert len(report["provenance"]["script_sha256"]) == 64
    assert len(report["provenance"]["input_generation_sha256"]) == 64
    assert report["provenance"]["actual_argv"]
    assert report["memory"]["first_window_sample_count"] == report["memory"]["equal_window_samples"]
    assert report["memory"]["last_window_sample_count"] == report["memory"]["equal_window_samples"]
    assert report["memory"]["rss_sampling_method"]
    assert report["memory"]["rss_sampling_scope"] == "benchmark_process"
    assert report["memory"]["process_tree_peak_claimed"] is False
    assert report["memory"]["rss_samples_may_miss_transient_peaks"] is True
    assert report["capacities"]["configured_pending_slots"] == 1
    assert report["capacities"]["source_rows_retained_max"] == 20
    assert report["capacities"]["source_rows_retained_at_end"] == 0
    assert report["capacities"]["diagnostics_bounded"] is True
    first_lines = report["capacities"]["line_capacity_first"]
    last_lines = report["capacities"]["line_capacity_last"]
    assert first_lines["factor_instance_root_count"] == 1
    assert first_lines["owner_count"] > first_lines["factor_instance_root_count"]
    assert first_lines["owner_count"] == last_lines["owner_count"]
    assert first_lines["line_count"] == last_lines["line_count"]
    assert first_lines["value_line_count"] > 0
    assert first_lines["reason_line_count"] > 0
    assert first_lines["line_buffers_full"] is True
    assert first_lines["value_line_count"] == last_lines["value_line_count"]
    assert first_lines["reason_line_count"] == last_lines["reason_line_count"]
    assert last_lines["line_buffers_full"] is True
    assert report["capacities"]["line_capacity_grew_after_warmup"] is False
    assert report["capacities"]["retained_receipts_at_first_sample"] == 20 * 64
    assert report["capacities"]["retained_receipts_at_end"] == 20 * 64
    assert report["capacities"]["receipt_window_full_at_first_sample"] is True
    assert report["capacities"]["receipt_window_full_at_last_sample"] is True


def test_invalid_or_all_missing_profiles_cannot_report_pass(tmp_path):
    module = _load_benchmark_module()
    invalid_report = {
        "profile": {"total_grid_slots": 3, "evaluation_grids": 2},
        "runtime": {"strategy_next_calls": 3},
        "oracle": {
            "comparisons": 0,
            "finite_factor_values": 0,
            "distinct_finite_factor_values": 0,
        },
    }
    with pytest.raises(module.BenchmarkFailure, match="oracle_produced_no_comparisons"):
        module._require_positive_witnesses(invalid_report)

    output = tmp_path / "invalid-grid.json"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "native",
            "--grids",
            "0",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 2
    assert not output.exists()
    assert "evaluation_grid_count_out_of_range" in completed.stderr


def test_alpha003_profile_does_not_require_deferred_feed_extra_lines():
    module = _load_benchmark_module()

    assert module._source_fields_for("alpha003") == (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
    )
    assert not set(module._source_fields_for("alpha003")).intersection(module.EXTRA_FACTOR_FIELDS)


def test_six_factor_streaming_oracle_has_finite_nontrivial_fixture_witnesses():
    module = _load_benchmark_module()
    targets = tuple("ASSET%02d" % index for index in range(module.ASSET_COUNT))
    oracle = module._StreamingFactorOracle(targets, module.FACTOR_IDS["representative-six"])
    finite_counts = dict.fromkeys(module.FACTOR_NAMES.values(), 0)
    distinct_values = {name: set() for name in finite_counts}
    total_grids = module.DEFAULT_SIX_FACTOR_WARMUP_BARS + 84

    for grid_index in range(total_grids):
        rows = {
            target: module._event_values(asset_index, grid_index)
            for asset_index, target in enumerate(targets)
        }
        outputs = oracle.update(rows)
        if grid_index < module.DEFAULT_SIX_FACTOR_WARMUP_BARS:
            continue
        for name in finite_counts:
            values = outputs[name]
            assert set(values) == set(targets)
            for value in values.values():
                assert math.isfinite(value)
                distinct_values[name].add(value)
            finite_counts[name] += len(values)

    for name in finite_counts:
        assert finite_counts[name] == 84 * module.ASSET_COUNT
        assert len(distinct_values[name]) >= 2


def test_existing_decision_database_is_rejected_before_benchmark_starts(tmp_path):
    output = tmp_path / "already-used.json"
    database = tmp_path / "already-used.decisions.sqlite3"
    sentinel = b"preserve-existing-journal"
    database.write_bytes(sentinel)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "native",
            "--smoke",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 2
    assert not output.exists()
    assert database.read_bytes() == sentinel
    assert "decision_database_path_already_exists" in completed.stderr


def test_current_rss_sampler_uses_linux_proc_when_psutil_is_unavailable(monkeypatch):
    module = _load_benchmark_module()
    rss_sequence = iter((100, 1_000_000, 105))

    def missing_psutil():
        raise ImportError("psutil unavailable")

    monkeypatch.setattr(module, "_load_psutil_module", missing_psutil)
    monkeypatch.setattr(module, "_read_linux_proc_rss_bytes", lambda: next(rss_sequence))

    sampler = module._create_rss_sampler(platform_name="linux", os_name="posix")

    assert sampler.method == "Linux /proc/self/statm resident pages"
    assert [sampler.sample_bytes() for _ in range(3)] == [100, 1_000_000, 105]


def test_rss_sampler_fails_closed_without_psutil_or_supported_current_rss_api(monkeypatch):
    module = _load_benchmark_module()

    def missing_psutil():
        raise ImportError("psutil unavailable")

    monkeypatch.setattr(module, "_load_psutil_module", missing_psutil)

    with pytest.raises(module.BenchmarkFailure, match="rss_sampler_unavailable"):
        module._create_rss_sampler(platform_name="freebsd13", os_name="posix")


def test_rss_growth_uses_current_sample_window_medians_not_lifetime_peak():
    module = _load_benchmark_module()

    summary = module._rss_window_summary((100, 1_000_000, 100), (110, 110, 110))

    assert summary["first_window_median_rss_bytes"] == 100
    assert summary["last_window_median_rss_bytes"] == 110
    assert summary["rss_growth_bytes"] == 10
    assert summary["growth_pass"] is True


def test_rss_growth_fails_closed_when_current_sample_window_is_incomplete():
    module = _load_benchmark_module()

    summary = module._rss_window_summary((100,), ())

    assert summary["rss_growth_bytes"] is None
    assert summary["growth_pass"] is False


def _valid_gate_report():
    return {
        "profile": {
            "factor_names": ["alpha003"],
            "total_grid_slots": 3,
            "evaluation_grids": 2,
            "warmup_bars": 1,
            "minimum_wall_clock_duration_seconds": 0,
        },
        "runtime": {"strategy_next_calls": 3, "warmup_complete_grids": 1},
        "oracle": {
            "comparisons": 1,
            "finite_factor_values": 2,
            "distinct_finite_factor_values": 2,
            "rank_reason_failures": 0,
            "correlation_reason_failures": 0,
            "per_factor": {
                "alpha003": {
                    "comparisons": 2,
                    "finite_factor_values": 2,
                    "distinct_finite_factor_values": 2,
                    "output_reason_failures": 0,
                    "output_unavailable_grids": 0,
                }
            },
        },
        "durable_noop_journal": {
            "noop_rows": 2,
            "new_grid_rows": 2,
            "cursor_ordinal": 2,
            "capacity_before": {
                "base_record_count": 0,
                "base_record_limit": 2,
                "base_payload_bytes": 0,
                "base_payload_byte_limit": 512 * 1024 * 1024,
                "settlement_record_count": 0,
                "settlement_record_limit": 4096,
                "settlement_payload_byte_limit": 64 * 1024 * 1024,
                "database_bytes": 0,
                "wal_bytes": 0,
                "physical_bytes": 0,
            },
            "capacity_after": {
                "base_record_count": 2,
                "base_record_limit": 2,
                "base_payload_bytes": 32,
                "base_payload_byte_limit": 512 * 1024 * 1024,
                "settlement_record_count": 0,
                "settlement_record_limit": 4096,
                "settlement_payload_byte_limit": 64 * 1024 * 1024,
                "database_bytes": 8192,
                "wal_bytes": 0,
                "physical_bytes": 8192,
            },
        },
        "latency": {"sample_count": 2, "p99_upper_bound_ms": 1.0, "max_ms": 1.0},
        "memory": {
            "rss_sampling_method": "synthetic test reader for current RSS samples",
            "rss_sampling_scope": "benchmark_process",
            "process_tree_peak_claimed": False,
            "rss_samples_may_miss_transient_peaks": True,
            "rss_growth_bytes": 0,
            "rss_growth_limit_bytes": 32,
            "equal_window_samples": 1,
            "first_window_sample_count": 1,
            "last_window_sample_count": 1,
        },
        "capacities": {
            "configured_pending_slots": 1,
            "source_rows_retained_max": 20,
            "source_rows_retained_at_end": 0,
            "cohort_pending_slots_at_end": 0,
            "configured_window_bars_per_member": 64,
            "retained_receipts_at_end": 20,
            "retained_receipts_at_first_sample": 20,
            "receipt_window_full_at_first_sample": True,
            "receipt_window_full_at_last_sample": True,
            "line_capacity_grew_after_warmup": False,
            "line_buffers_full_at_first_sample": True,
            "line_buffers_full_at_last_sample": True,
            "line_capacity_first": {
                "owner_count": 1,
                "factor_instance_root_count": 1,
                "line_count": 1,
                "value_line_count": 1,
                "reason_line_count": 1,
                "line_buffers_full": True,
            },
            "line_capacity_last": {
                "owner_count": 1,
                "factor_instance_root_count": 1,
                "line_count": 1,
                "value_line_count": 1,
                "reason_line_count": 1,
                "line_buffers_full": True,
            },
            "physical_db_wal_capacity_enforced": False,
            "diagnostics_bounded": True,
            "factor_diagnostic_sample_capacity_max": 64,
            "factor_diagnostic_samples_retained_max": 1,
        },
        "elapsed_seconds": 0.0,
    }


@pytest.mark.parametrize(
    "field,value,expected_failure",
    (
        ("p99_upper_bound_ms", math.nan, "durable_decision_p99_latency_exceeded_100ms"),
        ("p99_upper_bound_ms", -0.1, "durable_decision_p99_latency_exceeded_100ms"),
        ("max_ms", math.nan, "durable_decision_max_latency_exceeded_500ms"),
        ("max_ms", -0.1, "durable_decision_max_latency_exceeded_500ms"),
    ),
)
def test_latency_gate_rejects_nonfinite_and_negative_values(field, value, expected_failure):
    module = _load_benchmark_module()
    report = _valid_gate_report()
    assert module._check_gates(report)[0] is True
    report["latency"][field] = value

    passed, failures = module._check_gates(report)

    assert passed is False
    assert expected_failure in failures


@pytest.mark.parametrize(
    "field,expected_failure",
    (
        ("rank_reason_failures", "rank_nodes_reported_reason_failures"),
        ("correlation_reason_failures", "correlation_nodes_reported_reason_failures"),
    ),
)
def test_reason_failures_are_a_hard_gate(field, expected_failure):
    module = _load_benchmark_module()
    report = _valid_gate_report()
    assert module._check_gates(report)[0] is True
    report["oracle"][field] = 1

    passed, failures = module._check_gates(report)

    assert passed is False
    assert expected_failure in failures
