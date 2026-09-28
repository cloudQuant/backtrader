"""Narrow Windows process-tree supervision for read-only diagnostic children.

This module is an execution-containment prerequisite only. It does not perform
CTP admission, accept a preflight, load credentials, or grant provider or write
capabilities. Callers must pass a fixed command constructed by their own
code, an explicit environment, and a pure parser that projects stdout into a
value-free receipt. Raw child output is never returned or persisted.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence


_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_STARTF_USESHOWWINDOW = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_INFINITE = 0xFFFFFFFF
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_VALUE_FREE_TOKEN = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
_PROCESS_CONTAINMENT_LATCH: Optional[str] = None


class SupervisorError(RuntimeError):
    """Base exception for invalid supervisor inputs."""


class _ChildCreationError(OSError):
    def __init__(
        self,
        reason: str,
        *,
        process_created: bool,
        job_assigned: bool,
        process_exit_observed: Optional[bool],
        process_handle: Optional[int] = None,
        thread_handle: Optional[int] = None,
        job_termination_requested: bool = False,
        job_termination_call_succeeded: Optional[bool] = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.process_created = process_created
        self.job_assigned = job_assigned
        self.process_exit_observed = process_exit_observed
        self.process_handle = process_handle
        self.thread_handle = thread_handle
        self.job_termination_requested = job_termination_requested
        self.job_termination_call_succeeded = job_termination_call_succeeded


class _SupervisorDeadlineExceeded(RuntimeError):
    """The optional absolute budget expired before a child was created."""


def _deadline_expired(deadline_monotonic: Optional[float]) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic


def _remaining_seconds(deadline_monotonic: Optional[float]) -> Optional[float]:
    if deadline_monotonic is None:
        return None
    return max(0.0, deadline_monotonic - time.monotonic())


def _bounded_timeout_ms(timeout_ms: int, deadline_monotonic: Optional[float]) -> int:
    remaining = _remaining_seconds(deadline_monotonic)
    if remaining is None:
        return timeout_ms
    return min(timeout_ms, max(0, int(remaining * 1000)))


def _bounded_timeout_seconds(
    timeout_seconds: float, deadline_monotonic: Optional[float]
) -> float:
    remaining = _remaining_seconds(deadline_monotonic)
    if remaining is None:
        return timeout_seconds
    return min(timeout_seconds, remaining)


def _deadline_reason(
    relative_deadline: float, absolute_deadline: Optional[float]
) -> str:
    if absolute_deadline is not None and absolute_deadline <= relative_deadline:
        return "supervisor_deadline_exceeded"
    return "child_deadline_exceeded"


def _raise_if_setup_deadline_expired(
    deadline_monotonic: Optional[float],
    *,
    process_created: bool = False,
    job_assigned: bool = False,
) -> None:
    if _deadline_expired(deadline_monotonic):
        raise _ChildCreationError(
            "supervisor_deadline_exceeded",
            process_created=process_created,
            job_assigned=job_assigned,
            process_exit_observed=None,
        )


class FailClosedLatch(Protocol):
    """Caller-owned latch that persists a no-retry state across process restarts.

    ``trip`` must be idempotent, durable, and return true only after the
    no-retry state is committed. The supervisor also keeps a process-local
    latch, but that alone is not a cross-process recovery contract.
    """

    def is_tripped(self) -> bool:
        """Return whether a prior containment uncertainty blocks new launches."""

    def trip(self, reason: str) -> bool:
        """Durably latch ``reason`` and confirm the commit."""


@dataclass(frozen=True)
class ValueFreeReceiptSchema:
    """Exact output fields and allowed categorical values for one child receipt."""

    enum_fields: Mapping[str, Sequence[str]]
    bool_fields: Sequence[str]
    nullable_enum_fields: Mapping[str, Sequence[str]]
    nullable_bool_fields: Sequence[str] = ()

    def __post_init__(self) -> None:
        enum_fields = _copy_enum_fields(self.enum_fields)
        nullable_enum_fields = _copy_enum_fields(self.nullable_enum_fields)
        bool_fields = tuple(self.bool_fields)
        nullable_bool_fields = tuple(self.nullable_bool_fields)
        names = (
            set(enum_fields)
            | set(nullable_enum_fields)
            | set(bool_fields)
            | set(nullable_bool_fields)
        )
        if (
            len(names)
            != len(enum_fields)
            + len(nullable_enum_fields)
            + len(bool_fields)
            + len(nullable_bool_fields)
            or not 1 <= len(names) <= 64
            or "native_join_pending" not in set(bool_fields) | set(nullable_bool_fields)
        ):
            raise ValueError("receipt_schema_invalid")
        if any(type(name) is not str or not _VALUE_FREE_TOKEN.fullmatch(name) for name in names):
            raise ValueError("receipt_schema_invalid")
        if any(
            type(name) is not str or not _VALUE_FREE_TOKEN.fullmatch(name) for name in bool_fields
        ):
            raise ValueError("receipt_schema_invalid")
        if any(
            type(name) is not str or not _VALUE_FREE_TOKEN.fullmatch(name)
            for name in nullable_bool_fields
        ):
            raise ValueError("receipt_schema_invalid")
        object.__setattr__(self, "enum_fields", MappingProxyType(enum_fields))
        object.__setattr__(self, "nullable_enum_fields", MappingProxyType(nullable_enum_fields))
        object.__setattr__(self, "bool_fields", bool_fields)
        object.__setattr__(self, "nullable_bool_fields", nullable_bool_fields)


def _copy_enum_fields(fields: Mapping[str, Sequence[str]]) -> dict[str, frozenset[str]]:
    if not isinstance(fields, Mapping):
        raise ValueError("receipt_schema_invalid")
    copied: dict[str, frozenset[str]] = {}
    for name, values in fields.items():
        if type(name) is not str or not _VALUE_FREE_TOKEN.fullmatch(name):
            raise ValueError("receipt_schema_invalid")
        if isinstance(values, (str, bytes)):
            raise ValueError("receipt_schema_invalid")
        try:
            allowed = frozenset(values)
        except TypeError as exc:
            raise ValueError("receipt_schema_invalid") from exc
        if not allowed or any(
            type(value) is not str or not _VALUE_FREE_TOKEN.fullmatch(value) for value in allowed
        ):
            raise ValueError("receipt_schema_invalid")
        copied[name] = allowed
    return copied


@dataclass(frozen=True)
class FixedChildCommand:
    """An explicit command snapshot; do not populate this from CLI/user input."""

    argv: Sequence[str]
    cwd: Path | str
    env: Mapping[str, str]
    job_handle_env_name: Optional[str] = None

    def __post_init__(self) -> None:
        argv = tuple(self.argv)
        if (
            not argv
            or any(type(arg) is not str or not arg or "\0" in arg for arg in argv)
            or not Path(argv[0]).is_absolute()
        ):
            raise ValueError("child_command_invalid")
        cwd = Path(self.cwd)
        if not cwd.is_absolute():
            raise ValueError("child_cwd_must_be_absolute")
        if not isinstance(self.env, Mapping):
            raise ValueError("child_environment_invalid")
        copied: dict[str, str] = {}
        seen: set[str] = set()
        for key, value in self.env.items():
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or "=" in key
                or "\0" in key
                or "\0" in value
            ):
                raise ValueError("child_environment_invalid")
            folded = key.upper()
            if folded in seen:
                raise ValueError("child_environment_duplicate_key")
            seen.add(folded)
            copied[key] = value
        handle_env_name = self.job_handle_env_name
        if handle_env_name is not None and (
            type(handle_env_name) is not str
            or not _VALUE_FREE_TOKEN.fullmatch(handle_env_name)
            or handle_env_name.upper() in seen
        ):
            raise ValueError("child_job_handle_environment_invalid")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "env", MappingProxyType(copied))


@dataclass(frozen=True)
class ProcessEvidence:
    """Parent-observed operating-system facts, separate from the SDK receipt."""

    process_created: bool
    job_assignment_observed: bool
    process_resumed: bool
    process_exit_observed: Optional[bool]
    process_exit_code: Optional[int]
    job_termination_requested: bool
    job_termination_call_succeeded: Optional[bool]
    job_empty_observed: Optional[bool]
    containment: str


@dataclass(frozen=True)
class SupervisedResult:
    """Outcome metadata and two deliberately separate evidence channels."""

    status: str
    reason: str
    sdk_receipt: Optional[Mapping[str, object]]
    process_evidence: ProcessEvidence
    retained_control: Optional["RetainedJobControl"] = None


@dataclass
class RetainedJobControl:
    """Live Windows handles retained after uncertain cleanup for explicit retry."""

    _kernel32: Any
    _job_handle: Optional[int]
    _process_handle: Optional[int]
    _thread_handle: Optional[int]
    _job_assigned: bool
    _process_resumed: bool

    def resolve(self, timeout_seconds: float = 5.0) -> ProcessEvidence:
        """Retry termination and close handles only after OS exit/Job-empty evidence."""

        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or not 0.1 <= float(timeout_seconds) <= 30
        ):
            raise ValueError("termination_grace_out_of_range")
        call_succeeded: Optional[bool] = None
        requested = self._job_handle is not None or self._process_handle is not None
        if self._job_assigned and self._job_handle is not None:
            call_succeeded = bool(self._kernel32.TerminateJobObject(self._job_handle, 0xEE2D))
        elif self._process_handle is not None:
            call_succeeded = bool(self._kernel32.TerminateProcess(self._process_handle, 0xEE2D))

        process_exit: Optional[bool] = None
        process_exit_code: Optional[int] = None
        if self._process_handle is not None:
            process_exit, process_exit_code = _wait_for_process_exit(
                self._kernel32,
                self._process_handle,
                int(float(timeout_seconds) * 1000),
            )

        job_empty: Optional[bool] = None
        if self._job_handle is not None:
            job_empty = _wait_for_job_empty(
                self._kernel32, self._job_handle, float(timeout_seconds)
            )
        if job_empty is True and process_exit is not True and self._process_handle is not None:
            process_exit, process_exit_code = _wait_for_process_exit(
                self._kernel32,
                self._process_handle,
                int(float(timeout_seconds) * 1000),
            )
        safe_to_release = (
            process_exit is True
            and (job_empty is True or (not self._job_assigned and job_empty in (None, True)))
            and call_succeeded is True
        )
        if safe_to_release:
            if self._thread_handle is not None:
                self._kernel32.CloseHandle(self._thread_handle)
                self._thread_handle = None
            if self._process_handle is not None:
                self._kernel32.CloseHandle(self._process_handle)
                self._process_handle = None
            if self._job_handle is not None:
                self._kernel32.CloseHandle(self._job_handle)
                self._job_handle = None
        return ProcessEvidence(
            process_created=True,
            job_assignment_observed=self._job_assigned,
            process_resumed=self._process_resumed,
            process_exit_observed=process_exit,
            process_exit_code=process_exit_code,
            job_termination_requested=requested,
            job_termination_call_succeeded=call_succeeded,
            job_empty_observed=job_empty,
            containment="verified" if safe_to_release else "uncertain",
        )


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


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


@dataclass
class _CapturedOutput:
    limit: int
    data: bytearray
    overflow: bool = False
    read_error: bool = False
    total: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def drain(self, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                with self.lock:
                    self.total += len(chunk)
                    remaining = self.limit - len(self.data)
                    if remaining > 0:
                        self.data.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        self.overflow = True
        except Exception:
            self.read_error = True
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def snapshot(self) -> tuple[bytes, bool, bool]:
        with self.lock:
            return bytes(self.data), self.overflow, self.read_error


def _winapi() -> Any:
    if os.name != "nt":
        raise OSError("windows_required")
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
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
    ]
    kernel32.CreatePipe.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
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
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    return kernel32


def _create_job(kernel32: Any) -> int:
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError("job_create_failed")
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        kernel32.CloseHandle(job)
        raise OSError("job_kill_on_close_setup_failed")
    return int(job)


def _environment_block(env: Mapping[str, str]) -> Any:
    pairs = sorted(env.items(), key=lambda item: item[0].upper())
    block = "\0".join(f"{key}={value}" for key, value in pairs) + "\0\0"
    return ctypes.create_unicode_buffer(block)


def _new_pipe(kernel32: Any) -> tuple[int, int]:
    attributes = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    if not kernel32.CreatePipe(
        ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(attributes), 0
    ):
        raise OSError("stdout_pipe_create_failed")
    if not kernel32.SetHandleInformation(read_handle, 0x00000001, 0):
        kernel32.CloseHandle(read_handle)
        kernel32.CloseHandle(write_handle)
        raise OSError("stdout_pipe_inherit_setup_failed")
    return int(read_handle.value), int(write_handle.value)


def _create_suspended_process(
    kernel32: Any,
    command: FixedChildCommand,
    job: int,
    *,
    deadline_monotonic: Optional[float] = None,
) -> tuple[int, int, Any]:
    """Create suspended inside the Job atomically and return only if contained.

    PROC_THREAD_ATTRIBUTE_JOB_LIST is required here. A post-CreateProcess
    AssignProcessToJobObject call leaves a failure window in which rollback
    itself can fail and strand an uncontained child. Windows 10 and newer
    assign the child as part of process creation; unsupported systems reject
    before a child is created.
    """

    owned_handles: set[int] = set()
    process_info = _PROCESS_INFORMATION()
    attribute_list: Any = None
    process_created = False
    process_assigned = False
    process_confirmed_dead = False
    try:
        _raise_if_setup_deadline_expired(deadline_monotonic)
        stdout_read, stdout_write = _new_pipe(kernel32)
        owned_handles.update((stdout_read, stdout_write))
        _raise_if_setup_deadline_expired(deadline_monotonic)
        attributes = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
        null_stdin = kernel32.CreateFileW(
            "NUL", 0x80000000, 0x00000003, ctypes.byref(attributes), 3, 0x00000080, None
        )
        if not null_stdin or null_stdin == _INVALID_HANDLE_VALUE:
            raise OSError("stdin_handle_create_failed")
        owned_handles.add(int(null_stdin))
        _raise_if_setup_deadline_expired(deadline_monotonic)

        startup_ex = _STARTUPINFOEXW()
        startup = startup_ex.StartupInfo
        startup.cb = ctypes.sizeof(startup_ex)
        startup.dwFlags = _STARTF_USESTDHANDLES | _STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.hStdInput = null_stdin
        startup.hStdOutput = stdout_write
        startup.hStdError = null_stdin
        attribute_count = 2
        if command.job_handle_env_name is not None:
            if not kernel32.SetHandleInformation(job, 0x00000001, 0x00000001):
                raise OSError("startup_job_handle_inherit_failed")
            attribute_count += 1
        required_size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(
            None, attribute_count, 0, ctypes.byref(required_size)
        )
        _raise_if_setup_deadline_expired(deadline_monotonic)
        if not required_size.value:
            raise OSError("startup_attribute_size_unavailable")
        attribute_buffer = ctypes.create_string_buffer(required_size.value)
        attribute_list = ctypes.cast(attribute_buffer, wintypes.LPVOID)
        if not kernel32.InitializeProcThreadAttributeList(
            attribute_list, attribute_count, 0, ctypes.byref(required_size)
        ):
            attribute_list = None
            raise OSError("startup_attribute_list_init_failed")
        startup_ex.lpAttributeList = attribute_list
        _raise_if_setup_deadline_expired(deadline_monotonic)
        inherit_handles = (
            (wintypes.HANDLE * 3)(null_stdin, stdout_write, job)
            if command.job_handle_env_name is not None
            else (wintypes.HANDLE * 2)(null_stdin, stdout_write)
        )
        if not kernel32.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(inherit_handles, wintypes.LPVOID),
            ctypes.sizeof(inherit_handles),
            None,
            None,
        ):
            raise OSError("startup_handle_list_failed")
        _raise_if_setup_deadline_expired(deadline_monotonic)
        job_handles = (wintypes.HANDLE * 1)(job)
        if not kernel32.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_JOB_LIST,
            ctypes.cast(job_handles, wintypes.LPVOID),
            ctypes.sizeof(job_handles),
            None,
            None,
        ):
            raise OSError("startup_job_list_failed")
        _raise_if_setup_deadline_expired(deadline_monotonic)

        command_line_text = subprocess.list2cmdline(list(command.argv))
        if len(command_line_text) >= 32767:
            raise OSError("child_command_too_long")
        command_line = ctypes.create_unicode_buffer(command_line_text)
        child_environment = dict(command.env)
        if command.job_handle_env_name is not None:
            child_environment[command.job_handle_env_name] = str(job)
        env_block = _environment_block(child_environment)
        _raise_if_setup_deadline_expired(deadline_monotonic)
        flags = (
            _CREATE_SUSPENDED
            | _CREATE_UNICODE_ENVIRONMENT
            | _EXTENDED_STARTUPINFO_PRESENT
            | _CREATE_NO_WINDOW
        )
        created = kernel32.CreateProcessW(
            command.argv[0],
            command_line,
            None,
            None,
            True,
            flags,
            env_block,
            str(command.cwd),
            ctypes.cast(ctypes.byref(startup_ex), ctypes.POINTER(_STARTUPINFOW)),
            ctypes.byref(process_info),
        )
        if attribute_list is not None:
            kernel32.DeleteProcThreadAttributeList(attribute_list)
            attribute_list = None
        if not created:
            raise OSError("child_process_create_failed")
        process_created = True
        _raise_if_setup_deadline_expired(
            deadline_monotonic, process_created=True, job_assigned=False
        )
        if _job_active_processes(kernel32, job) != 1:
            # Keep the process suspended until independent Job accounting
            # confirms containment. This is defense in depth around the
            # atomic JOB_LIST startup attribute.
            kernel32.TerminateProcess(process_info.hProcess, 0xEE10)
            process_confirmed_dead = (
                kernel32.WaitForSingleObject(
                    process_info.hProcess, _bounded_timeout_ms(5000, deadline_monotonic)
                )
                == _WAIT_OBJECT_0
            )
            raise _ChildCreationError(
                "job_assignment_unobserved",
                process_created=True,
                job_assigned=False,
                process_exit_observed=process_confirmed_dead,
            )
        # Successful CreateProcessW with JOB_LIST means the suspended process
        # entered this Job atomically. There is deliberately no assignment
        # fallback that could create an uncontained process.
        process_assigned = True
        _raise_if_setup_deadline_expired(
            deadline_monotonic, process_created=True, job_assigned=True
        )

        for handle in (stdout_write, int(null_stdin)):
            if not kernel32.CloseHandle(handle):
                job_terminated = bool(kernel32.TerminateJobObject(job, 0xEE13))
                dead = (
                    kernel32.WaitForSingleObject(
                        process_info.hProcess, _bounded_timeout_ms(5000, deadline_monotonic)
                    )
                    == _WAIT_OBJECT_0
                )
                raise _ChildCreationError(
                    "child_pipe_handle_close_failed",
                    process_created=True,
                    job_assigned=True,
                    process_exit_observed=dead,
                    job_termination_requested=True,
                    job_termination_call_succeeded=job_terminated,
                )
            owned_handles.discard(handle)
            _raise_if_setup_deadline_expired(
                deadline_monotonic, process_created=True, job_assigned=True
            )
        owned_handles.discard(stdout_read)
        _raise_if_setup_deadline_expired(
            deadline_monotonic, process_created=True, job_assigned=True
        )
        return int(process_info.hProcess), int(process_info.hThread), stdout_read
    except BaseException as error:
        if process_info.hProcess and not process_assigned and not process_confirmed_dead:
            # Any exception after CreateProcess must leave no runnable uncontained child.
            kernel32.TerminateProcess(process_info.hProcess, 0xEE12)
            process_confirmed_dead = (
                kernel32.WaitForSingleObject(
                    process_info.hProcess, _bounded_timeout_ms(5000, deadline_monotonic)
                )
                == _WAIT_OBJECT_0
            )
        if process_created and not isinstance(error, _ChildCreationError):
            error = _ChildCreationError(
                "suspended_child_setup_failed",
                process_created=True,
                job_assigned=process_assigned,
                process_exit_observed=(process_confirmed_dead if not process_assigned else None),
            )
        if (
            process_info.hProcess
            and not process_confirmed_dead
            and isinstance(error, _ChildCreationError)
        ):
            error.process_handle = int(process_info.hProcess)
            error.thread_handle = int(process_info.hThread) if process_info.hThread else None
        for handle in tuple(owned_handles):
            kernel32.CloseHandle(handle)
        if attribute_list is not None:
            kernel32.DeleteProcThreadAttributeList(attribute_list)
        if process_info.hThread and (not process_info.hProcess or process_confirmed_dead):
            kernel32.CloseHandle(process_info.hThread)
        if process_info.hProcess and process_confirmed_dead:
            kernel32.CloseHandle(process_info.hProcess)
        if error is not None:
            raise error
        raise


def _handle_to_stream(handle: int) -> Any:
    import msvcrt

    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(fd, "rb", buffering=0)


def _job_active_processes(kernel32: Any, job: int) -> Optional[int]:
    information = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    if not kernel32.QueryInformationJobObject(
        job,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(information),
        ctypes.sizeof(information),
        None,
    ):
        return None
    return int(information.ActiveProcesses)


def _wait_for_job_empty(
    kernel32: Any,
    job: int,
    timeout_seconds: float,
    *,
    deadline_monotonic: Optional[float] = None,
) -> Optional[bool]:
    local_deadline = time.monotonic() + timeout_seconds
    if deadline_monotonic is not None:
        local_deadline = min(local_deadline, deadline_monotonic)
    while True:
        if deadline_monotonic is not None and time.monotonic() >= local_deadline:
            return False
        active = _job_active_processes(kernel32, job)
        if active == 0:
            return True
        if active is None:
            return None
        if time.monotonic() >= local_deadline:
            return False
        time.sleep(min(0.025, max(0.0, local_deadline - time.monotonic())))


def _wait_for_process_exit(
    kernel32: Any,
    process: int,
    timeout_ms: int,
    *,
    deadline_monotonic: Optional[float] = None,
) -> tuple[Optional[bool], Optional[int]]:
    """Observe actual process signaling, optionally retrying after Job-empty."""

    wait_result = kernel32.WaitForSingleObject(
        process, _bounded_timeout_ms(timeout_ms, deadline_monotonic)
    )
    if wait_result == _WAIT_OBJECT_0:
        exit_code = wintypes.DWORD()
        code = (
            int(exit_code.value)
            if kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code))
            else None
        )
        return True, code
    if wait_result == _WAIT_TIMEOUT:
        return False, None
    return None, None


def _wait_for_job_empty_with_budget(
    kernel32: Any,
    job: int,
    timeout_seconds: float,
    deadline_monotonic: Optional[float],
) -> Optional[bool]:
    if deadline_monotonic is None:
        return _wait_for_job_empty(kernel32, job, timeout_seconds)
    return _wait_for_job_empty(
        kernel32, job, timeout_seconds, deadline_monotonic=deadline_monotonic
    )


def _wait_for_process_exit_with_budget(
    kernel32: Any,
    process: int,
    timeout_ms: int,
    deadline_monotonic: Optional[float],
) -> tuple[Optional[bool], Optional[int]]:
    if deadline_monotonic is None:
        return _wait_for_process_exit(kernel32, process, timeout_ms)
    return _wait_for_process_exit(
        kernel32, process, timeout_ms, deadline_monotonic=deadline_monotonic
    )


def _validated_receipt(
    value: object, schema: ValueFreeReceiptSchema
) -> Optional[dict[str, object]]:
    """Apply the caller-owned exact field and enum allowlist at the boundary."""

    expected = (
        set(schema.bool_fields)
        | set(schema.enum_fields)
        | set(schema.nullable_enum_fields)
        | set(schema.nullable_bool_fields)
    )
    if type(value) is not dict or set(value) != expected:
        return None
    result: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str or not _VALUE_FREE_TOKEN.fullmatch(key):
            return None
        if key in schema.bool_fields:
            if type(item) is not bool:
                return None
        elif key in schema.nullable_bool_fields:
            if item is not None and type(item) is not bool:
                return None
        elif key in schema.enum_fields:
            if type(item) is not str or item not in schema.enum_fields[key]:
                return None
        elif key in schema.nullable_enum_fields:
            if item is not None and (
                type(item) is not str or item not in schema.nullable_enum_fields[key]
            ):
                return None
        else:
            return None
        result[key] = item
    return result


class _DuplicateJsonKey(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey("duplicate_json_key")
        result[key] = value
    return result


def _decode_single_json_object(raw: bytes) -> tuple[str, Optional[dict[str, object]]]:
    """Return incomplete/invalid/complete without allowing duplicate JSON keys."""

    try:
        text = raw.decode("utf-8", errors="strict")
        if not text.endswith("\n"):
            return "incomplete", None
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) != 1:
            return "invalid", None
        value = json.loads(lines[0], object_pairs_hook=_unique_json_object)
    except (UnicodeError, ValueError, TypeError):
        return "invalid", None
    if type(value) is not dict:
        return "invalid", None
    return "complete", value


def parse_single_json_receipt(
    raw: bytes, schema: ValueFreeReceiptSchema
) -> Optional[Mapping[str, object]]:
    """Parse one duplicate-free JSON object line and enforce its exact schema."""

    state, value = _decode_single_json_object(raw)
    if state != "complete" or value is None:
        return None
    return _validated_receipt(value, schema)


def _safe_parse(
    parser: Callable[[bytes], Optional[Mapping[str, object]]],
    raw: bytes,
    schema: ValueFreeReceiptSchema,
) -> tuple[Optional[dict[str, object]], bool]:
    state, _decoded = _decode_single_json_object(raw)
    if state == "incomplete":
        return None, False
    if state != "complete":
        return None, True
    try:
        return _validated_receipt(parser(raw), schema), False
    except Exception:
        return None, True


def _evidence(
    *,
    created: bool = False,
    assigned: bool = False,
    resumed: bool = False,
    process_exit_observed: Optional[bool] = None,
    process_exit_code: Optional[int] = None,
    job_termination_requested: bool = False,
    job_termination_call_succeeded: Optional[bool] = None,
    job_empty_observed: Optional[bool] = None,
    containment: str = "not_started",
) -> ProcessEvidence:
    return ProcessEvidence(
        process_created=created,
        job_assignment_observed=assigned,
        process_resumed=resumed,
        process_exit_observed=process_exit_observed,
        process_exit_code=process_exit_code,
        job_termination_requested=job_termination_requested,
        job_termination_call_succeeded=job_termination_call_succeeded,
        job_empty_observed=job_empty_observed,
        containment=containment,
    )


def _trip_fail_closed_latch(latch: FailClosedLatch, reason: str) -> bool:
    global _PROCESS_CONTAINMENT_LATCH
    _PROCESS_CONTAINMENT_LATCH = reason
    try:
        return latch.trip(reason) is True
    except Exception:
        return False


def run_readonly_child(
    command: FixedChildCommand,
    result_parser: Callable[[bytes], Optional[Mapping[str, object]]],
    *,
    receipt_schema: ValueFreeReceiptSchema,
    fail_closed_latch: FailClosedLatch,
    deadline_seconds: float,
    deadline_monotonic: Optional[float] = None,
    max_stdout_bytes: int = 64 * 1024,
    termination_grace_seconds: float = 5.0,
) -> SupervisedResult:
    """Run a fixed read-only child inside a kill-on-close Windows Job Object.

    ``result_parser`` must be pure and safe to call on growing stdout prefixes;
    return ``None`` until a complete, value-free receipt is available. The
    required exact ``receipt_schema`` validates every accepted field and enum.
    ``fail_closed_latch`` must durably block a retry after containment uncertainty.
    A receipt with ``native_join_pending=True`` immediately terminates the Job.
    The parser's output is shape-checked and retained separately from parent OS
    observations. This result is not a preflight or session-acceptance decision.

    ``deadline_monotonic``, when supplied, is an absolute cutoff in the same
    clock domain as ``time.monotonic()``. It adds an outer budget that includes
    latch checks, setup, child observation, and bounded cleanup waits; the
    earlier of that cutoff and ``deadline_seconds`` wins. The supervisor checks
    the budget between operations and caps wait/join timeouts by its remaining
    time. It cannot interrupt a synchronous Windows API or Python call that is
    already running (including process creation, termination, handle cleanup,
    latch callbacks, and result parsing), and scheduler delays can extend the
    observed return time. This is not a hard whole-call time bound.
    """

    if not isinstance(command, FixedChildCommand):
        raise TypeError("fixed_child_command_required")
    if not callable(result_parser):
        raise TypeError("result_parser_required")
    if not isinstance(receipt_schema, ValueFreeReceiptSchema):
        raise TypeError("value_free_receipt_schema_required")
    if not callable(getattr(fail_closed_latch, "is_tripped", None)) or not callable(
        getattr(fail_closed_latch, "trip", None)
    ):
        raise TypeError("fail_closed_latch_required")
    if (
        type(deadline_seconds) not in (int, float)
        or not math.isfinite(float(deadline_seconds))
        or not 0 < float(deadline_seconds) <= 3600
    ):
        raise ValueError("deadline_out_of_range")
    if deadline_monotonic is not None and (
        type(deadline_monotonic) not in (int, float)
        or not math.isfinite(float(deadline_monotonic))
    ):
        raise ValueError("deadline_monotonic_invalid")
    absolute_deadline = (
        None if deadline_monotonic is None else float(deadline_monotonic)
    )
    if type(max_stdout_bytes) is not int or not 1 <= max_stdout_bytes <= 1024 * 1024:
        raise ValueError("stdout_bound_out_of_range")
    if (
        type(termination_grace_seconds) not in (int, float)
        or not math.isfinite(float(termination_grace_seconds))
        or not 0.1 <= float(termination_grace_seconds) <= 30
    ):
        raise ValueError("termination_grace_out_of_range")
    global _PROCESS_CONTAINMENT_LATCH
    if _PROCESS_CONTAINMENT_LATCH is not None:
        return SupervisedResult(
            "latched",
            "prior_containment_uncertainty",
            None,
            _evidence(containment="latched"),
        )
    if _deadline_expired(absolute_deadline):
        return SupervisedResult(
            "timed_out",
            "supervisor_deadline_exceeded",
            None,
            _evidence(containment="not_started"),
        )
    try:
        external_latch = fail_closed_latch.is_tripped()
        if type(external_latch) is not bool:
            raise TypeError("containment_latch_state_invalid")
        if external_latch:
            return SupervisedResult(
                "latched",
                "prior_containment_uncertainty",
                None,
                _evidence(containment="latched"),
            )
    except Exception:
        return SupervisedResult(
            "supervisor_error",
            "containment_latch_unavailable",
            None,
            _evidence(containment="unavailable"),
        )
    if _deadline_expired(absolute_deadline):
        return SupervisedResult(
            "timed_out",
            "supervisor_deadline_exceeded",
            None,
            _evidence(containment="not_started"),
        )
    if os.name != "nt":
        return SupervisedResult(
            "supervisor_error",
            "windows_required",
            None,
            _evidence(containment="unavailable"),
        )

    kernel32: Any = None
    job: Optional[int] = None
    process: Optional[int] = None
    thread: Optional[int] = None
    stream: Any = None
    reader: Optional[threading.Thread] = None
    capture = _CapturedOutput(max_stdout_bytes, bytearray())
    receipt: Optional[dict[str, object]] = None
    parse_failed = False
    status = "supervisor_error"
    reason = "supervisor_setup_failed"
    created = False
    assigned = False
    resumed = False
    process_exit_observed: Optional[bool] = None
    process_exit_code: Optional[int] = None
    job_termination_requested = False
    job_termination_call_succeeded: Optional[bool] = None
    job_empty_observed: Optional[bool] = None
    containment = "uncertain"
    latch_trip_succeeded: Optional[bool] = None
    retained_control: Optional[RetainedJobControl] = None
    started = time.monotonic()
    relative_deadline = started + float(deadline_seconds)
    deadline = (
        relative_deadline
        if absolute_deadline is None
        else min(relative_deadline, absolute_deadline)
    )
    budget_deadline = deadline if absolute_deadline is not None else None
    terminate_after_loop = False
    terminate_code = 0xEE20
    receipt_length: Optional[int] = None
    try:
        if _deadline_expired(budget_deadline):
            raise _SupervisorDeadlineExceeded("supervisor_deadline_exceeded")
        kernel32 = _winapi()
        if _deadline_expired(budget_deadline):
            raise _SupervisorDeadlineExceeded("supervisor_deadline_exceeded")
        job = _create_job(kernel32)
        if _deadline_expired(budget_deadline):
            raise _SupervisorDeadlineExceeded("supervisor_deadline_exceeded")
        if budget_deadline is None:
            process, thread, stdout_handle = _create_suspended_process(kernel32, command, job)
        else:
            process, thread, stdout_handle = _create_suspended_process(
                kernel32,
                command,
                job,
                deadline_monotonic=budget_deadline,
            )
        created = True
        assigned = True
        if _deadline_expired(budget_deadline):
            raise _ChildCreationError(
                "supervisor_deadline_exceeded",
                process_created=True,
                job_assigned=True,
                process_exit_observed=None,
                process_handle=process,
                thread_handle=thread,
            )
        stream = _handle_to_stream(stdout_handle)
        if _deadline_expired(budget_deadline):
            raise _ChildCreationError(
                "supervisor_deadline_exceeded",
                process_created=True,
                job_assigned=True,
                process_exit_observed=None,
                process_handle=process,
                thread_handle=thread,
            )
        reader = threading.Thread(target=capture.drain, args=(stream,), daemon=True)
        reader.start()
        if _deadline_expired(budget_deadline):
            raise _ChildCreationError(
                "supervisor_deadline_exceeded",
                process_created=True,
                job_assigned=True,
                process_exit_observed=None,
                process_handle=process,
                thread_handle=thread,
            )
        if _deadline_expired(budget_deadline):
            status, reason = "timed_out", _deadline_reason(relative_deadline, absolute_deadline)
            terminate_after_loop = True
            terminate_code = 0xEE27
        else:
            resume_result = kernel32.ResumeThread(thread)
            if resume_result == 1:
                resumed = True
                kernel32.CloseHandle(thread)
                thread = None
            if _deadline_expired(budget_deadline):
                status, reason = "timed_out", _deadline_reason(
                    relative_deadline, absolute_deadline
                )
                terminate_after_loop = True
                terminate_code = 0xEE27
            elif resume_result != 1:
                status, reason = "containment_error", "child_resume_failed"
                terminate_after_loop = True
                terminate_code = 0xEE21
            else:
                status, reason = "running", "child_running"
                parsed_length = -1
                while True:
                    raw, overflow, read_error = capture.snapshot()
                    if overflow:
                        status, reason = "invalid_output", "stdout_limit_exceeded"
                        terminate_after_loop = True
                        terminate_code = 0xEE22
                        break
                    if read_error:
                        status, reason = "supervisor_error", "stdout_read_failed"
                        terminate_after_loop = True
                        terminate_code = 0xEE23
                        break
                    if len(raw) != parsed_length:
                        parsed_length = len(raw)
                        if receipt is not None:
                            status, reason = "invalid_output", "stdout_changed_after_receipt"
                            terminate_after_loop = True
                            terminate_code = 0xEE2C
                            break
                        parsed, parser_failed = _safe_parse(result_parser, raw, receipt_schema)
                        if parser_failed:
                            status, reason = "invalid_output", "result_parser_failed"
                            parse_failed = True
                            terminate_after_loop = True
                            terminate_code = 0xEE24
                            break
                        if parsed is not None:
                            receipt = parsed
                            receipt_length = len(raw)
                            if receipt["native_join_pending"] is True:
                                status, reason = "pending_native_join", "native_join_pending"
                                terminate_after_loop = True
                                terminate_code = 0xEE25
                                break
                    wait_result = kernel32.WaitForSingleObject(process, 0)
                    if wait_result == _WAIT_OBJECT_0:
                        process_exit_observed = True
                        exit_code = wintypes.DWORD()
                        if kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                            process_exit_code = int(exit_code.value)
                        else:
                            status, reason = "supervisor_error", "process_exit_code_unavailable"
                        if status == "running":
                            status, reason = "child_exited", "child_process_exited"
                        break
                    if wait_result != _WAIT_TIMEOUT:
                        status, reason = "supervisor_error", "process_wait_failed"
                        terminate_after_loop = True
                        terminate_code = 0xEE26
                        break
                    if time.monotonic() >= deadline:
                        status, reason = "timed_out", _deadline_reason(
                            relative_deadline, absolute_deadline
                        )
                        terminate_after_loop = True
                        terminate_code = 0xEE27
                        break
                    sleep_seconds = 0.02
                    if budget_deadline is not None:
                        sleep_seconds = _bounded_timeout_seconds(sleep_seconds, budget_deadline)
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)

        # Bound all remaining work, including descendants that retained stdout.
        if _deadline_expired(budget_deadline):
            status, reason = "timed_out", _deadline_reason(relative_deadline, absolute_deadline)
            terminate_after_loop = True
            terminate_code = 0xEE27
        if terminate_after_loop:
            job_termination_requested = True
            job_termination_call_succeeded = bool(kernel32.TerminateJobObject(job, terminate_code))
        else:
            # A signaled child can briefly remain counted in Job accounting.
            # Give the whole Job the existing bounded grace to become empty
            # naturally before treating remaining descendants as an error.
            job_empty_observed = _wait_for_job_empty_with_budget(
                kernel32, job, float(termination_grace_seconds), budget_deadline
            )
            if job_empty_observed is not True:
                job_termination_requested = True
                job_termination_call_succeeded = bool(
                    kernel32.TerminateJobObject(job, 0xEE28)
                )

        if job_termination_requested:
            if process_exit_observed is not True:
                process_exit_observed, process_exit_code = _wait_for_process_exit_with_budget(
                    kernel32,
                    process,
                    int(float(termination_grace_seconds) * 1000),
                    budget_deadline,
                )
            # After an explicit kill request, require a fresh bounded Job
            # accounting observation; natural-empty evidence is retained only
            # when no termination request was needed.
            job_empty_observed = _wait_for_job_empty_with_budget(
                kernel32, job, float(termination_grace_seconds), budget_deadline
            )

        if reader is not None:
            reader_join_timeout = float(termination_grace_seconds)
            if budget_deadline is not None:
                reader_join_timeout = _bounded_timeout_seconds(
                    reader_join_timeout, budget_deadline
                )
            reader.join(timeout=reader_join_timeout)
        raw, overflow, read_error = capture.snapshot()
        if receipt is None and not parse_failed and not overflow and not read_error:
            final_receipt, parser_failed = _safe_parse(result_parser, raw, receipt_schema)
            if parser_failed:
                status, reason = "invalid_output", "result_parser_failed"
            elif final_receipt is not None:
                receipt = final_receipt
                receipt_length = len(raw)
                if receipt["native_join_pending"] is True:
                    status, reason = "pending_native_join", "native_join_pending"
        if (
            receipt is not None
            and receipt["native_join_pending"] is True
            and not job_termination_requested
        ):
            # The child may exit before the output reader exposes its final
            # receipt. Still issue an explicit whole-Job termination request.
            job_termination_requested = True
            job_termination_call_succeeded = bool(kernel32.TerminateJobObject(job, 0xEE25))
            job_empty_observed = _wait_for_job_empty_with_budget(
                kernel32, job, float(termination_grace_seconds), budget_deadline
            )
        if job_empty_observed is True and process_exit_observed is not True:
            process_exit_observed, process_exit_code = _wait_for_process_exit_with_budget(
                kernel32,
                process,
                int(float(termination_grace_seconds) * 1000),
                budget_deadline,
            )
        if receipt is not None and receipt_length is not None and len(raw) > receipt_length:
            status, reason = "invalid_output", "stdout_changed_after_receipt"
            receipt = None
        if overflow:
            status, reason = "invalid_output", "stdout_limit_exceeded"
            receipt = None
        elif read_error or (reader is not None and reader.is_alive()):
            status, reason = "supervisor_error", "stdout_drain_unconfirmed"
        elif receipt is None and status in {"child_exited", "running"}:
            status, reason = "invalid_output", "result_receipt_unavailable"

        if (
            process_exit_observed is True
            and job_empty_observed is True
            and (not job_termination_requested or job_termination_call_succeeded is True)
        ):
            containment = "verified"
        else:
            containment = "uncertain"
            if status not in {"timed_out", "pending_native_join", "invalid_output"}:
                status, reason = "containment_error", "process_tree_containment_unverified"
        if created and containment != "verified":
            latch_trip_succeeded = _trip_fail_closed_latch(fail_closed_latch, reason)
            if not latch_trip_succeeded:
                status, reason = "supervisor_error", "containment_latch_trip_failed"
    except _SupervisorDeadlineExceeded:
        status, reason = "timed_out", "supervisor_deadline_exceeded"
        containment = "not_started"
    except _ChildCreationError as error:
        created = error.process_created
        assigned = error.job_assigned
        process_exit_observed = error.process_exit_observed
        job_termination_requested = error.job_termination_requested
        job_termination_call_succeeded = error.job_termination_call_succeeded
        deadline_error = error.reason == "supervisor_deadline_exceeded"
        status, reason = (
            ("timed_out", error.reason)
            if deadline_error
            else ("containment_error", error.reason)
        )
        if error.process_handle is not None:
            process = error.process_handle
            thread = error.thread_handle
            if assigned:
                job_termination_requested = True
                try:
                    job_termination_call_succeeded = bool(kernel32.TerminateJobObject(job, 0xEE2A))
                except Exception:
                    job_termination_call_succeeded = False
            else:
                try:
                    kernel32.TerminateProcess(process, 0xEE2B)
                except Exception:
                    pass
            try:
                process_exit_observed, process_exit_code = _wait_for_process_exit_with_budget(
                    kernel32,
                    process,
                    int(float(termination_grace_seconds) * 1000),
                    budget_deadline,
                )
            except Exception:
                process_exit_observed = None
        if job is not None and (created or not deadline_error):
            try:
                job_empty_observed = _wait_for_job_empty_with_budget(
                    kernel32, job, float(termination_grace_seconds), budget_deadline
                )
            except Exception:
                job_empty_observed = None
        if assigned and job_empty_observed is True and process_exit_observed is not True:
            try:
                process_exit_observed, process_exit_code = _wait_for_process_exit_with_budget(
                    kernel32,
                    process,
                    int(float(termination_grace_seconds) * 1000),
                    budget_deadline,
                )
            except Exception:
                process_exit_observed = None
        if not created and deadline_error:
            containment = "not_started"
        elif process_exit_observed is True:
            containment = (
                "verified"
                if assigned and job_empty_observed is True
                else "assignment_failed_child_terminated"
            )
        else:
            containment = "uncertain"
        if created and containment != "verified":
            latch_trip_succeeded = _trip_fail_closed_latch(fail_closed_latch, reason)
            if not latch_trip_succeeded:
                status, reason = "supervisor_error", "containment_latch_trip_failed"
    except Exception:
        status, reason = "supervisor_error", "supervisor_process_error"
        if kernel32 is not None and job is not None and process is not None:
            job_termination_requested = True
            try:
                job_termination_call_succeeded = bool(kernel32.TerminateJobObject(job, 0xEE29))
                if process is not None:
                    process_exit_observed, process_exit_code = _wait_for_process_exit_with_budget(
                        kernel32,
                        process,
                        int(float(termination_grace_seconds) * 1000),
                        budget_deadline,
                    )
                job_empty_observed = _wait_for_job_empty_with_budget(
                    kernel32, job, float(termination_grace_seconds), budget_deadline
                )
                if job_empty_observed is True and process_exit_observed is not True:
                    process_exit_observed, process_exit_code = _wait_for_process_exit_with_budget(
                        kernel32,
                        process,
                        int(float(termination_grace_seconds) * 1000),
                        budget_deadline,
                    )
            except Exception:
                containment = "uncertain"
        if (
            process_exit_observed is True
            and job_empty_observed is True
            and (not job_termination_requested or job_termination_call_succeeded is True)
        ):
            containment = "verified"
        else:
            containment = "uncertain"
        if created and containment != "verified":
            latch_trip_succeeded = _trip_fail_closed_latch(fail_closed_latch, reason)
            if not latch_trip_succeeded:
                reason = "containment_latch_trip_failed"
    finally:
        retain_control = (
            created
            and containment != "verified"
            and job is not None
            and (
                process_exit_observed is not True
                or job_empty_observed is not True
                or (job_termination_requested and job_termination_call_succeeded is not True)
            )
        )
        if retain_control:
            retained_control = RetainedJobControl(
                kernel32,
                job,
                process,
                thread,
                assigned,
                resumed,
            )
            job = None
            process = None
            thread = None
        if thread and kernel32 is not None:
            kernel32.CloseHandle(thread)
        if reader is not None and reader.is_alive():
            reader_join_timeout = 0.1
            if budget_deadline is not None:
                reader_join_timeout = _bounded_timeout_seconds(
                    reader_join_timeout, budget_deadline
                )
            reader.join(timeout=reader_join_timeout)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if process and kernel32 is not None:
            kernel32.CloseHandle(process)
        if job and kernel32 is not None:
            # KILL_ON_JOB_CLOSE is the final safety net; it is not counted as
            # observed-empty evidence if the explicit query above failed.
            kernel32.CloseHandle(job)

    if containment == "uncertain" and status not in {
        "timed_out",
        "pending_native_join",
        "invalid_output",
        "supervisor_error",
    }:
        status, reason = "containment_error", "process_tree_containment_unverified"
    if budget_deadline is not None and _deadline_expired(budget_deadline) and status in {
        "running",
        "child_exited",
        "pending_native_join",
    }:
        status, reason = "timed_out", _deadline_reason(relative_deadline, absolute_deadline)
    evidence = _evidence(
        created=created,
        assigned=assigned,
        resumed=resumed,
        process_exit_observed=process_exit_observed,
        process_exit_code=process_exit_code,
        job_termination_requested=job_termination_requested,
        job_termination_call_succeeded=job_termination_call_succeeded,
        job_empty_observed=job_empty_observed,
        containment=containment,
    )
    return SupervisedResult(status, reason, receipt, evidence, retained_control)
