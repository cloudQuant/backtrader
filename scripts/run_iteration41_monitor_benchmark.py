"""BM59-M local process measurement; no provider, credentials, or live route.

Run with a reviewed/frozen bt_api_monitor on the interpreter's import path.
The default profile is 20 events/second for 30 minutes after 1000 warmup events.
--smoke verifies the harness only. A single local run does not accept the full
five-round, two-platform benchmark matrix. Raw samples remain in output-dir.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.abc
import json
import math
import multiprocessing
import os
import platform
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

RATE = 20
SCOPE = "benchmark:synthetic-account:monitor"
CONSUMER = "bm59.synthetic-sink"
CONSUME_INTERVAL_NS = 100_000_000
RESOURCE_INTERVAL_NS = 50_000_000


def percentiles(values):
    """Nearest rank, as required by the versioned acceptance specification."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("at least one sample is required")
    return {
        name: ordered[max(0, math.ceil(rank * len(ordered)) - 1)]
        for name, rank in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99), ("max", 1))
    }


def evaluate(metrics):
    """Keep every measured failure visible, including smoke-run failures."""
    return {
        "complete_unique_count": metrics["received"] == metrics["expected"]
        and metrics["duplicates"] == 0
        and metrics["durable_counts_match"],
        "lag_p99_le_1s": metrics["lag_ns"]["p99"] <= 1_000_000_000,
        "cpu_single_core_le_5pct": metrics["cpu_single_core_percent"] <= 5.0,
        "peak_rss_le_256mib": metrics["peak_rss_bytes"] <= 256 * 1024**2,
        "persistent_growth_le_1gib_day": metrics["growth_bytes_per_day"] <= 1024**3,
        "producer_kept_rate": metrics["producer_finished_before_drain"]
        and metrics["producer_lateness_ns"]["max"] <= 1_000_000_000 // RATE,
        "drained_within_30s": metrics["drain_seconds"] <= 30.0,
        "no_network_or_native_attempt": metrics["audit_blocked_attempts"] == 0,
        "resource_sampling_complete": metrics["maximum_resource_gap_ns"] <= 250_000_000,
    }


class _NativeBlocker(importlib.abc.MetaPathFinder):
    def __init__(self, attempts):
        self.attempts = attempts

    def find_spec(self, fullname, path=None, target=None):
        if fullname.rpartition(".")[2] in {"_ctp", "ctp_wrap"}:
            self.attempts.append("native_import")
            raise ImportError("native provider disabled in monitor benchmark")
        return


def install_io_guard():
    """Process-local test guard, explicitly not an OS sandbox proof."""
    attempts = []

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("network disabled in monitor benchmark")
        if event == "ctypes.dlopen" and args:
            name = str(args[0]).lower()
            if "_ctp" in name or "thost" in name:
                attempts.append("native_library")
                raise RuntimeError("native provider disabled in monitor benchmark")
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            name = os.fsdecode(args[0]).replace("\\", "/").lower()
            if "/runtime-ctp-private/" in name or name.rsplit("/", 1)[-1] == ".env":
                attempts.append("protected_config")
                raise RuntimeError("private configuration disabled in monitor benchmark")

    sys.meta_path.insert(0, _NativeBlocker(attempts))
    sys.addaudithook(audit)
    return attempts


def database_size(path):
    total = 0
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            total += candidate.stat().st_size
        except FileNotFoundError:  # SQLite may remove a WAL after the previous stat.
            pass
    return total


