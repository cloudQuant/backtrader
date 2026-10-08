"""Windows Job supervisor for the isolated OKX M01 monitor candidate."""

from __future__ import annotations

import ctypes
import hashlib
import os
import secrets
import subprocess
import sys
import threading
import time
import struct
from dataclasses import dataclass, field
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping

from . import worker
from . import current_types
from _certification import m01_private_monitor_v2 as contract

PROFILE = worker.PROFILE
CASE_STATUS = worker.CASE_STATUS
MAX_PARENT_TIMEOUT_SECONDS = worker.MAX_RUN_SECONDS
MAX_CLEANUP_SECONDS = 5.0
PINNED_WORKER_SHA256 = "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41"
PINNED_CONTRACT_SHA256 = "1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db"
PINNED_PYTHON_EXE = Path(r"C:\anaconda3\python.exe")
PINNED_PYTHON_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
PINNED_PYTHON_DLL = Path(r"C:\anaconda3\python311.dll")
PINNED_PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
_ORPHANED_RUNTIME_HANDLE_SETS: list[tuple[Any, tuple[int, ...]]] = []

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_STARTF_USESHOWWINDOW = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_ERROR_BROKEN_PIPE = 109
_HANDLE_FLAG_INHERIT = 1
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_MAX_PINNED_RUNTIME_FILE_BYTES = 128 * 1024 * 1024
_MAX_STDOUT = worker.MAX_OUTPUT_BYTES
_MAX_STDERR = 16 * 1024
_CHILD_SCRIPT = Path(__file__).with_name("worker.py").resolve()
_CONTRACT_SCRIPT = (
    Path(__file__).resolve().parents[1] / "_certification" / "m01_private_monitor_v2.py"
).resolve()
_PARENT_JOURNAL_MAGIC = worker._FRAME_MAGIC


@dataclass(frozen=True, repr=False)
class PrivateEvent:
    sequence: int
    received_utc_ms: int
    received_monotonic_ns: int
    raw_sha256: str
    raw_bytes: bytes = field(repr=False)


@dataclass(frozen=True)
class ObserverReady:
    run_nonce: str
    parent_pid: int
    worker_pid: int
    worker_source_sha256: str
    account_scope_sha256: str = field(repr=False)
    credential_binding_sha256: str = field(repr=False)
    current_rest_read_receipt_sha256: str = field(repr=False)
    owner_invocation_sha256: str = field(repr=False)
    subscription_ack_ids: tuple[str, ...] = ()
    connection_id_sha256: str = field(default="", repr=False)
    connection_event_id: str = ""
    readiness_event_id: str = ""
    balance_position_payload_count: int = 0
    balance_snapshot_observed: bool = False


@dataclass(frozen=True, repr=False)
class ObserverWorkerReceipt:
    run_nonce: str
    parent_pid: int
    worker_pid: int
    worker_source_sha256: str
    account_scope_sha256: str = field(repr=False)
    credential_binding_sha256: str = field(repr=False)
    current_rest_read_receipt_sha256: str = field(repr=False)
    owner_invocation_sha256: str = field(repr=False)
    connection_id_sha256: str = field(default="", repr=False)
    connection_event_id: str = ""
    readiness_event_id: str = ""
    event_count: int = 0
    event_journal_sha256: str = ""
    login_acknowledged: bool = False
    subscription_ack_ids: tuple[str, ...] = ()
    balance_position_payload_count: int = 0
    balance_snapshot_observed: bool = False
    ready_sent: bool = False
    socket_closed: bool = False
    normal_websocket_close: bool = False
    control_thread_joined: bool = False
    reason: str = ""
    status: str = CASE_STATUS


@dataclass(frozen=True)
class QuietWindow:
    run_nonce: str
    command_id: str
    cursor_before: int
    cursor_after: int
    quiet: bool
    partial_frame_clear: bool
    started_monotonic_ns: int
    ended_monotonic_ns: int


@dataclass(frozen=True)
class ObservationDrain:
    run_nonce: str
    cursor: int
    event_count: int
    latest_event_sha256: str | None
    event_journal_sha256: str
    events: tuple[PrivateEvent, ...] = field(repr=False)


