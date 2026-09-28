"""Bounded named-pipe output transport for inert I13/I15 child stages.

The fixed worker wrapper owns its v1 frame schema.  Internal service stages
share only the private bounded transport primitives; their exact role schemas
are validated by their own fixed adapters. A suspended child is bound to one
local first-instance pipe by its exact process ID and handle before resume.
No process handles cross the launch boundary.

This module is not registered as a runtime operation.  It carries one bounded
canonical JSON frame and grants no provider, account, or execution authority.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import secrets
import struct
import time
from ctypes import wintypes
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional


PIPE_NAME_PREFIX = r"\\.\pipe\Backtrader-I13-Readonly-Receipt-v1-"
WORKER_SCHEMA = "ctp_i13_i15_readonly_preflight_worker_output.v1"
FRAME_SCHEMA = "ctp_i13_i15_readonly_preflight_worker_frame.v1"
MAX_FRAME_BYTES = 64 * 1024
MAX_WORKER_OUTPUT_BYTES = 63 * 1024
FRAME_LENGTH_BYTES = 4
_PIPE_BUFFER_BYTES = 4096
_READ_BUFFER_BYTES = MAX_FRAME_BYTES + FRAME_LENGTH_BYTES + 1

_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_NONCE_RE = re.compile(r"[0-9a-f]{32}\Z")
_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,15}[0-9]+\Z")

_ERROR_BROKEN_PIPE = 109
_ERROR_IO_INCOMPLETE = 996
_ERROR_IO_PENDING = 997
_ERROR_OPERATION_ABORTED = 995
_ERROR_MORE_DATA = 234
_ERROR_NO_DATA = 232
_ERROR_PIPE_NOT_CONNECTED = 233
_ERROR_PIPE_CONNECTED = 535
_ERROR_PIPE_BUSY = 231
_ERROR_FILE_NOT_FOUND = 2
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_STILL_ACTIVE = 259
_DEFAULT_IO_DRAIN_SECONDS = 0.25
_TERMINAL_OVERLAPPED_ERRORS = frozenset(
    {
        _ERROR_OPERATION_ABORTED,
        _ERROR_BROKEN_PIPE,
        _ERROR_MORE_DATA,
        _ERROR_NO_DATA,
        _ERROR_PIPE_NOT_CONNECTED,
    }
)

_DUPLICATE_SAME_ACCESS = 0x00000002
_FILE_WRITE_DATA = 0x00000002
_FILE_READ_ATTRIBUTES = 0x00000080
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
_FILE_FLAG_OVERLAPPED = 0x40000000
_FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
_PIPE_ACCESS_INBOUND = 0x00000001
_PIPE_TYPE_MESSAGE = 0x00000004
_PIPE_READMODE_MESSAGE = 0x00000002
_PIPE_WAIT = 0x00000000
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_HANDLE_FLAG_INHERIT = 0x00000001

# An unresolved cancellation/close is not safely disposable: retain the
# instance, OVERLAPPED objects, events, and native handles in process custody.
_RETAINED_UNRESOLVED_CHANNELS: list[object] = []
# Kept as a compatibility alias for the constructor-failure contract tests.
_FAILED_CONSTRUCTOR_CHANNELS = _RETAINED_UNRESOLVED_CHANNELS


def _retain_unresolved_channel(channel: object) -> None:
    if not any(retained is channel for retained in _RETAINED_UNRESOLVED_CHANNELS):
        _RETAINED_UNRESOLVED_CHANNELS.append(channel)


def _release_retained_channel(channel: object) -> None:
    _RETAINED_UNRESOLVED_CHANNELS[:] = [
        retained for retained in _RETAINED_UNRESOLVED_CHANNELS if retained is not channel
    ]


class WorkerOutputChannelError(ValueError):
    """Redacted fail-closed transport or frame error."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason) is None:
            reason = "worker_output_channel_failed"
        self.reason = reason
        super().__init__(reason)


def _canonical_sid(sid: object) -> Optional[str]:
    """Return a canonical textual SID, rejecting ambiguous numeric spellings."""

    if type(sid) is not str or _SID_RE.fullmatch(sid) is None:
        return None
    parts = sid.split("-")[1:]
    if not 3 <= len(parts) <= 17 or parts[0] != "1":
        return None
    if any(len(part) > 15 or not part.isascii() or not part.isdigit() for part in parts):
        return None
    if any(part != str(int(part)) for part in parts):
        return None
    if int(parts[1]) > (1 << 48) - 1 or any(
        int(part) > (1 << 32) - 1 for part in parts[2:]
    ):
        return None
    return "S-" + "-".join(parts)


def _validate_worker_channel_sids(service_sid: object, client_sid: object) -> None:
    service = _canonical_sid(service_sid)
    client = _canonical_sid(client_sid)
    if service is None or client is None:
        raise WorkerOutputChannelError("worker_output_identity_invalid")
    if service == client:
        raise WorkerOutputChannelError("worker_output_identity_collision")


def _validate_service_stage_sid(service_sid: object) -> None:
    if _canonical_sid(service_sid) is None:
        raise WorkerOutputChannelError("worker_output_identity_invalid")


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except BaseException:
        raise WorkerOutputChannelError("worker_output_json_invalid") from None


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerOutputChannelError("worker_output_duplicate_key")
        result[key] = value
    return result


def _parse_canonical_object(raw: bytes, *, reason: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_FRAME_BYTES:
        raise WorkerOutputChannelError(reason)
    try:
        text = raw.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                WorkerOutputChannelError("worker_output_json_invalid")
            ),
        )
    except WorkerOutputChannelError:
        raise
    except BaseException:
        raise WorkerOutputChannelError(reason) from None
    if type(value) is not dict or _canonical_json(value) != raw:
        raise WorkerOutputChannelError(reason)
    return value


