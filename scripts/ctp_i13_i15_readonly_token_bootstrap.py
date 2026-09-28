"""Token bootstrap for the fixed service-token coordinator role.

The remote token handle is transferred only over the one-shot service-only
control pipe after the supervisor has authenticated the original pipe client.
The coordinator re-queries the token before changing only TokenSessionId to
the code-owned noninteractive session 0. The concrete no-argument Win32
adapter is only for the fixed coordinator role.
"""

from __future__ import annotations

import json
import ctypes
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from ctypes import wintypes
from types import MappingProxyType
from typing import Mapping, Protocol


TOKEN_BOOTSTRAP_SCHEMA = "ctp_i13_i15_readonly_token_bootstrap.v1"
_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,14}[0-9]+\Z")
_FRAME_FIELDS = frozenset(
    {
        "schema",
        "request_id",
        "nonce",
        "remote_primary_token_handle",
        "owner_sid",
        "authentication_id",
        "source_session_id",
        "token_facts_sha256",
    }
)
_AUTHENTICATION_ID_FIELDS = frozenset({"high", "low"})
_TOKEN_FACT_FIELDS = frozenset(
    {"token_type", "user_sid", "authentication_id", "session_id", "stable_facts_sha256"}
)
_TOKEN_BOOTSTRAP_PIPE_PREFIX = r"\\.\pipe\Backtrader-I13-Readonly-Token-v1-"
_TOKEN_BOOTSTRAP_MAX_FRAME = 4096
_TOKEN_ADJUST_PRIVILEGES = 0x0020
_TOKEN_ADJUST_SESSIONID = 0x0100
_TOKEN_QUERY = 0x0008
_ERROR_NOT_ALL_ASSIGNED = 1300
_SE_PRIVILEGE_ENABLED = 0x00000002
_TOKEN_INFORMATION = {
    "user": 1,
    "groups": 2,
    "owner": 4,
    "primary_group": 5,
    "privileges": 3,
    "type": 8,
    "statistics": 10,
    "restricted_sids": 11,
    "session_id": 12,
    "elevation_type": 18,
    "has_restrictions": 21,
    "integrity": 25,
    "mandatory_policy": 27,
    "is_app_container": 29,
    "app_container_sid": 31,
    "virtualization_enabled": 24,
    "ui_access": 26,
}
_DUPLICATE_SAME_ACCESS = 0x00000002
_PROCESS_DUP_HANDLE = 0x00000040
_PIPE_READ_DATA = 0x00000001
_PIPE_READ_ATTRIBUTES = 0x00000080
_PIPE_READ_CONTROL = 0x00020000
_PIPE_SYNCHRONIZE = 0x00100000
_FILE_FLAG_OVERLAPPED = 0x40000000
_OPEN_EXISTING = 3
_ERROR_IO_PENDING = 997
_ERROR_BROKEN_PIPE = 109
_WAIT_OBJECT_0 = 0


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TOKEN_GROUPS_ONE(ctypes.Structure):
    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", _SID_AND_ATTRIBUTES * 1)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", wintypes.DWORD)]