@dataclass(frozen=True)
class ObserverCloseReceipt:
    run_nonce: str
    parent_pid: int
    worker_pid: int | None
    worker_source_sha256: str | None
    containment: str
    job_assigned_before_resume: bool
    process_resumed: bool
    stdin_closed: bool
    stdout_eof: bool
    stderr_eof: bool
    process_exit_observed: bool
    process_exit_code: int | None
    job_active_count: int | None
    drain_threads_joined: bool
    handles_closed: bool
    handle_close_failed: bool
    timed_out: bool
    forced_termination: bool
    termination_succeeded: bool | None
    socket_closed: bool
    normal_websocket_close: bool
    control_thread_joined: bool
    worker_receipt_valid: bool
    runtime_image_sha256: str | None = field(default=None, repr=False)
    runtime_dll_sha256: str | None = field(default=None, repr=False)
    runtime_image_file_id: str | None = field(default=None, repr=False)
    runtime_dll_file_id: str | None = field(default=None, repr=False)
    runtime_files_held_through_exit: bool = False
    runtime_files_closed: bool = False
    status: str = CASE_STATUS
    worker_receipt: ObserverWorkerReceipt | None = field(default=None, repr=False)


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", _FILETIME),
        ("ftLastAccessTime", _FILETIME),
        ("ftLastWriteTime", _FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
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


def _winapi() -> Any:
    if os.name != "nt":
        raise OSError("windows_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
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
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    kernel32.GetFileSizeEx.restype = wintypes.BOOL
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
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
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
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    return kernel32


def _canonical_win32_path(path: str) -> str:
    value = path[4:] if path.startswith("\\\\?\\") else path
    return os.path.normcase(os.path.normpath(value))


def _hold_and_verify_runtime_file(
    kernel32: Any, path: Path, expected_sha256: str, deadline: float
) -> tuple[int, str]:
    """Open one exact regular file and retain a handle denying write/delete sharing."""
    if type(expected_sha256) is not str or not worker._HEX64.fullmatch(expected_sha256):
        raise OSError("runtime_pin_invalid")
    expected_path = str(path)
    if not path.is_absolute() or str(path.resolve(strict=True)) != expected_path:
        raise OSError("runtime_path_identity")
    raw_handle = kernel32.CreateFileW(
        expected_path,
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if raw_handle in (None, 0, invalid_handle):
        raise OSError("runtime_file_open_failed")
    handle = int(raw_handle)
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise OSError("runtime_file_identity_unavailable")
        if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("runtime_file_reparse_point")
        final_buffer = ctypes.create_unicode_buffer(32768)
        final_length = kernel32.GetFinalPathNameByHandleW(
            handle, final_buffer, len(final_buffer), 0
        )
        if not final_length or final_length >= len(final_buffer):
            raise OSError("runtime_file_final_path_unavailable")
        if _canonical_win32_path(final_buffer.value) != _canonical_win32_path(expected_path):
            raise OSError("runtime_file_final_path_mismatch")
        file_size = ctypes.c_longlong()
        if not kernel32.GetFileSizeEx(handle, ctypes.byref(file_size)):
            raise OSError("runtime_file_size_unavailable")
        if not 0 < file_size.value <= _MAX_PINNED_RUNTIME_FILE_BYTES:
            raise OSError("runtime_file_size_invalid")
        digest = hashlib.sha256()
        total = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("runtime_file_verify_deadline")
            buffer = ctypes.create_string_buffer(64 * 1024)
            received = wintypes.DWORD()
            if not kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(received), None):
                raise OSError("runtime_file_read_failed")
            if not received.value:
                break
            total += received.value
            if total > _MAX_PINNED_RUNTIME_FILE_BYTES:
                raise OSError("runtime_file_size_invalid")
            digest.update(buffer.raw[: received.value])
        actual_sha256 = digest.hexdigest()
        if total != file_size.value or actual_sha256 != expected_sha256:
            raise OSError("runtime_file_pin_mismatch")
        file_id = (
            (int(info.dwVolumeSerialNumber) << 64)
            | (int(info.nFileIndexHigh) << 32)
            | int(info.nFileIndexLow)
        )
        if not file_id:
            raise OSError("runtime_file_id_invalid")
        return handle, f"{file_id:032x}"
    except BaseException:
        if not kernel32.CloseHandle(handle):
            _ORPHANED_RUNTIME_HANDLE_SETS.append((kernel32, (handle,)))
        raise


def _hold_runtime_files(kernel32: Any, deadline: float) -> dict[str, Any]:
    """Acquire the fixed executable and DLL before process creation."""
    acquired: list[int] = []
    files = (
        (PINNED_PYTHON_EXE, PINNED_PYTHON_SHA256, "image"),
        (PINNED_PYTHON_DLL, PINNED_PYTHON_DLL_SHA256, "dll"),
    )
    result: dict[str, Any] = {}
    try:
        for path, expected_sha256, name in files:
            if time.monotonic() >= deadline:
                raise TimeoutError("runtime_file_verify_deadline")
            handle, file_id = _hold_and_verify_runtime_file(
                kernel32, path, expected_sha256, deadline
            )
            acquired.append(handle)
            result[f"runtime_{name}_handle"] = handle
            result[f"runtime_{name}_sha256"] = expected_sha256
            result[f"runtime_{name}_file_id"] = file_id
        result["runtime_handles"] = tuple(acquired)
        return result
    except BaseException:
        failed: list[int] = []
        for handle in reversed(acquired):
            try:
                if not kernel32.CloseHandle(handle):
                    failed.append(handle)
            except Exception:
                failed.append(handle)
        if failed:
            _ORPHANED_RUNTIME_HANDLE_SETS.append((kernel32, tuple(failed)))
        raise


def _environment_block(env: Mapping[str, str]) -> Any:
    allowed = {
        "systemroot",
        "windir",
        "comspec",
        "temp",
        "tmp",
        "systemdrive",
        "userprofile",
        "localappdata",
        "appdata",
        "programfiles",
        "programfiles(x86)",
        "programdata",
        "path",
    }
    names = [key.lower() for key in env]
    if (
        any(type(key) is not str or type(value) is not str for key, value in env.items())
        or len(names) != len(set(names))
        or not set(names).issubset(allowed)
        or not {"systemroot", "windir"}.issubset(names)
        or any("\x00" in key or "\x00" in value for key, value in env.items())
    ):
        raise ValueError("fixed_child_environment_required")
    pairs = sorted(env.items(), key=lambda pair: pair[0].upper())
    text = "\0".join(f"{key}={value}" for key, value in pairs) + "\0\0"
    return ctypes.create_unicode_buffer(text)


def _new_pipe(kernel32: Any, *, parent_reads: bool) -> tuple[int, int]:
    security = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
    read_handle, write_handle = wintypes.HANDLE(), wintypes.HANDLE()
    if not kernel32.CreatePipe(
        ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(security), 16 * 1024
    ):
        raise OSError("pipe_create_failed")
    parent_handle = read_handle.value if parent_reads else write_handle.value
    if not kernel32.SetHandleInformation(parent_handle, _HANDLE_FLAG_INHERIT, 0):
        kernel32.CloseHandle(read_handle)
        kernel32.CloseHandle(write_handle)
        raise OSError("pipe_inherit_setup_failed")
    return int(read_handle.value), int(write_handle.value)


def _close_handle(kernel32: Any, handles: set[int], handle: int | None) -> bool:
    if not handle:
        return True
    try:
        closed = bool(kernel32.CloseHandle(handle))
    except Exception:
        closed = False
    if closed:
        handles.discard(int(handle))
    return closed


def _active_count(kernel32: Any, job: int) -> int:
    if not job:
        raise OSError("job_handle_required")
    info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    if not kernel32.QueryInformationJobObject(
        job,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    ):
        raise OSError("job_accounting_unavailable")
    return int(info.ActiveProcesses)


def _new_job(kernel32: Any) -> int:
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


def _worker_bootstrap(source_sha256: str, source_size: int) -> str:
    """Small `-c` loader that compiles only parent-verified worker bytes."""
    path_literal = repr(str(_CHILD_SCRIPT))
    return (
        "import hashlib,sys\n"
        f"_expected={source_sha256!r}\n"
        f"_size={source_size!r}\n"
        f"_file={path_literal}\n"
        "def _read_exact(n):\n"
        " b=bytearray()\n"
        " while len(b)<n:\n"
        "  p=sys.stdin.buffer.read(n-len(b))\n"
        "  if not p: raise SystemExit(91)\n"
        "  b.extend(p)\n"
        " return bytes(b)\n"
        "if int.from_bytes(_read_exact(4),'big')!=_size: raise SystemExit(92)\n"
        "_source=_read_exact(_size)\n"
        "if hashlib.sha256(_source).hexdigest()!=_expected: raise SystemExit(93)\n"
        "_ns={'__name__':'__main__','__file__':_file,'__cached__':None,'__package__':None}\n"
        "_ns['__okx_verified_worker_source_sha256__']=_expected\n"
        "_exit=None\n"
        "try:\n"
        " exec(compile(_source,_file,'exec'),_ns,_ns)\n"
        "except SystemExit as _error:\n"
        " _exit=_error.code\n"
        "if not callable(_ns.get('_worker_source_sha256')) or _ns['_worker_source_sha256']()!=_expected: raise SystemExit(94)\n"
        "raise SystemExit(_exit)\n"
    )


def _create_suspended(
    kernel32: Any,
    env: Mapping[str, str],
    *,
    worker_source_sha256: str,
    worker_source_size: int,
    deadline: float,
) -> dict[str, Any]:
    """Create one child suspended; explicit Job assignment precedes resume."""
    handles: set[int] = set()
    runtime: dict[str, Any] = {}
    job = 0
    pi = _PROCESS_INFORMATION()
    created = False
    attribute_list = None
    pipes: list[int] = []
    try:
        runtime = _hold_runtime_files(kernel32, deadline)
        handles.update(runtime["runtime_handles"])
        if time.monotonic() >= deadline:
            raise TimeoutError("runtime_setup_deadline")
        job = _new_job(kernel32)
        handles.add(job)
        stdin_read, stdin_write = _new_pipe(kernel32, parent_reads=False)
        stdout_read, stdout_write = _new_pipe(kernel32, parent_reads=True)
        stderr_read, stderr_write = _new_pipe(kernel32, parent_reads=True)
        pipes.extend(
            (stdin_read, stdin_write, stdout_read, stdout_write, stderr_read, stderr_write)
        )
        handles.update(pipes)

        startup_ex = _STARTUPINFOEXW()
        startup = startup_ex.StartupInfo
        startup.cb = ctypes.sizeof(startup_ex)
        startup.dwFlags = _STARTF_USESTDHANDLES | _STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.hStdInput = stdin_read
        startup.hStdOutput = stdout_write
        startup.hStdError = stderr_write
        required_size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(required_size))
        if not required_size.value:
            raise OSError("startup_attribute_size_unavailable")
        attr_storage = ctypes.create_string_buffer(required_size.value)
        attribute_list = ctypes.cast(attr_storage, wintypes.LPVOID)
        if not kernel32.InitializeProcThreadAttributeList(
            attribute_list, 1, 0, ctypes.byref(required_size)
        ):
            attribute_list = None
            raise OSError("startup_attribute_list_init_failed")
        startup_ex.lpAttributeList = attribute_list
        child_handles = (wintypes.HANDLE * 3)(stdin_read, stdout_write, stderr_write)
        if not kernel32.UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(child_handles, wintypes.LPVOID),
            ctypes.sizeof(child_handles),
            None,
            None,
        ):
            raise OSError("startup_handle_list_failed")

        python_exe = PINNED_PYTHON_EXE
        worker_path = _CHILD_SCRIPT
        if not python_exe.is_absolute() or not worker_path.is_absolute():
            raise OSError("absolute_child_paths_required")
        bootstrap = _worker_bootstrap(worker_source_sha256, worker_source_size)
        argv = [str(python_exe), "-I", "-S", "-B", "-c", bootstrap]
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        environment = _environment_block(env)
        flags = (
            _CREATE_SUSPENDED
            | _CREATE_UNICODE_ENVIRONMENT
            | _EXTENDED_STARTUPINFO_PRESENT
            | _CREATE_NO_WINDOW
        )
        if not kernel32.CreateProcessW(
            str(python_exe),
            command,
            None,
            None,
            True,
            flags,
            environment,
            str(PINNED_PYTHON_EXE.parent),
            ctypes.cast(ctypes.byref(startup_ex), ctypes.POINTER(_STARTUPINFOW)),
            ctypes.byref(pi),
        ):
            raise OSError("child_process_create_failed")
        created = True
        process = int(pi.hProcess)
        thread = int(pi.hThread)
        handles.update((process, thread))
        for handle in (stdin_read, stdout_write, stderr_write):
            if not _close_handle(kernel32, handles, handle):
                raise OSError("child_pipe_handle_close_failed")
        return {
            "job": job,
            "process": process,
            "thread": thread,
            "stdin": stdin_write,
            "stdout": stdout_read,
            "stderr": stderr_read,
            "handles": handles,
            "pid": int(pi.dwProcessId),
            "assigned": False,
            "created": created,
            "attribute_list": attribute_list,
            "attribute_storage": attr_storage,
            **runtime,
            "runtime_files_held_through_exit": False,
            "runtime_files_retained_for_unknown_child": False,
        }
    except BaseException as original_error:
        reaped = not created
        if created:
            try:
                kernel32.TerminateProcess(pi.hProcess, 0xEE51)
            except Exception:
                pass
            try:
                reaped = _wait_process(kernel32, int(pi.hProcess), 5000)
            except Exception:
                reaped = False
        runtime_handles = set(runtime.get("runtime_handles", ()))
        retained: list[int] = []
        for handle in list(handles):
            if handle in runtime_handles and not reaped:
                retained.append(handle)
                continue
            _close_handle(kernel32, handles, handle)
        if retained:
            _ORPHANED_RUNTIME_HANDLE_SETS.append((kernel32, tuple(retained)))
            raise ObserverError("child_cleanup_unconfirmed") from original_error
        raise
    finally:
        if attribute_list is not None:
            try:
                kernel32.DeleteProcThreadAttributeList(attribute_list)
            except Exception:
                pass


