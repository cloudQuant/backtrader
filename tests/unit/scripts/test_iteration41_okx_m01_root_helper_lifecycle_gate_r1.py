"""Faithful fake-Win32 coverage for the fixed M01 root-helper lifecycle gate."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import threading
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
GATE_PATH = ROOT / "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r1.py"
_GATE_SPEC = importlib.util.spec_from_file_location("_m01_root_helper_gate_test", GATE_PATH)
assert _GATE_SPEC is not None and _GATE_SPEC.loader is not None
gate = importlib.util.module_from_spec(_GATE_SPEC)
_GATE_SPEC.loader.exec_module(gate)


@pytest.fixture
def pinned_modules(monkeypatch):
    if os.name != "nt":
        pytest.skip("the source-bound M01 root-helper gate is Windows-only")
    monkeypatch.syspath_prepend(str(VENUE))
    reader = importlib.import_module("_m01_readonly_monitor_v3.current_reader")
    return reader, reader.job_supervisor, reader.worker


class _FakeWinFunction:
    def __init__(self, kernel, name):
        self.kernel = kernel
        self.name = name
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        method = getattr(self.kernel, "call_" + self.name, None)
        if method is None:
            return False
        return method(*args)


class _FakeKernel:
    """In-memory pipes, process, and Job for the real V2 supervisor methods."""

    def __init__(self, supervisor, *, fail_job_close=False):
        self.supervisor = supervisor
        self.fail_job_close = fail_job_close
        self.functions = {}
        self.next_handle = 0x5100
        self.job = 0x5001
        self.process = 0x5201
        self.thread = 0x5202
        self.job_handle = self.job
        self.assigned = False
        self.exited = False
        self.exit_event = threading.Event()
        self.lock = threading.RLock()
        self.local = threading.local()
        self.channels = {}
        self.handle_to_channel = {}
        self.output_handles = None
        self.stdout_bytes = b""
        self.stdin_frame = b""
        self.child_exit_code = None
        self.closed_handles = set()
        self.close_failures = 0

    def __getattr__(self, name):
        if name.startswith("call_"):
            raise AttributeError(name)
        if name not in self.functions:
            self.functions[name] = _FakeWinFunction(self, name)
        return self.functions[name]

    def _new_handle(self):
        self.next_handle += 1
        return self.next_handle

    def set_last_error(self, value):
        self.local.error = value

    def get_last_error(self):
        return getattr(self.local, "error", 0)

    def call_CloseHandle(self, handle):
        value = int(handle)
        if self.fail_job_close and value == self.job_handle:
            self.close_failures += 1
            self.set_last_error(5)
            return False
        self.closed_handles.add(value)
        return True

    def call_CreateJobObjectW(self, _security, _name):
        return self.job

    def call_SetInformationJobObject(self, _job, _kind, _info, _size):
        return True

    def call_QueryInformationJobObject(self, _job, _kind, info_ptr, _size, _returned):
        info = self.supervisor._JOBOBJECT_BASIC_ACCOUNTING_INFORMATION.from_address(
            __import__("ctypes").cast(info_ptr, __import__("ctypes").c_void_p).value
        )
        info.ActiveProcesses = int(self.assigned and not self.exited)
        return True

    def call_CreatePipe(self, read_ptr, write_ptr, _security, _size):
        import ctypes
        from ctypes import wintypes

        read_handle = self._new_handle()
        write_handle = self._new_handle()
        channel = {"read": read_handle, "write": write_handle, "data": b"", "offset": 0}
        self.channels[read_handle] = channel
        self.channels[write_handle] = channel
        self.handle_to_channel[read_handle] = channel
        self.handle_to_channel[write_handle] = channel
        ctypes.cast(read_ptr, ctypes.POINTER(wintypes.HANDLE)).contents.value = read_handle
        ctypes.cast(write_ptr, ctypes.POINTER(wintypes.HANDLE)).contents.value = write_handle
        return True

    def call_SetHandleInformation(self, _handle, _mask, _flags):
        return True

    def call_InitializeProcThreadAttributeList(self, attribute_list, _count, _flags, size_ptr):
        import ctypes

        ctypes.cast(size_ptr, ctypes.POINTER(ctypes.c_size_t)).contents.value = 64
        return attribute_list is not None

    def call_UpdateProcThreadAttribute(self, *_args):
        return True

    def call_DeleteProcThreadAttributeList(self, *_args):
        return None

    def call_CreateProcessW(self, *_args):
        import ctypes

        startup_ptr = _args[-2]
        process_info_ptr = _args[-1]
        startup = ctypes.cast(startup_ptr, ctypes.POINTER(self.supervisor._STARTUPINFOW)).contents
        process_info = ctypes.cast(
            process_info_ptr, ctypes.POINTER(self.supervisor._PROCESS_INFORMATION)
        ).contents
        process_info.hProcess = self.process
        process_info.hThread = self.thread
        process_info.dwProcessId = 23141
        process_info.dwThreadId = 23142
        self.output_handles = (int(startup.hStdOutput), int(startup.hStdError))
        return True

    def call_AssignProcessToJobObject(self, _job, _process):
        self.assigned = True
        return True

    def call_ResumeThread(self, _thread):
        return 1

    def call_WriteFile(self, handle, buffer, count, written_ptr, _overlapped):
        import ctypes

        payload = ctypes.string_at(buffer, count)
        self.stdin_frame += payload
        ctypes.cast(
            written_ptr, ctypes.POINTER(__import__("ctypes").wintypes.DWORD)
        ).contents.value = count
        self._execute_bootstrap_frame(payload)
        return True

    def _execute_bootstrap_frame(self, framed_source):
        import ctypes
        import hashlib as hashlib_module
        import io as io_module
        import sys as sys_module
        from unittest.mock import patch

        if len(framed_source) < 4:
            self.child_exit_code = 92
            return
        source_size = struct.unpack(">I", framed_source[:4])[0]
        source = framed_source[4:]
        if source_size != len(source):
            self.child_exit_code = 92
            return
        expected = hashlib_module.sha256(source).hexdigest()
        bootstrap = self.supervisor._worker_bootstrap(expected, source_size)
        fake_stdin = SimpleNamespace(buffer=io_module.BytesIO(framed_source))
        captured = io_module.StringIO()
        fake_stdout = SimpleNamespace(write=captured.write)
        namespace = {"__name__": "__main__"}
        with patch.object(sys_module, "stdin", fake_stdin), patch.object(
            sys_module, "stdout", fake_stdout
        ):
            try:
                exec(compile(bootstrap, "<pinned-v2-bootstrap-test>", "exec"), namespace, namespace)
            except SystemExit as error:
                self.child_exit_code = 0 if error.code is None else error.code
            except BaseException:
                self.child_exit_code = 93
        if self.output_handles is not None:
            stdout_handle = self.output_handles[0]
            channel = self.handle_to_channel[stdout_handle]
            channel["data"] = captured.getvalue().encode("utf-8")
            self.stdout_bytes = channel["data"]

    def call_WaitForSingleObject(self, _handle, _milliseconds):
        self.exited = True
        self.exit_event.set()
        return 0

    def call_GetExitCodeProcess(self, _process, exit_ptr):
        import ctypes
        from ctypes import wintypes

        ctypes.cast(exit_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = (
            self.child_exit_code if self.child_exit_code is not None else 0xEE
        )
        return True

    def call_TerminateJobObject(self, _job, _code):
        self.exited = True
        self.exit_event.set()
        return True

    def call_TerminateProcess(self, _process, _code):
        self.exited = True
        self.exit_event.set()
        return True

    def call_ReadFile(self, handle, buffer, capacity, received_ptr, _overlapped):
        import ctypes
        from ctypes import wintypes

        if not self.exit_event.wait(3.0):
            self.set_last_error(1460)
            return False
        channel = self.handle_to_channel[int(handle)]
        with self.lock:
            remaining = channel["data"][channel["offset"] :]
            if not remaining:
                self.set_last_error(109)
                return False
            chunk = remaining[:capacity]
            channel["offset"] += len(chunk)
        ctypes.memmove(buffer, chunk, len(chunk))
        ctypes.cast(received_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = len(chunk)
        return True


@pytest.fixture
def fake_win32(monkeypatch, pinned_modules):
    _reader, supervisor, _worker = pinned_modules
    kernel = _FakeKernel(supervisor)
    monkeypatch.setattr(
        supervisor.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel, raising=False
    )
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor,
        "_hold_runtime_files",
        lambda _kernel, _deadline: {"runtime_handles": set()},
    )
    return kernel


def test_fixed_probe_exercises_pinned_reader_and_v2_lifecycle_with_fake_win32(
    pinned_modules, fake_win32
):
    result = gate.run_fixed_synthetic_probe(*pinned_modules)

    assert result["status"] == "SOURCE_FAKE_ONLY"
    assert result["phase"] == "complete"
    assert result["source_functions_restored"] is True
    assert result["process_created"] is True
    assert result["job_assigned_before_resume"] is True
    assert result["resumed"] is True
    assert result["source_frame_write_succeeded"] is True
    assert result["stdin_close_succeeded"] is True
    assert result["process_wait_succeeded"] is True
    assert result["process_exit_code_zero"] is True
    assert result["job_zero_after_exit"] is True
    assert result["stdout_eof"] is True
    assert result["stderr_eof"] is True
    assert result["stdout_thread_joined"] is True
    assert result["stderr_thread_joined"] is True
    assert result["stdout_matches_fixed"] is True
    assert result["stderr_empty"] is True
    assert result["all_observed_handles_closed"] is True
    assert result["handle_close_failures"] == 0
    assert result["retained_context"] is False
    assert result["production_acceptance"] is False
    assert fake_win32.child_exit_code == 0
    assert fake_win32.stdout_bytes == gate.SYNTHETIC_OUTPUT
    assert fake_win32.stdin_frame[4:].startswith(b"def _worker_source_sha256():\n")


def test_gate_retains_context_when_reader_ignores_a_failed_final_handle_close(
    monkeypatch, pinned_modules
):
    _reader, supervisor, _worker = pinned_modules
    kernel = _FakeKernel(supervisor, fail_job_close=True)
    monkeypatch.setattr(
        supervisor.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel, raising=False
    )
    monkeypatch.setattr(supervisor.ctypes, "get_last_error", kernel.get_last_error, raising=False)
    monkeypatch.setattr(
        supervisor,
        "_hold_runtime_files",
        lambda _kernel, _deadline: {"runtime_handles": set()},
    )

    result = gate.run_fixed_synthetic_probe(*pinned_modules)

    assert result["status"] == "LIFECYCLE_BLOCKED"
    assert result["phase"] == "cleanup_close"
    assert result["win32_api"] == "CloseHandle"
    assert result["winerror"] == 5
    assert result["process_wait_succeeded"] is True
    assert result["stdout_eof"] is True
    assert result["stderr_eof"] is True
    assert result["handle_close_failures"] == 1
    assert result["all_observed_handles_closed"] is False
    assert result["retained_context"] is True
    assert result["production_acceptance"] is False


def test_exact_v2_bootstrap_rejects_changed_source_bytes_before_execution(
    pinned_modules, monkeypatch
):
    reader, supervisor, _worker = pinned_modules
    wrapper = reader._root_helper_wrapper(gate.SYNTHETIC_HELPER)
    expected = hashlib.sha256(wrapper).hexdigest()
    bootstrap = supervisor._worker_bootstrap(expected, len(wrapper))
    corrupted = bytearray(struct.pack(">I", len(wrapper)) + wrapper)
    corrupted[-1] ^= 1
    fake_stdin = SimpleNamespace(buffer=io.BytesIO(bytes(corrupted)))
    captured = io.StringIO()
    fake_stdout = SimpleNamespace(write=captured.write)
    namespace = {"__name__": "__main__"}
    with monkeypatch.context() as patcher:
        patcher.setattr(sys, "stdin", fake_stdin)
        patcher.setattr(sys, "stdout", fake_stdout)
        with pytest.raises(SystemExit) as raised:
            exec(compile(bootstrap, "<pinned-v2-bootstrap-test>", "exec"), namespace, namespace)

    assert raised.value.code == 93
    assert captured.getvalue() == ""


def test_gate_rejects_same_filename_reader_function_with_detached_globals(
    pinned_modules, monkeypatch
):
    reader, supervisor, worker = pinned_modules
    namespace = {}
    exec(
        compile(
            "def _run_pinned_root_helper(*args, **kwargs):\n    return None\n",
            str(Path(reader.__file__).resolve()),
            "exec",
        ),
        namespace,
        namespace,
    )
    monkeypatch.setattr(reader, "_run_pinned_root_helper", namespace["_run_pinned_root_helper"])

    with pytest.raises(gate.GateError) as raised:
        gate._bind_sources(reader, supervisor, worker)

    assert raised.value.code == "reader_global_binding_mismatch"


def test_gate_rejects_same_filename_supervisor_function_with_detached_globals(
    pinned_modules, monkeypatch
):
    reader, supervisor, worker = pinned_modules
    namespace = {}
    exec(
        compile(
            "def _write_all(*args, **kwargs):\n    return True\n",
            str(Path(supervisor.__file__).resolve()),
            "exec",
        ),
        namespace,
        namespace,
    )
    monkeypatch.setattr(supervisor, "_write_all", namespace["_write_all"])

    with pytest.raises(gate.GateError) as raised:
        gate._bind_sources(reader, supervisor, worker)

    assert raised.value.code == "supervisor_code_origin_mismatch"


def test_gate_rejects_same_filename_runtime_holder_with_detached_globals(
    pinned_modules, monkeypatch
):
    reader, supervisor, worker = pinned_modules
    namespace = {}
    exec(
        compile(
            "def _hold_runtime_files(*args, **kwargs):\n    return {'runtime_handles': set()}\n",
            str(Path(supervisor.__file__).resolve()),
            "exec",
        ),
        namespace,
        namespace,
    )
    monkeypatch.setattr(supervisor, "_hold_runtime_files", namespace["_hold_runtime_files"])

    with pytest.raises(gate.GateError) as raised:
        gate._bind_sources(reader, supervisor, worker)

    assert raised.value.code == "runtime_holder_global_binding_mismatch"
