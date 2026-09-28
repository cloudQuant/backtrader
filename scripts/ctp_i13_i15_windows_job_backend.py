"""Windows Job backend for the offline I13/I15 outer-watchdog contract.

This module is not registered with a CLI and has no config, marker, provider,
SDK, or network behavior. It launches only the fixed argv/cwd/environment
received from its caller. The current integration tests use inert local Python
children; fake-kernel tests cover API call order and ownership failures.

The backend requires ``PROC_THREAD_ATTRIBUTE_JOB_LIST``. It creates a private
Job with ``KILL_ON_JOB_CLOSE`` and starts the launcher suspended with that Job
in the startup attribute list. It deliberately has no post-create assignment
fallback. Unsupported Windows versions and any failed/ambiguous setup reject
or return an unresumed session for fail-closed cleanup.

The process-wide custodian keeps active sessions and retained sessions alive
independently of the short-lived backend object. Retention tokens refer only to
that in-process custody registry. Closing the host process closes its Job
handles, which requests Job termination through ``KILL_ON_JOB_CLOSE``; this
does not prove that a hard deadline can interrupt a host blocked in a native
API.
"""

from __future__ import annotations

import atexit
import ctypes
import math
import os
import secrets
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from scripts.ctp_i13_i15_outer_watchdog import OuterBackendCreationError


_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_MAX_RECONCILE_SECONDS = 30.0


def _monotonic() -> float:
    """Keep the setup clock replaceable in inert contract tests."""

    return time.monotonic()


class WindowsJobBackendError(OuterBackendCreationError):
    """Redacted failure from the Windows Job backend."""

    def __init__(self, reason: str, *, retention_token: Optional[str] = None) -> None:
        super().__init__(reason, retention_token=retention_token)


@dataclass(frozen=True)
class RetainedControlResolution:
    """Value-free result of one explicit retry for a retained control token."""

    state: str
    reason: str
    process_exit_observed: Optional[bool]
    job_empty_observed: Optional[bool]
    termination_call_succeeded: Optional[bool]
    controls_released: bool


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", wintypes.LPVOID)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _JOBOBJECT_IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


def _as_handle(value: Any) -> int:
    if value is None:
        return 0
    if type(value) is int:
        return value
    raw = getattr(value, "value", None)
    if type(raw) is int:
        return raw
    raise WindowsJobBackendError("native_handle_invalid")


def _load_kernel32() -> Any:
    if os.name != "nt":
        raise WindowsJobBackendError("windows_required")
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.INT,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.INT,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOW),
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL
        kernel32.InitializeProcThreadAttributeList.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel32.UpdateProcThreadAttribute.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
        kernel32.DeleteProcThreadAttributeList.restype = None
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        return kernel32
    except Exception:
        raise WindowsJobBackendError("native_api_unavailable") from None


def _load_advapi32() -> Any:
    """Load only the alternate-token process entry point used by read-only workers."""

    if os.name != "nt":
        raise WindowsJobBackendError("windows_required")
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.CreateProcessAsUserW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOW),
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        advapi32.CreateProcessAsUserW.restype = wintypes.BOOL
        return advapi32
    except Exception:
        raise WindowsJobBackendError("alternate_user_process_api_unavailable") from None


def _environment_block(env: Dict[str, str]) -> Any:
    ordered = sorted(env.items(), key=lambda item: item[0].casefold())
    value = "\0".join("{}={}".format(key, item) for key, item in ordered) + "\0\0"
    return ctypes.create_unicode_buffer(value)


def _validate_command(command: Any) -> Tuple[Tuple[str, ...], str, Dict[str, str]]:
    argv = getattr(command, "argv", None)
    cwd = getattr(command, "cwd", None)
    env = getattr(command, "env", None)
    if type(argv) is not tuple or not argv:
        raise WindowsJobBackendError("outer_command_argv_invalid")
    if any(type(part) is not str or not part or "\0" in part for part in argv):
        raise WindowsJobBackendError("outer_command_argv_invalid")
    if not os.path.isabs(argv[0]):
        raise WindowsJobBackendError("outer_executable_must_be_absolute")
    if type(cwd) is not str or not os.path.isabs(cwd) or "\0" in cwd:
        raise WindowsJobBackendError("outer_command_cwd_invalid")
    if not isinstance(env, dict) and not hasattr(env, "items"):
        raise WindowsJobBackendError("outer_command_environment_invalid")
    environment: Dict[str, str] = {}
    seen = set()
    try:
        items = env.items()
        for key, value in items:
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or "=" in key
                or "\0" in key
                or "\0" in value
            ):
                raise WindowsJobBackendError("outer_command_environment_invalid")
            folded = key.casefold()
            if folded in seen:
                raise WindowsJobBackendError("outer_command_environment_invalid")
            seen.add(folded)
            environment[key] = value
    except WindowsJobBackendError:
        raise
    except Exception:
        raise WindowsJobBackendError("outer_command_environment_invalid") from None
    return argv, cwd, environment


