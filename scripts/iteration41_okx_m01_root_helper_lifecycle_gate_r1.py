"""Source-bound, credential-free probe for the fixed M01 root-helper lifecycle."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
READER_RELATIVE = "_m01_readonly_monitor_v3/current_reader.py"
SUPERVISOR_RELATIVE = "_m01_readonly_monitor_v2/job_supervisor.py"
WORKER_RELATIVE = "_m01_readonly_monitor_v2/worker.py"
READER_SHA256 = "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734"
SUPERVISOR_SHA256 = "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82"
WORKER_SHA256 = "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41"
SYNTHETIC_OUTPUT = b"OKX_M01_ROOT_HELPER_GATE_R1_OK\n"
SYNTHETIC_HELPER = (
    b"from datetime import datetime, timezone\n"
    b"import sys\n"
    b"sys.stdout.write('OKX_M01_ROOT_HELPER_GATE_R1_OK\\n')\n"
)
_MAX_SOURCE_BYTES = 256 * 1024
_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}\Z")
_WINERROR_MAX = 65535
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_ERROR_BROKEN_PIPE = 109
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ORPHANED_GATE_CONTEXTS: list[tuple[Any, ...]] = []
_OBSERVATION_LOCK = threading.RLock()
_WIN32_NAMES = frozenset(
    {
        "CloseHandle",
        "CreateFileW",
        "GetFileInformationByHandle",
        "GetFinalPathNameByHandleW",
        "GetFileSizeEx",
        "CreateJobObjectW",
        "SetInformationJobObject",
        "QueryInformationJobObject",
        "CreatePipe",
        "SetHandleInformation",
        "CreateProcessW",
        "InitializeProcThreadAttributeList",
        "UpdateProcThreadAttribute",
        "DeleteProcThreadAttributeList",
        "AssignProcessToJobObject",
        "ResumeThread",
        "WaitForSingleObject",
        "TerminateJobObject",
        "TerminateProcess",
        "GetExitCodeProcess",
        "ReadFile",
        "WriteFile",
    }
)
_SUPERVISOR_FUNCTIONS = (
    "_winapi",
    "_new_pipe_state",
    "_create_suspended",
    "_drain",
    "_write_all",
    "_wait_process",
    "_process_exit_code",
    "_active_count",
    "_assign_control_to_job",
    "_resume_control",
    "_terminate_control",
    "_close_handle",
)
_SUPERVISOR_BOUND_FUNCTIONS = _SUPERVISOR_FUNCTIONS + (
    "_new_job",
    "_new_pipe",
    "_environment_block",
    "_worker_bootstrap",
)
_SUPERVISOR_IDENTITY_FUNCTIONS = _SUPERVISOR_BOUND_FUNCTIONS + ("_hold_runtime_files",)
_PHASES = frozenset(
    {
        "source_binding",
        "winapi_factory",
        "create_suspended",
        "pipe_setup",
        "job_assign",
        "job_count_assign",
        "resume",
        "job_count_resume",
        "thread_handle_close",
        "stdin_write",
        "stdin_close",
        "process_wait",
        "process_exit_code",
        "stdout_drain",
        "stderr_drain",
        "pipe_join",
        "job_count_after_exit",
        "cleanup_terminate",
        "cleanup_wait",
        "cleanup_close",
        "complete",
    }
)


class GateError(ValueError):
    """Finite gate rejection."""

    def __init__(self, code: str):
        self.code = code if type(code) is str and _SAFE_CODE.fullmatch(code) else "gate_rejected"
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise GateError(code)


def _module_source(module: Any, expected_name: str, relative: str, expected_sha: str) -> Path:
    path = (VENUE / relative).resolve(strict=True)
    try:
        origin = Path(module.__file__).resolve(strict=True)
        raw = origin.read_bytes()
    except Exception:
        raise GateError("source_module_unavailable") from None
    _require(
        module.__name__ == expected_name
        and origin == path
        and len(raw) <= _MAX_SOURCE_BYTES
        and hashlib.sha256(raw).hexdigest() == expected_sha,
        "source_module_pin_mismatch",
    )
    return path


def _code_origin(function: Any, path: Path) -> bool:
    code = getattr(function, "__code__", None)
    if code is None:
        return False
    try:
        return Path(code.co_filename).resolve(strict=False) == path
    except Exception:
        return False


def _bind_sources(
    reader: Any, expected_supervisor: Any, expected_worker: Any
) -> tuple[Any, Path, Path]:
    _require(os.name == "nt", "windows_required")
    _require(
        getattr(reader, "job_supervisor", None) is expected_supervisor
        and getattr(reader, "worker", None) is expected_worker,
        "held_module_binding_mismatch",
    )
    reader_path = _module_source(
        reader,
        "_m01_readonly_monitor_v3.current_reader",
        READER_RELATIVE,
        READER_SHA256,
    )
    supervisor = expected_supervisor
    supervisor_path = _module_source(
        supervisor,
        "_m01_readonly_monitor_v2.job_supervisor",
        SUPERVISOR_RELATIVE,
        SUPERVISOR_SHA256,
    )
    worker = expected_worker
    _module_source(
        worker,
        "_m01_readonly_monitor_v2.worker",
        WORKER_RELATIVE,
        WORKER_SHA256,
    )
    _require(supervisor.worker is worker, "worker_binding_mismatch")
    _require(
        reader._root_helper_wrapper.__globals__ is reader.__dict__
        and reader._run_pinned_root_helper.__globals__ is reader.__dict__,
        "reader_global_binding_mismatch",
    )
    _require(
        reader.__dict__.get("job_supervisor") is supervisor
        and reader.__dict__.get("worker") is worker,
        "reader_global_module_mismatch",
    )
    _require(
        supervisor.__dict__.get("worker") is worker,
        "supervisor_global_worker_mismatch",
    )
    _require(
        _code_origin(reader._root_helper_wrapper, reader_path)
        and _code_origin(reader._run_pinned_root_helper, reader_path),
        "reader_code_origin_mismatch",
    )
    for name in _SUPERVISOR_BOUND_FUNCTIONS:
        function = getattr(supervisor, name, None)
        _require(
            callable(function)
            and _code_origin(function, supervisor_path)
            and function.__globals__ is supervisor.__dict__,
            "supervisor_code_origin_mismatch",
        )
    runtime_holder = getattr(supervisor, "_hold_runtime_files", None)
    if _is_source_function(runtime_holder, supervisor_path):
        _require(
            runtime_holder.__globals__ is supervisor.__dict__,
            "runtime_holder_global_binding_mismatch",
        )
    return supervisor, reader_path, supervisor_path


def _error_category(
    exc: BaseException, reader: Any, supervisor: Any
) -> tuple[str, str | None, int | None]:
    code = None
    if isinstance(exc, reader.CurrentReaderError):
        category = "reader_error"
        value = getattr(exc, "code", None)
        code = value if type(value) is str and _SAFE_CODE.fullmatch(value) else None
    elif isinstance(exc, supervisor.ObserverError):
        category = "supervisor_error"
        value = getattr(exc, "reason", None)
        code = value if type(value) is str and _SAFE_CODE.fullmatch(value) else None
    elif isinstance(exc, TimeoutError):
        category = "timeout"
    elif isinstance(exc, OSError):
        category = "os_error"
    elif isinstance(exc, ValueError):
        category = "value_error"
    elif isinstance(exc, Exception):
        category = "exception"
    else:
        category = "base_exception"
    raw_winerror = getattr(exc, "winerror", None)
    winerror = (
        raw_winerror if type(raw_winerror) is int and 0 < raw_winerror <= _WINERROR_MAX else None
    )
    return category, code, winerror


class _Observation:
    def __init__(self, reader: Any, supervisor: Any):
        self.reader = reader
        self.supervisor = supervisor
        self.lock = threading.RLock()
        self.local = threading.local()
        self.phase = "source_binding"
        self.failed_phase = None
        self.error_category = None
        self.error_code = None
        self.native_api = None
        self.native_winerror = None
        self.native_failure_seen = False
        self.control = None
        self.raw_kernel = None
        self.kernel_proxy = None
        self.open_handles: set[int] = set()
        self.created = False
        self.assigned = False
        self.resumed = False
        self.source_write_ok = False
        self.stdin_closed = False
        self.wait_results: list[bool] = []
        self.process_exit_code_present = False
        self.process_exit_code_zero = False
        self.job_counts: list[int] = []
        self.stdout_eof = False
        self.stderr_eof = False
        self.stdout_done = False
        self.stderr_done = False
        self.stdout_error = False
        self.stderr_error = False
        self.stdout_overflow = False
        self.stderr_overflow = False
        self.thread_starts = {"stdout": False, "stderr": False}
        self.thread_joins = {"stdout": False, "stderr": False}
        self.thread_references: list[Any] = []
        self.pipe_state_references: list[Any] = []
        self.terminate_requested = False
        self.terminate_succeeded = False
        self.close_calls = 0
        self.close_failures = 0
        self.last_close_all_succeeded = False
        self.pipes_eof_complete = False
        self.output_matches = False
        self.stderr_empty = False
        self.sourcefake = False
        self.control_reference = None
        self.kernel_reference = None
        self.sibling_registry = None
        self.runtime_registry = getattr(supervisor, "_ORPHANED_RUNTIME_HANDLE_SETS", None)
        self.runtime_registry_empty_before = (
            isinstance(self.runtime_registry, list) and not self.runtime_registry
        )
        self.runtime_registry_length_before = (
            len(self.runtime_registry) if isinstance(self.runtime_registry, list) else None
        )

    def current_phase(self) -> str:
        return getattr(self.local, "phase", self.phase)

    def enter(self, phase: str) -> str:
        previous = self.current_phase()
        with self.lock:
            self.phase = phase if phase in _PHASES else "create_suspended"
        self.local.phase = phase
        return previous

    def leave(self, previous: str) -> None:
        self.local.phase = previous
        with self.lock:
            self.phase = previous if previous in _PHASES else "create_suspended"

    def failed(self, phase: str, exc: BaseException) -> None:
        category, code, winerror = _error_category(exc, self.reader, self.supervisor)
        with self.lock:
            if self.failed_phase is None:
                self.failed_phase = phase if phase in _PHASES else "create_suspended"
                self.error_category = category
                self.error_code = code
                if winerror is not None:
                    self.native_winerror = winerror

    def native_failure(self, name: str, phase: str, winerror: int | None) -> None:
        with self.lock:
            self.native_failure_seen = True
            if self.native_api is None:
                self.native_api = name if name in _WIN32_NAMES else "other_win32_call"
                self.native_winerror = (
                    winerror if type(winerror) is int and 0 < winerror <= _WINERROR_MAX else None
                )
                if self.failed_phase is None:
                    self.failed_phase = phase if phase in _PHASES else "create_suspended"
                    self.error_category = "win32_call_failed"

    def native_exception(self, name: str, phase: str, exc: BaseException) -> None:
        category, _code, winerror = _error_category(exc, self.reader, self.supervisor)
        if winerror is None:
            winerror = _last_error()
        self.native_failure(name, phase, winerror)
        if self.error_category is None:
            with self.lock:
                self.error_category = category

    def result(self) -> dict[str, bool | str | int | None]:
        with self.lock:
            has_output = self.output_matches and self.stderr_empty
            cleanup_certain = (
                bool(self.wait_results)
                and self.wait_results[0]
                and self.process_exit_code_present
                and self.assigned
                and self.job_counts
                and self.job_counts[-1] == 0
                and self.stdout_eof
                and self.stderr_eof
                and self.stdout_done
                and self.stderr_done
                and not self.stdout_error
                and not self.stderr_error
                and not self.stdout_overflow
                and not self.stderr_overflow
                and self.thread_starts["stdout"]
                and self.thread_starts["stderr"]
                and self.thread_joins["stdout"]
                and self.thread_joins["stderr"]
                and self.last_close_all_succeeded
                and not self.open_handles
            )
            if self.failed_phase is not None:
                phase = self.failed_phase
                status = "LIFECYCLE_BLOCKED"
            elif not cleanup_certain:
                phase = self.phase if self.phase in _PHASES else "cleanup_close"
                status = "CLEANUP_UNCONFIRMED"
            elif not has_output or not self.process_exit_code_zero:
                phase = "complete"
                status = "OUTPUT_MISMATCH"
            else:
                phase = "complete"
                status = "SOURCE_FAKE_ONLY" if self.sourcefake else "LOCAL_SYNTHETIC_CHILD"
            retained = bool(_ORPHANED_GATE_CONTEXTS and _ORPHANED_GATE_CONTEXTS[-1][0] is self)
            return {
                "schema": "iteration41.okx.m01.root-helper-lifecycle-gate.v1",
                "status": status,
                "phase": phase,
                "error_category": self.error_category,
                "error_code": self.error_code,
                "win32_api": self.native_api,
                "winerror": self.native_winerror,
                "reader_source_pinned": True,
                "supervisor_source_pinned": True,
                "worker_source_pinned": True,
                "source_functions_restored": True,
                "process_created": self.created,
                "job_assigned_before_resume": self.assigned,
                "resumed": self.resumed,
                "source_frame_write_succeeded": self.source_write_ok,
                "stdin_close_succeeded": self.stdin_closed,
                "process_wait_succeeded": bool(self.wait_results and self.wait_results[0]),
                "cleanup_wait_attempted": len(self.wait_results) > 1,
                "cleanup_wait_succeeded": len(self.wait_results) > 1 and self.wait_results[1],
                "process_reaped_after_cleanup": bool(self.wait_results and self.wait_results[-1]),
                "process_exit_code_present": self.process_exit_code_present,
                "process_exit_code_zero": self.process_exit_code_zero,
                "job_count_observed": bool(self.job_counts),
                "job_zero_after_exit": bool(self.job_counts and self.job_counts[-1] == 0),
                "stdout_eof": self.stdout_eof,
                "stderr_eof": self.stderr_eof,
                "stdout_read_done": self.stdout_done,
                "stderr_read_done": self.stderr_done,
                "stdout_read_error": self.stdout_error,
                "stderr_read_error": self.stderr_error,
                "stdout_overflow": self.stdout_overflow,
                "stderr_overflow": self.stderr_overflow,
                "stdout_matches_fixed": self.output_matches,
                "stderr_empty": self.stderr_empty,
                "stdout_thread_started": self.thread_starts["stdout"],
                "stderr_thread_started": self.thread_starts["stderr"],
                "stdout_thread_joined": self.thread_joins["stdout"],
                "stderr_thread_joined": self.thread_joins["stderr"],
                "termination_requested": self.terminate_requested,
                "termination_succeeded": self.terminate_succeeded,
                "handle_close_calls": self.close_calls,
                "handle_close_failures": self.close_failures,
                "all_observed_handles_closed": not self.open_handles,
                "runtime_registry_empty_before": self.runtime_registry_empty_before,
                "runtime_registry_empty_after": (
                    isinstance(self.runtime_registry, list) and not self.runtime_registry
                ),
                "runtime_registry_unchanged": (
                    self.supervisor._ORPHANED_RUNTIME_HANDLE_SETS is self.runtime_registry
                    and isinstance(self.runtime_registry, list)
                    and len(self.runtime_registry) == self.runtime_registry_length_before
                ),
                "retained_context": retained,
                "source_fake_only": self.sourcefake,
                "production_acceptance": False,
            }


def _last_error() -> int | None:
    getter = getattr(ctypes, "get_last_error", None)
    try:
        value = getter() if callable(getter) else None
    except Exception:
        return None
    return value if type(value) is int and 0 < value <= _WINERROR_MAX else None


def _handle_value(value: Any) -> int | None:
    if type(value) is int:
        return value if value else None
    raw = getattr(value, "value", None)
    return raw if type(raw) is int and raw else None


class _ObservedWinCall:
    def __init__(self, kernel: "_ObservedKernel", name: str, original: Any):
        self.kernel = kernel
        self.name = name
        self.original = original

    def __call__(self, *args, **kwargs):
        phase = self.kernel.observation.current_phase()
        try:
            result = self.original(*args, **kwargs)
        except BaseException as exc:
            self.kernel.observation.native_exception(self.name, phase, exc)
            raise
        native_error = _last_error()
        self.kernel.capture_handles(self.name, args, result)
        if self.kernel.failed_result(self.name, args, result, native_error):
            self.kernel.observation.native_failure(self.name, phase, native_error)
        return result


class _ObservedKernel:
    def __init__(self, raw: Any, observation: _Observation):
        self.raw = raw
        self.observation = observation

    def __getattr__(self, name: str):
        if name not in _WIN32_NAMES:
            raise AttributeError(name)
        return _ObservedWinCall(self, name, getattr(self.raw, name))

    def failed_result(
        self, name: str, args: tuple[Any, ...], result: Any, error: int | None
    ) -> bool:
        if name == "DeleteProcThreadAttributeList":
            return False
        if name == "InitializeProcThreadAttributeList" and args and args[0] is None:
            return False
        if name == "ReadFile" and result is False and error == _ERROR_BROKEN_PIPE:
            return False
        if name == "WaitForSingleObject" and result in (_WAIT_OBJECT_0, _WAIT_TIMEOUT):
            return False
        if name == "ResumeThread":
            return result != 1
        if name in {"CreateJobObjectW", "CreateFileW"}:
            value = _handle_value(result)
            return value is None or value == _INVALID_HANDLE
        if name == "CreatePipe":
            return not bool(result)
        if name == "CreateProcessW":
            return not bool(result)
        if name == "GetExitCodeProcess":
            return not bool(result)
        if name in _WIN32_NAMES:
            return result is False or result == 0
        return False

    def capture_handles(self, name: str, args: tuple[Any, ...], result: Any) -> None:
        if name in {"CreateFileW", "CreateJobObjectW"}:
            value = _handle_value(result)
            if value is not None and value != _INVALID_HANDLE:
                with self.observation.lock:
                    self.observation.open_handles.add(value)
        elif name == "CreatePipe" and bool(result) and len(args) >= 2:
            try:
                read_handle = ctypes.cast(args[0], ctypes.POINTER(wintypes.HANDLE)).contents.value
                write_handle = ctypes.cast(args[1], ctypes.POINTER(wintypes.HANDLE)).contents.value
                for value in (read_handle, write_handle):
                    if value:
                        with self.observation.lock:
                            self.observation.open_handles.add(int(value))
            except Exception:
                pass
        elif name == "CreateProcessW" and bool(result) and args:
            try:
                process_info = ctypes.cast(
                    args[-1], ctypes.POINTER(self.observation.supervisor._PROCESS_INFORMATION)
                ).contents
                for value in (process_info.hProcess, process_info.hThread):
                    handle = _handle_value(value)
                    if handle is not None:
                        with self.observation.lock:
                            self.observation.open_handles.add(handle)
            except Exception:
                pass
        elif name == "CloseHandle" and args:
            value = _handle_value(args[0])
            if value is not None:
                self.observation.close_calls += 1
                if bool(result):
                    with self.observation.lock:
                        self.observation.open_handles.discard(value)
                else:
                    self.observation.close_failures += 1
                    self.observation.native_failure(
                        "CloseHandle", self.observation.current_phase(), _last_error()
                    )


def _phase_for_close(observation: _Observation, handle: Any) -> str:
    control = observation.control
    value = _handle_value(handle)
    if observation.current_phase() == "create_suspended" or control is None:
        return "pipe_setup"
    if value == _handle_value(control.get("thread")):
        return "thread_handle_close"
    if value == _handle_value(control.get("stdin")):
        return "stdin_close"
    return "cleanup_close"


def _install_wrappers(reader: Any, supervisor: Any, observation: _Observation):
    originals = {name: getattr(supervisor, name) for name in _SUPERVISOR_FUNCTIONS}
    original_reader_threading = reader.threading
    original_thread = original_reader_threading.Thread
    wrappers: dict[str, Any] = {}

    def wrap(name: str, phase_fn):
        original = originals[name]

        def observed(*args, **kwargs):
            phase = phase_fn(args, kwargs)
            previous = observation.enter(phase)
            try:
                result = original(*args, **kwargs)
            except BaseException as exc:
                observation.failed(phase, exc)
                raise
            else:
                if name == "_winapi":
                    observation.raw_kernel = result
                    observation.kernel_proxy = _ObservedKernel(result, observation)
                    return observation.kernel_proxy
                if name == "_create_suspended":
                    observation.control = result
                    observation.created = type(result) is dict and bool(result.get("process"))
                    observation.control_reference = result
                    observation.kernel_reference = args[0] if args else None
                    observation.sibling_registry = supervisor._ORPHANED_RUNTIME_HANDLE_SETS
                elif name == "_drain":
                    handle, state = args[1], args[2]
                    observation.pipe_state_references.append(state)
                    label = (
                        "stdout"
                        if observation.control and handle == observation.control.get("stdout")
                        else "stderr"
                    )
                    setattr(observation, label + "_eof", state.get("eof") is True)
                    setattr(observation, label + "_done", state.get("done") is True)
                    setattr(observation, label + "_error", state.get("error") is True)
                    setattr(observation, label + "_overflow", state.get("overflow") is True)
                elif name == "_write_all":
                    observation.source_write_ok = result is True
                elif name == "_wait_process":
                    observation.wait_results.append(result is True)
                    if observation.terminate_requested:
                        observation.phase = "cleanup_wait"
                elif name == "_process_exit_code":
                    observation.process_exit_code_present = type(result) is int
                    observation.process_exit_code_zero = type(result) is int and result == 0
                elif name == "_active_count":
                    if type(result) is int:
                        observation.job_counts.append(result)
                elif name == "_assign_control_to_job":
                    observation.assigned = bool(
                        observation.control and observation.control.get("assigned")
                    )
                elif name == "_resume_control":
                    observation.resumed = True
                elif name == "_terminate_control":
                    observation.terminate_requested = True
                    observation.terminate_succeeded = bool(result)
                elif name == "_close_handle":
                    if observation.control is not None:
                        observation.stdin_closed = (
                            observation.stdin_closed
                            or _handle_value(args[2])
                            == _handle_value(observation.control.get("stdin"))
                            and result is True
                        )
                return result
            finally:
                observation.leave(previous)

        wrappers[name] = observed
        setattr(supervisor, name, observed)

    try:
        phase_functions = {
            "_winapi": lambda _args, _kwargs: "winapi_factory",
            "_new_pipe_state": lambda _args, _kwargs: "pipe_setup",
            "_create_suspended": lambda _args, _kwargs: "create_suspended",
            "_drain": lambda args, _kwargs: (
                "stdout_drain"
                if observation.control and args[1] == observation.control.get("stdout")
                else "stderr_drain"
            ),
            "_write_all": lambda _args, _kwargs: "stdin_write",
            "_wait_process": lambda _args, _kwargs: (
                "cleanup_wait"
                if observation.terminate_requested or observation.wait_results
                else "process_wait"
            ),
            "_process_exit_code": lambda _args, _kwargs: "process_exit_code",
            "_active_count": lambda _args, _kwargs: (
                "job_count_assign"
                if observation.current_phase() == "job_assign"
                else "job_count_resume"
                if observation.current_phase() == "resume"
                else "job_count_after_exit"
            ),
            "_assign_control_to_job": lambda _args, _kwargs: "job_assign",
            "_resume_control": lambda _args, _kwargs: "resume",
            "_terminate_control": lambda _args, _kwargs: "cleanup_terminate",
            "_close_handle": lambda args, _kwargs: _phase_for_close(observation, args[2]),
        }
        for name in _SUPERVISOR_FUNCTIONS:
            wrap(name, phase_functions[name])

        class ObservedThread(original_thread):
            def _label(self):
                return (
                    "stdout"
                    if str(getattr(self, "name", "")).endswith("stdout-drain")
                    else "stderr"
                )

            def start(self):
                label = self._label()
                previous = observation.enter("pipe_setup")
                try:
                    observation.thread_references.append(self)
                    result = super().start()
                    observation.thread_starts[label] = True
                    return result
                except BaseException as exc:
                    observation.failed("pipe_setup", exc)
                    raise
                finally:
                    observation.leave(previous)

            def join(self, timeout=None):
                label = self._label()
                previous = observation.enter("pipe_join")
                try:
                    result = super().join(timeout)
                    observation.thread_joins[label] = not self.is_alive()
                    return result
                except BaseException as exc:
                    observation.failed("pipe_join", exc)
                    raise
                finally:
                    observation.leave(previous)

        reader.threading = SimpleNamespace(Thread=ObservedThread)
        return originals, original_reader_threading
    except BaseException:
        for name, original in originals.items():
            setattr(supervisor, name, original)
        reader.threading = original_reader_threading
        raise


def _restore_wrappers(
    reader: Any, supervisor: Any, originals: dict[str, Any], original_threading: Any
) -> bool:
    try:
        for name, original in originals.items():
            setattr(supervisor, name, original)
        reader.threading = original_threading
        return all(getattr(supervisor, name) is original for name, original in originals.items())
    except Exception:
        return False


def _is_source_function(function: Any, path: Path) -> bool:
    return callable(function) and _code_origin(function, path)


def run_fixed_synthetic_probe(
    reader_module: Any, supervisor_module: Any, worker_module: Any
) -> dict[str, bool | str | int | None]:
    """Run one fixed no-network child through the pinned reader and supervisor.

    Root must pass its exact held reader, V2 supervisor, and worker module
    objects. This helper emits only finite lifecycle facts, never child
    output, paths, handles, environment values, credentials, or exception text.
    """
    with _OBSERVATION_LOCK:
        supervisor, reader_path, supervisor_path = _bind_sources(
            reader_module, supervisor_module, worker_module
        )
        observation = _Observation(reader_module, supervisor)
        _observation_originals = {
            name: getattr(supervisor, name) for name in _SUPERVISOR_IDENTITY_FUNCTIONS
        }
        reader_wrapper_originals = (
            reader_module._root_helper_wrapper,
            reader_module._run_pinned_root_helper,
        )
        wrappers = None
        original_threading = reader_module.threading
        result = None
        outer_error = None
        wrappers_restored = False
        try:
            wrappers, original_threading = _install_wrappers(reader_module, supervisor, observation)
            wrapper = reader_module._root_helper_wrapper(SYNTHETIC_HELPER)
            system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or "C:\\Windows"
            environment = {"SYSTEMROOT": system_root, "WINDIR": system_root}
            result = reader_module._run_pinned_root_helper(
                wrapper,
                environment,
                timeout_seconds=60.0,
            )
        except BaseException as exc:
            outer_error = exc
            phase = observation.current_phase()
            observation.failed(phase, exc)
        finally:
            if wrappers is not None:
                wrappers_restored = _restore_wrappers(
                    reader_module, supervisor, wrappers, original_threading
                )

        observation.pipes_eof_complete = (
            observation.stdout_eof
            and observation.stderr_eof
            and observation.stdout_done
            and observation.stderr_done
            and not observation.stdout_error
            and not observation.stderr_error
            and not observation.stdout_overflow
            and not observation.stderr_overflow
        )
        if result is not None:
            try:
                observation.output_matches = result[0] == SYNTHETIC_OUTPUT
                observation.stderr_empty = result[1] == b""
                observation.assigned = (
                    observation.assigned and result[4].get("assigned_before_resume") is True
                )
                observation.job_counts.append(
                    result[4].get("active_count_after_exit")
                    if type(result[4].get("active_count_after_exit")) is int
                    else -1
                )
            except Exception:
                observation.output_matches = False
                observation.stderr_empty = False
        if outer_error is not None and observation.error_category is None:
            category, code, winerror = _error_category(outer_error, reader_module, supervisor)
            observation.error_category = category
            observation.error_code = code
            observation.native_winerror = winerror
        observation.last_close_all_succeeded = (
            not observation.open_handles and observation.close_failures == 0
        )
        if not wrappers_restored:
            observation.failed("cleanup_close", GateError("source_restore_failed"))
        identities_restored = (
            all(
                getattr(supervisor, name) is original
                for name, original in _observation_originals.items()
            )
            and reader_module._root_helper_wrapper is reader_wrapper_originals[0]
            and reader_module._run_pinned_root_helper is reader_wrapper_originals[1]
        )
        if not identities_restored:
            observation.failed("cleanup_close", GateError("source_identity_restore_failed"))
        observation.sourcefake = not _is_source_function(
            _observation_originals["_hold_runtime_files"], supervisor_path
        )
        uncertain = (
            not observation.wait_results
            or not observation.wait_results[0]
            or not observation.process_exit_code_present
            or not observation.job_counts
            or observation.job_counts[-1] != 0
            or not observation.pipes_eof_complete
            or not all(observation.thread_joins.values())
            or bool(observation.open_handles)
            or observation.close_failures > 0
            or not wrappers_restored
        )
        if uncertain:
            _ORPHANED_GATE_CONTEXTS.append(
                (
                    observation,
                    reader_module,
                    supervisor,
                    observation.raw_kernel,
                    observation.kernel_proxy,
                    observation.control_reference,
                    tuple(observation.thread_references),
                    tuple(observation.pipe_state_references),
                    tuple(observation.open_handles),
                    supervisor._ORPHANED_RUNTIME_HANDLE_SETS,
                )
            )
        output = observation.result()
        output["source_functions_restored"] = wrappers_restored and identities_restored
        output["retained_context"] = bool(
            _ORPHANED_GATE_CONTEXTS and _ORPHANED_GATE_CONTEXTS[-1][0] is observation
        )
        return output