def _encode_frame(worker_output_raw: bytes, *, request_id: str, nonce: str) -> bytes:
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise WorkerOutputChannelError("worker_output_request_id_invalid")
    if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
        raise WorkerOutputChannelError("worker_output_nonce_invalid")
    if type(worker_output_raw) is not bytes or len(worker_output_raw) > MAX_WORKER_OUTPUT_BYTES:
        raise WorkerOutputChannelError("worker_output_limit_exceeded")
    worker_output = _parse_canonical_object(
        worker_output_raw, reason="worker_output_payload_invalid"
    )
    if worker_output.get("schema") != WORKER_SCHEMA:
        raise WorkerOutputChannelError("worker_output_schema_invalid")
    envelope = {
        "schema": FRAME_SCHEMA,
        "receipt_nonce": nonce,
        "request_id": request_id,
        "worker_output": worker_output,
    }
    payload = _canonical_json(envelope)
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise WorkerOutputChannelError("worker_output_limit_exceeded")
    return struct.pack(">I", len(payload)) + payload


def _decode_frame_payload(payload: bytes, *, request_id: str, nonce: str) -> bytes:
    envelope = _parse_canonical_object(payload, reason="worker_output_frame_invalid")
    if set(envelope) != {"schema", "receipt_nonce", "request_id", "worker_output"}:
        raise WorkerOutputChannelError("worker_output_frame_fields_invalid")
    if (
        envelope["schema"] != FRAME_SCHEMA
        or envelope["receipt_nonce"] != nonce
        or envelope["request_id"] != request_id
        or type(envelope["worker_output"]) is not dict
        or envelope["worker_output"].get("schema") != WORKER_SCHEMA
    ):
        raise WorkerOutputChannelError("worker_output_frame_binding_invalid")
    return _canonical_json(envelope["worker_output"])


def _decode_frame(frame: bytes, *, request_id: str, nonce: str) -> bytes:
    if type(frame) is not bytes or len(frame) < FRAME_LENGTH_BYTES:
        raise WorkerOutputChannelError("worker_output_frame_invalid")
    length = struct.unpack(">I", frame[:FRAME_LENGTH_BYTES])[0]
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise WorkerOutputChannelError("worker_output_limit_exceeded")
    if len(frame) != FRAME_LENGTH_BYTES + length:
        raise WorkerOutputChannelError("worker_output_frame_trailing_or_incomplete")
    return _decode_frame_payload(
        frame[FRAME_LENGTH_BYTES:], request_id=request_id, nonce=nonce
    )


def _validate_bounded_frame(frame: bytes) -> bytes:
    """Validate only framing/canonical JSON; role schemas stay in wrappers."""

    if type(frame) is not bytes or len(frame) < FRAME_LENGTH_BYTES:
        raise WorkerOutputChannelError("worker_output_frame_invalid")
    length = struct.unpack(">I", frame[:FRAME_LENGTH_BYTES])[0]
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise WorkerOutputChannelError("worker_output_limit_exceeded")
    if len(frame) != FRAME_LENGTH_BYTES + length:
        raise WorkerOutputChannelError("worker_output_frame_trailing_or_incomplete")
    _parse_canonical_object(frame[FRAME_LENGTH_BYTES:], reason="worker_output_frame_invalid")
    return frame


def _handle_value(value: object) -> int:
    try:
        if isinstance(value, ctypes.c_void_p):
            result = value.value
        else:
            result = int(value)  # ctypes HANDLE restype commonly returns an int.
    except BaseException:
        return 0
    return int(result or 0)


def _winerror(kernel32: Any) -> int:
    try:
        return int(ctypes.get_last_error())
    except BaseException:
        return 0


def _load_kernel32() -> Any:
    if os.name != "nt":
        raise WorkerOutputChannelError("windows_required")
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)
    except BaseException:
        raise WorkerOutputChannelError("worker_output_windows_api_unavailable") from None


def _service_security_attributes(
    kernel32: Any, *, service_sid: str, client_sid: str
) -> tuple[object, int]:
    _validate_worker_channel_sids(service_sid, client_sid)
    # Named-pipe client opens also require the read-attributes access bit for
    # this write-only endpoint.  Do not use GENERIC_WRITE: it includes
    # FILE_APPEND_DATA / FILE_CREATE_PIPE_INSTANCE (0x4).
    client_access = _FILE_WRITE_DATA | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    sddl = "D:P(A;;GA;;;SY)(A;;GA;;;{})(A;;0x{:08x};;;{})".format(
        service_sid, client_access, client_sid
    )
    descriptor = wintypes.LPVOID()
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    except BaseException:
        raise WorkerOutputChannelError("worker_output_windows_api_unavailable") from None
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.ULONG),
    ]
    convert.restype = wintypes.BOOL
    descriptor_size = wintypes.ULONG()
    if not convert(sddl, 1, ctypes.byref(descriptor), ctypes.byref(descriptor_size)):
        raise WorkerOutputChannelError("worker_output_acl_create_failed")

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    return attributes, _handle_value(descriptor)


def _service_stage_security_attributes(
    kernel32: Any, *, service_sid: str
) -> tuple[object, int]:
    """Build a service-only DACL for fixed same-service internal child stages."""

    _validate_service_stage_sid(service_sid)
    sddl = "D:P(A;;GA;;;SY)(A;;GA;;;{})".format(service_sid)
    descriptor = wintypes.LPVOID()
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    except BaseException:
        raise WorkerOutputChannelError("worker_output_windows_api_unavailable") from None
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.ULONG),
    ]
    convert.restype = wintypes.BOOL
    descriptor_size = wintypes.ULONG()
    if not convert(sddl, 1, ctypes.byref(descriptor), ctypes.byref(descriptor_size)):
        raise WorkerOutputChannelError("worker_output_acl_create_failed")

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    return attributes, _handle_value(descriptor)


def _free_security_descriptor(kernel32: Any, descriptor: int) -> bool:
    if not descriptor:
        return True
    try:
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        return not bool(local_free(wintypes.HLOCAL(descriptor)))
    except BaseException:
        return False


def _filetime_pair(value: object) -> tuple[int, int]:
    return int(value.dwHighDateTime), int(value.dwLowDateTime)


