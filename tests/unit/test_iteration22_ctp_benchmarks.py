"""Focused contract tests for the Iteration 22 local acceptance benchmarks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_iteration22_ctp_benchmarks.py"
SPEC = importlib.util.spec_from_file_location("iteration22_ctp_benchmarks", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
BENCHMARKS = importlib.util.module_from_spec(SPEC)
_original_path = list(sys.path)
_module_names = ("features", "reporting", "signal_model")
_original_modules = {name: sys.modules.get(name) for name in _module_names}
try:
    for _name in _module_names:
        sys.modules.pop(_name, None)
    SPEC.loader.exec_module(BENCHMARKS)
finally:
    sys.path[:] = _original_path
    for _name, _module in _original_modules.items():
        if _module is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _module


def test_default_schedule_requires_every_expected_event() -> None:
    counts: dict[int, dict[str, int]] = {}
    previous_due = -1.0
    event_count = 0
    for minute, phase, phase_index, due in BENCHMARKS._iter_scheduled_events(
        duration=BENCHMARKS.DEFAULT_STRESS_SECONDS,
        base_rate=BENCHMARKS.DEFAULT_BASE_RATE,
        burst_rate=BENCHMARKS.DEFAULT_BURST_RATE,
        burst_seconds=BENCHMARKS.DEFAULT_BURST_SECONDS,
    ):
        assert due > previous_due
        assert phase_index >= 0
        previous_due = due
        bucket = counts.setdefault(minute, {"burst_events": 0, "base_events": 0})
        bucket[phase] += 1
        event_count += 1

    report = BENCHMARKS._minute_schedule_report(
        counts,
        duration=BENCHMARKS.DEFAULT_STRESS_SECONDS,
        base_rate=BENCHMARKS.DEFAULT_BASE_RATE,
        burst_rate=BENCHMARKS.DEFAULT_BURST_RATE,
        burst_seconds=BENCHMARKS.DEFAULT_BURST_SECONDS,
        default_shape_requested=True,
    )

    assert report["status"] == "PASS"
    assert event_count == 504_000
    assert report["observed_total_events"] == 504_000
    assert len(report["minutes"]) == 240
    assert all(
        row["burst_events"] == 1_000
        and row["base_events"] == 1_100
        and row["total_events"] == 2_100
        for row in report["minutes"]
    )

    counts[239]["base_events"] -= 1
    failed = BENCHMARKS._minute_schedule_report(
        counts,
        duration=BENCHMARKS.DEFAULT_STRESS_SECONDS,
        base_rate=BENCHMARKS.DEFAULT_BASE_RATE,
        burst_rate=BENCHMARKS.DEFAULT_BURST_RATE,
        burst_seconds=BENCHMARKS.DEFAULT_BURST_SECONDS,
        default_shape_requested=True,
    )
    assert failed["status"] == "FAIL"
    assert failed["valid"] is False


def test_rss_windows_require_all_seven_windows_and_valid_samples() -> None:
    samples = [
        {
            "elapsed_seconds": float(second),
            "rss_bytes": 64 * BENCHMARKS.MIB,
            "process_count": 1,
            "sampling_error_count": 0,
            "sampling_valid": True,
        }
        for second in range(BENCHMARKS.DEFAULT_STRESS_SECONDS)
    ]

    report = BENCHMARKS._rss_windows(samples, actual_elapsed=BENCHMARKS.DEFAULT_STRESS_SECONDS)
    assert report["status"] == "PASS"
    assert report["coverage_complete"] is True
    assert len(report["windows"]) == 7

    missing = BENCHMARKS._rss_windows(
        samples[:-200], actual_elapsed=BENCHMARKS.DEFAULT_STRESS_SECONDS
    )
    assert missing["status"] == "FAIL"
    assert missing["coverage_complete"] is False

    samples[-1]["sampling_error_count"] = 1
    samples[-1]["sampling_valid"] = False
    invalid = BENCHMARKS._rss_windows(samples, actual_elapsed=BENCHMARKS.DEFAULT_STRESS_SECONDS)
    assert invalid["status"] == "FAIL"
    assert invalid["sampling_error_count"] > 0


def _rss_sample(elapsed: float) -> dict[str, object]:
    return {
        "elapsed_seconds": elapsed,
        "rss_bytes": 64 * BENCHMARKS.MIB,
        "process_count": 1,
        "sampling_error_count": 0,
        "sampling_valid": True,
    }


@pytest.mark.parametrize(
    ("samples", "failed_metric"),
    [
        ([], "empty"),
        ([_rss_sample(0.1), _rss_sample(0.9)], "duplicate_slot_count"),
        ([_rss_sample(1.1), _rss_sample(0.1)], "nonincreasing_timestamp_count"),
        ([_rss_sample(0.0), _rss_sample(2.1)], "maximum_interval_seconds"),
    ],
)
def test_rss_series_rejects_empty_duplicate_nonincreasing_and_gapped_samples(
    samples: list[dict[str, object]], failed_metric: str
) -> None:
    quality, unique = BENCHMARKS._rss_series_quality(samples)

    assert quality["status"] == "FAIL"
    assert quality["valid"] is False
    assert quality["unique_slot_count"] == len(unique)
    if failed_metric == "empty":
        assert quality["unique_slot_count"] == 0
    elif failed_metric == "maximum_interval_seconds":
        assert quality[failed_metric] > quality["maximum_allowed_interval_seconds"]
    else:
        assert quality[failed_metric] > 0


def test_evidence_manifest_hashes_active_and_rotated_segments(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    rotated = evidence / "quotes.jsonl.0001"
    active = evidence / "quotes.jsonl"
    rotated.write_bytes(b'{"seq":1}\n{"seq":2}\n')
    active.write_bytes(b'{"seq":3}\n')

    manifest, line_counts, errors = BENCHMARKS._evidence_segment_manifest(
        evidence,
        ("quotes", "orders"),
        expected_rotation_counts={"quotes": 1, "orders": 0},
        expected_line_counts={"quotes": 3, "orders": 0},
    )

    assert errors == []
    assert line_counts == {"quotes": 3, "orders": 0}
    identities = {Path(item["path"]).name: item for item in manifest["quotes"]}
    assert identities["quotes.jsonl"]["active"] is True
    assert identities["quotes.jsonl.0001"]["active"] is False
    assert identities["quotes.jsonl"]["rotation_index"] is None
    assert identities["quotes.jsonl.0001"]["rotation_index"] == 1
    assert identities["quotes.jsonl"]["line_count"] == 1
    assert identities["quotes.jsonl.0001"]["line_count"] == 2
    assert identities["quotes.jsonl"]["ends_with_newline"] is True
    assert identities["quotes.jsonl.0001"]["ends_with_newline"] is True
    assert identities["quotes.jsonl"]["sha256"] == hashlib.sha256(active.read_bytes()).hexdigest()
    assert (
        identities["quotes.jsonl.0001"]["sha256"]
        == hashlib.sha256(rotated.read_bytes()).hexdigest()
    )

    _manifest, _line_counts, rotation_errors = BENCHMARKS._evidence_segment_manifest(
        evidence,
        ("quotes",),
        expected_rotation_counts={"quotes": 2},
        expected_line_counts={"quotes": 3},
    )
    assert "quotes:rotation_index_mismatch" in rotation_errors

    _manifest, _line_counts, count_errors = BENCHMARKS._evidence_segment_manifest(
        evidence,
        ("quotes",),
        expected_rotation_counts={"quotes": 1},
        expected_line_counts={"quotes": 4},
    )
    assert "quotes:line_count_mismatch" in count_errors

    active.write_bytes(b'{"seq":3}')
    _manifest, _line_counts, newline_errors = BENCHMARKS._evidence_segment_manifest(
        evidence,
        ("quotes",),
        expected_rotation_counts={"quotes": 1},
        expected_line_counts={"quotes": 3},
    )
    assert "quotes.jsonl:missing_final_newline" in newline_errors


def _healthy_acceptance_inputs() -> dict[str, bool]:
    return {
        "complete_profile_requested": False,
        "requested_wall_clock_complete": True,
        "schedule_lag_within_limit": True,
        "requested_schedule_complete": True,
        "event_count_matches_schedule": True,
        "rss_sampling_healthy": True,
        "rss_peak_within_limit": True,
        "resource_sampling_healthy": True,
        "writer_healthy": True,
        "opening_allowed": True,
        "dropped_clear": True,
        "pending_clear": True,
        "evidence_counts_match": True,
        "segment_integrity": True,
        "runtime_clean": True,
        "source_stable": True,
        "full_rss_windows_complete": False,
    }


def test_healthy_short_profile_is_incomplete_without_failed_gates() -> None:
    result = BENCHMARKS._assess_stress_acceptance(**_healthy_acceptance_inputs())

    assert result["status"] == "INCOMPLETE_PROFILE"
    assert result["exit_code"] == 0
    assert result["failed_gates"] == []


@pytest.mark.parametrize(
    "failed_gate",
    [
        "requested_wall_clock_complete",
        "schedule_lag_within_limit",
        "requested_schedule_complete",
        "event_count_matches_schedule",
        "rss_sampling_healthy",
        "rss_peak_within_limit",
        "resource_sampling_healthy",
        "writer_healthy",
        "opening_allowed",
        "dropped_clear",
        "pending_clear",
        "evidence_counts_match",
        "segment_integrity",
        "runtime_clean",
        "source_stable",
    ],
)
def test_short_profile_runtime_gate_failures_are_fail_closed(failed_gate: str) -> None:
    inputs = _healthy_acceptance_inputs()
    inputs[failed_gate] = False

    result = BENCHMARKS._assess_stress_acceptance(**inputs)

    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert result["failed_gates"] == [failed_gate]


def test_complete_profile_requires_all_rss_windows() -> None:
    inputs = _healthy_acceptance_inputs()
    inputs["complete_profile_requested"] = True

    failed = BENCHMARKS._assess_stress_acceptance(**inputs)
    assert failed["status"] == "FAIL"
    assert failed["exit_code"] == 1
    assert failed["failed_gates"] == ["full_rss_windows_complete"]

    inputs["full_rss_windows_complete"] = True
    passed = BENCHMARKS._assess_stress_acceptance(**inputs)
    assert passed["status"] == "PASS"
    assert passed["exit_code"] == 0
    assert passed["failed_gates"] == []


def test_short_stress_profile_waits_for_deadline_and_is_incomplete(tmp_path: Path) -> None:
    output = tmp_path / "stress"
    args = Namespace(
        output_dir=str(output),
        duration_seconds=0.2,
        base_rate=20.0,
        burst_rate=200.0,
        burst_seconds=0.05,
        sample_interval=0.05,
    )

    assert BENCHMARKS.run_stress(args) == 0
    report = json.loads((output / "stress_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "iter22.resource_benchmark.v2"
    assert report["status"] == "INCOMPLETE_PROFILE"
    assert report["complete_profile_requested"] is False
    assert report["elapsed_seconds"] >= 0.2
    assert report["schedule"]["status"] == "PASS"
    assert report["acceptance"]["failed_gates"] == []
    assert report["rss_windows"]["series_quality"]["status"] == "PASS"
    assert report["evidence"]["healthy"] is True
    assert report["evidence"]["counts_match"] is True
    assert report["evidence"]["segment_errors"] == []


def test_short_stress_rss_fault_is_fail_closed_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "stress-rss-fault"

    def failed_rss_sample(elapsed: float) -> dict[str, object]:
        return {
            "elapsed_seconds": elapsed,
            "rss_bytes": 0,
            "process_count": 0,
            "sampling_error_count": 1,
            "sampling_valid": False,
        }

    monkeypatch.setattr(BENCHMARKS, "_rss_observation", failed_rss_sample)
    args = Namespace(
        output_dir=str(output),
        duration_seconds=0.1,
        base_rate=20.0,
        burst_rate=200.0,
        burst_seconds=0.05,
        sample_interval=0.05,
    )

    assert BENCHMARKS.run_stress(args) == 1
    report = json.loads((output / "stress_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "rss_sampling_healthy" in report["acceptance"]["failed_gates"]
    assert report["rss_windows"]["series_quality"]["status"] == "FAIL"


def test_short_latency_profile_preserves_measurement_evidence(tmp_path: Path) -> None:
    output = tmp_path / "latency"
    args = Namespace(output_dir=str(output), samples=25, warmup_samples=0)

    assert BENCHMARKS.run_latency(args) == 0
    report = json.loads((output / "latency_report.json").read_text(encoding="utf-8"))

    assert report["status"] == "INCOMPLETE_PROFILE"
    assert report["sample_count"] == 25
    assert report["warmup_sample_count"] >= 1_241
    assert report["measurement_boundary"].startswith("local normalize_quote")
    assert report["source_stable"] is True
    durations = output / "latencies_ns.txt"
    snapshots = output / "frozen_snapshots.jsonl"
    assert len(durations.read_text(encoding="utf-8").splitlines()) == 25
    assert len(snapshots.read_text(encoding="utf-8").splitlines()) == 25
    assert hashlib.sha256(durations.read_bytes()).hexdigest() == report["raw_durations"]["sha256"]


def test_latency_source_drift_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "latency-source-drift"
    hashes = iter(({"script": "a" * 64}, {"script": "b" * 64}))
    monkeypatch.setattr(BENCHMARKS, "_source_hashes", lambda: next(hashes))
    args = Namespace(output_dir=str(output), samples=1, warmup_samples=0)

    assert BENCHMARKS.run_latency(args) == 1
    report = json.loads((output / "latency_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["source_stable"] is False
    assert report["source_sha256_at_start"] != report["source_sha256_at_end"]
