"""DIAGNOSTIC_ONLY replay of the public R6 Iteration 50 decision payloads.

This is a one-off journal latency diagnostic, not a benchmark acceptance run.
It uses the pinned R6 installed consumer and keeps its WAL/FULL/default
autocheckpoint behavior. SQL text and parameters are timed but never retained.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / ".codex-tmp"
SOURCE_DIR = Path("D:/temp/i50-formal-20261025-r6/27a-build")
SOURCE_DB = SOURCE_DIR / "result.decisions.sqlite3"
SOURCE_REPORT = SOURCE_DIR / "result.json"
SITE_PACKAGES = Path("D:/temp/i5051c-20261025-r6/venv/Lib/site-packages")
EXPECTED_PYTHON = Path("D:/temp/i5051c-20261025-r6/venv/Scripts/python.exe")
JOURNAL_PATH = SITE_PACKAGES / "backtrader/stores/execution_decision_journal.py"
RUNNER_PATH = ROOT / "scripts/run_iteration50_live_factor_benchmark.py"
WHEEL_PATH = Path(
    "D:/temp/i5051b-03852948a7a4/wheel/back_trader_python-1.4.0-py3-none-any.whl"
)

EXPECTED = 100_000
ACCOUNT = "synthetic-no-account"
STRATEGY = "live-longstream-alpha003-build"
COHORT = "cohort-iteration50-build"
DECISION_KIND = "benchmark-noop"
RESERVATION_FIELD = "_journal_run_order_reservation"

PINS = {
    str(JOURNAL_PATH): "b5b1ba708a4c18c324315a454ae3d3dbc09d43793743cf327a037d5a69266b79",
    str(RUNNER_PATH): "75ca8866f6adb7fb8fc2dd361107d7749170d2cb453ba4cff4754a334567c2db",
    str(WHEEL_PATH): "bc33814b37ab44963ab9a964e689ee7c2665ed9a709b5bcbe0eb0bcd9770b7ee",
    str(SOURCE_REPORT): "ef915ad4c77c4c39d5fffb105006b956a9637718b2ef87f4ee59ddf79fd23c5e",
    str(SOURCE_DB): "e12fd983c51d1f87cca00e3ec43ccf25f9c345eca932dcd2f1c6172e91e60485",
}

HIST_LIMITS_NS = (1_000_000, 2_000_000, 5_000_000, 10_000_000, 25_000_000,
                  50_000_000, 100_000_000, 250_000_000, 500_000_000,
                  1_000_000_000, 2_000_000_000)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return {"size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _source_files() -> Dict[str, Optional[Dict[str, Any]]]:
    return {
        str(path): _file_fingerprint(path)
        for path in (SOURCE_DB, Path(str(SOURCE_DB) + "-wal"), Path(str(SOURCE_DB) + "-shm"))
    }


def _sql_phase(sql: str) -> str:
    text = sql.lstrip().lower()
    if text.startswith("begin"):
        return "BEGIN"
    if text.startswith("commit") or text.startswith("end"):
        return "COMMIT"
    if text.startswith("rollback"):
        return "ROLLBACK"
    # Durable capacity must be classified before the run-order table family.
    if "durable_capacity" in text or "execution_durable_capacity" in text:
        return "DURABLE_CAPACITY"
    if "execution_run_order_budgets" in text:
        return "RUN_ORDER_BUDGET"
    if "execution_decision_capacity_usage" in text or "execution_journal_capacity" in text:
        return "DECISION_CAPACITY"
    if "execution_grid_cursors" in text or "execution_grid_highwaters" in text:
        return "GRID_CURSOR_HIGHWATER"
    if "factor_position_grid_history" in text:
        return "GRID_HISTORY"
    if "execution_decisions" in text:
        return "DECISIONS"
    return "OTHER"


class _SqlObserver:
    def __init__(self) -> None:
        self.enabled = False
        self.depth = 0
        self.current: Optional[Dict[str, Any]] = None
        self.statement_count = 0
        self.phase_totals: Dict[str, Dict[str, int]] = {}

    def begin(self, sql: str) -> Optional[Tuple[str, int, int]]:
        if not self.enabled or self.depth:
            return None
        self.depth = 1
        return _sql_phase(sql), time.perf_counter_ns(), time.thread_time_ns()

    def end(self, token: Optional[Tuple[str, int, int]]) -> None:
        if token is None:
            return
        self.depth = 0
        phase, wall_start, cpu_start = token
        wall_ns = time.perf_counter_ns() - wall_start
        cpu_ns = time.thread_time_ns() - cpu_start
        self.statement_count += 1
        totals = self.phase_totals.setdefault(
            phase, {"count": 0, "wall_ns": 0, "thread_cpu_ns": 0, "max_wall_ns": 0}
        )
        totals["count"] += 1
        totals["wall_ns"] += wall_ns
        totals["thread_cpu_ns"] += cpu_ns
        totals["max_wall_ns"] = max(totals["max_wall_ns"], wall_ns)
        if self.current is not None:
            row = self.current["phases"].setdefault(
                phase, {"count": 0, "wall_ns": 0, "thread_cpu_ns": 0}
            )
            row["count"] += 1
            row["wall_ns"] += wall_ns
            row["thread_cpu_ns"] += cpu_ns


_OBSERVER = _SqlObserver()


class _TimedCursor(sqlite3.Cursor):
    def execute(self, sql: str, parameters: Any = (), /):
        token = _OBSERVER.begin(sql)
        try:
            return super().execute(sql, parameters)
        finally:
            _OBSERVER.end(token)


class _TimedConnection(sqlite3.Connection):
    def execute(self, sql: str, parameters: Any = (), /):
        token = _OBSERVER.begin(sql)
        try:
            return super().execute(sql, parameters)
        finally:
            _OBSERVER.end(token)

    def executemany(self, sql: str, seq_of_parameters: Any, /):
        token = _OBSERVER.begin(sql)
        try:
            return super().executemany(sql, seq_of_parameters)
        finally:
            _OBSERVER.end(token)

    def cursor(self, factory: Any = _TimedCursor, /):
        return super().cursor(factory)


def _open_journal(journal_module: Any, database: Path, options: Mapping[str, int]):
    original_connect = sqlite3.connect

    def connect(*args: Any, **kwargs: Any):
        kwargs.setdefault("factory", _TimedConnection)
        return original_connect(*args, **kwargs)

    sqlite3.connect = connect
    try:
        return journal_module.ExecutionDecisionJournal(database, **options)
    finally:
        sqlite3.connect = original_connect


def _pragma_values(journal: Any) -> Dict[str, Any]:
    connection = journal._connection
    return {
        "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
        "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
        "wal_autocheckpoint": int(connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]),
        "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
    }


def _histogram(values: Mapping[str, int]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    lower = 0
    for upper in HIST_LIMITS_NS:
        result["%d-%d_ms" % (lower // 1_000_000, upper // 1_000_000)] = values.get(str(upper), 0)
        lower = upper
    result[">2000_ms"] = values.get("inf", 0)
    return result


def _hist_bucket(hist: Dict[str, int], value_ns: int) -> None:
    for limit in HIST_LIMITS_NS:
        if value_ns <= limit:
            hist[str(limit)] = hist.get(str(limit), 0) + 1
            return
    hist["inf"] = hist.get("inf", 0) + 1


def _source_connection() -> sqlite3.Connection:
    uri = SOURCE_DB.as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
        raise RuntimeError("SOURCE_QUERY_ONLY_NOT_ENABLED")
    return connection


def _source_counts(connection: sqlite3.Connection) -> Dict[str, int]:
    history = int(connection.execute(
        """SELECT COUNT(*) FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=?""",
        (ACCOUNT, STRATEGY, COHORT),
    ).fetchone()[0])
    decisions = int(connection.execute("SELECT COUNT(*) FROM execution_decisions").fetchone()[0])
    return {"history_rows": history, "decision_rows": decisions}


def _source_rows(connection: sqlite3.Connection) -> Iterator[Tuple[sqlite3.Row, sqlite3.Row]]:
    history = connection.execute(
        """SELECT ordinal,batch_id,close_time FROM factor_position_grid_history
           WHERE account_scope=? AND strategy_scope=? AND cohort_id=? ORDER BY ordinal""",
        (ACCOUNT, STRATEGY, COHORT),
    )
    decisions = connection.execute(
        """SELECT rowid AS source_rowid,business_key_json,economic_payload_json,
                  intent_keys_json FROM execution_decisions ORDER BY rowid"""
    )
    expected_ordinal = 0
    while True:
        grid = history.fetchone()
        decision = decisions.fetchone()
        if grid is None and decision is None:
            return
        if grid is None or decision is None:
            raise RuntimeError("SOURCE_HISTORY_DECISION_COUNT_MISMATCH")
        expected_ordinal += 1
        if int(grid["ordinal"]) != expected_ordinal:
            raise RuntimeError("SOURCE_GRID_ORDINAL_NOT_CONTIGUOUS")
        yield grid, decision


def _metrics_end(
    ordinal: int,
    started_wall: int,
    started_cpu: int,
    phases: Dict[str, Any],
    top: list,
    wall_hist: Dict[str, int],
    cpu_hist: Dict[str, int],
    aggregate: Dict[str, int],
) -> None:
    wall_ns = time.perf_counter_ns() - started_wall
    cpu_ns = time.thread_time_ns() - started_cpu
    sql_wall_ns = sum(row["wall_ns"] for row in phases.values())
    sql_cpu_ns = sum(row["thread_cpu_ns"] for row in phases.values())
    residual_wall = max(0, wall_ns - sql_wall_ns)
    residual_cpu = max(0, cpu_ns - sql_cpu_ns)
    aggregate["calls"] += 1
    aggregate["wall_ns"] += wall_ns
    aggregate["thread_cpu_ns"] += cpu_ns
    aggregate["residual_wall_ns"] += residual_wall
    aggregate["residual_thread_cpu_ns"] += residual_cpu
    aggregate["max_wall_ns"] = max(aggregate["max_wall_ns"], wall_ns)
    _hist_bucket(wall_hist, wall_ns)
    _hist_bucket(cpu_hist, cpu_ns)
    item = {
        "ordinal": ordinal,
        "wall_ms": round(wall_ns / 1_000_000, 3),
        "thread_cpu_ms": round(cpu_ns / 1_000_000, 3),
        "outside_observed_sql_wall_ms": round(residual_wall / 1_000_000, 3),
        "outside_observed_sql_thread_cpu_ms": round(residual_cpu / 1_000_000, 3),
        "sql_by_phase": {
            phase: {
                "count": row["count"],
                "wall_ms": round(row["wall_ns"] / 1_000_000, 3),
                "thread_cpu_ms": round(row["thread_cpu_ns"] / 1_000_000, 3),
            }
            for phase, row in phases.items()
        },
    }
    entry = (wall_ns, ordinal, item)
    if len(top) < 16:
        heapq.heappush(top, entry)
    elif entry[:2] > top[0][:2]:
        heapq.heapreplace(top, entry)


def _timing_receipt(
    aggregate: Mapping[str, int],
    top: list,
    wall_hist: Mapping[str, int],
    cpu_hist: Mapping[str, int],
) -> Dict[str, Any]:
    return {
        "sample_scope": "new 100k replay; ordinals are not attributed to the earlier formal max call",
        "calls": aggregate["calls"],
        "api_returned_calls": aggregate.get("api_returned_calls", 0),
        "sql_statement_count": _OBSERVER.statement_count,
        "wrapper_note": "Connection/Cursor execute wrappers add diagnostic overhead; not formal performance evidence.",
        "outer_wall_ms_sum": round(aggregate["wall_ns"] / 1_000_000, 3),
        "outer_thread_cpu_ms_sum": round(aggregate["thread_cpu_ns"] / 1_000_000, 3),
        "outside_observed_sql_wall_ms_sum": round(aggregate["residual_wall_ns"] / 1_000_000, 3),
        "outside_observed_sql_thread_cpu_ms_sum": round(aggregate["residual_thread_cpu_ns"] / 1_000_000, 3),
        "max_outer_wall_ms": round(aggregate["max_wall_ns"] / 1_000_000, 3),
        "wall_histogram": _histogram(wall_hist),
        "thread_cpu_histogram": _histogram(cpu_hist),
        "sql_phase_totals": _OBSERVER.phase_totals,
        "top16_calls": [entry[2] for entry in sorted(top, reverse=True)],
    }


def _journal_sizes(path: Path) -> Dict[str, int]:
    return {
        "database_bytes": path.stat().st_size if path.exists() else 0,
        "wal_bytes": Path(str(path) + "-wal").stat().st_size
        if Path(str(path) + "-wal").exists() else 0,
    }


def _safe_error(error: Exception) -> Dict[str, str]:
    result = {"type": type(error).__name__}
    code = getattr(error, "code", None)
    if isinstance(code, str) and code and code.replace("_", "").isalnum():
        result["code"] = code
    elif isinstance(error, RuntimeError) and str(error).replace("_", "").isalnum():
        result["code"] = str(error)
    return result


def _load_and_check_pins(source_pre: Mapping[str, Optional[Dict[str, Any]]]) -> Dict[str, str]:
    found = {
        name: (
            source_pre[name]["sha256"]
            if name == str(SOURCE_DB) and source_pre[name] is not None
            else _sha256(Path(name))
        )
        for name in PINS
    }
    for name, expected in PINS.items():
        if found[name] != expected:
            raise RuntimeError("PIN_MISMATCH")
    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise RuntimeError("NOT_R6_CONSUMER_INTERPRETER")
    if not SITE_PACKAGES.is_dir():
        raise RuntimeError("R6_SITE_PACKAGES_MISSING")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SITE_PACKAGES))
    import backtrader.stores.execution_decision_journal as journal_module

    module_path = Path(journal_module.__file__).resolve()
    if module_path != JOURNAL_PATH.resolve():
        raise RuntimeError("INSTALLED_JOURNAL_ORIGIN_MISMATCH")
    return found


def _validate_report() -> Dict[str, Any]:
    with SOURCE_REPORT.open("r", encoding="utf-8") as stream:
        report = json.load(stream)
    profile = report["profile"]
    durable = report["durable_noop_journal"]
    if (
        Path(report.get("decision_database_path", "")).resolve() != SOURCE_DB.resolve()
        or profile.get("evaluation_grids") != EXPECTED
        or profile.get("factor_profile") != "alpha003"
        or profile.get("mode") != "build"
        or profile.get("scenario") != "standard"
        or profile.get("target_count") != 20
        or durable.get("capacity_after", {}).get("base_record_count") != EXPECTED
        or durable.get("new_grid_rows") != EXPECTED
        or durable.get("noop_rows") != EXPECTED
        or durable.get("logical_run_id") is None
    ):
        raise RuntimeError("R6_SOURCE_REPORT_PROFILE_MISMATCH")
    return report


def _prepare_output(path: Path) -> Path:
    root = TEMP_ROOT.resolve()
    output = path.resolve()
    if output.parent != root or not output.name.startswith("i50-journal-payload-replay-"):
        raise RuntimeError("OUTPUT_MUST_BE_FRESH_DIRECT_I50_TEMP_CHILD")
    if output.exists():
        raise RuntimeError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    output.mkdir()
    return output


def run(output_arg: Path) -> Tuple[Dict[str, Any], int]:
    output = _prepare_output(output_arg)
    result: Dict[str, Any] = {
        "schema": "i50-journal-payload-replay-diagnostic-v1",
        "evidence_level": "DIAGNOSTIC_ONLY_NOT_FORMAL_ACCEPTANCE",
        "status": "RUNNING",
        "source": {},
        "timing": {},
        "persistence": {},
    }
    source = None
    journal = None
    source_pre: Dict[str, Optional[Dict[str, Any]]] = {}
    last_ordinal = 0
    try:
        source_pre = _source_files()
        if source_pre[str(SOURCE_DB)] is None:
            raise RuntimeError("SOURCE_DATABASE_MISSING")
        wal = source_pre[str(Path(str(SOURCE_DB) + "-wal"))]
        if wal is not None and wal["size_bytes"] != 0:
            raise RuntimeError("SOURCE_WAL_NOT_EMPTY")
        result["source"]["files_before"] = source_pre
        result["source"]["expected_pins"] = _load_and_check_pins(source_pre)
        frozen_report = _validate_report()
        expected_run_id = frozen_report["durable_noop_journal"]["logical_run_id"]
        result["source"]["r6_report_pin"] = PINS[str(SOURCE_REPORT)]
        source = _source_connection()
        counts = _source_counts(source)
        if counts != {"history_rows": EXPECTED, "decision_rows": EXPECTED}:
            raise RuntimeError("SOURCE_ROW_COUNT_MISMATCH")
        result["source"]["row_counts"] = counts
        source_cursor = source.execute(
            """SELECT ordinal,epoch_id,batch_id FROM execution_grid_cursors
               WHERE account_scope=? AND strategy_scope=? AND cohort_id=?""",
            (ACCOUNT, STRATEGY, COHORT),
        ).fetchone()
        if source_cursor is None or int(source_cursor["ordinal"]) != EXPECTED or source_cursor["epoch_id"] != "1":
            raise RuntimeError("SOURCE_CURSOR_MISMATCH")
        result["source"]["cursor_ordinal"] = int(source_cursor["ordinal"])

        journal_path = output / "replay.decisions.sqlite3"
        options = {
            "max_decision_records": EXPECTED,
            "settlement_decision_reserve_records": 4096,
            "max_decision_bytes": 536_870_912,
            "settlement_decision_reserve_bytes": 67_108_864,
            "max_pending_intents": 1,
            "max_pending_callbacks": 1,
            "max_payload_bytes": 65_536,
        }
        journal_module = sys.modules["backtrader.stores.execution_decision_journal"]
        journal = _open_journal(journal_module, journal_path, options)
        before_pragma = _pragma_values(journal)
        if before_pragma["journal_mode"] != "wal" or before_pragma["synchronous"] != 2:
            raise RuntimeError("WAL_FULL_NOT_OBSERVED")
        result["persistence"]["pragma_before_replay"] = before_pragma
        initial_capacity = journal.decision_capacity_snapshot()
        if initial_capacity.base_record_count != 0:
            raise RuntimeError("OUTPUT_JOURNAL_NOT_EMPTY")

        wall_hist: Dict[str, int] = {}
        cpu_hist: Dict[str, int] = {}
        top = []
        aggregate = defaultdict(int)
        successful = 0
        last_batch_id = None
        source_run_id = None
        size_samples = [{"ordinal": 0, **_journal_sizes(journal_path)}]
        for ordinal, (grid, row) in enumerate(_source_rows(source), start=1):
            last_ordinal = ordinal
            key_data = json.loads(row["business_key_json"])
            if (
                key_data.get("account_scope") != ACCOUNT
                or key_data.get("strategy_scope") != STRATEGY
                or key_data.get("cohort_id") != COHORT
                or key_data.get("logical_run_id") != expected_run_id
                or key_data.get("decision_kind") != DECISION_KIND
                or key_data.get("close_time") != grid["close_time"]
            ):
                raise RuntimeError("SOURCE_KEY_HISTORY_MISMATCH")
            key = journal_module.ExecutionDecisionKey(**key_data)
            if row["business_key_json"] != journal_module._canonical_json(
                journal_module._decision_key_values(key)
            ):
                raise RuntimeError("SOURCE_KEY_NOT_CANONICAL")
            if source_run_id is None:
                source_run_id = key.logical_run_id
            elif key.logical_run_id != source_run_id:
                raise RuntimeError("SOURCE_LOGICAL_RUN_ID_CHANGED")
            if row["intent_keys_json"] != "[]":
                raise RuntimeError("SOURCE_NOT_NOOP")
            payload = json.loads(row["economic_payload_json"])
            reservation = payload.pop(RESERVATION_FIELD, None)
            if (
                reservation != {"max_order_intents_per_run": 0, "remaining_exit_intent_reserve": 0}
                or type(reservation.get("max_order_intents_per_run")) is not int
                or type(reservation.get("remaining_exit_intent_reserve")) is not int
                or payload.get("benchmark") != "iteration50-live-factor-longstream"
                or payload.get("factor_profile") != "alpha003"
                or payload.get("mode") != "build"
                or payload.get("finite_target_count") != 20
                or payload.get("no_op_reason") != "benchmark_only_no_execution_route"
            ):
                raise RuntimeError("SOURCE_PAYLOAD_OR_RESERVATION_MISMATCH")
            phases: Dict[str, Any] = {}
            _OBSERVER.current = {"phases": phases}
            _OBSERVER.enabled = True
            start_wall = time.perf_counter_ns()
            start_cpu = time.thread_time_ns()
            try:
                durable = journal.record_grid_decision(
                    key,
                    payload,
                    intent_keys=(),
                    epoch_id="1",
                    batch_id=grid["batch_id"],
                    eligible=True,
                    complete=True,
                    live_ready=True,
                    inputs_complete=True,
                    max_order_intents_per_run=reservation["max_order_intents_per_run"],
                    expected_run_order_intents_used=0,
                    remaining_exit_intent_reserve=reservation["remaining_exit_intent_reserve"],
                )
                successful += 1
                aggregate["api_returned_calls"] += 1
            finally:
                _OBSERVER.enabled = False
                _metrics_end(ordinal, start_wall, start_cpu, phases, top, wall_hist, cpu_hist, aggregate)
                _OBSERVER.current = None
            if phases.get("COMMIT", {}).get("count") != 1:
                raise RuntimeError("GRID_COMMIT_NOT_OBSERVED")
            if (
                not durable.eligible
                or durable.decision is None
                or not durable.decision.is_noop
                or not durable.is_new_grid
                or durable.cursor is None
                or durable.cursor.ordinal != ordinal
                or durable.cursor.batch_id != grid["batch_id"]
            ):
                raise RuntimeError("JOURNAL_GRID_RESULT_MISMATCH")
            last_batch_id = grid["batch_id"]
            if ordinal % 256 == 0 or ordinal == EXPECTED:
                size_samples.append({"ordinal": ordinal, **_journal_sizes(journal_path)})
        if successful != EXPECTED:
            raise RuntimeError("REPLAY_SUCCESS_COUNT_MISMATCH")
        if _OBSERVER.phase_totals.get("COMMIT", {}).get("count") != EXPECTED:
            raise RuntimeError("COMMIT_OBSERVATION_COUNT_MISMATCH")
        if last_batch_id != source_cursor["batch_id"]:
            raise RuntimeError("SOURCE_LAST_BATCH_MISMATCH")
        result["timing"] = _timing_receipt(aggregate, top, wall_hist, cpu_hist)
        result["persistence"]["size_samples"] = size_samples
        result["persistence"]["pragma_before_close"] = _pragma_values(journal)
        if result["persistence"]["pragma_before_close"] != before_pragma:
            raise RuntimeError("JOURNAL_PRAGMA_CHANGED_DURING_REPLAY")
        journal.close()
        journal = None
        result["persistence"]["first_close_returned"] = True
        result["persistence"]["size_after_first_close"] = _journal_sizes(journal_path)

        journal = _open_journal(journal_module, journal_path, options)
        reopened_pragma = _pragma_values(journal)
        capacity = journal.decision_capacity_snapshot()
        cursor = journal.grid_cursor(ACCOUNT, STRATEGY, COHORT)
        intent_count = journal.run_order_count(ACCOUNT, STRATEGY, source_run_id)
        result["persistence"]["pragma_after_reopen"] = reopened_pragma
        result["persistence"]["reopened"] = {
            "base_record_count": capacity.base_record_count,
            "cursor_ordinal": None if cursor is None else cursor.ordinal,
            "run_order_intent_count": intent_count,
            "database_bytes": capacity.database_bytes,
            "wal_bytes": capacity.wal_bytes,
        }
        if (
            capacity.base_record_count != EXPECTED
            or cursor is None
            or cursor.ordinal != EXPECTED
            or intent_count != 0
            or reopened_pragma["journal_mode"] != "wal"
            or reopened_pragma["synchronous"] != 2
            or reopened_pragma != before_pragma
        ):
            raise RuntimeError("REOPENED_PERSISTENCE_MISMATCH")

        exact_rows = 0
        for ordinal, (grid, row) in enumerate(_source_rows(source), start=1):
            key = journal_module.ExecutionDecisionKey(**json.loads(row["business_key_json"]))
            decision_id = journal_module._stable_id(
                "decision",
                journal_module._canonical_json(journal_module._decision_key_values(key)),
            )
            persisted = journal._connection.execute(
                """SELECT d.business_key_json,d.economic_payload_json,d.intent_keys_json,
                          h.ordinal,h.batch_id,h.close_time
                   FROM factor_position_grid_history AS h
                   JOIN execution_decisions AS d ON d.decision_id=?
                   WHERE h.account_scope=? AND h.strategy_scope=? AND h.cohort_id=?
                     AND h.ordinal=?""",
                (decision_id, ACCOUNT, STRATEGY, COHORT, ordinal),
            ).fetchone()
            if (
                persisted is None
                or persisted["business_key_json"] != row["business_key_json"]
                or persisted["economic_payload_json"] != row["economic_payload_json"]
                or persisted["intent_keys_json"] != row["intent_keys_json"]
                or int(persisted["ordinal"]) != ordinal
                or persisted["batch_id"] != grid["batch_id"]
                or persisted["close_time"] != grid["close_time"]
            ):
                raise RuntimeError("REOPENED_SOURCE_PAYLOAD_MISMATCH")
            exact_rows += 1
        if exact_rows != EXPECTED:
            raise RuntimeError("REOPENED_EXACT_PAYLOAD_COUNT_MISMATCH")
        result["persistence"]["source_payload_exact_rows"] = exact_rows
        journal.close()
        journal = None
        result["persistence"]["reopen_close_returned"] = True
        result["persistence"]["size_after_reopen_close"] = _journal_sizes(journal_path)
        result["status"] = "DIAGNOSTIC_COMPLETE_NOT_FORMAL_ACCEPTANCE"
    except Exception as error:
        result["status"] = "DIAGNOSTIC_FAILED"
        result["first_error"] = _safe_error(error)
        result["source"]["failure_ordinal"] = last_ordinal
        if "aggregate" in locals():
            result["timing"] = _timing_receipt(aggregate, top, wall_hist, cpu_hist)
    finally:
        _OBSERVER.enabled = False
        _OBSERVER.depth = 0
        _OBSERVER.current = None
        if journal is not None:
            try:
                journal.close()
            except Exception as error:
                result.setdefault("close_errors", []).append(_safe_error(error))
        if source is not None:
            source.close()
        if source_pre:
            try:
                source_post = _source_files()
                result["source"]["files_after"] = source_post
                result["source"]["unchanged"] = source_pre == source_post
                if source_pre != source_post:
                    result["status"] = "DIAGNOSTIC_FAILED_SOURCE_CHANGED"
                    result.setdefault("first_error", {"code": "SOURCE_OR_SIDECAR_CHANGED"})
            except Exception as error:
                result["source"]["post_fingerprint_error"] = _safe_error(error)
                result["status"] = "DIAGNOSTIC_FAILED_SOURCE_FINGERPRINT"
        else:
            result["source"]["unchanged"] = None
        pins_after = {}
        for name in PINS:
            if name != str(SOURCE_DB) and Path(name).exists():
                pins_after[name] = _sha256(Path(name))
        result["source"]["pins_after"] = pins_after
        expected_pins = result["source"].get("expected_pins")
        if expected_pins and pins_after != {
            name: digest for name, digest in expected_pins.items() if name != str(SOURCE_DB)
        }:
            result["status"] = "DIAGNOSTIC_FAILED_PIN_CHANGED"
            result.setdefault("first_error", {"code": "PINNED_SOURCE_CHANGED"})

    result_path = output / "diagnostic.json"
    with result_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")
    return result, 0 if result["status"] == "DIAGNOSTIC_COMPLETE_NOT_FORMAL_ACCEPTANCE" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result, exit_code = run(args.output_dir)
    print(json.dumps({"status": result["status"], "output_dir": str(args.output_dir)}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