def _query_job_active_processes(kernel32: Any, job: int) -> Optional[int]:
    info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    succeeded = kernel32.QueryInformationJobObject(
        job,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    )
    if not succeeded:
        return None
    return int(info.ActiveProcesses)


def _ensure_before_deadline(deadline_monotonic: float) -> None:
    """Reject another setup step once the caller's whole-command budget ends."""

    if _monotonic() >= deadline_monotonic:
        raise WindowsJobBackendError("outer_deadline_expired")


def _create_job(kernel32: Any) -> int:
    raw = kernel32.CreateJobObjectW(None, None)
    job = _as_handle(raw)
    if not job:
        raise WindowsJobBackendError("job_create_failed")
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    native_interruption = None
    try:
        succeeded = kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    except BaseException as error:
        succeeded = False
        native_interruption = error
    if not succeeded:
        try:
            closed = bool(kernel32.CloseHandle(job))
        except Exception:
            closed = False
        if not closed:
            token = _CUSTODIAN.retain_orphan_job(kernel32, job)
            raise WindowsJobBackendError(
                "job_kill_on_close_setup_failed", retention_token=token
            )
        if native_interruption is not None and not isinstance(
            native_interruption, Exception
        ):
            raise native_interruption
        raise WindowsJobBackendError("job_kill_on_close_setup_failed")
    return job