def _drain(kernel32: Any, handle: int, state: dict[str, Any], limit: int) -> None:
    try:
        while True:
            buffer = ctypes.create_string_buffer(8192)
            received = wintypes.DWORD()
            ok = kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(received), None)
            if not ok:
                state["eof"] = ctypes.get_last_error() == _ERROR_BROKEN_PIPE
                state["error"] = not state["eof"]
                break
            if received.value == 0:
                state["eof"] = True
                break
            chunk = buffer.raw[: received.value]
            state["total"] += len(chunk)
            with state["condition"]:
                available = max(0, limit - len(state["raw"]))
                state["raw"].extend(chunk[:available])
                if len(chunk) > available:
                    state["overflow"] = True
                state["condition"].notify_all()
    except BaseException:
        state["error"] = True
    finally:
        with state["condition"]:
            state["done"] = True
            state["condition"].notify_all()


def _write_all(kernel32: Any, handle: int, raw: bytes, deadline: float) -> bool:
    if type(raw) is not bytes or len(raw) > worker.MAX_LAUNCH_FRAME_BYTES:
        return False
    offset = 0
    while offset < len(raw):
        if time.monotonic() >= deadline:
            raise TimeoutError("stdin_deadline")
        chunk = raw[offset:]
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not kernel32.WriteFile(handle, buffer, len(chunk), ctypes.byref(written), None):
            return False
        if written.value <= 0:
            return False
        offset += written.value
    return True


def _wait_process(kernel32: Any, handle: int, milliseconds: int) -> bool:
    result = kernel32.WaitForSingleObject(handle, max(0, milliseconds))
    if result == _WAIT_OBJECT_0:
        return True
    if result == _WAIT_TIMEOUT:
        return False
    raise OSError("process_wait_failed")


def _process_exit_code(kernel32: Any, process: int) -> int | None:
    value = wintypes.DWORD()
    if not kernel32.GetExitCodeProcess(process, ctypes.byref(value)) or value.value == 259:
        return None
    return int(value.value)


