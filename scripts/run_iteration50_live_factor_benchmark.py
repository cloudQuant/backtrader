#!/usr/bin/env python
"""Bounded live-cohort long-stream composition benchmark.

The benchmark uses ordinary Cerebro, exact ``BtApiFeed`` instances, a
``LiveFactorSet`` bound to their complete cohort, and the SQLite execution
decision journal. Only the outer ``Store.poll_live`` leaf is synthetic. It
creates one bar at a time from a deterministic rank-crossing recipe; no full
event tape or factor-output array is materialized.

Run one mode per process.  ``--smoke`` selects a small composition profile;
``--grids 100000`` selects the Iteration 50/51 accelerated-stream size after
warm-up. ``--factors representative-six`` selects Alpha001/003/006/048/056/101.
The finite calendar can be wall-clock paced with ``--duration-seconds``; this
does not turn the synthetic source into online/provider evidence, nor does the
current harness cover the fault/idle/Broker lifecycle required for AC50-27b.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
import uuid


ASSET_COUNT = 20
FACTOR_NAME = "alpha003"
CORRELATION_WINDOW = 10
DEFAULT_WARMUP_BARS = 30
DEFAULT_ALPHA003_FORMAL_WARMUP_BARS = 64
SIX_FACTOR_MAX_LOOKBACK = 252
SIX_FACTOR_BUFFER_STABILITY_BARS = 64
DEFAULT_SIX_FACTOR_WARMUP_BARS = SIX_FACTOR_MAX_LOOKBACK + SIX_FACTOR_BUFFER_STABILITY_BARS
DEFAULT_SMOKE_GRIDS = 24
MAX_FORMAL_GRIDS = 100_000
MAX_WINDOW_BARS = 4096
MAX_CALENDAR_SLOTS = 200_000
DEFAULT_LINE_WINDOW = 64
BASE_JOURNAL_BYTE_BUDGET = 512 * 1024 * 1024
SETTLEMENT_JOURNAL_RECORD_RESERVE = 4096
SETTLEMENT_JOURNAL_BYTE_RESERVE = 64 * 1024 * 1024
JOURNAL_ESTIMATED_ROW_BYTE_BUDGET = 4096
RSS_GROWTH_ABSOLUTE_LIMIT = 32 * 1024 * 1024
LATENCY_P99_LIMIT_MS = 100.0
LATENCY_MAX_LIMIT_MS = 500.0
LATENCY_HISTOGRAM_RESOLUTION_MS = 0.1
LATENCY_HISTOGRAM_MAX_MS = 1000.0
UTC = timezone.utc
FACTOR_IDS = {
    "alpha003": (3,),
    "representative-six": (1, 3, 6, 48, 56, 101),
}
FACTOR_NAMES = {alpha_id: "alpha%03d" % alpha_id for alpha_id in (1, 3, 6, 48, 56, 101)}
FACTOR_FIELDS = {
    1: ("close",),
    3: ("open", "volume"),
    6: ("open", "volume"),
    48: ("close", "subindustry"),
    56: ("close", "cap"),
    101: ("open", "high", "low", "close"),
}
EXTRA_FACTOR_FIELDS = ("vwap", "cap", "sector", "industry", "subindustry")
STANDARD_SOURCE_LINE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "openinterest",
)
SOURCE_LINE_FIELDS = STANDARD_SOURCE_LINE_FIELDS + EXTRA_FACTOR_FIELDS


def _source_fields_for(factor_profile: str) -> Tuple[str, ...]:
    """Keep the accepted Alpha003 profile independent of deferred extra lines."""
    if factor_profile == "alpha003":
        return STANDARD_SOURCE_LINE_FIELDS
    if factor_profile == "representative-six":
        return SOURCE_LINE_FIELDS
    raise BenchmarkFailure("unsupported_factor_profile")


def _window_bars_for(factor_profile: str, warmup_bars: int) -> int:
    profile_lookback = (
        SIX_FACTOR_MAX_LOOKBACK if factor_profile == "representative-six" else CORRELATION_WINDOW
    )
    return max(DEFAULT_LINE_WINDOW, warmup_bars, profile_lookback)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_generator_sha256(factor_profile: str) -> str:
    """Hash generator source together with its profile-specific input contract."""
    generator_source = "\n\n".join(
        inspect.getsource(function).replace("\r\n", "\n").replace("\r", "\n")
        for function in (_make_slots, _event_values)
    )
    payload = json.dumps(
        {
            "generator_source": generator_source,
            "factor_profile": factor_profile,
            "factor_ids": FACTOR_IDS[factor_profile],
            "targets": ["ASSET%02d" % index for index in range(ASSET_COUNT)],
            "source_fields": _source_fields_for(factor_profile),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _runtime_facts() -> Dict[str, Any]:
    return {
        "python_version": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "os_system": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
    }


class BenchmarkFailure(RuntimeError):
    """A bounded benchmark contract failed."""


class _LatencyHistogram:
    """Fixed-capacity histogram that gives a conservative p99 upper bound."""

    def __init__(self) -> None:
        self._width = LATENCY_HISTOGRAM_RESOLUTION_MS
        self._max = LATENCY_HISTOGRAM_MAX_MS
        self._bins = [0] * (int(self._max / self._width) + 1)
        self._count = 0
        self._max_observed = 0.0
        self._overflow = 0

    def add(self, value_ms: float) -> None:
        value = float(value_ms)
        if not math.isfinite(value) or value < 0.0:
            raise BenchmarkFailure("invalid_monotonic_latency")
        self._count += 1
        self._max_observed = max(self._max_observed, value)
        if value > self._max:
            self._overflow += 1
            return
        index = min(int(value / self._width), len(self._bins) - 1)
        self._bins[index] += 1

    @property
    def count(self) -> int:
        return self._count

    @property
    def maximum_ms(self) -> float:
        return self._max_observed

    @property
    def p99_upper_bound_ms(self) -> Optional[float]:
        if not self._count:
            return None
        target = int(math.ceil(0.99 * self._count))
        seen = 0
        for index, count in enumerate(self._bins):
            seen += count
            if seen >= target:
                return min((index + 1) * self._width, self._max)
        if seen + self._overflow >= target:
            return self._max_observed
        return None

    def report(self) -> Dict[str, Any]:
        return {
            "sample_count": self.count,
            "p99_upper_bound_ms": self.p99_upper_bound_ms,
            "max_ms": self.maximum_ms if self.count else None,
        }


def _sanitize_import_path(package_root: Optional[Path]) -> Path:
    """Select one explicit Backtrader root and remove ambient PYTHONPATH roots."""
    repository_root = Path(__file__).resolve().parents[1]
    selected_root = (package_root or repository_root).resolve()
    if not (selected_root / "backtrader" / "__init__.py").is_file():
        raise BenchmarkFailure("selected_package_root_has_no_backtrader_package")

    ambient = {
        os.path.normcase(os.path.abspath(value.strip().strip('"')))
        for value in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if value.strip()
    }
    filtered = []
    for entry in sys.path:
        candidate = entry or os.getcwd()
        if os.path.normcase(os.path.abspath(candidate)) in ambient:
            continue
        if os.path.normcase(os.path.abspath(candidate)) == os.path.normcase(str(repository_root)):
            continue
        filtered.append(entry)
    sys.path[:] = [str(selected_root)] + filtered
    return selected_root


def _validate_cli(args: argparse.Namespace) -> Tuple[int, int, str]:
    if args.smoke and args.grids is not None:
        raise BenchmarkFailure("choose_smoke_or_explicit_grids")
    if not args.smoke and args.grids is None:
        raise BenchmarkFailure("select_smoke_or_explicit_grids")
    grids = DEFAULT_SMOKE_GRIDS if args.smoke else args.grids
    if type(grids) is not int or not 1 <= grids <= MAX_FORMAL_GRIDS:
        raise BenchmarkFailure("evaluation_grid_count_out_of_range")
    if args.factors not in FACTOR_IDS:
        raise BenchmarkFailure("unsupported_factor_profile")
    default_warmup = (
        DEFAULT_SIX_FACTOR_WARMUP_BARS
        if args.factors == "representative-six"
        else DEFAULT_WARMUP_BARS
    )
    warmup_bars = default_warmup if args.warmup_bars is None else args.warmup_bars
    minimum_warmup = (
        DEFAULT_SIX_FACTOR_WARMUP_BARS
        if args.factors == "representative-six"
        else CORRELATION_WINDOW
    )
    if type(warmup_bars) is not int or warmup_bars < minimum_warmup:
        raise BenchmarkFailure("warmup_does_not_cover_profile_lookback_and_buffer")
    if warmup_bars > MAX_WINDOW_BARS:
        raise BenchmarkFailure("warmup_exceeds_bounded_window_capacity")
    if warmup_bars + grids > MAX_CALENDAR_SLOTS:
        raise BenchmarkFailure("finite_calendar_exceeds_200000_slot_limit")
    if args.mode not in ("native", "build"):
        raise BenchmarkFailure("unsupported_factor_mode")
    if type(args.duration_seconds) is not int or args.duration_seconds < 0:
        raise BenchmarkFailure("duration_seconds_must_be_a_nonnegative_integer")
    if not args.smoke and args.factors == "representative-six":
        if grids < MAX_FORMAL_GRIDS:
            raise BenchmarkFailure("representative_six_requires_100000_evaluation_grids")
        if args.duration_seconds < 7200:
            raise BenchmarkFailure("representative_six_requires_7200_wall_clock_seconds")
    if not args.output:
        raise BenchmarkFailure("an_explicit_output_path_is_required")
    output_path = Path(args.output).expanduser().resolve(strict=False)
    if output_path.exists():
        raise BenchmarkFailure("output_path_already_exists")
    database_path = output_path.with_name(output_path.stem + ".decisions.sqlite3")
    if database_path.exists():
        raise BenchmarkFailure("decision_database_path_already_exists")
    profile = "SMOKE_COMPOSITION" if args.smoke else "ACCELERATED_LONGSTREAM"
    return grids, warmup_bars, profile


def _average_ranks(values: Sequence[float]) -> Tuple[float, ...]:
    """Independent alpha101-v2 average ranks, normalized by finite count."""
    count = len(values)
    order = sorted(range(count), key=lambda index: values[index])
    ranks = [0.0] * count
    start = 0
    while start < count:
        end = start + 1
        while end < count and values[order[end]] == values[order[start]]:
            end += 1
        rank = ((start + 1) + end) / (2.0 * count)
        for ordered_index in range(start, end):
            ranks[order[ordered_index]] = rank
        start = end
    return tuple(ranks)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise BenchmarkFailure("oracle_window_is_not_complete")
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    left_ss = math.fsum(value * value for value in left_centered)
    right_ss = math.fsum(value * value for value in right_centered)
    if left_ss <= 0.0 or right_ss <= 0.0:
        raise BenchmarkFailure("oracle_correlation_window_is_constant")
    result = math.fsum(a * b for a, b in zip(left_centered, right_centered)) / (
        math.sqrt(left_ss) * math.sqrt(right_ss)
    )
    if not math.isfinite(result):
        raise BenchmarkFailure("oracle_correlation_is_not_finite")
    return result


def _population_std(values: Sequence[float]) -> float:
    """Independent population standard deviation for Alpha001's stream oracle."""
    if not values:
        raise BenchmarkFailure("oracle_std_window_is_empty")
    scale = max(abs(value) for value in values)
    if scale == 0.0:
        return 0.0
    normalized = [value / scale for value in values]
    mean = math.fsum(normalized) / len(normalized)
    variance = math.fsum((value - mean) ** 2 for value in normalized) / len(normalized)
    return scale * math.sqrt(variance)


