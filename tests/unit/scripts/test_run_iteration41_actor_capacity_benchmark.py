"""Contracts for the BM58 fake-only two-client capacity diagnostic."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "run_iteration41_actor_capacity_benchmark.py"
SPEC = importlib.util.spec_from_file_location("iteration41_actor_capacity_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_default_and_capacity_profiles_are_explicit_fake_diagnostics() -> None:
    smoke = benchmark.resolve_profile("smoke")
    capacity = benchmark.resolve_profile("capacity-30m")

    assert smoke["duration_seconds"] == 2
    assert smoke["rate_per_second"] == 10
    assert capacity["duration_seconds"] == 1800
    assert capacity["rate_per_second"] == 50
    assert capacity["process_count"] == 2
    assert capacity["status"] == "FAKE_LOCAL_DIAGNOSTIC"
    assert capacity["acceptance_status"] == "NOT_ACCEPTED"


def test_custom_profile_requires_explicit_even_rate_and_duration() -> None:
    with pytest.raises(ValueError, match="requires rate and duration"):
        benchmark.resolve_profile("custom")
    with pytest.raises(ValueError, match="positive even integer"):
        benchmark.resolve_profile("custom", rate_per_second=5, duration_seconds=1)
    with pytest.raises(ValueError, match="fake provider latency"):
        benchmark.resolve_profile(
            "custom", rate_per_second=2, duration_seconds=1, provider_latency_ms=float("nan")
        )
    with pytest.raises(ValueError, match="fake provider latency"):
        benchmark.resolve_profile(
            "custom", rate_per_second=2, duration_seconds=1, provider_latency_ms=float("inf")
        )

    custom = benchmark.resolve_profile(
        "custom", rate_per_second=8, duration_seconds=3, duplicate_every=2
    )
    assert custom["rate_per_second"] == 8
    assert custom["duration_seconds"] == 3
    assert custom["duplicate_every"] == 2


def _run_cli(output_dir: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(output_dir), *arguments],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_two_process_smoke_records_idempotent_duplicates_and_raw_results(
    tmp_path: Path,
) -> None:
    output = tmp_path / "bm58-smoke"
    process = _run_cli(
        output,
        "--profile",
        "custom",
        "--rate-per-second",
        "8",
        "--duration-seconds",
        "1",
        "--duplicate-every",
        "2",
        "--provider-latency-ms",
        "1",
        "--max-outstanding",
        "32",
    )

    assert process.returncode == 0, process.stderr + process.stdout
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "FAKE_LOCAL_DIAGNOSTIC"
    assert result["acceptance_status"] == "NOT_ACCEPTED"
    assert result["run_status"] == "PASS"
    assert result["profile"]["process_count"] == 2
    assert result["metrics"]["input_intents_planned"] == 8
    assert result["metrics"]["accepted_unique_intents"] == 8
    assert result["metrics"]["completed_intents"] == 8
    assert result["metrics"]["duplicate_attempts"] == 4
    assert result["metrics"]["lost_intents"] == 0
    assert result["metrics"]["fake_provider_calls"] == 8
    assert result["metrics"]["provider_dispatches"] == 0
    assert result["metrics"]["network_calls"] == 0
    assert len(result["clients"]) == 2
    assert all(result["checks"].values())
    for name in result["raw_outputs"]:
        assert (output / name).is_file()
    assert len((output / "intent-samples.csv").read_text(encoding="utf-8").splitlines()) == 9
    assert len((output / "request-attempts.csv").read_text(encoding="utf-8").splitlines()) == 13


def test_bounded_authority_reports_backpressure_and_drains_without_loss(
    tmp_path: Path,
) -> None:
    output = tmp_path / "bm58-backpressure"
    process = _run_cli(
        output,
        "--profile",
        "custom",
        "--rate-per-second",
        "40",
        "--duration-seconds",
        "1",
        "--duplicate-every",
        "0",
        "--provider-latency-ms",
        "100",
        "--max-outstanding",
        "1",
    )

    assert process.returncode == 0, process.stderr + process.stdout
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    metrics = result["metrics"]
    assert result["run_status"] == "PASS"
    assert metrics["input_intents_planned"] == 40
    assert metrics["completed_intents"] == 40
    assert metrics["lost_intents"] == 0
    assert metrics["peak_backlog"] == 1
    assert metrics["backpressure_events"] > 0
    assert metrics["backpressure_wait_ns"] > 0
    assert metrics["outstanding_at_end"] == 0
    assert len((output / "backpressure-samples.csv").read_text(encoding="utf-8").splitlines()) > 1