def _assign_control_to_job(kernel32: Any, control: dict[str, Any], deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("job_assignment_deadline")
    if not kernel32.AssignProcessToJobObject(control["job"], control["process"]):
        raise OSError("job_assignment_failed")
    if _active_count(kernel32, control["job"]) != 1:
        raise OSError("job_assignment_unobserved")
    control["assigned"] = True


def _resume_control(kernel32: Any, control: dict[str, Any], deadline: float) -> None:
    if not control.get("assigned") or _active_count(kernel32, control["job"]) != 1:
        raise OSError("job_assignment_required_before_resume")
    if time.monotonic() >= deadline:
        raise TimeoutError("resume_deadline")
    if kernel32.ResumeThread(control["thread"]) != 1:
        raise OSError("resume_not_observed")


def _terminate_control(kernel32: Any, control: dict[str, Any], exit_code: int) -> bool:
    if control.get("assigned"):
        return bool(kernel32.TerminateJobObject(control["job"], exit_code))
    return bool(kernel32.TerminateProcess(control["process"], exit_code))


def _first_child_frame(raw: bytes) -> tuple[int, bytes] | None:
    if len(raw) < 5:
        return None
    kind = raw[0]
    length = int.from_bytes(raw[1:5], "big")
    if length > worker.MAX_CONTROL_FRAME_BYTES:
        raise ValueError("first_control_frame_size")
    if len(raw) < 5 + length:
        return None
    return kind, raw[5 : 5 + length]


class ObserverError(ValueError):
    """Fixed, redacted parent-side observer failure."""

    def __init__(self, reason: str):
        if type(reason) is not str or not worker._SAFE_REASON.fullmatch(reason):
            reason = "observer_error"
        super().__init__(reason)
        self.reason = reason


def _verify_candidate_source_pins() -> tuple[bytes, bytes]:
    """Verify exact local worker and pure-contract bytes before any child starts."""
    loaded_path = getattr(contract, "__file__", None)
    try:
        if type(loaded_path) is not str or Path(loaded_path).resolve() != _CONTRACT_SCRIPT:
            raise ObserverError("contract_source_origin_mismatch")
        contract_bytes = _CONTRACT_SCRIPT.read_bytes()
        worker_bytes = _CHILD_SCRIPT.read_bytes()
    except ObserverError:
        raise
    except Exception:
        raise ObserverError("candidate_source_unavailable") from None
    if hashlib.sha256(contract_bytes).hexdigest() != PINNED_CONTRACT_SHA256:
        raise ObserverError("contract_source_pin_mismatch")
    if hashlib.sha256(worker_bytes).hexdigest() != PINNED_WORKER_SHA256:
        raise ObserverError("worker_source_pin_mismatch")
    return worker_bytes, contract_bytes


def _new_pipe_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "raw": bytearray(),
        "total": 0,
        "eof": False,
        "error": False,
        "overflow": False,
        "done": False,
    }
    state["condition"] = threading.Condition()
    return state