class _WindowsJobSession:
    """Single owner for the Job, process, thread, and deferred startup-list handles."""

    process_created = True

    def __init__(
        self,
        custodian: "_ProcessCustodian",
        kernel32: Any,
        job: int,
        process: Optional[int],
        thread: Optional[int],
        *,
        assignment_observed: Optional[bool],
        attribute_list: Any = None,
        attribute_storage: Any = None,
        job_handle_array: Any = None,
    ) -> None:
        self._custodian = custodian
        self._lock = threading.RLock()
        self._kernel32 = kernel32
        self._job_handle: Optional[int] = job
        self._process_handle: Optional[int] = process
        self._thread_handle: Optional[int] = thread
        self._attribute_list = attribute_list
        self._attribute_storage = attribute_storage
        self._job_handle_array = job_handle_array
        self.job_assignment_observed = assignment_observed
        self._resume_attempted = False
        self._resumed = False
        self._exit_observed = False
        self._exit_code: Optional[int] = None
        self._job_empty_observed: Optional[bool] = None
        self._closed = False
        self._custody_token = _new_token()

    def resume_launcher(self) -> bool:
        with self._lock:
            if (
                self.job_assignment_observed is not True
                or self._thread_handle is None
                or self._resume_attempted
            ):
                return False
            self._resume_attempted = True
            try:
                previous_count = int(self._kernel32.ResumeThread(self._thread_handle))
            except Exception:
                return False
            if previous_count != 1:
                return False
            self._resumed = True
            try:
                if self._kernel32.CloseHandle(self._thread_handle):
                    self._thread_handle = None
            except Exception:
                pass
            # A failed thread-handle close is retained for release after
            # Job-empty evidence. It does not undo a successful resume.
            return True

    def poll_launcher_exit_code(self) -> Optional[int]:
        with self._lock:
            if self._exit_observed:
                return self._exit_code
            if self._process_handle is None:
                raise WindowsJobBackendError("process_exit_handle_unavailable")
            try:
                wait_result = self._kernel32.WaitForSingleObject(self._process_handle, 0)
            except Exception:
                raise WindowsJobBackendError("process_wait_failed") from None
            if wait_result == _WAIT_TIMEOUT:
                return None
            if wait_result != _WAIT_OBJECT_0:
                raise WindowsJobBackendError("process_wait_failed")
            exit_code = wintypes.DWORD()
            try:
                succeeded = self._kernel32.GetExitCodeProcess(
                    self._process_handle, ctypes.byref(exit_code)
                )
            except Exception:
                succeeded = False
            if not succeeded:
                raise WindowsJobBackendError("process_exit_code_unavailable")
            self._exit_observed = True
            self._exit_code = int(exit_code.value)
            return self._exit_code

    def poll_job_empty(self) -> Optional[bool]:
        with self._lock:
            if self._job_empty_observed is True:
                return True
            if self._job_handle is None:
                raise WindowsJobBackendError("job_empty_evidence_unavailable")
            try:
                active = _query_job_active_processes(self._kernel32, self._job_handle)
            except Exception:
                active = None
            if active is None:
                raise WindowsJobBackendError("job_accounting_unavailable")
            self._job_empty_observed = active == 0
            return self._job_empty_observed

    def terminate_job(self) -> Optional[bool]:
        with self._lock:
            if self._job_handle is None:
                return None
            try:
                return bool(self._kernel32.TerminateJobObject(self._job_handle, 0xEE13))
            except Exception:
                return None

    def terminate_launcher_process(self) -> Optional[bool]:
        with self._lock:
            if self._process_handle is None or self._resumed:
                return None
            try:
                return bool(self._kernel32.TerminateProcess(self._process_handle, 0xEE14))
            except Exception:
                return None

    def release_controls(self) -> bool:
        """Close only after fresh process-exit and Job-empty observations."""

        with self._lock:
            try:
                exit_code = self.poll_launcher_exit_code()
                job_empty = self.poll_job_empty()
            except Exception:
                return False
            if exit_code is None or job_empty is not True:
                return False

            if self._attribute_list is not None:
                try:
                    self._kernel32.DeleteProcThreadAttributeList(self._attribute_list)
                except Exception:
                    return False
                self._attribute_list = None
                self._attribute_storage = None
                self._job_handle_array = None

            for field_name in ("_thread_handle", "_process_handle", "_job_handle"):
                handle = getattr(self, field_name)
                if handle is None:
                    continue
                try:
                    closed = bool(self._kernel32.CloseHandle(handle))
                except Exception:
                    closed = False
                if not closed:
                    return False
                setattr(self, field_name, None)

            self._closed = True
            self._custodian.forget_session(self)
            return True

    def _close_for_host_exit(self) -> None:
        """Use kill-on-close as the final host-shutdown containment action."""

        with self._lock:
            if self._job_handle is not None:
                try:
                    closed = bool(self._kernel32.CloseHandle(self._job_handle))
                except Exception:
                    closed = False
                if closed:
                    self._job_handle = None
            for field_name in ("_thread_handle", "_process_handle"):
                handle = getattr(self, field_name)
                if handle is None:
                    continue
                try:
                    closed = bool(self._kernel32.CloseHandle(handle))
                except Exception:
                    closed = False
                if closed:
                    setattr(self, field_name, None)


def _new_token() -> str:
    return "outerjob-" + secrets.token_hex(16)