def database_snapshot(path):
    """Read allocated persistent pages independently of transient WAL lifetime."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        row_count, unique_count, last_sequence = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT event_id), MAX(sequence) "
            "FROM monitor_outbox_events WHERE scope = ?",
            (SCOPE,),
        ).fetchone()
        return {
            "rows": row_count,
            "unique_rows": unique_count,
            "last_sequence": last_sequence,
            "phase_counts": dict(
                connection.execute(
                    "SELECT json_extract(data_json, '$.phase'), COUNT(*) "
                    "FROM monitor_outbox_events WHERE scope = ? "
                    "GROUP BY json_extract(data_json, '$.phase')",
                    (SCOPE,),
                ).fetchall()
            ),
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "page_count": connection.execute("PRAGMA page_count").fetchone()[0],
            "page_size": connection.execute("PRAGMA page_size").fetchone()[0],
            "freelist_count": connection.execute("PRAGMA freelist_count").fetchone()[0],
        }


def _write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _monitor_process(output_dir, control):
    """Real consumer process with bounded per-poll work and an in-memory fake sink."""
    try:
        blocked = install_io_guard()
        import psutil
        from bt_api_monitor import DurableOutbox, DurableOutboxConsumer

        output = Path(output_dir)
        database = output / "monitor.sqlite3"
        outbox = DurableOutbox(database)
        process = psutil.Process()
        received = set()
        duplicates = 0
        samples = []
        resources = []
        cpu_start = None
        cpu_start_observed_monotonic_ns = None
        start_ns = None
        deadline_ns = None
        planned_end_ns = None
        planned_cpu_end = None
        planned_cpu_observed_ns = None
        expected = None
        peak_rss = 0
        peak_storage = database_size(database)
        next_resource_ns = 0
        next_consume_ns = 0
        consume_calls = 0
        empty_consume_calls = 0
        finished = False

        def fake_transport(item):
            # No blocking I/O or extra notification worker in the fake sink.
            nonlocal duplicates
            if item.event.data["phase"] != "measurement":
                return
            identity = item.event.event_id
            index = item.event.data["index"]
            if (
                expected is None
                or type(index) is not int
                or not 0 <= index < expected
                or identity != "measure-" + str(index)
            ):
                raise ValueError("unexpected synthetic event identity")
            if identity in received:
                duplicates += 1
            received.add(identity)

        consumer = DurableOutboxConsumer(outbox, CONSUMER, SCOPE, fake_transport)
        control.send({"status": "ready", "pid": os.getpid()})
        while True:
            if control.poll():
                command = control.recv()
                if command["command"] == "start":
                    start_ns = command["start_ns"]
                    expected = command["expected"]
                    deadline_ns = command["end_ns"] + 30_000_000_000
                    planned_end_ns = command["end_ns"]
                    cpu_start_observed_monotonic_ns = time.perf_counter_ns()
                    cpu_start = time.process_time_ns()
                elif command["command"] == "finish":
                    finished = True
                elif command["command"] == "abort":
                    raise RuntimeError("producer aborted")
            delivered = []
            if time.perf_counter_ns() >= next_consume_ns:
                delivered = consumer.consume(limit=32)
                consume_calls += 1
                empty_consume_calls += not delivered
                # Public consume() is synchronous and has no scheduler. Poll
                # on a bounded 100ms cadence, including after a successful
                # batch, instead of repeatedly opening an idle SQLite reader.
                # Each delivered event still receives its own durable ACK.
                next_consume_ns = time.perf_counter_ns() + CONSUME_INTERVAL_NS
            now = time.perf_counter_ns()
            for item in delivered:
                if item.event.data["phase"] == "measurement":
                    # Includes the committed checkpoint; batch completion is a
                    # conservative upper bound for earlier entries in this batch.
                    samples.append(
                        (item.sequence, item.event.event_id, item.event.data["origin_ns"], now)
                    )
            if now >= next_resource_ns:
                memory = process.memory_info()
                peak_rss = max(peak_rss, memory.rss, getattr(memory, "peak_wset", 0))
                peak_storage = max(peak_storage, database_size(database))
                if start_ns is not None:
                    resources.append((now, memory.rss, time.process_time_ns()))
                next_resource_ns = now + RESOURCE_INTERVAL_NS
            if planned_end_ns is not None and now >= planned_end_ns and planned_cpu_end is None:
                planned_cpu_end = time.process_time_ns()
                planned_cpu_observed_ns = now
            if start_ns is not None and finished and len(received) >= expected:
                break
            if deadline_ns is not None and now > deadline_ns:
                raise TimeoutError("monitor drain exceeded 30 seconds")
            remaining_ns = min(next_consume_ns, next_resource_ns) - time.perf_counter_ns()
            if remaining_ns > 0:
                time.sleep(min(remaining_ns, RESOURCE_INTERVAL_NS) / 1_000_000_000)
        end_ns = time.perf_counter_ns()
        final_cpu = time.process_time_ns()
        process_time_clock = time.get_clock_info("process_time")
        # The numerator conservatively includes pre-start CPU and the first
        # observation after the planned end. Drain cannot dilute the denominator.
        cpu_ns = planned_cpu_end - cpu_start
        with (output / "consumer-samples.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("sequence", "event_id", "origin_ns", "checkpoint_observed_ns"))
            writer.writerows(samples)
        with (output / "consumer-resources.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("monotonic_ns", "rss_bytes", "process_cpu_ns"))
            writer.writerows(resources)
        report = {
            "status": "complete",
            "pid": os.getpid(),
            "received": len(received),
            "duplicates": duplicates,
            "consume_calls_including_warmup": consume_calls,
            "empty_consume_calls_including_warmup": empty_consume_calls,
            "lag_ns": percentiles([row[3] - row[2] for row in samples]),
            "cpu_single_core_percent": cpu_ns * 100 / (planned_end_ns - start_ns),
            "cpu_measurement_basis": "conservative_upper_bound_over_fixed_injection_duration",
            "cpu_start_process_time_ns": cpu_start,
            "cpu_end_process_time_ns": planned_cpu_end,
            "cpu_delta_process_time_ns": cpu_ns,
            "cpu_start_observed_monotonic_ns": cpu_start_observed_monotonic_ns,
            "cpu_start_offset_from_planned_ns": cpu_start_observed_monotonic_ns - start_ns,
            "cpu_cutoff_observed_ns": planned_cpu_observed_ns,
            "planned_end_cutoff_overshoot_ns": planned_cpu_observed_ns - planned_end_ns,
            "process_time_clock": {
                "implementation": process_time_clock.implementation,
                "nominal_resolution_seconds": process_time_clock.resolution,
                "monotonic": process_time_clock.monotonic,
                "adjustable": process_time_clock.adjustable,
                "resolution_note": (
                    "nominal clock metadata; it does not establish observed process-CPU "
                    "accounting granularity"
                ),
            },
            "drain_cpu_ns": final_cpu - planned_cpu_end,
            "maximum_resource_gap_ns": max(
                [right[0] - left[0] for left, right in zip(resources, resources[1:])]
                + [max(0, resources[0][0] - start_ns), max(0, end_ns - resources[-1][0])]
            ),
            "peak_rss_bytes": peak_rss,
            "peak_database_bytes": peak_storage,
            "checkpoint": consumer.checkpoint(),
            "end_ns": end_ns,
            "audit_blocked_attempts": len(blocked),
        }
        _write_json(output / "consumer-summary.json", report)
        control.send(report)
    except BaseException as error:
        control.send({"status": "error", "error_type": type(error).__name__})
        raise
    finally:
        control.close()


def run(output, *, smoke=False):
    if sys.gettrace() is not None or os.environ.get("PYTEST_XDIST_WORKER"):
        raise RuntimeError("benchmark requires a serial interpreter without tracing")
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("the frozen benchmark profile requires Python 3.11")
    output.mkdir(parents=True, exist_ok=False)
    blocked = install_io_guard()
    import psutil
    import bt_api_monitor.durable as durable

    duration = 3 if smoke else 1800
    warmup = 20 if smoke else 1000
    expected = duration * RATE
    database = output / "monitor.sqlite3"
    outbox = durable.DurableOutbox(database)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    worker = context.Process(target=_monitor_process, args=(str(output), child))
    worker.start()
    child.close()
    complete = False
    try:
        if not parent.poll(60) or parent.recv().get("status") != "ready":
            raise RuntimeError("monitor did not start")
        for index in range(warmup):
            outbox.append(
                durable.OutboxEvent(
                    "warmup-" + str(index),
                    SCOPE,
                    "benchmark.fact",
                    {"phase": "warmup", "index": index},
                    time.time(),
                )
            )
        deadline = time.monotonic() + 60
        while outbox.checkpoint(CONSUMER, SCOPE) != warmup:
            if time.monotonic() > deadline or not worker.is_alive():
                raise RuntimeError("warmup did not drain")
            time.sleep(0.02)
        baseline = database_snapshot(database)
        baseline_bytes = baseline["page_count"] * baseline["page_size"]
        start_ns = time.perf_counter_ns() + 100_000_000
        end_ns = start_ns + duration * 1_000_000_000
        parent.send(
            {"command": "start", "start_ns": start_ns, "end_ns": end_ns, "expected": expected}
        )
        producer_samples = []
        for index in range(expected):
            scheduled = start_ns + index * 1_000_000_000 // RATE
            remaining = (scheduled - time.perf_counter_ns()) / 1_000_000_000
            if remaining > 0:
                time.sleep(remaining)
            origin = time.perf_counter_ns()
            outbox.append(
                durable.OutboxEvent(
                    "measure-" + str(index),
                    SCOPE,
                    "benchmark.fact",
                    {
                        "phase": "measurement",
                        "index": index,
                        "origin_ns": origin,
                        "quantity": "1",
                        "fee": "0.01",
                        "status": "ACKED",
                    },
                    time.time(),
                )
            )
            producer_samples.append((index, scheduled, origin, time.perf_counter_ns()))
            if not worker.is_alive():
                raise RuntimeError("monitor exited during production")
        producer_end = time.perf_counter_ns()
        remaining = (end_ns - producer_end) / 1_000_000_000
        if remaining > 0:
            time.sleep(remaining)
        parent.send({"command": "finish"})
        if not parent.poll(31):
            raise TimeoutError("monitor did not report a drained result")
        report = parent.recv()
        if report.get("status") != "complete":
            raise RuntimeError("monitor failed: " + str(report.get("error_type")))
        worker.join(5)
        if worker.exitcode != 0:
            raise RuntimeError("monitor process did not exit cleanly")
        with (output / "producer-samples.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("index", "scheduled_ns", "origin_ns", "append_committed_ns"))
            writer.writerows(producer_samples)
        final_storage = database_snapshot(database)
        final_bytes = final_storage["page_count"] * final_storage["page_size"]
        report.update(
            {
                "expected": expected,
                "durable_counts_match": final_storage["rows"]
                == final_storage["unique_rows"]
                == warmup + expected
                and final_storage["last_sequence"] == report["checkpoint"],
                "durable_rows": final_storage["rows"],
                "producer_lateness_ns": percentiles(
                    [max(0, row[2] - row[1]) for row in producer_samples]
                ),
                "growth_bytes_per_day": max(0, final_bytes - baseline_bytes) * 86400 / duration,
                "producer_append_latency_ns": percentiles(
                    [row[3] - row[2] for row in producer_samples]
                ),
                "producer_finished_before_drain": producer_end <= end_ns,
                "drain_seconds": max(0, (report["end_ns"] - end_ns) / 1_000_000_000),
                "audit_blocked_attempts": len(blocked) + report["audit_blocked_attempts"],
            }
        )
        report["durable_counts_match"] = report["durable_counts_match"] and (
            final_storage["phase_counts"] == {"warmup": warmup, "measurement": expected}
            and report["checkpoint"] == warmup + expected
        )
        checks = evaluate(report)
        module_path = Path(durable.__file__).resolve()
        result = {
            "benchmark": "BM59-M",
            "status": "SMOKE_ONLY" if smoke else "LOCAL_SINGLE_RUN",
            "measured_thresholds_pass": all(checks.values()),
            "acceptance": "NOT_ACCEPTED_FULL_MATRIX",
            "checks": checks,
            "metrics": report,
            "profile": {
                "duration_seconds": duration,
                "events_per_second": RATE,
                "warmup_events": warmup,
                "consumer_poll_interval_ns": CONSUME_INTERVAL_NS,
                "consumer_batch_limit": 32,
                "resource_sample_interval_ns": RESOURCE_INTERVAL_NS,
                "scope_count": 1,
                "scope": SCOPE,
                "retention": "no deletion; all warmup and measured rows retained",
                "producer_lateness_tolerance_ns": 1_000_000_000 // RATE,
            },
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "sqlite": sqlite3.sqlite_version,
                "sqlite_storage_baseline": baseline,
                "sqlite_storage_final": final_storage,
                "psutil": psutil.__version__,
                "physical_cpu_count": psutil.cpu_count(logical=False),
                "ram_bytes": psutil.virtual_memory().total,
                "module_origin": str(module_path),
                "module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
            },
            "limitations": [
                "one run, one platform, synthetic nonblocking sink",
                "storage device, filesystem and power mode need operator evidence",
                "RSS and database sizes sampled every 50ms; Windows also uses peak_wset",
                "process-local I/O guard is not OS isolation",
                "no fsync syscall counter; WAL/FULL implementation is source evidence",
                "lag includes committed checkpoint and conservative batch completion",
                "resource samples and raw CSV instrumentation are separate from product DB growth",
                "persistent growth uses allocated SQLite pages; peak file bytes additionally include WAL/SHM",
                "CPU is a conservative bound over fixed injection duration; drain cannot dilute it",
            ],
        }
        _write_json(output / "result.json", result)
        complete = True
        return result
    finally:
        if worker.is_alive():
            try:
                parent.send({"command": "abort"})
            except (BrokenPipeError, EOFError, OSError):
                pass
            worker.join(2)
            if worker.is_alive():
                worker.terminate()  # Only this script's synthetic monitor child.
                worker.join(5)
        parent.close()
        if not complete:
            _write_json(
                output / "failure.json", {"status": "HARNESS_FAILED", "acceptance": "NOT_ACCEPTED"}
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = run(args.output_dir.resolve(), smoke=args.smoke)
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks": result["checks"],
                "acceptance": result["acceptance"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["measured_thresholds_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
