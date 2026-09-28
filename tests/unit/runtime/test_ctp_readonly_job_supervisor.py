"""Synthetic-only tests for the optional Windows read-only child supervisor."""

from __future__ import annotations

import json
import io
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import pytest

from backtrader_runtime import ctp_readonly_job_supervisor as supervisor


def _command(code: str, cwd: Path) -> supervisor.FixedChildCommand:
    env: dict[str, str] = {}
    for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return supervisor.FixedChildCommand((sys.executable, "-c", code), cwd, env)


def _json_parser(raw: bytes):
    return supervisor.parse_single_json_receipt(raw, _SCHEMA)


_SCHEMA = supervisor.ValueFreeReceiptSchema(
    enum_fields={"status": ("complete", "incomplete", "rejected")},
    bool_fields=("native_join_pending",),
    nullable_enum_fields={},
)


class _MemoryLatch:
    def __init__(self, *, tripped: bool = False, trip_result: bool = True) -> None:
        self.tripped = tripped
        self.trip_result = trip_result
        self.trip_reasons: list[str] = []

    def is_tripped(self) -> bool:
        return self.tripped

    def trip(self, reason: str) -> bool:
        self.trip_reasons.append(reason)
        self.tripped = self.trip_result
        return self.trip_result


class _FakeMonotonicClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _SynchronousDrainThread:
    def __init__(self, target: object, args: tuple[object, ...], daemon: bool = False) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.join_timeouts: list[float | None] = []

    def start(self) -> None:
        self.target(*self.args)  # type: ignore[operator]

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)

    def is_alive(self) -> bool:
        return False


class _SyntheticDeadlineKernel:
    def __init__(
        self,
        clock: _FakeMonotonicClock,
        *,
        child_running: bool,
        terminate_advance_seconds: float = 0.0,
        query_advance_on: int | None = None,
        query_advance_seconds: float = 0.0,
        active_process_samples: list[int] | None = None,
        active_processes: int | None = None,
    ) -> None:
        self.clock = clock
        self.process_exited = not child_running
        self.active_processes = int(child_running) if active_processes is None else active_processes
        self.terminate_advance_seconds = terminate_advance_seconds
        self.query_advance_on = query_advance_on
        self.query_advance_seconds = query_advance_seconds
        self.active_process_samples = list(active_process_samples or ())
        self.query_calls = 0
        self.wait_timeouts: list[int] = []
        self.terminate_calls: list[int] = []
        self.closed_handles: list[int] = []

    def ResumeThread(self, _thread: int) -> int:
        return 1

    def CloseHandle(self, handle: int) -> bool:
        self.closed_handles.append(handle)
        return True

    def TerminateJobObject(self, _job: int, code: int) -> bool:
        self.terminate_calls.append(code)
        self.process_exited = True
        self.active_processes = 0
        self.clock.now += self.terminate_advance_seconds
        return True

    def WaitForSingleObject(self, _process: int, timeout_ms: int) -> int:
        self.wait_timeouts.append(timeout_ms)
        return supervisor._WAIT_OBJECT_0 if self.process_exited else supervisor._WAIT_TIMEOUT

    def GetExitCodeProcess(self, _process: int, exit_code: object) -> bool:
        ctypes.cast(exit_code, ctypes.POINTER(wintypes.DWORD)).contents.value = 0
        return True

    def QueryInformationJobObject(
        self,
        _job: int,
        _information_class: int,
        information: object,
        _information_length: int,
        _return_length: object,
    ) -> bool:
        self.query_calls += 1
        if self.query_calls == self.query_advance_on:
            self.clock.now += self.query_advance_seconds
        active_processes = (
            self.active_process_samples.pop(0)
            if self.active_process_samples
            else self.active_processes
        )
        ctypes.cast(
            information,
            ctypes.POINTER(supervisor._JOBOBJECT_BASIC_ACCOUNTING_INFORMATION),
        ).contents.ActiveProcesses = active_processes
        return True