class ObserverContext:
    """Incremental bounded Job context; owns one child through normal close."""

    def __init__(
        self,
        *,
        kernel32: Any,
        control: dict[str, Any],
        request: worker.LaunchRequest,
        journal_writer: Any,
        stdout_state: dict[str, Any],
        stderr_state: dict[str, Any],
        drain_threads: list[threading.Thread],
        absolute_started: float,
        absolute_deadline: float,
        cleanup_seconds: float,
    ):
        self._kernel32 = kernel32
        self._control = control
        self.request = request
        self._writer = journal_writer
        self._stdout = stdout_state
        self._stderr = stderr_state
        self._drain_threads = drain_threads
        self._started = absolute_started
        self._deadline = absolute_deadline
        self._cleanup_seconds = cleanup_seconds
        self._stdout_offset = 0
        self._events: list[PrivateEvent] = []
        self._raw_events: list[bytes] = []
        self._ready: ObserverReady | None = None
        self._worker_receipt: ObserverWorkerReceipt | None = None
        self._pending_acks: dict[tuple[int, str], Mapping[str, Any]] = {}
        self._error_reason: str | None = None
        self._closed = False
        self._stdin_closed = False
        self._timed_out = False
        self._forced = False
        self._termination_succeeded: bool | None = None
        self._handle_close_failed = False
        self._exit_observed = False
        self._exit_code: int | None = None
        self._job_active_count: int | None = None
        self._containment = "windows_job"
        self._writer.write_bytes(_PARENT_JOURNAL_MAGIC)

    @property
    def run_nonce(self) -> str:
        return self.request.run_nonce

    @property
    def deadline_monotonic(self) -> float:
        return self._deadline

    def _check_deadline(self, caller_deadline: float | None = None) -> float:
        deadline = self._deadline
        if caller_deadline is not None:
            deadline = min(deadline, caller_deadline)
        if time.monotonic() >= deadline:
            raise TimeoutError("observer_deadline")
        return deadline

    def _extract_frame(self) -> tuple[int, bytes] | None:
        with self._stdout["condition"]:
            if self._stdout["overflow"] or self._stdout["error"]:
                raise ObserverError("stdout_drain_failed")
            raw = self._stdout["raw"]
            available = len(raw) - self._stdout_offset
            if available < 5:
                if self._stdout["done"]:
                    if available:
                        raise ObserverError("stdout_truncated_header")
                    return None
                return None
            kind = raw[self._stdout_offset]
            length = struct.unpack_from(">I", raw, self._stdout_offset + 1)[0]
            if kind == worker._FRAME_EVENT:
                maximum = worker.MAX_EVENT_BYTES + worker._EVENT_HEADER.size
            else:
                maximum = worker.MAX_CONTROL_FRAME_BYTES
            if length > maximum:
                raise ObserverError("stdout_frame_size")
            if available < 5 + length:
                if self._stdout["done"]:
                    raise ObserverError("stdout_truncated_payload")
                return None
            start = self._stdout_offset + 5
            payload = bytes(raw[start : start + length])
            self._stdout_offset += 5 + length
            return kind, payload

    def _wait_frame(self, deadline: float) -> tuple[int, bytes] | None:
        while True:
            frame = self._extract_frame()
            if frame is not None:
                return frame
            if self._stdout["done"]:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with self._stdout["condition"]:
                self._stdout["condition"].wait(timeout=min(0.05, remaining))

    def _store_event(self, payload: bytes) -> PrivateEvent:
        sequence, wall_ms, mono_ns, raw = worker.decode_event_payload(payload)
        if sequence != len(self._events) + 1:
            raise ObserverError("event_sequence")
        digest = hashlib.sha256(raw).hexdigest()
        record = struct.pack(">IQQI", sequence, wall_ms, mono_ns, len(raw)) + raw
        self._writer.write_bytes(record + bytes.fromhex(digest))
        event = PrivateEvent(sequence, wall_ms, mono_ns, digest, raw)
        self._events.append(event)
        self._raw_events.append(raw)
        return event

    def _handle_frame(self, kind: int, payload: bytes) -> Mapping[str, Any] | PrivateEvent | None:
        if kind == worker._FRAME_EVENT:
            return self._store_event(payload)
        if kind in (
            worker._FRAME_READY,
            worker._FRAME_QUIET_ACK,
            worker._FRAME_DRAIN_ACK,
            worker._FRAME_RECEIPT,
            worker._FRAME_ERROR,
        ):
            value = worker.strict_json(
                payload[:-1] if payload.endswith(b"\n") else payload,
                limit=worker.MAX_CONTROL_FRAME_BYTES,
            )
            if type(value) is not dict:
                raise ObserverError("control_frame_shape")
            if kind == worker._FRAME_READY:
                expected = {
                    "account_scope_sha256",
                    "credential_binding_sha256",
                    "balance_position_payload_count",
                    "balance_snapshot_observed",
                    "connection_event_id",
                    "connection_id_sha256",
                    "current_rest_read_receipt_sha256",
                    "parent_pid",
                    "owner_invocation_sha256",
                    "profile",
                    "protocol_version",
                    "readiness_event_id",
                    "run_nonce",
                    "subscription_ack_ids",
                    "worker_pid",
                    "worker_source_sha256",
                }
                if set(value) != expected or self._ready is not None:
                    raise ObserverError("ready_shape")
                if (
                    value["profile"] != PROFILE
                    or value["protocol_version"] != worker.PROTOCOL_VERSION
                    or value["run_nonce"] != self.request.run_nonce
                    or value["parent_pid"] != self.request.parent_pid
                    or value["worker_pid"] != self._control["pid"]
                    or value["worker_source_sha256"] != self.request.worker_source_sha256
                    or value["account_scope_sha256"] != self.request.account_scope_sha256
                    or value["credential_binding_sha256"] != self.request.credential_binding_sha256
                    or value["current_rest_read_receipt_sha256"]
                    != self.request.current_rest_read_receipt_sha256
                    or value["owner_invocation_sha256"] != self.request.owner_invocation_sha256
                    or value["subscription_ack_ids"] != [worker.SUBSCRIPTION_ID]
                    or type(value["balance_position_payload_count"]) is not int
                    or value["balance_position_payload_count"] < 0
                    or value["balance_snapshot_observed"] is not False
                    or type(value["worker_pid"]) is not int
                    or type(value["connection_id_sha256"]) is not str
                    or not worker._HEX64.fullmatch(value["connection_id_sha256"])
                    or type(value["connection_event_id"]) is not str
                    or type(value["readiness_event_id"]) is not str
                ):
                    raise ObserverError("ready_binding")
                credentials = worker.parse_credentials(self.request.credential_packet)
                summary = contract.validate_event_journal(
                    self._raw_events,
                    expected_rest_uid=credentials.expected_rest_uid,
                    run_nonce=self.request.run_nonce,
                )
                if (
                    value["connection_id_sha256"] != summary.connection_id_sha256
                    or value["connection_event_id"] != summary.connection_event_id
                    or value["readiness_event_id"] != summary.readiness_event_id
                    or value["balance_position_payload_count"] != summary.private_data_event_count
                ):
                    raise ObserverError("ready_event_journal_binding")
                self._ready = ObserverReady(
                    run_nonce=value["run_nonce"],
                    parent_pid=value["parent_pid"],
                    worker_pid=value["worker_pid"],
                    worker_source_sha256=value["worker_source_sha256"],
                    account_scope_sha256=value["account_scope_sha256"],
                    credential_binding_sha256=value["credential_binding_sha256"],
                    current_rest_read_receipt_sha256=value["current_rest_read_receipt_sha256"],
                    owner_invocation_sha256=value["owner_invocation_sha256"],
                    subscription_ack_ids=tuple(value["subscription_ack_ids"]),
                    connection_id_sha256=value["connection_id_sha256"],
                    connection_event_id=value["connection_event_id"],
                    readiness_event_id=value["readiness_event_id"],
                    balance_position_payload_count=value["balance_position_payload_count"],
                    balance_snapshot_observed=value["balance_snapshot_observed"],
                )
                return value
            if kind == worker._FRAME_ERROR:
                reason = value.get("reason", "child_error")
                if type(reason) is not str or not worker._SAFE_REASON.fullmatch(reason):
                    reason = "child_error"
                self._error_reason = reason
                raise ObserverError(reason)
            if kind == worker._FRAME_RECEIPT:
                expected = {
                    "account_scope_sha256",
                    "credential_binding_sha256",
                    "balance_position_payload_count",
                    "balance_snapshot_observed",
                    "connection_event_id",
                    "connection_id_sha256",
                    "current_rest_read_receipt_sha256",
                    "event_count",
                    "event_journal_sha256",
                    "login_acknowledged",
                    "normal_websocket_close",
                    "parent_pid",
                    "owner_invocation_sha256",
                    "profile",
                    "reason",
                    "readiness_event_id",
                    "run_nonce",
                    "socket_closed",
                    "status",
                    "subscription_ack_ids",
                    "worker_pid",
                    "worker_source_sha256",
                    "ready_sent",
                    "control_thread_joined",
                }
                if set(value) != expected or value.get("run_nonce") != self.request.run_nonce:
                    raise ObserverError("receipt_shape")
                ack_ids = value.get("subscription_ack_ids")
                expected_ack_ids = [worker.SUBSCRIPTION_ID]
                credentials = worker.parse_credentials(self.request.credential_packet)
                summary = contract.validate_event_journal(
                    self._raw_events,
                    expected_rest_uid=credentials.expected_rest_uid,
                    run_nonce=self.request.run_nonce,
                )
                if (
                    value["parent_pid"] != self.request.parent_pid
                    or value["worker_pid"] != self._control["pid"]
                    or value["worker_source_sha256"] != self.request.worker_source_sha256
                    or value["account_scope_sha256"] != self.request.account_scope_sha256
                    or value["credential_binding_sha256"] != self.request.credential_binding_sha256
                    or value["current_rest_read_receipt_sha256"]
                    != self.request.current_rest_read_receipt_sha256
                    or value["owner_invocation_sha256"] != self.request.owner_invocation_sha256
                    or value["profile"] != PROFILE
                    or value["status"] != CASE_STATUS
                    or value["event_count"] != len(self._events)
                    or value["event_journal_sha256"]
                    != hashlib.sha256(worker.encode_journal(self._raw_events)).hexdigest()
                    or type(value["event_count"]) is not int
                    or not 0 <= value["event_count"] <= worker.MAX_EVENT_COUNT
                    or type(value["event_journal_sha256"]) is not str
                    or not worker._HEX64.fullmatch(value["event_journal_sha256"])
                    or type(value["login_acknowledged"]) is not bool
                    or not value["login_acknowledged"]
                    or type(value["ready_sent"]) is not bool
                    or type(value["socket_closed"]) is not bool
                    or type(value["normal_websocket_close"]) is not bool
                    or type(value["control_thread_joined"]) is not bool
                    or type(value["balance_position_payload_count"]) is not int
                    or value["balance_position_payload_count"] != summary.private_data_event_count
                    or value["balance_snapshot_observed"] is not False
                    or value["connection_id_sha256"] != summary.connection_id_sha256
                    or value["connection_event_id"] != summary.connection_event_id
                    or value["readiness_event_id"] != summary.readiness_event_id
                    or type(value["reason"]) is not str
                    or not worker._SAFE_REASON.fullmatch(value["reason"])
                    or type(ack_ids) is not list
                    or any(item not in expected_ack_ids for item in ack_ids)
                    or len(ack_ids) != len(set(ack_ids))
                    or (value["ready_sent"] and ack_ids != expected_ack_ids)
                    or not value["ready_sent"]
                    or value["reason"] != "normal_close_requested"
                    or not value["socket_closed"]
                    or not value["normal_websocket_close"]
                    or not value["control_thread_joined"]
                ):
                    raise ObserverError("receipt_binding")
                self._worker_receipt = ObserverWorkerReceipt(
                    run_nonce=value["run_nonce"],
                    parent_pid=value["parent_pid"],
                    worker_pid=value["worker_pid"],
                    worker_source_sha256=value["worker_source_sha256"],
                    account_scope_sha256=value["account_scope_sha256"],
                    credential_binding_sha256=value["credential_binding_sha256"],
                    current_rest_read_receipt_sha256=value["current_rest_read_receipt_sha256"],
                    owner_invocation_sha256=value["owner_invocation_sha256"],
                    connection_id_sha256=value["connection_id_sha256"],
                    connection_event_id=value["connection_event_id"],
                    readiness_event_id=value["readiness_event_id"],
                    event_count=value["event_count"],
                    event_journal_sha256=value["event_journal_sha256"],
                    login_acknowledged=value["login_acknowledged"],
                    subscription_ack_ids=tuple(ack_ids),
                    balance_position_payload_count=value["balance_position_payload_count"],
                    balance_snapshot_observed=value["balance_snapshot_observed"],
                    ready_sent=value["ready_sent"],
                    socket_closed=value["socket_closed"],
                    normal_websocket_close=value["normal_websocket_close"],
                    control_thread_joined=value["control_thread_joined"],
                    reason=value["reason"],
                    status=value["status"],
                )
                return value
            if kind in (worker._FRAME_QUIET_ACK, worker._FRAME_DRAIN_ACK):
                command_id = value.get("command_id")
                if type(command_id) is not str or not worker._NONCE.fullmatch(command_id):
                    raise ObserverError("ack_command_id")
                self._pending_acks[(kind, command_id)] = value
                return value
        raise ObserverError("unexpected_child_frame")

    def _pump(self, *, deadline: float, wait: bool) -> Mapping[str, Any] | PrivateEvent | None:
        frame = self._wait_frame(deadline) if wait else self._extract_frame()
        if frame is None:
            return None
        return self._handle_frame(*frame)

    def wait_ready(self, deadline_monotonic: float | None = None) -> ObserverReady:
        deadline = self._check_deadline(deadline_monotonic)
        while self._ready is None:
            result = self._pump(deadline=deadline, wait=True)
            if result is None:
                raise TimeoutError("ready_deadline")
            if self._worker_receipt is not None:
                raise ObserverError("child_exited_before_ready")
        return self._ready

    def _pump_available(self) -> None:
        now = time.monotonic()
        while True:
            result = self._pump(deadline=now, wait=False)
            if result is None:
                return

    def events_since(self, cursor: int) -> tuple[PrivateEvent, ...]:
        if type(cursor) is not int or not 0 <= cursor <= worker.MAX_EVENT_COUNT:
            raise ObserverError("event_cursor")
        self._pump_available()
        if cursor > len(self._events):
            raise ObserverError("event_cursor_ahead")
        return tuple(self._events[cursor:])

    def wait_next_event(self, cursor: int, deadline_monotonic: float) -> PrivateEvent:
        deadline = self._check_deadline(deadline_monotonic)
        while True:
            events = self.events_since(cursor)
            if events:
                return events[0]
            result = self._pump(deadline=deadline, wait=True)
            if isinstance(result, PrivateEvent) and result.sequence > cursor:
                return result
            if result is None:
                raise TimeoutError("event_deadline")
            if self._worker_receipt is not None:
                raise ObserverError("observer_closed")

    def _send_command(self, document: Mapping[str, Any], deadline: float) -> None:
        if self._stdin_closed or not self._control.get("stdin"):
            raise ObserverError("stdin_closed")
        raw = worker.encode_control(worker._FRAME_COMMAND, document)
        if not _write_all(self._kernel32, self._control["stdin"], raw, deadline):
            raise ObserverError("control_write_failed")

    def assert_quiet(self, cursor: int, duration_ms: int, deadline_monotonic: float) -> QuietWindow:
        deadline = self._check_deadline(deadline_monotonic)
        if self._ready is None:
            raise ObserverError("ready_required")
        if type(duration_ms) is not int or not 1 <= duration_ms <= worker.MAX_QUIET_MS:
            raise ObserverError("quiet_duration")
        self._pump_available()
        if type(cursor) is not int or not 0 <= cursor <= len(self._events):
            raise ObserverError("event_cursor")
        started = time.monotonic_ns()
        command_id = secrets.token_hex(16)
        if cursor != len(self._events):
            return QuietWindow(
                self.run_nonce,
                command_id,
                cursor,
                len(self._events),
                False,
                True,
                started,
                time.monotonic_ns(),
            )
        self._send_command(
            {
                "command": "quiet",
                "command_id": command_id,
                "cursor": cursor,
                "duration_ms": duration_ms,
                "run_nonce": self.run_nonce,
            },
            deadline,
        )
        while (worker._FRAME_QUIET_ACK, command_id) not in self._pending_acks:
            result = self._pump(deadline=deadline, wait=True)
            if result is None:
                raise TimeoutError("quiet_ack_deadline")
        value = self._pending_acks.pop((worker._FRAME_QUIET_ACK, command_id))
        if set(value) != {"command_id", "cursor", "partial_frame_clear", "quiet", "run_nonce"}:
            raise ObserverError("quiet_ack_shape")
        if value["run_nonce"] != self.run_nonce or value["command_id"] != command_id:
            raise ObserverError("quiet_ack_binding")
        cursor_after = value["cursor"]
        partial_clear = value["partial_frame_clear"]
        quiet = value["quiet"]
        if (
            type(cursor_after) is not int
            or type(partial_clear) is not bool
            or type(quiet) is not bool
        ):
            raise ObserverError("quiet_ack_types")
        if quiet and (cursor_after != cursor or not partial_clear):
            raise ObserverError("quiet_ack_claim")
        return QuietWindow(
            self.run_nonce,
            command_id,
            cursor,
            cursor_after,
            quiet,
            partial_clear,
            started,
            time.monotonic_ns(),
        )

    def drain(self, deadline_monotonic: float) -> ObservationDrain:
        deadline = self._check_deadline(deadline_monotonic)
        if self._ready is None:
            raise ObserverError("ready_required")
        command_id = secrets.token_hex(16)
        self._send_command(
            {"command": "drain", "command_id": command_id, "run_nonce": self.run_nonce}, deadline
        )
        while (worker._FRAME_DRAIN_ACK, command_id) not in self._pending_acks:
            result = self._pump(deadline=deadline, wait=True)
            if result is None:
                raise TimeoutError("drain_ack_deadline")
        value = self._pending_acks.pop((worker._FRAME_DRAIN_ACK, command_id))
        if set(value) != {"command_id", "cursor", "event_journal_sha256", "run_nonce"}:
            raise ObserverError("drain_ack_shape")
        self._pump_available()
        cursor = value.get("cursor")
        if (
            value["run_nonce"] != self.run_nonce
            or value["command_id"] != command_id
            or type(cursor) is not int
            or not 0 <= cursor <= len(self._events)
            or value["event_journal_sha256"]
            != hashlib.sha256(worker.encode_journal(self._raw_events[:cursor])).hexdigest()
        ):
            raise ObserverError("drain_ack_binding")
        events = tuple(self._events[:cursor])
        latest = events[-1].raw_sha256 if events else None
        return ObservationDrain(
            self.run_nonce,
            cursor,
            cursor,
            latest,
            value["event_journal_sha256"],
            events,
        )

    def _close_pipe(self, name: str) -> None:
        handle = self._control.get(name)
        if handle:
            if not _close_handle(self._kernel32, self._control["handles"], handle):
                self._handle_close_failed = True
            self._control[name] = 0

    def close(self, deadline_monotonic: float | None = None) -> ObserverCloseReceipt:
        if self._closed:
            return self._close_receipt()
        now = time.monotonic()
        cleanup_deadline = min(
            self._deadline + self._cleanup_seconds,
            now + self._cleanup_seconds,
            deadline_monotonic if deadline_monotonic is not None else now + self._cleanup_seconds,
        )
        if self._ready is not None and self._worker_receipt is None and not self._stdin_closed:
            try:
                command_id = secrets.token_hex(16)
                self._send_command(
                    {"command": "close", "command_id": command_id, "run_nonce": self.run_nonce},
                    min(cleanup_deadline, self._deadline),
                )
            except Exception:
                pass
        self._close_pipe("stdin")
        self._stdin_closed = True
        process = self._control.get("process")
        job = self._control.get("job")
        normal_shutdown_deadline = min(cleanup_deadline, time.monotonic() + 4.0)
        while time.monotonic() < normal_shutdown_deadline:
            try:
                self._pump(deadline=min(cleanup_deadline, time.monotonic() + 0.05), wait=True)
            except (ObserverError, worker.CandidateError):
                pass
            try:
                self._exit_observed = _wait_process(
                    self._kernel32,
                    process,
                    min(50, max(0, int((normal_shutdown_deadline - time.monotonic()) * 1000))),
                )
                self._job_active_count = _active_count(self._kernel32, job)
            except Exception:
                self._job_active_count = None
            if (
                self._exit_observed
                and self._job_active_count == 0
                and self._stdout["eof"]
                and self._stderr["eof"]
            ):
                break
        if not self._exit_observed or self._job_active_count != 0:
            self._timed_out = True
            self._forced = True
            try:
                self._termination_succeeded = bool(
                    self._kernel32.TerminateJobObject(job, 0xEE57)
                    if self._control.get("assigned")
                    else self._kernel32.TerminateProcess(process, 0xEE57)
                )
            except Exception:
                self._termination_succeeded = False
            while time.monotonic() < cleanup_deadline:
                try:
                    self._exit_observed = _wait_process(self._kernel32, process, 50)
                    self._job_active_count = _active_count(self._kernel32, job)
                except Exception:
                    pass
                if (
                    self._exit_observed
                    and self._job_active_count == 0
                    and self._stdout["eof"]
                    and self._stderr["eof"]
                ):
                    break
                time.sleep(0.01)
        self._exit_code = _process_exit_code(self._kernel32, process)
        self._close_pipe("stdout")
        self._close_pipe("stderr")
        for thread in self._drain_threads:
            thread.join(timeout=self._cleanup_seconds)
        if self._drain_threads and any(thread.is_alive() for thread in self._drain_threads):
            self._handle_close_failed = True
        for name in ("thread", "process", "job"):
            self._close_pipe(name)
        runtime_handles = tuple(self._control.get("runtime_handles", ()))
        runtime_was_held = bool(runtime_handles) and all(
            handle in self._control["handles"] for handle in runtime_handles
        )
        release_runtime_files = (
            self._exit_observed and self._job_active_count == 0 and runtime_was_held
        )
        self._control["runtime_files_held_through_exit"] = release_runtime_files
        if release_runtime_files:
            for handle in reversed(runtime_handles):
                if not _close_handle(self._kernel32, self._control["handles"], handle):
                    self._handle_close_failed = True
        elif runtime_handles:
            self._control["runtime_files_retained_for_unknown_child"] = True
            _ORPHANED_RUNTIME_HANDLE_SETS.append((self._kernel32, runtime_handles))
        if self._control.get("handles"):
            self._handle_close_failed = True
        self._closed = True
        return self._close_receipt()

    def _close_receipt(self) -> ObserverCloseReceipt:
        receipt = self._worker_receipt
        job = self._control.get("job")
        if job:
            try:
                self._job_active_count = _active_count(self._kernel32, job)
            except Exception:
                pass
        return ObserverCloseReceipt(
            run_nonce=self.run_nonce,
            parent_pid=self.request.parent_pid,
            worker_pid=self._control.get("pid"),
            worker_source_sha256=self.request.worker_source_sha256,
            containment=self._containment,
            job_assigned_before_resume=bool(self._control.get("assigned")),
            process_resumed=bool(self._control.get("resumed")),
            stdin_closed=self._stdin_closed,
            stdout_eof=bool(self._stdout.get("eof")),
            stderr_eof=bool(self._stderr.get("eof")),
            process_exit_observed=self._exit_observed,
            process_exit_code=self._exit_code,
            job_active_count=self._job_active_count,
            drain_threads_joined=all(not thread.is_alive() for thread in self._drain_threads),
            handles_closed=not bool(self._control.get("handles")) and not self._handle_close_failed,
            handle_close_failed=self._handle_close_failed,
            timed_out=self._timed_out,
            forced_termination=self._forced,
            termination_succeeded=self._termination_succeeded,
            socket_closed=receipt.socket_closed if receipt is not None else False,
            normal_websocket_close=receipt.normal_websocket_close if receipt is not None else False,
            control_thread_joined=receipt.control_thread_joined if receipt is not None else False,
            worker_receipt_valid=bool(self._worker_receipt),
            runtime_image_sha256=self._control.get("runtime_image_sha256"),
            runtime_dll_sha256=self._control.get("runtime_dll_sha256"),
            runtime_image_file_id=self._control.get("runtime_image_file_id"),
            runtime_dll_file_id=self._control.get("runtime_dll_file_id"),
            runtime_files_held_through_exit=bool(
                self._control.get("runtime_files_held_through_exit")
            ),
            runtime_files_closed=all(
                handle not in self._control.get("handles", set())
                for handle in self._control.get("runtime_handles", ())
            ),
            worker_receipt=receipt,
        )


