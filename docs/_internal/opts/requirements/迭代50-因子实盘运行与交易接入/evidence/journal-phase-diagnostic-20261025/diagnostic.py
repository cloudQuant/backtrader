#!/usr/bin/env python
"""DIAGNOSTIC_ONLY: phase timings for a bounded 2,048-grid Iteration 50 run.

This calls the frozen benchmark runner unchanged against the pinned 718
installed package. It does not change SQLite WAL/FULL settings, budgets, or
checkpoint behavior. Per-call timing and SQLite wrappers add overhead, so the
result is diagnostic and is not formal performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3 as _sqlite3
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional


RUNNER_SHA256 = "75ca8866f6adb7fb8fc2dd361107d7749170d2cb453ba4cff4754a334567c2db"
JOURNAL_MODULE_SHA256 = "b5b1ba708a4c18c324315a454ae3d3dbc09d43793743cf327a037d5a69266b79"
SOURCE_REVISION = "718ca1dc644321b316c761d361a04497fc2719af"
DEFAULT_PACKAGE_ROOT = Path(
    r"D:\temp\i5051c-20261025-r3\venv\Lib\site-packages"
)
GRID_COUNT = 2048
WARMUP_BARS = 64
PHASES = (
    "begin",
    "commit",
    "rollback",
    "decision_rows",
    "capacity",
    "run_order_budget",
    "cursor_highwater",
    "factor_position",
    "other_sql",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sql_phase(sql: Any) -> str:
    if not isinstance(sql, str):
        return "other_sql"
    upper = sql.lstrip().upper()
    first = upper.split(None, 1)[0] if upper else ""
    if first == "BEGIN":
        return "begin"
    if first == "COMMIT":
        return "commit"
    if first == "ROLLBACK":
        return "rollback"
    if "FACTOR_POSITION" in upper:
        return "factor_position"
    if "EXECUTION_RUN_ORDER" in upper:
        return "run_order_budget"
    if (
        "DURABLE_CAPACITY" in upper
        or "EXECUTION_DECISION_CAPACITY" in upper
        or "EXECUTION_JOURNAL_CAPACITY" in upper
    ):
        return "capacity"
    if "EXECUTION_GRID_CURSOR" in upper or "EXECUTION_GRID_HIGHWATER" in upper:
        return "cursor_highwater"
    if "EXECUTION_DECISIONS" in upper:
        return "decision_rows"
    return "other_sql"


class _CallTimer:
    """Bounded in-memory timing collector; never records SQL text or values."""

    def __init__(self) -> None:
        self.local = threading.local()
        self.calls = []
        self.instrumentation_errors = 0

    def begin(self) -> Dict[str, Any]:
        call = {
            "call_index": len(self.calls) + 1,
            "started_ns": time.perf_counter_ns(),
            "sql_ns": 0,
            "sql_counts": {name: 0 for name in PHASES},
            "phase_ns": {name: 0 for name in PHASES},
            "grid_ordinal": None,
            "outcome": "returned",
        }
        self.local.current = call
        return call

    def observe_sql(self, sql: Any, elapsed_ns: int) -> None:
        call = getattr(self.local, "current", None)
        if call is None:
            return
        phase = _sql_phase(sql)
        call["sql_ns"] += elapsed_ns
        call["sql_counts"][phase] += 1
        call["phase_ns"][phase] += elapsed_ns

    def finish(self, call: Dict[str, Any], result: Any, failed: bool) -> None:
        try:
            call["total_ns"] = time.perf_counter_ns() - call["started_ns"]
            if failed:
                call["outcome"] = "raised"
            else:
                cursor = getattr(result, "cursor", None)
                ordinal = getattr(cursor, "ordinal", None)
                if type(ordinal) is int:
                    call["grid_ordinal"] = ordinal
            self.calls.append(call)
        except BaseException:
            self.instrumentation_errors += 1
        finally:
            self.local.current = None


_TIMER = _CallTimer()


def _timed_sql(sql: Any, delegate: Callable[[], Any]) -> Any:
    if getattr(_TIMER.local, "current", None) is None:
        return delegate()
    started_ns = time.perf_counter_ns()
    try:
        return delegate()
    finally:
        elapsed_ns = time.perf_counter_ns() - started_ns
        try:
            _TIMER.observe_sql(sql, elapsed_ns)
        except BaseException:
            _TIMER.instrumentation_errors += 1


def _install_journal_observer(package_root: Path):
    # Import from the requested installed package before the runner executes.
    sys.path.insert(0, str(package_root))
    module = importlib.import_module("backtrader.stores.execution_decision_journal")
    package_dir = (package_root / "backtrader").resolve()
    module_path = Path(module.__file__).resolve()
    if not module_path.is_relative_to(package_dir):
        raise RuntimeError("journal_module_not_from_requested_package_root")
    if _sha256(module_path) != JOURNAL_MODULE_SHA256:
        raise RuntimeError("installed_journal_module_pin_mismatch")

    class TimedCursor(_sqlite3.Cursor):
        def execute(self, *args, **kwargs):
            sql = args[0] if args else kwargs.get("sql")
            return _timed_sql(
                sql,
                lambda: super(TimedCursor, self).execute(*args, **kwargs),
            )

        def executemany(self, *args, **kwargs):
            sql = args[0] if args else kwargs.get("sql")
            return _timed_sql(
                sql,
                lambda: super(TimedCursor, self).executemany(*args, **kwargs),
            )

    class TimedConnection(_sqlite3.Connection):
        def cursor(self, factory=None):
            selected_factory = TimedCursor if factory is None else factory
            return super(TimedConnection, self).cursor(factory=selected_factory)

        def execute(self, *args, **kwargs):
            sql = args[0] if args else kwargs.get("sql")
            return _timed_sql(
                sql,
                lambda: super(TimedConnection, self).execute(*args, **kwargs),
            )

        def executemany(self, *args, **kwargs):
            sql = args[0] if args else kwargs.get("sql")
            return _timed_sql(
                sql,
                lambda: super(TimedConnection, self).executemany(*args, **kwargs),
            )

    class SQLiteProxy:
        def connect(self, *args, **kwargs):
            kwargs["factory"] = TimedConnection
            return _sqlite3.connect(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(_sqlite3, name)

    module.sqlite3 = SQLiteProxy()
    original = module.ExecutionDecisionJournal.record_grid_decision

    def timed_record_grid_decision(self, *args, **kwargs):
        call = _TIMER.begin()
        try:
            result = original(self, *args, **kwargs)
        except BaseException:
            _TIMER.finish(call, None, True)
            raise
        _TIMER.finish(call, result, False)
        return result

    module.ExecutionDecisionJournal.record_grid_decision = timed_record_grid_decision
    return module_path


def _ms(ns: int) -> float:
    return round(ns / 1_000_000.0, 6)


def _percentile(values, percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, int(percentile * len(ordered) + 0.999999) - 1),
    )
    return _ms(ordered[index])


def _inside_codex_tmp(path: Path, repo_root: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    target_root = (repo_root / ".codex-tmp").resolve()
    if not resolved.is_relative_to(target_root):
        raise ValueError("output_must_be_under_repository_codex_tmp")
    return resolved


def main(argv=None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    parser.add_argument(
        "--runner",
        type=Path,
        default=repo_root / "scripts" / "run_iteration50_live_factor_benchmark.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / ".codex-tmp" / "iteration50_journal_phase_diag_2048_r2.json",
    )
    args = parser.parse_args(argv)
    package_root = args.package_root.expanduser().resolve()
    runner_path = args.runner.expanduser().resolve()
    output_path = _inside_codex_tmp(args.output, repo_root)
    runner_output = output_path.with_name(output_path.stem + ".runner.json")
    if output_path.exists() or runner_output.exists():
        raise FileExistsError("diagnostic_output_already_exists")
    if _sha256(runner_path) != RUNNER_SHA256:
        raise RuntimeError("frozen_benchmark_runner_pin_mismatch")
    if not (package_root / "backtrader" / "__init__.py").is_file():
        raise RuntimeError("installed_package_root_missing_backtrader")

    # Keep imports from creating __pycache__ files in the installed consumer
    # or the repository; all files produced by the run stay under .codex-tmp.
    sys.dont_write_bytecode = True
    journal_path = _install_journal_observer(package_root)
    spec = importlib.util.spec_from_file_location(
        "_iteration50_frozen_benchmark_runner", runner_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("frozen_benchmark_runner_load_failed")
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    runner_argv = [
        "--mode",
        "native",
        "--factors",
        "alpha003",
        "--scenario",
        "standard",
        "--recovery-mode",
        "same-generation",
        "--grids",
        str(GRID_COUNT),
        "--warmup-bars",
        str(WARMUP_BARS),
        "--duration-seconds",
        "0",
        "--output",
        str(runner_output),
        "--source-revision",
        SOURCE_REVISION,
        "--package-root",
        str(package_root),
    ]
    prior_argv = sys.argv
    sys.argv = [str(runner_path)] + runner_argv
    try:
        runner_exit_code = runner.main(runner_argv)
    finally:
        sys.argv = prior_argv

    raw_bytes = runner_output.read_bytes()
    raw_report = json.loads(raw_bytes.decode("utf-8"))
    calls = _TIMER.calls
    total_ns = [call.get("total_ns", 0) for call in calls]
    sql_total_ns = sum(call.get("sql_ns", 0) for call in calls)
    residual_total_ns = sum(
        max(0, call.get("total_ns", 0) - call.get("sql_ns", 0)) for call in calls
    )
    aggregate = {name: 0 for name in PHASES}
    aggregate_counts = {name: 0 for name in PHASES}
    for call in calls:
        for phase in PHASES:
            aggregate[phase] += call["phase_ns"][phase]
            aggregate_counts[phase] += call["sql_counts"][phase]
    top_calls = sorted(
        calls,
        key=lambda call: (-call.get("total_ns", 0), call["call_index"]),
    )[:16]
    per_grid_timings = sorted(
        calls,
        key=lambda call: (
            call["grid_ordinal"] is None,
            call["grid_ordinal"] if call["grid_ordinal"] is not None else call["call_index"],
        ),
    )
    per_grid_timings = [
        {
            "call_index": call["call_index"],
            "grid_ordinal": call["grid_ordinal"],
            "outcome": call["outcome"],
            "record_grid_decision_ms": _ms(call.get("total_ns", 0)),
            "sql_execute_ms": _ms(call.get("sql_ns", 0)),
            "unclassified_python_lock_fetch_and_wrapper_ms": _ms(
                max(0, call.get("total_ns", 0) - call.get("sql_ns", 0))
            ),
        }
        for call in per_grid_timings
    ]
    top16 = [
        {
            "call_index": call["call_index"],
            "grid_ordinal": call["grid_ordinal"],
            "outcome": call["outcome"],
            "record_grid_decision_ms": _ms(call.get("total_ns", 0)),
            "sql_execute_ms": _ms(call.get("sql_ns", 0)),
            "unclassified_python_lock_fetch_and_wrapper_ms": _ms(
                max(0, call.get("total_ns", 0) - call.get("sql_ns", 0))
            ),
            "phase_ms": {name: _ms(call["phase_ns"][name]) for name in PHASES},
            "phase_statement_counts": dict(call["sql_counts"]),
        }
        for call in top_calls
    ]
    raw_timing = raw_report.get("latency", {}).get("monotonic_phases", {})
    raw_record_timing = raw_timing.get("record_grid_decision_call", {})
    report = {
        "schema_version": 1,
        "evidence_level": "DIAGNOSTIC_ONLY",
        "formal_acceptance_claimed": False,
        "comparison_limit": (
            "This is a new 2,048-grid sample. It makes no claim that its slowest "
            "ordinal matches any ordinal from the earlier 100,000-grid run."
        ),
        "profile": {
            "mode": "native",
            "factor_profile": "alpha003",
            "scenario": "standard",
            "evaluation_grids": GRID_COUNT,
            "warmup_bars": WARMUP_BARS,
            "duration_seconds": 0,
            "source_revision": SOURCE_REVISION,
        },
        "runner": {
            "path": str(runner_path),
            "sha256": RUNNER_SHA256,
            "installed_package_root": str(package_root),
            "journal_module_path": str(journal_path),
            "exit_code": runner_exit_code,
            "status": raw_report.get("status"),
            "gate_failures": raw_report.get("gate_failures", []),
            "raw_report_path": str(runner_output),
            "raw_report_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "decision_database_path": raw_report.get("decision_database_path"),
            "runner_record_grid_decision_call": raw_record_timing,
        },
        "instrumentation": {
            "journal_method": "wrapper delegates exactly once to the saved original method and returns its exact result; raised exceptions are re-raised",
            "sqlite_observation": "Connection/Cursor execute and executemany delegate to sqlite3 originals; SQL text and bound values are not emitted",
            "sql_measurement": "time spent inside each SQLite execute/executemany call while record_grid_decision is active",
            "residual_measurement": "method total minus summed SQL execute time; combines Python, lock wait, fetch/decode, serialization, and observer overhead",
            "wrapper_overhead": "per-call and per-statement Python dispatch/timer/accounting adds overhead and can materially affect absolute latency; diagnostic only",
            "durability_and_budget": "frozen runner policy is unchanged: WAL/FULL and the runner-derived 2,048-record budget; no timed checkpoint added",
            "timed_checkpoint": False,
            "bytecode_writes_disabled": True,
            "instrumentation_errors": _TIMER.instrumentation_errors,
        },
        "call_summary": {
            "record_grid_decision_calls": len(calls),
            "total_ms": _ms(sum(total_ns)),
            "max_ms": _ms(max(total_ns, default=0)),
            "p99_nearest_rank_ms": _percentile(total_ns, 0.99),
            "sql_execute_total_ms": _ms(sql_total_ns),
            "unclassified_python_lock_fetch_and_wrapper_total_ms": _ms(residual_total_ns),
        },
        "sql_phase_totals": {
            name: {
                "calls": aggregate_counts[name],
                "elapsed_ms": _ms(aggregate[name]),
            }
            for name in PHASES
        },
        "per_grid_call_timings": per_grid_timings,
        "top16_record_grid_decision_calls": top16,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as target:
        target.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"evidence_level": "DIAGNOSTIC_ONLY", "output": str(output_path)}))
    return runner_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