def _install_deadline_harness(
    monkeypatch: pytest.MonkeyPatch,
    clock: _FakeMonotonicClock,
    kernel: _SyntheticDeadlineKernel,
    stdout: bytes,
) -> list[_SynchronousDrainThread]:
    threads: list[_SynchronousDrainThread] = []

    def make_thread(*args: object, **kwargs: object) -> _SynchronousDrainThread:
        thread = _SynchronousDrainThread(*args, **kwargs)  # type: ignore[arg-type]
        threads.append(thread)
        return thread

    monkeypatch.setattr(supervisor, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(supervisor, "time", clock)
    monkeypatch.setattr(supervisor, "threading", SimpleNamespace(Thread=make_thread))
    monkeypatch.setattr(supervisor, "_winapi", lambda: kernel)
    monkeypatch.setattr(supervisor, "_create_job", lambda _kernel: 10)
    monkeypatch.setattr(
        supervisor,
        "_create_suspended_process",
        lambda _kernel, _command, _job, **_kwargs: (20, 21, 22),
    )
    monkeypatch.setattr(supervisor, "_handle_to_stream", lambda _handle: io.BytesIO(stdout))
    return threads


def test_absolute_deadline_during_job_setup_stops_before_child_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(10.0)
    kernel = _SyntheticDeadlineKernel(clock, child_running=True)
    monkeypatch.setattr(supervisor, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(supervisor, "time", clock)
    monkeypatch.setattr(supervisor, "_winapi", lambda: kernel)

    def create_job(_kernel: object) -> int:
        clock.now = 10.06
        return 10

    monkeypatch.setattr(supervisor, "_create_job", create_job)
    monkeypatch.setattr(
        supervisor,
        "_create_suspended_process",
        lambda *_args, **_kwargs: pytest.fail("child creation ran after budget expiry"),
    )
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})

    result = supervisor.run_readonly_child(
        command,
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=_MemoryLatch(),
        deadline_seconds=100,
        deadline_monotonic=10.05,
    )

    assert result.status == "timed_out"
    assert result.reason == "supervisor_deadline_exceeded"
    assert result.process_evidence.process_created is False
    assert result.process_evidence.containment == "not_started"
    assert kernel.closed_handles == [10]


def test_suspended_setup_stops_after_pipe_setup_crosses_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(40.0)
    closed_handles: list[int] = []
    kernel = SimpleNamespace(CloseHandle=lambda handle: closed_handles.append(handle) or True)
    monkeypatch.setattr(supervisor, "time", clock)

    def create_pipe(_kernel: object) -> tuple[int, int]:
        clock.now = 40.06
        return 30, 31

    monkeypatch.setattr(supervisor, "_new_pipe", create_pipe)
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})

    with pytest.raises(supervisor._ChildCreationError) as raised:
        supervisor._create_suspended_process(
            kernel, command, 99, deadline_monotonic=40.05
        )

    assert raised.value.reason == "supervisor_deadline_exceeded"
    assert raised.value.process_created is False
    assert set(closed_handles) == {30, 31}


def test_absolute_deadline_terminates_child_running_past_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(10.0)
    kernel = _SyntheticDeadlineKernel(clock, child_running=True)
    _install_deadline_harness(monkeypatch, clock, kernel, b"")
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})
    latch = _MemoryLatch()

    result = supervisor.run_readonly_child(
        command,
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=latch,
        deadline_seconds=100,
        deadline_monotonic=10.05,
        termination_grace_seconds=2,
    )

    assert result.status == "timed_out"
    assert result.reason == "supervisor_deadline_exceeded"
    assert result.process_evidence.job_termination_requested is True
    assert result.process_evidence.job_termination_call_succeeded is True
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_empty_observed is False
    assert result.process_evidence.containment == "uncertain"
    assert result.retained_control is not None
    assert kernel.wait_timeouts and all(timeout == 0 for timeout in kernel.wait_timeouts)
    assert latch.trip_reasons == ["supervisor_deadline_exceeded"]


def test_absolute_deadline_caps_pending_native_join_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(20.0)
    kernel = _SyntheticDeadlineKernel(
        clock, child_running=True, terminate_advance_seconds=0.1
    )
    pending = b'{"native_join_pending":true,"status":"incomplete"}\n'
    _install_deadline_harness(monkeypatch, clock, kernel, pending)
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})
    latch = _MemoryLatch()

    result = supervisor.run_readonly_child(
        command,
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=latch,
        deadline_seconds=100,
        deadline_monotonic=20.05,
        termination_grace_seconds=2,
    )

    assert result.status == "timed_out"
    assert result.reason == "supervisor_deadline_exceeded"
    assert result.sdk_receipt == {"native_join_pending": True, "status": "incomplete"}
    assert result.process_evidence.job_termination_requested is True
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_empty_observed is False
    assert result.process_evidence.containment == "uncertain"
    assert kernel.terminate_calls
    assert kernel.wait_timeouts and all(timeout == 0 for timeout in kernel.wait_timeouts)
    assert latch.trip_reasons == ["native_join_pending"]


