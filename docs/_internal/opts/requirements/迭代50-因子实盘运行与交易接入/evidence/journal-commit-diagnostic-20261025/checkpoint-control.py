"""CONTROL_DIAGNOSTIC for the frozen Iteration 50 journal payload replay.

This wrapper reuses the pinned replay unchanged. It changes only the output
connection's WAL autocheckpoint setting and performs a PASSIVE checkpoint
inside every 256th successful record call, while that call is still covered by
the replay's existing outer wall/thread-CPU timer. This is diagnostic evidence,
not formal benchmark acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


BASE_SCRIPT = Path(__file__).resolve().with_name("i50_journal_payload_replay_20261025.py")
BASE_SHA256 = "779ff53a1e6d6680ca4b790d67dffc4e94dd8e0f620107feef9bc8a82c8756df"
WRAPPER_PATH = Path(__file__).resolve()
CHECKPOINT_INTERVAL = 256
TOP_K = 16


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_frozen_base():
    if not BASE_SCRIPT.is_file() or _sha256(BASE_SCRIPT) != BASE_SHA256:
        raise RuntimeError("FROZEN_BASE_PIN_MISMATCH")
    spec = importlib.util.spec_from_file_location("_i50_frozen_payload_replay", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("FROZEN_BASE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ControlState:
    def __init__(self) -> None:
        self.journal_opens = 0
        self.record_calls = 0
        self.connection_settings = []
        self.checkpoint_top = []
        self.checkpoint_totals = {
            "count": 0,
            "busy_nonzero_count": 0,
            "busy_sum": 0,
            "log_frames_sum": 0,
            "checkpointed_frames_sum": 0,
            "max_log_frames": 0,
            "max_checkpointed_frames": 0,
            "incomplete_count": 0,
        }

    def add_connection_setting(self, before: int, after: int) -> None:
        if len(self.connection_settings) < 8:
            self.connection_settings.append(
                {"wal_autocheckpoint_before": before, "wal_autocheckpoint_after": after}
            )

    def checkpoint(self, base: Any, journal: Any, ordinal: int) -> None:
        started_wall = time.perf_counter_ns()
        started_cpu = time.thread_time_ns()
        row = journal._connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        wall_ns = time.perf_counter_ns() - started_wall
        cpu_ns = time.thread_time_ns() - started_cpu
        if row is None or len(row) != 3 or any(type(value) is not int for value in row):
            raise RuntimeError("PASSIVE_CHECKPOINT_RESULT_INVALID")
        busy, log_frames, checkpointed_frames = (int(value) for value in row)
        totals = self.checkpoint_totals
        totals["count"] += 1
        totals["busy_nonzero_count"] += int(busy != 0)
        totals["busy_sum"] += busy
        totals["log_frames_sum"] += log_frames
        totals["checkpointed_frames_sum"] += checkpointed_frames
        totals["max_log_frames"] = max(totals["max_log_frames"], log_frames)
        totals["max_checkpointed_frames"] = max(
            totals["max_checkpointed_frames"], checkpointed_frames
        )
        incomplete = busy != 0 or (log_frames >= 0 and checkpointed_frames < log_frames)
        totals["incomplete_count"] += int(incomplete)
        sample = {
            "ordinal": ordinal,
            "busy": busy,
            "log_frames": log_frames,
            "checkpointed_frames": checkpointed_frames,
            "wall_ms": round(wall_ns / 1_000_000, 3),
            "thread_cpu_ms": round(cpu_ns / 1_000_000, 3),
        }
        entry = (wall_ns, ordinal, sample)
        if len(self.checkpoint_top) < TOP_K:
            heapq.heappush(self.checkpoint_top, entry)
        elif entry[:2] > self.checkpoint_top[0][:2]:
            heapq.heapreplace(self.checkpoint_top, entry)
        if incomplete:
            raise RuntimeError("PASSIVE_CHECKPOINT_INCOMPLETE")


def _install_control(base: Any, state: _ControlState) -> None:
    original_phase = base._sql_phase

    def control_phase(sql: str) -> str:
        if sql.lstrip().lower().startswith("pragma wal_checkpoint"):
            return "CHECKPOINT"
        return original_phase(sql)

    base._sql_phase = control_phase

    original_connection_type = base._TimedConnection

    class _NoAutoCheckpointConnection(original_connection_type):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            before = int(self.execute("PRAGMA wal_autocheckpoint").fetchone()[0])
            self.execute("PRAGMA wal_autocheckpoint=0")
            after = int(self.execute("PRAGMA wal_autocheckpoint").fetchone()[0])
            state.add_connection_setting(before, after)
            if after != 0:
                raise RuntimeError("WAL_AUTOCHECKPOINT_OVERRIDE_NOT_OBSERVED")

    base._TimedConnection = _NoAutoCheckpointConnection
    original_open = base._open_journal

    def open_with_control(journal_module: Any, database: Path, options: Any):
        journal = original_open(journal_module, database, options)
        state.journal_opens += 1
        if state.journal_opens == 1:
            original_record = journal.record_grid_decision

            def record_with_checkpoint(*args: Any, **kwargs: Any):
                result = original_record(*args, **kwargs)
                state.record_calls += 1
                if state.record_calls % CHECKPOINT_INTERVAL == 0:
                    state.checkpoint(base, journal, state.record_calls)
                return result

            journal.record_grid_decision = record_with_checkpoint
        return journal

    base._open_journal = open_with_control


def _control_report(base: Any, state: _ControlState, result: Dict[str, Any]) -> Dict[str, Any]:
    expected_checkpoints = base.EXPECTED // CHECKPOINT_INTERVAL
    timing = result.get("timing", {})
    phase_totals = timing.get("sql_phase_totals", {})
    commit_phase = phase_totals.get("COMMIT", {})
    checkpoint_phase = phase_totals.get("CHECKPOINT", {})
    persistence = result.get("persistence", {})
    pragma_values = (
        persistence.get("pragma_before_replay"),
        persistence.get("pragma_before_close"),
        persistence.get("pragma_after_reopen"),
    )
    checks = {
        "base_replay_complete": result.get("status")
        == "DIAGNOSTIC_COMPLETE_NOT_FORMAL_ACCEPTANCE",
        "exact_reopened_payload_rows": persistence.get("source_payload_exact_rows")
        == base.EXPECTED,
        "expected_successful_records": state.record_calls == base.EXPECTED,
        "expected_checkpoint_count": state.checkpoint_totals["count"] == expected_checkpoints,
        "commit_sql_phase_count": commit_phase.get("count") == base.EXPECTED,
        "checkpoint_sql_phase_count": checkpoint_phase.get("count") == expected_checkpoints,
        "exactly_two_control_connections": len(state.connection_settings) == 2,
        "autocheckpoint_disabled_each_connection": len(state.connection_settings) == 2
        and all(row["wal_autocheckpoint_after"] == 0 for row in state.connection_settings),
        "wal_full_preserved_each_observation": all(
            isinstance(value, dict)
            and value.get("journal_mode") == "wal"
            and value.get("synchronous") == 2
            and value.get("wal_autocheckpoint") == 0
            for value in pragma_values
        ),
        "all_passive_checkpoints_complete": state.checkpoint_totals["incomplete_count"] == 0,
    }
    report = {
        "classification": "CONTROL_DIAGNOSTIC",
        "evidence_level": "CONTROL_DIAGNOSTIC_NOT_FORMAL_ACCEPTANCE",
        "control_status": "CONTROL_DIAGNOSTIC_COMPLETE"
        if all(checks.values())
        else "CONTROL_DIAGNOSTIC_INCOMPLETE",
        "base_replay_status": result.get("status"),
        "base_script": {
            "path": str(BASE_SCRIPT),
            "sha256": _sha256(BASE_SCRIPT),
            "expected_sha256": BASE_SHA256,
        },
        "wrapper": {
            "path": str(WRAPPER_PATH),
            "size_bytes": WRAPPER_PATH.stat().st_size,
            "sha256": _sha256(WRAPPER_PATH),
        },
        "settings": {
            "changed_pragma_only": "PRAGMA wal_autocheckpoint=0 on each new output journal connection",
            "connection_values": state.connection_settings,
            "checkpoint_sql": "PRAGMA wal_checkpoint(PASSIVE)",
            "checkpoint_interval_successful_records": CHECKPOINT_INTERVAL,
            "checkpoint_count_expected": expected_checkpoints,
            "checkpoint_inside_outer_record_timing": True,
            "wal_mode": "WAL",
            "synchronous_mode": "FULL (SQLite value 2)",
            "payload_source_and_validation": "frozen base replay unchanged; all reopened payload rows must match",
            "base_self_check_compatibility": (
                "The base checks WAL/FULL and equality of pragma snapshots, but does not require "
                "the default autocheckpoint value; replay and reopen both observe zero, so the "
                "existing equality check remains intact."
            ),
        },
        "checks": checks,
        "records_observed": state.record_calls,
        "journal_open_count": state.journal_opens,
        "checkpoint_aggregate": state.checkpoint_totals,
        "checkpoint_top16_by_wall": [
            entry[2] for entry in sorted(state.checkpoint_top, reverse=True)
        ],
        "commit_sql_phase": commit_phase,
        "checkpoint_sql_phase": checkpoint_phase,
        "outer_record_timing_note": (
            "The wrapper performs each checkpoint before record_grid_decision returns; "
            "the frozen base outer wall/thread-CPU sample and histogram therefore include "
            "checkpoint time, while CHECKPOINT is also counted as its own SQL phase."
        ),
        "bounded_wal_observation": {
            "checkpoint_cadence": "one PASSIVE checkpoint per 256 successful grid records",
            "base_size_sample_count": len(persistence.get("size_samples", [])),
            "base_max_sampled_wal_bytes": max(
                (int(item.get("wal_bytes", 0)) for item in persistence.get("size_samples", [])),
                default=0,
            ),
            "base_size_samples_preserved": True,
        },
    }
    return report


def run(output_dir: Path) -> int:
    base = _load_frozen_base()
    state = _ControlState()
    _install_control(base, state)
    result, base_exit = base.run(output_dir)
    report = _control_report(base, state, result)
    result["control_diagnostic"] = report
    result["evidence_level"] = "CONTROL_DIAGNOSTIC_NOT_FORMAL_ACCEPTANCE"
    result["classification"] = "CONTROL_DIAGNOSTIC"
    result_path = output_dir / "diagnostic.json"
    with result_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "classification": "CONTROL_DIAGNOSTIC",
                "control_status": report["control_status"],
                "output_dir": str(output_dir),
            },
            sort_keys=True,
        )
    )
    return 0 if base_exit == 0 and report["control_status"] == "CONTROL_DIAGNOSTIC_COMPLETE" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    return run(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