def _process_creation_time(kernel32: Any, process_handle: int) -> Optional[tuple[int, int]]:
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    get_times.restype = wintypes.BOOL
    if not get_times(
        wintypes.HANDLE(process_handle),
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        return None
    return _filetime_pair(creation)


def _process_id(kernel32: Any, process_handle: int) -> int:
    get_id = kernel32.GetProcessId
    get_id.argtypes = [wintypes.HANDLE]
    get_id.restype = wintypes.DWORD
    return int(get_id(wintypes.HANDLE(process_handle)))


def _close_handle(kernel32: Any, handle: Optional[int]) -> bool:
    if handle is None or handle <= 0:
        return True
    try:
        close = kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        return bool(close(wintypes.HANDLE(handle)))
    except BaseException:
        return False


def create_worker_output_channel(
    *, service_sid: str, client_sid: str
) -> "WorkerOutputChannel":
    """Create a worker-output endpoint with distinct service and owner SIDs."""

    _validate_worker_channel_sids(service_sid, client_sid)
    return _create_bounded_output_channel(service_sid=service_sid, client_sid=client_sid)


def create_service_stage_output_channel(*, service_sid: str) -> "WorkerOutputChannel":
    """Create a service-only endpoint for a fixed internal service-token stage."""

    _validate_service_stage_sid(service_sid)
    return _create_bounded_output_channel(service_sid=service_sid, client_sid=None)


def _create_bounded_output_channel(
    *, service_sid: str, client_sid: Optional[str]
) -> "_BoundedOutputChannel":
    """Create an internal bounded channel; callers own the typed frame parser."""

    nonce = secrets.token_hex(16)
    if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
        raise WorkerOutputChannelError("worker_output_nonce_unavailable")
    return _BoundedOutputChannel(
        service_sid=service_sid, client_sid=client_sid, nonce=nonce, max_bytes=MAX_FRAME_BYTES
    )


class _BoundedOutputChannel:
    """Internal one-frame transport bound to one suspended child process."""

    def __init__(
        self,
        *,
        service_sid: str,
        client_sid: Optional[str],
        nonce: str,
        max_bytes: int = MAX_FRAME_BYTES,
    ) -> None:
        if (
            type(nonce) is not str
            or _NONCE_RE.fullmatch(nonce) is None
            or type(max_bytes) is not int
            or max_bytes != MAX_FRAME_BYTES
        ):
            raise WorkerOutputChannelError("worker_output_channel_binding_invalid")
        if client_sid is None:
            _validate_service_stage_sid(service_sid)
        else:
            _validate_worker_channel_sids(service_sid, client_sid)
        self._kernel32 = _load_kernel32()
        self._winapi = self._load_winapi()
        self._nonce = nonce
        self._max_bytes = max_bytes
        self._pipe_name = PIPE_NAME_PREFIX + nonce
        self._service_sid = service_sid
        self._client_sid = client_sid
        self._pipe_handle: Optional[int] = None
        self._security_descriptor_handle: Optional[int] = None
        self._connect_overlapped: Any = None
        self._read_overlapped: Any = None
        self._worker_pid: Optional[int] = None
        self._worker_handle: Optional[int] = None
        self._worker_creation_time: Optional[tuple[int, int]] = None
        self._peer_pid: Optional[int] = None
        self._peer_handle: Optional[int] = None
        self._frame_message: Optional[bytes] = None
        self._supervision_poll_count = 0
        self._active_supervision_poll_count = 0
        self._frame_completed_while_worker_alive = False
        self._supervision_request_id: Optional[str] = None
        self._supervision_result: Any = None
        self._supervision_worker_identity: Optional[tuple[int, int, tuple[int, int]]] = None
        self._connected = False
        self._eof = False
        self._failure: Optional[str] = None
        self._deadline_monotonic: Optional[float] = None
        self._close_attempted = False
        self._close_deadline_missed = False
        self._closed = False
        self._server_pid = self._current_pid()
        try:
            self._create_server_pipe()
            self._begin_accept()
        except WorkerOutputChannelError:
            if not self.close():
                _FAILED_CONSTRUCTOR_CHANNELS.append(self)
                raise WorkerOutputChannelError(
                    "worker_output_constructor_cleanup_unconfirmed"
                ) from None
            raise
        except BaseException:
            if not self.close():
                _FAILED_CONSTRUCTOR_CHANNELS.append(self)
                raise WorkerOutputChannelError(
                    "worker_output_constructor_cleanup_unconfirmed"
                ) from None
            raise WorkerOutputChannelError("worker_output_constructor_failed") from None

    @staticmethod
    def _load_winapi() -> Any:
        if os.name != "nt":
            raise WorkerOutputChannelError("windows_required")
        try:
            import _winapi
        except BaseException:
            raise WorkerOutputChannelError("worker_output_overlapped_unavailable") from None
        return _winapi

    def _current_pid(self) -> int:
        get_pid = self._kernel32.GetCurrentProcessId
        get_pid.argtypes = []
        get_pid.restype = wintypes.DWORD
        value = int(get_pid())
        if value <= 0:
            raise WorkerOutputChannelError("worker_output_server_pid_unavailable")
        return value

    @property
    def bootstrap_binding(self) -> Mapping[str, object]:
        """Return only the nonce/PID pair for a fixed internal stage binding."""

        return MappingProxyType({"nonce": self._nonce, "server_pid": self._server_pid})

    process_output_binding = bootstrap_binding

    def _create_server_pipe(self) -> None:
        kernel32 = self._kernel32
        create_pipe = kernel32.CreateNamedPipeW
        create_pipe.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        create_pipe.restype = wintypes.HANDLE
        if self._client_sid is None:
            attributes, descriptor = _service_stage_security_attributes(
                kernel32, service_sid=self._service_sid
            )
        else:
            attributes, descriptor = _service_security_attributes(
                kernel32, service_sid=self._service_sid, client_sid=self._client_sid
            )
        self._security_descriptor_handle = descriptor
        try:
            handle = create_pipe(
                self._pipe_name,
                _PIPE_ACCESS_INBOUND
                | _FILE_FLAG_OVERLAPPED
                | _FILE_FLAG_FIRST_PIPE_INSTANCE,
                _PIPE_TYPE_MESSAGE | _PIPE_READMODE_MESSAGE | _PIPE_WAIT | _PIPE_REJECT_REMOTE_CLIENTS,
                1,
                0,
                _PIPE_BUFFER_BYTES,
                0,
                ctypes.byref(attributes),
            )
            value = _handle_value(handle)
            if value == 0 or value == ctypes.c_void_p(-1).value:
                raise WorkerOutputChannelError("worker_output_pipe_create_failed")
            self._pipe_handle = value
        finally:
            if not _free_security_descriptor(kernel32, descriptor):
                raise WorkerOutputChannelError("worker_output_acl_release_failed")
            self._security_descriptor_handle = None

    def _begin_accept(self) -> None:
        if self._pipe_handle is None:
            raise WorkerOutputChannelError("worker_output_pipe_unavailable")
        try:
            self._connect_overlapped = self._winapi.ConnectNamedPipe(
                self._pipe_handle, overlapped=True
            )
        except OSError as error:
            if getattr(error, "winerror", None) == _ERROR_PIPE_CONNECTED:
                self._connected = True
                self._authenticate_peer()
                self._begin_read()
                return
            raise WorkerOutputChannelError("worker_output_pipe_accept_failed") from None
        except BaseException:
            raise WorkerOutputChannelError("worker_output_pipe_accept_failed") from None

    def bind_suspended_process(self, process_id: int, process_handle: int) -> bool:
        """Bind the exact still-suspended, already-in-Job child identity once."""

        if (
            self._closed
            or self._failure is not None
            or self._worker_pid is not None
            or type(process_id) is not int
            or process_id <= 0
            or type(process_handle) is not int
            or process_handle <= 0
        ):
            return False
        kernel32 = self._kernel32
        try:
            if _process_id(kernel32, process_handle) != process_id:
                return False
            creation = _process_creation_time(kernel32, process_handle)
            if creation is None:
                return False
            if int(kernel32.WaitForSingleObject(wintypes.HANDLE(process_handle), 0)) != _WAIT_TIMEOUT:
                return False
            current_process = _handle_value(kernel32.GetCurrentProcess())
            duplicate = wintypes.HANDLE()
            duplicate_handle = kernel32.DuplicateHandle
            duplicate_handle.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.HANDLE),
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            duplicate_handle.restype = wintypes.BOOL
            desired = _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE
            if not duplicate_handle(
                wintypes.HANDLE(current_process),
                wintypes.HANDLE(process_handle),
                wintypes.HANDLE(current_process),
                ctypes.byref(duplicate),
                desired,
                False,
                0,
            ):
                return False
            duplicated = _handle_value(duplicate)
            if duplicated <= 0:
                return False
            set_flags = kernel32.SetHandleInformation
            set_flags.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
            set_flags.restype = wintypes.BOOL
            if not set_flags(wintypes.HANDLE(duplicated), _HANDLE_FLAG_INHERIT, 0):
                _close_handle(kernel32, duplicated)
                return False
            if (
                _process_id(kernel32, duplicated) != process_id
                or _process_creation_time(kernel32, duplicated) != creation
            ):
                _close_handle(kernel32, duplicated)
                return False
        except BaseException:
            return False
        self._worker_pid = process_id
        self._worker_handle = duplicated
        self._worker_creation_time = creation
        self._supervision_poll_count = 0
        self._active_supervision_poll_count = 0
        self._frame_completed_while_worker_alive = False
        return True

    bind_suspended_worker = bind_suspended_process

    def _authenticate_peer(self) -> None:
        if self._worker_pid is None or self._worker_handle is None:
            raise WorkerOutputChannelError("worker_output_process_not_bound")
        peer_pid = wintypes.DWORD()
        get_client_pid = self._kernel32.GetNamedPipeClientProcessId
        get_client_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        get_client_pid.restype = wintypes.BOOL
        if not get_client_pid(wintypes.HANDLE(self._pipe_handle), ctypes.byref(peer_pid)):
            raise WorkerOutputChannelError("worker_output_peer_pid_unavailable")
        actual_pid = int(peer_pid.value)
        if actual_pid <= 0 or actual_pid != self._worker_pid:
            raise WorkerOutputChannelError("worker_output_peer_pid_mismatch")
        open_process = self._kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        peer = _handle_value(
            open_process(
                _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE,
                False,
                actual_pid,
            )
        )
        if peer <= 0 or peer == ctypes.c_void_p(-1).value:
            raise WorkerOutputChannelError("worker_output_peer_process_unavailable")
        creation = _process_creation_time(self._kernel32, peer)
        lifetime = int(self._kernel32.WaitForSingleObject(wintypes.HANDLE(peer), 0))
        if (
            creation is None
            or creation != self._worker_creation_time
            or lifetime not in (_WAIT_TIMEOUT, _WAIT_OBJECT_0)
        ):
            _close_handle(self._kernel32, peer)
            raise WorkerOutputChannelError("worker_output_peer_process_identity_mismatch")
        self._peer_pid = actual_pid
        self._peer_handle = peer
        self._connected = True
        self._connect_overlapped = None
        self._begin_read()

    def _complete_overlapped(self, overlapped: Any) -> Optional[tuple[int, int]]:
        try:
            result = overlapped.GetOverlappedResult(False)
        except OSError as error:
            if getattr(error, "winerror", None) == _ERROR_IO_INCOMPLETE:
                return None
            if getattr(error, "winerror", None) == _ERROR_BROKEN_PIPE:
                return (0, _ERROR_BROKEN_PIPE)
            raise WorkerOutputChannelError("worker_output_overlapped_io_failed") from None
        except BaseException:
            raise WorkerOutputChannelError("worker_output_overlapped_io_failed") from None
        if type(result) is tuple and len(result) == 2:
            completed = int(result[1] or 0)
            if completed == _ERROR_IO_INCOMPLETE:
                return None
            return int(result[0]), completed
        if type(result) is int:
            return result, 0
        raise WorkerOutputChannelError("worker_output_overlapped_result_invalid")

    def _begin_read(self) -> None:
        if self._read_overlapped is not None or self._pipe_handle is None:
            raise WorkerOutputChannelError("worker_output_read_state_invalid")
        try:
            self._read_overlapped, error_code = self._winapi.ReadFile(
                self._pipe_handle,
                _READ_BUFFER_BYTES,
                overlapped=True,
            )
        except OSError as error:
            if getattr(error, "winerror", None) == _ERROR_BROKEN_PIPE:
                self._eof = True
                if self._frame_message is None:
                    self._failure = "worker_output_missing_frame"
                return
            raise WorkerOutputChannelError("worker_output_read_failed") from None
        except BaseException:
            raise WorkerOutputChannelError("worker_output_read_failed") from None
        if error_code not in (0, _ERROR_IO_PENDING):
            raise WorkerOutputChannelError("worker_output_read_failed")

    def _poll_connect(self) -> None:
        if self._connected or self._connect_overlapped is None:
            return
        result = self._complete_overlapped(self._connect_overlapped)
        if result is None:
            return
        if result[1] not in (0, _ERROR_PIPE_CONNECTED):
            raise WorkerOutputChannelError("worker_output_pipe_accept_failed")
        self._authenticate_peer()

    def _poll_read(self) -> None:
        if self._read_overlapped is None:
            return
        overlapped = self._read_overlapped
        result = self._complete_overlapped(overlapped)
        if result is None:
            return
        self._read_overlapped = None
        count, error_code = result
        if error_code == _ERROR_BROKEN_PIPE:
            self._eof = True
            if self._frame_message is None:
                self._failure = "worker_output_missing_frame"
            return
        if error_code == _ERROR_MORE_DATA:
            self._failure = "worker_output_limit_exceeded"
            return
        if error_code != 0 or type(count) is not int or count <= 0:
            self._failure = "worker_output_read_invalid"
            return
        maximum = self._max_bytes + FRAME_LENGTH_BYTES
        if count > maximum:
            self._failure = "worker_output_limit_exceeded"
            return
        try:
            raw = bytes(overlapped.getbuffer())[:count]
        except BaseException:
            self._failure = "worker_output_read_invalid"
            return
        if len(raw) != count:
            self._failure = "worker_output_read_invalid"
            return
        if self._frame_message is not None:
            self._failure = "worker_output_extra_frame"
            return
        self._frame_message = raw
        if self._worker_handle is not None:
            try:
                if int(
                    self._kernel32.WaitForSingleObject(
                        wintypes.HANDLE(self._worker_handle), 0
                    )
                ) == _WAIT_TIMEOUT:
                    self._frame_completed_while_worker_alive = True
            except BaseException:
                self._failure = "worker_output_process_lifetime_unavailable"
                return

    def _poll_eof_or_extra(self) -> None:
        if not self._connected or self._eof or self._frame_message is None:
            return
        available = wintypes.DWORD()
        total = wintypes.DWORD()
        peek = self._kernel32.PeekNamedPipe
        peek.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        peek.restype = wintypes.BOOL
        if not peek(
            wintypes.HANDLE(self._pipe_handle),
            None,
            0,
            None,
            ctypes.byref(available),
            ctypes.byref(total),
        ):
            if _winerror(self._kernel32) == _ERROR_BROKEN_PIPE:
                self._eof = True
                return
            self._failure = "worker_output_pipe_peek_failed"
            return
        if int(available.value) > 0:
            self._failure = "worker_output_extra_frame"

    def poll_abort_reason(self) -> Optional[str]:
        """Advance overlapped accept/read and drain the bounded message."""

        if self._closed:
            return "worker_output_channel_closed"
        if self._failure is not None:
            return self._failure
        if self._worker_handle is not None:
            self._supervision_poll_count += 1
            try:
                if int(
                    self._kernel32.WaitForSingleObject(
                        wintypes.HANDLE(self._worker_handle), 0
                    )
                ) == _WAIT_TIMEOUT:
                    self._active_supervision_poll_count += 1
            except BaseException:
                self._failure = "worker_output_process_lifetime_unavailable"
                return self._failure
        try:
            self._poll_connect()
            if self._connected:
                self._poll_read()
                self._poll_eof_or_extra()
        except WorkerOutputChannelError as error:
            self._failure = error.reason
        except BaseException:
            self._failure = "worker_output_poll_failed"
        return self._failure

    def _outer_result_is_complete(self, result: object, *, request_id: str) -> bool:
        from .ctp_i13_i15_outer_watchdog import OuterProcessEvidence, OuterWatchdogResult

        if (
            type(result) is not OuterWatchdogResult
            or type(getattr(result, "evidence", None)) is not OuterProcessEvidence
            or result is not self._supervision_result
            or request_id != self._supervision_request_id
            or self._worker_pid is None
            or self._worker_handle is None
            or self._worker_creation_time is None
            or self._supervision_worker_identity
            != (self._worker_pid, self._worker_handle, self._worker_creation_time)
        ):
            return False
        evidence = getattr(result, "evidence", None)
        return bool(
            getattr(result, "state", None) == "exited"
            and getattr(result, "reason", None) == "launcher_exited_job_empty"
            and getattr(evidence, "process_created", None) is True
            and getattr(evidence, "job_assignment_observed", None) is True
            and getattr(evidence, "launcher_resumed", None) is True
            and getattr(evidence, "launcher_exit_observed", None) is True
            and type(getattr(evidence, "launcher_exit_code", None)) is int
            and getattr(evidence, "job_termination_requested", None) is False
            and getattr(evidence, "job_empty_observed", None) is True
            and getattr(evidence, "containment", None) == "verified"
            and getattr(evidence, "controls_retained", None) is False
        )

    def read_frame_after_job_empty(
        self,
        *,
        request_id: str,
        outer_result: object,
        deadline_monotonic: float,
        monotonic=time.monotonic,
    ) -> bytes:
        """Return one bounded canonical frame after verified process/Job completion.

        This transport method deliberately does not select a payload schema.
        Fixed worker/coordinator/receipt-writer adapters validate their own
        exact frame schema after this process and EOF check. The returned
        bytes are the canonical JSON frame body, without the four-byte length
        prefix; role parsers validate their own outer envelope binding.
        """

        if not self._outer_result_is_complete(outer_result, request_id=request_id):
            raise WorkerOutputChannelError("worker_output_job_empty_unverified")
        if self._closed or self._close_attempted:
            raise WorkerOutputChannelError("worker_output_channel_closed")
        if self._supervision_poll_count <= 0:
            raise WorkerOutputChannelError("worker_output_drain_unobserved")
        if (
            type(request_id) is not str
            or _REQUEST_ID_RE.fullmatch(request_id) is None
            or type(deadline_monotonic) not in (int, float)
            or not callable(monotonic)
        ):
            raise WorkerOutputChannelError("worker_output_read_binding_invalid")
        try:
            deadline = float(deadline_monotonic)
            if not math.isfinite(deadline):
                raise OverflowError
        except BaseException:
            raise WorkerOutputChannelError("worker_output_deadline_invalid") from None
        bound_deadline = getattr(self, "_deadline_monotonic", None)
        if bound_deadline is not None and float(bound_deadline) != deadline:
            raise WorkerOutputChannelError("worker_output_deadline_mismatch")
        self._deadline_monotonic = deadline
        if self._failure is not None:
            raise WorkerOutputChannelError(self._failure)
        while not self._eof:
            try:
                if float(monotonic()) >= deadline:
                    raise WorkerOutputChannelError("worker_output_deadline_exceeded")
            except WorkerOutputChannelError:
                raise
            except BaseException:
                raise WorkerOutputChannelError("worker_output_clock_invalid") from None
            reason = self.poll_abort_reason()
            if reason is not None:
                raise WorkerOutputChannelError(reason)
            if not self._eof:
                time.sleep(min(0.001, max(0.0, deadline - float(monotonic()))))
        if self._failure is not None:
            raise WorkerOutputChannelError(self._failure)
        if self._frame_message is None:
            raise WorkerOutputChannelError("worker_output_missing_frame")
        if self._worker_handle is None or self._peer_handle is None:
            raise WorkerOutputChannelError("worker_output_process_identity_missing")
        if (
            _process_id(self._kernel32, self._worker_handle) != self._worker_pid
            or _process_id(self._kernel32, self._peer_handle) != self._peer_pid
            or _process_creation_time(self._kernel32, self._worker_handle)
            != self._worker_creation_time
            or _process_creation_time(self._kernel32, self._peer_handle)
            != self._worker_creation_time
            or self._worker_pid != self._peer_pid
        ):
            raise WorkerOutputChannelError("worker_output_process_identity_changed")
        try:
            worker_exit = int(
                self._kernel32.WaitForSingleObject(
                    wintypes.HANDLE(self._worker_handle), 0
                )
            )
        except BaseException:
            raise WorkerOutputChannelError("worker_output_process_exit_unobserved") from None
        if worker_exit != _WAIT_OBJECT_0:
            raise WorkerOutputChannelError("worker_output_process_exit_unobserved")
        frame = _validate_bounded_frame(self._frame_message)
        if not self.close(deadline_monotonic=deadline, monotonic=monotonic):
            raise WorkerOutputChannelError("worker_output_channel_close_unconfirmed")
        try:
            if float(monotonic()) >= deadline:
                raise WorkerOutputChannelError("worker_output_deadline_exceeded")
        except WorkerOutputChannelError:
            raise
        except BaseException:
            raise WorkerOutputChannelError("worker_output_clock_invalid") from None
        return frame[FRAME_LENGTH_BYTES:]

    def read_after_job_empty(
        self,
        *,
        request_id: str,
        outer_result: object,
        deadline_monotonic: float,
        monotonic=time.monotonic,
    ) -> bytes:
        """Worker-specific adapter preserving the locked worker JSON schema."""

        if (
            not self._outer_result_is_complete(outer_result, request_id=request_id)
            or outer_result.evidence.launcher_exit_code != 0
        ):
            raise WorkerOutputChannelError("worker_output_worker_exit_unaccepted")

        frame = self.read_frame_after_job_empty(
            request_id=request_id,
            outer_result=outer_result,
            deadline_monotonic=deadline_monotonic,
            monotonic=monotonic,
        )
        return _decode_frame_payload(frame, request_id=request_id, nonce=self._nonce)

    def _consume_overlapped_completion(
        self,
        overlapped: Any,
        *,
        deadline_monotonic: float,
        monotonic: Callable[[], float],
    ) -> bool:
        """Wait for and consume one final completion without extending D."""

        while True:
            try:
                result = overlapped.GetOverlappedResult(False)
            except OSError as error:
                error_code = getattr(error, "winerror", None)
                if type(error_code) is not int:
                    return False
                if error_code != _ERROR_IO_INCOMPLETE:
                    # Accept only known terminal statuses for this pipe
                    # transport. An invalid handle or unknown API error is not
                    # enough evidence to release the OVERLAPPED storage.
                    return error_code in _TERMINAL_OVERLAPPED_ERRORS
            except BaseException:
                return False
            else:
                if type(result) is int:
                    return True
                if type(result) is not tuple or len(result) != 2:
                    return False
                if type(result[1]) is not int:
                    return False
                if result[1] == 0 or result[1] in _TERMINAL_OVERLAPPED_ERRORS:
                    return True
                if result[1] != _ERROR_IO_INCOMPLETE:
                    return False

            try:
                current = float(monotonic())
            except BaseException:
                return False
            if not math.isfinite(current) or current >= deadline_monotonic:
                return False
            event_handle = _handle_value(getattr(overlapped, "event", None))
            if event_handle <= 0:
                return False
            remaining_ms = max(
                1, min(600_000, math.ceil((deadline_monotonic - current) * 1000.0))
            )
            try:
                wait = self._kernel32.WaitForSingleObject
                wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                wait.restype = wintypes.DWORD
                wait_result = int(wait(wintypes.HANDLE(event_handle), remaining_ms))
            except BaseException:
                return False
            if wait_result == _WAIT_TIMEOUT:
                continue
            if wait_result != _WAIT_OBJECT_0:
                return False

    def close(
        self,
        *,
        deadline_monotonic: Optional[float] = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> bool:
        """Cancel I/O, consume final completions, then close owned handles.

        A caller-supplied absolute deadline is never restarted. Before a run
        has bound a request deadline, constructor cleanup gets only a short
        local drain window. If completion or close is uncertain, this object
        remains globally retained with its OVERLAPPED/event/handle custody.
        """

        if self._closed:
            return True
        if getattr(self, "_close_deadline_missed", False):
            _retain_unresolved_channel(self)
            return False
        self._close_attempted = True
        if deadline_monotonic is None:
            deadline_monotonic = getattr(self, "_deadline_monotonic", None)
        bound_deadline = getattr(self, "_deadline_monotonic", None)
        try:
            if deadline_monotonic is None:
                deadline = float(monotonic()) + _DEFAULT_IO_DRAIN_SECONDS
            else:
                if type(deadline_monotonic) not in (int, float):
                    raise ValueError
                deadline = float(deadline_monotonic)
            if not math.isfinite(deadline) or not callable(monotonic):
                raise ValueError
            if bound_deadline is not None and deadline != float(bound_deadline):
                raise ValueError
        except BaseException:
            _retain_unresolved_channel(self)
            return False

        def still_before_deadline() -> bool:
            try:
                current = float(monotonic())
            except BaseException:
                return False
            return math.isfinite(current) and current < deadline

        if not still_before_deadline():
            self._close_deadline_missed = True
            _retain_unresolved_channel(self)
            return False

        pipe_handle = getattr(self, "_pipe_handle", None)
        if pipe_handle is not None:
            try:
                cancel = self._kernel32.CancelIoEx
                cancel.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
                cancel.restype = wintypes.BOOL
                if not cancel(wintypes.HANDLE(pipe_handle), None):
                    _winerror(self._kernel32)
                # Neither ERROR_NOT_FOUND nor another CancelIoEx error proves
                # that an OVERLAPPED result was consumed. The per-operation
                # GetOverlappedResult checks below decide.
            except BaseException:
                # Cancellation failure is fail-closed unless the exact
                # operation independently reaches a consumed completion.
                pass
        if not still_before_deadline():
            self._close_deadline_missed = True
            _retain_unresolved_channel(self)
            return False

        for name in ("_connect_overlapped", "_read_overlapped"):
            overlapped = getattr(self, name, None)
            if overlapped is None:
                continue
            if not self._consume_overlapped_completion(
                overlapped,
                deadline_monotonic=deadline,
                monotonic=monotonic,
            ):
                if not still_before_deadline():
                    self._close_deadline_missed = True
                _retain_unresolved_channel(self)
                return False
            setattr(self, name, None)
            if not still_before_deadline():
                self._close_deadline_missed = True
                _retain_unresolved_channel(self)
                return False

        ok = True
        if getattr(self, "_security_descriptor_handle", None) is not None:
            if not still_before_deadline():
                self._close_deadline_missed = True
                _retain_unresolved_channel(self)
                return False
            descriptor = self._security_descriptor_handle
            if _free_security_descriptor(self._kernel32, descriptor):
                self._security_descriptor_handle = None
            else:
                ok = False
            if not still_before_deadline():
                self._close_deadline_missed = True
                _retain_unresolved_channel(self)
                return False

        for name in ("_peer_handle", "_worker_handle", "_pipe_handle"):
            handle = getattr(self, name, None)
            if handle is None:
                continue
            if not still_before_deadline():
                self._close_deadline_missed = True
                _retain_unresolved_channel(self)
                return False
            if _close_handle(self._kernel32, handle):
                setattr(self, name, None)
            else:
                ok = False
            if not still_before_deadline():
                self._close_deadline_missed = True
                _retain_unresolved_channel(self)
                return False

        if ok:
            self._closed = True
            _release_retained_channel(self)
            return True
        _retain_unresolved_channel(self)
        return False


def _write_bounded_frame(
    raw_frame: bytes,
    *,
    nonce: str,
    expected_server_pid: int,
    deadline_monotonic_ns: int,
) -> None:
    """Write one prebuilt canonical frame; typed adapters own its schema."""

    if os.name != "nt":
        raise WorkerOutputChannelError("windows_required")
    if (
        type(nonce) is not str
        or _NONCE_RE.fullmatch(nonce) is None
        or type(expected_server_pid) is not int
        or expected_server_pid <= 0
        or type(deadline_monotonic_ns) is not int
        or deadline_monotonic_ns <= 0
    ):
        raise WorkerOutputChannelError("worker_output_client_binding_invalid")
    _validate_bounded_frame(raw_frame)
    kernel32 = _load_kernel32()
    pipe_name = PIPE_NAME_PREFIX + nonce
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = 0
    while handle <= 0 or handle == ctypes.c_void_p(-1).value:
        remaining_ns = deadline_monotonic_ns - time.monotonic_ns()
        if remaining_ns <= 0:
            raise WorkerOutputChannelError("worker_output_connect_deadline_exceeded")
        opened = create_file(
            pipe_name,
            _FILE_WRITE_DATA | _SYNCHRONIZE,
            0,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OVERLAPPED,
            None,
        )
        handle = _handle_value(opened)
        if handle > 0 and handle != ctypes.c_void_p(-1).value:
            break
        code = _winerror(kernel32)
        if code not in (_ERROR_PIPE_BUSY, _ERROR_FILE_NOT_FOUND):
            raise WorkerOutputChannelError("worker_output_connect_failed")
        remaining_ms = max(1, min(100, math.ceil(remaining_ns / 1_000_000)))
        wait_named_pipe = kernel32.WaitNamedPipeW
        wait_named_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        wait_named_pipe.restype = wintypes.BOOL
        if not wait_named_pipe(pipe_name, remaining_ms):
            code = _winerror(kernel32)
            if code not in (_ERROR_PIPE_BUSY, _ERROR_FILE_NOT_FOUND, 121):
                raise WorkerOutputChannelError("worker_output_connect_failed")

    try:
        server_pid = wintypes.DWORD()
        get_server_pid = kernel32.GetNamedPipeServerProcessId
        get_server_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        get_server_pid.restype = wintypes.BOOL
        if not get_server_pid(wintypes.HANDLE(handle), ctypes.byref(server_pid)):
            raise WorkerOutputChannelError("worker_output_server_pid_unavailable")
        if int(server_pid.value) != expected_server_pid:
            raise WorkerOutputChannelError("worker_output_server_pid_mismatch")
        try:
            import _winapi

            overlapped, error_code = _winapi.WriteFile(
                handle, raw_frame, overlapped=True
            )
        except BaseException:
            raise WorkerOutputChannelError("worker_output_write_failed") from None
        if error_code not in (0, _ERROR_IO_PENDING):
            raise WorkerOutputChannelError("worker_output_write_failed")
        if error_code == _ERROR_IO_PENDING:
            remaining_ns = deadline_monotonic_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                try:
                    overlapped.cancel()
                except BaseException:
                    pass
                raise WorkerOutputChannelError("worker_output_write_deadline_exceeded")
            timeout_ms = max(1, min(600_000, math.ceil(remaining_ns / 1_000_000)))
            try:
                wait = _winapi.WaitForMultipleObjects(
                    [overlapped.event], False, timeout_ms
                )
            except BaseException:
                try:
                    overlapped.cancel()
                except BaseException:
                    pass
                raise WorkerOutputChannelError("worker_output_write_wait_failed") from None
            if wait == 0x102:
                try:
                    overlapped.cancel()
                except BaseException:
                    pass
                raise WorkerOutputChannelError("worker_output_write_deadline_exceeded")
            if wait != _WAIT_OBJECT_0:
                try:
                    overlapped.cancel()
                except BaseException:
                    pass
                raise WorkerOutputChannelError("worker_output_write_wait_failed")
            try:
                written, final_error = overlapped.GetOverlappedResult(True)
            except BaseException:
                raise WorkerOutputChannelError("worker_output_write_failed") from None
        else:
            try:
                written, final_error = overlapped.GetOverlappedResult(False)
            except BaseException:
                raise WorkerOutputChannelError("worker_output_write_failed") from None
        if final_error or written != len(raw_frame):
            raise WorkerOutputChannelError("worker_output_short_write")
    finally:
        if not _close_handle(kernel32, handle):
            raise WorkerOutputChannelError("worker_output_client_handle_close_failed")


def run_child_with_output_channel(
    channel: "WorkerOutputChannel",
    command: object,
    *,
    backend: object,
    request_id: str,
    deadline_monotonic: float,
    stop_deadline_monotonic: Optional[float] = None,
    after_resume: Optional[Callable[[], Optional[str]]] = None,
) -> object:
    """Run one fixed child with this channel's drain poll wired unconditionally.

    The worker may block while sending a message larger than the pipe's kernel
    buffer.  The outer loop must therefore poll this channel while the child is
    still in its Job.  Callers cannot replace or omit that callback through
    this wrapper.  The returned frame remains untrusted until the separate
    ``read_frame_after_job_empty`` check validates completed Job cleanup.
    ``after_resume`` is a code-owned local callback, never wire data; the
    watchdog invokes it once after confirmed resume and before its first poll.
    Callers must bound any callback I/O by the same absolute deadline.
    """

    if type(channel) is not _BoundedOutputChannel:
        raise WorkerOutputChannelError("worker_output_channel_required")
    if (
        type(request_id) is not str
        or _REQUEST_ID_RE.fullmatch(request_id) is None
        or channel._supervision_result is not None
        or channel._supervision_request_id is not None
    ):
        raise WorkerOutputChannelError("worker_output_run_binding_invalid")
    if (
        type(deadline_monotonic) not in (int, float)
        or not math.isfinite(float(deadline_monotonic))
    ):
        raise WorkerOutputChannelError("worker_output_deadline_invalid")
    from . import ctp_i13_i15_outer_watchdog
    from .ctp_i13_i15_outer_watchdog import OuterWatchdogResult

    channel._supervision_request_id = request_id
    channel._deadline_monotonic = float(deadline_monotonic)
    result = ctp_i13_i15_outer_watchdog.run_outer_watchdog(
        command,
        backend=backend,
        deadline_monotonic=deadline_monotonic,
        stop_deadline_monotonic=stop_deadline_monotonic,
        abort_requested=channel.poll_abort_reason,
        after_resume=after_resume,
    )
    if type(result) is not OuterWatchdogResult:
        channel._failure = "worker_output_outer_result_invalid"
        raise WorkerOutputChannelError("worker_output_outer_result_invalid")
    if (
        channel._worker_pid is None
        or channel._worker_handle is None
        or channel._worker_creation_time is None
    ):
        channel._failure = "worker_output_process_not_bound"
        raise WorkerOutputChannelError("worker_output_process_not_bound")
    channel._supervision_worker_identity = (
        channel._worker_pid,
        channel._worker_handle,
        channel._worker_creation_time,
    )
    channel._supervision_result = result
    return result


def write_worker_output_frame(
    worker_output_raw: bytes,
    *,
    request_id: str,
    nonce: str,
    expected_server_pid: int,
    deadline_monotonic_ns: int,
) -> None:
    """Send one exact worker-v1 frame to its nonce-derived local pipe."""

    frame = _encode_frame(worker_output_raw, request_id=request_id, nonce=nonce)
    _write_bounded_frame(
        frame,
        nonce=nonce,
        expected_server_pid=expected_server_pid,
        deadline_monotonic_ns=deadline_monotonic_ns,
    )


# Historical worker-facing name retained for the fixed worker wrapper.
WorkerOutputChannel = _BoundedOutputChannel


__all__ = [
    "FRAME_SCHEMA",
    "MAX_FRAME_BYTES",
    "MAX_WORKER_OUTPUT_BYTES",
    "PIPE_NAME_PREFIX",
    "WORKER_SCHEMA",
    "WorkerOutputChannel",
    "WorkerOutputChannelError",
    "create_service_stage_output_channel",
    "create_worker_output_channel",
    "run_child_with_output_channel",
    "write_worker_output_frame",
]