class _StreamingFactorOracle:
    """Bounded scalar reference for the six selected frozen Alpha formulas.

    This implementation intentionally uses only source rows, bounded deques,
    and small scalar math helpers above. It never calls production factor,
    operator, or registry calculation methods.
    """

    def __init__(self, targets: Sequence[str], factor_ids: Sequence[int]) -> None:
        self.targets = tuple(targets)
        self.factor_ids = tuple(factor_ids)
        self._state = {
            target: {
                "close": deque(maxlen=SIX_FACTOR_MAX_LOOKBACK + 2),
                "returns": deque(maxlen=20),
                "open": deque(maxlen=CORRELATION_WINDOW),
                "volume": deque(maxlen=CORRELATION_WINDOW),
                "alpha003_open_rank": deque(maxlen=CORRELATION_WINDOW),
                "alpha003_volume_rank": deque(maxlen=CORRELATION_WINDOW),
                "alpha001_power": deque(maxlen=5),
                "alpha048_left": deque(maxlen=250),
                "alpha048_right": deque(maxlen=250),
                "alpha048_return_square": deque(maxlen=250),
                "alpha056_inner_sum": deque(maxlen=3),
            }
            for target in self.targets
        }

    def update(self, rows: Mapping[str, Mapping[str, float]]) -> Dict[str, Dict[str, float]]:
        if set(rows) != set(self.targets):
            raise BenchmarkFailure("oracle_did_not_receive_the_complete_source_grid")
        ordered = tuple(rows[target] for target in self.targets)
        ranks_by_field = {}
        for field in ("open", "volume"):
            ranks = _average_ranks(tuple(float(row[field]) for row in ordered))
            ranks_by_field[field] = ranks
            rank_key = "alpha003_%s_rank" % field
            for index, target in enumerate(self.targets):
                self._state[target][rank_key].append(ranks[index])

        per_asset = {}
        for target, row in zip(self.targets, ordered):
            state = self._state[target]
            close = float(row["close"])
            state["close"].append(close)
            state["open"].append(float(row["open"]))
            state["volume"].append(float(row["volume"]))
            previous_close = state["close"][-2] if len(state["close"]) >= 2 else None
            current_return = None
            delta_now = None
            if previous_close is not None:
                delta_now = close - previous_close
                if previous_close == 0.0:
                    raise BenchmarkFailure("oracle_return_denominator_is_zero")
                current_return = delta_now / previous_close
                state["returns"].append(current_return)
                state["alpha048_return_square"].append(current_return * current_return)
                if len(state["returns"]) >= 2:
                    state["alpha056_inner_sum"].append(math.fsum(tuple(state["returns"])[-2:]))
            if len(state["close"]) >= 3:
                delayed_delta = state["close"][-2] - state["close"][-3]
                state["alpha048_left"].append(delta_now)
                state["alpha048_right"].append(delayed_delta)

            alpha001_raw = None
            if len(state["returns"]) == 20:
                selected = (
                    _population_std(tuple(state["returns"])) if current_return < 0.0 else close
                )
                state["alpha001_power"].append(selected * selected)
                if len(state["alpha001_power"]) == 5:
                    values = tuple(state["alpha001_power"])
                    alpha001_raw = float(values.index(max(values)) + 1)

            alpha003_value = None
            if len(state["alpha003_open_rank"]) == CORRELATION_WINDOW:
                alpha003_value = -_pearson(
                    tuple(state["alpha003_open_rank"]),
                    tuple(state["alpha003_volume_rank"]),
                )

            alpha006_value = None
            if len(state["open"]) == CORRELATION_WINDOW:
                alpha006_value = -_pearson(tuple(state["open"]), tuple(state["volume"]))

            alpha048_raw = None
            if len(state["alpha048_left"]) == 250 and len(state["alpha048_return_square"]) == 250:
                correlation = _pearson(
                    tuple(state["alpha048_left"]), tuple(state["alpha048_right"])
                )
                alpha048_raw = (correlation * delta_now) / close

            alpha056_ratio = None
            if len(state["returns"]) >= 10 and len(state["alpha056_inner_sum"]) == 3:
                nested_sum = math.fsum(state["alpha056_inner_sum"])
                if nested_sum != 0.0:
                    alpha056_ratio = math.fsum(tuple(state["returns"])[-10:]) / nested_sum
            alpha056_return_cap = None
            if 56 in self.factor_ids and current_return is not None:
                alpha056_return_cap = current_return * float(row["cap"])

            high = float(row["high"])
            low = float(row["low"])
            alpha101_value = (close - float(row["open"])) / (high - low + 0.001)
            per_asset[target] = {
                "alpha001_raw": alpha001_raw,
                "alpha003": alpha003_value,
                "alpha006": alpha006_value,
                "alpha048_raw": alpha048_raw,
                "alpha056_ratio": alpha056_ratio,
                "alpha056_return_cap": alpha056_return_cap,
                "alpha101": alpha101_value,
            }

        results: Dict[str, Dict[str, float]] = {}
        if 1 in self.factor_ids:
            raw = [per_asset[target]["alpha001_raw"] for target in self.targets]
            results["alpha001"] = self._rank_finite(raw, offset=-0.5)
        if 3 in self.factor_ids:
            results["alpha003"] = self._as_factor_map(
                [per_asset[target]["alpha003"] for target in self.targets]
            )
        if 6 in self.factor_ids:
            results["alpha006"] = self._as_factor_map(
                [per_asset[target]["alpha006"] for target in self.targets]
            )
        if 48 in self.factor_ids:
            raw = [per_asset[target]["alpha048_raw"] for target in self.targets]
            neutralized = self._neutralize_by_subindustry(raw, ordered)
            results["alpha048"] = {}
            for target, value in zip(self.targets, neutralized):
                denom = math.fsum(self._state[target]["alpha048_return_square"])
                if value is not None and denom != 0.0:
                    results["alpha048"][target] = value / denom
        if 56 in self.factor_ids:
            ratio = [per_asset[target]["alpha056_ratio"] for target in self.targets]
            return_cap = [per_asset[target]["alpha056_return_cap"] for target in self.targets]
            ratio_ranks = self._rank_finite(ratio)
            return_cap_ranks = self._rank_finite(return_cap)
            results["alpha056"] = {
                target: -(ratio_ranks[target] * return_cap_ranks[target])
                for target in self.targets
                if target in ratio_ranks and target in return_cap_ranks
            }
        if 101 in self.factor_ids:
            results["alpha101"] = self._as_factor_map(
                [per_asset[target]["alpha101"] for target in self.targets]
            )
        return results

    def _as_factor_map(self, values: Sequence[Optional[float]]) -> Dict[str, float]:
        return {
            target: float(value)
            for target, value in zip(self.targets, values)
            if value is not None and math.isfinite(value)
        }

    def _rank_finite(
        self, values: Sequence[Optional[float]], *, offset: float = 0.0
    ) -> Dict[str, float]:
        finite_indices = [index for index, value in enumerate(values) if value is not None]
        if not finite_indices:
            return {}
        ranks = _average_ranks(tuple(float(values[index]) for index in finite_indices))
        return {
            self.targets[index]: ranks[position] + offset
            for position, index in enumerate(finite_indices)
        }

    def _neutralize_by_subindustry(
        self, values: Sequence[Optional[float]], rows: Sequence[Mapping[str, float]]
    ) -> Tuple[Optional[float], ...]:
        groups: Dict[float, list] = {}
        for index, (value, row) in enumerate(zip(values, rows)):
            if value is not None and math.isfinite(value):
                groups.setdefault(float(row["subindustry"]), []).append(index)
        result: list = [None] * len(values)
        for indices in groups.values():
            mean = math.fsum(float(values[index]) for index in indices) / len(indices)
            for index in indices:
                result[index] = float(values[index]) - mean
        return tuple(result)


def _within_tolerance(actual: float, expected: float) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= (1.0e-12 + 1.0e-10 * abs(expected))


def _require_positive_witnesses(report: Mapping[str, Any]) -> None:
    """Reject empty/all-missing runtime evidence before a report can pass."""
    oracle = report.get("oracle")
    if not isinstance(oracle, Mapping):
        raise BenchmarkFailure("oracle_summary_missing")
    comparisons = oracle.get("comparisons")
    finite = oracle.get("finite_factor_values")
    distinct = oracle.get("distinct_finite_factor_values")
    if type(comparisons) is not int or comparisons <= 0:
        raise BenchmarkFailure("oracle_produced_no_comparisons")
    if type(finite) is not int or finite <= 0:
        raise BenchmarkFailure("factor_produced_no_finite_values")
    if type(distinct) is not int or distinct < 2:
        raise BenchmarkFailure("factor_has_no_nontrivial_finite_witness")
    factor_names = report.get("profile", {}).get("factor_names", (FACTOR_NAME,))
    per_factor = oracle.get("per_factor")
    if not isinstance(per_factor, Mapping):
        raise BenchmarkFailure("per_factor_oracle_summary_missing")
    for factor_name in factor_names:
        evidence = per_factor.get(factor_name)
        if not isinstance(evidence, Mapping):
            raise BenchmarkFailure("factor_oracle_witness_missing:%s" % factor_name)
        if type(evidence.get("comparisons")) is not int or evidence["comparisons"] <= 0:
            raise BenchmarkFailure("factor_oracle_produced_no_comparisons:%s" % factor_name)
        if (
            type(evidence.get("finite_factor_values")) is not int
            or evidence["finite_factor_values"] <= 0
        ):
            raise BenchmarkFailure("factor_produced_no_finite_values:%s" % factor_name)
        if (
            type(evidence.get("distinct_finite_factor_values")) is not int
            or evidence["distinct_finite_factor_values"] < 2
        ):
            raise BenchmarkFailure("factor_has_no_nontrivial_finite_witness:%s" % factor_name)
    if report.get("runtime", {}).get("strategy_next_calls") != report.get("profile", {}).get(
        "total_grid_slots"
    ):
        raise BenchmarkFailure("ordinary_strategy_runtime_was_not_fully_exercised")


