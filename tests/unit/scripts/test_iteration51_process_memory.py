"""Focused contracts for the bounded Iteration 51 RSS observer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace
from threading import Event

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "observe_iteration51_process_memory.py"
SPEC = importlib.util.spec_from_file_location("iteration51_process_memory", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)
R10_SCRIPT = (
    ROOT
    / "tests"
    / "fixtures"
    / "iteration51"
    / "r10_frozen_disabled"
    / "i51_root_golden_minute_actual_r10_memory_supervised_20261028.py"
)
R10_FIXTURE_SHA256 = "b42d238f021bb3ffe927a4c4fa0ab324eceea7988ef294748b8af3d9671dc883"
SYNTHETIC_PROFILE_BYTES = b'{"selection":{"query_mode":"synthetic"}}\n'
SYNTHETIC_POSTFLIGHT_BYTES = b"DRAFT_UNEXECUTABLE = True\nSYNTHETIC_POSTFLIGHT = True\n"
R10_SPEC = importlib.util.spec_from_file_location("i51_root_memory_r10", R10_SCRIPT)
assert R10_SPEC is not None and R10_SPEC.loader is not None
r10 = importlib.util.module_from_spec(R10_SPEC)
R10_SPEC.loader.exec_module(r10)


def test_r10_public_fixture_is_frozen_disabled_draft():
    fixture_bytes = R10_SCRIPT.read_bytes()
    assert r10.hashlib.sha256(fixture_bytes).hexdigest() == R10_FIXTURE_SHA256
    assert r10.DRAFT_UNEXECUTABLE is True
    assert r10.R10_SUPERVISOR_ENABLED is False
    fixture_source = fixture_bytes.decode("utf-8")
    assert "'process_tree_memory_observation': 'NOT_RUN_IN_R9'" in fixture_source
    assert "'supervisor_rss_report': {" in fixture_source
    assert "R10's sibling" in fixture_source


def _synthetic_live_capacity_report(logical_run_id, pid, create_time, epoch_id, calendar_id):
    cohort_id = "alpha003:{}:{}".format(calendar_id, epoch_id)
    boundary = {
        "ordinal_source": "live_cohort_batch_slot_index_zero_based",
        "grid_ordinal": 7,
        "slot_index": 7,
        "cohort_id": cohort_id,
        "epoch_id": epoch_id,
        "calendar_id": calendar_id,
        "batch_id": "synthetic-batch-7",
        "engine_phase": "grid_recorded",
        "system_utc_epoch_ns": 1_798_000_000_000_000_000,
        "monotonic_before_ns": 10_000,
        "monotonic_after_ns": 10_010,
    }
    sample = {
        "schema": "backtrader.live_capacity_snapshot.v1",
        "run_id": logical_run_id,
        "ordinal": 7,
        "status": "OBSERVED",
        "acceptance_evaluated": False,
        "run_binding": {
            "run_id": logical_run_id,
            "epoch_id": epoch_id,
            "process_id": pid,
            "process_create_time": create_time,
        },
        "ready_boundary": boundary,
        "cohort_identity": {
            "status": "OBSERVED",
            "cohort_id": cohort_id,
            "epoch_id": epoch_id,
        },
        "lines": {
            "status": "OBSERVED",
            "graph_node_count": 88,
            "graph_reference_count": 99,
            "line_buffer_count": 77,
            "bounded_line_buffer_count": 77,
            "line_capacity_sum": 15_000,
            "retained_line_value_count": 12_000,
        },
        "cohort": {
            "status": "OBSERVED",
            "member_count": 87,
            "pending_slot_count": 0,
        },
        "diagnostics": {
            "status": "OBSERVED",
            "factor_count": 174,
            "call_count": 25_000,
            "once_range_count": 0,
        },
        "strategy_events": {
            "status": "OBSERVED",
            "events": {
                "order_events": {"count": 0},
                "trade_events": {"count": 0},
            },
        },
        "orders": {
            "status": "OBSERVED",
            "active_order_count": 0,
            "unknown_order_count": 0,
            "terminal_order_count": 0,
        },
    }
    return {
        "schema": "backtrader.live_capacity_run_report.v1",
        "run_id": logical_run_id,
        "status": "RECORDED_NOT_EVALUATED",
        "acceptance_evaluated": False,
        "window_evaluation": "NOT_EVALUATED",
        "growth_evaluation": "NOT_EVALUATED",
        "stability_peak_claimed": False,
        "epoch_id": epoch_id,
        "calendar_id": calendar_id,
        "calendar_slot_count": 195,
        "expected_ordinals": (7,),
        "max_samples": 16,
        "sample_count": 1,
        "process_identity": {
            "status": "OBSERVED",
            "pid": pid,
            "create_time": create_time,
        },
        "first_ready_boundary": {"epoch_id": epoch_id, "calendar_id": calendar_id},
        "samples": (sample,),
        "issues": (),
    }


def test_r10_live_capacity_projection_binds_same_call_and_keeps_acceptance_unevaluated(
    monkeypatch: pytest.MonkeyPatch,
):
    run_uuid = "i51-" + "a" * 32
    logical_run_id = "i5051:synthetic:logical-run"
    pid = 43210
    create_time = 1790000000.25
    epoch_id = 3
    calendar_id = "synthetic-calendar-r10"
    monkeypatch.setattr(r10, "MEMORY_RUN_ID", run_uuid)
    monkeypatch.setattr(
        r10,
        "MEMORY_TARGET_IDENTITY",
        {"pid": pid, "create_time": create_time},
    )
    config = {
        "live": {"logical_run_id": logical_run_id},
        "cohort": {"epoch_id": epoch_id, "calendar_id": calendar_id},
    }
    summary = {
        "live_capacity": _synthetic_live_capacity_report(
            logical_run_id, pid, create_time, epoch_id, calendar_id
        )
    }

    projected = r10.public_live_capacity(summary, config)
    assert projected["status"] == "BOUND_RECORDED_NOT_EVALUATED"
    assert projected["acceptance_evaluated"] is False
    assert projected["window_evaluation"] == "NOT_EVALUATED"
    assert projected["growth_evaluation"] == "NOT_EVALUATED"
    assert projected["stability_peak_claimed"] is False
    assert projected["binding"] == {
        "association": "SAME_TARGET_RUN_CALL_CONTEXT",
        "supervisor_run_uuid": run_uuid,
        "logical_run_id": logical_run_id,
        "root_pid": pid,
        "root_create_time": create_time,
        "epoch_id": epoch_id,
        "calendar_id": calendar_id,
    }
    assert projected["sample_count"] == 1
    assert projected["samples"][0]["batch_id"] == "synthetic-batch-7"
    assert projected["samples"][0]["counts"]["line_capacity_sum"] == 15_000
    runner = SimpleNamespace(
        _live_epoch_retired=lambda _summary: True,
        _live_epoch_controlled_stopped=lambda _summary: True,
    )
    summary.update(
        {
            "status": "LIVE_RUN_COMPLETE",
            "routes": {},
            "decision_tape": {},
            "_plan": {
                "targets": tuple(range(87)),
                "grid": SimpleNamespace(to_dict=lambda: {"minutes": list(range(195))}),
            },
            "factor_mode": "native",
            "write_mode": False,
            "cleanup_complete": True,
            "strategy_shutdown_ready": True,
            "strategy_shutdown_post_join_confirmed": True,
            "resource_shutdown": [],
        }
    )
    run_projection = r10.public_summary(summary, runner, config)
    assert run_projection["live_capacity"] == projected
    assert run_projection["write_mode_disabled"] is True
    assert r10.DRAFT_UNEXECUTABLE is True
    assert r10.R10_SUPERVISOR_ENABLED is False


@pytest.mark.parametrize("empty_field", ("samples", "expected_ordinals"))
def test_r10_live_capacity_projection_rejects_empty_capture_sequences(
    empty_field: str, monkeypatch: pytest.MonkeyPatch
):
    run_uuid = "i51-" + "c" * 32
    logical_run_id = "i5051:synthetic:empty-capacity"
    pid = 65432
    create_time = 1790000001.0
    epoch_id = 5
    calendar_id = "synthetic-calendar-empty-r10"
    report = _synthetic_live_capacity_report(
        logical_run_id, pid, create_time, epoch_id, calendar_id
    )
    if empty_field == "samples":
        report["samples"] = ()
        report["sample_count"] = 0
    else:
        report["expected_ordinals"] = ()

    monkeypatch.setattr(r10, "MEMORY_RUN_ID", run_uuid)
    monkeypatch.setattr(
        r10,
        "MEMORY_TARGET_IDENTITY",
        {"pid": pid, "create_time": create_time},
    )
    config = {
        "live": {"logical_run_id": logical_run_id},
        "cohort": {"epoch_id": epoch_id, "calendar_id": calendar_id},
    }

    projected = r10.public_live_capacity({"live_capacity": report}, config)
    assert projected["status"] == "INCOMPLETE"
    assert projected["reason_code"] == "LIVE_CAPACITY_REPORT_BINDING_INVALID"
    assert projected["acceptance_evaluated"] is False
    assert projected["samples"] == []


@pytest.mark.parametrize(
    "mismatch",
    (
        "logical_run_id",
        "pid",
        "create_time",
        "epoch_id",
        "calendar_id",
        "sample_process",
        "sample_calendar",
        "missing_supervisor_uuid",
    ),
)
def test_r10_live_capacity_projection_rejects_identity_drift(
    mismatch: str, monkeypatch: pytest.MonkeyPatch
):
    run_uuid = "i51-" + "b" * 32
    logical_run_id = "i5051:synthetic:logical-run"
    pid = 54321
    create_time = 1790000000.5
    epoch_id = 4
    calendar_id = "synthetic-calendar-r10"
    report = _synthetic_live_capacity_report(
        logical_run_id, pid, create_time, epoch_id, calendar_id
    )
    config = {
        "live": {"logical_run_id": logical_run_id},
        "cohort": {"epoch_id": epoch_id, "calendar_id": calendar_id},
    }
    identity = {"pid": pid, "create_time": create_time}
    if mismatch == "logical_run_id":
        report["run_id"] = "other-logical-run"
    elif mismatch == "pid":
        report["process_identity"]["pid"] += 1
    elif mismatch == "create_time":
        report["process_identity"]["create_time"] += 1.0
    elif mismatch == "epoch_id":
        report["epoch_id"] += 1
    elif mismatch == "calendar_id":
        report["calendar_id"] = "other-calendar"
    elif mismatch == "sample_process":
        report["samples"][0]["run_binding"]["process_id"] += 1
    elif mismatch == "sample_calendar":
        report["samples"][0]["ready_boundary"]["calendar_id"] = "other-calendar"
    elif mismatch == "missing_supervisor_uuid":
        run_uuid = None

    monkeypatch.setattr(r10, "MEMORY_RUN_ID", run_uuid)
    monkeypatch.setattr(r10, "MEMORY_TARGET_IDENTITY", identity)
    projected = r10.public_live_capacity({"live_capacity": report}, config)
    assert projected["status"] == "INCOMPLETE"
    assert projected["acceptance_evaluated"] is False
    assert projected["samples"] == []


def test_r10_live_run_call_explicitly_enables_capacity_capture():
    tree = ast.parse(R10_SCRIPT.read_text(encoding="utf-8"))
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Attribute)
            and isinstance(first.value, ast.Name)
            and first.value.id == "runner"
            and first.attr == "run_live"
        ):
            matches.append({keyword.arg: keyword.value for keyword in node.keywords})
    assert len(matches) == 1
    capture = matches[0].get("_capture_live_capacity")
    assert isinstance(capture, ast.Constant) and capture.value is True


def test_synthetic_process_tree_rss_and_sanitized_completion(tmp_path: Path):
    if observer.psutil is None:
        pytest.skip("psutil unavailable")
    ready_path = tmp_path / observer.READY_FILENAME
    receipt_path = tmp_path / observer.RECEIPT_FILENAME
    output_path = tmp_path / "rss.jsonl"
    run_id = "synthetic-run-1"
    child_code = "import time; time.sleep(1.4)"
    runner_code = "\n".join(
        (
            "import datetime, json, os, pathlib, subprocess, sys, time",
            "import psutil",
            "ready = pathlib.Path(sys.argv[1])",
            "deadline = time.monotonic() + 5.0",
            "while not ready.exists() and time.monotonic() < deadline: time.sleep(0.01)",
            "payload = json.loads(ready.read_text(encoding='utf-8'))",
            "assert payload['run_id'] == sys.argv[4]",
            "assert payload['root_pid'] == os.getpid()",
            "assert payload['sampling_valid'] is True",
            "ready_mono = time.monotonic_ns()",
            "start_mono = time.monotonic_ns()",
            "child = subprocess.Popen([sys.executable, '-c', sys.argv[3]])",
            "pathlib.Path(sys.argv[5]).write_text(json.dumps({'child_pid': child.pid, 'ready_mono': payload['sample_monotonic_ns'], 'start_mono': start_mono}), encoding='utf-8')",
            "time.sleep(0.2)",
            "child.wait()",
            "next_mono = time.monotonic_ns()",
            "close_deadline = time.monotonic() + 1.0",
            "while time.monotonic_ns() <= next_mono and time.monotonic() < close_deadline: time.sleep(0.01)",
            "close_mono = time.monotonic_ns()",
            "assert close_mono > next_mono",
            "target = pathlib.Path(sys.argv[2])",
            "payload = {",
            "    'schema': 1, 'status': 'LIVE_RUN_COMPLETE', 'closed': True,",
            "    'cleanup_complete': True, 'receipt_id': sys.argv[4] + ':close',",
            "    'run_id': sys.argv[4], 'root_pid': os.getpid(),",
            "    'root_create_time': psutil.Process().create_time(),",
            "    'live_ready_boundary_id': sys.argv[4] + ':live-ready',",
            "    'live_ready_monotonic_ns': ready_mono,",
            "    'live_next_boundary_id': sys.argv[4] + ':first-next',",
            "    'live_next_monotonic_ns': next_mono,",
            "    'close_utc': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),",
            "    'close_monotonic_ns': close_mono,",
            "    'close_clock_pair_span_ns': 1000,",
            "}",
            "temp = target.with_name('.receipt.tmp')",
            "temp.write_text(json.dumps(payload), encoding='utf-8')",
            "os.replace(temp, target)",
        )
    )
    target = subprocess.Popen(
        [
            sys.executable,
            "-c",
            runner_code,
            str(ready_path),
            str(receipt_path),
            child_code,
            run_id,
            str(tmp_path / "target_child.json"),
        ]
    )
    sampler = None
    try:
        expected_create_time = observer.psutil.Process(target.pid).create_time()
        sampler = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                "--root-pid",
                str(target.pid),
                "--expected-create-time",
                repr(expected_create_time),
                "--run-id",
                run_id,
                "--completion-receipt",
                str(receipt_path),
                "--ready-path",
                str(ready_path),
                "--output",
                str(output_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = sampler.communicate(timeout=10.0)
        assert sampler.returncode == 0, (
            stdout,
            stderr,
            output_path.read_text(encoding="utf-8") if output_path.exists() else None,
        )
        result = json.loads(stdout)
        assert target.wait(timeout=5.0) == 0
        child_info = json.loads(
            (tmp_path / "target_child.json").read_text(encoding="utf-8")
        )
        child_pid = child_info["child_pid"]
        assert child_info["start_mono"] > child_info["ready_mono"]

        records = [
            json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()
        ]
        samples = [record for record in records if record["record_type"] == "sample"]
        summary = records[-1]
        assert summary["stop_reason"] == "COMPLETION_RECEIPT"
        assert summary["completion_receipt_id"] == f"{run_id}:close"
        assert summary["completion_run_id"] == run_id
        assert summary["completion_root_pid"] == target.pid
        assert summary["completion_root_create_time"] == expected_create_time
        assert summary["completion_cleanup_complete"] is True
        assert result["status"] == "COMPLETE"
        assert summary["result_complete"] is True
        assert samples and all(sample["sampling_valid"] for sample in samples)
        first_tree = samples[0]["process_tree"]
        assert {entry["pid"] for entry in first_tree} == {target.pid}
        assert all(entry["pid"] != sampler.pid for sample in samples for entry in sample["process_tree"])
        descendant_rows = [
            sample for sample in samples
            if any(entry["pid"] == child_pid for entry in sample["process_tree"])
        ]
        assert descendant_rows
        assert all(entry["create_time"] is not None for entry in descendant_rows[0]["process_tree"])
        assert all(entry["rss_bytes"] > 0 for entry in descendant_rows[0]["process_tree"])
        assert descendant_rows[0]["rss_total_bytes"] == sum(
            entry["rss_bytes"] for entry in descendant_rows[0]["process_tree"]
        )
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
        # The fixture owns both short-lived synthetic processes and waits for natural exits.
        if target.poll() is None:
            target.wait(timeout=5.0)
        if sampler is not None and sampler.poll() is None:
            sampler.wait(timeout=5.0)


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


def test_r10_analysis_uses_monotonic_boundaries_and_fails_closed(tmp_path: Path):
    start = datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc)
    start_utc = start.isoformat().replace("+00:00", "Z")
    live_ready = start + timedelta(minutes=2)
    live_ready_utc = live_ready.isoformat().replace("+00:00", "Z")
    close = live_ready + timedelta(hours=1)
    close_utc = close.isoformat().replace("+00:00", "Z")
    start_mono = 50_000_000_000
    live_ready_mono = start_mono + 120 * 1_000_000_000
    live_next_mono = live_ready_mono + 10 * 1_000_000_000
    close_mono = live_ready_mono + 3600 * 1_000_000_000
    run_id = "i51-" + "a" * 32
    root_pid = 12345
    sampler_pid = 12346
    create_time = 456.5
    receipt_id = f"{run_id}:close"
    header = {
        "record_type": "header", "schema": 1, "run_id": run_id,
        "root_pid": root_pid, "expected_create_time": create_time,
        "sampler_pid": sampler_pid,
    }
    summary = {
        "record_type": "summary", "schema": 1, "run_id": run_id,
        "root_pid": root_pid, "expected_create_time": create_time,
        "sampler_pid": sampler_pid, "stop_reason": "COMPLETION_RECEIPT",
        "completion_receipt_state": "terminal", "completion_status": "LIVE_RUN_COMPLETE",
        "completion_closed": True, "completion_cleanup_complete": True,
        "completion_receipt_id": receipt_id, "completion_run_id": run_id,
        "completion_root_pid": root_pid, "completion_root_create_time": create_time,
        "completion_live_ready_boundary_id": f"{run_id}:live-ready",
        "completion_live_ready_monotonic_ns": live_ready_mono,
        "completion_live_next_boundary_id": f"{run_id}:first-next",
        "completion_live_next_monotonic_ns": live_next_mono,
        "close_utc": close_utc, "close_monotonic_ns": close_mono,
        "close_clock_pair_span_ns": 1000, "sampling_quality_valid": True,
    }
    rows = [header]
    def sample(mono, when, rss=4096):
        return {
            "record_type": "sample", "monotonic_ns": mono,
            "utc": when.isoformat().replace("+00:00", "Z"),
            "sampling_valid": True, "rss_total_bytes": rss,
            "process_tree": [{"pid": root_pid, "create_time": create_time, "rss_bytes": rss}],
        }
    rows.append(sample(start_mono - 1, start - timedelta(seconds=1)))
    rows.append(sample(start_mono + 60 * 1_000_000_000, start + timedelta(seconds=60)))
    for second in range(3600):
        sample_utc = live_ready + timedelta(seconds=second)
        if second == 100:
            sample_utc = live_ready + timedelta(seconds=99)
        rows.append(sample(live_ready_mono + second * 1_000_000_000, sample_utc, 4096 + second))
    rows.append(sample(close_mono, close))
    rows.append(summary)
    output = tmp_path / "process_rss.jsonl"
    output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    start_record = {
        "schema": 1, "run_id": run_id, "root_pid": root_pid,
        "root_create_time": create_time, "start_utc": start_utc,
        "start_monotonic_ns": start_mono, "clock_pair_span_ns": 1000,
    }
    live_ready_record = {
        "schema": 1, "boundary_id": f"{run_id}:live-ready", "run_id": run_id,
        "root_pid": root_pid, "root_create_time": create_time,
        "readiness": "LIVE_READY", "replay_mode": False,
        "cohort_id": "synthetic-cohort", "epoch_id": 1,
        "calendar_id": "synthetic-calendar", "batch_id": "synthetic-batch-4",
        "slot_index": 4,
        "ready_utc": live_ready_utc, "ready_monotonic_ns": live_ready_mono,
        "clock_pair_span_ns": 1000,
    }
    live_next_record = {
        "schema": 1, "boundary_id": f"{run_id}:first-next", "run_id": run_id,
        "root_pid": root_pid, "root_create_time": create_time,
        "readiness": "LIVE_READY", "replay_mode": False,
        "cohort_id": "synthetic-cohort", "epoch_id": 1,
        "calendar_id": "synthetic-calendar", "batch_id": "synthetic-batch-5",
        "slot_index": 5,
        "live_ready_boundary_id": f"{run_id}:live-ready",
        "next_utc": (live_ready + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
        "next_monotonic_ns": live_next_mono, "clock_pair_span_ns": 1000,
    }
    close_record = {
        "schema": 1, "status": "LIVE_RUN_COMPLETE", "closed": True,
        "cleanup_complete": True, "receipt_id": receipt_id, "run_id": run_id,
        "root_pid": root_pid, "root_create_time": create_time,
        "live_ready_boundary_id": f"{run_id}:live-ready",
        "live_ready_monotonic_ns": live_ready_mono,
        "live_next_boundary_id": f"{run_id}:first-next",
        "live_next_monotonic_ns": live_next_mono,
        "close_utc": close_utc, "close_monotonic_ns": close_mono,
        "close_clock_pair_span_ns": 1000,
    }
    def analyze(start_value=start_record, ready_value=live_ready_record, close_value=close_record):
        return r10.analyze_memory_capture(
            observer, output_path=output, run_id=run_id, root_pid=root_pid,
            root_create_time=create_time, sampler_pid=sampler_pid,
            start_record=start_value, live_ready_record=ready_value,
            live_next_record=live_next_record,
            close_record=close_value,
        )
    result = analyze()
    assert result["status"] == "WINDOWS_RECORDED", result
    assert result["memory_acceptance"] == "NOT_EVALUATED"
    assert result["pre_run_sample_count_filtered"] == 1
    assert result["pre_live_ready_sample_count_filtered"] == 1
    assert result["post_close_sample_count_filtered"] == 1
    assert result["first_live_ready_utc"] == live_ready_utc
    assert result["first_live_ready_monotonic_ns"] == live_ready_mono
    assert result["first_live_next_monotonic_ns"] == live_next_mono
    assert live_next_record["batch_id"] != live_ready_record["batch_id"]
    assert live_next_record["slot_index"] > live_ready_record["slot_index"]
    assert result["window_start_source"] == "FIRST_LIVE_READY_PAIRED_OS_UTC_MONOTONIC"
    assert result["window_summary"]["window_clock_source"] == "MONOTONIC_WITH_INDEPENDENT_UTC_CHECK"
    assert [window["valid_samples"] for window in result["window_summary"]["windows"]] == [1800, 1800]
    assert [window["median_rss_bytes"] for window in result["window_summary"]["windows"]] == [
        4995.5, 6795.5,
    ]
    assert result["rss_growth_diagnostic"] == {
        "status": "WITHIN_DIAGNOSTIC_LIMIT",
        "comparison_scope": "DIAGNOSTIC_ONLY",
        "stable_rss_established": False,
        "baseline_source": "FIRST_WINDOW_MEDIAN_PROXY",
        "first_window_median_rss_bytes": 4995.5,
        "last_window_median_rss_bytes": 6795.5,
        "growth_bytes": 1800.0,
        "diagnostic_limit_bytes": 32 * 1024 * 1024,
        "object_growth_evidence": "NOT_COLLECTED",
        "formal_memory_acceptance": "NOT_EVALUATED",
    }
    assert result["object_growth_evidence"] == "NOT_COLLECTED"
    assert result["memory_acceptance"] == "NOT_EVALUATED"

    assert analyze(start_value=None)["failure_code"] == "RUN_START_RECORD_INVALID"
    assert r10.analyze_memory_capture(
        observer, output_path=output, run_id=run_id, root_pid=root_pid,
        root_create_time=create_time, sampler_pid=sampler_pid,
        start_record=start_record, live_ready_record=live_ready_record,
        live_next_record=None, close_record=close_record,
    )["failure_code"] == "LIVE_NEXT_RECORD_MISSING_OR_INVALID"
    missing_ready = analyze(ready_value=None)
    assert missing_ready["status"] == "INCOMPLETE"
    assert missing_ready["failure_code"] == "LIVE_READY_RECORD_MISSING_OR_INVALID"
    reordered = dict(live_ready_record, ready_monotonic_ns=start_mono)
    output.write_text(
        "".join(json.dumps(row) + "\n" for row in rows[:-1])
        + json.dumps(dict(summary, completion_live_ready_monotonic_ns=start_mono)) + "\n",
        encoding="utf-8",
    )
    wrong_order = analyze(
        ready_value=reordered,
        close_value=dict(close_record, live_ready_monotonic_ns=start_mono),
    )
    assert wrong_order["status"] == "INCOMPLETE"
    assert wrong_order["failure_code"] == "LIVE_READY_BOUNDARY_ORDER_INVALID"
    output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    wrong_identity = dict(live_ready_record, root_pid=root_pid + 1)
    assert analyze(ready_value=wrong_identity)["failure_code"] == "LIVE_READY_TARGET_BINDING_INVALID"
    unclosed = dict(close_record, status="LIVE_RUN_INCOMPLETE", cleanup_complete=False)
    incomplete = analyze(close_value=unclosed)
    assert incomplete["status"] == "INCOMPLETE"
    assert incomplete["memory_acceptance"] == "NOT_EVALUATED"


def test_r10_rss_growth_over_limit_remains_diagnostic_only():
    first = 100 * 1024 * 1024
    diagnostic = r10._rss_growth_diagnostic({
        "status": "WINDOWS_RECORDED",
        "windows": [
            {"median_rss_bytes": first},
            {"median_rss_bytes": first + 33 * 1024 * 1024},
        ],
    })
    assert diagnostic["status"] == "OVER_DIAGNOSTIC_LIMIT"
    assert diagnostic["diagnostic_limit_bytes"] == 32 * 1024 * 1024
    assert diagnostic["growth_bytes"] == 33 * 1024 * 1024
    assert diagnostic["stable_rss_established"] is False
    assert diagnostic["formal_memory_acceptance"] == "NOT_EVALUATED"
    assert diagnostic["object_growth_evidence"] == "NOT_COLLECTED"



def test_r10_postflight_must_bind_same_target_run_and_resource_close():
    run_id = "i51-" + "c" * 32
    root_pid = 4567
    create_time = 123.5
    ready_mono = 9_000_000_000
    next_mono = ready_mono + 1_000_000_000
    close_mono = ready_mono + 60_000_000_000
    close = {
        "schema": 1,
        "status": "LIVE_RUN_COMPLETE",
        "closed": True,
        "cleanup_complete": True,
        "receipt_id": f"{run_id}:close",
        "run_id": run_id,
        "root_pid": root_pid,
        "root_create_time": create_time,
        "live_ready_boundary_id": f"{run_id}:live-ready",
        "live_ready_monotonic_ns": ready_mono,
        "live_next_boundary_id": f"{run_id}:first-next",
        "live_next_monotonic_ns": next_mono,
        "close_utc": "2026-10-28T01:01:00Z",
        "close_monotonic_ns": close_mono,
        "close_clock_pair_span_ns": 1000,
    }
    checks = {name: True for name in r10.TARGET_POSTFLIGHT_CHECKS}
    payload = {
        "root_pid": root_pid,
        "phase": "complete",
        "status": "FULL_POOL_TAPE_WITNESS_PASS",
        "private_context_closed": True,
        "fullpool_tape_witness_pass": True,
        "fullpool_acceptance_checks": checks,
        "postflight": {"status": "PASS"},
        "memory_binding": {
            "schema": 1,
            "run_id": run_id,
            "root_pid": root_pid,
            "root_create_time": create_time,
            "live_ready_boundary_id": f"{run_id}:live-ready",
            "live_ready_monotonic_ns": ready_mono,
            "live_next_boundary_id": f"{run_id}:first-next",
            "live_next_monotonic_ns": next_mono,
            "resource_close_receipt_id": f"{run_id}:close",
            "resource_close_monotonic_ns": close_mono,
        },
    }
    bound = r10.validate_target_postflight_result(
        payload,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=create_time,
        close_record=close,
    )
    assert bound["status"] == "PASS"
    assert bound["bound_run_id"] == run_id
    assert bound["bound_root_pid"] == root_pid

    wrong_target = dict(payload, memory_binding=dict(payload["memory_binding"], root_pid=root_pid + 1))
    rejected = r10.validate_target_postflight_result(
        wrong_target,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=create_time,
        close_record=close,
    )
    assert rejected["status"] == "INCOMPLETE"
    assert rejected["failure_code"] == "TARGET_MEMORY_TARGET_BINDING_MISMATCH"
    failed_check = dict(payload, fullpool_acceptance_checks=dict(checks, live_run_complete=False))
    rejected = r10.validate_target_postflight_result(
        failed_check,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=create_time,
        close_record=close,
    )
    assert rejected["status"] == "INCOMPLETE"
    assert rejected["failure_code"] == "TARGET_POSTFLIGHT_NOT_PASS"


def test_r10_protocol_records_are_atomic_and_preserve_incomplete_close(tmp_path: Path, monkeypatch):
    run_id = "i51-" + "b" * 32
    target_identity = {"pid": 321, "create_time": 654.25}
    monkeypatch.setattr(r10, "MEMORY_CONTROL", tmp_path)
    monkeypatch.setattr(r10, "MEMORY_RUN_ID", run_id)
    monkeypatch.setattr(r10, "MEMORY_TARGET_IDENTITY", target_identity)
    monkeypatch.setattr(r10, "MEMORY_LIVE_READY_RECORD", None)
    monkeypatch.setattr(r10, "MEMORY_LIVE_NEXT_RECORD", None)
    monkeypatch.setattr(
        r10,
        "ROOT_STATE",
        {
            "closed": True,
            "observer_sink": {"cleanup_confirmed": True, "timer_joined": True},
        },
    )

    start = r10.publish_run_start_record()
    start_path = tmp_path / r10.START_NAME
    start_bytes = start_path.read_bytes()
    assert start_bytes.endswith(b"\n")
    assert json.loads(start_bytes)["start_monotonic_ns"] == start["start_monotonic_ns"]
    with pytest.raises(FileExistsError):
        r10.publish_run_start_record()
    live_ready = r10.publish_live_ready_record({
        "readiness": "LIVE_READY",
        "replay_mode": False,
        "cohort_id": "synthetic-cohort",
        "epoch_id": 1,
        "calendar_id": "synthetic-calendar",
        "batch_id": "synthetic-batch-4",
        "slot_index": 4,
    })
    live_next = r10.publish_live_next_record({
        "readiness": "LIVE_READY",
        "replay_mode": False,
        "cohort_id": "synthetic-cohort",
        "epoch_id": 1,
        "calendar_id": "synthetic-calendar",
        "batch_id": "synthetic-batch-5",
        "slot_index": 5,
    })

    complete = r10.publish_close_record(
        {"status": "LIVE_RUN_COMPLETE", "cleanup_complete": True},
        closed=True,
    )
    receipt_path = tmp_path / r10.RECEIPT_NAME
    receipt_bytes = receipt_path.read_bytes()
    assert receipt_bytes.endswith(b"\n")
    assert json.loads(receipt_bytes) == complete
    observed = observer._read_receipt(
        receipt_path,
        run_id=run_id,
        root_pid=target_identity["pid"],
        expected_create_time=target_identity["create_time"],
    )
    assert observed["state"] == "terminal", (observed, live_ready, complete)
    assert observed["status"] == "LIVE_RUN_COMPLETE"
    assert observed["cleanup_complete"] is True
    assert observed["live_ready_boundary_id"] == live_ready["boundary_id"]
    assert observed["live_ready_monotonic_ns"] == live_ready["ready_monotonic_ns"]
    assert observed["live_next_boundary_id"] == live_next["boundary_id"]
    assert observed["live_next_monotonic_ns"] == live_next["next_monotonic_ns"]

    incomplete_dir = tmp_path / "incomplete"
    incomplete_dir.mkdir()
    monkeypatch.setattr(r10, "MEMORY_CONTROL", incomplete_dir)
    monkeypatch.setattr(r10, "MEMORY_LIVE_READY_RECORD", None)
    monkeypatch.setattr(r10, "MEMORY_LIVE_NEXT_RECORD", None)
    monkeypatch.setattr(
        r10,
        "ROOT_STATE",
        {
            "closed": True,
            "observer_sink": {"cleanup_confirmed": False, "timer_joined": True},
        },
    )
    incomplete = r10.publish_close_record(
        {"status": "LIVE_RUN_INCOMPLETE", "cleanup_complete": False},
        closed=True,
    )
    incomplete_observed = observer._read_receipt(
        incomplete_dir / r10.RECEIPT_NAME,
        run_id=run_id,
        root_pid=target_identity["pid"],
        expected_create_time=target_identity["create_time"],
    )
    assert incomplete["closed"] is True
    assert incomplete["cleanup_complete"] is False
    assert incomplete_observed["state"] == "terminal"
    assert incomplete_observed["status"] == "LIVE_RUN_INCOMPLETE"
    assert incomplete_observed["live_ready_boundary_id"] is None


def test_r10_loaded_runner_and_strategy_bind_to_current_public_sources(
    monkeypatch: pytest.MonkeyPatch,
):
    example = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
    strategy_path = example / "alpha003_strategy.py"
    runner_path = example / "run.py"
    monkeypatch.setattr(r10, "EXAMPLE", example)
    monkeypatch.setattr(r10, "STRATEGY_MODULE_PATH", strategy_path)
    monkeypatch.setitem(
        r10.PUBLIC_PINS,
        str(strategy_path),
        r10.hashlib.sha256(strategy_path.read_bytes()).hexdigest(),
    )
    monkeypatch.setitem(
        r10.PUBLIC_PINS,
        str(runner_path),
        r10.hashlib.sha256(runner_path.read_bytes()).hexdigest(),
    )
    monkeypatch.syspath_prepend(str(example))

    monkeypatch.delitem(sys.modules, r10.STRATEGY_MODULE_KEY, raising=False)
    monkeypatch.delitem(sys.modules, "run", raising=False)
    strategy_module = r10.load_public_module(
        r10.STRATEGY_MODULE_KEY, strategy_path, register=True
    )
    runner = r10.load_public_module("run", runner_path, register=True)

    strategy_class = r10.verify_loaded_live_runner(runner, strategy_module)
    assert strategy_class is strategy_module.Alpha003TargetStrategy
    assert runner.run_live.__globals__ is runner.__dict__
    assert runner._make_strategy_kwargs.__globals__ is runner.__dict__
    with pytest.raises(RuntimeError, match="LIVE_RUNNER_MODULE_IDENTITY_INVALID"):
        r10.verify_loaded_live_runner(ModuleType("shadow_run"), strategy_module)

    monkeypatch.setitem(r10.PUBLIC_PINS, str(strategy_path), "0" * 64)
    with pytest.raises(RuntimeError, match="STRATEGY_MODULE_SOURCE_PIN_INVALID"):
        r10.verify_loaded_strategy_module(strategy_module)


def test_r10_runtime_dependencies_are_pinned_and_replaced_module_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    for dependency in r10.R10_RUNTIME_DEPENDENCIES:
        expected = r10.PUBLIC_PINS.get(str(dependency))
        assert type(expected) is str and len(expected) == 64
        assert all(character in "0123456789abcdef" for character in expected)

    dependency = tmp_path / "i51_fullpool_golden_postflight_synthetic.py"
    dependency.write_bytes(SYNTHETIC_POSTFLIGHT_BYTES)
    expected_sha = r10.hashlib.sha256(SYNTHETIC_POSTFLIGHT_BYTES).hexdigest()
    monkeypatch.setattr(r10, "POSTFLIGHT_HELPER", dependency)
    monkeypatch.setattr(r10, "R10_RUNTIME_DEPENDENCIES", (dependency,))
    monkeypatch.setattr(r10, "PUBLIC_PINS", {str(dependency): expected_sha})
    loaded = r10.load_public_module("i51_fullpool_golden_postflight", dependency)
    assert loaded.DRAFT_UNEXECUTABLE is True
    assert loaded.__i51_source_sha256__ == expected_sha

    dependency.write_bytes(SYNTHETIC_POSTFLIGHT_BYTES + b"# replaced\n")
    with pytest.raises(RuntimeError, match="PUBLIC_INPUT_CHANGED"):
        r10.load_public_module("i51_fullpool_golden_postflight", dependency)


def test_r10_profile_loader_consumes_the_pinned_public_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    profile = tmp_path / "profile.json"
    pinned_source = SYNTHETIC_PROFILE_BYTES
    profile.write_bytes(pinned_source)
    monkeypatch.setattr(r10, "PROFILE", profile)
    monkeypatch.setattr(
        r10,
        "PUBLIC_PINS",
        {str(profile): r10.hashlib.sha256(pinned_source).hexdigest()},
    )

    class RunnerProbe:
        path = None
        consumed_bytes = None

        @staticmethod
        def load_config(path):
            RunnerProbe.path = Path(path)
            RunnerProbe.consumed_bytes = RunnerProbe.path.read_bytes()
            return json.loads(RunnerProbe.consumed_bytes.decode("utf-8"))

    config = r10.load_pinned_profile(RunnerProbe)
    assert config == {"selection": {"query_mode": "synthetic"}}
    assert RunnerProbe.path != profile
    assert RunnerProbe.consumed_bytes == pinned_source

    profile.write_bytes(b'{"selection":{"query_mode":"replacement"}}\n')
    with pytest.raises(RuntimeError, match="PUBLIC_INPUT_CHANGED"):
        r10.load_pinned_profile(RunnerProbe)


def test_r10_verify_sources_rejects_replaced_runtime_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dependency = tmp_path / "profile.json"
    pinned_source = b"{}\n"
    dependency.write_bytes(pinned_source)
    record = tmp_path / "RECORD"
    record.write_bytes(b"synthetic installed record\n")
    monkeypatch.setattr(r10, "DRAFT_UNEXECUTABLE", False)
    monkeypatch.setattr(r10, "EXPECTED_DEV_HEAD", "root-bound-dev-head")
    monkeypatch.setattr(r10, "BT_RECORD", record)
    monkeypatch.setattr(r10, "SDK_RECORD", record)
    record_hash = r10.hashlib.sha256(record.read_bytes()).hexdigest()
    monkeypatch.setattr(r10, "BT_RECORD_SHA", record_hash)
    monkeypatch.setattr(r10, "SDK_RECORD_SHA", record_hash)
    monkeypatch.setattr(
        r10,
        "PUBLIC_PINS",
        {str(dependency): r10.hashlib.sha256(pinned_source).hexdigest()},
    )
    monkeypatch.setattr(r10, "R10_RUNTIME_DEPENDENCIES", (dependency,))
    r10.verify_sources()
    dependency.write_bytes(b"{\"replacement\": true}\n")
    with pytest.raises(RuntimeError, match="PUBLIC_INPUT_CHANGED"):
        r10.verify_sources()


def test_real_cerebro_prenext_ready_then_later_next_slot_binds_r10_sampler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Exercise the production callbacks across real Cerebro lifecycle phases."""
    import threading

    import backtrader as bt
    import pandas as pd

    strategy_path = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute" / "alpha003_strategy.py"
    strategy_name = "i51_alpha003_callback_lifecycle_test"
    strategy_spec = importlib.util.spec_from_file_location(strategy_name, strategy_path)
    assert strategy_spec is not None and strategy_spec.loader is not None
    strategy_module = importlib.util.module_from_spec(strategy_spec)
    monkeypatch.setitem(sys.modules, strategy_name, strategy_module)
    strategy_spec.loader.exec_module(strategy_module)

    def run_case(
        case_name: str,
        bar_count: int,
        *,
        ready_fails: bool = False,
        missing_member: bool = False,
        ready_in_next: bool = False,
    ):
        case_dir = tmp_path / case_name
        case_dir.mkdir()
        run_id = "i51-" + case_name + "-" + "d" * (32 - len(case_name) - 1)
        target_identity = {"pid": 87654, "create_time": 321.5}
        base_utc = datetime(2026, 10, 28, tzinfo=timezone.utc)
        if ready_fails:
            pair_offsets = (0, 3722)
        elif bar_count >= 3:
            pair_offsets = (0, 120, 121, 3722)
        else:
            pair_offsets = (0, 120, 3722)
        pairs = iter(
            (
                (base_utc + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z"),
                10_000_000_000 + offset * 1_000_000_000,
                1000,
            )
            for offset in pair_offsets
        )

        def fake_clock_pair(*, strictly_after_monotonic_ns=None):
            utc, mono, span = next(pairs)
            assert strictly_after_monotonic_ns is None or mono > strictly_after_monotonic_ns
            return utc, mono, span

        monkeypatch.setattr(r10, "capture_os_clock_pair", fake_clock_pair)
        monkeypatch.setattr(r10, "MEMORY_CONTROL", case_dir)
        monkeypatch.setattr(r10, "MEMORY_RUN_ID", run_id)
        monkeypatch.setattr(r10, "MEMORY_TARGET_IDENTITY", target_identity)
        monkeypatch.setattr(r10, "MEMORY_LIVE_READY_RECORD", None)
        monkeypatch.setattr(r10, "MEMORY_LIVE_NEXT_RECORD", None)
        monkeypatch.setattr(r10, "ROOT_STATE", {})
        start_record = r10.publish_run_start_record()
        callback_threads = []

        def on_ready(event):
            callback_threads.append(threading.get_ident())
            if ready_fails:
                raise OSError("synthetic callback failure")
            return r10.publish_live_ready_record(event)

        def on_next(event):
            callback_threads.append(threading.get_ident())
            return r10.publish_live_next_record(event)

        class CohortProbe:
            cohort_id = "cerebro-synthetic-cohort"

            def __init__(self):
                self.batch = None

            def current_batch(self):
                return self.batch

        cohort = CohortProbe()

        class LifecycleProbe(strategy_module.Alpha003TargetStrategy):
            def __init__(self):
                bt.Strategy.__init__(self)
                self._minimum_period_probe = bt.indicators.SMA(self.data.close, period=3)
                self.live_factors = SimpleNamespace(snapshot=lambda: self._synthetic_snapshot)
                self._last_batch_id = None
                self._shutdown_requested = Event()
                self._last_session_close_at = None
                self.last_execution_block_reason = None
                self._control_refresh_stopped = True
                self.source_continuity_failure_count = 0
                self.source_continuity_first_error = None
                self.phase_calls = []
                self._live_ready_callback_attempted = False
                self._live_ready_callback_completed = False
                self._live_ready_callback_failed = False
                self._live_ready_event_identity = None
                self._live_next_callback_attempted = False
                self._live_next_callback_completed = False
                self._live_next_callback_failed = False
                self._target_ids = ("target", "missing") if missing_member else ("target",)
                self._install_synthetic_coordinator()

            def _current_batch_snapshot(self):
                index = len(self)
                close_time = base_utc + timedelta(minutes=index)
                available_at = close_time + timedelta(seconds=1)
                batch_id = "batch-{}".format(index)
                envelope = SimpleNamespace(
                    source_role="live",
                    complete=True,
                    quality="GOOD",
                    present=True,
                    missing_fields=(),
                    quality_flags=(),
                )
                batch = SimpleNamespace(
                    status="COMPLETE",
                    batch_id=batch_id,
                    cohort_id=cohort.cohort_id,
                    epoch_id=1,
                    calendar_id="cerebro-synthetic-calendar",
                    slot_index=index,
                    close_time=close_time,
                    available_at=available_at,
                    members={"target": SimpleNamespace(envelope=envelope)},
                )
                snapshot = SimpleNamespace(
                    readiness=(
                        "WARMUP" if index < (3 if ready_in_next else 2) else "LIVE_READY"
                    ),
                    batch_complete=True,
                    batch_id=batch_id,
                    cohort_id=cohort.cohort_id,
                    epoch_id=1,
                    calendar_id=batch.calendar_id,
                    close_time=close_time,
                    available_at=available_at,
                    factors={
                        strategy_module.FACTOR_NAME: SimpleNamespace(
                            source_sha256="synthetic-factor-source"
                        )
                    },
                )
                cohort.batch = batch
                self._synthetic_snapshot = snapshot
                return batch, snapshot

            def _record_decision_tape(self, batch, *_args):
                return (
                    True,
                    {
                        "file_id": "synthetic-tape-file",
                        "record_id": "synthetic-record-{}".format(batch.batch_id),
                        "record_index": len(self),
                        "batch_id": batch.batch_id,
                    },
                    None,
                )

            def _record_source_only(self, *_args):
                return True

            def _run_live_prenext_risk(self):
                self.phase_calls.append(("prenext-risk", len(self)))

            def _clock_now(self):
                return base_utc + timedelta(minutes=len(self))

            def _update_target_decision(self, *_args, **_kwargs):
                return None

            def _session_facts(self, _batch):
                return None, False, None

            def _live_facts(self, _now):
                return None

            def _source_receipt(self, batch, snapshot, _tape_reference):
                if tuple(sorted(batch.members)) != tuple(sorted(self._target_ids)):
                    raise ValueError("synthetic source batch member set mismatch")
                return SimpleNamespace(readiness=snapshot.readiness)

            def _confirm_source_anchor(self, receipt, *, anchor_kind):
                assert receipt.readiness == "LIVE_READY"
                assert anchor_kind == "GRID"
                self.synthetic_grid_anchors.append(cohort.batch.batch_id)
                return True

            def _run_live(self, *args, **kwargs):
                self.phase_calls.append(("next-live", len(self)))
                return strategy_module.Alpha003TargetStrategy._run_live(
                    self, *args, **kwargs
                )

            def _install_synthetic_coordinator(self):
                class GridScope:
                    dispatch_allowed = False

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                class JournalProbe:
                    @staticmethod
                    def fee_pair_required_scope(*_args):
                        return None

                class CoordinatorProbe:
                    journal = JournalProbe()

                    @staticmethod
                    def run_order_count():
                        return 0

                    def decision_scope(_self, **scope_args):
                        assert scope_args["batch"] is cohort.batch
                        assert scope_args["source_receipt"].readiness == "LIVE_READY"
                        return GridScope()

                self._coordinator = CoordinatorProbe()
                self._account_scope = "synthetic-account"
                self._strategy_scope = "synthetic-strategy"
                self._logical_run_id = "synthetic-logical-run"
                self._source_kind = "ALPHA003_GRID"
                self._risk_policy = None
                self._last_signal_target = None
                self.synthetic_grid_anchors = []

        cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
        frame = pd.DataFrame(
            {
                "open": [100.0] * bar_count,
                "high": [101.0] * bar_count,
                "low": [99.0] * bar_count,
                "close": [100.0] * bar_count,
                "volume": [1.0] * bar_count,
            },
            index=pd.date_range("2026-10-28 00:01:00", periods=bar_count, freq="min"),
        )
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="target")
        cerebro.addstrategy(
            LifecycleProbe,
            cohort=cohort,
            calendar_id="cerebro-synthetic-calendar",
            replay_mode=False,
            live_ready_callback=on_ready,
            live_next_callback=on_next,
        )
        strategy = cerebro.run()[0]
        ready_path = case_dir / r10.LIVE_READY_NAME
        ready_record = json.loads(ready_path.read_text(encoding="utf-8")) if ready_path.exists() else None
        next_path = case_dir / r10.LIVE_NEXT_NAME
        next_record = json.loads(next_path.read_text(encoding="utf-8")) if next_path.exists() else None
        assert strategy._live_ready_callback_attempted is (not missing_member)
        expected_callback_count = (
            0 if missing_member else (1 if ready_fails or bar_count < 3 else 2)
        )
        assert len(callback_threads) == expected_callback_count
        assert set(callback_threads) == (
            set() if missing_member else {threading.get_ident()}
        )
        if not ready_fails and not missing_member:
            assert strategy._live_ready_callback_completed is True
            ready_slot = 3 if ready_in_next else 2
            assert ready_record["slot_index"] == ready_slot
            assert ready_record["batch_id"] == f"batch-{ready_slot}"

        monkeypatch.setattr(
            r10,
            "ROOT_STATE",
            {
                "closed": True,
                "observer_sink": {"cleanup_confirmed": True, "timer_joined": True},
            },
        )
        close = r10.publish_close_record(
            {"status": "LIVE_RUN_COMPLETE", "cleanup_complete": True}, closed=True
        )
        if ready_fails:
            assert ready_record is None
            assert strategy._live_ready_callback_failed is True
            assert strategy._live_ready_callback_completed is False
            assert strategy._live_next_callback_attempted is False
            assert next_record is None
            assert close["status"] == "LIVE_RUN_INCOMPLETE"
            assert strategy.phase_calls[-1] == ("next-live", 3)
            return {
                "case_dir": case_dir,
                "start": start_record,
                "ready": None,
                "next": None,
                "close": close,
                "run_id": run_id,
                "identity": target_identity,
            }
        if missing_member:
            assert ready_record is None
            assert next_record is None
            assert strategy._live_ready_callback_completed is False
            assert strategy._live_next_callback_attempted is False
            assert strategy.source_continuity_first_error == "SOURCE_RECEIPT_BUILD_FAILED"
            assert strategy.synthetic_grid_anchors == []
            assert close["status"] == "LIVE_RUN_INCOMPLETE"
            return {
                "case_dir": case_dir,
                "start": start_record,
                "ready": None,
                "next": None,
                "close": close,
                "run_id": run_id,
                "identity": target_identity,
            }
        if bar_count < 3:
            assert next_record is None
            assert strategy._live_next_callback_attempted is False
            assert close["status"] == "LIVE_RUN_INCOMPLETE"
            assert close["cleanup_complete"] is True
            return {
                "case_dir": case_dir,
                "start": start_record,
                "ready": ready_record,
                "next": None,
                "close": close,
                "run_id": run_id,
                "identity": target_identity,
            }

        assert next_record is not None
        assert strategy._live_next_callback_completed is True
        if ready_in_next:
            assert next_record["batch_id"] == ready_record["batch_id"]
            assert next_record["slot_index"] == ready_record["slot_index"]
        else:
            assert next_record["batch_id"] == "batch-3"
            assert next_record["slot_index"] == 3
            assert next_record["batch_id"] != ready_record["batch_id"]
        assert next_record["cohort_id"] == ready_record["cohort_id"]
        assert next_record["epoch_id"] == ready_record["epoch_id"]
        assert next_record["calendar_id"] == ready_record["calendar_id"]
        assert ready_record["ready_monotonic_ns"] < next_record["next_monotonic_ns"]
        assert next_record["next_monotonic_ns"] < close["close_monotonic_ns"]
        assert close["status"] == "LIVE_RUN_COMPLETE"
        assert strategy._live_ready_event_identity == (
            "cerebro-synthetic-cohort",
            1,
            "cerebro-synthetic-calendar",
            ready_slot,
            f"batch-{ready_slot}",
        )
        assert strategy._live_next_callback_attempted is True
        assert strategy.phase_calls[-1] == ("next-live", bar_count)
        return {
            "case_dir": case_dir,
            "start": start_record,
            "ready": ready_record,
            "next": next_record,
            "close": close,
            "run_id": run_id,
            "identity": target_identity,
        }

    completed = run_case("adjacent", 4)
    assert completed["close"]["status"] == "LIVE_RUN_COMPLETE"
    root_pid = completed["identity"]["pid"]
    create_time = completed["identity"]["create_time"]
    sampler_pid = root_pid + 1
    ready_mono = completed["ready"]["ready_monotonic_ns"]
    close_mono = completed["close"]["close_monotonic_ns"]
    ready_utc = datetime.fromisoformat(completed["ready"]["ready_utc"].replace("Z", "+00:00"))
    header = {
        "record_type": "header", "schema": 1, "run_id": completed["run_id"],
        "root_pid": root_pid, "expected_create_time": create_time, "sampler_pid": sampler_pid,
    }
    sample_rows = [
        {
            "record_type": "sample", "monotonic_ns": mono,
            "utc": when.isoformat().replace("+00:00", "Z"),
            "sampling_valid": True, "rss_total_bytes": 4096,
            "process_tree": [{"pid": root_pid, "create_time": create_time, "rss_bytes": 4096}],
        }
        for mono, when in (
            (completed["start"]["start_monotonic_ns"] - 1, ready_utc - timedelta(seconds=121)),
            (ready_mono - 1, ready_utc - timedelta(seconds=1)),
            *(
                (ready_mono + second * 1_000_000_000, ready_utc + timedelta(seconds=second))
                for second in range(3602)
            ),
            (close_mono, ready_utc + timedelta(seconds=3602)),
        )
    ]
    summary = {
        "record_type": "summary", "schema": 1, "run_id": completed["run_id"],
        "root_pid": root_pid, "expected_create_time": create_time, "sampler_pid": sampler_pid,
        "stop_reason": "COMPLETION_RECEIPT", "completion_receipt_state": "terminal",
        "completion_status": "LIVE_RUN_COMPLETE", "completion_closed": True,
        "completion_cleanup_complete": True,
        "completion_receipt_id": f"{completed['run_id']}:close",
        "completion_run_id": completed["run_id"], "completion_root_pid": root_pid,
        "completion_root_create_time": create_time,
        "completion_live_ready_boundary_id": completed["ready"]["boundary_id"],
        "completion_live_ready_monotonic_ns": ready_mono,
        "completion_live_next_boundary_id": completed["next"]["boundary_id"],
        "completion_live_next_monotonic_ns": completed["next"]["next_monotonic_ns"],
        "close_utc": completed["close"]["close_utc"],
        "close_monotonic_ns": close_mono,
        "close_clock_pair_span_ns": completed["close"]["close_clock_pair_span_ns"],
        "sampling_quality_valid": True,
    }
    output = completed["case_dir"] / r10.SAMPLE_NAME
    output.write_text(
        "".join(json.dumps(row) + "\n" for row in (header, *sample_rows, summary)),
        encoding="utf-8",
    )
    analysis = r10.analyze_memory_capture(
        observer,
        output_path=output,
        run_id=completed["run_id"],
        root_pid=root_pid,
        root_create_time=create_time,
        sampler_pid=sampler_pid,
        start_record=completed["start"],
        live_ready_record=completed["ready"],
        live_next_record=completed["next"],
        close_record=completed["close"],
    )
    assert analysis["status"] == "WINDOWS_RECORDED", analysis
    assert analysis["memory_acceptance"] == "NOT_EVALUATED"
    assert [window["valid_samples"] for window in analysis["window_summary"]["windows"]] == [1800, 1800]

    never_next = run_case("never-next", 2)
    assert never_next["close"]["status"] == "LIVE_RUN_INCOMPLETE"
    assert never_next["close"]["live_ready_boundary_id"] == f"{never_next['run_id']}:live-ready"
    assert never_next["close"]["live_next_boundary_id"] is None

    missing_member = run_case("missing-member", 4, missing_member=True)
    assert missing_member["ready"] is None
    assert missing_member["next"] is None
    assert missing_member["close"]["status"] == "LIVE_RUN_INCOMPLETE"

    callback_error = run_case("callback-error", 3, ready_fails=True)
    assert callback_error["close"]["status"] == "LIVE_RUN_INCOMPLETE"
    assert callback_error["close"]["live_ready_boundary_id"] is None
    assert callback_error["close"]["live_next_boundary_id"] is None

    ready_in_regular_next = run_case("ready-in-next", 5, ready_in_next=True)
    assert ready_in_regular_next["ready"]["boundary_id"] == (
        f"{ready_in_regular_next['run_id']}:live-ready"
    )
    assert ready_in_regular_next["next"]["boundary_id"] == (
        f"{ready_in_regular_next['run_id']}:first-next"
    )
    assert ready_in_regular_next["ready"]["batch_id"] == (
        ready_in_regular_next["next"]["batch_id"]
    )
    assert ready_in_regular_next["ready"]["slot_index"] == (
        ready_in_regular_next["next"]["slot_index"]
    )
    assert (
        ready_in_regular_next["ready"]["ready_monotonic_ns"]
        < ready_in_regular_next["next"]["next_monotonic_ns"]
        < ready_in_regular_next["close"]["close_monotonic_ns"]
    )