def test_deadline_during_cleanup_returns_timed_out_even_with_containment_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(30.0)
    kernel = _SyntheticDeadlineKernel(
        clock,
        child_running=False,
        query_advance_on=1,
        query_advance_seconds=0.1,
    )
    complete = b'{"native_join_pending":false,"status":"complete"}\n'
    threads = _install_deadline_harness(monkeypatch, clock, kernel, complete)
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})

    result = supervisor.run_readonly_child(
        command,
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=_MemoryLatch(),
        deadline_seconds=100,
        deadline_monotonic=30.05,
        termination_grace_seconds=2,
    )

    assert result.status == "timed_out"
    assert result.reason == "supervisor_deadline_exceeded"
    assert result.sdk_receipt == {"native_join_pending": False, "status": "complete"}
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"
    assert kernel.terminate_calls == []
    assert len(threads) == 1
    assert threads[0].join_timeouts == [0.0]


def test_signaled_child_waits_for_transient_job_accounting_before_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(35.0)
    kernel = _SyntheticDeadlineKernel(
        clock,
        child_running=False,
        active_process_samples=[1, 0],
    )
    complete = b'{"native_join_pending":false,"status":"complete"}\n'
    _install_deadline_harness(monkeypatch, clock, kernel, complete)
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})

    result = supervisor.run_readonly_child(
        command,
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=_MemoryLatch(),
        deadline_seconds=5,
        termination_grace_seconds=0.2,
    )

    assert result.status == "child_exited"
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_termination_requested is False
    assert result.process_evidence.job_termination_call_succeeded is None
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"
    assert kernel.terminate_calls == []
    assert clock.now == pytest.approx(35.025)


def test_signaled_child_with_remaining_descendant_terminates_after_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonicClock(45.0)
    kernel = _SyntheticDeadlineKernel(
        clock,
        child_running=False,
        active_process_samples=[1, 1, 1, 1],
        active_processes=1,
    )
    complete = b'{"native_join_pending":false,"status":"complete"}\n'
    _install_deadline_harness(monkeypatch, clock, kernel, complete)
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})

    result = supervisor.run_readonly_child(
        command,
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=_MemoryLatch(),
        deadline_seconds=5,
        termination_grace_seconds=0.1,
    )

    assert result.status == "child_exited"
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_termination_requested is True
    assert result.process_evidence.job_termination_call_succeeded is True
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"
    assert kernel.terminate_calls == [0xEE28]
    assert clock.now == pytest.approx(45.1)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are required")