def _check_gates(report: Dict[str, Any]) -> Tuple[bool, Tuple[str, ...]]:
    failures = []
    try:
        _require_positive_witnesses(report)
    except BenchmarkFailure as error:
        failures.append(str(error))

    profile = report.get("profile", {})
    durable = report.get("durable_noop_journal", {})
    expected = profile.get("evaluation_grids")
    if durable.get("noop_rows") != expected or durable.get("new_grid_rows") != expected:
        failures.append("durable_noop_rows_do_not_match_evaluation_grids")
    if durable.get("cursor_ordinal") != expected:
        failures.append("durable_grid_cursor_did_not_advance_once_per_evaluation_grid")
    capacity_before = durable.get("capacity_before")
    capacity_after = durable.get("capacity_after")
    if not isinstance(capacity_before, Mapping) or not isinstance(capacity_after, Mapping):
        failures.append("journal_capacity_snapshots_missing")
    else:
        if capacity_before.get("base_record_count") != 0:
            failures.append("journal_base_capacity_was_not_empty_before_run")
        if capacity_after.get("base_record_count") != expected:
            failures.append("journal_base_record_high_water_did_not_match_noop_rows")
        if (
            capacity_before.get("base_record_limit") != expected
            or capacity_after.get("base_record_limit") != expected
        ):
            failures.append("journal_base_record_budget_is_below_planned_noop_rows")
        if capacity_before.get("base_payload_byte_limit") != BASE_JOURNAL_BYTE_BUDGET or (
            capacity_after.get("base_payload_byte_limit") != BASE_JOURNAL_BYTE_BUDGET
        ):
            failures.append("journal_base_payload_byte_budget_is_not_explicit_profile_budget")
        if capacity_before.get("settlement_record_count") != 0 or (
            capacity_after.get("settlement_record_count") != 0
        ):
            failures.append("journal_settlement_reserve_was_unexpectedly_consumed")
        if (
            capacity_before.get("settlement_record_limit") != SETTLEMENT_JOURNAL_RECORD_RESERVE
            or capacity_after.get("settlement_record_limit") != SETTLEMENT_JOURNAL_RECORD_RESERVE
        ):
            failures.append("journal_settlement_record_reserve_is_not_explicit")
        if (
            capacity_before.get("settlement_payload_byte_limit") != SETTLEMENT_JOURNAL_BYTE_RESERVE
            or capacity_after.get("settlement_payload_byte_limit")
            != SETTLEMENT_JOURNAL_BYTE_RESERVE
        ):
            failures.append("journal_settlement_byte_reserve_is_not_explicit")
        if (
            type(capacity_before.get("base_payload_bytes")) is not int
            or capacity_before.get("base_payload_bytes") != 0
            or type(capacity_after.get("base_payload_bytes")) is not int
            or type(capacity_after.get("base_payload_byte_limit")) is not int
            or capacity_after.get("base_payload_bytes", -1)
            > capacity_after.get("base_payload_byte_limit", -1)
        ):
            failures.append("journal_base_payload_bytes_exceeded_explicit_budget")
        for snapshot in (capacity_before, capacity_after):
            database_bytes = snapshot.get("database_bytes")
            wal_bytes = snapshot.get("wal_bytes")
            physical_bytes = snapshot.get("physical_bytes")
            if (
                type(database_bytes) is not int
                or type(wal_bytes) is not int
                or type(physical_bytes) is not int
                or min(database_bytes, wal_bytes, physical_bytes) < 0
                or physical_bytes != database_bytes + wal_bytes
            ):
                failures.append("journal_physical_db_wal_measurement_invalid")
                break

    latency = report.get("latency", {})
    if latency.get("sample_count") != expected:
        failures.append("durable_decision_latency_samples_do_not_match_evaluation_grids")
    p99 = latency.get("p99_upper_bound_ms")
    maximum = latency.get("max_ms")
    if (
        type(p99) not in (int, float)
        or not math.isfinite(float(p99))
        or p99 < 0.0
        or p99 > LATENCY_P99_LIMIT_MS
    ):
        failures.append("durable_decision_p99_latency_exceeded_100ms")
    if (
        type(maximum) not in (int, float)
        or not math.isfinite(float(maximum))
        or maximum < 0.0
        or maximum > LATENCY_MAX_LIMIT_MS
    ):
        failures.append("durable_decision_max_latency_exceeded_500ms")

    oracle = report.get("oracle", {})
    if (
        type(oracle.get("rank_reason_failures")) is not int
        or oracle.get("rank_reason_failures") != 0
    ):
        failures.append("rank_nodes_reported_reason_failures")
    if (
        type(oracle.get("correlation_reason_failures")) is not int
        or oracle.get("correlation_reason_failures") != 0
    ):
        failures.append("correlation_nodes_reported_reason_failures")
    for factor_name in profile.get("factor_names", (FACTOR_NAME,)):
        factor_evidence = oracle.get("per_factor", {}).get(factor_name, {})
        if factor_evidence.get("output_reason_failures") != 0:
            failures.append("factor_output_reason_failures:%s" % factor_name)
        if factor_evidence.get("output_unavailable_grids") != 0:
            failures.append("factor_outputs_unavailable:%s" % factor_name)

    memory = report.get("memory", {})
    growth = memory.get("rss_growth_bytes")
    threshold = memory.get("rss_growth_limit_bytes")
    if type(growth) is not int or type(threshold) is not int or growth > threshold:
        failures.append("rss_growth_exceeded_fixed_capacity_limit")
    if not isinstance(memory.get("rss_sampling_method"), str) or not memory.get(
        "rss_sampling_method"
    ):
        failures.append("rss_current_sampler_method_missing")
    if memory.get("rss_sampling_scope") != "benchmark_process":
        failures.append("rss_sampling_scope_is_not_benchmark_process")
    if memory.get("process_tree_peak_claimed") is not False:
        failures.append("rss_report_makes_unsupported_process_tree_peak_claim")
    if memory.get("rss_samples_may_miss_transient_peaks") is not True:
        failures.append("rss_sampling_limit_not_disclosed")
    rss_window = memory.get("equal_window_samples")
    if (
        type(rss_window) is not int
        or rss_window <= 0
        or memory.get("first_window_sample_count") != rss_window
        or memory.get("last_window_sample_count") != rss_window
    ):
        failures.append("rss_first_and_last_windows_are_not_equally_sampled")

    capacities = report.get("capacities", {})
    if capacities.get("configured_pending_slots") != 1:
        failures.append("source_pending_slot_capacity_is_not_one")
    if capacities.get("source_rows_retained_max", ASSET_COUNT + 1) > ASSET_COUNT:
        failures.append("source_leaf_retained_more_than_one_member_row_per_asset")
    if (
        capacities.get("cohort_pending_slots_at_end") != 0
        or capacities.get("source_rows_retained_at_end") != 0
    ):
        failures.append("source_buffers_were_not_empty_after_finite_stream")
    window_limit = ASSET_COUNT * capacities.get("configured_window_bars_per_member", 0)
    if (
        type(capacities.get("retained_receipts_at_end")) is not int
        or capacities.get("retained_receipts_at_end", window_limit + 1) > window_limit
    ):
        failures.append("cohort_receipts_exceeded_configured_rolling_window")
    if capacities.get("receipt_window_full_at_first_sample") is not True:
        failures.append("cohort_receipt_window_not_full_at_first_sample")
    if capacities.get("receipt_window_full_at_last_sample") is not True:
        failures.append("cohort_receipt_window_not_full_at_last_sample")
    if capacities.get("line_buffers_full_at_first_sample") is not True:
        failures.append("line_buffers_not_full_at_first_steady_sample")
    if capacities.get("line_buffers_full_at_last_sample") is not True:
        failures.append("line_buffers_not_full_at_last_steady_sample")
    if capacities.get("line_capacity_grew_after_warmup") is True:
        failures.append("line_capacity_grew_after_warmup")
    first_lines = capacities.get("line_capacity_first", {})
    last_lines = capacities.get("line_capacity_last", {})
    if (
        type(first_lines.get("value_line_count")) is not int
        or first_lines.get("value_line_count", 0) <= 0
        or type(first_lines.get("reason_line_count")) is not int
        or first_lines.get("reason_line_count", 0) <= 0
        or type(first_lines.get("factor_instance_root_count")) is not int
        or first_lines.get("factor_instance_root_count", 0) <= 0
        or type(first_lines.get("owner_count")) is not int
        or first_lines.get("owner_count", 0) <= 0
        or first_lines.get("line_count") != last_lines.get("line_count")
        or first_lines.get("owner_count") != last_lines.get("owner_count")
        or first_lines.get("factor_instance_root_count")
        != last_lines.get("factor_instance_root_count")
        or first_lines.get("value_line_count") != last_lines.get("value_line_count")
        or first_lines.get("reason_line_count") != last_lines.get("reason_line_count")
    ):
        failures.append("value_reason_line_counts_missing_or_unstable")
    if capacities.get("diagnostics_bounded") is not True:
        failures.append("factor_diagnostics_are_not_bounded")
    diagnostic_limit = capacities.get("factor_diagnostic_sample_capacity_max")
    diagnostic_retained = capacities.get("factor_diagnostic_samples_retained_max")
    if (
        type(diagnostic_limit) is not int
        or diagnostic_limit <= 0
        or type(diagnostic_retained) is not int
        or diagnostic_retained < 0
        or diagnostic_retained > diagnostic_limit
    ):
        failures.append("factor_diagnostic_samples_exceeded_capacity")

    runtime = report.get("runtime", {})
    if runtime.get("warmup_complete_grids") != profile.get("warmup_bars"):
        failures.append("ordinary_strategy_warmup_grid_count_mismatch")
    requested_duration = profile.get("minimum_wall_clock_duration_seconds", 0)
    elapsed = report.get("elapsed_seconds")
    if (
        type(requested_duration) not in (int, float)
        or not math.isfinite(float(requested_duration))
        or requested_duration < 0
        or type(elapsed) not in (int, float)
        or not math.isfinite(float(elapsed))
        or elapsed < requested_duration
    ):
        failures.append("requested_monotonic_wall_clock_duration_not_met")
    return not failures, tuple(failures)


def _load_psutil_module():
    try:
        import psutil

        return psutil
    except ImportError:
        raise


