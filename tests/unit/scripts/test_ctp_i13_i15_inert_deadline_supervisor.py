"""Process-level contracts for the unregistered inert deadline supervisor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts import ctp_i13_i15_inert_deadline_supervisor as supervisor


def test_deadline_supervisor_requires_inert_only_acknowledgement() -> None:
    with pytest.raises(SystemExit):
        supervisor._arguments(
            [
                "--child-seconds",
                "1",
                "--stop-deadline-monotonic",
                "10",
                "--deadline-monotonic",
                "12",
                "--receipt-root",
                str(Path.cwd()),
            ]
        )


def test_deadlines_reserve_time_for_cleanup_and_receipt() -> None:
    with pytest.raises(ValueError, match="supervisor_deadline_invalid"):
        supervisor._validate_deadlines(
            child_seconds=1.0,
            stop_deadline_monotonic=101.75,
            deadline_monotonic=102.0,
            now=100.0,
        )

    child, stop, deadline = supervisor._validate_deadlines(
        child_seconds=1.0,
        stop_deadline_monotonic=101.5,
        deadline_monotonic=102.0,
        now=100.0,
    )
    assert (child, stop, deadline) == (1.0, 101.5, 102.0)


def test_supervisor_entry_rejects_deadline_without_cleanup_reserve(
    tmp_path: Path,
) -> None:
    now = time.monotonic()
    with pytest.raises(ValueError, match="supervisor_deadline_invalid"):
        supervisor.run_inert_deadline_supervisor(
            child_seconds=1.0,
            stop_deadline_monotonic=now + 1.0,
            deadline_monotonic=now + 1.25,
            receipt_root=str(tmp_path),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="the receipt writer is Windows-only")
def test_supervisor_preserves_failed_state_after_one_nonempty_job_poll(
    tmp_path: Path,
) -> None:
    """A transient nonempty observation stays failed after successful cleanup."""

    from scripts.ctp_i13_i15_outer_watchdog import FixedOuterCommand

    class Session:
        process_created = True
        job_assignment_observed = True

        def __init__(self) -> None:
            self.job_empty_polls = 0
            self.termination_requested = False
            self.controls_released = False

        def resume_launcher(self) -> bool:
            return True

        def poll_launcher_exit_code(self) -> int:
            return 2

        def poll_job_empty(self) -> bool:
            self.job_empty_polls += 1
            return self.job_empty_polls > 1

        def terminate_job(self) -> bool:
            self.termination_requested = True
            return True

        def terminate_launcher_process(self) -> bool:
            raise AssertionError("assigned Job should own the launcher")

        def release_controls(self) -> bool:
            self.controls_released = True
            return True

    class Backend:
        def __init__(self) -> None:
            self.session = Session()

        def create_suspended_in_job(self, command, *, deadline_monotonic):
            del command, deadline_monotonic
            return self.session

        def retain_controls(self, session):
            del session
            raise AssertionError("verified cleanup must release controls directly")

    receipt_root = tmp_path / "single-false-receipt"
    receipt_root.mkdir()
    now = time.monotonic()
    deadline = now + 10.0
    backend = Backend()
    command = FixedOuterCommand([sys.executable], str(tmp_path), {})

    exit_code = supervisor._supervise_fixed_command(
        command,
        receipt_root=str(receipt_root),
        stop_deadline_monotonic=deadline - 1.0,
        deadline_monotonic=deadline,
        backend=backend,
    )

    receipt = json.loads((receipt_root / supervisor._RECEIPT_NAME).read_text(encoding="ascii"))
    assert exit_code == 2
    assert backend.session.job_empty_polls == 2
    assert backend.session.termination_requested is True
    assert backend.session.controls_released is True
    assert receipt["state"] == "unknown"
    assert receipt["supervisor_state"] == "failed"
    assert receipt["supervisor_reason"] == "descendant_or_job_state_unconfirmed"
    assert receipt["launcher_exit_code"] == 2
    assert receipt["job_termination_requested"] is True
    assert receipt["job_termination_call_succeeded"] is True
    assert receipt["launcher_exit_observed"] is True
    assert receipt["job_empty_observed"] is True
    assert receipt["controls_released_monotonic"] is not None
    assert (
        receipt["launcher_exit_observed_monotonic"]
        <= receipt["job_termination_call_started_monotonic"]
        <= receipt["job_termination_call_returned_monotonic"]
        <= receipt["job_empty_observed_monotonic"]
        <= receipt["controls_released_monotonic"]
    )


@pytest.mark.skipif(
    os.name != "nt" or sys.getwindowsversion().major < 10 or sys.getwindowsversion().build < 14393,
    reason="the process contract requires Windows nested Jobs and Job lists",
)
def test_supervisor_kills_blocked_inert_service_after_owner_death(tmp_path: Path) -> None:
    """An independent process enforces one deadline after its owner is killed."""

    import ctypes
    from ctypes import wintypes

    repo_root = Path(__file__).resolve().parents[3]
    receipt_root = tmp_path / "supervisor-output"
    receipt_root.mkdir()
    child_active_path = tmp_path / "nested-inert-child.json"
    service_script = tmp_path / "blocked_inert_service.py"
    service_script.write_text(
        "\n".join(
            [
                "import ctypes, json, os, sys, time",
                "from ctypes import wintypes",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts.ctp_i13_i15_outer_watchdog import FixedOuterCommand",
                "from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend",
                "child_active_path = Path(sys.argv[1])",
                "system_root = os.environ.get('SYSTEMROOT', r'C:\\Windows')",
                "env = {'PATH': os.path.dirname(os.path.abspath(sys.executable)), 'SYSTEMROOT': system_root, 'WINDIR': os.environ.get('WINDIR', system_root)}",
                "command = FixedOuterCommand([sys.executable, '-I', '-S', '-B', '-c', 'import time; time.sleep(120)'], os.getcwd(), env)",
                "backend = WindowsJobBackend()",
                "session = backend.create_suspended_in_job(command, deadline_monotonic=time.monotonic() + 15.0)",
                "if session.job_assignment_observed is not True or not session.resume_launcher(): raise SystemExit(31)",
                "kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)",
                "get_process_id = kernel32.GetProcessId",
                "get_process_id.argtypes = [wintypes.HANDLE]",
                "get_process_id.restype = wintypes.DWORD",
                "child_pid = int(get_process_id(wintypes.HANDLE(session._process_handle)))",
                "child_active_path.write_text(json.dumps({'service_pid': os.getpid(), 'child_pid': child_pid}), encoding='ascii')",
                "while True: time.sleep(1.0)",
            ]
        ),
        encoding="utf-8",
    )
    supervisor_script = tmp_path / "independent_supervisor.py"
    supervisor_script.write_text(
        "\n".join(
            [
                "import os, sys, time",
                f"sys.path.insert(0, {str(repo_root)!r})",
                "from scripts.ctp_i13_i15_outer_watchdog import FixedOuterCommand",
                "from scripts.ctp_i13_i15_inert_deadline_supervisor import _supervise_fixed_command",
                "from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend",
                "service_script, child_active_path, receipt_root, deadline_text = sys.argv[1:]",
                "system_root = os.environ.get('SYSTEMROOT', r'C:\\Windows')",
                "env = {'PATH': os.path.dirname(os.path.abspath(sys.executable)), 'SYSTEMROOT': system_root, 'WINDIR': os.environ.get('WINDIR', system_root)}",
                "command = FixedOuterCommand([sys.executable, '-I', '-S', '-B', service_script, child_active_path], os.getcwd(), env)",
                "_supervise_fixed_command(command, receipt_root=receipt_root, stop_deadline_monotonic=float(deadline_text) - 1.0, deadline_monotonic=float(deadline_text), backend=WindowsJobBackend())",
            ]
        ),
        encoding="utf-8",
    )
    owner_script = tmp_path / "owner.py"
    owner_started_path = tmp_path / "owner-started.json"
    owner_script.write_text(
        "\n".join(
            [
                "import json, os, subprocess, sys, time",
                "from pathlib import Path",
                "service_script, child_active_path, receipt_root, supervisor_script, owner_started_path = sys.argv[1:]",
                "deadline = time.monotonic() + 10.0",
                "process = subprocess.Popen([sys.executable, '-I', '-S', '-B', supervisor_script, service_script, child_active_path, receipt_root, repr(deadline)], cwd=os.getcwd(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
                "Path(owner_started_path).write_text(json.dumps({'owner_pid': os.getpid(), 'supervisor_pid': process.pid, 'deadline': deadline}), encoding='ascii')",
                "while True: time.sleep(1.0)",
            ]
        ),
        encoding="utf-8",
    )

    owner = None
    owner_pid = None
    owner_handle = None
    supervisor_handle = None
    service_handle = None
    child_handle = None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    synchronize = 0x00100000
    process_terminate = 0x0001

    def wait_for_json(path: Path, timeout: float) -> dict:
        until = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < until:
            try:
                value = json.loads(path.read_text(encoding="ascii"))
                if type(value) is dict:
                    return value
            except (OSError, ValueError) as error:
                last_error = error
            time.sleep(0.02)
        raise AssertionError(f"timed out waiting for valid JSON in {path.name}: {last_error!r}")

    try:
        owner = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(owner_script),
                str(service_script),
                str(child_active_path),
                str(receipt_root),
                str(supervisor_script),
                str(owner_started_path),
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        owner_facts = wait_for_json(owner_started_path, 5.0)
        owner_pid = int(owner_facts["owner_pid"])
        assert owner_pid > 0
        deadline = float(owner_facts["deadline"])
        supervisor_pid = int(owner_facts["supervisor_pid"])
        child_facts = wait_for_json(child_active_path, 6.0)
        service_pid = int(child_facts["service_pid"])
        child_pid = int(child_facts["child_pid"])

        owner_handle = kernel32.OpenProcess(synchronize | process_terminate, False, owner_pid)
        supervisor_handle = kernel32.OpenProcess(synchronize, False, supervisor_pid)
        service_handle = kernel32.OpenProcess(synchronize, False, service_pid)
        child_handle = kernel32.OpenProcess(synchronize, False, child_pid)
        assert owner_handle and supervisor_handle and service_handle and child_handle
        assert kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout

        # Destroy the request owner while the service is blocked after resuming
        # an inert Job child.  The separate supervisor must outlive its parent.
        assert kernel32.TerminateProcess(owner_handle, 0xEE14)
        assert kernel32.WaitForSingleObject(owner_handle, 10_000) == wait_object_0
        owner.wait(timeout=5.0)
        assert time.monotonic() < deadline - 1.0
        assert kernel32.WaitForSingleObject(supervisor_handle, 0) == wait_timeout
        assert kernel32.WaitForSingleObject(service_handle, 0) == wait_timeout
        assert kernel32.WaitForSingleObject(child_handle, 0) == wait_timeout

        receipt_path = receipt_root / supervisor._RECEIPT_NAME
        receipt = wait_for_json(receipt_path, max(5.0, deadline - time.monotonic() + 5.0))
        assert receipt["schema"] == "ctp_i13_i15_inert_deadline_supervisor_receipt.v1"
        assert receipt["state"] == "unknown"
        assert receipt["reason"] == "absolute_deadline_termination_requested"
        assert receipt["supervisor_state"] == "timed_out"
        assert receipt["supervisor_reason"] == "outer_worker_deadline_exceeded"
        assert receipt["job_assignment_observed"] is True
        assert receipt["launcher_resumed"] is True
        assert receipt["job_termination_requested"] is True
        assert receipt["job_termination_call_succeeded"] is True
        assert receipt["deadline_monotonic"] == deadline
        assert receipt["job_empty_observed"] is True

        assert kernel32.WaitForSingleObject(supervisor_handle, 10_000) == wait_object_0
        supervisor_exit_at = time.monotonic()
        assert supervisor_exit_at <= deadline
        assert receipt["supervisor_receipt_write_started_monotonic"] <= deadline
        assert receipt["job_empty_observed_monotonic"] <= deadline
        assert kernel32.WaitForSingleObject(service_handle, 10_000) == wait_object_0
        assert kernel32.WaitForSingleObject(child_handle, 10_000) == wait_object_0
    finally:
        if owner_handle is None and owner_started_path.exists():
            try:
                owner_facts = json.loads(owner_started_path.read_text(encoding="ascii"))
                owner_pid = int(owner_facts["owner_pid"])
                owner_handle = kernel32.OpenProcess(
                    synchronize | process_terminate, False, owner_pid
                )
            except (OSError, ValueError, KeyError, TypeError):
                owner_handle = None
        if owner_handle and kernel32.WaitForSingleObject(owner_handle, 0) == wait_timeout:
            kernel32.TerminateProcess(owner_handle, 0xEE14)
            kernel32.WaitForSingleObject(owner_handle, 10_000)
        if owner is not None and owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5.0)
        for handle in (service_handle, child_handle, supervisor_handle):
            if handle and kernel32.WaitForSingleObject(handle, 0) == wait_timeout:
                kernel32.TerminateProcess(handle, 0xEE14)
                kernel32.WaitForSingleObject(handle, 10_000)
        for handle in (child_handle, service_handle, supervisor_handle, owner_handle):
            if handle:
                kernel32.CloseHandle(handle)


def _write_inert_chain_helpers(tmp_path: Path, repo_root: Path) -> tuple[Path, Path]:
    supervisor_script = tmp_path / "inert_chain_supervisor.py"
    supervisor_script.write_text(
        "\n".join(
            [
                "import json, os, sys, time",
                "from pathlib import Path",
                "repo_root, receipt_root, stage, stop_text, deadline_text = sys.argv[1:]",
                "sys.path.insert(0, repo_root)",
                "from scripts.ctp_i13_i15_inert_deadline_supervisor import run_inert_deadline_supervisor",
                "Path(receipt_root, 'supervisor-started.json').write_text(json.dumps({'pid': os.getpid(), 'started_monotonic': time.monotonic()}), encoding='ascii')",
                "raise SystemExit(run_inert_deadline_supervisor(",
                "    child_seconds=0.05, stop_deadline_monotonic=float(stop_text),",
                "    deadline_monotonic=float(deadline_text), receipt_root=receipt_root, stage=stage,",
                "))",
            ]
        ),
        encoding="utf-8",
    )
    owner_script = tmp_path / "inert_chain_owner.py"
    owner_script.write_text(
        "\n".join(
            [
                "import json, os, subprocess, sys, time",
                "from pathlib import Path",
                "repo_root, supervisor_script, receipt_root, stage, owner_path, total_text, reserve_text = sys.argv[1:]",
                "deadline = time.monotonic() + float(total_text)",
                "stop = deadline - float(reserve_text)",
                "process = subprocess.Popen([sys.executable, '-I', '-S', '-B', supervisor_script, repo_root, receipt_root, stage, repr(stop), repr(deadline)], cwd=repo_root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
                "Path(owner_path).write_text(json.dumps({'pid': os.getpid(), 'deadline': deadline, 'stop': stop, 'supervisor_launcher_pid': process.pid}), encoding='ascii')",
                "while True: time.sleep(1.0)",
            ]
        ),
        encoding="utf-8",
    )
    return supervisor_script, owner_script


@pytest.mark.parametrize(
    ("stage", "kill_owner", "worker_expected"),
    [
        ("complete", False, True),
        ("setup-block", False, False),
        ("worker-block", True, True),
        ("close-block", False, True),
        ("receipt-fail", False, True),
    ],
)
@pytest.mark.skipif(
    os.name != "nt" or sys.getwindowsversion().major < 10 or sys.getwindowsversion().build < 14393,
    reason="the process contract requires Windows Job lists",
)
def test_inert_parent_setup_worker_and_close_share_one_supervisor_deadline(
    tmp_path: Path, stage: str, kill_owner: bool, worker_expected: bool
) -> None:
    """Observe setup/worker/close process facts under the same absolute budget."""

    import ctypes
    from ctypes import wintypes

    repo_root = Path(__file__).resolve().parents[3]
    receipt_root = tmp_path / "inert-parent-output"
    receipt_root.mkdir()
    if stage == "receipt-fail":
        (receipt_root / "inert-parent-receipt.json").write_bytes(b"parent-receipt-preserve-me")
    supervisor_script, owner_script = _write_inert_chain_helpers(tmp_path, repo_root)
    owner_path = tmp_path / "inert-parent-owner.json"
    owner = None
    handles = {}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    synchronize = 0x00100000
    process_query_information = 0x00000400
    process_terminate = 0x0001

    def wait_for_json(path: Path, timeout: float = 10.0) -> dict:
        until = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < until:
            try:
                value = json.loads(path.read_text(encoding="ascii"))
                if type(value) is dict:
                    return value
            except (OSError, ValueError) as error:
                last_error = error
            time.sleep(0.02)
        raise AssertionError("timed out waiting for {0}: {1!r}".format(path.name, last_error))

    def open_process(name: str, pid: int, *, terminate: bool = False) -> int:
        access = synchronize | process_query_information | (process_terminate if terminate else 0)
        handle = kernel32.OpenProcess(access, False, pid)
        assert handle, "OpenProcess failed for {0} PID {1}".format(name, pid)
        handles[name] = handle
        return handle

    def wait_signaled(name: str, timeout_ms: int = 15_000) -> float:
        assert kernel32.WaitForSingleObject(handles[name], timeout_ms) == wait_object_0
        return time.monotonic()

    try:
        owner = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(owner_script),
                str(repo_root),
                str(supervisor_script),
                str(receipt_root),
                stage,
                str(owner_path),
                "8.0",
                "3.0",
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        owner_facts = wait_for_json(owner_path)
        supervisor_facts = wait_for_json(receipt_root / "supervisor-started.json")
        supervisor_pid = int(supervisor_facts["pid"])
        supervisor_handle = open_process("supervisor", supervisor_pid)
        owner_handle = open_process("owner", int(owner_facts["pid"]), terminate=True)
        setup_facts = wait_for_json(receipt_root / "inert-parent-setup.json")
        parent_pid = int(setup_facts["parent_pid"])
        parent_handle = open_process("parent", parent_pid)
        assert int(setup_facts["supervisor_pid"]) == supervisor_pid

        worker_handle = None
        worker_pid = None
        if worker_expected:
            worker_facts = wait_for_json(receipt_root / "inert-parent-worker.json")
            worker_pid = int(wait_for_json(receipt_root / "inert-parent-worker-pid.json")["pid"])
            worker_handle = open_process("worker", worker_pid)
            assert int(worker_facts["parent_pid"]) == parent_pid
            if stage == "close-block":
                close_facts = wait_for_json(receipt_root / "inert-parent-close.json")
                assert int(close_facts["worker_pid"]) == worker_pid
                assert kernel32.WaitForSingleObject(worker_handle, 0) == wait_object_0
            elif stage in ("worker-block", "receipt-fail"):
                if stage == "worker-block":
                    assert kernel32.WaitForSingleObject(worker_handle, 0) == wait_timeout
                else:
                    assert kernel32.WaitForSingleObject(worker_handle, 2_000) == wait_object_0
            elif stage == "complete":
                assert kernel32.WaitForSingleObject(worker_handle, 2_000) == wait_object_0

        deadline = float(owner_facts["deadline"])
        stop = float(owner_facts["stop"])
        assert stop < deadline
        assert kernel32.WaitForSingleObject(supervisor_handle, 0) == wait_timeout
        assert kernel32.WaitForSingleObject(parent_handle, 0) == wait_timeout

        owner_exit_time = None
        if kill_owner:
            assert kernel32.TerminateProcess(owner_handle, 0xEE41)
            owner_exit_time = wait_signaled("owner")
            assert owner_exit_time < stop
            assert kernel32.WaitForSingleObject(supervisor_handle, 0) == wait_timeout
            assert kernel32.WaitForSingleObject(parent_handle, 0) == wait_timeout
            assert worker_handle is not None
            assert kernel32.WaitForSingleObject(worker_handle, 0) == wait_timeout

        receipt_path = receipt_root / supervisor._RECEIPT_NAME
        until = time.monotonic() + max(15.0, deadline - time.monotonic() + 5.0)
        while not receipt_path.exists() and time.monotonic() < until:
            time.sleep(0.02)
        assert receipt_path.exists(), "supervisor did not write its independent receipt"
        receipt_seen_at = time.monotonic()
        receipt = json.loads(receipt_path.read_text(encoding="ascii"))
        assert receipt["schema"] == "ctp_i13_i15_inert_deadline_supervisor_receipt.v1"
        assert receipt["state"] == "unknown"
        assert receipt["deadline_monotonic"] == deadline
        assert receipt["launcher_exit_observed"] is True
        assert receipt["job_empty_observed"] is True
        assert receipt["launcher_exit_observed_monotonic"] is not None
        assert receipt["job_empty_observed_monotonic"] is not None
        assert receipt["supervisor_receipt_write_started_monotonic"] is not None
        assert receipt_seen_at >= receipt["supervisor_receipt_write_started_monotonic"]

        if stage == "complete":
            assert receipt["reason"] == "supervisor_outcome_unverified"
            assert receipt["supervisor_state"] == "exited"
            assert receipt["job_termination_call_started_monotonic"] is None
            assert receipt["launcher_exit_code"] == 0
            parent_receipt = json.loads(
                (receipt_root / "inert-parent-receipt.json").read_text(encoding="ascii")
            )
            assert parent_receipt["state"] == "completed"
        elif stage == "receipt-fail":
            assert receipt["reason"] == "supervisor_outcome_unverified"
            assert receipt["launcher_exit_code"] == 2
            assert (receipt_root / "inert-parent-receipt.json").read_bytes() == (
                b"parent-receipt-preserve-me"
            )
            if receipt["supervisor_state"] == "exited":
                assert receipt["supervisor_reason"] == "launcher_exited_job_empty"
                assert receipt["job_termination_requested"] is False
                assert receipt["job_termination_call_started_monotonic"] is None
            else:
                assert receipt["supervisor_state"] == "failed"
                assert receipt["supervisor_reason"] == "descendant_or_job_state_unconfirmed"
                assert receipt["job_termination_requested"] is True
                assert receipt["job_termination_call_succeeded"] is True
                requested_at = receipt["job_termination_call_started_monotonic"]
                finished_at = receipt["job_termination_call_returned_monotonic"]
                assert requested_at is not None and finished_at is not None
                assert receipt["launcher_exit_observed_monotonic"] <= requested_at
                assert requested_at <= finished_at <= receipt["job_empty_observed_monotonic"]
                assert receipt["controls_released_monotonic"] is not None
        else:
            assert receipt["reason"] == "absolute_deadline_termination_requested"
            assert receipt["supervisor_state"] == "timed_out"
            assert receipt["job_termination_requested"] is True
            assert receipt["job_termination_call_succeeded"] is True
            requested_at = receipt["job_termination_call_started_monotonic"]
            finished_at = receipt["job_termination_call_returned_monotonic"]
            assert requested_at is not None and finished_at is not None
            assert stop <= requested_at <= deadline + 1.0
            assert requested_at <= finished_at
            assert receipt["job_empty_observed_monotonic"] >= requested_at
            assert receipt["launcher_exit_observed_monotonic"] >= requested_at
            assert receipt_seen_at <= deadline + 5.0

        parent_exit_time = wait_signaled("parent")
        supervisor_exit_time = wait_signaled("supervisor")
        worker_exit_time = wait_signaled("worker") if worker_handle is not None else None
        if stage not in ("receipt-fail", "complete"):
            assert parent_exit_time >= receipt["job_termination_call_started_monotonic"]
        if worker_exit_time is not None and stage in ("worker-block",):
            assert worker_exit_time >= receipt["job_termination_call_started_monotonic"]
        assert supervisor_exit_time >= receipt_seen_at
        if owner_exit_time is None:
            assert kernel32.WaitForSingleObject(owner_handle, 0) == wait_timeout

        exit_code = wintypes.DWORD()
        assert kernel32.GetExitCodeProcess(parent_handle, ctypes.byref(exit_code))
        assert exit_code.value != 259  # STILL_ACTIVE
        if stage == "receipt-fail":
            assert exit_code.value == 2
        elif stage == "complete":
            assert exit_code.value == 0
    finally:
        if owner is not None and owner_path.exists():
            try:
                facts = json.loads(owner_path.read_text(encoding="ascii"))
                owner_handle = handles.get("owner") or kernel32.OpenProcess(
                    synchronize | process_terminate, False, int(facts["pid"])
                )
                if owner_handle and kernel32.WaitForSingleObject(owner_handle, 0) == wait_timeout:
                    kernel32.TerminateProcess(owner_handle, 0xEE41)
                    kernel32.WaitForSingleObject(owner_handle, 10_000)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5.0)
        for name in ("worker", "parent", "supervisor", "owner"):
            handle = handles.get(name)
            if handle:
                kernel32.CloseHandle(handle)