def test_synthetic_child_reports_sdk_receipt_and_parent_os_evidence_separately() -> None:
    payload = {"native_join_pending": False, "status": "complete"}
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    code = "import sys;sys.stdout.write(" + repr(line) + ");sys.stdout.flush()"
    with tempfile.TemporaryDirectory(prefix="ctp-readonly-supervisor-") as temporary:
        result = supervisor.run_readonly_child(
            _command(code, Path(temporary)),
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=_MemoryLatch(),
            deadline_seconds=5,
        )

    assert result.status == "child_exited"
    assert result.sdk_receipt == payload
    assert result.process_evidence.process_created is True
    assert result.process_evidence.job_assignment_observed is True
    assert result.process_evidence.process_resumed is True
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.process_exit_code == 0
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job handle inheritance only")
def test_child_can_verify_exact_inherited_supervisor_job_handle() -> None:
    code = (
        "import ctypes,json,os;"
        "name='test_supervisor_job_handle';"
        "raw=os.environ.pop(name);"
        "job=ctypes.c_void_p(int(raw));"
        "k=ctypes.WinDLL('kernel32',use_last_error=True);"
        "k.GetCurrentProcess.argtypes=();"
        "k.GetCurrentProcess.restype=ctypes.c_void_p;"
        "k.IsProcessInJob.argtypes=(ctypes.c_void_p,ctypes.c_void_p,"
        "ctypes.POINTER(ctypes.c_int));"
        "k.IsProcessInJob.restype=ctypes.c_int;"
        "inside=ctypes.c_int();"
        "ok=k.IsProcessInJob(k.GetCurrentProcess(),job,ctypes.byref(inside));"
        "k.CloseHandle.argtypes=(ctypes.c_void_p,);"
        "k.CloseHandle.restype=ctypes.c_int;"
        "k.CloseHandle(job);"
        "print(json.dumps({'status':'complete','native_join_pending':not(bool(ok)"
        " and inside.value)},separators=(',',':')))"
    )
    with tempfile.TemporaryDirectory(prefix="ctp-readonly-job-handle-") as temporary:
        base = _command(code, Path(temporary))
        command = supervisor.FixedChildCommand(
            base.argv,
            base.cwd,
            base.env,
            job_handle_env_name="test_supervisor_job_handle",
        )
        result = supervisor.run_readonly_child(
            command,
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=_MemoryLatch(),
            deadline_seconds=5,
            max_stdout_bytes=1024,
            termination_grace_seconds=2,
        )

    assert result.status == "child_exited"
    assert result.sdk_receipt == {"status": "complete", "native_join_pending": False}
    assert result.process_evidence.job_assignment_observed is True
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are required")
def test_pending_native_join_terminates_entire_synthetic_job() -> None:
    line = '{"native_join_pending":true,"status":"incomplete"}\n'
    code = "import sys,time;sys.stdout.write(" + repr(line) + ");sys.stdout.flush();time.sleep(20)"
    with tempfile.TemporaryDirectory(prefix="ctp-readonly-pending-join-") as temporary:
        result = supervisor.run_readonly_child(
            _command(code, Path(temporary)),
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=_MemoryLatch(),
            deadline_seconds=5,
            termination_grace_seconds=3,
        )

    assert result.status == "pending_native_join"
    assert result.sdk_receipt == {"native_join_pending": True, "status": "incomplete"}
    assert result.process_evidence.job_termination_requested is True
    assert result.process_evidence.job_termination_call_succeeded is True
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are required")
def test_deadline_terminates_parent_and_descendant_inside_job() -> None:
    code = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']);"
        "time.sleep(20)"
    )
    with tempfile.TemporaryDirectory(prefix="ctp-readonly-timeout-") as temporary:
        result = supervisor.run_readonly_child(
            _command(code, Path(temporary)),
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=_MemoryLatch(),
            deadline_seconds=0.25,
            termination_grace_seconds=3,
        )

    assert result.status == "timed_out"
    assert result.sdk_receipt is None
    assert result.process_evidence.job_termination_requested is True
    assert result.process_evidence.job_termination_call_succeeded is True
    assert result.process_evidence.process_exit_observed is True
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are required")
def test_stdout_bound_kills_synthetic_child_without_returning_raw_output() -> None:
    code = "import sys,time;sys.stdout.write('x'*4096);sys.stdout.flush();time.sleep(20)"
    with tempfile.TemporaryDirectory(prefix="ctp-readonly-output-limit-") as temporary:
        result = supervisor.run_readonly_child(
            _command(code, Path(temporary)),
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=_MemoryLatch(),
            deadline_seconds=5,
            max_stdout_bytes=128,
            termination_grace_seconds=3,
        )

    assert result.status == "invalid_output"
    assert result.reason == "stdout_limit_exceeded"
    assert result.sdk_receipt is None
    assert result.process_evidence.job_empty_observed is True
    assert result.process_evidence.containment == "verified"


def test_value_free_receipt_parser_rejects_raw_or_numeric_values() -> None:
    assert supervisor.parse_single_json_receipt(
        b'{"native_join_pending":false,"status":"incomplete"}\n', _SCHEMA
    ) == {"native_join_pending": False, "status": "incomplete"}
    assert (
        supervisor.parse_single_json_receipt(
            b'{"native_join_pending":false,"password":"hunter2","status":"complete"}\n',
            _SCHEMA,
        )
        is None
    )
    assert (
        supervisor.parse_single_json_receipt(
            b'{"native_join_pending":false,"status":"hunter2"}\n', _SCHEMA
        )
        is None
    )
    assert (
        supervisor.parse_single_json_receipt(
            b'{"native_join_pending":false,"native_join_pending":true,"status":"complete"}\n',
            _SCHEMA,
        )
        is None
    )