class _RssSampler:
    """Read current resident bytes for the benchmark process only."""

    def __init__(self, method: str, reader):
        self.method = method
        self._reader = reader

    def sample_bytes(self) -> int:
        try:
            value = self._reader()
        except BenchmarkFailure:
            raise
        except Exception:
            raise BenchmarkFailure("rss_sampling_failed") from None
        if type(value) is not int or value <= 0:
            raise BenchmarkFailure("rss_sampling_returned_invalid_current_bytes")
        return value


def _read_windows_working_set_bytes() -> int:
    import ctypes
    from ctypes import wintypes

    class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    if not ok:
        raise BenchmarkFailure("rss_sampling_failed")
    return int(counters.WorkingSetSize)


def _read_linux_proc_rss_bytes() -> int:
    try:
        fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
        resident_pages = int(fields[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        raise BenchmarkFailure("rss_sampling_failed") from None
    if resident_pages <= 0 or page_size <= 0:
        raise BenchmarkFailure("rss_sampling_returned_invalid_current_bytes")
    return resident_pages * page_size


def _create_rss_sampler(
    *, platform_name: Optional[str] = None, os_name: Optional[str] = None
) -> _RssSampler:
    """Select an actual current-RSS source or fail closed before the run."""
    selected_platform = sys.platform if platform_name is None else platform_name
    selected_os = os.name if os_name is None else os_name
    try:
        psutil = _load_psutil_module()
    except ImportError:
        psutil = None
    except Exception:
        raise BenchmarkFailure("rss_sampler_initialization_failed") from None

    if psutil is not None:
        try:
            process = psutil.Process(os.getpid())
        except Exception:
            raise BenchmarkFailure("rss_sampler_initialization_failed") from None
        return _RssSampler(
            "psutil.Process(os.getpid()).memory_info().rss",
            lambda: int(process.memory_info().rss),
        )
    if selected_os == "nt":
        return _RssSampler(
            "Windows GetProcessMemoryInfo.WorkingSetSize", _read_windows_working_set_bytes
        )
    if selected_platform.startswith("linux"):
        return _RssSampler("Linux /proc/self/statm resident pages", _read_linux_proc_rss_bytes)
    raise BenchmarkFailure("rss_sampler_unavailable")


def _rss_window_summary(first_samples: Sequence[int], last_samples: Sequence[int]):
    if not first_samples or not last_samples:
        return {
            "first_window_median_rss_bytes": None,
            "last_window_median_rss_bytes": None,
            "rss_growth_bytes": None,
            "rss_growth_limit_bytes": None,
            "growth_pass": False,
        }
    if any(type(value) is not int or value <= 0 for value in (*first_samples, *last_samples)):
        raise BenchmarkFailure("rss_sampling_returned_invalid_current_bytes")
    first_median = int(statistics.median(first_samples))
    last_median = int(statistics.median(last_samples))
    growth = last_median - first_median
    growth_limit = max(RSS_GROWTH_ABSOLUTE_LIMIT, int(first_median * 0.10))
    return {
        "first_window_median_rss_bytes": first_median,
        "last_window_median_rss_bytes": last_median,
        "rss_growth_bytes": growth,
        "rss_growth_limit_bytes": growth_limit,
        "growth_pass": growth <= growth_limit,
    }


def _make_slots(slot_count: int):
    from backtrader.research.live_cohort import LiveCalendarSlot

    start = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    day = start.date().isoformat()
    return tuple(
        LiveCalendarSlot(
            slot_id="grid-%06d" % index,
            bucket_start=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            trading_day=day,
            session_segment="synthetic-regular",
        )
        for index in range(slot_count)
    )


def _event_values(asset_index: int, grid_index: int) -> Dict[str, float]:
    """Deterministic, crossing, finite source row for one poll only."""
    open_position = (asset_index * 7 + grid_index * 3) % ASSET_COUNT
    volume_position = (asset_index * 13 + grid_index * 7) % ASSET_COUNT
    open_value = 100.0 + open_position
    phase = (asset_index + 1) * (grid_index + 1) * 0.08
    close_value = (
        100.0
        + asset_index * 0.6
        + grid_index * 0.015
        + 0.03 * math.sin(phase)
        + 0.012 * math.cos(phase * 0.61)
    )
    high_value = max(open_value, close_value) + 0.25
    low_value = min(open_value, close_value) - 0.25
    return {
        "open": open_value,
        "high": high_value,
        "low": low_value,
        "close": close_value,
        "volume": 1000.0 + volume_position + 0.05 * math.sin(phase * 0.73),
        "openinterest": 0.0,
        # This is an independent synthetic source field; never reconstruct it
        # from the row's OHLC values inside the benchmark fixture.
        "vwap": 98.5
        + asset_index * 0.37
        + (grid_index % 29) * 0.013
        + 0.02 * math.sin(phase * 0.37),
        "cap": 1_000_000.0 + asset_index * 50_000.0 + grid_index * 100.0,
        "sector": float(asset_index // 10),
        "industry": float(asset_index // 5),
        "subindustry": float(asset_index // 5),
    }


def _cohort_diagnostics(cohort: Any, feed_mapping: Mapping[str, Any]) -> Dict[str, Any]:
    """Return finite counters useful when a synthetic composition fails."""
    return {
        "cohort_frozen": cohort.frozen,
        "cohort_frozen_reason": cohort.frozen_reason,
        "cohort_next_slot_index": cohort._next_slot_index,
        "cohort_pending_by_slot": {
            str(slot_index): len(rows) for slot_index, rows in sorted(cohort._pending.items())
        },
        "feed_last_delivered_slot": {
            name: feed._cohort_last_delivered_slot_index for name, feed in feed_mapping.items()
        },
    }


def _make_runtime(args: argparse.Namespace, grids: int, warmup_bars: int, rss_sampler: _RssSampler):
    """Build one isolated ordinary Cerebro/live-feed/journal profile."""
    import backtrader as bt
    from backtrader.research import FactorSpec, LiveFactorPlan, LiveFactorSet
    from backtrader.research.alpha101 import get_alpha
    from backtrader.research.live_cohort import LiveBarCohort, LiveCohortCalendar
    from backtrader.research.operators import OperatorReason
    from backtrader.stores.execution_decision_journal import (
        ExecutionDecisionJournal,
        ExecutionDecisionKey,
    )

    targets = tuple("ASSET%02d" % index for index in range(ASSET_COUNT))
    factor_ids = FACTOR_IDS[args.factors]
    factor_names = tuple(FACTOR_NAMES[alpha_id] for alpha_id in factor_ids)
    source_fields = _source_fields_for(args.factors)
    total_slots = warmup_bars + grids
    slots = _make_slots(total_slots)
    calendar = LiveCohortCalendar(
        calendar_id="iteration50-%s-%s" % (args.factors, args.mode),
        version="synthetic-v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="synthetic-source-utc",
        session_semantics="synthetic-regular-v1",
        slots=slots,
    )

    class _AcceleratedSourceClock:
        def __init__(self):
            self.grid_index = 0
            self.wait_calls = 0
            self.wait_seconds = 0.0
            self.pacing_start_ns = time.monotonic_ns()
            self.duration_ns = int(args.duration_seconds * 1_000_000_000)

        def wait_for_grid(self, grid_index):
            if not self.duration_ns:
                return
            target_ns = self.pacing_start_ns + (self.duration_ns * grid_index) // total_slots
            remaining_ns = target_ns - time.monotonic_ns()
            if remaining_ns > 0:
                seconds = remaining_ns / 1_000_000_000.0
                self.wait_calls += 1
                self.wait_seconds += seconds
                time.sleep(seconds)

        def wait_until_duration(self):
            if not self.duration_ns:
                return
            target_ns = self.pacing_start_ns + self.duration_ns
            remaining_ns = target_ns - time.monotonic_ns()
            if remaining_ns > 0:
                seconds = remaining_ns / 1_000_000_000.0
                self.wait_calls += 1
                self.wait_seconds += seconds
                time.sleep(seconds)

        def utc_now(self):
            return slots[min(self.grid_index, len(slots) - 1)].close_time

        def monotonic_ns(self):
            return time.monotonic_ns()

        def wait(self, timeout_seconds):
            self.wait_calls += 1
            self.wait_seconds += float(timeout_seconds)
            time.sleep(max(0.0, float(timeout_seconds)))

        def advance_grid(self):
            self.grid_index += 1

    clock = _AcceleratedSourceClock()

    class _BoundedSyntheticStore:
        """Only the external polling leaf is synthetic; no event tape exists."""

        def __init__(self):
            self.preserve_raw_bars = True
            self.cursors = dict.fromkeys(targets, 0)
            self.target_indices = {name: index for index, name in enumerate(targets)}
            self.current_grid_index = None
            self.current_rows: Dict[str, Dict[str, float]] = {}
            self.current_arrivals: Dict[str, int] = {}
            self.poll_calls = 0
            self.events_returned = 0
            self.max_current_rows = 0
            self.max_pending_source_slots = 0
            self.registered = set()
            self.started = 0
            self.subscribed = set()

        def start(self, data=None):
            self.started += 1

        def stop(self, data=None):
            return None

        def get_notifications(self):
            return []

        def register(self, data):
            self.registered.add(getattr(data, "_dataname", None))

        def subscribe(self, dataname):
            self.subscribed.add(dataname)

        def poll_live(self, dataname):
            self.poll_calls += 1
            if dataname not in self.cursors:
                raise BenchmarkFailure("unexpected_feed_requested_by_store")
            grid_index = self.cursors[dataname]
            if grid_index >= total_slots:
                return None
            if grid_index != clock.grid_index:
                raise BenchmarkFailure(
                    "feed_poll_escaped_current_calendar_grid:%s:cursor=%d:clock=%d:rows=%d"
                    % (dataname, grid_index, clock.grid_index, len(self.current_rows))
                )
            if self.current_grid_index != grid_index:
                if (
                    self.current_grid_index is not None
                    and self.current_grid_index + 1 != grid_index
                ):
                    raise BenchmarkFailure("synthetic_store_skipped_a_grid")
                self.current_grid_index = grid_index
                clock.wait_for_grid(grid_index)
                self.current_rows = {}
                self.current_arrivals = {}
            if dataname in self.current_rows:
                raise BenchmarkFailure("synthetic_store_repeated_a_member_grid")

            asset_index = self.target_indices[dataname]
            generated_values = _event_values(asset_index, grid_index)
            values = {field: generated_values[field] for field in source_fields}
            available_monotonic_ns = time.monotonic_ns()
            self.current_rows[dataname] = values
            self.current_arrivals[dataname] = available_monotonic_ns
            self.max_current_rows = max(self.max_current_rows, len(self.current_rows))
            self.max_pending_source_slots = max(
                self.max_pending_source_slots,
                1 if self.current_rows else 0,
            )
            self.cursors[dataname] += 1
            self.events_returned += 1

            slot = slots[grid_index]
            return MappingProxyType(
                {
                    "instrument": "SYN-%s" % dataname,
                    "symbol": dataname,
                    "timestamp": slot.close_time.timestamp(),
                    "datetime": slot.close_time,
                    "bucket_start": slot.bucket_start,
                    "bucket_end": slot.close_time,
                    "available_at": slot.close_time,
                    "trading_day": slot.trading_day,
                    "session_segment": slot.session_segment,
                    "timezone_id": "UTC",
                    "clock_domain_id": "synthetic-source-utc",
                    "connection_generation": "synthetic-generation-1",
                    "bar_sequence": grid_index + 1,
                    "bar_id": "%s:%d" % (dataname, grid_index),
                    **values,
                    "present": True,
                    "complete": True,
                    "quality": "GOOD",
                    "quality_flags": (),
                    "source": "iteration50-bounded-synthetic-poll-live",
                }
            )

        def finish_grid(self, grid_index):
            if self.current_grid_index != grid_index:
                raise BenchmarkFailure("strategy_completed_a_different_store_grid")
            if len(self.current_rows) != ASSET_COUNT or len(self.current_arrivals) != ASSET_COUNT:
                raise BenchmarkFailure("incomplete_synthetic_source_grid")
            self.current_rows = {}
            self.current_arrivals = {}
            self.current_grid_index = None
            if grid_index == total_slots - 1:
                clock.wait_until_duration()

    store = _BoundedSyntheticStore()
    window_bars = _window_bars_for(args.factors, warmup_bars)
    cohort = LiveBarCohort(
        "cohort-iteration50-%s" % args.mode,
        calendar,
        max_pending_slots=1,
        max_window_bars=window_bars,
        wait_timeout_ns=5_000_000_000,
    )
    feed_mapping = {}
    cerebro = bt.Cerebro(
        stdstats=False,
        exactbars=1,
        preload=False,
        runonce=False,
        oldsync=False,
        cheat_on_open=False,
    )
    for target in targets:
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            store=store,
            backfill_start=False,
            cohort_source_mode=True,
            historical_bars=(),
            live_bars=(),
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            dispatch_ticks=False,
            dispatch_orderbooks=False,
            dispatch_bars=False,
        )
        feed_lines = getattr(feed, "lines", None)
        alias_getter = getattr(type(feed_lines), "getlinealiases", None)
        feed_aliases = set(alias_getter()) if callable(alias_getter) else set()
        missing_lines = tuple(field for field in source_fields if field not in feed_aliases)
        if missing_lines:
            raise BenchmarkFailure(
                "selected_profile_requires_unavailable_btapifeed_lines:%s" % ",".join(missing_lines)
            )
        cerebro.adddata(feed, name=target)
        feed_mapping[target] = feed
        cohort.register_member(
            "member-%s" % target.lower(),
            feed,
            instrument="SYN-%s" % target,
            source_ref="synthetic-feed-%s" % target,
            line_fields=source_fields,
            raw_fields=source_fields,
            numeric_fields=source_fields,
        )

    specs = {
        FACTOR_NAMES[alpha_id]: FactorSpec(
            name=FACTOR_NAMES[alpha_id],
            indicator=get_alpha(alpha_id),
            panel_line="factor",
            params={},
            field_bindings={field: "feed:target:%s" % field for field in FACTOR_FIELDS[alpha_id]},
            mode=args.mode,
        )
        for alpha_id in factor_ids
    }
    plan = LiveFactorPlan(
        plan_id="iteration50-%s-%s" % (args.factors, args.mode),
        targets=targets,
        groups=dict.fromkeys(targets, "all-assets"),
        factors=specs,
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=warmup_bars,
        max_pending_slots=1,
        max_window_bars=window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_live_bar_age_seconds=1.0,
        max_future_skew_seconds=0.0,
        allow_history_prewarm=False,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)

    output_path = Path(args.output).expanduser().resolve(strict=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    database_path = output_path.with_name(output_path.stem + ".decisions.sqlite3")
    run_id = uuid.uuid4().hex
    context: Dict[str, Any] = {}
    strategy_params = {
        "plan": plan,
        "cohort": cohort,
        "clock": clock,
        "store": store,
        "run_id": run_id,
        "mode": args.mode,
        "warmup_bars": warmup_bars,
        "evaluation_grids": grids,
        "database_path": str(database_path),
        "context": context,
        "slot_count": total_slots,
        "targets": targets,
        "factor_ids": factor_ids,
        "factor_names": factor_names,
        "factor_profile": args.factors,
        "source_fields": source_fields,
        "strategy_scope": "live-longstream-%s-%s" % (args.factors, args.mode),
        "duration_seconds": args.duration_seconds,
        "operator_reason_ready": float(OperatorReason.READY),
        "rss_window": min(1000, max(1, grids // 10)),
        "rss_sampler": rss_sampler,
    }

    class _OrdinaryLiveFactorStrategy(bt.Strategy):
        params = tuple((name, value) for name, value in strategy_params.items())

        def __init__(self):
            self.p.context["strategy"] = self
            self.live_factors = LiveFactorSet.bind(
                self.p.plan,
                {data._name: data for data in self.datas},
                cohort=self.p.cohort,
            )
            self._factor_roots = {
                name: self.live_factors.factor_instances[name]["all-assets"]
                for name in self.p.factor_names
            }
            self._factor = self._factor_roots.get(FACTOR_NAME)
            self._feeds = {data._name: data for data in self.datas}
            self._journal = ExecutionDecisionJournal(
                self.p.database_path,
                max_decision_records=self.p.evaluation_grids,
                settlement_decision_reserve_records=SETTLEMENT_JOURNAL_RECORD_RESERVE,
                max_decision_bytes=BASE_JOURNAL_BYTE_BUDGET,
                settlement_decision_reserve_bytes=SETTLEMENT_JOURNAL_BYTE_RESERVE,
                max_pending_intents=1,
                max_pending_callbacks=1,
                max_payload_bytes=65536,
            )
            self._journal_capacity_before = self._capacity_snapshot()
            if self._journal_capacity_before["base_record_count"] != 0:
                raise BenchmarkFailure("fresh_decision_journal_is_not_empty")
            if self._journal_capacity_before["base_record_limit"] < self.p.evaluation_grids:
                raise BenchmarkFailure("decision_journal_record_budget_below_planned_rows")
            self._estimated_base_payload_budget = (
                self.p.evaluation_grids * JOURNAL_ESTIMATED_ROW_BYTE_BUDGET
            )
            if self._estimated_base_payload_budget > BASE_JOURNAL_BYTE_BUDGET:
                raise BenchmarkFailure("decision_journal_byte_budget_below_prelaunch_estimate")
            self._reference_oracle = _StreamingFactorOracle(self.p.targets, self.p.factor_ids)
            self._factor_stats = {
                name: {
                    "comparisons": 0,
                    "finite_factor_values": 0,
                    "first_value": None,
                    "distinct_value_seen": False,
                    "factor_min": None,
                    "factor_max": None,
                    "output_reason_failures": 0,
                    "output_unavailable_grids": 0,
                }
                for name in self.p.factor_names
            }
            self._oracle_open = deque(maxlen=CORRELATION_WINDOW)
            self._oracle_volume = deque(maxlen=CORRELATION_WINDOW)
            self._latencies = _LatencyHistogram()
            self._arrival_spread_latencies = _LatencyHistogram()
            self._last_member_to_strategy_latencies = _LatencyHistogram()
            self._last_member_to_factor_snapshot_latencies = _LatencyHistogram()
            self._factor_snapshot_to_journal_latencies = _LatencyHistogram()
            self._journal_write_latencies = _LatencyHistogram()
            self._source_clock_availability_lag = _LatencyHistogram()
            self._rss_window = self.p.rss_window
            self._first_rss = []
            self._last_rss = []
            self._line_snapshot_first = None
            self._line_snapshot_last = None
            self._receipt_count_first = None
            self._comparisons = 0
            self._finite_factor_values = 0
            self._first_finite_factor = None
            self._distinct_factor_value = False
            self._factor_min = None
            self._factor_max = None
            self._open_rank_changes = 0
            self._volume_rank_changes = 0
            self._previous_open_rank = None
            self._previous_volume_rank = None
            self._strategy_next_calls = 0
            self._warmup_complete_grids = 0
            self._noop_rows = 0
            self._new_grid_rows = 0
            self._rank_reason_failures = 0
            self._correlation_reason_failures = 0
            self._factor_values_unavailable = 0
            self._decision_rows_not_noop = 0

        def _capacity_snapshot(self):
            snapshot = self._journal.decision_capacity_snapshot()
            return {
                "base_record_count": snapshot.base_record_count,
                "base_record_limit": snapshot.base_record_limit,
                "base_payload_bytes": snapshot.base_payload_bytes,
                "base_payload_byte_limit": snapshot.base_payload_byte_limit,
                "settlement_record_count": snapshot.settlement_record_count,
                "settlement_record_limit": snapshot.settlement_record_limit,
                "settlement_payload_bytes": snapshot.settlement_payload_bytes,
                "settlement_payload_byte_limit": snapshot.settlement_payload_byte_limit,
                "database_bytes": snapshot.database_bytes,
                "wal_bytes": snapshot.wal_bytes,
                "physical_bytes": snapshot.physical_bytes,
            }

        def _rank_line(self, node, feed):
            return float(node.outputs[feed].value[0])

        def _correlation_line(self, node):
            return float(node.lines.value[0])

        def _line_capacity_snapshot(self):
            from backtrader.linebuffer import LineBuffer

            found = {}
            found_values = {}
            found_reasons = {}
            stack = [self, *self.datas]
            factor_instance_root_count = 0
            for instances_by_target in self.live_factors.factor_instances.values():
                stack.extend(instances_by_target.values())
                factor_instance_root_count += len(instances_by_target)
            visited = set()
            while stack:
                owner = stack.pop()
                if id(owner) in visited:
                    continue
                visited.add(id(owner))

                lines = getattr(owner, "lines", None)
                line_values = getattr(lines, "lines", ())
                aliases = ()
                getter = getattr(type(lines), "getlinealiases", None)
                if callable(getter):
                    aliases = getter()
                for index, line in enumerate(line_values):
                    if isinstance(line, LineBuffer):
                        found[id(line)] = line
                        alias = aliases[index] if index < len(aliases) else ""
                        if alias == "value":
                            found_values[id(line)] = line
                        elif alias == "reason":
                            found_reasons[id(line)] = line

                # Cross-sectional rank panels expose one real line pair per
                # feed through outputs rather than the owner's own Lines list.
                outputs = getattr(owner, "outputs", None)
                if isinstance(outputs, Mapping):
                    for output in outputs.values():
                        value_line = getattr(output, "value", None)
                        reason_line = getattr(output, "reason", None)
                        if isinstance(value_line, LineBuffer):
                            found[id(value_line)] = value_line
                            found_values[id(value_line)] = value_line
                        if isinstance(reason_line, LineBuffer):
                            found[id(reason_line)] = reason_line
                            found_reasons[id(reason_line)] = reason_line
                for child_groups in getattr(owner, "_lineiterators", {}).values():
                    for child in child_groups:
                        stack.append(child)
            lengths = [len(line.array) for line in found.values()]
            capacities = [int(getattr(line, "maxlen", 0) or 0) for line in found.values()]
            value_lines = tuple(found_values.values())
            reason_lines = tuple(found_reasons.values())
            value_capacities = [int(getattr(line, "maxlen", 0) or 0) for line in value_lines]
            reason_capacities = [int(getattr(line, "maxlen", 0) or 0) for line in reason_lines]
            return {
                "owner_count": len(visited),
                "factor_instance_root_count": factor_instance_root_count,
                "line_count": len(found),
                "retained_line_values": sum(lengths),
                "max_line_length": max(lengths, default=0),
                "max_line_capacity": max(capacities, default=0),
                "line_capacity_sum": sum(capacities),
                "line_capacity_filled_count": sum(
                    1
                    for line, capacity in zip(found.values(), capacities)
                    if capacity > 0 and len(line.array) >= capacity
                ),
                "line_capacity_fillable_count": sum(1 for capacity in capacities if capacity > 0),
                "line_buffers_full": bool(capacities)
                and all(
                    capacity <= 0 or len(line.array) >= capacity
                    for line, capacity in zip(found.values(), capacities)
                ),
                "value_line_count": len(value_lines),
                "reason_line_count": len(reason_lines),
                "retained_value_line_values": sum(len(line.array) for line in value_lines),
                "retained_reason_line_values": sum(len(line.array) for line in reason_lines),
                "value_capacity_sum": sum(value_capacities),
                "reason_capacity_sum": sum(reason_capacities),
            }

        def _node_reason(self, node, feed=None):
            if feed is not None and hasattr(node, "outputs"):
                return float(node.outputs[feed].reason[0])
            lines = getattr(node, "lines", None)
            reason = getattr(lines, "reason", None)
            return None if reason is None else float(reason[0])

        def _oracle_grid(self, batch, snapshot, *, evaluation_grid):
            rows = self.p.store.current_rows
            if len(rows) != ASSET_COUNT:
                raise BenchmarkFailure("oracle_did_not_receive_the_complete_source_grid")
            ordered_rows = tuple(rows[target] for target in self.p.targets)
            expected_factors = self._reference_oracle.update(rows)
            if evaluation_grid:
                for factor_name in self.p.factor_names:
                    expected = expected_factors.get(factor_name, {})
                    actual_result = snapshot.factors[factor_name]
                    stats = self._factor_stats[factor_name]
                    for target in self.p.targets:
                        output = actual_result.values[target]
                        if output.status.value != "OUTPUT_AVAILABLE" or not math.isfinite(
                            float(output.value)
                        ):
                            stats["output_unavailable_grids"] += 1
                            raise BenchmarkFailure(
                                "factor_%s_output_missing_or_nonfinite:%s" % (factor_name, target)
                            )
                        if output.reason not in (None, ""):
                            stats["output_reason_failures"] += 1
                            raise BenchmarkFailure(
                                "factor_%s_output_has_reason:%s" % (factor_name, target)
                            )
                        expected_value = expected.get(target)
                        if expected_value is None or not math.isfinite(float(expected_value)):
                            raise BenchmarkFailure(
                                "independent_oracle_%s_output_unavailable:%s"
                                % (factor_name, target)
                            )
                        actual_value = float(output.value)
                        if not _within_tolerance(actual_value, float(expected_value)):
                            raise BenchmarkFailure(
                                "factor_%s_differs_from_independent_oracle:%s"
                                % (factor_name, target)
                            )
                        stats["comparisons"] += 1
                        stats["finite_factor_values"] += 1
                        if stats["first_value"] is None:
                            stats["first_value"] = actual_value
                        elif actual_value != stats["first_value"]:
                            stats["distinct_value_seen"] = True
                        stats["factor_min"] = (
                            actual_value
                            if stats["factor_min"] is None
                            else min(stats["factor_min"], actual_value)
                        )
                        stats["factor_max"] = (
                            actual_value
                            if stats["factor_max"] is None
                            else max(stats["factor_max"], actual_value)
                        )
            if self._factor is None:
                return expected_factors.get(FACTOR_NAME)
            open_rank = _average_ranks(tuple(row["open"] for row in ordered_rows))
            volume_rank = _average_ranks(tuple(row["volume"] for row in ordered_rows))
            if open_rank != self._previous_open_rank:
                self._open_rank_changes += 1
            if volume_rank != self._previous_volume_rank:
                self._volume_rank_changes += 1
            self._previous_open_rank = open_rank
            self._previous_volume_rank = volume_rank
            self._oracle_open.append(open_rank)
            self._oracle_volume.append(volume_rank)

            open_node = self._factor._nodes["rank_open"]
            volume_node = self._factor._nodes["rank_volume"]
            for index, target in enumerate(self.p.targets):
                feed = self._feeds[target]
                actual_open_rank = self._rank_line(open_node, feed)
                actual_volume_rank = self._rank_line(volume_node, feed)
                if not _within_tolerance(actual_open_rank, open_rank[index]):
                    raise BenchmarkFailure("open_rank_differs_from_independent_oracle")
                if not _within_tolerance(actual_volume_rank, volume_rank[index]):
                    raise BenchmarkFailure("volume_rank_differs_from_independent_oracle")
                expected_ready = self.p.operator_reason_ready
                if self._node_reason(open_node, feed) != expected_ready:
                    self._rank_reason_failures += 1
                if self._node_reason(volume_node, feed) != expected_ready:
                    self._rank_reason_failures += 1
                self._comparisons += 2

            if len(self._oracle_open) < CORRELATION_WINDOW:
                return expected_factors.get(FACTOR_NAME)

            actual_correlation_nodes = tuple(
                self._factor._nodes["correlation10_%d" % index] for index in range(ASSET_COUNT)
            )
            expected_factor_values = []
            factor_result = snapshot.factors[FACTOR_NAME]
            for index, target in enumerate(self.p.targets):
                expected_corr = _pearson(
                    tuple(grid[index] for grid in self._oracle_open),
                    tuple(grid[index] for grid in self._oracle_volume),
                )
                expected_factor = -expected_corr
                actual_corr = self._correlation_line(actual_correlation_nodes[index])
                actual_factor = float(factor_result.values[target].value)
                if not _within_tolerance(actual_corr, expected_corr):
                    raise BenchmarkFailure("correlation10_differs_from_independent_oracle")
                if not _within_tolerance(actual_factor, expected_factor):
                    raise BenchmarkFailure("alpha003_differs_from_independent_oracle")
                if self._node_reason(actual_correlation_nodes[index]) != expected_ready:
                    self._correlation_reason_failures += 1
                self._comparisons += 2
                expected_factor_values.append(actual_factor)
                if evaluation_grid:
                    self._finite_factor_values += 1
                    if self._first_finite_factor is None:
                        self._first_finite_factor = actual_factor
                    elif actual_factor != self._first_finite_factor:
                        self._distinct_factor_value = True
                    self._factor_min = (
                        actual_factor
                        if self._factor_min is None
                        else min(self._factor_min, actual_factor)
                    )
                    self._factor_max = (
                        actual_factor
                        if self._factor_max is None
                        else max(self._factor_max, actual_factor)
                    )
            return expected_factor_values

        def prenext(self):
            # The ordinary Backtrader lifecycle calls prenext while the live
            # Alpha003 lookback warms.  Every complete source batch must still
            # be consumed and the causal benchmark clock advanced exactly once.
            self.next()

        def next(self):
            strategy_entry_ns = time.monotonic_ns()
            self._strategy_next_calls += 1
            batch = self.p.cohort.current_batch()
            if batch is None or batch.slot_index != self._strategy_next_calls - 1:
                raise BenchmarkFailure("ordinary_strategy_did_not_receive_each_grid_once")
            snapshot = self.live_factors.snapshot()
            factor_snapshot_ns = time.monotonic_ns()
            if not snapshot.batch_complete or snapshot.close_time != batch.close_time:
                raise BenchmarkFailure("live_factor_snapshot_is_not_bound_to_current_batch")

            if batch.slot_index < self.p.warmup_bars:
                self._warmup_complete_grids += 1
                # Warm-up nodes are expected to be live even though the factor
                # window itself is not yet available.
                self._oracle_grid(batch, snapshot, evaluation_grid=False)
                self.p.store.finish_grid(batch.slot_index)
                self.p.clock.advance_grid()
                return

            evaluation_index = batch.slot_index - self.p.warmup_bars
            if evaluation_index >= self.p.evaluation_grids:
                raise BenchmarkFailure("ordinary_strategy_observed_unplanned_grid")
            if snapshot.readiness.value != "LIVE_READY":
                raise BenchmarkFailure("live_factor_set_never_reached_live_ready")
            factor_results = {name: snapshot.factors[name] for name in self.p.factor_names}
            output_values = tuple(
                output
                for factor_result in factor_results.values()
                for output in (factor_result.values[target] for target in self.p.targets)
            )
            inputs_complete = all(
                output.status.value == "OUTPUT_AVAILABLE" and math.isfinite(float(output.value))
                for output in output_values
            )
            if not inputs_complete:
                self._factor_values_unavailable += 1
                raise BenchmarkFailure("one_or_more_factor_outputs_missing_after_warmup")
            if batch.available_at < batch.close_time:
                raise BenchmarkFailure("source_availability_precedes_bar_close")
            arrivals = self.p.store.current_arrivals
            if len(arrivals) != ASSET_COUNT:
                raise BenchmarkFailure("last_member_source_availability_is_unobserved")
            source_available_ns = max(arrivals.values())
            first_source_available_ns = min(arrivals.values())
            self._arrival_spread_latencies.add(
                (source_available_ns - first_source_available_ns) / 1_000_000.0
            )
            self._last_member_to_strategy_latencies.add(
                (strategy_entry_ns - source_available_ns) / 1_000_000.0
            )
            self._last_member_to_factor_snapshot_latencies.add(
                (factor_snapshot_ns - source_available_ns) / 1_000_000.0
            )
            availability_lag_ms = (batch.available_at - batch.close_time).total_seconds() * 1000.0
            if availability_lag_ms < 0.0:
                raise BenchmarkFailure("source_availability_precedes_bar_close")
            self._source_clock_availability_lag.add(availability_lag_ms)
            start_ns = source_available_ns
            key = ExecutionDecisionKey(
                account_scope="synthetic-no-account",
                strategy_scope=self.p.strategy_scope,
                logical_run_id=self.p.run_id,
                cohort_id=self.p.cohort.cohort_id,
                close_time=batch.close_time.isoformat().replace("+00:00", "Z"),
                decision_kind="benchmark-noop",
            )
            journal_start_ns = time.monotonic_ns()
            durable = self._journal.record_grid_decision(
                key,
                {
                    "benchmark": "iteration50-live-factor-longstream",
                    "factor_profile": self.p.factor_profile,
                    "factors": list(self.p.factor_names),
                    "mode": self.p.mode,
                    "finite_target_count": ASSET_COUNT,
                    "sample_factor_values": {
                        name: float(factor_results[name].values[self.p.targets[0]].value)
                        for name in self.p.factor_names
                    },
                    "no_op_reason": "benchmark_only_no_execution_route",
                },
                intent_keys=(),
                epoch_id=str(batch.epoch_id),
                batch_id=batch.batch_id,
                eligible=True,
                complete=snapshot.batch_complete,
                live_ready=True,
                inputs_complete=inputs_complete,
                max_order_intents_per_run=0,
                expected_run_order_intents_used=0,
                remaining_exit_intent_reserve=0,
            )
            end_ns = time.monotonic_ns()
            self._journal_write_latencies.add((end_ns - journal_start_ns) / 1_000_000.0)
            self._factor_snapshot_to_journal_latencies.add(
                (end_ns - factor_snapshot_ns) / 1_000_000.0
            )
            self._latencies.add((end_ns - start_ns) / 1_000_000.0)
            if not durable.eligible or durable.decision is None:
                raise BenchmarkFailure("execution_journal_did_not_persist_grid_decision")
            if not durable.decision.is_noop:
                self._decision_rows_not_noop += 1
                raise BenchmarkFailure("benchmark_journal_row_contains_order_intents")
            if not durable.is_new_grid:
                raise BenchmarkFailure("execution_journal_did_not_create_one_new_grid_row")
            self._noop_rows += 1
            self._new_grid_rows += 1

            self._oracle_grid(batch, snapshot, evaluation_grid=True)
            rss = self.p.rss_sampler.sample_bytes()
            if evaluation_index < self._rss_window:
                self._first_rss.append(rss)
            if evaluation_index >= self.p.evaluation_grids - self._rss_window:
                self._last_rss.append(rss)
            if evaluation_index == 0:
                self._line_snapshot_first = self._line_capacity_snapshot()
                self._receipt_count_first = sum(
                    len(receipts) for receipts in self.p.cohort._window_receipts.values()
                )
            if evaluation_index == self.p.evaluation_grids - 1:
                self._line_snapshot_last = self._line_capacity_snapshot()

            self.p.store.finish_grid(batch.slot_index)
            self.p.clock.advance_grid()

        def benchmark_result(self):
            cursor = self._journal.grid_cursor(
                "synthetic-no-account",
                self.p.strategy_scope,
                self.p.cohort.cohort_id,
            )
            rss_summary = _rss_window_summary(self._first_rss, self._last_rss)
            first_line = self._line_snapshot_first or {}
            last_line = self._line_snapshot_last or {}
            diag_nodes = []
            stack = list(self._factor_roots.values())
            visited = set()
            while stack:
                owner = stack.pop()
                if id(owner) in visited:
                    continue
                visited.add(id(owner))
                diagnostics = getattr(owner, "lifecycle_diagnostics", None)
                if (
                    isinstance(diagnostics, Mapping)
                    and diagnostics.get("diagnostic_kind") == "bounded_live_samples"
                ):
                    diag_nodes.append(diagnostics)
                for children in getattr(owner, "_lineiterators", {}).values():
                    stack.extend(children)
            diag_capacities = [int(item["sample_limit"]) for item in diag_nodes]
            diagnostic_bounded = bool(diag_nodes) and all(
                len(item["call_times"]) <= int(item["sample_limit"])
                and len(item["once_ranges"]) <= int(item["sample_limit"])
                for item in diag_nodes
            )
            per_factor = {
                name: {
                    "comparisons": stats["comparisons"],
                    "finite_factor_values": stats["finite_factor_values"],
                    "distinct_finite_factor_values": (
                        2
                        if stats["distinct_value_seen"]
                        else (1 if stats["finite_factor_values"] else 0)
                    ),
                    "factor_min": stats["factor_min"],
                    "factor_max": stats["factor_max"],
                    "output_reason_failures": stats["output_reason_failures"],
                    "output_unavailable_grids": stats["output_unavailable_grids"],
                }
                for name, stats in self._factor_stats.items()
            }
            capacity_after = self._capacity_snapshot()
            factor_stats = tuple(self._factor_stats.values())
            all_factor_values = sum(stats["finite_factor_values"] for stats in factor_stats)
            all_factor_comparisons = sum(stats["comparisons"] for stats in factor_stats)
            all_factors_distinct = all(stats["distinct_value_seen"] for stats in factor_stats)
            return {
                "latency": {
                    "start": "max synthetic Store.poll_live monotonic timestamp for the complete member grid",
                    "end": "record_grid_decision return, before any RPC or order route",
                    "sample_count": self._latencies.count,
                    "p99_upper_bound_ms": self._latencies.p99_upper_bound_ms,
                    "p99_bin_resolution_ms": LATENCY_HISTOGRAM_RESOLUTION_MS,
                    "max_ms": self._latencies.maximum_ms,
                    "p99_limit_ms": LATENCY_P99_LIMIT_MS,
                    "max_limit_ms": LATENCY_MAX_LIMIT_MS,
                    "clock_domains_are_separate": True,
                    "source_clock_bar_close_to_available": {
                        "clock_domain_id": "synthetic-source-utc",
                        **self._source_clock_availability_lag.report(),
                    },
                    "monotonic_phases": {
                        "first_member_available_to_last_member_available": self._arrival_spread_latencies.report(),
                        "last_member_available_to_strategy_next_entry": self._last_member_to_strategy_latencies.report(),
                        "last_member_available_to_factor_snapshot": self._last_member_to_factor_snapshot_latencies.report(),
                        "factor_snapshot_to_journal_return": self._factor_snapshot_to_journal_latencies.report(),
                        "record_grid_decision_call": self._journal_write_latencies.report(),
                    },
                    "rpc": {"called": False, "sample_count": 0, "latency_ms": None},
                },
                "memory": {
                    "rss_sampling_method": self.p.rss_sampler.method,
                    "rss_sampling_scope": "benchmark_process",
                    "process_tree_peak_claimed": False,
                    "rss_samples_may_miss_transient_peaks": True,
                    "rss_sampling_cadence": "one current-RSS sample after each evaluated grid's journal and oracle work",
                    "equal_window_samples": self._rss_window,
                    "first_window_sample_count": len(self._first_rss),
                    "last_window_sample_count": len(self._last_rss),
                    **rss_summary,
                },
                "capacities": {
                    "configured_pending_slots": self.p.cohort.max_pending_slots,
                    "configured_pending_bars": self.p.cohort.max_pending_bars,
                    "configured_window_bars_per_member": self.p.cohort.max_window_bars,
                    "cohort_pending_slots_at_end": len(self.p.cohort._pending),
                    "retained_receipts_at_end": sum(
                        len(receipts) for receipts in self.p.cohort._window_receipts.values()
                    ),
                    "receipt_window_full_at_last_sample": (
                        sum(len(receipts) for receipts in self.p.cohort._window_receipts.values())
                        == ASSET_COUNT * self.p.cohort.max_window_bars
                    ),
                    "retained_receipts_at_first_sample": self._receipt_count_first,
                    "receipt_window_full_at_first_sample": (
                        self._receipt_count_first == ASSET_COUNT * self.p.cohort.max_window_bars
                    ),
                    "max_pending_source_slots": self.p.store.max_pending_source_slots,
                    "source_rows_retained_max": self.p.store.max_current_rows,
                    "source_rows_retained_at_end": len(self.p.store.current_rows),
                    "line_capacity_first": first_line,
                    "line_capacity_last": last_line,
                    "line_buffers_full_at_first_sample": first_line.get("line_buffers_full")
                    is True,
                    "line_buffers_full_at_last_sample": last_line.get("line_buffers_full") is True,
                    "line_capacity_grew_after_warmup": any(
                        last_line.get(name, 0) > first_line.get(name, 0)
                        for name in (
                            "max_line_capacity",
                            "max_line_length",
                            "line_capacity_sum",
                            "retained_line_values",
                            "value_capacity_sum",
                            "reason_capacity_sum",
                            "retained_value_line_values",
                            "retained_reason_line_values",
                        )
                    ),
                    "factor_diagnostic_node_count": len(diag_nodes),
                    "factor_diagnostic_sample_capacity_max": max(diag_capacities, default=0),
                    "factor_diagnostic_samples_retained_max": max(
                        (len(item["call_times"]) for item in diag_nodes), default=0
                    ),
                    "diagnostics_bounded": diagnostic_bounded,
                },
                "oracle": {
                    "algorithm": "bounded scalar streaming references; finite average ranks, centered Pearson, rolling sums/std, and direct scalar Alpha101 formulas",
                    "formulas": dict.fromkeys(
                        self.p.factor_names, "independent scalar formula oracle"
                    ),
                    "tolerance": "abs(actual-reference) <= 1e-12 + 1e-10*abs(reference)",
                    "comparisons": all_factor_comparisons,
                    "finite_factor_values": all_factor_values,
                    "distinct_finite_factor_values": (
                        2 if all_factors_distinct else (1 if all_factor_values else 0)
                    ),
                    "factor_min": min(
                        (
                            stats["factor_min"]
                            for stats in factor_stats
                            if stats["factor_min"] is not None
                        ),
                        default=None,
                    ),
                    "factor_max": max(
                        (
                            stats["factor_max"]
                            for stats in factor_stats
                            if stats["factor_max"] is not None
                        ),
                        default=None,
                    ),
                    "open_rank_changed_grids": self._open_rank_changes,
                    "volume_rank_changed_grids": self._volume_rank_changes,
                    "rank_reason_failures": self._rank_reason_failures,
                    "correlation_reason_failures": self._correlation_reason_failures,
                    "factor_output_unavailable_grids": self._factor_values_unavailable,
                    "per_factor": per_factor,
                },
                "runtime": {
                    "ordinary_strategy_class": "Backtrader Strategy subclass",
                    "strategy_next_calls": self._strategy_next_calls,
                    "warmup_complete_grids": self._warmup_complete_grids,
                    "broker_order_calls": 0,
                    "broker_cancel_calls": 0,
                    "execution_intents": 0,
                    "source_wait_calls": self.p.clock.wait_calls,
                    "source_wait_seconds": self.p.clock.wait_seconds,
                    "source_gap_count": len(self.p.cohort.gaps),
                    "cohort_frozen": self.p.cohort.frozen,
                    "duration_requested_seconds": self.p.duration_seconds,
                    "duration_pacing_kind": "monotonic pacing across finite synthetic source calendar",
                    "duration_seconds_met": (
                        self.p.duration_seconds == 0
                        or (time.monotonic_ns() - self.p.clock.pacing_start_ns)
                        >= self.p.clock.duration_ns
                    ),
                },
                "durable_noop_journal": {
                    "database_path": self.p.database_path,
                    "logical_run_id": self.p.run_id,
                    "noop_rows": self._noop_rows,
                    "new_grid_rows": self._new_grid_rows,
                    "intent_count": self._journal.run_order_count(
                        "synthetic-no-account",
                        self.p.strategy_scope,
                        self.p.run_id,
                    ),
                    "cursor_ordinal": None if cursor is None else cursor.ordinal,
                    "cursor_close_time": None if cursor is None else cursor.close_time,
                    "durable_api": "ExecutionDecisionJournal.record_grid_decision",
                    "external_rpc_or_order_route": False,
                    "configured_capacity_before_launch": {
                        "base_records": self.p.evaluation_grids,
                        "base_payload_bytes": BASE_JOURNAL_BYTE_BUDGET,
                        "prelaunch_estimated_base_payload_bytes": self._estimated_base_payload_budget,
                        "estimated_bytes_per_noop_row": JOURNAL_ESTIMATED_ROW_BYTE_BUDGET,
                        "settlement_reserve_records": SETTLEMENT_JOURNAL_RECORD_RESERVE,
                        "settlement_reserve_payload_bytes": SETTLEMENT_JOURNAL_BYTE_RESERVE,
                        "max_payload_bytes_per_decision": 65536,
                        "physical_db_wal_capacity_enforced": False,
                        "physical_db_wal_note": "SQLite and WAL sizes are measured; journal limits enforce canonical decision payload bytes and record counts.",
                    },
                    "capacity_before": self._journal_capacity_before,
                    "capacity_after": capacity_after,
                },
                "soak_coverage": {
                    "ac50_27b_ready": False,
                    "ordinary_broker_lifecycle_exercised": False,
                    "idle_order_event_path_exercised": False,
                    "failure_recovery_path_exercised": False,
                    "reason": "the current bounded synthetic benchmark has no Broker order lifecycle/fault-idle fixture",
                },
            }

    cerebro.addstrategy(_OrdinaryLiveFactorStrategy, **strategy_params)
    return (
        cerebro,
        cohort,
        calendar,
        clock,
        store,
        run_id,
        database_path,
        context,
        feed_mapping,
    )


def _build_report(args: argparse.Namespace, grids: int, warmup_bars: int, profile: str):
    _fresh_output_paths(args.output)
    selected_root = _sanitize_import_path(
        None if args.package_root is None else Path(args.package_root)
    )
    rss_sampler = _create_rss_sampler()
    started_ns = time.monotonic_ns()
    (
        cerebro,
        cohort,
        calendar,
        clock,
        store,
        run_id,
        database_path,
        context,
        feed_mapping,
    ) = _make_runtime(args, grids, warmup_bars, rss_sampler)
    source_fields = _source_fields_for(args.factors)
    backtrader_module = sys.modules.get("backtrader")
    backtrader_version = getattr(backtrader_module, "__version__", None)
    report: Dict[str, Any] = {
        "schema_version": 1,
        "benchmark": "iteration50-live-factor-longstream",
        "status": "RUNNING",
        "evidence_level": "COMPOSITION_SYNTHETIC_SOURCE_STREAM_ONLY",
        "formal_acceptance_claimed": False,
        "account_or_execution_claimed": False,
        "profile": {
            "kind": profile,
            "factor_profile": args.factors,
            "factor_ids": list(FACTOR_IDS[args.factors]),
            "factor_names": [FACTOR_NAMES[alpha_id] for alpha_id in FACTOR_IDS[args.factors]],
            "mode": args.mode,
            "target_count": ASSET_COUNT,
            "evaluation_grids": grids,
            "warmup_bars": warmup_bars,
            "total_grid_slots": warmup_bars + grids,
            "calendar_slot_count": len(calendar.slots),
            "calendar_slot_limit": MAX_CALENDAR_SLOTS,
            "calendar_frequency": calendar.frequency,
            "calendar_frequency_seconds": calendar.frequency_seconds,
            "line_window_bars": _window_bars_for(args.factors, warmup_bars),
            "steady_capacity_sample_definition": (
                "first evaluation grid after all warmup slots and last evaluation grid"
            ),
            "rss_window_sample_definition": (
                "first and last min(1000, max(1, evaluation_grids // 10)) evaluation grids"
            ),
            "minimum_wall_clock_duration_seconds": args.duration_seconds,
            "finite_calendar": True,
            "source_schedule": "finite synthetic UTC calendar; optional monotonic wall-clock pacing is a local duration measurement only",
            "soak_fault_idle_order_coverage_complete": False,
        },
        "environment": {
            **_runtime_facts(),
            "backtrader_version": backtrader_version,
            "source_revision": os.environ.get("BT_BENCHMARK_SOURCE_REVISION"),
        },
        "provenance": {
            "actual_argv": list(sys.argv),
            "script_path": str(Path(__file__).resolve()),
            "script_sha256": _sha256_file(Path(__file__).resolve()),
            "input_generation_hash_kind": "sha256_of_normalized_calendar_row_generator_source_and_profile_input_contract",
            "input_generation_sha256": _source_generator_sha256(args.factors),
            "calendar_and_event_fixture": "finite deterministic 20-target local synthetic source",
        },
        "source": {
            "provider_leaf": "bounded synthetic Store.poll_live",
            "event_generation": "one deterministic member/grid mapping per poll call",
            "raw_numeric_fields": list(source_fields),
            "factor_extra_line_fields": [
                field for field in source_fields if field not in STANDARD_SOURCE_LINE_FIELDS
            ],
            "line_fields_registered_per_member": list(source_fields),
            "categorical_codes_are_fixture_local": args.factors == "representative-six",
            "full_event_tape_materialized": False,
            "all_output_arrays_materialized": False,
            "actual_external_provider_calls": 0,
            "account_calls": 0,
            "selected_package_root": str(selected_root),
            "ambient_pythonpath_used_for_backtrader": False,
        },
        "started_monotonic_ns": started_ns,
    }

    strategy = None
    runtime_error = None
    try:
        strategies = cerebro.run()
        if len(strategies) != 1:
            raise BenchmarkFailure("ordinary_cerebro_did_not_return_one_strategy")
        strategy = strategies[0]
        if strategy.__class__.__name__ != "_OrdinaryLiveFactorStrategy":
            raise BenchmarkFailure("unexpected_strategy_runtime_type")
        report.update(strategy.benchmark_result())
        report["source"].update(
            {
                "poll_calls": store.poll_calls,
                "events_returned": store.events_returned,
                "max_current_member_rows": store.max_current_rows,
                "max_pending_source_slots": store.max_pending_source_slots,
                "started_feed_count": store.started,
                "registered_feed_count": len(store.registered),
                "subscribed_feed_count": len(store.subscribed),
            }
        )
        report["elapsed_seconds"] = (time.monotonic_ns() - started_ns) / 1_000_000_000.0
        gates_pass, failures = _check_gates(report)
        report["status"] = "PASS" if gates_pass else "FAIL"
        report["gate_failures"] = list(failures)
        report["diagnostics"] = _cohort_diagnostics(cohort, feed_mapping)
        return report, database_path
    except Exception as error:
        runtime_error = error
        report["status"] = "FAIL"
        report["gate_failures"] = [
            "runtime_exception",
            type(error).__name__,
            str(error)[:240],
        ]
        report["elapsed_seconds"] = (time.monotonic_ns() - started_ns) / 1_000_000_000.0
        report["source"].update(
            {
                "poll_calls": store.poll_calls,
                "events_returned": store.events_returned,
                "max_current_member_rows": store.max_current_rows,
                "max_pending_source_slots": store.max_pending_source_slots,
            }
        )
        if strategy is None:
            strategy = context.get("strategy")
        if strategy is not None:
            report.update(strategy.benchmark_result())
        report["diagnostics"] = _cohort_diagnostics(cohort, feed_mapping)
        return report, database_path
    finally:
        if strategy is not None:
            strategy._journal.close()
        elif context.get("strategy") is not None:
            context["strategy"]._journal.close()
        if runtime_error is not None:
            # Close only the synthetic source leaf.  It owns no provider or
            # native handles, and the journal is closed above when available.
            pass


def _write_report(path_text: str, report: Mapping[str, Any]) -> None:
    path = Path(path_text).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise BenchmarkFailure("output_path_already_exists")
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        raise BenchmarkFailure("output_temporary_path_already_exists")
    payload = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _fresh_output_paths(path_text: str):
    path = Path(path_text).expanduser().resolve(strict=False)
    database_path = path.with_name(path.stem + ".decisions.sqlite3")
    temporary = path.with_suffix(path.suffix + ".tmp")
    if path.exists():
        raise BenchmarkFailure("output_path_already_exists")
    if database_path.exists():
        raise BenchmarkFailure("decision_database_path_already_exists")
    if temporary.exists():
        raise BenchmarkFailure("output_temporary_path_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, database_path


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("native", "build"))
    parser.add_argument(
        "--factors",
        choices=tuple(FACTOR_IDS),
        default="alpha003",
        help="alpha003 or the six representative Alpha101 factors",
    )
    profile = parser.add_mutually_exclusive_group(required=True)
    profile.add_argument("--smoke", action="store_true")
    profile.add_argument("--grids", type=int, help="post-warm-up evaluation grids (1..100000)")
    parser.add_argument("--warmup-bars", type=int, default=None)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=0,
        help="monotonic pacing duration; formal representative-six requires at least 7200",
    )
    parser.add_argument("--output", required=True, help="new JSON result path")
    parser.add_argument(
        "--package-root",
        help="explicit directory containing backtrader/ (source checkout or installed wheel)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        grids, warmup_bars, profile = _validate_cli(args)
        report, database_path = _build_report(args, grids, warmup_bars, profile)
        report["completed_monotonic_ns"] = time.monotonic_ns()
        report["decision_database_path"] = str(database_path)
        _write_report(args.output, report)
        print(json.dumps({"status": report["status"], "output": str(Path(args.output).resolve())}))
        return 0 if report["status"] == "PASS" else 3
    except BenchmarkFailure as error:
        print("benchmark configuration/runtime contract failed: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
