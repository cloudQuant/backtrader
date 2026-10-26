"""Bounded external RSS sampling for one explicitly identified process tree.

Only a sanitized ``completion_receipt.json`` is read. The observer never reads
runner configuration, tape, journal, command lines, or process environments.
Window summaries require caller-supplied UTC boundaries and are diagnostics,
not a trading-grid acceptance oracle.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Iterable, Mapping, Optional

try:
    import psutil
except ImportError:  # pragma: no cover - minimal installs
    psutil = None


SAMPLE_NS = 1_000_000_000
MAX_DURATION_NS = 7 * 60 * 60 * SAMPLE_NS
MAX_RECEIPT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
SUMMARY_RESERVE_BYTES = 16 * 1024
MAX_TREE_PROCESSES = 256
MAX_SAMPLE_GAP_SECONDS = 2.0
WINDOW_SECONDS = 30 * 60
MIN_WINDOW_COVERAGE = 0.90
RECEIPT_FILENAME = "completion_receipt.json"
SUCCESS_STATUSES = {"LIVE_RUN_COMPLETE", "LIVE_EPOCH_SEQUENCE_COMPLETE"}
TERMINAL_STATUSES = SUCCESS_STATUSES | {
    "LIVE_RUN_INCOMPLETE",
    "LIVE_EPOCH_SEQUENCE_INCOMPLETE",
    "LIVE_RUN_FAILED",
    "LIVE_EPOCH_SEQUENCE_FAILED",
    "BLOCKED",
    "FAILED",
}
_RECEIPT_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
UTC = timezone.utc


def _utc_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("invalid_utc_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid_utc_timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("utc_timestamp_must_be_utc")
    return parsed.astimezone(UTC)


def _is_receipt_path(path: Path) -> bool:
    return path.name == RECEIPT_FILENAME


def _read_receipt(path: Path) -> dict[str, Any]:
    """Return only whitelisted receipt facts; never return the raw payload."""
    if not _is_receipt_path(path):
        return {"state": "invalid", "error_code": "RECEIPT_PATH_NOT_ALLOWED"}
    try:
        before = path.lstat()
    except FileNotFoundError:
        return {"state": "absent"}
    except OSError:
        return {"state": "invalid", "error_code": "RECEIPT_STAT_FAILED"}
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        return {"state": "invalid", "error_code": "RECEIPT_NOT_REGULAR_FILE"}
    if before.st_size < 0 or before.st_size > MAX_RECEIPT_BYTES:
        return {"state": "invalid", "error_code": "RECEIPT_SIZE_LIMIT"}

    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(str(path), flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size != before.st_size
                or opened.st_size > MAX_RECEIPT_BYTES
                or (opened.st_ino and before.st_ino and opened.st_ino != before.st_ino)
            ):
                return {"state": "invalid", "error_code": "RECEIPT_CHANGED_DURING_READ"}
            raw = source.read(MAX_RECEIPT_BYTES + 1)
            after = os.fstat(source.fileno())
            if (
                after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or (after.st_ino and opened.st_ino and after.st_ino != opened.st_ino)
            ):
                return {"state": "invalid", "error_code": "RECEIPT_CHANGED_DURING_READ"}
    except OSError:
        return {"state": "invalid", "error_code": "RECEIPT_READ_FAILED"}
    if len(raw) > MAX_RECEIPT_BYTES:
        return {"state": "invalid", "error_code": "RECEIPT_SIZE_LIMIT"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"state": "invalid", "error_code": "RECEIPT_JSON_INVALID"}
    if not isinstance(payload, dict):
        return {"state": "invalid", "error_code": "RECEIPT_SHAPE_INVALID"}
    if set(payload) - {"status", "closed", "cleanup_complete", "receipt_id"}:
        return {"state": "invalid", "error_code": "RECEIPT_FIELDS_NOT_SANITIZED"}

    status = payload.get("status")
    if not isinstance(status, str) or status not in TERMINAL_STATUSES:
        return {"state": "nonterminal", "error_code": "RECEIPT_STATUS_NOT_TERMINAL"}
    closed = [payload[key] for key in ("closed", "cleanup_complete") if key in payload]
    if not closed or any(type(value) is not bool for value in closed):
        return {"state": "invalid", "error_code": "RECEIPT_CLOSED_FIELD_INVALID"}
    if any(value != closed[0] for value in closed[1:]):
        return {"state": "invalid", "error_code": "RECEIPT_CLOSED_FIELDS_CONFLICT"}
    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or _RECEIPT_ID.fullmatch(receipt_id) is None:
        receipt_id = None
    return {
        "state": "terminal",
        "status": status,
        "closed": closed[0],
        "receipt_id": receipt_id,
        "error_code": None if receipt_id else "RECEIPT_ID_MISSING_OR_INVALID",
    }


def _error_code(error: BaseException) -> str:
    if psutil is not None:
        if isinstance(error, getattr(psutil, "ZombieProcess", ())):
            return "PROCESS_ZOMBIE"
        if isinstance(error, getattr(psutil, "NoSuchProcess", ())):
            return "PROCESS_DISAPPEARED"
        if isinstance(error, getattr(psutil, "AccessDenied", ())):
            return "PROCESS_ACCESS_DENIED"
        if isinstance(error, getattr(psutil, "Error", ())):
            return "PROCESS_QUERY_FAILED"
    return "PROCESS_OS_ERROR" if isinstance(error, OSError) else "PROCESS_QUERY_FAILED"


def _invalid_snapshot(reason: str, code: str, tree=()) -> dict[str, Any]:
    return {
        "valid": False,
        "stop_reason": reason,
        "rss_total_bytes": None,
        "process_tree": list(tree),
        "error_codes": [code],
    }


def _snapshot(root_pid: int, expected_create_time: float) -> dict[str, Any]:
    """Collect an all-or-invalid tree sample; failures never become zero RSS."""
    if psutil is None:
        return _invalid_snapshot("PSUTIL_UNAVAILABLE", "PSUTIL_UNAVAILABLE")
    try:
        root = psutil.Process(root_pid)
        root_time = float(root.create_time())
    except Exception as error:
        code = _error_code(error)
        if code == "PROCESS_DISAPPEARED":
            return _invalid_snapshot("ROOT_EXIT_OBSERVED", "ROOT_NOT_FOUND")
        return _invalid_snapshot("ROOT_SAMPLING_UNAVAILABLE", code)
    if root_time != expected_create_time:
        return _invalid_snapshot(
            "ROOT_IDENTITY_CHANGED",
            "ROOT_CREATE_TIME_MISMATCH",
            ({"pid": root_pid, "create_time": root_time, "rss_bytes": None},),
        )

    errors: set[str] = set()
    try:
        processes = [root, *root.children(recursive=True)]
    except Exception as error:
        return _invalid_snapshot(
            "TREE_SAMPLING_UNAVAILABLE", "TREE_DISCOVERY_" + _error_code(error)
        )
    if len(processes) > MAX_TREE_PROCESSES:
        processes = processes[:MAX_TREE_PROCESSES]
        errors.add("TREE_PROCESS_LIMIT")

    entries = []
    seen: dict[int, float] = {}
    total = 0
    root_exit = False
    root_changed = False
    for process in processes:
        pid = int(process.pid)
        entry = {"pid": pid, "create_time": None, "rss_bytes": None}
        try:
            created = float(process.create_time())
            entry["create_time"] = created
            if pid in seen:
                if seen[pid] != created:
                    raise RuntimeError("PROCESS_IDENTITY_CHANGED")
                continue
            seen[pid] = created
            if pid == root_pid and created != expected_create_time:
                root_changed = True
                raise RuntimeError("ROOT_CREATE_TIME_MISMATCH")
            if not process.is_running():
                raise RuntimeError("PROCESS_DISAPPEARED")
            rss = int(process.memory_info().rss)
            if rss < 0 or not process.is_running():
                raise RuntimeError("PROCESS_DISAPPEARED")
            entry["rss_bytes"] = rss
            total += rss
        except Exception as error:
            code = (
                str(error)
                if isinstance(error, RuntimeError)
                and str(error)
                in {
                    "PROCESS_IDENTITY_CHANGED",
                    "ROOT_CREATE_TIME_MISMATCH",
                    "PROCESS_DISAPPEARED",
                }
                else _error_code(error)
            )
            entry["error_code"] = code
            errors.add(code)
            if pid == root_pid:
                root_exit = code == "PROCESS_DISAPPEARED"
                root_changed = root_changed or code == "ROOT_CREATE_TIME_MISMATCH"
        entries.append(entry)

    if root_changed:
        return _invalid_snapshot("ROOT_IDENTITY_CHANGED", "ROOT_CREATE_TIME_MISMATCH", entries)
    if entries and entries[0]["pid"] == root_pid and entries[0]["rss_bytes"] is None:
        reason = "ROOT_EXIT_OBSERVED" if root_exit else "ROOT_SAMPLING_UNAVAILABLE"
        return _invalid_snapshot(
            reason, "ROOT_NOT_FOUND" if root_exit else next(iter(errors)), entries
        )
    valid = bool(entries) and not errors
    return {
        "valid": valid,
        "stop_reason": None,
        "rss_total_bytes": total if valid else None,
        "process_tree": entries,
        "error_codes": sorted(errors),
    }


def summarize_equal_windows(
    samples: Iterable[Mapping[str, Any]], *, warmup_end_utc: str, run_end_utc: str
) -> dict[str, Any]:
    """Compare explicit equal first/last 30-minute windows from raw sample rows."""
    try:
        warmup = _parse_utc(warmup_end_utc)
        end = _parse_utc(run_end_utc)
    except ValueError:
        return {"status": "INVALID_WINDOW_BOUNDS", "windows": []}
    first = (warmup, warmup + timedelta(seconds=WINDOW_SECONDS))
    last = (end - timedelta(seconds=WINDOW_SECONDS), end)
    if end <= warmup or first[1] > last[0]:
        return {"status": "INVALID_WINDOW_BOUNDS", "windows": []}

    rows: list[list[tuple[datetime, int, bool]]] = [[], []]
    unlocated = 0
    for sample in samples:
        try:
            when = _parse_utc(sample.get("utc"))
        except (ValueError, TypeError):
            unlocated += 1
            continue
        for index, (start, stop) in enumerate((first, last)):
            if start <= when < stop:
                valid = sample.get("sampling_valid") is True
                rss = sample.get("rss_total_bytes")
                if type(rss) is not int or rss <= 0:
                    valid, rss = False, 0
                rows[index].append((when, rss, valid))
                break

    windows = []
    minimum = math.ceil(WINDOW_SECONDS * MIN_WINDOW_COVERAGE)
    for (start, stop), observed in zip((first, last), rows):
        observed.sort(key=lambda row: row[0])
        valid_rows = [row for row in observed if row[2]]
        slots = {int((row[0] - start).total_seconds()) for row in valid_rows}
        values = sorted(row[1] for row in valid_rows)
        times = [row[0] for row in valid_rows]
        gaps = [(times[0] - start).total_seconds()] if times else []
        gaps.extend((b - a).total_seconds() for a, b in zip(times, times[1:]))
        if times:
            gaps.append((stop - times[-1]).total_seconds())
        max_gap = max(gaps, default=float(WINDOW_SECONDS))
        enough = (
            len(slots) >= minimum
            and len(valid_rows) == len(slots)
            and len(observed) == len(valid_rows)
            and max_gap <= MAX_SAMPLE_GAP_SECONDS
        )
        windows.append(
            {
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "end_utc": stop.isoformat().replace("+00:00", "Z"),
                "expected_samples": WINDOW_SECONDS,
                "valid_samples": len(slots),
                "invalid_samples": len(observed) - len(valid_rows),
                "duplicate_second_count": len(valid_rows) - len(slots),
                "coverage_ratio": len(slots) / WINDOW_SECONDS,
                "maximum_gap_seconds": max_gap,
                "p95_rss_bytes": values[max(0, math.ceil(len(values) * 0.95) - 1)]
                if values
                else None,
                "peak_rss_bytes": max(values) if values else None,
                "coverage_status": "SUFFICIENT" if enough else "INSUFFICIENT",
            }
        )
    enough = unlocated == 0 and all(row["coverage_status"] == "SUFFICIENT" for row in windows)
    return {
        "status": "WINDOWS_RECORDED" if enough else "INSUFFICIENT_COVERAGE",
        "window_seconds": WINDOW_SECONDS,
        "minimum_coverage_ratio": MIN_WINDOW_COVERAGE,
        "unlocated_invalid_sample_count": unlocated,
        "first_vs_last_p95_growth_bytes": (
            windows[1]["p95_rss_bytes"] - windows[0]["p95_rss_bytes"] if enough else None
        ),
        "windows": windows,
    }


def _write_line(stream, row: Mapping[str, Any], size: int, reserve: int = 0) -> int:
    data = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if size + len(data) + reserve > MAX_OUTPUT_BYTES:
        return -1
    stream.write(data)
    stream.flush()
    return size + len(data)


def observe_process(
    *,
    root_pid: int,
    expected_create_time: float,
    completion_receipt: Path,
    output_path: Path,
    warmup_end_utc: Optional[str] = None,
    run_end_utc: Optional[str] = None,
) -> dict[str, Any]:
    """Stream bounded samples until a receipt, root exit, or fixed time limit."""
    if psutil is None:
        raise RuntimeError("psutil_unavailable")
    if type(root_pid) is not int or root_pid <= 0:
        raise ValueError("invalid_root_pid")
    if (
        isinstance(expected_create_time, bool)
        or not isinstance(expected_create_time, (int, float))
        or not math.isfinite(expected_create_time)
        or expected_create_time <= 0
    ):
        raise ValueError("invalid_expected_create_time")
    if not _is_receipt_path(completion_receipt):
        raise ValueError("completion_receipt_path_not_allowed")
    if completion_receipt.resolve(strict=False) == output_path.resolve(strict=False):
        raise ValueError("receipt_and_output_must_differ")
    if (warmup_end_utc is None) != (run_end_utc is None):
        raise ValueError("both_window_times_required")
    windows = None
    if warmup_end_utc is not None and run_end_utc is not None:
        check = summarize_equal_windows((), warmup_end_utc=warmup_end_utc, run_end_utc=run_end_utc)
        if check["status"] == "INVALID_WINDOW_BOUNDS":
            raise ValueError("invalid_window_bounds")
        start = _parse_utc(warmup_end_utc)
        end = _parse_utc(run_end_utc)
        windows = (
            (start, start + timedelta(seconds=WINDOW_SECONDS)),
            (end - timedelta(seconds=WINDOW_SECONDS), end),
        )

    started_ns, started_utc = time.monotonic_ns(), _utc_text()
    counts = {
        "sample_count": 0,
        "valid_sample_count": 0,
        "invalid_sample_count": 0,
        "missed_sample_count": 0,
        "completion_receipt_errors": 0,
    }
    sample_rows: list[dict[str, Any]] = []
    max_gap = 0.0
    previous_ns = None
    peak = None
    limited = False
    stop_reason = "MAX_DURATION"
    stop_error_codes: list[str] = []
    receipt: dict[str, Any] = {"state": "absent"}
    size = 0

    with output_path.open("xb") as stream:
        header = {
            "record_type": "header",
            "schema": 1,
            "root_pid": root_pid,
            "expected_create_time": expected_create_time,
            "sample_interval_seconds": 1,
            "maximum_duration_seconds": 7 * 60 * 60,
            "maximum_output_bytes": MAX_OUTPUT_BYTES,
            "started_utc": started_utc,
            "window_summary_requested": windows is not None,
        }
        size = _write_line(stream, header, size, SUMMARY_RESERVE_BYTES)
        if size < 0:
            raise RuntimeError("output_header_exceeds_limit")

        deadline = started_ns
        while True:
            now = time.monotonic_ns()
            if now - started_ns >= MAX_DURATION_NS:
                break
            if deadline > now:
                time.sleep((deadline - now) / 1_000_000_000)
            if time.monotonic_ns() - started_ns >= MAX_DURATION_NS:
                break
            receipt = _read_receipt(completion_receipt)
            if receipt["state"] == "terminal":
                if receipt.get("error_code"):
                    counts["completion_receipt_errors"] += 1
                stop_reason = "COMPLETION_RECEIPT"
                break
            if receipt.get("error_code"):
                counts["completion_receipt_errors"] += 1
            if time.monotonic_ns() - started_ns >= MAX_DURATION_NS:
                break

            mono = time.monotonic_ns()
            utc = _utc_text()
            snap = _snapshot(root_pid, expected_create_time)
            if snap["stop_reason"]:
                stop_reason = snap["stop_reason"]
                stop_error_codes = list(snap["error_codes"])
                break
            row = {
                "record_type": "sample",
                "monotonic_ns": mono,
                "utc": utc,
                "sampling_valid": snap["valid"],
                "rss_total_bytes": snap["rss_total_bytes"],
                "process_tree": snap["process_tree"],
                "error_codes": snap["error_codes"],
            }
            size = _write_line(stream, row, size, SUMMARY_RESERVE_BYTES)
            if size < 0:
                limited, stop_reason = True, "OUTPUT_BYTE_LIMIT"
                break
            counts["sample_count"] += 1
            if row["sampling_valid"]:
                counts["valid_sample_count"] += 1
                peak = max(peak or 0, row["rss_total_bytes"])
            else:
                counts["invalid_sample_count"] += 1
            if previous_ns is not None:
                max_gap = max(max_gap, (mono - previous_ns) / 1_000_000_000)
            previous_ns = mono
            if windows is not None:
                when = _parse_utc(utc)
                if any(left <= when < right for left, right in windows):
                    sample_rows.append(
                        {
                            "utc": utc,
                            "sampling_valid": row["sampling_valid"],
                            "rss_total_bytes": row["rss_total_bytes"],
                        }
                    )

            deadline += SAMPLE_NS
            now = time.monotonic_ns()
            if deadline < now:
                missed = (now - deadline + SAMPLE_NS - 1) // SAMPLE_NS
                counts["missed_sample_count"] += int(missed)
                deadline += int(missed) * SAMPLE_NS

        ended_utc = _utc_text()
        elapsed = max(0.0, (time.monotonic_ns() - started_ns) / 1_000_000_000)
        receipt_id = receipt.get("receipt_id")
        receipt_success = (
            receipt.get("state") == "terminal"
            and receipt.get("status") in SUCCESS_STATUSES
            and receipt.get("closed") is True
            and isinstance(receipt_id, str)
        )
        quality = (
            counts["sample_count"] > 0
            and counts["invalid_sample_count"] == 0
            and counts["missed_sample_count"] == 0
            and max_gap <= MAX_SAMPLE_GAP_SECONDS
            and not limited
        )
        window_summary = None
        if windows is not None:
            window_summary = summarize_equal_windows(
                sample_rows, warmup_end_utc=warmup_end_utc or "", run_end_utc=run_end_utc or ""
            )
            quality = quality and window_summary["status"] == "WINDOWS_RECORDED"
        summary = {
            "record_type": "summary",
            "schema": 1,
            "started_utc": started_utc,
            "ended_utc": ended_utc,
            "elapsed_seconds": elapsed,
            "stop_reason": stop_reason,
            "completion_receipt_state": receipt.get("state"),
            "completion_status": receipt.get("status"),
            "completion_closed": receipt.get("closed"),
            "completion_receipt_id": receipt_id,
            "completion_receipt_error_code": receipt.get("error_code"),
            "stop_error_codes": stop_error_codes,
            **counts,
            "maximum_sample_gap_seconds": max_gap,
            "peak_rss_bytes": peak,
            "sampling_quality_valid": quality,
            "output_limited": limited,
            "result_complete": bool(receipt_success and quality),
            "window_summary": window_summary,
        }
        if _write_line(stream, summary, size) < 0:
            raise RuntimeError("output_summary_reserve_exhausted")
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--expected-create-time", type=float, required=True)
    parser.add_argument("--completion-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-end-utc")
    parser.add_argument("--run-end-utc")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = observe_process(
            root_pid=args.root_pid,
            expected_create_time=args.expected_create_time,
            completion_receipt=args.completion_receipt,
            output_path=args.output,
            warmup_end_utc=args.warmup_end_utc,
            run_end_utc=args.run_end_utc,
        )
    except (OSError, ValueError, RuntimeError):
        print('{"status":"OBSERVER_ERROR"}')
        return 2
    print(
        json.dumps(
            {
                "status": "COMPLETE" if result["result_complete"] else "INCOMPLETE",
                "sample_count": result["sample_count"],
                "completion_receipt_id": result["completion_receipt_id"],
                "output_bytes": args.output.stat().st_size,
            },
            sort_keys=True,
        )
    )
    return 0 if result["result_complete"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