def test_value_free_receipt_parser_preserves_nullable_boolean_evidence() -> None:
    schema = supervisor.ValueFreeReceiptSchema(
        enum_fields={"status": ("incomplete", "complete")},
        bool_fields=(),
        nullable_enum_fields={},
        nullable_bool_fields=("native_join_pending", "matching_tick_observed"),
    )
    assert supervisor.parse_single_json_receipt(
        b'{"matching_tick_observed":null,"native_join_pending":null,"status":"incomplete"}\n',
        schema,
    ) == {
        "matching_tick_observed": None,
        "native_join_pending": None,
        "status": "incomplete",
    }
    assert supervisor.parse_single_json_receipt(
        b'{"matching_tick_observed":true,"native_join_pending":false,"status":"complete"}\n',
        schema,
    ) == {
        "matching_tick_observed": True,
        "native_join_pending": False,
        "status": "complete",
    }
    assert (
        supervisor.parse_single_json_receipt(
            b'{"matching_tick_observed":0,"native_join_pending":false,"status":"complete"}\n',
            schema,
        )
        is None
    )


def test_fixed_command_snapshots_argv_and_environment() -> None:
    environment = {"PATH": "synthetic"}
    command = supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), environment)
    environment["PATH"] = "changed"

    assert command.env["PATH"] == "synthetic"
    with pytest.raises(TypeError):
        command.env["PATH"] = "mutated"  # type: ignore[index]


def test_suspended_child_is_created_atomically_in_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    class _AtomicJobKernel:
        def __init__(self) -> None:
            self.attribute_count: int | None = None
            self.attributes: list[int] = []
            self.job_handle: int | None = None
            self.attribute_list_attached = False

        def CreateFileW(self, *_args: object) -> int:
            return 12

        def InitializeProcThreadAttributeList(
            self,
            attribute_list: object,
            attribute_count: int,
            _flags: int,
            required_size: object,
        ) -> bool:
            self.attribute_count = attribute_count
            if attribute_list is None:
                required_size._obj.value = 128  # type: ignore[attr-defined]
                return False
            return True

        def UpdateProcThreadAttribute(
            self,
            _attribute_list: object,
            _flags: int,
            attribute: int,
            value: object,
            _size: int,
            _previous: object,
            _returned_size: object,
        ) -> bool:
            self.attributes.append(attribute)
            if attribute == supervisor._PROC_THREAD_ATTRIBUTE_JOB_LIST:
                handle = ctypes.cast(value, ctypes.POINTER(wintypes.HANDLE))[0]
                self.job_handle = handle if isinstance(handle, int) else handle.value
            return True

        def CreateProcessW(self, *_args: object) -> bool:
            startup = ctypes.cast(_args[-2], ctypes.POINTER(supervisor._STARTUPINFOEXW)).contents
            self.attribute_list_attached = bool(startup.lpAttributeList)
            process_info = ctypes.cast(
                _args[-1], ctypes.POINTER(supervisor._PROCESS_INFORMATION)
            ).contents
            process_info.hProcess = 21
            process_info.hThread = 22
            return True

        def QueryInformationJobObject(
            self,
            _job: int,
            _information_class: int,
            information: object,
            _information_length: int,
            _return_length: object,
        ) -> bool:
            ctypes.cast(
                information,
                ctypes.POINTER(supervisor._JOBOBJECT_BASIC_ACCOUNTING_INFORMATION),
            ).contents.ActiveProcesses = 1
            return True

        def DeleteProcThreadAttributeList(self, _attribute_list: object) -> None:
            return None

        def CloseHandle(self, _handle: int) -> bool:
            return True

    kernel = _AtomicJobKernel()
    monkeypatch.setattr(supervisor, "_new_pipe", lambda _kernel: (10, 11))
    command = supervisor.FixedChildCommand(
        (sys.executable, "-c", "pass"), Path.cwd(), {"PYTHONNOUSERSITE": "1"}
    )

    process, thread, stdout_read = supervisor._create_suspended_process(kernel, command, 99)

    assert (process, thread, stdout_read) == (21, 22, 10)
    assert kernel.attribute_count == 2
    assert kernel.attribute_list_attached is True
    assert kernel.attributes == [
        supervisor._PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        supervisor._PROC_THREAD_ATTRIBUTE_JOB_LIST,
    ]
    assert kernel.job_handle == 99


def test_custom_parser_cannot_escape_exact_schema_allowlist() -> None:
    raw = b'{"native_join_pending":false,"status":"complete"}\n'
    parsed, parser_failed = supervisor._safe_parse(
        lambda _raw: {
            "native_join_pending": False,
            "password": "hunter2",
            "status": "complete",
        },
        raw,
        _SCHEMA,
    )

    assert parsed is None
    assert parser_failed is False


