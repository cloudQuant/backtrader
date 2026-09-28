"""BM58 fake-only two-client/shared-SQLite-authority capacity diagnostic.

Default invocation is a short smoke profile. The 50 unique intents/second for
30 minutes profile is selected only with ``--profile capacity-30m``. Both
profiles use exactly two spawned client processes, one shared SQLite database,
and a local fake provider delay. This is a diagnostic harness, not runtime or
provider acceptance evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing
import os
import platform
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCHEMA = "iteration41.bm58_actor_capacity.v1"
DIAGNOSTIC_STATUS = "FAKE_LOCAL_DIAGNOSTIC"
ACCEPTANCE_STATUS = "NOT_ACCEPTED"
CLIENT_COUNT = 2
DEFAULTS = {
    "smoke": {"rate_per_second": 10, "duration_seconds": 2, "duplicate_every": 10},
    "capacity-30m": {
        "rate_per_second": 50,
        "duration_seconds": 1800,
        "duplicate_every": 100,
    },
}


class BenchmarkError(RuntimeError):
    """A fixed harness failure, never an application/provider response."""


class _Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, int] = {}

    def add(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + amount

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._values)


def resolve_profile(
    profile: str,
    *,
    rate_per_second: Optional[int] = None,
    duration_seconds: Optional[int] = None,
    duplicate_every: Optional[int] = None,
    provider_latency_ms: Optional[float] = None,
    max_outstanding: Optional[int] = None,
) -> Dict[str, Any]:
    """Resolve and validate explicit smoke, 30-minute, or custom settings."""

    if profile not in {"smoke", "capacity-30m", "custom"}:
        raise ValueError("unsupported profile")
    if profile == "custom":
        if rate_per_second is None or duration_seconds is None:
            raise ValueError("custom profile requires rate and duration")
        defaults = {
            "rate_per_second": rate_per_second,
            "duration_seconds": duration_seconds,
            "duplicate_every": 0,
        }
    else:
        if rate_per_second is not None or duration_seconds is not None:
            raise ValueError("rate/duration overrides require --profile custom")
        defaults = dict(DEFAULTS[profile])
    selected = {
        "rate_per_second": defaults["rate_per_second"],
        "duration_seconds": defaults["duration_seconds"],
        "duplicate_every": (
            defaults["duplicate_every"] if duplicate_every is None else duplicate_every
        ),
        "provider_latency_ms": 2.0 if provider_latency_ms is None else provider_latency_ms,
        "max_outstanding": 256 if max_outstanding is None else max_outstanding,
    }
    rate = selected["rate_per_second"]
    duration = selected["duration_seconds"]
    duplicates = selected["duplicate_every"]
    latency = selected["provider_latency_ms"]
    outstanding = selected["max_outstanding"]
    if type(rate) is not int or rate < 2 or rate % CLIENT_COUNT:
        raise ValueError("rate must be a positive even integer for two clients")
    if type(duration) is not int or duration < 1:
        raise ValueError("duration must be a positive integer number of seconds")
    if type(duplicates) is not int or duplicates < 0:
        raise ValueError("duplicate interval must be a nonnegative exact integer")
    if (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or not math.isfinite(latency)
        or latency < 0
    ):
        raise ValueError("fake provider latency must be a nonnegative number")
    if type(outstanding) is not int or outstanding < 1:
        raise ValueError("max outstanding must be a positive exact integer")
    selected["profile"] = profile
    selected["process_count"] = CLIENT_COUNT
    selected["status"] = DIAGNOSTIC_STATUS
    selected["acceptance_status"] = ACCEPTANCE_STATUS
    return selected


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")


def _connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database), timeout=0.05, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=50")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _begin(connection: sqlite3.Connection, counters: _Counters) -> None:
    deadline = time.monotonic() + 10.0
    while True:
        try:
            connection.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as error:
            text = str(error).lower()
            if "locked" not in text and "busy" not in text:
                raise
            counters.add("sqlite_busy_retries")
            if time.monotonic() >= deadline:
                raise BenchmarkError("sqlite writer remained busy") from None
            time.sleep(0.001)


def _initialize_database(database: Path, profile: Dict[str, Any], run_id: str) -> None:
    connection = sqlite3.connect(str(database), timeout=5.0, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(
            "CREATE TABLE run_state ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "run_id TEXT NOT NULL, peak_backlog INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE clients ("
            "client_id INTEGER PRIMARY KEY CHECK(client_id IN (0,1)),"
            "producer_done INTEGER NOT NULL DEFAULT 0 CHECK(producer_done IN (0,1)),"
            "producer_done_ns INTEGER);"
            "CREATE TABLE intents ("
            "intent_id TEXT PRIMARY KEY, global_index INTEGER NOT NULL UNIQUE,"
            "producer_client INTEGER NOT NULL CHECK(producer_client IN (0,1)),"
            "payload_sha256 TEXT NOT NULL, scheduled_ns INTEGER NOT NULL,"
            "accepted_ns INTEGER NOT NULL, state TEXT NOT NULL "
            "CHECK(state IN ('PENDING','CLAIMED','COMPLETE')),"
            "claim_client INTEGER, claimed_ns INTEGER, completed_ns INTEGER,"
            "fake_receipt_sha256 TEXT);"
            "CREATE TABLE request_attempts ("
            "attempt_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,"
            "request_client INTEGER NOT NULL CHECK(request_client IN (0,1)),"
            "kind TEXT NOT NULL CHECK(kind IN ('ACCEPTED','DUPLICATE')),"
            "requested_ns INTEGER NOT NULL, recorded_ns INTEGER NOT NULL,"
            "FOREIGN KEY(intent_id) REFERENCES intents(intent_id));"
            "CREATE TABLE backpressure_samples ("
            "sample_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "client_id INTEGER NOT NULL CHECK(client_id IN (0,1)),"
            "intent_id TEXT NOT NULL, started_ns INTEGER NOT NULL, ended_ns INTEGER NOT NULL,"
            "wait_ns INTEGER NOT NULL, polls INTEGER NOT NULL,"
            "outstanding_at_limit INTEGER NOT NULL);"
        )
        connection.execute("INSERT INTO run_state(singleton,run_id) VALUES(1,?)", (run_id,))
        connection.executemany("INSERT INTO clients(client_id) VALUES(?)", [(0,), (1,)])
        connection.commit()
    finally:
        connection.close()


def _outstanding(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM intents WHERE state IN ('PENDING','CLAIMED')"
        ).fetchone()[0]
    )


def _submit_intent(
    connection: sqlite3.Connection,
    counters: _Counters,
    *,
    client_id: int,
    intent_id: str,
    global_index: int,
    payload_sha256: str,
    scheduled_ns: int,
    max_outstanding: int,
) -> Tuple[str, int]:
    _begin(connection, counters)
    try:
        existing = connection.execute(
            "SELECT payload_sha256 FROM intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        now_ns = time.monotonic_ns()
        if existing is not None:
            if existing[0] != payload_sha256:
                raise BenchmarkError("intent id replay had a different payload digest")
            connection.execute(
                "INSERT INTO request_attempts"
                "(attempt_id,intent_id,request_client,kind,requested_ns,recorded_ns)"
                " VALUES(?,?,?,'DUPLICATE',?,?)",
                (intent_id + ":duplicate", intent_id, client_id, now_ns, now_ns),
            )
            connection.commit()
            return "DUPLICATE", _outstanding(connection)
        backlog = _outstanding(connection)
        if backlog >= max_outstanding:
            connection.rollback()
            return "BACKPRESSURED", backlog
        connection.execute(
            "INSERT INTO intents"
            "(intent_id,global_index,producer_client,payload_sha256,scheduled_ns,accepted_ns,state)"
            " VALUES(?,?,?,?,?,?,'PENDING')",
            (intent_id, global_index, client_id, payload_sha256, scheduled_ns, now_ns),
        )
        connection.execute(
            "INSERT INTO request_attempts"
            "(attempt_id,intent_id,request_client,kind,requested_ns,recorded_ns)"
            " VALUES(?,?,?,'ACCEPTED',?,?)",
            (intent_id + ":primary", intent_id, client_id, scheduled_ns, now_ns),
        )
        connection.execute(
            "UPDATE run_state SET peak_backlog=MAX(peak_backlog,?) WHERE singleton=1",
            (backlog + 1,),
        )
        connection.commit()
        return "ACCEPTED", backlog + 1
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def _record_pressure(
    connection: sqlite3.Connection,
    counters: _Counters,
    *,
    client_id: int,
    intent_id: str,
    start_ns: int,
    end_ns: int,
    polls: int,
    backlog: int,
) -> None:
    _begin(connection, counters)
    try:
        connection.execute(
            "INSERT INTO backpressure_samples"
            "(client_id,intent_id,started_ns,ended_ns,wait_ns,polls,outstanding_at_limit)"
            " VALUES(?,?,?,?,?,?,?)",
            (client_id, intent_id, start_ns, end_ns, end_ns - start_ns, polls, backlog),
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def _producer(
    database: Path,
    client_id: int,
    profile: Dict[str, Any],
    run_id: str,
    start_ns: int,
    counters: _Counters,
    finished: threading.Event,
    errors: List[str],
    error_lock: threading.Lock,
    pressure_csv: Path,
) -> None:
    connection = _connect(database)
    rate = profile["rate_per_second"]
    expected = profile["duration_seconds"] * rate
    per_client = expected // CLIENT_COUNT
    duplicate_every = profile["duplicate_every"]
    max_outstanding = profile["max_outstanding"]
    try:
        with pressure_csv.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                (
                    "client_id",
                    "intent_id",
                    "started_ns",
                    "ended_ns",
                    "wait_ns",
                    "polls",
                    "outstanding_at_limit",
                )
            )
            for local_index in range(per_client):
                global_index = client_id + local_index * CLIENT_COUNT
                scheduled_ns = start_ns + global_index * 1_000_000_000 // rate
                delay_ns = scheduled_ns - time.monotonic_ns()
                if delay_ns > 0:
                    time.sleep(delay_ns / 1_000_000_000)
                intent_id = "bm58:" + run_id + ":" + str(global_index).zfill(9)
                payload = json.dumps(
                    {"symbol": "SYNTHETIC-1", "side": "BUY", "quantity": 1},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                pressure_start = None
                pressure_polls = 0
                peak_at_limit = 0
                while True:
                    result, backlog = _submit_intent(
                        connection,
                        counters,
                        client_id=client_id,
                        intent_id=intent_id,
                        global_index=global_index,
                        payload_sha256=payload_sha256,
                        scheduled_ns=scheduled_ns,
                        max_outstanding=max_outstanding,
                    )
                    if result != "BACKPRESSURED":
                        if result == "ACCEPTED":
                            counters.add("accepted_unique_intents")
                        if pressure_start is not None:
                            ended_ns = time.monotonic_ns()
                            counters.add("backpressure_events")
                            counters.add("backpressure_wait_ns", ended_ns - pressure_start)
                            counters.add("backpressure_polls", pressure_polls)
                            _record_pressure(
                                connection,
                                counters,
                                client_id=client_id,
                                intent_id=intent_id,
                                start_ns=pressure_start,
                                end_ns=ended_ns,
                                polls=pressure_polls,
                                backlog=peak_at_limit,
                            )
                            writer.writerow(
                                (
                                    client_id,
                                    intent_id,
                                    pressure_start,
                                    ended_ns,
                                    ended_ns - pressure_start,
                                    pressure_polls,
                                    peak_at_limit,
                                )
                            )
                            stream.flush()
                        break
                    if pressure_start is None:
                        pressure_start = time.monotonic_ns()
                    pressure_polls += 1
                    peak_at_limit = max(peak_at_limit, backlog)
                    time.sleep(0.001)
                if duplicate_every and global_index % duplicate_every == 0:
                    duplicate_result, _ = _submit_intent(
                        connection,
                        counters,
                        client_id=client_id,
                        intent_id=intent_id,
                        global_index=global_index,
                        payload_sha256=payload_sha256,
                        scheduled_ns=scheduled_ns,
                        max_outstanding=max_outstanding,
                    )
                    if duplicate_result != "DUPLICATE":
                        raise BenchmarkError("injected retry was not classified duplicate")
                    counters.add("duplicate_attempts")
            counters.add("producer_expected_intents", per_client)
    except BaseException as error:
        with error_lock:
            errors.append(type(error).__name__)
        raise
    finally:
        try:
            _begin(connection, counters)
            connection.execute(
                "UPDATE clients SET producer_done=1,producer_done_ns=? WHERE client_id=?",
                (time.monotonic_ns(), client_id),
            )
            connection.commit()
        finally:
            connection.close()
            finished.set()


def _claim_next(
    connection: sqlite3.Connection, counters: _Counters, client_id: int
) -> Optional[Tuple[str, str]]:
    # Keep the empty-queue polling path read-only; BEGIN IMMEDIATE is reserved
    # for an actual claim so idle clients do not manufacture writer pressure.
    candidate = connection.execute(
        "SELECT intent_id,payload_sha256 FROM intents WHERE state='PENDING'"
        " ORDER BY scheduled_ns,global_index LIMIT 1"
    ).fetchone()
    if candidate is None:
        return None
    _begin(connection, counters)
    try:
        row = connection.execute(
            "SELECT intent_id,payload_sha256 FROM intents WHERE state='PENDING'"
            " ORDER BY scheduled_ns,global_index LIMIT 1"
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        now_ns = time.monotonic_ns()
        cursor = connection.execute(
            "UPDATE intents SET state='CLAIMED',claim_client=?,claimed_ns=?"
            " WHERE intent_id=? AND state='PENDING'",
            (client_id, now_ns, row[0]),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        connection.commit()
        return str(row[0]), str(row[1])
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def _complete_fake_provider_call(
    connection: sqlite3.Connection,
    counters: _Counters,
    *,
    client_id: int,
    intent_id: str,
    payload_sha256: str,
    latency_seconds: float,
) -> None:
    counters.add("fake_provider_calls")
    if latency_seconds:
        time.sleep(latency_seconds)
    receipt = hashlib.sha256(
        ("bm58-fake-provider:" + intent_id + ":" + payload_sha256).encode("utf-8")
    ).hexdigest()
    _begin(connection, counters)
    try:
        cursor = connection.execute(
            "UPDATE intents SET state='COMPLETE',completed_ns=?,fake_receipt_sha256=?"
            " WHERE intent_id=? AND state='CLAIMED' AND claim_client=?",
            (time.monotonic_ns(), receipt, intent_id, client_id),
        )
        if cursor.rowcount != 1:
            raise BenchmarkError("fake provider completion did not match claimed row")
        connection.commit()
        counters.add("completed_intents")
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def _client_process(
    database_text: str,
    client_id: int,
    profile: Dict[str, Any],
    run_id: str,
    control: Any,
    output_text: str,
) -> None:
    database = Path(database_text)
    output = Path(output_text)
    counters = _Counters()
    producer_finished = threading.Event()
    errors: List[str] = []
    error_lock = threading.Lock()
    consumer_connection: Optional[sqlite3.Connection] = None
    producer_thread: Optional[threading.Thread] = None
    try:
        consumer_connection = _connect(database)
        control.send({"kind": "ready", "client_id": client_id})
        start = control.recv()
        if type(start) is not dict or type(start.get("start_ns")) is not int:
            raise BenchmarkError("invalid parent start frame")
        start_ns = start["start_ns"]
        producer_thread = threading.Thread(
            target=_producer,
            args=(
                database,
                client_id,
                profile,
                run_id,
                start_ns,
                counters,
                producer_finished,
                errors,
                error_lock,
                output / ("backpressure-client-" + str(client_id) + ".csv"),
            ),
            name="bm58-producer-" + str(client_id),
            daemon=False,
        )
        producer_thread.start()
        fake_latency = profile["provider_latency_ms"] / 1000.0
        while True:
            with error_lock:
                if errors:
                    raise BenchmarkError("producer thread failed: " + errors[0])
            claimed = _claim_next(consumer_connection, counters, client_id)
            if claimed is not None:
                counters.add("claimed_intents")
                _complete_fake_provider_call(
                    consumer_connection,
                    counters,
                    client_id=client_id,
                    intent_id=claimed[0],
                    payload_sha256=claimed[1],
                    latency_seconds=fake_latency,
                )
                continue
            done_count = int(
                consumer_connection.execute(
                    "SELECT COUNT(*) FROM clients WHERE producer_done=1"
                ).fetchone()[0]
            )
            pending = _outstanding(consumer_connection)
            if done_count == CLIENT_COUNT and pending == 0:
                break
            time.sleep(0.001)
        producer_thread.join(timeout=5)
        if producer_thread.is_alive():
            raise BenchmarkError("producer thread did not stop")
        counters.add("producer_done")
        control.send(
            {
                "kind": "complete",
                "client_id": client_id,
                "counters": counters.snapshot(),
            }
        )
    except BaseException as error:
        if producer_thread is not None and producer_thread.is_alive():
            producer_thread.join(timeout=2)
        try:
            control.send(
                {"kind": "error", "client_id": client_id, "error_type": type(error).__name__}
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    finally:
        if consumer_connection is not None:
            consumer_connection.close()
        control.close()


def _dump_csv(connection: sqlite3.Connection, output: Path) -> None:
    with (output / "intent-samples.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "intent_id",
                "global_index",
                "producer_client",
                "payload_sha256",
                "scheduled_ns",
                "accepted_ns",
                "state",
                "claim_client",
                "claimed_ns",
                "completed_ns",
                "fake_receipt_sha256",
            )
        )
        writer.writerows(
            connection.execute(
                "SELECT intent_id,global_index,producer_client,payload_sha256,scheduled_ns,"
                "accepted_ns,state,claim_client,claimed_ns,completed_ns,fake_receipt_sha256 "
                "FROM intents ORDER BY global_index"
            )
        )
    with (output / "request-attempts.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ("attempt_id", "intent_id", "request_client", "kind", "requested_ns", "recorded_ns")
        )
        writer.writerows(
            connection.execute(
                "SELECT attempt_id,intent_id,request_client,kind,requested_ns,recorded_ns "
                "FROM request_attempts ORDER BY recorded_ns,attempt_id"
            )
        )
    with (output / "backpressure-samples.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "sample_id",
                "client_id",
                "intent_id",
                "started_ns",
                "ended_ns",
                "wait_ns",
                "polls",
                "outstanding_at_limit",
            )
        )
        writer.writerows(
            connection.execute(
                "SELECT sample_id,client_id,intent_id,started_ns,ended_ns,wait_ns,polls,"
                "outstanding_at_limit FROM backpressure_samples ORDER BY sample_id"
            )
        )


def run(output_dir: Path, profile: Dict[str, Any]) -> Dict[str, Any]:
    if sys.gettrace() is not None or os.environ.get("PYTEST_XDIST_WORKER"):
        raise BenchmarkError("benchmark requires a serial, untraced interpreter")
    if output_dir.exists():
        raise BenchmarkError("output directory must not already exist")
    output_dir.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    database = output_dir / "authority.sqlite3"
    _initialize_database(database, profile, run_id)
    context = multiprocessing.get_context("spawn")
    workers = []
    controls = []
    results = []
    try:
        for client_id in range(CLIENT_COUNT):
            parent, child = context.Pipe(duplex=True)
            process = context.Process(
                target=_client_process,
                args=(str(database), client_id, profile, run_id, child, str(output_dir)),
                name="bm58-client-" + str(client_id),
            )
            process.start()
            child.close()
            workers.append(process)
            controls.append(parent)
        ready = set()
        for control in controls:
            if not control.poll(30):
                raise BenchmarkError("client process did not become ready")
            frame = control.recv()
            if frame.get("kind") != "ready":
                raise BenchmarkError("invalid client ready frame")
            ready.add(frame["client_id"])
        if ready != {0, 1}:
            raise BenchmarkError("expected exactly two ready clients")
        start_ns = time.monotonic_ns() + 200_000_000
        end_ns = start_ns + profile["duration_seconds"] * 1_000_000_000
        for control in controls:
            control.send({"start_ns": start_ns})
        timeout = profile["duration_seconds"] + 120
        deadline = time.monotonic() + timeout
        for control in controls:
            remaining = max(0.0, deadline - time.monotonic())
            if not control.poll(remaining):
                raise BenchmarkError("client did not finish before drain timeout")
            frame = control.recv()
            if frame.get("kind") != "complete":
                raise BenchmarkError(
                    "client reported " + str(frame.get("error_type", "invalid frame"))
                )
            results.append(frame)
        for process in workers:
            process.join(10)
            if process.exitcode != 0:
                raise BenchmarkError("client process exited unsuccessfully")
        completed_at_ns = time.monotonic_ns()
        with closing(sqlite3.connect(str(database), timeout=10.0)) as connection:
            connection.row_factory = sqlite3.Row
            planned = profile["rate_per_second"] * profile["duration_seconds"]
            accepted = int(connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0])
            completed = int(
                connection.execute(
                    "SELECT COUNT(*) FROM intents WHERE state='COMPLETE'"
                ).fetchone()[0]
            )
            duplicates = int(
                connection.execute(
                    "SELECT COUNT(*) FROM request_attempts WHERE kind='DUPLICATE'"
                ).fetchone()[0]
            )
            incomplete = int(
                connection.execute(
                    "SELECT COUNT(*) FROM intents WHERE state!='COMPLETE'"
                ).fetchone()[0]
            )
            attempt_count = int(
                connection.execute("SELECT COUNT(*) FROM request_attempts").fetchone()[0]
            )
            peak_backlog = int(
                connection.execute(
                    "SELECT peak_backlog FROM run_state WHERE singleton=1"
                ).fetchone()[0]
            )
            outstanding = _outstanding(connection)
            producer_finish_ns = int(
                connection.execute("SELECT MAX(producer_done_ns) FROM clients").fetchone()[0]
            )
            last_completion_ns = connection.execute(
                "SELECT MAX(completed_ns) FROM intents"
            ).fetchone()[0]
            pressure_rows = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(wait_ns),0),COALESCE(SUM(polls),0) "
                "FROM backpressure_samples"
            ).fetchone()
            _dump_csv(connection, output_dir)
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        counters = [frame["counters"] for frame in results]

        def total(key: str) -> int:
            return sum(row.get(key, 0) for row in counters)

        expected_duplicates = (
            len(range(0, planned, profile["duplicate_every"])) if profile["duplicate_every"] else 0
        )
        lost = max(0, planned - completed)
        drain_seconds = (
            max(0, (int(last_completion_ns) - producer_finish_ns) / 1_000_000_000)
            if last_completion_ns is not None
            else 0.0
        )
        checks = {
            "two_clients_started": len(results) == CLIENT_COUNT and len(workers) == CLIENT_COUNT,
            "all_planned_intents_accepted": accepted == planned,
            "all_accepted_intents_completed": completed == accepted and incomplete == 0,
            "expected_duplicate_retries_observed": duplicates == expected_duplicates,
            "zero_lost_intents": lost == 0,
            "authority_backlog_drained": outstanding == 0,
            "fake_provider_calls_match_completions": total("fake_provider_calls") == completed,
            "sqlite_wal_enabled": journal_mode.lower() == "wal",
        }
        result = {
            "schema": SCHEMA,
            "benchmark": "BM58",
            "status": DIAGNOSTIC_STATUS,
            "acceptance_status": ACCEPTANCE_STATUS,
            "run_status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "profile": profile,
            "metrics": {
                "input_intents_planned": planned,
                "input_attempts_recorded": attempt_count,
                "accepted_unique_intents": accepted,
                "completed_intents": completed,
                "duplicate_attempts": duplicates,
                "expected_duplicate_attempts": expected_duplicates,
                "lost_intents": lost,
                "accepted_but_incomplete_intents": incomplete,
                "outstanding_at_end": outstanding,
                "peak_backlog": peak_backlog,
                "backpressure_events": int(pressure_rows[0]),
                "backpressure_wait_ns": int(pressure_rows[1]),
                "backpressure_polls": int(pressure_rows[2]),
                "sqlite_busy_retries": total("sqlite_busy_retries"),
                "fake_provider_calls": total("fake_provider_calls"),
                "provider_dispatches": 0,
                "native_api_calls": 0,
                "network_calls": 0,
                "drain_seconds_after_both_producers_finished": drain_seconds,
                "last_completion_ns": last_completion_ns,
                "producers_finished_ns": producer_finish_ns,
                "planned_end_ns": end_ns,
                "production_extension_seconds": max(
                    0, (producer_finish_ns - end_ns) / 1_000_000_000
                ),
                "actual_elapsed_seconds": max(0, (completed_at_ns - start_ns) / 1_000_000_000),
            },
            "clients": sorted(results, key=lambda row: row["client_id"]),
            "raw_outputs": [
                "authority.sqlite3",
                "intent-samples.csv",
                "request-attempts.csv",
                "backpressure-samples.csv",
                "backpressure-client-0.csv",
                "backpressure-client-1.csv",
            ],
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "sqlite": sqlite3.sqlite_version,
                "database_journal_mode": journal_mode,
            },
            "limitations": [
                "two local spawned clients sharing one SQLite database only",
                "uses the benchmark's own SQLite admission/claim tables, not a registered runtime or actor-server API",
                "fake provider work is a configurable local sleep and deterministic receipt hash",
                "no real provider, SDK, native API, account, credentials, or network is accessed",
                "process-local benchmark evidence is not OS isolation or a live authority guarantee",
                "a single run is FAKE_LOCAL_DIAGNOSTIC and does not establish AC41-58 acceptance",
            ],
        }
        _write_json(output_dir / "client-results.json", result["clients"])
        _write_json(output_dir / "result.json", result)
        return result
    except BaseException as error:
        _write_json(
            output_dir / "failure.json",
            {
                "schema": SCHEMA,
                "status": "FAKE_LOCAL_DIAGNOSTIC",
                "run_status": "HARNESS_FAILED",
                "error_type": type(error).__name__,
                "acceptance_status": ACCEPTANCE_STATUS,
            },
        )
        raise
    finally:
        for control in controls:
            control.close()
        for process in workers:
            if process.is_alive():
                process.terminate()
                process.join(5)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=("smoke", "capacity-30m", "custom"), default="smoke")
    parser.add_argument("--rate-per-second", type=int)
    parser.add_argument("--duration-seconds", type=int)
    parser.add_argument("--duplicate-every", type=int)
    parser.add_argument("--provider-latency-ms", type=float)
    parser.add_argument("--max-outstanding", type=int)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    try:
        profile = resolve_profile(
            args.profile,
            rate_per_second=args.rate_per_second,
            duration_seconds=args.duration_seconds,
            duplicate_every=args.duplicate_every,
            provider_latency_ms=args.provider_latency_ms,
            max_outstanding=args.max_outstanding,
        )
        result = run(args.output_dir.resolve(), profile)
    except (BenchmarkError, ValueError, OSError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "run_status": result["run_status"],
                "acceptance_status": result["acceptance_status"],
                "metrics": result["metrics"],
                "result_path": str(args.output_dir.resolve() / "result.json"),
            },
            sort_keys=True,
        )
    )
    return 0 if result["run_status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