class _ProcessCustodian:
    """Module-lifetime owner for active and unresolved Windows controls."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, _WindowsJobSession] = {}
        self._retained_sessions: Dict[str, _WindowsJobSession] = {}
        self._orphan_jobs: Dict[str, Tuple[Any, int]] = {}

    def register_session(self, session: _WindowsJobSession) -> None:
        with self._lock:
            self._sessions[session._custody_token] = session

    def forget_session(self, session: _WindowsJobSession) -> None:
        with self._lock:
            self._sessions.pop(session._custody_token, None)
            self._retained_sessions.pop(session._custody_token, None)

    def retain_session(self, session: _WindowsJobSession) -> Optional[str]:
        with self._lock:
            token = session._custody_token
            if session._closed or self._sessions.get(token) is not session:
                return None
            self._retained_sessions[token] = session
            return token

    def retain_orphan_job(self, kernel32: Any, job: int) -> str:
        token = _new_token()
        with self._lock:
            self._orphan_jobs[token] = (kernel32, job)
        return token

    def retained_tokens(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted(set(self._retained_sessions) | set(self._orphan_jobs)))

    def resolve(
        self, token: str, *, timeout_seconds: float
    ) -> RetainedControlResolution:
        with self._lock:
            session = self._retained_sessions.get(token)
            orphan = self._orphan_jobs.get(token)
        if session is None and orphan is None:
            return RetainedControlResolution(
                "unknown", "retention_token_unknown", None, None, None, False
            )
        deadline = time.monotonic() + timeout_seconds
        termination_succeeded: Optional[bool] = None

        if orphan is not None:
            kernel32, job = orphan
            while True:
                try:
                    active = _query_job_active_processes(kernel32, job)
                except Exception:
                    active = None
                if active == 0:
                    try:
                        released = bool(kernel32.CloseHandle(job))
                    except Exception:
                        released = False
                    if released:
                        with self._lock:
                            self._orphan_jobs.pop(token, None)
                    return RetainedControlResolution(
                        "resolved" if released else "unknown",
                        "orphan_job_closed" if released else "orphan_job_close_unconfirmed",
                        None,
                        True,
                        termination_succeeded,
                        released,
                    )
                try:
                    termination_succeeded = bool(
                        kernel32.TerminateJobObject(job, 0xEE15)
                    )
                except Exception:
                    termination_succeeded = False
                if time.monotonic() >= deadline:
                    return RetainedControlResolution(
                        "unknown",
                        "orphan_job_not_empty",
                        None,
                        False if active is not None else None,
                        termination_succeeded,
                        False,
                    )
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

        assert session is not None
        while True:
            try:
                exit_code = session.poll_launcher_exit_code()
                process_exit = exit_code is not None
            except Exception:
                process_exit = None
            try:
                job_empty = session.poll_job_empty()
            except Exception:
                job_empty = None
            if process_exit is True and job_empty is True:
                released = session.release_controls()
                return RetainedControlResolution(
                    "resolved" if released else "unknown",
                    "controls_released" if released else "control_release_unconfirmed",
                    True,
                    True,
                    termination_succeeded,
                    released,
                )
            if termination_succeeded is not True:
                if session.job_assignment_observed is True:
                    termination_succeeded = session.terminate_job()
                else:
                    termination_succeeded = session.terminate_launcher_process()
            if time.monotonic() >= deadline:
                return RetainedControlResolution(
                    "unknown",
                    "process_tree_not_drained",
                    process_exit,
                    job_empty,
                    termination_succeeded,
                    False,
                )
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    def shutdown(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            orphan_jobs = tuple(self._orphan_jobs.values())
        for session in sessions:
            session._close_for_host_exit()
        for kernel32, job in orphan_jobs:
            try:
                kernel32.CloseHandle(job)
            except Exception:
                pass


_CUSTODIAN = _ProcessCustodian()
atexit.register(_CUSTODIAN.shutdown)


class WindowsJobBackend:
    """Atomic Windows Job launcher backend; ``kernel32`` injection is test-only."""

    def __init__(
        self,
        *,
        kernel32: Any = None,
        advapi32: Any = None,
        primary_token_handle: Optional[int] = None,
        inherited_stdin_handle: Optional[int] = None,
        inherited_stdout_handle: Optional[int] = None,
        inherited_stderr_handle: Optional[int] = None,
        no_inherited_handles: bool = False,
        process_created_callback: Optional[Callable[[int, int], object]] = None,
    ) -> None:
        if primary_token_handle is not None and (
            type(primary_token_handle) is not int or primary_token_handle <= 0
        ):
            raise WindowsJobBackendError("primary_token_invalid")
        stdio_handles = (
            inherited_stdin_handle,
            inherited_stdout_handle,
            inherited_stderr_handle,
        )
        if type(no_inherited_handles) is not bool:
            raise WindowsJobBackendError("no_inherited_handles_flag_invalid")
        if no_inherited_handles and any(handle is not None for handle in stdio_handles):
            raise WindowsJobBackendError("no_inherited_handles_conflict")
        if any(handle is not None for handle in stdio_handles):
            if any(type(handle) is not int or handle <= 0 for handle in stdio_handles):
                raise WindowsJobBackendError("inherited_stdio_handles_invalid")
            inherited_handles = tuple(dict.fromkeys(stdio_handles))
        else:
            inherited_handles = ()
        if process_created_callback is not None and (
            not callable(process_created_callback)
            or no_inherited_handles is not True
        ):
            raise WindowsJobBackendError("suspended_process_binding_invalid")
        self._injected_kernel32 = kernel32
        self._injected_advapi32 = advapi32
        # This is a borrowed handle from the service's authenticated pipe-token
        # context. The backend never closes it; the service keeps it alive until
        # process creation returns and then closes it on every path.
        self._primary_token_handle = primary_token_handle
        self._inherited_stdio_handles = inherited_handles
        self._stdio_handles = stdio_handles
        self._no_inherited_handles = no_inherited_handles
        self._process_created_callback = process_created_callback

    def _kernel32(self) -> Any:
        if self._injected_kernel32 is not None:
            return self._injected_kernel32
        return _load_kernel32()

    def _advapi32(self) -> Any:
        if self._injected_advapi32 is not None:
            return self._injected_advapi32
        return _load_advapi32()

    def create_suspended_in_job(
        self, command: Any, *, deadline_monotonic: float
    ) -> _WindowsJobSession:
        if (
            type(deadline_monotonic) not in (int, float)
            or not math.isfinite(float(deadline_monotonic))
        ):
            raise WindowsJobBackendError("outer_deadline_invalid")
        if _monotonic() >= float(deadline_monotonic):
            raise WindowsJobBackendError("outer_deadline_expired")
        argv, cwd, env = _validate_command(command)
        deadline = float(deadline_monotonic)
        _ensure_before_deadline(deadline)
        kernel32 = self._kernel32()
        _ensure_before_deadline(deadline)
        process_api = (
            self._advapi32()
            if self._primary_token_handle is not None
            else kernel32
        )
        process_create = (
            process_api.CreateProcessAsUserW
            if self._primary_token_handle is not None
            else process_api.CreateProcessW
        )
        job = _create_job(kernel32)
        attribute_list = None
        attribute_storage = None
        job_handle_array = None
        inherited_handle_array = None
        attribute_initialized = False
        process_info = _PROCESS_INFORMATION()

        try:
            # Job creation and its kill-on-close setup are native operations.
            # If either consumed the remaining budget, close/escrow the Job
            # below and do not continue constructing a launcher.
            _ensure_before_deadline(deadline)
            required_size = ctypes.c_size_t()
            _ensure_before_deadline(deadline)
            try:
                attribute_count = 1 + int(bool(self._inherited_stdio_handles))
                kernel32.InitializeProcThreadAttributeList(
                    None, attribute_count, 0, ctypes.byref(required_size)
                )
            except Exception:
                raise WindowsJobBackendError("job_list_attribute_unavailable") from None
            _ensure_before_deadline(deadline)
            if not required_size.value:
                raise WindowsJobBackendError("job_list_attribute_unavailable")
            attribute_storage = ctypes.create_string_buffer(required_size.value)
            attribute_list = ctypes.cast(attribute_storage, wintypes.LPVOID)
            _ensure_before_deadline(deadline)
            try:
                initialized = bool(
                    kernel32.InitializeProcThreadAttributeList(
                        attribute_list, attribute_count, 0, ctypes.byref(required_size)
                    )
                )
            except Exception:
                initialized = False
            if not initialized:
                attribute_list = None
                raise WindowsJobBackendError("job_list_attribute_unavailable")
            attribute_initialized = True
            _ensure_before_deadline(deadline)

            job_handle_array = (wintypes.HANDLE * 1)(job)
            _ensure_before_deadline(deadline)
            try:
                updated = bool(
                    kernel32.UpdateProcThreadAttribute(
                        attribute_list,
                        0,
                        _PROC_THREAD_ATTRIBUTE_JOB_LIST,
                        ctypes.cast(job_handle_array, wintypes.LPVOID),
                        ctypes.sizeof(job_handle_array),
                        None,
                        None,
                    )
                )
            except Exception:
                updated = False
            if not updated:
                raise WindowsJobBackendError("job_list_attribute_unavailable")
            _ensure_before_deadline(deadline)

            if self._inherited_stdio_handles:
                inherited_handle_array = (wintypes.HANDLE * len(self._inherited_stdio_handles))(
                    *self._inherited_stdio_handles
                )
                try:
                    updated = bool(
                        kernel32.UpdateProcThreadAttribute(
                            attribute_list,
                            0,
                            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                            ctypes.cast(inherited_handle_array, wintypes.LPVOID),
                            ctypes.sizeof(inherited_handle_array),
                            None,
                            None,
                        )
                    )
                except Exception:
                    updated = False
                if not updated:
                    raise WindowsJobBackendError("worker_output_handle_list_unavailable")
                _ensure_before_deadline(deadline)

            command_line_text = subprocess.list2cmdline(list(argv))
            if len(command_line_text) >= 32767:
                raise WindowsJobBackendError("outer_command_too_long")
            command_line = ctypes.create_unicode_buffer(command_line_text)
            environment_block = _environment_block(env)
            startup_ex = _STARTUPINFOEXW()
            startup_ex.StartupInfo.cb = ctypes.sizeof(startup_ex)
            startup_ex.lpAttributeList = attribute_list
            inherit_handles = (
                False
                if self._no_inherited_handles
                else bool(self._inherited_stdio_handles)
            )
            if inherit_handles:
                startup_ex.StartupInfo.dwFlags |= _STARTF_USESTDHANDLES
                stdin_handle, stdout_handle, stderr_handle = self._stdio_handles
                startup_ex.StartupInfo.hStdInput = wintypes.HANDLE(stdin_handle)
                startup_ex.StartupInfo.hStdOutput = wintypes.HANDLE(stdout_handle)
                startup_ex.StartupInfo.hStdError = wintypes.HANDLE(stderr_handle)
            flags = (
                _CREATE_SUSPENDED
                | _CREATE_UNICODE_ENVIRONMENT
                | _EXTENDED_STARTUPINFO_PRESENT
                | _CREATE_NO_WINDOW
            )
            # This is the critical setup boundary: never create a new launcher
            # after attribute preparation has exhausted the absolute budget.
            _ensure_before_deadline(deadline)
            startup_pointer = ctypes.cast(
                ctypes.byref(startup_ex), ctypes.POINTER(_STARTUPINFOW)
            )
            if self._primary_token_handle is None:
                created = bool(
                    process_create(
                        argv[0],
                        command_line,
                        None,
                        None,
                        inherit_handles,
                        flags,
                        environment_block,
                        cwd,
                        startup_pointer,
                        ctypes.byref(process_info),
                    )
                )
            else:
                try:
                    created = bool(
                        process_create(
                            self._primary_token_handle,
                            argv[0],
                            command_line,
                            None,
                            None,
                            inherit_handles,
                            flags,
                            environment_block,
                            cwd,
                            startup_pointer,
                            ctypes.byref(process_info),
                        )
                    )
                except BaseException:
                    raise WindowsJobBackendError(
                        "owner_token_process_create_call_failed"
                    ) from None
                if not created:
                    winerror = int(ctypes.get_last_error())
                    raise WindowsJobBackendError(
                        "owner_token_process_create_failed_{}".format(winerror)
                    )

            process_handle = _as_handle(process_info.hProcess)
            thread_handle = _as_handle(process_info.hThread)
            if not created:
                if not process_handle:
                    raise WindowsJobBackendError("atomic_job_process_create_failed")
                session = self._register_session(
                    kernel32,
                    job,
                    process_handle or None,
                    thread_handle or None,
                    False,
                    attribute_list,
                    attribute_storage,
                    job_handle_array,
                )
                try:
                    kernel32.DeleteProcThreadAttributeList(attribute_list)
                except Exception:
                    session.job_assignment_observed = None
                    return session
                session._attribute_list = None
                session._attribute_storage = None
                session._job_handle_array = None
                return session
            if not process_handle or not thread_handle:
                session = self._register_session(
                    kernel32,
                    job,
                    process_handle or None,
                    thread_handle or None,
                    None,
                    attribute_list,
                    attribute_storage,
                    job_handle_array,
                )
                try:
                    kernel32.DeleteProcThreadAttributeList(attribute_list)
                except Exception:
                    return session
                session._attribute_list = None
                session._attribute_storage = None
                session._job_handle_array = None
                return session

            session = self._register_session(
                kernel32,
                job,
                process_handle,
                thread_handle,
                None,
                attribute_list,
                attribute_storage,
                job_handle_array,
            )
            # The job handle array and attribute-list storage remain alive
            # through successful CreateProcessW and until this deletion.
            try:
                kernel32.DeleteProcThreadAttributeList(attribute_list)
            except Exception:
                # Keep the list and its value storage attached to the session;
                # the caller will not resume when assignment is unobserved.
                session.job_assignment_observed = None
                return session
            session._attribute_list = None
            session._attribute_storage = None
            session._job_handle_array = None
            attribute_list = None
            attribute_initialized = False

            # CreateProcessW itself cannot be interrupted by this Python
            # caller. If it returns after the deadline, return the still
            # suspended process with unknown assignment so the outer watchdog
            # terminates it without resuming or doing another setup/query step.
            if _monotonic() >= deadline:
                session.job_assignment_observed = None
                return session

            try:
                active = _query_job_active_processes(kernel32, job)
            except Exception:
                active = None
            if active == 1:
                session.job_assignment_observed = True
                if self._process_created_callback is not None:
                    # The callback receives only the exact process ID after the
                    # atomic JOB_LIST assignment is observed and while the
                    # launcher is still suspended.  A rejected/failed binding
                    # leaves the session unresumable so the outer watchdog
                    # performs its normal fail-closed Job cleanup.
                    try:
                        callback_result = self._process_created_callback(
                            int(process_info.dwProcessId), int(process_handle)
                        )
                    except BaseException:
                        callback_result = None
                    if callback_result is not True:
                        session.job_assignment_observed = None
            elif active == 0:
                session.job_assignment_observed = False
            else:
                # An unexpected count does not prove the launcher is outside
                # the Job, so do not collapse it to a negative assignment.
                session.job_assignment_observed = None
            return session
        except BaseException as error:
            # The native API contract says a failed CreateProcessW call did
            # not create a process. If a fake or wrapper contradicts that, the
            # process-info handles above are transferred into a session.
            process_handle = _as_handle(process_info.hProcess)
            thread_handle = _as_handle(process_info.hThread)
            if process_handle or thread_handle:
                session = self._register_session(
                    kernel32,
                    job,
                    process_handle or None,
                    thread_handle or None,
                    None,
                    attribute_list if attribute_initialized else None,
                    attribute_storage if attribute_initialized else None,
                    job_handle_array if attribute_initialized else None,
                )
                try:
                    session.terminate_job()
                    session.terminate_launcher_process()
                except Exception:
                    pass
                released = False
                try:
                    if (
                        session.poll_launcher_exit_code() is not None
                        and session.poll_job_empty() is True
                    ):
                        released = session.release_controls()
                except Exception:
                    released = False
                token = None if released else self.retain_controls(session)
                reason = (
                    error.reason
                    if isinstance(error, WindowsJobBackendError)
                    else "atomic_job_process_create_outcome_unknown"
                )
                raise WindowsJobBackendError(
                    reason, retention_token=token
                ) from None

            if attribute_initialized and attribute_list is not None:
                try:
                    kernel32.DeleteProcThreadAttributeList(attribute_list)
                except Exception:
                    pass
            try:
                closed = bool(kernel32.CloseHandle(job))
            except Exception:
                closed = False
            token = None if closed else _CUSTODIAN.retain_orphan_job(kernel32, job)
            if isinstance(error, WindowsJobBackendError) or token is not None:
                reason = (
                    error.reason
                    if isinstance(error, WindowsJobBackendError)
                    else "atomic_job_process_create_failed"
                )
                raise WindowsJobBackendError(reason, retention_token=token) from None
            if not isinstance(error, Exception):
                raise
            raise WindowsJobBackendError(
                "atomic_job_process_create_failed", retention_token=token
            ) from None

    def _register_session(
        self,
        kernel32: Any,
        job: int,
        process: Optional[int],
        thread: Optional[int],
        assignment: Optional[bool],
        attribute_list: Any,
        attribute_storage: Any,
        job_handle_array: Any,
    ) -> _WindowsJobSession:
        session = _WindowsJobSession(
            _CUSTODIAN,
            kernel32,
            job,
            process,
            thread,
            assignment_observed=assignment,
            attribute_list=attribute_list,
            attribute_storage=attribute_storage,
            job_handle_array=job_handle_array,
        )
        _CUSTODIAN.register_session(session)
        return session

    def retain_controls(self, session: Any) -> Optional[str]:
        if not isinstance(session, _WindowsJobSession):
            return None
        if session._custodian is not _CUSTODIAN:
            return None
        return _CUSTODIAN.retain_session(session)

    def resolve_retained_controls(
        self, token: str, *, timeout_seconds: float = 5.0
    ) -> RetainedControlResolution:
        if (
            type(token) is not str
            or not token
            or type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or not 0.0 <= float(timeout_seconds) <= _MAX_RECONCILE_SECONDS
        ):
            raise ValueError("retained_control_resolution_invalid")
        return _CUSTODIAN.resolve(token, timeout_seconds=float(timeout_seconds))

    def retained_tokens(self) -> Tuple[str, ...]:
        """Return opaque tokens for explicitly escrowed controls on this host."""

        return _CUSTODIAN.retained_tokens()


__all__ = [
    "RetainedControlResolution",
    "WindowsJobBackend",
    "WindowsJobBackendError",
]
