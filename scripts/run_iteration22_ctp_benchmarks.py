#!/usr/bin/env python
"""Run the frozen Iteration 22 latency and resource benchmarks.

The latency benchmark measures only local quote normalization, feature
calculation, and signal fusion.  It does not measure a CTP network round trip,
exchange queueing, or order execution latency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    import psutil
except ImportError as exc:  # pragma: no cover - explicit operator prerequisite
    raise SystemExit("psutil is required for the process-tree RSS benchmark") from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "013_3_sa_midfreq_simnow"
sys.path.insert(0, str(EXAMPLE_DIR))

from features import QuoteFeatureWindow, normalize_quote  # noqa: E402
from reporting import EvidenceWriteError, EvidenceWriter, atomic_write_json  # noqa: E402
from signal_model import CostInputs, MinuteFeatures, fuse  # noqa: E402

DEFAULT_LATENCY_SAMPLES = 100_000
DEFAULT_STRESS_SECONDS = 4 * 60 * 60
DEFAULT_BASE_RATE = 20.0
DEFAULT_BURST_RATE = 200.0
DEFAULT_BURST_SECONDS = 5.0
RSS_POLL_SECONDS = 1.0
RSS_WARMUP_SECONDS = 30 * 60
RSS_WINDOW_SECONDS = 30 * 60
RSS_WINDOW_COUNT = 7
RSS_MIN_WINDOW_COVERAGE = 0.90
RSS_MAX_SAMPLE_INTERVAL_SECONDS = 2.0
MAX_SCHEDULE_LAG_SECONDS = 2.0
MIB = 1024 * 1024

DEFAULT_STRESS_MINUTES = DEFAULT_STRESS_SECONDS // 60
DEFAULT_BURST_EVENTS_PER_MINUTE = int(DEFAULT_BURST_RATE * DEFAULT_BURST_SECONDS)
DEFAULT_BASE_EVENTS_PER_MINUTE = int(DEFAULT_BASE_RATE * (60.0 - DEFAULT_BURST_SECONDS))
DEFAULT_EVENTS_PER_MINUTE = DEFAULT_BURST_EVENTS_PER_MINUTE + DEFAULT_BASE_EVENTS_PER_MINUTE
DEFAULT_STRESS_EVENTS = DEFAULT_STRESS_MINUTES * DEFAULT_EVENTS_PER_MINUTE


def _source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__).resolve(),
        EXAMPLE_DIR / "features.py",
        EXAMPLE_DIR / "signal_model.py",
    )
    reporting_path = EXAMPLE_DIR / "reporting.py"
    return {
        str(path.relative_to(REPO_ROOT)): _sha256_file(path) for path in (*paths, reporting_path)
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quantile(values: Iterable[int | float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return math.nan
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _cpu_model() -> str:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or platform.machine()


def _hardware() -> dict[str, Any]:
    load_average = None
    try:
        load_average = list(os.getloadavg())
    except OSError:
        pass
    return {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "cpu_model": _cpu_model(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "memory_bytes": psutil.virtual_memory().total,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "load_average_at_start": load_average,
    }


def _raw_quote(index: int, event_time: float, recv_monotonic: float) -> dict[str, Any]:
    # Integer tick changes make the generator stable across platforms while
    # still exercising rolling volatility, momentum, imbalance, and OFI.
    phase = (index // 20) % 40
    offset = phase if phase <= 20 else 40 - phase
    bid = 2_390.0 + float(offset)
    ask = bid + 1.0
    return {
        "schema_version": "ctp.quote.v2",
        "volume_semantics": "delta",
        "volume_complete": True,
        "volume_quality": "CONTINUOUS",
        "event_time_utc": event_time,
        "event_time_source": "benchmark_epoch",
        "recv_time_utc": event_time,
        "recv_monotonic": recv_monotonic,
        "recv_monotonic_ns": int(round(recv_monotonic * 1_000_000_000)),
        "ingest_seq": index + 1,
        "bid": bid,
        "ask": ask,
        "bid_size": float(10 + index % 7),
        "ask_size": float(11 + (index * 3) % 7),
        "last": bid if index % 2 == 0 else ask,
        "cum_volume": float(index + 1),
        "delta_volume": 1.0,
        "volume": 1.0,
        "open_interest": 100_000.0 + float(index % 100),
        "lower_limit": 2_000.0,
        "upper_limit": 3_000.0,
        "trading_day": "20260909",
        "action_day": "20260909",
        "connection_generation": 1,
        "source": "ctp.simnow.iter22_benchmark",
        "continuity_status": "continuous",
        "quality_flags": (),
        "stale": False,
    }


def _minute_features(event_time: float) -> MinuteFeatures:
    return MinuteFeatures(
        ready=True,
        reasons=(),
        bar_id="SA601:20260909:0001:v1",
        bar_end=event_time,
        available_at=event_time,
        trading_day="20260909",
        ema5=2_402.0,
        ema20=2_398.0,
        atr14=8.0,
        trend=0.5,
        return1=0.1,
        return3=0.4,
        return5=0.5,
        volume_ratio=1.2,
    )


def _costs() -> CostInputs:
    return CostInputs(
        tick_size=1.0,
        multiplier=20.0,
        lots=1,
        entry_price=2_400.0,
        exit_price=2_400.0,
        open_money_rate=0.0,
        open_volume_rate=1.5,
        close_money_rate=0.0,
        close_volume_rate=1.5,
        verified=True,
        source="frozen_benchmark_fixture",
    )


def _process_quote(
    raw: dict[str, Any],
    window: QuoteFeatureWindow,
    minute: MinuteFeatures,
    costs: CostInputs,
) -> tuple[Any, Any]:
    validation = normalize_quote(
        raw,
        tick_size=1.0,
        now_wall_utc=float(raw["event_time_utc"]),
        now_monotonic=float(raw["recv_monotonic"]),
    )
    if not validation.valid or validation.quote is None:
        raise RuntimeError(f"benchmark generated an invalid quote: {validation.reason}")
    if not window.add(validation.quote):
        raise RuntimeError(f"benchmark quote ordering failed: {window.last_invalid_reason}")
    fast = window.calculate()
    return fast, fuse(fast, minute, costs)


def _default_output_dir(kind: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return EXAMPLE_DIR / "output" / "benchmarks" / f"{kind}-{stamp}"


def _prepare_output_dir(path: Path) -> None:
    """Create a clean evidence directory without overwriting an older run."""

    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(f"benchmark output directory already exists: {path}") from exc


def run_latency(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir("latency")
    _prepare_output_dir(output_dir)
    source_sha256_at_start = _source_hashes()
    duration_path = output_dir / "latencies_ns.txt"
    snapshot_path = output_dir / "frozen_snapshots.jsonl"
    report_path = output_dir / "latency_report.json"
    hardware = _hardware()
    window = QuoteFeatureWindow(1.0)
    costs = _costs()
    base_wall = 1_788_883_200.0
    base_monotonic = 10_000.0
    interval = 0.05
    warmup_samples = max(int(args.warmup_samples), 1_241)
    minute = _minute_features(base_wall)

    snapshots = [
        _raw_quote(
            warmup_samples + offset,
            base_wall + (warmup_samples + offset) * interval,
            base_monotonic + (warmup_samples + offset) * interval,
        )
        for offset in range(int(args.samples))
    ]
    with snapshot_path.open("w", encoding="utf-8") as handle:
        for snapshot in snapshots:
            handle.write(
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())

    for index in range(warmup_samples):
        raw = _raw_quote(
            index,
            base_wall + index * interval,
            base_monotonic + index * interval,
        )
        _process_quote(raw, window, minute, costs)

    durations: list[int] = []
    decision_checksum = 0
    measured_started = time.perf_counter_ns()
    for raw in snapshots:
        started = time.perf_counter_ns()
        fast, decision = _process_quote(raw, window, minute, costs)
        durations.append(time.perf_counter_ns() - started)
        decision_checksum ^= int(round((decision.score or 0.0) * 1_000_000))
        decision_checksum ^= int(round((fast.mid or 0.0) * 1_000))
    measured_elapsed = time.perf_counter_ns() - measured_started

    with duration_path.open("w", encoding="utf-8") as handle:
        handle.writelines(f"{value}\n" for value in durations)
        handle.flush()
        os.fsync(handle.fileno())

    percentiles_ms = {
        "p50": _quantile(durations, 0.50) / 1_000_000.0,
        "p95": _quantile(durations, 0.95) / 1_000_000.0,
        "p99": _quantile(durations, 0.99) / 1_000_000.0,
        "max": max(durations, default=0) / 1_000_000.0,
    }
    complete_profile = int(args.samples) == DEFAULT_LATENCY_SAMPLES
    source_sha256_at_end = _source_hashes()
    source_stable = source_sha256_at_end == source_sha256_at_start
    if not source_stable:
        status = "FAIL"
    elif complete_profile:
        status = "PASS" if percentiles_ms["p99"] <= 20.0 else "FAIL"
    else:
        status = "INCOMPLETE_PROFILE"
    report = {
        "schema_version": "iter22.latency_benchmark.v1",
        "status": status,
        "threshold": {"metric": "p99_ms", "maximum": 20.0},
        "sample_count": len(durations),
        "required_sample_count": DEFAULT_LATENCY_SAMPLES,
        "warmup_sample_count": warmup_samples,
        "percentiles_ms": percentiles_ms,
        "wall_elapsed_seconds": measured_elapsed / 1_000_000_000.0,
        "throughput_per_second": (
            len(durations) / (measured_elapsed / 1_000_000_000.0) if measured_elapsed else None
        ),
        "measurement_boundary": (
            "local normalize_quote -> bounded QuoteFeatureWindow -> frozen signal fusion"
        ),
        "excluded_boundaries": [
            "CTP network transit",
            "broker/exchange queueing",
            "order acknowledgement and fill latency",
            "evidence recording",
        ],
        "recording_enabled": False,
        "input": {
            "generator": "iter22_integer_tick_quote_fixture_v1",
            "schema_version": "ctp.quote.v2",
            "interval_seconds": interval,
            "trading_day": "20260909",
            "frozen_snapshot_path": str(snapshot_path.resolve()),
            "frozen_snapshot_sha256": _sha256_file(snapshot_path),
            "frozen_before_measurement": True,
        },
        "raw_durations": {
            "path": str(duration_path.resolve()),
            "sha256": _sha256_file(duration_path),
            "unit": "nanoseconds",
        },
        "decision_checksum": decision_checksum,
        "hardware": hardware,
        "source_sha256": source_sha256_at_start,
        "source_sha256_at_start": source_sha256_at_start,
        "source_sha256_at_end": source_sha256_at_end,
        "source_stable": source_stable,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(report_path, report)
    print(json.dumps({"report": str(report_path), "status": status}, ensure_ascii=False))
    return 0 if status in {"PASS", "INCOMPLETE_PROFILE"} else 1


def _process_tree_rss_bytes() -> tuple[int, int, int]:
    try:
        process = psutil.Process()
    except psutil.Error:
        return 0, 0, 1
    processes = [process]
    error_count = 0
    try:
        processes.extend(process.children(recursive=True))
    except psutil.Error:
        error_count += 1
    total = 0
    observed = 0
    for item in processes:
        try:
            total += int(item.memory_info().rss)
            observed += 1
        except psutil.Error:
            error_count += 1
            continue
    return total, observed, error_count


def _rss_observation(elapsed: float) -> dict[str, Any]:
    rss, process_count, sampling_error_count = _process_tree_rss_bytes()
    return {
        "elapsed_seconds": elapsed,
        "rss_bytes": rss,
        "process_count": process_count,
        "sampling_error_count": sampling_error_count,
        "sampling_valid": bool(process_count > 0 and rss > 0 and sampling_error_count == 0),
    }


def _rss_series_quality(
    samples: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    unique_samples: list[dict[str, Any]] = []
    seen_slots: set[int] = set()
    duplicate_slot_count = 0
    nonincreasing_timestamp_count = 0
    invalid_timestamp_count = 0
    previous_elapsed: float | None = None
    previous_unique_elapsed: float | None = None
    maximum_interval = 0.0

    for item in samples:
        try:
            elapsed = float(item["elapsed_seconds"])
        except (KeyError, TypeError, ValueError):
            invalid_timestamp_count += 1
            continue
        if not math.isfinite(elapsed) or elapsed < 0:
            invalid_timestamp_count += 1
            continue
        if previous_elapsed is not None:
            if elapsed <= previous_elapsed:
                nonincreasing_timestamp_count += 1
        previous_elapsed = elapsed
        slot = int(elapsed // RSS_POLL_SECONDS)
        if slot in seen_slots:
            duplicate_slot_count += 1
            continue
        seen_slots.add(slot)
        if previous_unique_elapsed is not None and elapsed > previous_unique_elapsed:
            maximum_interval = max(maximum_interval, elapsed - previous_unique_elapsed)
        previous_unique_elapsed = elapsed
        unique_samples.append(item)

    sampling_error_count = sum(int(item.get("sampling_error_count", 0)) for item in samples)
    invalid_sample_count = sum(
        0 if bool(item.get("sampling_valid", False)) else 1 for item in samples
    )
    valid = (
        bool(unique_samples)
        and not any(
            (
                sampling_error_count,
                invalid_sample_count,
                invalid_timestamp_count,
                duplicate_slot_count,
                nonincreasing_timestamp_count,
            )
        )
        and maximum_interval <= RSS_MAX_SAMPLE_INTERVAL_SECONDS
    )
    return (
        {
            "status": "PASS" if valid else "FAIL",
            "valid": valid,
            "raw_sample_count": len(samples),
            "unique_slot_count": len(unique_samples),
            "sampling_error_count": sampling_error_count,
            "invalid_sample_count": invalid_sample_count,
            "invalid_timestamp_count": invalid_timestamp_count,
            "duplicate_slot_count": duplicate_slot_count,
            "nonincreasing_timestamp_count": nonincreasing_timestamp_count,
            "maximum_interval_seconds": maximum_interval,
            "maximum_allowed_interval_seconds": RSS_MAX_SAMPLE_INTERVAL_SECONDS,
            "first_elapsed_seconds": (
                float(unique_samples[0]["elapsed_seconds"]) if unique_samples else None
            ),
            "last_elapsed_seconds": (
                float(unique_samples[-1]["elapsed_seconds"]) if unique_samples else None
            ),
        },
        unique_samples,
    )


def _rss_windows(samples: list[dict[str, Any]], *, actual_elapsed: float) -> dict[str, Any]:
    series_quality, unique_samples = _rss_series_quality(samples)
    windows: list[dict[str, Any]] = []
    expected_samples = int(RSS_WINDOW_SECONDS / RSS_POLL_SECONDS)
    minimum_samples = math.ceil(expected_samples * RSS_MIN_WINDOW_COVERAGE)
    for window_index in range(RSS_WINDOW_COUNT):
        start = RSS_WARMUP_SECONDS + window_index * RSS_WINDOW_SECONDS
        end = start + RSS_WINDOW_SECONDS
        window_samples = [
            item for item in unique_samples if start <= float(item["elapsed_seconds"]) < end
        ]
        values = [
            int(item["rss_bytes"])
            for item in window_samples
            if bool(item.get("sampling_valid", False))
        ]
        invalid_count = len(window_samples) - len(values)
        coverage_ratio = len(values) / expected_samples
        coverage_pass = len(values) >= minimum_samples and invalid_count == 0
        windows.append(
            {
                "index": window_index,
                "start_seconds": start,
                "end_seconds": end,
                "sample_count": len(values),
                "invalid_sample_count": invalid_count,
                "expected_sample_count": expected_samples,
                "minimum_sample_count": minimum_samples,
                "coverage_ratio": coverage_ratio,
                "coverage_status": "PASS" if coverage_pass else "FAIL",
                "p95_rss_bytes": int(_quantile(values, 0.95)) if values else None,
            }
        )

    duration_complete = actual_elapsed >= DEFAULT_STRESS_SECONDS
    coverage_complete = all(item["coverage_status"] == "PASS" for item in windows)
    common = {
        "windows": windows,
        "duration_complete": duration_complete,
        "coverage_complete": coverage_complete,
        "series_quality": series_quality,
        "sampling_error_count": series_quality["sampling_error_count"],
        "invalid_sample_count": series_quality["invalid_sample_count"],
        "required_window_count": RSS_WINDOW_COUNT,
        "minimum_coverage_ratio": RSS_MIN_WINDOW_COVERAGE,
    }
    if not series_quality["valid"]:
        return {
            "status": "FAIL",
            **common,
            "first_stable_p95_bytes": None,
            "last_p95_bytes": None,
            "growth_bytes": None,
            "allowed_growth_bytes": None,
        }
    if not duration_complete:
        return {
            "status": "INCOMPLETE_DURATION",
            **common,
            "first_stable_p95_bytes": None,
            "last_p95_bytes": None,
            "growth_bytes": None,
            "allowed_growth_bytes": None,
        }
    if not coverage_complete:
        return {
            "status": "FAIL",
            **common,
            "first_stable_p95_bytes": None,
            "last_p95_bytes": None,
            "growth_bytes": None,
            "allowed_growth_bytes": None,
        }

    first = int(windows[0]["p95_rss_bytes"])
    last = int(windows[-1]["p95_rss_bytes"])
    allowed = max(32 * MIB, int(first * 0.10))
    return {
        "status": "PASS" if last - first <= allowed else "FAIL",
        **common,
        "first_stable_p95_bytes": first,
        "last_p95_bytes": last,
        "growth_bytes": last - first,
        "allowed_growth_bytes": allowed,
    }


def _iter_scheduled_events(
    *, duration: float, base_rate: float, burst_rate: float, burst_seconds: float
) -> Iterator[tuple[int, str, int, float]]:
    """Yield absolute due times derived from integer minute/phase/event indexes."""

    for minute_index in range(math.ceil(duration / 60.0)):
        minute_start = minute_index * 60.0
        minute_end = min(minute_start + 60.0, duration)
        burst_end = min(minute_start + burst_seconds, minute_end)
        phases = (
            ("burst_events", minute_start, burst_end, burst_rate),
            ("base_events", burst_end, minute_end, base_rate),
        )
        for phase, phase_start, phase_end, rate in phases:
            phase_index = 0
            while True:
                due_elapsed = phase_start + phase_index / rate
                if due_elapsed >= phase_end:
                    break
                yield minute_index, phase, phase_index, due_elapsed
                phase_index += 1


def _expected_schedule_counts(
    *, duration: float, base_rate: float, burst_rate: float, burst_seconds: float
) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = {}
    for minute_index, phase, _phase_index, _due_elapsed in _iter_scheduled_events(
        duration=duration,
        base_rate=base_rate,
        burst_rate=burst_rate,
        burst_seconds=burst_seconds,
    ):
        bucket = counts.setdefault(minute_index, {"burst_events": 0, "base_events": 0})
        bucket[phase] += 1
    return counts


def _minute_schedule_report(
    counts: dict[int, dict[str, int]],
    *,
    duration: float,
    base_rate: float,
    burst_rate: float,
    burst_seconds: float,
    default_shape_requested: bool,
) -> dict[str, Any]:
    expected = _expected_schedule_counts(
        duration=duration,
        base_rate=base_rate,
        burst_rate=burst_rate,
        burst_seconds=burst_seconds,
    )
    minute_count = max(max((*counts, *expected), default=-1) + 1, 1)
    rows = []
    for minute_index in range(minute_count):
        observed = counts.get(minute_index, {})
        required = expected.get(minute_index, {})
        burst_events = int(observed.get("burst_events", 0))
        base_events = int(observed.get("base_events", 0))
        expected_burst = int(required.get("burst_events", 0))
        expected_base = int(required.get("base_events", 0))
        minute_pass = burst_events == expected_burst and base_events == expected_base
        rows.append(
            {
                "minute_index": minute_index,
                "burst_events": burst_events,
                "base_events": base_events,
                "total_events": burst_events + base_events,
                "expected_burst_events": expected_burst,
                "expected_base_events": expected_base,
                "expected_total_events": expected_burst + expected_base,
                "status": "PASS" if minute_pass else "FAIL",
            }
        )
    observed_total = sum(
        int(item.get("burst_events", 0)) + int(item.get("base_events", 0))
        for item in counts.values()
    )
    expected_total = sum(
        int(item.get("burst_events", 0)) + int(item.get("base_events", 0))
        for item in expected.values()
    )
    requested_schedule_valid = bool(
        counts == expected
        and observed_total == expected_total
        and all(row["status"] == "PASS" for row in rows)
    )
    default_constants_valid = bool(
        not default_shape_requested
        or (
            expected_total == DEFAULT_STRESS_EVENTS
            and len(expected) == DEFAULT_STRESS_MINUTES
            and all(
                row["expected_burst_events"] == DEFAULT_BURST_EVENTS_PER_MINUTE
                and row["expected_base_events"] == DEFAULT_BASE_EVENTS_PER_MINUTE
                for row in rows
            )
        )
    )
    valid = requested_schedule_valid and default_constants_valid
    return {
        "status": "PASS" if valid else "FAIL",
        "valid": valid,
        "default_constants_valid": default_constants_valid,
        "observed_total_events": observed_total,
        "expected_total_events": expected_total,
        "required_default_total_events": DEFAULT_STRESS_EVENTS,
        "observed_minute_count": len(counts),
        "expected_minute_count": len(expected),
        "required_default_minute_count": DEFAULT_STRESS_MINUTES,
        "required_default_burst_events_per_minute": DEFAULT_BURST_EVENTS_PER_MINUTE,
        "required_default_base_events_per_minute": DEFAULT_BASE_EVENTS_PER_MINUTE,
        "required_default_total_events_per_minute": DEFAULT_EVENTS_PER_MINUTE,
        "minutes": rows,
    }


def _file_segment_identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size_bytes = 0
    line_count = 0
    last_byte = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size_bytes += len(chunk)
            line_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
        "line_count": line_count,
        "ends_with_newline": not size_bytes or last_byte == b"\n",
    }


def _evidence_segment_manifest(
    directory: Path,
    streams: Iterable[str],
    *,
    expected_rotation_counts: dict[str, int] | None = None,
    expected_line_counts: dict[str, int] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[str]]:
    manifest: dict[str, list[dict[str, Any]]] = {}
    line_counts: dict[str, int] = {}
    errors: list[str] = []
    for stream in streams:
        segments: list[dict[str, Any]] = []
        for path in sorted(directory.glob(f"{stream}.jsonl*")):
            try:
                identity = _file_segment_identity(path)
            except OSError as exc:
                errors.append(f"{path.name}:{type(exc).__name__}")
                continue
            base_name = f"{stream}.jsonl"
            suffix = path.name.removeprefix(base_name)
            identity["active"] = suffix == ""
            if suffix == "":
                identity["rotation_index"] = None
            elif suffix.startswith(".") and len(suffix) == 5 and suffix[1:].isdigit():
                identity["rotation_index"] = int(suffix[1:])
            else:
                identity["rotation_index"] = None
                errors.append(f"{path.name}:invalid_segment_name")
            if not identity["ends_with_newline"]:
                errors.append(f"{path.name}:missing_final_newline")
            segments.append(identity)
        active_count = sum(bool(item["active"]) for item in segments)
        if active_count > 1:
            errors.append(f"{stream}:multiple_active_segments")
        if expected_line_counts is not None:
            expected_lines = int(expected_line_counts.get(stream, 0))
            if (expected_lines > 0 and active_count != 1) or (expected_lines == 0 and segments):
                errors.append(f"{stream}:active_segment_mismatch")
        if expected_rotation_counts is not None:
            expected_indexes = list(range(1, int(expected_rotation_counts.get(stream, 0)) + 1))
            observed_indexes = sorted(
                int(item["rotation_index"])
                for item in segments
                if item["rotation_index"] is not None
            )
            if observed_indexes != expected_indexes:
                errors.append(f"{stream}:rotation_index_mismatch")
        segments.sort(
            key=lambda item: (
                item["rotation_index"] is None,
                int(item["rotation_index"] or 0),
            )
        )
        manifest[stream] = segments
        line_counts[stream] = sum(int(item["line_count"]) for item in segments)
        if expected_line_counts is not None and line_counts[stream] != int(
            expected_line_counts.get(stream, 0)
        ):
            errors.append(f"{stream}:line_count_mismatch")
    return manifest, line_counts, errors


def _resource_sample(
    *,
    elapsed: float,
    writer: EvidenceWriter,
    event_count: int,
    maximum_schedule_lag: float,
) -> dict[str, Any]:
    rss, process_count, sampling_error_count = _process_tree_rss_bytes()
    return {
        "elapsed_seconds": elapsed,
        "rss_bytes": rss,
        "process_count": process_count,
        "sampling_error_count": sampling_error_count,
        "sampling_valid": bool(process_count > 0 and rss > 0 and sampling_error_count == 0),
        "event_count": event_count,
        "pending_counts": writer.pending_counts,
        "persisted_counts": dict(writer.counts),
        "dropped_counts": dict(writer.dropped_counts),
        "rotation_counts": dict(writer.rotation_counts),
        "max_pending_counts": dict(writer.max_pending_counts),
        "max_pending_total": writer.max_pending_total,
        "opening_allowed": writer.opening_allowed,
        "failure_reason": writer.failure_reason or None,
        "disk_free_bytes": shutil_disk_free(writer.directory),
        "maximum_schedule_lag_seconds": maximum_schedule_lag,
    }


def shutil_disk_free(path: Path) -> int | None:
    try:
        return int(psutil.disk_usage(str(path)).free)
    except (OSError, psutil.Error):
        return None


def _assess_stress_acceptance(
    *,
    complete_profile_requested: bool,
    requested_wall_clock_complete: bool,
    schedule_lag_within_limit: bool,
    requested_schedule_complete: bool,
    event_count_matches_schedule: bool,
    rss_sampling_healthy: bool,
    rss_peak_within_limit: bool,
    resource_sampling_healthy: bool,
    writer_healthy: bool,
    opening_allowed: bool,
    dropped_clear: bool,
    pending_clear: bool,
    evidence_counts_match: bool,
    segment_integrity: bool,
    runtime_clean: bool,
    source_stable: bool,
    full_rss_windows_complete: bool,
) -> dict[str, Any]:
    runtime_gates = {
        "requested_wall_clock_complete": requested_wall_clock_complete,
        "schedule_lag_within_limit": schedule_lag_within_limit,
        "requested_schedule_complete": requested_schedule_complete,
        "event_count_matches_schedule": event_count_matches_schedule,
        "rss_sampling_healthy": rss_sampling_healthy,
        "rss_peak_within_limit": rss_peak_within_limit,
        "resource_sampling_healthy": resource_sampling_healthy,
        "writer_healthy": writer_healthy,
        "opening_allowed": opening_allowed,
        "dropped_clear": dropped_clear,
        "pending_clear": pending_clear,
        "evidence_counts_match": evidence_counts_match,
        "segment_integrity": segment_integrity,
        "runtime_clean": runtime_clean,
        "source_stable": source_stable,
    }
    profile_gates = {"full_rss_windows_complete": full_rss_windows_complete}
    failed_runtime = [name for name, passed in runtime_gates.items() if not passed]
    failed_profile = (
        [name for name, passed in profile_gates.items() if not passed]
        if complete_profile_requested
        else []
    )
    failed_gates = failed_runtime + failed_profile
    if failed_gates:
        status = "FAIL"
        exit_code = 1
    elif complete_profile_requested:
        status = "PASS"
        exit_code = 0
    else:
        status = "INCOMPLETE_PROFILE"
        exit_code = 0
    return {
        "status": status,
        "exit_code": exit_code,
        "failed_gates": failed_gates,
        "runtime_gates": runtime_gates,
        "profile_gates": profile_gates,
    }


def run_stress(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir("stress")
    evidence_dir = output_dir / "evidence"
    _prepare_output_dir(output_dir)
    source_sha256_at_start = _source_hashes()
    report_path = output_dir / "stress_report.json"
    samples_path = output_dir / "resource_samples.jsonl"
    rss_samples_path = output_dir / "rss_samples.jsonl"
    duration = float(args.duration_seconds)
    base_rate = float(args.base_rate)
    burst_rate = float(args.burst_rate)
    burst_seconds = float(args.burst_seconds)
    sample_interval = float(args.sample_interval)
    timing_values = (duration, base_rate, burst_rate, burst_seconds, sample_interval)
    if not all(math.isfinite(value) for value in timing_values) or min(timing_values) <= 0:
        raise SystemExit("stress timing and rate arguments must be finite and positive")
    if burst_seconds >= 60.0:
        raise SystemExit("burst-seconds must be less than 60")

    hardware = _hardware()
    writer = EvidenceWriter(
        evidence_dir,
        audit_queue_limit=10_000,
        rotate_bytes=100_000_000,
        max_rotated_files_per_stream=128,
    )
    window = QuoteFeatureWindow(1.0)
    minute = _minute_features(1_788_883_200.0)
    costs = _costs()
    samples: list[dict[str, Any]] = []
    rss_samples: list[dict[str, Any]] = []
    minute_counts: dict[int, dict[str, int]] = {}
    event_count = 0
    maximum_schedule_lag = 0.0
    last_event_due_elapsed: float | None = None
    last_event_started_elapsed: float | None = None
    failure: str | None = None
    started = time.monotonic()
    deadline = started + duration
    scheduled_events = iter(
        _iter_scheduled_events(
            duration=duration,
            base_rate=base_rate,
            burst_rate=burst_rate,
            burst_seconds=burst_seconds,
        )
    )
    next_scheduled = next(scheduled_events, None)
    next_sample = started
    next_rss_sample = started
    last_bar_minute = -1

    try:
        while True:
            now = time.monotonic()
            if now >= next_sample:
                samples.append(
                    _resource_sample(
                        elapsed=now - started,
                        writer=writer,
                        event_count=event_count,
                        maximum_schedule_lag=maximum_schedule_lag,
                    )
                )
                # Do not backfill samples after a stall.  The real timestamps
                # make any coverage gap visible to the acceptance gate.
                next_sample = now + sample_interval

            if now >= next_rss_sample:
                rss_samples.append(_rss_observation(now - started))
                next_rss_sample = now + RSS_POLL_SECONDS

            now = time.monotonic()
            if now >= deadline:
                break
            if next_scheduled is None:
                time.sleep(min(deadline - now, 0.05))
                continue
            minute_index, phase, _phase_index, due_elapsed = next_scheduled
            next_due = started + due_elapsed
            if now < next_due:
                time.sleep(min(next_due - now, deadline - now, 0.05))
                continue
            event_started = time.monotonic()
            if event_started >= deadline:
                break
            last_event_due_elapsed = due_elapsed
            last_event_started_elapsed = event_started - started
            maximum_schedule_lag = max(maximum_schedule_lag, event_started - next_due)
            bucket = minute_counts.setdefault(minute_index, {"burst_events": 0, "base_events": 0})
            bucket[phase] += 1
            raw = _raw_quote(
                event_count,
                1_788_883_200.0 + due_elapsed,
                10_000.0 + due_elapsed,
            )
            fast, decision = _process_quote(raw, window, minute, costs)
            writer.append("quotes", raw)
            writer.append(
                "signals",
                {
                    "ingest_seq": raw["ingest_seq"],
                    "event_time_utc": raw["event_time_utc"],
                    "fast_ready": fast.ready,
                    "decision": decision.as_dict(),
                },
            )
            if minute_index != last_bar_minute:
                last_bar_minute = minute_index
                writer.append(
                    "bars",
                    {
                        "bar_id": f"SA601:20260909:{minute_index:04d}:v1",
                        "minute_index": minute_index,
                        "available_at": raw["event_time_utc"],
                    },
                )
            event_count += 1
            next_scheduled = next(scheduled_events, None)
    except (EvidenceWriteError, OSError, RuntimeError) as exc:
        failure = f"{type(exc).__name__}:{exc}"
    finally:
        elapsed = time.monotonic() - started
        samples.append(
            _resource_sample(
                elapsed=elapsed,
                writer=writer,
                event_count=event_count,
                maximum_schedule_lag=maximum_schedule_lag,
            )
        )
        final_rss = _rss_observation(elapsed)
        if rss_samples and int(
            float(rss_samples[-1]["elapsed_seconds"]) // RSS_POLL_SECONDS
        ) == int(elapsed // RSS_POLL_SECONDS):
            rss_samples[-1] = final_rss
        else:
            rss_samples.append(final_rss)
        writer_healthy = writer.close(timeout=120.0)

    with samples_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    with rss_samples_path.open("w", encoding="utf-8") as handle:
        for sample in rss_samples:
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    expected_persisted_counts = dict.fromkeys(writer.STREAMS, 0)
    expected_persisted_counts["quotes"] = event_count
    expected_persisted_counts["signals"] = event_count
    expected_persisted_counts["bars"] = len(minute_counts)
    persisted_counts = dict(writer.counts)
    enqueued_counts = dict(writer.enqueued_counts)
    segment_manifest, segment_line_counts, segment_errors = _evidence_segment_manifest(
        evidence_dir,
        writer.STREAMS,
        expected_rotation_counts=dict(writer.rotation_counts),
        expected_line_counts=persisted_counts,
    )
    queue_counts_match = persisted_counts == enqueued_counts == expected_persisted_counts
    segment_counts_match = segment_line_counts == persisted_counts
    evidence_counts_match = queue_counts_match and segment_counts_match

    peak_rss = max((int(item["rss_bytes"]) for item in rss_samples), default=0)
    resource_sampling_error_count = sum(
        int(item.get("sampling_error_count", 0)) for item in samples
    )
    resource_invalid_sample_count = sum(
        0 if bool(item.get("sampling_valid", False)) else 1 for item in samples
    )
    windows = _rss_windows(rss_samples, actual_elapsed=elapsed)
    default_shape_requested = (
        duration == DEFAULT_STRESS_SECONDS
        and base_rate == DEFAULT_BASE_RATE
        and burst_rate == DEFAULT_BURST_RATE
        and burst_seconds == DEFAULT_BURST_SECONDS
    )
    schedule = _minute_schedule_report(
        minute_counts,
        duration=duration,
        base_rate=base_rate,
        burst_rate=burst_rate,
        burst_seconds=burst_seconds,
        default_shape_requested=default_shape_requested,
    )
    complete_profile = default_shape_requested and sample_interval <= 60.0
    wall_clock_pass = elapsed >= duration
    deadline_pass = wall_clock_pass and (
        last_event_started_elapsed is None or last_event_started_elapsed < duration
    )
    schedule_lag_pass = maximum_schedule_lag <= MAX_SCHEDULE_LAG_SECONDS
    rss_sampling_healthy = bool(windows["series_quality"]["valid"])
    rss_peak_within_limit = peak_rss <= 512 * MIB
    resource_sampling_healthy = (
        resource_sampling_error_count == 0 and resource_invalid_sample_count == 0
    )
    durable_pass = (
        writer_healthy
        and writer.opening_allowed
        and not any(writer.dropped_counts.values())
        and not any(writer.pending_counts.values())
        and evidence_counts_match
        and not segment_errors
        and failure is None
    )
    source_sha256_at_end = _source_hashes()
    source_stable = source_sha256_at_end == source_sha256_at_start
    acceptance = _assess_stress_acceptance(
        complete_profile_requested=complete_profile,
        requested_wall_clock_complete=deadline_pass,
        schedule_lag_within_limit=schedule_lag_pass,
        requested_schedule_complete=bool(schedule["valid"]),
        event_count_matches_schedule=event_count == schedule["expected_total_events"],
        rss_sampling_healthy=rss_sampling_healthy,
        rss_peak_within_limit=rss_peak_within_limit,
        resource_sampling_healthy=resource_sampling_healthy,
        writer_healthy=writer_healthy,
        opening_allowed=writer.opening_allowed,
        dropped_clear=not any(writer.dropped_counts.values()),
        pending_clear=not any(writer.pending_counts.values()),
        evidence_counts_match=queue_counts_match,
        segment_integrity=segment_counts_match and not segment_errors,
        runtime_clean=failure is None,
        source_stable=source_stable,
        full_rss_windows_complete=windows["status"] == "PASS",
    )
    status = str(acceptance["status"])
    report = {
        "schema_version": "iter22.resource_benchmark.v2",
        "status": status,
        "complete_profile_requested": complete_profile,
        "acceptance": acceptance,
        "profile": {
            "duration_seconds": duration,
            "base_events_per_second": base_rate,
            "burst_events_per_second": burst_rate,
            "burst_seconds_each_minute": burst_seconds,
            "sample_interval_seconds": sample_interval,
        },
        "required_profile": {
            "duration_seconds": DEFAULT_STRESS_SECONDS,
            "base_events_per_second": DEFAULT_BASE_RATE,
            "burst_events_per_second": DEFAULT_BURST_RATE,
            "burst_seconds_each_minute": DEFAULT_BURST_SECONDS,
            "maximum_sample_interval_seconds": 60.0,
            "expected_minute_count": DEFAULT_STRESS_MINUTES,
            "expected_burst_events_per_minute": DEFAULT_BURST_EVENTS_PER_MINUTE,
            "expected_base_events_per_minute": DEFAULT_BASE_EVENTS_PER_MINUTE,
            "expected_total_events_per_minute": DEFAULT_EVENTS_PER_MINUTE,
            "expected_total_events": DEFAULT_STRESS_EVENTS,
            "maximum_schedule_lag_seconds": MAX_SCHEDULE_LAG_SECONDS,
            "rss_poll_interval_seconds": RSS_POLL_SECONDS,
            "maximum_rss_sample_interval_seconds": RSS_MAX_SAMPLE_INTERVAL_SECONDS,
            "minimum_rss_window_coverage_ratio": RSS_MIN_WINDOW_COVERAGE,
        },
        "event_count": event_count,
        "elapsed_seconds": elapsed,
        "wall_clock_duration_status": "PASS" if deadline_pass else "FAIL",
        "deadline_policy": "stop_generation_at_monotonic_deadline_without_catch_up",
        "last_event_due_elapsed_seconds": last_event_due_elapsed,
        "last_event_started_elapsed_seconds": last_event_started_elapsed,
        "maximum_schedule_lag_seconds": maximum_schedule_lag,
        "schedule_lag_status": "PASS" if schedule_lag_pass else "FAIL",
        "schedule": schedule,
        "peak_process_tree_rss_bytes": peak_rss,
        "peak_rss_limit_bytes": 512 * MIB,
        "resource_sampling_error_count": resource_sampling_error_count,
        "resource_invalid_sample_count": resource_invalid_sample_count,
        "rss_windows": windows,
        "evidence": {
            "healthy": durable_pass,
            "opening_allowed": writer.opening_allowed,
            "failure_reason": writer.failure_reason or failure,
            "expected_counts": expected_persisted_counts,
            "persisted_counts": persisted_counts,
            "enqueued_counts": enqueued_counts,
            "segment_line_counts": segment_line_counts,
            "counts_match": evidence_counts_match,
            "dropped_counts": dict(writer.dropped_counts),
            "pending_counts": writer.pending_counts,
            "rotation_counts": dict(writer.rotation_counts),
            "max_pending_counts": dict(writer.max_pending_counts),
            "max_pending_total": writer.max_pending_total,
            "queue_limit": writer.audit_queue_limit,
            "rotate_bytes": writer.rotate_bytes,
            "directory": str(evidence_dir.resolve()),
            "segment_manifest": segment_manifest,
            "segment_errors": segment_errors,
        },
        "resource_samples": {
            "path": str(samples_path.resolve()),
            "sha256": _sha256_file(samples_path),
            "count": len(samples),
        },
        "rss_samples": {
            "path": str(rss_samples_path.resolve()),
            "sha256": _sha256_file(rss_samples_path),
            "count": len(rss_samples),
            "poll_interval_seconds": RSS_POLL_SECONDS,
        },
        "hardware": hardware,
        "source_sha256": source_sha256_at_start,
        "source_sha256_at_start": source_sha256_at_start,
        "source_sha256_at_end": source_sha256_at_end,
        "source_stable": source_stable,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(report_path, report)
    print(json.dumps({"report": str(report_path), "status": status}, ensure_ascii=False))
    return int(acceptance["exit_code"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    latency = subparsers.add_parser("latency", help="run the 100k local callback benchmark")
    latency.add_argument("--samples", type=int, default=DEFAULT_LATENCY_SAMPLES)
    latency.add_argument("--warmup-samples", type=int, default=2_000)
    latency.add_argument("--output-dir")
    latency.set_defaults(handler=run_latency)

    stress = subparsers.add_parser("stress", help="run the bounded four-hour resource load")
    stress.add_argument("--duration-seconds", type=float, default=DEFAULT_STRESS_SECONDS)
    stress.add_argument("--base-rate", type=float, default=DEFAULT_BASE_RATE)
    stress.add_argument("--burst-rate", type=float, default=DEFAULT_BURST_RATE)
    stress.add_argument("--burst-seconds", type=float, default=DEFAULT_BURST_SECONDS)
    stress.add_argument("--sample-interval", type=float, default=60.0)
    stress.add_argument("--output-dir")
    stress.set_defaults(handler=run_stress)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "samples", 1) <= 0 or getattr(args, "warmup_samples", 1) < 0:
        raise SystemExit("sample counts must be positive")
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