def test_latch_prevents_a_new_child_before_process_creation() -> None:
    latch = _MemoryLatch(tripped=True)
    result = supervisor.run_readonly_child(
        supervisor.FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {}),
        _json_parser,
        receipt_schema=_SCHEMA,
        fail_closed_latch=latch,
        deadline_seconds=1,
    )

    assert result.status == "latched"
    assert result.process_evidence.process_created is False


def test_retained_control_releases_handles_only_after_exit_and_empty_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _VerifiedKernel:
        def __init__(self) -> None:
            self.closed: list[int] = []

        def TerminateJobObject(self, _job: int, _code: int) -> bool:
            return True

        def WaitForSingleObject(self, _process: int, _timeout: int) -> int:
            return supervisor._WAIT_OBJECT_0

        def GetExitCodeProcess(self, _process: int, _exit_code: object) -> bool:
            return False

        def CloseHandle(self, handle: int) -> bool:
            self.closed.append(handle)
            return True

    kernel = _VerifiedKernel()
    monkeypatch.setattr(supervisor, "_wait_for_job_empty", lambda _kernel, _job, _timeout: True)
    control = supervisor.RetainedJobControl(kernel, 100, 101, 102, True, True)

    evidence = control.resolve(timeout_seconds=0.1)

    assert evidence.process_exit_observed is True
    assert evidence.job_empty_observed is True
    assert evidence.containment == "verified"
    assert control._job_handle is None
    assert control._process_handle is None
    assert kernel.closed == [102, 101, 100]


@pytest.fixture(autouse=True)
def reset_process_latch():
    supervisor._PROCESS_CONTAINMENT_LATCH = None
    yield
    supervisor._PROCESS_CONTAINMENT_LATCH = None


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are required")
def test_termination_uncertainty_trips_latch_and_retains_job_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FaultKernel:
        def __init__(self) -> None:
            self.closed: list[int] = []

        def ResumeThread(self, _thread: int) -> int:
            return 1

        def CloseHandle(self, handle: int) -> bool:
            self.closed.append(handle)
            return True

        def TerminateJobObject(self, _job: int, _code: int) -> bool:
            return False

        def TerminateProcess(self, _process: int, _code: int) -> bool:
            return False

        def WaitForSingleObject(self, _handle: int, _timeout: int) -> int:
            return supervisor._WAIT_TIMEOUT

        def GetExitCodeProcess(self, _process: int, _exit_code: object) -> bool:
            return False

    kernel = _FaultKernel()
    latch = _MemoryLatch(trip_result=False)
    monkeypatch.setattr(supervisor, "_winapi", lambda: kernel)
    monkeypatch.setattr(supervisor, "_create_job", lambda _kernel: 100)
    monkeypatch.setattr(
        supervisor,
        "_create_suspended_process",
        lambda _kernel, _command, _job: (101, 102, 103),
    )
    monkeypatch.setattr(supervisor, "_handle_to_stream", lambda _handle: io.BytesIO(b""))
    monkeypatch.setattr(supervisor, "_job_active_processes", lambda _kernel, _job: 1)
    monkeypatch.setattr(supervisor, "_wait_for_job_empty", lambda _kernel, _job, _timeout: False)

    with tempfile.TemporaryDirectory(prefix="ctp-readonly-latch-") as temporary:
        result = supervisor.run_readonly_child(
            _command("pass", Path(temporary)),
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=latch,
            deadline_seconds=0.05,
            termination_grace_seconds=0.1,
        )

        assert result.status == "supervisor_error"
        assert result.reason == "containment_latch_trip_failed"
        assert result.process_evidence.containment == "uncertain"
        assert result.retained_control is not None
        assert result.retained_control._job_handle == 100
        assert result.retained_control._process_handle == 101
        assert 100 not in kernel.closed
        assert 101 not in kernel.closed
        assert latch.trip_reasons == ["child_deadline_exceeded"]
        resolution = result.retained_control.resolve(timeout_seconds=0.1)
        assert resolution.containment == "uncertain"
        assert result.retained_control._job_handle == 100
        assert result.retained_control._process_handle == 101
        assert 100 not in kernel.closed
        assert 101 not in kernel.closed

        retry = supervisor.run_readonly_child(
            _command("pass", Path(temporary)),
            _json_parser,
            receipt_schema=_SCHEMA,
            fail_closed_latch=latch,
            deadline_seconds=1,
        )

    assert retry.status == "latched"
    assert retry.process_evidence.process_created is False