def test_r10_supervisor_synthetic_sibling_gate_and_close_receipts(tmp_path: Path, monkeypatch):
    if observer.psutil is None:
        pytest.skip("psutil unavailable")
    target_script = tmp_path / "synthetic_target.py"
    target_script.write_text(
        "\n".join(
            (
                "import importlib.util, json, os, pathlib, sys, time",
                "import psutil",
                "run_id, control_text, close_mode, r10_source = sys.argv[1:]",
                "assert sys.flags.isolated == 1 and sys.flags.interactive == 1",
                "control = pathlib.Path(control_text)",
                "def read(path): return json.loads(path.read_text(encoding='utf-8'))",
                "spec = importlib.util.spec_from_file_location('i51_synthetic_target_r10', r10_source)",
                "r10 = importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(r10)",
                "deadline = time.monotonic() + 10",
                "release_path = control / 'target_release.json'",
                "while not release_path.exists() and time.monotonic() < deadline: time.sleep(0.01)",
                "gate = read(release_path)",
                "process = psutil.Process()",
                "assert gate['run_id'] == run_id",
                "assert gate['target_pid'] == os.getpid()",
                "assert gate['target_create_time'] == process.create_time()",
                "assert gate['supervisor_pid'] == process.ppid()",
                "assert gate['sampler_pid'] != os.getpid()",
                "assert gate['release_monotonic_ns'] > gate['ready_sample_monotonic_ns']",
                "r10.MEMORY_CONTROL = control",
                "r10.MEMORY_RUN_ID = run_id",
                "r10.MEMORY_TARGET_IDENTITY = {'pid': os.getpid(), 'create_time': process.create_time()}",
                "r10.publish_run_start_record()",
                "time.sleep(0.02)",
                "live_ready = None if close_mode == 'missing-ready' else r10.publish_live_ready_record({",
                "    'readiness': 'LIVE_READY', 'replay_mode': False,",
                "    'cohort_id': 'synthetic-cohort', 'epoch_id': 1,",
                "    'calendar_id': 'synthetic-calendar', 'batch_id': 'synthetic-batch-4', 'slot_index': 4})",
                "time.sleep(2.2)",
                "live_next = None if close_mode in ('missing-ready', 'missing-next') else r10.publish_live_next_record({",
                "    'readiness': 'LIVE_READY', 'replay_mode': False,",
                "    'cohort_id': 'synthetic-cohort', 'epoch_id': 1,",
                "    'calendar_id': 'synthetic-calendar', 'batch_id': 'synthetic-batch-5', 'slot_index': 5})",
                "resource_closed = True",
                "assert resource_closed",
                "r10.publish_protocol_record(control / 'synthetic_resource_close.json', {",
                "    'run_id': run_id, 'pid': os.getpid(),",
                "    'create_time': process.create_time(),",
                "    'closed_monotonic_ns': time.monotonic_ns()})",
                "time.sleep(0.05)",
                "cleanup = close_mode == 'success'",
                "r10.ROOT_STATE = {'closed': True, 'observer_sink': {",
                "    'cleanup_confirmed': cleanup, 'timer_joined': True}}",
                "r10.publish_close_record({",
                "    'status': 'LIVE_RUN_COMPLETE' if cleanup else 'LIVE_RUN_INCOMPLETE',",
                "    'cleanup_complete': cleanup}, closed=True)",
                "checks = {name: bool(cleanup and live_ready is not None and live_next is not None) for name in r10.TARGET_POSTFLIGHT_CHECKS}",
                "target_result = {",
                "    'root_pid': os.getpid(), 'phase': 'complete',",
                "    'status': 'FULL_POOL_TAPE_WITNESS_PASS' if all(checks.values()) else 'FULL_POOL_TAPE_WITNESS_ACCEPTANCE_FAIL',",
                "    'private_context_closed': True, 'fullpool_tape_witness_pass': all(checks.values()),",
                "    'fullpool_acceptance_checks': checks,",
                "    'postflight': {'status': 'PASS' if all(checks.values()) else 'FAIL'},",
                "    'process_tree_memory_observation': 'NOT_RUN_IN_R9',",
                "    'memory_binding': r10._memory_binding_projection(),",
                "}",
                "r10.publish_protocol_record(control / r10.TARGET_RESULT_NAME, target_result)",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(r10, "DRAFT_UNEXECUTABLE", False)
    monkeypatch.setattr(r10, "R10_SUPERVISOR_ENABLED", True)
    monkeypatch.setattr(r10.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(r10, "_verify_r10_dependencies", lambda: None)
    observer_sha = r10.hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    monkeypatch.setattr(r10, "MEMORY_OBSERVER", SCRIPT)
    monkeypatch.setattr(r10, "MEMORY_OBSERVER_SHA", observer_sha)
    monkeypatch.setitem(r10.PUBLIC_PINS, str(SCRIPT), observer_sha)

    def run_case(mode: str):
        def command_factory(run_id: str, control_dir: Path):
            return [
                sys.executable,
                "-I",
                "-i",
                str(target_script),
                run_id,
                str(control_dir),
                mode,
                str(R10_SCRIPT),
            ]

        return r10.supervisor_main(
            execute_bound_readonly_run=True,
            _target_command_factory=command_factory,
        )

    success = run_case("success")
    success_dir = Path(success["control_directory"])
    success_receipt = json.loads((success_dir / r10.RECEIPT_NAME).read_text(encoding="utf-8"))
    success_target = json.loads(
        (success_dir / r10.TARGET_RESULT_NAME).read_text(encoding="utf-8")
    )
    sampler_ready_signal = json.loads(
        (success_dir / r10.READY_NAME).read_text(encoding="utf-8")
    )
    success_ready = json.loads(
        (success_dir / r10.LIVE_READY_NAME).read_text(encoding="utf-8")
    )
    success_next = json.loads((success_dir / r10.LIVE_NEXT_NAME).read_text(encoding="utf-8"))
    success_gate = json.loads((success_dir / r10.RELEASE_NAME).read_text(encoding="utf-8"))
    resource_close = json.loads(
        (success_dir / "synthetic_resource_close.json").read_text(encoding="utf-8")
    )
    success_rows = [
        json.loads(line)
        for line in (success_dir / r10.SAMPLE_NAME).read_text(encoding="utf-8").splitlines()
    ]
    success_header, success_samples, success_summary = (
        success_rows[0],
        success_rows[1:-1],
        success_rows[-1],
    )
    assert success["target_release_gate_opened"] is True
    assert success["cleanup_state"] == "CHILDREN_EXITED"
    assert success["target_exit_code"] == success["sampler_exit_code"] == 0
    assert success["status"] == "INCOMPLETE"
    assert success["memory_acceptance"] == "NOT_EVALUATED"
    assert success["target_postflight_status"] == "PASS"
    assert success["fullpool_acceptance"] == "NOT_EVALUATED"
    assert success_target["process_tree_memory_observation"] == "NOT_RUN_IN_R9"
    assert success_target["memory_binding"]["run_id"] == success["run_id"]
    assert success_header["run_id"] == success["run_id"] == success_receipt["run_id"]
    assert success_header["root_pid"] == success_receipt["root_pid"]
    assert success_header["expected_create_time"] == success_receipt["root_create_time"]
    assert success_header["sampler_pid"] != success_header["root_pid"]
    assert success_receipt["status"] == "LIVE_RUN_COMPLETE"
    assert success_receipt["closed"] is True and success_receipt["cleanup_complete"] is True
    assert success_receipt["live_ready_boundary_id"] == f"{success['run_id']}:live-ready"
    assert success_receipt["live_next_boundary_id"] == f"{success['run_id']}:first-next"
    assert "batch_id" in success_next, success_next
    assert "batch_id" in success_ready, success_ready
    assert success_next["batch_id"] != success_ready["batch_id"]
    assert success_next["slot_index"] > success_ready["slot_index"]
    assert success_next["cohort_id"] == success_ready["cohort_id"]
    assert success_next["epoch_id"] == success_ready["epoch_id"]
    assert success_next["calendar_id"] == success_ready["calendar_id"]
    assert success_summary["stop_reason"] == "COMPLETION_RECEIPT"
    assert success_summary["completion_receipt_id"] == f"{success['run_id']}:close"
    assert success_samples
    rss_report = success["supervisor_rss_report"]
    assert rss_report["status"] == "ANALYSIS_RECORDED"
    assert rss_report["scope"] == "R10_SIBLING_PROCESS_TREE_RSS"
    assert rss_report["run_id"] == success["run_id"]
    assert rss_report["target_pid"] == success_header["root_pid"]
    assert rss_report["target_create_time"] == success_header["expected_create_time"]
    assert rss_report["sampler_pid"] == success_header["sampler_pid"]
    assert rss_report["sample_file"] == r10.SAMPLE_NAME
    assert rss_report["analysis_status"] == success["status"]
    assert (success_dir / rss_report["sample_file"]).is_file()
    assert rss_report["diagnostic_only"] is True
    assert rss_report["stable_rss_established"] is False
    assert rss_report["object_growth_evidence"] == "NOT_COLLECTED"
    assert rss_report["formal_memory_acceptance"] == "NOT_EVALUATED"
    assert success["rss_growth_diagnostic"]["comparison_scope"] == "DIAGNOSTIC_ONLY"
    assert success["rss_growth_diagnostic"]["stable_rss_established"] is False
    assert success["object_growth_evidence"] == "NOT_COLLECTED"
    assert success["memory_acceptance"] == "NOT_EVALUATED"
    first_sample = success_samples[0]
    assert first_sample["sampling_valid"] is True
    assert first_sample["monotonic_ns"] == sampler_ready_signal["sample_monotonic_ns"]
    assert success_gate["ready_sample_monotonic_ns"] == first_sample["monotonic_ns"]
    assert success_gate["release_monotonic_ns"] > success_gate["ready_sample_monotonic_ns"]
    start_record = json.loads((success_dir / r10.START_NAME).read_text(encoding="utf-8"))
    assert start_record["start_monotonic_ns"] > success_gate["release_monotonic_ns"]
    live_ready_record = success_ready
    assert start_record["start_monotonic_ns"] < live_ready_record["ready_monotonic_ns"]
    assert live_ready_record["ready_monotonic_ns"] < success_receipt["close_monotonic_ns"]
    assert live_ready_record["ready_monotonic_ns"] < success_next["next_monotonic_ns"]
    assert success_next["next_monotonic_ns"] < success_receipt["close_monotonic_ns"]
    assert success["first_live_ready_monotonic_ns"] == live_ready_record["ready_monotonic_ns"]
    assert success["window_start_source"] == "FIRST_LIVE_READY_PAIRED_OS_UTC_MONOTONIC"
    assert resource_close["run_id"] == success["run_id"]
    assert resource_close["pid"] == success_receipt["root_pid"]
    assert resource_close["create_time"] == success_receipt["root_create_time"]
    assert resource_close["closed_monotonic_ns"] < success_receipt["close_monotonic_ns"]
    assert start_record["start_monotonic_ns"] < success_receipt["close_monotonic_ns"]
    in_run = [
        row for row in success_samples
        if live_ready_record["ready_monotonic_ns"] <= row["monotonic_ns"] < success_receipt["close_monotonic_ns"]
    ]
    assert len(in_run) >= 1
    for row in success_samples:
        assert all(entry["pid"] != success_header["sampler_pid"] for entry in row["process_tree"])
        target_rows = [entry for entry in row["process_tree"] if entry["pid"] == success_header["root_pid"]]
        assert len(target_rows) == 1
        assert target_rows[0]["create_time"] == success_header["expected_create_time"]

    failed = run_case("incomplete")
    failed_dir = Path(failed["control_directory"])
    failed_receipt = json.loads((failed_dir / r10.RECEIPT_NAME).read_text(encoding="utf-8"))
    failed_rows = [
        json.loads(line)
        for line in (failed_dir / r10.SAMPLE_NAME).read_text(encoding="utf-8").splitlines()
    ]
    assert failed["target_release_gate_opened"] is True
    assert failed["cleanup_state"] == "CHILDREN_EXITED"
    assert failed["target_exit_code"] == 0
    assert failed["sampler_exit_code"] == 1
    assert failed["status"] == "INCOMPLETE"
    assert failed["memory_acceptance"] == "NOT_EVALUATED"
    assert failed["target_postflight_status"] == "INCOMPLETE"
    assert failed["fullpool_acceptance"] == "NOT_EVALUATED"
    assert failed_receipt["run_id"] == failed["run_id"]
    assert failed_receipt["status"] == "LIVE_RUN_INCOMPLETE"
    assert failed_receipt["closed"] is True and failed_receipt["cleanup_complete"] is False
    assert failed_rows[-1]["stop_reason"] == "COMPLETION_RECEIPT"
    assert failed_rows[-1]["completion_status"] == "LIVE_RUN_INCOMPLETE"
    assert failed_rows[-1]["completion_cleanup_complete"] is False

    missing = run_case("missing-ready")
    missing_dir = Path(missing["control_directory"])
    missing_receipt = json.loads((missing_dir / r10.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert missing["status"] == "INCOMPLETE"
    assert missing["failure_code"] == "LIVE_READY_RECORD_MISSING_OR_INVALID"
    assert missing["target_postflight_status"] == "INCOMPLETE"
    assert missing["fullpool_acceptance"] == "NOT_EVALUATED"
    assert missing_receipt["status"] == "LIVE_RUN_INCOMPLETE"
    assert missing_receipt["live_ready_boundary_id"] is None

    no_next = run_case("missing-next")
    no_next_dir = Path(no_next["control_directory"])
    no_next_receipt = json.loads((no_next_dir / r10.RECEIPT_NAME).read_text(encoding="utf-8"))
    no_next_rows = [
        json.loads(line)
        for line in (no_next_dir / r10.SAMPLE_NAME).read_text(encoding="utf-8").splitlines()
    ]
    assert no_next["status"] == "INCOMPLETE"
    assert no_next["failure_code"] == "LIVE_NEXT_RECORD_MISSING_OR_INVALID"
    assert no_next["target_postflight_status"] == "INCOMPLETE"
    assert no_next["fullpool_acceptance"] == "NOT_EVALUATED"
    assert no_next_receipt["status"] == "LIVE_RUN_INCOMPLETE"
    assert no_next_receipt["live_ready_boundary_id"] == f"{no_next['run_id']}:live-ready"
    assert no_next_receipt["live_next_boundary_id"] is None
    assert no_next_rows[-1]["completion_live_next_boundary_id"] is None


def test_slow_sampling_skips_deadlines_without_catchup_burst(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    clock = {"ns": 1, "receipt_reads": 0}

    class FakePsutil:
        pass

    monkeypatch.setattr(observer, "psutil", FakePsutil)
    monkeypatch.setattr(observer.time, "monotonic_ns", lambda: clock["ns"])
    monkeypatch.setattr(
        observer.time,
        "sleep",
        lambda seconds: clock.__setitem__("ns", clock["ns"] + round(seconds * 1_000_000_000)),
    )

    def receipt(_path, **_identity):
        clock["receipt_reads"] += 1
        if clock["receipt_reads"] < 3:
            return {"state": "absent"}
        return {
            "state": "terminal",
            "status": "LIVE_RUN_COMPLETE",
            "closed": True,
            "cleanup_complete": True,
            "receipt_id": "synthetic-clock:close",
            "run_id": "synthetic-clock",
            "root_pid": 123,
            "root_create_time": 1.0,
            "live_ready_boundary_id": "synthetic-clock:live-ready",
            "live_ready_monotonic_ns": 1,
            "live_next_boundary_id": "synthetic-clock:first-next",
            "live_next_monotonic_ns": 2,
            "close_utc": "2026-10-27T00:00:02Z",
            "close_monotonic_ns": clock["ns"],
            "close_clock_pair_span_ns": 1000,
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
        run_id="synthetic-clock",
        completion_receipt=tmp_path / observer.RECEIPT_FILENAME,
        ready_path=tmp_path / observer.READY_FILENAME,
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
    clock = {"ns": 1, "receipt_reads": 0}

    class FakePsutil:
        pass

    monkeypatch.setattr(observer, "psutil", FakePsutil)
    monkeypatch.setattr(observer.time, "monotonic_ns", lambda: clock["ns"])
    monkeypatch.setattr(
        observer.time,
        "sleep",
        lambda seconds: clock.__setitem__("ns", clock["ns"] + round(seconds * 1_000_000_000)),
    )

    def receipt(_path, **_identity):
        clock["receipt_reads"] += 1
        if clock["receipt_reads"] == 1:
            return {"state": "absent"}
        return {
            "state": "terminal",
            "status": "LIVE_RUN_INCOMPLETE",
            "closed": False,
            "cleanup_complete": False,
            "receipt_id": None,
            "run_id": "synthetic-terminal",
            "root_pid": 123,
            "root_create_time": 1.0,
            "close_utc": None,
            "close_monotonic_ns": None,
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
        run_id="synthetic-terminal",
        completion_receipt=tmp_path / observer.RECEIPT_FILENAME,
        ready_path=tmp_path / observer.READY_FILENAME,
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
                "schema": 1,
                "status": "LIVE_RUN_COMPLETE",
                "closed": True,
                "cleanup_complete": True,
                "receipt_id": "synthetic-run-2:close",
                "run_id": "synthetic-run-2",
                "root_pid": 123,
                "root_create_time": 456.0,
                "close_utc": "2026-10-27T00:00:00Z",
                "close_monotonic_ns": 1,
                "untrusted_text": "must-not-be-copied",
            }
        ),
        encoding="utf-8",
    )
    observed = observer._read_receipt(
        receipt, run_id="synthetic-run-2", root_pid=123, expected_create_time=456.0
    )
    assert observed == {"state": "invalid", "error_code": "RECEIPT_FIELDS_INVALID"}
    assert "must-not-be-copied" not in json.dumps(observed)
