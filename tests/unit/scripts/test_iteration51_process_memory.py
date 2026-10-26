"""Focused contracts for the bounded Iteration 51 RSS observer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "observe_iteration51_process_memory.py"
SPEC = importlib.util.spec_from_file_location("iteration51_process_memory", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


def test_synthetic_process_tree_rss_and_sanitized_completion(tmp_path: Path):
    if observer.psutil is None:
        pytest.skip("psutil unavailable")
    ready_path = tmp_path / "ready.json"
    receipt_path = tmp_path / observer.RECEIPT_FILENAME
    output_path = tmp_path / "rss.jsonl"
    child_code = "import time; time.sleep(1.4)"
    runner_code = "\n".join(
        (
            "import json, pathlib, subprocess, sys, time",
            "child = subprocess.Popen([sys.executable, '-c', sys.argv[3]])",
            "pathlib.Path(sys.argv[1]).write_text(json.dumps({'child_pid': child.pid}), encoding='utf-8')",
            "time.sleep(0.2)",
            "child.wait()",
            "pathlib.Path(sys.argv[2]).write_text(json.dumps({",
            "    'status': 'LIVE_RUN_COMPLETE', 'cleanup_complete': True,",
            "    'receipt_id': 'synthetic-run-1'",
            "}), encoding='utf-8')",
        )
    )
    target = subprocess.Popen(
        [sys.executable, "-c", runner_code, str(ready_path), str(receipt_path), child_code]
    )
    try:
        ready_deadline = time.monotonic() + 5.0
        while not ready_path.exists() and time.monotonic() < ready_deadline:
            time.sleep(0.01)
        assert ready_path.exists()
        child_pid = json.loads(ready_path.read_text(encoding="utf-8"))["child_pid"]
        expected_create_time = observer.psutil.Process(target.pid).create_time()

        result = observer.observe_process(
            root_pid=target.pid,
            expected_create_time=expected_create_time,
            completion_receipt=receipt_path,
            output_path=output_path,
        )
        assert target.wait(timeout=5.0) == 0

        records = [
            json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()
        ]
        samples = [record for record in records if record["record_type"] == "sample"]
        assert result["stop_reason"] == "COMPLETION_RECEIPT"
        assert result["completion_receipt_id"] == "synthetic-run-1"
        assert result["result_complete"] is True
        assert samples and all(sample["sampling_valid"] for sample in samples)
        first_tree = samples[0]["process_tree"]
        assert {entry["pid"] for entry in first_tree} >= {target.pid, child_pid}
        assert all(entry["create_time"] is not None for entry in first_tree)
        assert all(entry["rss_bytes"] > 0 for entry in first_tree)
        assert samples[0]["rss_total_bytes"] == sum(entry["rss_bytes"] for entry in first_tree)
        assert b"synthetic-run-1" in output_path.read_bytes()
        assert output_path.stat().st_size <= observer.MAX_OUTPUT_BYTES
        # The public summary consumes sample rows exactly as written to JSONL.
        raw_rows = [json.loads(json.dumps(sample)) for sample in samples]
        summary = observer.summarize_equal_windows(
            raw_rows,
            warmup_end_utc="2000-01-01T00:00:00Z",
            run_end_utc="2000-01-01T02:00:00Z",
        )
        assert summary["unlocated_invalid_sample_count"] == 0
    finally:
        # The fixture owns this short-lived synthetic process and waits for its natural exit.
        if target.poll() is None:
            target.wait(timeout=5.0)


def test_create_time_mismatch_has_no_rss_total(monkeypatch: pytest.MonkeyPatch):
    class FakePsutilError(Exception):
        pass

    class FakeNoSuchProcess(FakePsutilError):
        pass

    class FakeAccessDenied(FakePsutilError):
        pass

    class FakeZombieProcess(FakeNoSuchProcess):
        pass

    class FakeProcess:
        pid = 123

        def create_time(self):
            return 456.0

    class FakePsutil:
        Error = FakePsutilError
        NoSuchProcess = FakeNoSuchProcess
        AccessDenied = FakeAccessDenied
        ZombieProcess = FakeZombieProcess
        Process = lambda _pid: FakeProcess()

    monkeypatch.setattr(observer, "psutil", FakePsutil)
    result = observer._snapshot(123, 123.0)
    assert result["stop_reason"] == "ROOT_IDENTITY_CHANGED"
    assert result["rss_total_bytes"] is None
    assert result["error_codes"] == ["ROOT_CREATE_TIME_MISMATCH"]


def test_child_sampling_error_does_not_become_zero_rss(monkeypatch: pytest.MonkeyPatch):
    class FakePsutilError(Exception):
        pass

    class FakeNoSuchProcess(FakePsutilError):
        pass

    class FakeAccessDenied(FakePsutilError):
        pass

    class FakeZombieProcess(FakeNoSuchProcess):
        pass

    class MemoryInfo:
        rss = 4096

    class FakeProcess:
        def __init__(self, pid: int, create_time: float, *, denied: bool = False):
            self.pid = pid
            self._create_time = create_time
            self.denied = denied

        def create_time(self):
            return self._create_time

        def children(self, recursive: bool):
            assert recursive is True
            return [child]

        def is_running(self):
            return True

        def memory_info(self):
            if self.denied:
                raise FakeAccessDenied()
            return MemoryInfo()

    root = FakeProcess(123, 456.0)
    child = FakeProcess(124, 457.0, denied=True)

    class FakePsutil:
        Error = FakePsutilError
        NoSuchProcess = FakeNoSuchProcess
        AccessDenied = FakeAccessDenied
        ZombieProcess = FakeZombieProcess
        Process = lambda _pid: root

    monkeypatch.setattr(observer, "psutil", FakePsutil)
    result = observer._snapshot(123, 456.0)
    assert result["valid"] is False
    assert result["rss_total_bytes"] is None
    assert result["process_tree"][1]["rss_bytes"] is None
    assert result["process_tree"][1]["error_code"] == "PROCESS_ACCESS_DENIED"


def test_equal_window_summary_rejects_missing_and_invalid_samples():
    start = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)
    run_end = start + timedelta(hours=2)
    samples = [
        {
            "utc": start.isoformat().replace("+00:00", "Z"),
            "sampling_valid": True,
            "rss_total_bytes": 1000,
        },
        {
            "utc": (run_end - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "sampling_valid": True,
            "rss_total_bytes": 1200,
        },
        {"utc": "not-a-time", "sampling_valid": False, "rss_total_bytes": None},
    ]
    summary = observer.summarize_equal_windows(
        samples,
        warmup_end_utc=start.isoformat().replace("+00:00", "Z"),
        run_end_utc=run_end.isoformat().replace("+00:00", "Z"),
    )
    assert summary["status"] == "INSUFFICIENT_COVERAGE"
    assert summary["unlocated_invalid_sample_count"] == 1
    assert all(window["coverage_status"] == "INSUFFICIENT" for window in summary["windows"])


def test_equal_window_summary_accepts_raw_sample_rows():
    start = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)
    run_end = start + timedelta(hours=2)
    rows = []
    for window_start in (start, run_end - timedelta(seconds=observer.WINDOW_SECONDS)):
        for second in range(observer.WINDOW_SECONDS):
            rows.append(
                {
                    "record_type": "sample",
                    "utc": (window_start + timedelta(seconds=second))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "sampling_valid": True,
                    "rss_total_bytes": 4096,
                }
            )
    raw_jsonl_rows = [json.loads(json.dumps(row)) for row in rows]
    summary = observer.summarize_equal_windows(
        raw_jsonl_rows,
        warmup_end_utc=start.isoformat().replace("+00:00", "Z"),
        run_end_utc=run_end.isoformat().replace("+00:00", "Z"),
    )
    assert summary["status"] == "WINDOWS_RECORDED"
    assert [window["valid_samples"] for window in summary["windows"]] == [1800, 1800]


def test_slow_sampling_skips_deadlines_without_catchup_burst(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    clock = {"ns": 0, "receipt_reads": 0}

    class FakePsutil:
        pass

    monkeypatch.setattr(observer, "psutil", FakePsutil)
    monkeypatch.setattr(observer.time, "monotonic_ns", lambda: clock["ns"])
    monkeypatch.setattr(
        observer.time,
        "sleep",
        lambda seconds: clock.__setitem__("ns", clock["ns"] + round(seconds * 1_000_000_000)),
    )

    def receipt(_path):
        clock["receipt_reads"] += 1
        if clock["receipt_reads"] < 3:
            return {"state": "absent"}
        return {
            "state": "terminal",
            "status": "LIVE_RUN_COMPLETE",
            "closed": True,
            "receipt_id": "synthetic-clock",
            "error_code": None,
        }

    def slow_snapshot(_pid, _created):
        clock["ns"] += 1_500_000_000
        return {
            "valid": True,
            "stop_reason": None,
            "rss_total_bytes": 4096,
            "process_tree": [{"pid": 123, "create_time": 1.0, "rss_bytes": 4096}],
            "error_codes": [],
        }

    monkeypatch.setattr(observer, "_read_receipt", receipt)
    monkeypatch.setattr(observer, "_snapshot", slow_snapshot)
    output = tmp_path / "slow.jsonl"
    result = observer.observe_process(
        root_pid=123,
        expected_create_time=1.0,
        completion_receipt=tmp_path / observer.RECEIPT_FILENAME,
        output_path=output,
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    samples = [row for row in rows if row["record_type"] == "sample"]
    assert len(samples) == 2
    assert samples[1]["monotonic_ns"] - samples[0]["monotonic_ns"] >= observer.SAMPLE_NS
    assert result["missed_sample_count"] == 2
    assert result["sampling_quality_valid"] is False
    assert result["result_complete"] is False


def test_terminal_receipt_without_identifier_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    clock = {"ns": 0, "receipt_reads": 0}

    class FakePsutil:
        pass

    monkeypatch.setattr(observer, "psutil", FakePsutil)
    monkeypatch.setattr(observer.time, "monotonic_ns", lambda: clock["ns"])
    monkeypatch.setattr(
        observer.time,
        "sleep",
        lambda seconds: clock.__setitem__("ns", clock["ns"] + round(seconds * 1_000_000_000)),
    )

    def receipt(_path):
        clock["receipt_reads"] += 1
        if clock["receipt_reads"] == 1:
            return {"state": "absent"}
        return {
            "state": "terminal",
            "status": "LIVE_RUN_COMPLETE",
            "closed": True,
            "receipt_id": None,
            "error_code": "RECEIPT_ID_MISSING_OR_INVALID",
        }

    monkeypatch.setattr(observer, "_read_receipt", receipt)
    monkeypatch.setattr(
        observer,
        "_snapshot",
        lambda _pid, _created: {
            "valid": True,
            "stop_reason": None,
            "rss_total_bytes": 4096,
            "process_tree": [{"pid": 123, "create_time": 1.0, "rss_bytes": 4096}],
            "error_codes": [],
        },
    )
    result = observer.observe_process(
        root_pid=123,
        expected_create_time=1.0,
        completion_receipt=tmp_path / observer.RECEIPT_FILENAME,
        output_path=tmp_path / "missing-receipt-id.jsonl",
    )
    assert result["completion_receipt_id"] is None
    assert result["completion_receipt_error_code"] == "RECEIPT_ID_MISSING_OR_INVALID"
    assert result["sampling_quality_valid"] is True
    assert result["result_complete"] is False


def test_equal_window_bounds_must_be_explicit_utc_and_nonoverlapping():
    start = "2026-10-27T01:00:00Z"
    assert (
        observer.summarize_equal_windows(
            (), warmup_end_utc="2026-10-27T01:00:00", run_end_utc="2026-10-27T03:00:00Z"
        )["status"]
        == "INVALID_WINDOW_BOUNDS"
    )
    assert (
        observer.summarize_equal_windows(
            (), warmup_end_utc=start, run_end_utc="2026-10-27T01:59:59Z"
        )["status"]
        == "INVALID_WINDOW_BOUNDS"
    )


def test_completion_receipt_rejects_unwhitelisted_content(tmp_path: Path):
    receipt = tmp_path / observer.RECEIPT_FILENAME
    receipt.write_text(
        json.dumps(
            {
                "status": "LIVE_RUN_COMPLETE",
                "cleanup_complete": True,
                "receipt_id": "synthetic-run-2",
                "untrusted_text": "must-not-be-copied",
            }
        ),
        encoding="utf-8",
    )
    observed = observer._read_receipt(receipt)
    assert observed == {"state": "invalid", "error_code": "RECEIPT_FIELDS_NOT_SANITIZED"}
    assert "must-not-be-copied" not in json.dumps(observed)