def start_m01_monitor(
    *,
    current_read_proof: current_types.CurrentReadProof,
    invocation: current_types.M01Invocation,
    journal_writer: Any,
    timeout_seconds: float = MAX_PARENT_TIMEOUT_SECONDS,
    cleanup_seconds: float = MAX_CLEANUP_SECONDS,
) -> ObserverContext:
    """Start one fixed child from a one-use, factory-minted C01 proof."""
    (
        account_scope_sha256,
        credential_binding_sha256,
        current_rest_read_receipt_sha256,
        owner_invocation_sha256,
        expected_rest_uid,
        credential_packet,
    ) = current_types.consume_current_read_proof(
        current_read_proof, invocation, now_ms=time.time_ns() // 1_000_000
    )
    parsed_credentials = worker.parse_credentials(credential_packet)
    if parsed_credentials.expected_rest_uid != expected_rest_uid:
        raise ObserverError("proof_credential_uid_mismatch")
    if worker.LIVE_TRANSPORT_ENABLEMENT != "ROOT_FIXED_ISSUER_ADMITTED":
        raise ObserverError("candidate_unregistered")
    started = time.monotonic()
    parent_pid = os.getpid()
    if os.name != "nt":
        raise ObserverError("windows_job_required")
    if (
        type(timeout_seconds) not in (int, float)
        or not 0 < float(timeout_seconds) <= MAX_PARENT_TIMEOUT_SECONDS
        or type(cleanup_seconds) not in (int, float)
        or not 0 < float(cleanup_seconds) <= MAX_CLEANUP_SECONDS
    ):
        raise ObserverError("deadline_invalid")
    if not callable(getattr(journal_writer, "write_bytes", None)):
        raise ObserverError("private_journal_writer_required")
    if type(account_scope_sha256) is not str or not worker._HEX64.fullmatch(account_scope_sha256):
        raise ObserverError("account_scope_invalid")
    if type(credential_binding_sha256) is not str or not worker._HEX64.fullmatch(
        credential_binding_sha256
    ):
        raise ObserverError("credential_binding_invalid")
    if type(current_rest_read_receipt_sha256) is not str or not worker._HEX64.fullmatch(
        current_rest_read_receipt_sha256
    ):
        raise ObserverError("rest_read_receipt_invalid")
    if type(owner_invocation_sha256) is not str or not worker._HEX64.fullmatch(
        owner_invocation_sha256
    ):
        raise ObserverError("owner_invocation_invalid")
    if (
        type(credential_packet) is not bytes
        or len(credential_packet) > worker.MAX_CREDENTIAL_PACKET_BYTES
    ):
        raise ObserverError("credential_packet_size")
    source_bytes, _contract_bytes = _verify_candidate_source_pins()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    deadline = started + float(timeout_seconds)
    request = worker.LaunchRequest(
        run_nonce=secrets.token_hex(16),
        parent_pid=parent_pid,
        worker_source_sha256=source_sha256,
        account_scope_sha256=account_scope_sha256,
        credential_binding_sha256=credential_binding_sha256,
        current_rest_read_receipt_sha256=current_rest_read_receipt_sha256,
        owner_invocation_sha256=owner_invocation_sha256,
        event_timeout_ms=int(float(timeout_seconds) * 1000),
        credential_packet=credential_packet,
    )
    launch_frame = worker.encode_launch_frame(request)
    environment = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
    }
    if not all(environment.values()):
        raise ObserverError("fixed_windows_environment_unavailable")
    if (
        str(PINNED_PYTHON_EXE).lower() != r"c:\anaconda3\python.exe"
        or str(PINNED_PYTHON_DLL).lower() != r"c:\anaconda3\python311.dll"
        or PINNED_PYTHON_EXE.parent != PINNED_PYTHON_DLL.parent
        or len(PINNED_PYTHON_SHA256) != 64
        or len(PINNED_PYTHON_DLL_SHA256) != 64
        or sys.version_info[:2] != (3, 11)
        or ctypes.sizeof(ctypes.c_void_p) != 8
    ):
        raise ObserverError("fixed_python_311_x64_required")
    kernel32 = _winapi()
    control: dict[str, Any] | None = None
    stdout_state = _new_pipe_state()
    stderr_state = _new_pipe_state()
    drain_threads: list[threading.Thread] = []
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("setup_deadline")
        control = _create_suspended(
            kernel32,
            environment,
            worker_source_sha256=source_sha256,
            worker_source_size=len(source_bytes),
            deadline=deadline,
        )
        for pipe_name, state, limit in (
            ("stdout", stdout_state, _MAX_STDOUT),
            ("stderr", stderr_state, _MAX_STDERR),
        ):
            thread = threading.Thread(
                target=_drain,
                args=(kernel32, control[pipe_name], state, limit),
                daemon=True,
                name=f"okx-t01-{pipe_name}-drain",
            )
            thread.start()
            drain_threads.append(thread)
        if time.monotonic() >= deadline:
            raise TimeoutError("pre_assignment_deadline")
        _assign_control_to_job(kernel32, control, deadline)
        _resume_control(kernel32, control, deadline)
        control["resumed"] = True
        for name in ("thread",):
            if not _close_handle(kernel32, control["handles"], control[name]):
                raise ObserverError("thread_handle_close_failed")
            control[name] = 0
        if time.monotonic() >= deadline:
            raise TimeoutError("launch_deadline")
        source_frame = len(source_bytes).to_bytes(4, "big") + source_bytes
        if not _write_all(kernel32, control["stdin"], source_frame + launch_frame, deadline):
            raise ObserverError("launch_write_failed")
        return ObserverContext(
            kernel32=kernel32,
            control=control,
            request=request,
            journal_writer=journal_writer,
            stdout_state=stdout_state,
            stderr_state=stderr_state,
            drain_threads=drain_threads,
            absolute_started=started,
            absolute_deadline=deadline,
            cleanup_seconds=float(cleanup_seconds),
        )
    except BaseException as original_error:
        reaped = control is None
        if control is not None:
            try:
                _terminate_control(kernel32, control, 0xEE58)
            except Exception:
                pass
            try:
                reaped = _wait_process(kernel32, control["process"], 5000)
            except Exception:
                reaped = False
            for thread in drain_threads:
                thread.join(timeout=cleanup_seconds)
            runtime_handles = set(control.get("runtime_handles", ()))
            retained: list[int] = []
            for handle in list(control["handles"]):
                if handle in runtime_handles and not reaped:
                    retained.append(handle)
                    continue
                _close_handle(kernel32, control["handles"], handle)
            if retained:
                _ORPHANED_RUNTIME_HANDLE_SETS.append((kernel32, tuple(retained)))
                raise ObserverError("child_cleanup_unconfirmed") from original_error
        raise