class _TOKEN_PRIVILEGES_ONE(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", _LUID_AND_ATTRIBUTES * 1)]


class _TOKEN_STATISTICS(ctypes.Structure):
    _fields_ = [
        ("TokenId", _LUID),
        ("AuthenticationId", _LUID),
        ("ExpirationTime", ctypes.c_longlong),
        ("TokenType", wintypes.DWORD),
        ("ImpersonationLevel", wintypes.DWORD),
        ("DynamicCharged", wintypes.DWORD),
        ("DynamicAvailable", wintypes.DWORD),
        ("GroupCount", wintypes.DWORD),
        ("PrivilegeCount", wintypes.DWORD),
        ("ModifiedId", _LUID),
    ]


class _TOKEN_PRIVILEGES_BUFFER(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privilege", _LUID_AND_ATTRIBUTES)]


@dataclass
class _SeTcbRestoreState:
    token_handle: int
    previous_state: bytes
    previous_size: int
    _closed: bool = False


@dataclass(frozen=True)
class _TokenInformationBuffer:
    """A live GetTokenInformation allocation and its initialized byte count.

    Several TOKEN_* structures contain absolute pointers into the allocation.
    Keeping the ctypes allocation here is part of the pointer-validity proof;
    copying ``buffer.raw`` would leave those pointers referring to freed memory.
    """

    storage: object
    length: int

    @property
    def address(self) -> int:
        return int(ctypes.addressof(self.storage))

    @property
    def end(self) -> int:
        return self.address + self.length

    def read(self, offset: int, length: int) -> bytes:
        if (
            type(offset) is not int
            or type(length) is not int
            or offset < 0
            or length < 0
            or offset > self.length
            or length > self.length - offset
        ):
            raise TokenBootstrapError("token_buffer_range_invalid")
        return ctypes.string_at(self.address + offset, length)


class TokenBootstrapError(ValueError):
    """A fixed, non-sensitive token bootstrap rejection."""


class FatalPrivilegeRestore(BaseException):
    """Raised only if fail-stop termination unexpectedly returns in tests."""


@dataclass(frozen=True)
class OwnerTokenTransfer:
    request_id: str
    nonce: str
    remote_primary_token_handle: int
    owner_sid: str
    authentication_id: tuple[int, int]
    source_session_id: int
    token_facts_sha256: str


@dataclass(frozen=True)
class TokenSessionFacts:
    owner_sid: str
    authentication_id: tuple[int, int]
    source_session_id: int
    target_session_id: int
    stable_facts_sha256: str


class TokenSessionApi(Protocol):
    """Narrow process-local token operations supplied by the fixed bootstrap."""

    def query_token_facts(self, token_handle: int) -> Mapping[str, object]: ...

    def enable_se_tcb_privilege(self) -> object: ...

    def set_token_session_id(self, token_handle: int, session_id: int) -> None: ...

    def restore_se_tcb_privilege(self, previous_state: object) -> None: ...

    def fail_stop_current_process(self, reason: str) -> None: ...


class WindowsTokenSessionApi:
    """Concrete coordinator-only Win32 token adapter.

    The public constructor has no arguments.  Tests exercise the pure parsing
    and call-order seams; production APIs always come from the current
    protected process.  This object is intended for one disposable coordinator
    process before it starts any worker threads.
    """

    def __init__(self) -> None:
        if os.name != "nt":
            raise TokenBootstrapError("windows_required")
        try:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        except BaseException:
            raise TokenBootstrapError("token_api_unavailable") from None

    @staticmethod
    def _handle(token_handle: object) -> int:
        if type(token_handle) is not int or token_handle <= 0:
            raise TokenBootstrapError("token_handle_invalid")
        return token_handle

    def _get_information(
        self, token_handle: int, information_class: int
    ) -> _TokenInformationBuffer:
        get_info = self._advapi32.GetTokenInformation
        get_info.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_info.restype = wintypes.BOOL
        required = wintypes.DWORD()
        ctypes.set_last_error(0)
        get_info(
            wintypes.HANDLE(token_handle),
            information_class,
            None,
            0,
            ctypes.byref(required),
        )
        if not required.value or required.value > 1024 * 1024:
            raise TokenBootstrapError("token_query_failed")
        buffer = ctypes.create_string_buffer(required.value)
        returned = wintypes.DWORD()
        if (
            not get_info(
                wintypes.HANDLE(token_handle),
                information_class,
                ctypes.cast(buffer, wintypes.LPVOID),
                required.value,
                ctypes.byref(returned),
            )
            or not returned.value
            or returned.value > required.value
        ):
            raise TokenBootstrapError("token_query_failed")
        return _TokenInformationBuffer(buffer, int(returned.value))

    def _sid_string(self, sid_pointer: object, information: _TokenInformationBuffer) -> str:
        pointer = ctypes.cast(sid_pointer, ctypes.c_void_p).value if sid_pointer else None
        if (
            type(information) is not _TokenInformationBuffer
            or not pointer
            or pointer < information.address
            or pointer > information.end - 8
        ):
            raise TokenBootstrapError("token_sid_invalid")
        # SID is {revision, subauthority_count, identifier_authority[6],
        # subauthority[count]}. Read the fixed header only after its complete
        # range is proven to lie inside the live GetTokenInformation buffer.
        header = information.read(pointer - information.address, 8)
        revision, subauthority_count = header[0], header[1]
        if revision != 1 or subauthority_count > 15:
            raise TokenBootstrapError("token_sid_invalid")
        sid_length = 8 + 4 * subauthority_count
        if pointer > information.end - sid_length:
            raise TokenBootstrapError("token_sid_invalid")
        sid = information.read(pointer - information.address, sid_length)
        authority = int.from_bytes(sid[2:8], "big", signed=False)
        subauthorities = [
            str(int.from_bytes(sid[8 + index * 4 : 12 + index * 4], "little", signed=False))
            for index in range(subauthority_count)
        ]
        value = "S-{}-{}".format(revision, authority)
        if subauthorities:
            value += "-" + "-".join(subauthorities)
        if _SID_RE.fullmatch(value) is None:
            raise TokenBootstrapError("token_sid_invalid")
        return value

    def _sid_and_attributes(self, token_handle: int, information_class: int) -> list[list[object]]:
        information = self._get_information(token_handle, information_class)
        if information.length < _TOKEN_GROUPS_ONE.Groups.offset:
            raise TokenBootstrapError("token_group_facts_invalid")
        header = ctypes.cast(information.address, ctypes.POINTER(_TOKEN_GROUPS_ONE)).contents
        offset = _TOKEN_GROUPS_ONE.Groups.offset
        count = int(header.GroupCount)
        available = (information.length - offset) // ctypes.sizeof(_SID_AND_ATTRIBUTES)
        if count > available:
            raise TokenBootstrapError("token_group_facts_invalid")
        result = []
        if count:
            entries = ctypes.cast(
                information.address + offset,
                ctypes.POINTER(_SID_AND_ATTRIBUTES * count),
            ).contents
            for index in range(count):
                entry = entries[index]
                result.append([self._sid_string(entry.Sid, information), int(entry.Attributes)])
        result.sort(key=lambda item: (item[0], item[1]))
        return result

    def _single_sid(self, token_handle: int, information_class: int) -> str:
        information = self._get_information(token_handle, information_class)
        pointer_size = ctypes.sizeof(wintypes.LPVOID)
        if information.length < pointer_size:
            raise TokenBootstrapError("token_sid_invalid")
        pointer = ctypes.cast(information.address, ctypes.POINTER(wintypes.LPVOID)).contents
        return self._sid_string(pointer, information)

    def _single_sid_and_attributes(self, token_handle: int, information_class: int) -> list[object]:
        information = self._get_information(token_handle, information_class)
        if information.length < ctypes.sizeof(_SID_AND_ATTRIBUTES):
            raise TokenBootstrapError("token_group_facts_invalid")
        value = ctypes.cast(information.address, ctypes.POINTER(_SID_AND_ATTRIBUTES)).contents
        return [self._sid_string(value.Sid, information), int(value.Attributes)]

    def _privileges(self, token_handle: int) -> list[list[int]]:
        information = self._get_information(token_handle, _TOKEN_INFORMATION["privileges"])
        offset = _TOKEN_PRIVILEGES_ONE.Privileges.offset
        if information.length < offset:
            raise TokenBootstrapError("token_privilege_facts_invalid")
        header = ctypes.cast(information.address, ctypes.POINTER(_TOKEN_PRIVILEGES_ONE)).contents
        count = int(header.PrivilegeCount)
        available = (information.length - offset) // ctypes.sizeof(_LUID_AND_ATTRIBUTES)
        if count > available:
            raise TokenBootstrapError("token_privilege_facts_invalid")
        result = []
        if count:
            entries = ctypes.cast(
                information.address + offset,
                ctypes.POINTER(_LUID_AND_ATTRIBUTES * count),
            ).contents
            for index in range(count):
                item = entries[index]
                high = int(item.Luid.HighPart) & 0xFFFFFFFF
                low = int(item.Luid.LowPart)
                result.append([high, low, int(item.Attributes)])
        result.sort()
        return result

    def _scalar(self, token_handle: int, information_class: int, *, kind: str) -> object:
        information = self._get_information(token_handle, information_class)
        if kind == "bool":
            if information.length == 1:
                value = information.read(0, 1)[0]
            elif information.length == ctypes.sizeof(wintypes.DWORD):
                value = wintypes.DWORD.from_buffer_copy(
                    information.read(0, information.length)
                ).value
            else:
                raise TokenBootstrapError("token_scalar_facts_invalid")
            if value not in (0, 1):
                raise TokenBootstrapError("token_scalar_facts_invalid")
            return bool(value)
        if information.length < ctypes.sizeof(wintypes.DWORD):
            raise TokenBootstrapError("token_scalar_facts_invalid")
        return int(
            wintypes.DWORD.from_buffer_copy(
                information.read(0, ctypes.sizeof(wintypes.DWORD))
            ).value
        )

    def query_token_facts(self, token_handle: int) -> Mapping[str, object]:
        handle = self._handle(token_handle)
        token_type = self._scalar(handle, _TOKEN_INFORMATION["type"], kind="int")
        if token_type != 1:
            raise TokenBootstrapError("token_not_primary")
        user_info = self._get_information(handle, _TOKEN_INFORMATION["user"])
        if user_info.length < ctypes.sizeof(_TOKEN_USER):
            raise TokenBootstrapError("token_user_facts_invalid")
        user = ctypes.cast(user_info.address, ctypes.POINTER(_TOKEN_USER)).contents
        user_sid = self._sid_string(user.User.Sid, user_info)

        statistics_info = self._get_information(handle, _TOKEN_INFORMATION["statistics"])
        if statistics_info.length < ctypes.sizeof(_TOKEN_STATISTICS):
            raise TokenBootstrapError("token_statistics_invalid")
        statistics = _TOKEN_STATISTICS.from_buffer_copy(
            statistics_info.read(0, ctypes.sizeof(_TOKEN_STATISTICS))
        )
        authentication_id = {
            "high": int(statistics.AuthenticationId.HighPart) & 0xFFFFFFFF,
            "low": int(statistics.AuthenticationId.LowPart),
        }
        session_id = self._scalar(handle, _TOKEN_INFORMATION["session_id"], kind="int")

        app_container = self._scalar(handle, _TOKEN_INFORMATION["is_app_container"], kind="bool")
        app_container_sid = None
        if app_container:
            app_container_sid = self._single_sid(handle, _TOKEN_INFORMATION["app_container_sid"])

        stable_facts = {
            "user_sid": user_sid,
            "groups": self._sid_and_attributes(handle, _TOKEN_INFORMATION["groups"]),
            "owner_sid": self._single_sid(handle, _TOKEN_INFORMATION["owner"]),
            "primary_group_sid": self._single_sid(handle, _TOKEN_INFORMATION["primary_group"]),
            "privileges": self._privileges(handle),
            "restricted_sids": self._sid_and_attributes(
                handle, _TOKEN_INFORMATION["restricted_sids"]
            ),
            "integrity": self._single_sid_and_attributes(handle, _TOKEN_INFORMATION["integrity"]),
            "has_restrictions": self._scalar(
                handle, _TOKEN_INFORMATION["has_restrictions"], kind="bool"
            ),
            "elevation_type": self._scalar(
                handle, _TOKEN_INFORMATION["elevation_type"], kind="int"
            ),
            "mandatory_policy": self._scalar(
                handle, _TOKEN_INFORMATION["mandatory_policy"], kind="int"
            ),
            "is_app_container": app_container,
            "app_container_sid": app_container_sid,
            "virtualization_enabled": self._scalar(
                handle, _TOKEN_INFORMATION["virtualization_enabled"], kind="bool"
            ),
            "ui_access": self._scalar(handle, _TOKEN_INFORMATION["ui_access"], kind="bool"),
        }
        stable_raw = _canonical(stable_facts)
        return {
            "token_type": "primary",
            "user_sid": user_sid,
            "authentication_id": authentication_id,
            "session_id": session_id,
            "stable_facts_sha256": hashlib.sha256(stable_raw).hexdigest(),
        }

    @staticmethod
    def _require_single_thread() -> None:
        if len(threading.enumerate()) != 1:
            raise TokenBootstrapError("coordinator_thread_concurrency_invalid")

    def enable_se_tcb_privilege(self) -> object:
        self._require_single_thread()
        open_token = self._advapi32.OpenProcessToken
        open_token.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        open_token.restype = wintypes.BOOL
        get_current = self._kernel32.GetCurrentProcess
        get_current.argtypes = []
        get_current.restype = wintypes.HANDLE
        process_token = wintypes.HANDLE()
        if (
            not open_token(
                get_current(), _TOKEN_QUERY | _TOKEN_ADJUST_PRIVILEGES, ctypes.byref(process_token)
            )
            or not process_token.value
        ):
            raise TokenBootstrapError("se_tcb_token_open_failed")
        token_handle = int(process_token.value)
        try:
            lookup = self._advapi32.LookupPrivilegeValueW
            lookup.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(_LUID)]
            lookup.restype = wintypes.BOOL
            luid = _LUID()
            if not lookup(None, "SeTcbPrivilege", ctypes.byref(luid)):
                raise TokenBootstrapError("se_tcb_lookup_failed")
            requested = _TOKEN_PRIVILEGES_BUFFER()
            requested.PrivilegeCount = 1
            requested.Privilege = _LUID_AND_ATTRIBUTES(luid, _SE_PRIVILEGE_ENABLED)
            previous = ctypes.create_string_buffer(1024)
            previous_length = wintypes.DWORD()
            adjust = self._advapi32.AdjustTokenPrivileges
            adjust.argtypes = [
                wintypes.HANDLE,
                wintypes.BOOL,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.LPVOID,
                ctypes.POINTER(wintypes.DWORD),
            ]
            adjust.restype = wintypes.BOOL
            ctypes.set_last_error(0)
            adjusted = adjust(
                wintypes.HANDLE(token_handle),
                False,
                ctypes.cast(ctypes.byref(requested), wintypes.LPVOID),
                len(previous),
                ctypes.cast(previous, wintypes.LPVOID),
                ctypes.byref(previous_length),
            )
            last_error = ctypes.get_last_error()
            if not adjusted or last_error == _ERROR_NOT_ALL_ASSIGNED:
                raise TokenBootstrapError("se_tcb_not_available")
            if last_error != 0 or previous_length.value > len(previous):
                raise TokenBootstrapError("se_tcb_enable_failed")
            return _SeTcbRestoreState(
                token_handle=token_handle,
                previous_state=previous.raw[: previous_length.value],
                previous_size=int(previous_length.value),
            )
        except BaseException:
            if not self._kernel32.CloseHandle(wintypes.HANDLE(token_handle)):
                raise TokenBootstrapError("se_tcb_handle_cleanup_failed") from None
            raise

    def set_token_session_id(self, token_handle: int, session_id: int) -> None:
        if self._handle(token_handle) <= 0 or type(session_id) is not int or session_id != 0:
            raise TokenBootstrapError("token_session_target_not_fixed")
        set_info = self._advapi32.SetTokenInformation
        set_info.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        set_info.restype = wintypes.BOOL
        target = wintypes.DWORD(0)
        if not set_info(
            wintypes.HANDLE(token_handle),
            _TOKEN_INFORMATION["session_id"],
            ctypes.cast(ctypes.byref(target), wintypes.LPVOID),
            ctypes.sizeof(target),
        ):
            raise TokenBootstrapError("token_session_set_failed")

    def restore_se_tcb_privilege(self, previous_state: object) -> None:
        if type(previous_state) is not _SeTcbRestoreState or previous_state._closed:
            raise TokenBootstrapError("se_tcb_restore_state_invalid")
        try:
            if previous_state.previous_size:
                restore = self._advapi32.AdjustTokenPrivileges
                restore.argtypes = [
                    wintypes.HANDLE,
                    wintypes.BOOL,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.LPVOID,
                    ctypes.POINTER(wintypes.DWORD),
                ]
                restore.restype = wintypes.BOOL
                raw = ctypes.create_string_buffer(previous_state.previous_state)
                ctypes.set_last_error(0)
                restored = restore(
                    wintypes.HANDLE(previous_state.token_handle),
                    False,
                    ctypes.cast(raw, wintypes.LPVOID),
                    0,
                    None,
                    None,
                )
                last_error = ctypes.get_last_error()
                if not restored or last_error != 0:
                    raise TokenBootstrapError("se_tcb_restore_failed")
        finally:
            if not self._kernel32.CloseHandle(wintypes.HANDLE(previous_state.token_handle)):
                raise TokenBootstrapError("se_tcb_token_close_failed")
            previous_state._closed = True

    def close_owner_token(self, transfer: OwnerTokenTransfer) -> None:
        transfer = _validate_transfer(transfer)
        if not self._kernel32.CloseHandle(wintypes.HANDLE(transfer.remote_primary_token_handle)):
            raise TokenBootstrapError("owner_token_close_failed")

    def fail_stop_current_process(self, reason: str) -> None:
        del reason  # Reasons are deliberately never formatted into OS-visible output.
        get_current = self._kernel32.GetCurrentProcess
        get_current.argtypes = []
        get_current.restype = wintypes.HANDLE
        terminate = self._kernel32.TerminateProcess
        terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate.restype = wintypes.BOOL
        try:
            if terminate(get_current(), 0xE141):
                # A successful TerminateProcess does not return on Windows. If
                # a test double does return, still do not execute role cleanup.
                os._exit(0xE141)
        except BaseException:
            pass
        os._exit(0xE141)


def read_token_bootstrap_frame_from_pipe(
    channel: Mapping[str, object],
    *,
    expected_request_id: str,
    expected_owner_sid: str,
    deadline_monotonic_ns: int,
) -> OwnerTokenTransfer:
    """Read one bounded token transfer from the fixed local control endpoint.

    The pipe name is derived from the fixed prefix and service-generated nonce;
    there is no caller/path input. OS server PID is checked before and after
    the one length-prefixed message, and a second read must observe EOF.
    """

    if os.name != "nt":
        raise TokenBootstrapError("windows_required")
    if type(channel) not in (dict, MappingProxyType) or set(channel) != {"nonce", "server_pid"}:
        raise TokenBootstrapError("token_channel_invalid")
    nonce = channel["nonce"]
    server_pid = channel["server_pid"]
    if (
        type(nonce) is not str
        or _REQUEST_ID_RE.fullmatch(nonce) is None
        or type(server_pid) is not int
        or server_pid <= 0
        or type(expected_request_id) is not str
        or _REQUEST_ID_RE.fullmatch(expected_request_id) is None
        or type(deadline_monotonic_ns) is not int
        or deadline_monotonic_ns <= 0
    ):
        raise TokenBootstrapError("token_channel_invalid")
    address = _TOKEN_BOOTSTRAP_PIPE_PREFIX + nonce
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wait_pipe = kernel32.WaitNamedPipeW
    wait_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    wait_pipe.restype = wintypes.BOOL
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
    try:
        remaining_ns = deadline_monotonic_ns - time.monotonic_ns()
        if remaining_ns <= 0:
            raise TokenBootstrapError("token_pipe_deadline_exceeded")
        timeout_ms = max(1, min(600_000, (remaining_ns + 999_999) // 1_000_000))
        if not wait_pipe(address, timeout_ms):
            raise TokenBootstrapError("token_pipe_unavailable")
        access = _PIPE_READ_DATA | _PIPE_READ_ATTRIBUTES | _PIPE_READ_CONTROL | _PIPE_SYNCHRONIZE
        opened = create_file(
            address,
            access,
            0,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OVERLAPPED,
            None,
        )
        handle = int(opened) if type(opened) is int else int(getattr(opened, "value", 0) or 0)
        if handle <= 0 or handle == ctypes.c_void_p(-1).value:
            raise TokenBootstrapError("token_pipe_open_failed")
        server_pid = _named_pipe_server_pid(kernel32, handle)
        if server_pid != channel["server_pid"]:
            raise TokenBootstrapError("token_pipe_server_binding_mismatch")
        raw_frame = _read_one_overlapped_message(handle, deadline_monotonic_ns)
        if _named_pipe_server_pid(kernel32, handle) != server_pid:
            raise TokenBootstrapError("token_pipe_server_changed")
        _require_pipe_eof(handle, deadline_monotonic_ns)
        if len(raw_frame) < 4:
            raise TokenBootstrapError("token_frame_length_invalid")
        frame_size = int.from_bytes(raw_frame[:4], "big", signed=False)
        body = raw_frame[4:]
        if frame_size <= 0 or frame_size > _TOKEN_BOOTSTRAP_MAX_FRAME or len(body) != frame_size:
            raise TokenBootstrapError("token_frame_length_invalid")
        return parse_token_bootstrap_frame(
            body,
            expected_request_id=expected_request_id,
            expected_nonce=nonce,
            expected_owner_sid=expected_owner_sid,
        )
    finally:
        if handle:
            if not kernel32.CloseHandle(wintypes.HANDLE(handle)):
                raise TokenBootstrapError("token_pipe_handle_close_failed")


def _named_pipe_server_pid(kernel32: object, pipe_handle: int) -> int:
    get_pid = kernel32.GetNamedPipeServerProcessId
    get_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    get_pid.restype = wintypes.BOOL
    pid = wintypes.ULONG()
    if not get_pid(wintypes.HANDLE(pipe_handle), ctypes.byref(pid)) or not pid.value:
        raise TokenBootstrapError("token_pipe_server_pid_unavailable")
    return int(pid.value)


def _wait_overlapped(overlapped: object, deadline_monotonic_ns: int) -> None:
    try:
        import _winapi

        remaining = deadline_monotonic_ns - time.monotonic_ns()
        if remaining <= 0:
            overlapped.cancel()
            raise TokenBootstrapError("token_pipe_deadline_exceeded")
        timeout_ms = max(1, min(600_000, (remaining + 999_999) // 1_000_000))
        if _winapi.WaitForMultipleObjects([overlapped.event], False, timeout_ms) != _WAIT_OBJECT_0:
            overlapped.cancel()
            raise TokenBootstrapError("token_pipe_deadline_exceeded")
    except TokenBootstrapError:
        raise
    except BaseException:
        try:
            overlapped.cancel()
        except BaseException:
            pass
        raise TokenBootstrapError("token_pipe_wait_failed") from None


def _read_pipe_chunk(handle: int, size: int, deadline_monotonic_ns: int) -> bytes:
    import _winapi

    try:
        overlapped, error_code = _winapi.ReadFile(handle, size, overlapped=True)
    except OSError as error:
        if getattr(error, "winerror", None) == _ERROR_BROKEN_PIPE:
            return b""
        raise TokenBootstrapError("token_pipe_read_failed") from None
    except BaseException:
        raise TokenBootstrapError("token_pipe_read_failed") from None
    if error_code == _ERROR_IO_PENDING:
        _wait_overlapped(overlapped, deadline_monotonic_ns)
    try:
        count, final_error = overlapped.GetOverlappedResult(True)
    except OSError as error:
        if getattr(error, "winerror", None) == _ERROR_BROKEN_PIPE:
            return b""
        raise TokenBootstrapError("token_pipe_read_failed") from None
    except BaseException:
        raise TokenBootstrapError("token_pipe_read_failed") from None
    if final_error == _ERROR_BROKEN_PIPE or count == 0:
        return b""
    if type(count) is not int or count < 0 or count > size:
        raise TokenBootstrapError("token_pipe_read_failed")
    return bytes(overlapped.getbuffer())[:count]


def _read_one_overlapped_message(handle: int, deadline_monotonic_ns: int) -> bytes:
    raw = _read_pipe_chunk(handle, _TOKEN_BOOTSTRAP_MAX_FRAME + 5, deadline_monotonic_ns)
    if not raw or len(raw) > _TOKEN_BOOTSTRAP_MAX_FRAME + 4:
        raise TokenBootstrapError("token_frame_size_invalid")
    return raw


def _require_pipe_eof(handle: int, deadline_monotonic_ns: int) -> None:
    trailing = _read_pipe_chunk(handle, 1, deadline_monotonic_ns)
    if trailing:
        raise TokenBootstrapError("token_frame_trailing_bytes")


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TokenBootstrapError("token_frame_duplicate_key")
        result[key] = value
    return result


def _canonical(value) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise TokenBootstrapError("token_frame_invalid") from None


def encode_token_bootstrap_frame(value: Mapping[str, object]) -> bytes:
    raw = _canonical(dict(value))
    if not raw or len(raw) > 4096:
        raise TokenBootstrapError("token_frame_size_invalid")
    return raw


def _parse_authentication_id(value: object) -> tuple[int, int]:
    if type(value) is not dict or set(value) != _AUTHENTICATION_ID_FIELDS:
        raise TokenBootstrapError("token_authentication_id_invalid")
    high = value["high"]
    low = value["low"]
    if any(type(item) is not int or not 0 <= item <= 0xFFFFFFFF for item in (high, low)):
        raise TokenBootstrapError("token_authentication_id_invalid")
    return high, low


def parse_token_bootstrap_frame(
    raw: bytes,
    *,
    expected_request_id: str,
    expected_nonce: str,
    expected_owner_sid: str,
) -> OwnerTokenTransfer:
    if type(raw) is not bytes or not raw or len(raw) > 4096:
        raise TokenBootstrapError("token_frame_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_pairs)
    except TokenBootstrapError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise TokenBootstrapError("token_frame_invalid") from None
    if type(value) is not dict or set(value) != _FRAME_FIELDS or _canonical(value) != raw:
        raise TokenBootstrapError("token_frame_fields_invalid")
    if value["schema"] != TOKEN_BOOTSTRAP_SCHEMA:
        raise TokenBootstrapError("token_frame_schema_invalid")
    request_id = value["request_id"]
    nonce = value["nonce"]
    owner_sid = value["owner_sid"]
    if (
        type(request_id) is not str
        or _REQUEST_ID_RE.fullmatch(request_id) is None
        or request_id != expected_request_id
        or type(nonce) is not str
        or _REQUEST_ID_RE.fullmatch(nonce) is None
        or nonce != expected_nonce
        or type(owner_sid) is not str
        or _SID_RE.fullmatch(owner_sid) is None
        or owner_sid != expected_owner_sid
    ):
        raise TokenBootstrapError("token_frame_binding_mismatch")
    handle = value["remote_primary_token_handle"]
    source_session = value["source_session_id"]
    digest = value["token_facts_sha256"]
    if type(handle) is not int or handle <= 0:
        raise TokenBootstrapError("token_handle_invalid")
    if type(source_session) is not int or source_session < 0:
        raise TokenBootstrapError("token_session_invalid")
    if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None or digest == "0" * 64:
        raise TokenBootstrapError("token_facts_digest_invalid")
    return OwnerTokenTransfer(
        request_id=request_id,
        nonce=nonce,
        remote_primary_token_handle=handle,
        owner_sid=owner_sid,
        authentication_id=_parse_authentication_id(value["authentication_id"]),
        source_session_id=source_session,
        token_facts_sha256=digest,
    )


def _read_token_facts(value: object) -> tuple[str, tuple[int, int], int, str]:
    if type(value) is not dict or set(value) != _TOKEN_FACT_FIELDS:
        raise TokenBootstrapError("token_query_facts_invalid")
    if value["token_type"] != "primary":
        raise TokenBootstrapError("token_not_primary")
    user_sid = value["user_sid"]
    if type(user_sid) is not str or _SID_RE.fullmatch(user_sid) is None:
        raise TokenBootstrapError("token_query_facts_invalid")
    auth_id_map = value["authentication_id"]
    if type(auth_id_map) is not dict or set(auth_id_map) != _AUTHENTICATION_ID_FIELDS:
        raise TokenBootstrapError("token_query_facts_invalid")
    auth_id = _parse_authentication_id(auth_id_map)
    session_id = value["session_id"]
    digest = value["stable_facts_sha256"]
    if type(session_id) is not int or session_id < 0:
        raise TokenBootstrapError("token_query_facts_invalid")
    if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None or digest == "0" * 64:
        raise TokenBootstrapError("token_query_facts_invalid")
    return user_sid, auth_id, session_id, digest


def _validate_transfer(transfer: object) -> OwnerTokenTransfer:
    if type(transfer) is not OwnerTokenTransfer:
        raise TokenBootstrapError("token_transfer_invalid")
    if (
        type(transfer.request_id) is not str
        or _REQUEST_ID_RE.fullmatch(transfer.request_id) is None
        or type(transfer.nonce) is not str
        or _REQUEST_ID_RE.fullmatch(transfer.nonce) is None
        or type(transfer.remote_primary_token_handle) is not int
        or transfer.remote_primary_token_handle <= 0
        or type(transfer.owner_sid) is not str
        or _SID_RE.fullmatch(transfer.owner_sid) is None
        or type(transfer.authentication_id) is not tuple
        or len(transfer.authentication_id) != 2
        or any(
            type(part) is not int or not 0 <= part <= 0xFFFFFFFF
            for part in transfer.authentication_id
        )
        or type(transfer.source_session_id) is not int
        or transfer.source_session_id < 0
        or type(transfer.token_facts_sha256) is not str
        or _SHA256_RE.fullmatch(transfer.token_facts_sha256) is None
        or transfer.token_facts_sha256 == "0" * 64
    ):
        raise TokenBootstrapError("token_transfer_invalid")
    return transfer


def apply_owner_token_session_zero(
    transfer: OwnerTokenTransfer,
    *,
    api: TokenSessionApi,
) -> TokenSessionFacts:
    """Re-query the transferred token and apply only the fixed SessionId=0.

    SeTcb is enabled only for this coordinator operation and restored in all
    ordinary success/failure paths.  A failed privilege restore is
    process-fatal because the coordinator's service token may remain changed.
    """

    transfer = _validate_transfer(transfer)
    handle = transfer.remote_primary_token_handle
    before_raw = api.query_token_facts(handle)
    before_sid, before_auth, source_session, stable_digest = _read_token_facts(before_raw)
    if (
        before_sid != transfer.owner_sid
        or before_auth != transfer.authentication_id
        or source_session != transfer.source_session_id
        or stable_digest != transfer.token_facts_sha256
    ):
        raise TokenBootstrapError("token_transfer_binding_changed")

    try:
        previous_state = api.enable_se_tcb_privilege()
    except BaseException:
        # The API may have changed the process token before surfacing an
        # exception.  Do not continue a reusable service-role process with
        # privilege state that cannot be proven.
        api.fail_stop_current_process("se_tcb_enable_state_unknown")
        raise FatalPrivilegeRestore("se_tcb_enable_state_unknown") from None
    if previous_state is None:
        api.fail_stop_current_process("se_tcb_enable_state_unknown")
        raise FatalPrivilegeRestore("se_tcb_enable_state_unknown")
    operation_error = None
    result = None
    try:
        api.set_token_session_id(handle, 0)
        after_sid, after_auth, target_session, after_digest = _read_token_facts(
            api.query_token_facts(handle)
        )
        if (
            after_sid != before_sid
            or after_auth != before_auth
            or target_session != 0
            or after_digest != stable_digest
        ):
            raise TokenBootstrapError("token_session_readback_mismatch")
        result = TokenSessionFacts(
            owner_sid=after_sid,
            authentication_id=after_auth,
            source_session_id=source_session,
            target_session_id=target_session,
            stable_facts_sha256=after_digest,
        )
    except BaseException as exc:
        operation_error = exc
    try:
        api.restore_se_tcb_privilege(previous_state)
    except BaseException:
        api.fail_stop_current_process("se_tcb_restore_failed")
        raise FatalPrivilegeRestore("se_tcb_restore_failed") from None
    if operation_error is not None:
        if isinstance(operation_error, TokenBootstrapError):
            raise operation_error
        if not isinstance(operation_error, Exception):
            raise operation_error
        raise TokenBootstrapError("token_session_change_failed") from None
    if result is None:
        raise TokenBootstrapError("token_session_change_failed")
    return result


__all__ = [
    "TOKEN_BOOTSTRAP_SCHEMA",
    "OwnerTokenTransfer",
    "TokenBootstrapError",
    "TokenSessionFacts",
    "FatalPrivilegeRestore",
    "WindowsTokenSessionApi",
    "parse_token_bootstrap_frame",
    "encode_token_bootstrap_frame",
    "read_token_bootstrap_frame_from_pipe",
    "apply_owner_token_session_zero",
]
