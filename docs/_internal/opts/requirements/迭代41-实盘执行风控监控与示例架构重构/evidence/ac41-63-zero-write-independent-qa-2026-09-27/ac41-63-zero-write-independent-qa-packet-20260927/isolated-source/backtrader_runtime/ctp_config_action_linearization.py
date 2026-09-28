"""Offline Windows config-path read lease and a future broker interface.

``ConfigPathReadLease`` blocks tested ordinary data-write, replacement,
unlink, and rename opens on a local NTFS config path. It is diagnostic only,
not an action grant, and must not be used to linearize a final config check
with a CTP native call: Windows sharing does not constrain
``FILE_WRITE_ATTRIBUTES``. The focused negative test successfully sets a
custom name-surrogate reparse tag on the held config file through a parallel
``FILE_WRITE_ATTRIBUTES`` handle.
Microsoft's ``CreateFileW`` contract says share flags do not affect attribute
access requests, and the MS-FSA ``FSCTL_SET_REPARSE_POINT`` contract allows
that operation when the handle has ``FILE_WRITE_DATA`` or
``FILE_WRITE_ATTRIBUTES``. The app-tag documentation allows non-Microsoft
tags outside reserved ranges. These rules match the Windows negative test:
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4aeefef8-92c3-4abc-af7a-a610caf8a165
https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-tags

The smallest defensible future boundary is a trusted external broker which
owns the config's write ACL and every config/path mutation route, ensures no
untrusted process can hold a pre-opened mutator handle before startup, and
serializes all authorized config edits with native actions. It must re-read
the exact protected config generation and scope, then perform the one bound
native action itself while retaining its writer fence. The broker must also
own the CTP client/native handle: returning a signed allow token to a caller
that can still mutate the file or invoke the native API independently is not
a fence. Its OS identity, IPC authentication, config ownership, and native
client ownership are deployment trust roots; a Python ``Protocol``
implementation or structural type check cannot prove any of them. This
module only declares that future interface. It has no broker, IPC transport,
native dispatch, or write route, so callers must keep CTP writes closed.
"""

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import List, Protocol, Tuple


_GENERIC_READ = 0x80000000
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_DRIVE_FIXED = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class ConfigActionLinearizationError(RuntimeError):
    """Raised when an exclusive config path lease cannot be established."""


@dataclass(frozen=True)
class ConfigBoundActionRequest:
    """Non-secret request facts bound by a trusted external action broker."""

    config_identity: str
    config_generation: str
    config_sha256: str
    effective_scope_sha256: str
    action_id: str
    action_kind: str
    action_payload_sha256: str


class TrustedConfigActionBroker(Protocol):
    """Type-only contract; implementations must own config and native dispatch.

    An implementation must authenticate its caller over a trusted IPC
    boundary; own the config write ACL, all path-mutation routes, and the CTP
    native client; prevent pre-opened mutator handles before startup; derive
    and verify config identity/generation; compare the action payload digest;
    revalidate the sealed scope; and dispatch the one allowlisted action
    inside the same fenced operation. It returns only an opaque broker
    receipt. This structural Python protocol is not proof that an object is
    trusted. Caller-held locks, bearer grants, and local callbacks do not
    satisfy the contract.
    """

    def execute_action(self, request: ConfigBoundActionRequest, action_payload: bytes) -> bytes:
        """Atomically validate and dispatch one config-bound native action."""
        ...


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time_low", ctypes.c_uint32),
        ("creation_time_high", ctypes.c_uint32),
        ("last_access_time_low", ctypes.c_uint32),
        ("last_access_time_high", ctypes.c_uint32),
        ("last_write_time_low", ctypes.c_uint32),
        ("last_write_time_high", ctypes.c_uint32),
        ("volume_serial_number", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


def _win_api():
    if os.name != "nt":
        raise ConfigActionLinearizationError("config_action_lease_windows_required")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.GetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFileSizeEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64)]
    kernel32.GetFileSizeEx.restype = ctypes.c_int
    kernel32.SetFilePointerEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int64,
        ctypes.POINTER(ctypes.c_int64),
        ctypes.c_uint32,
    ]
    kernel32.SetFilePointerEx.restype = ctypes.c_int
    kernel32.ReadFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = ctypes.c_int
    kernel32.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumeInformationW.restype = ctypes.c_int
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint32
    return kernel32


def _open_handle(kernel32, path: str, access: int, flags: int):
    handle = kernel32.CreateFileW(
        path,
        access,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE or handle is None:
        error = ctypes.get_last_error()
        raise ConfigActionLinearizationError(
            "config_action_lease_open_failed: winerror={}".format(error)
        )
    return handle


def _identity(kernel32, handle) -> Tuple[int, int, int, int]:
    info = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        error = ctypes.get_last_error()
        raise ConfigActionLinearizationError(
            "config_action_lease_identity_failed: winerror={}".format(error)
        )
    if info.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise ConfigActionLinearizationError("config_action_lease_reparse_component")
    file_index = (info.file_index_high << 32) | info.file_index_low
    return info.volume_serial_number, file_index, info.attributes, info.number_of_links


def _require_fixed_local_drive(kernel32, root: str) -> None:
    drive_type = kernel32.GetDriveTypeW(root)
    if drive_type != _DRIVE_FIXED:
        raise ConfigActionLinearizationError(
            "config_action_lease_fixed_local_drive_required: drive_type={}".format(
                drive_type
            )
        )


def _require_ntfs(kernel32, root: str) -> None:
    file_system_name = ctypes.create_unicode_buffer(64)
    if not kernel32.GetVolumeInformationW(
        root, None, 0, None, None, None, file_system_name, len(file_system_name)
    ):
        error = ctypes.get_last_error()
        raise ConfigActionLinearizationError(
            "config_action_lease_volume_check_failed: winerror={}".format(error)
        )
    if file_system_name.value.upper() != "NTFS":
        raise ConfigActionLinearizationError("config_action_lease_ntfs_required")


class ConfigPathReadLease:
    """Diagnostic read hold; it does not fence path metadata or native calls."""

    def __init__(self, kernel32, path: Path, handles: List[object], file_handle):
        self.path = path
        self._kernel32 = kernel32
        self._handles = handles
        self._file_handle = file_handle
        self._closed = False
        self._close_complete = False

    def read_bytes(self) -> bytes:
        """Read the held file object, independent of a later pathname lookup."""

        if self._closed:
            raise ConfigActionLinearizationError("config_action_lease_closed")

        _, _, _, number_of_links = _identity(self._kernel32, self._file_handle)
        if number_of_links != 1:
            raise ConfigActionLinearizationError("config_action_lease_config_hardlink_not_allowed")

        size = ctypes.c_int64()
        if not self._kernel32.GetFileSizeEx(self._file_handle, ctypes.byref(size)):
            error = ctypes.get_last_error()
            raise ConfigActionLinearizationError(
                "config_action_lease_size_failed: winerror={}".format(error)
            )
        if size.value < 0:
            raise ConfigActionLinearizationError("config_action_lease_invalid_size")

        new_position = ctypes.c_int64()
        if not self._kernel32.SetFilePointerEx(
            self._file_handle, 0, ctypes.byref(new_position), 0
        ):
            error = ctypes.get_last_error()
            raise ConfigActionLinearizationError(
                "config_action_lease_seek_failed: winerror={}".format(error)
            )

        remaining = size.value
        chunks = []
        while remaining:
            count = min(remaining, 1024 * 1024)
            buffer = ctypes.create_string_buffer(count)
            bytes_read = ctypes.c_uint32()
            if not self._kernel32.ReadFile(
                self._file_handle,
                buffer,
                count,
                ctypes.byref(bytes_read),
                None,
            ):
                error = ctypes.get_last_error()
                raise ConfigActionLinearizationError(
                    "config_action_lease_read_failed: winerror={}".format(error)
                )
            if bytes_read.value == 0:
                raise ConfigActionLinearizationError("config_action_lease_short_read")
            chunks.append(buffer.raw[: bytes_read.value])
            remaining -= bytes_read.value
        return b"".join(chunks)

    def close(self) -> None:
        if self._close_complete:
            return
        self._closed = True
        close_errors = []
        remaining_handles = []
        for handle in reversed(self._handles):
            if not self._kernel32.CloseHandle(handle):
                close_errors.append(ctypes.get_last_error())
                remaining_handles.append(handle)
        self._handles = list(reversed(remaining_handles))
        if close_errors:
            raise ConfigActionLinearizationError(
                "config_action_lease_close_failed: winerrors={}".format(close_errors)
            )
        self._close_complete = True
        self._handles = []
        self._file_handle = None

    def __enter__(self):
        if self._closed:
            raise ConfigActionLinearizationError("config_action_lease_closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def acquire_config_path_read_lease(config_path) -> ConfigPathReadLease:
    """Hold a local NTFS config path for diagnostics; this is not a write grant.

    The local lease is useful for documenting which common mutations Windows
    share modes block. It cannot fence FILE_WRITE_ATTRIBUTES or arbitrary
    name-surrogate tags and must not guard native submit/cancel. The caller must
    use an external broker satisfying :class:`TrustedConfigActionBroker` for
    action linearization. This candidate is not connected to any runner or
    submission path.
    """

    kernel32 = _win_api()
    path_text = os.path.abspath(os.fspath(config_path))
    windows_path = PureWindowsPath(path_text)
    if not windows_path.is_absolute() or windows_path.drive.startswith("\\\\"):
        raise ConfigActionLinearizationError("config_action_lease_local_absolute_path_required")
    if any(part in (".", "..") for part in windows_path.parts):
        raise ConfigActionLinearizationError("config_action_lease_normalized_path_required")

    root = windows_path.anchor
    _require_fixed_local_drive(kernel32, root)
    _require_ntfs(kernel32, root)
    path = Path(path_text)
    directories = [root]
    parent = root
    for component in windows_path.parts[1:-1]:
        parent = os.path.join(parent, component)
        directories.append(parent)

    handles = []
    try:
        identities = []
        directory_flags = _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT
        for directory in directories:
            handle = _open_handle(kernel32, directory, _FILE_READ_ATTRIBUTES, directory_flags)
            handles.append(handle)
            volume_id, file_id, attrs, _ = _identity(kernel32, handle)
            if not attrs & _FILE_ATTRIBUTE_DIRECTORY:
                raise ConfigActionLinearizationError("config_action_lease_non_directory_component")
            identities.append((volume_id, file_id))

        file_handle = _open_handle(
            kernel32,
            path_text,
            _GENERIC_READ,
            _FILE_FLAG_OPEN_REPARSE_POINT,
        )
        handles.append(file_handle)
        file_volume, file_id, file_attrs, file_links = _identity(kernel32, file_handle)
        if file_attrs & _FILE_ATTRIBUTE_DIRECTORY:
            raise ConfigActionLinearizationError("config_action_lease_config_not_regular_file")
        if file_links != 1:
            raise ConfigActionLinearizationError("config_action_lease_config_hardlink_not_allowed")
        identities.append((file_volume, file_id))

        # Reopen every component by name while all original handles remain
        # held. This detects a component that changed during lease acquisition.
        verify_paths = directories + [path_text]
        verify_handles = []
        try:
            verify_flags = directory_flags
            for index, verify_path in enumerate(verify_paths):
                flags = verify_flags if index < len(directories) else _FILE_FLAG_OPEN_REPARSE_POINT
                access = _FILE_READ_ATTRIBUTES if index < len(directories) else _GENERIC_READ
                verify_handle = _open_handle(kernel32, verify_path, access, flags)
                verify_handles.append(verify_handle)
                volume_id, verify_id, _, verify_links = _identity(kernel32, verify_handle)
                if index == len(identities) - 1 and verify_links != 1:
                    raise ConfigActionLinearizationError(
                        "config_action_lease_config_hardlink_not_allowed"
                    )
                if (volume_id, verify_id) != identities[index]:
                    raise ConfigActionLinearizationError(
                        "config_action_lease_path_changed_during_acquire"
                    )
        finally:
            for verify_handle in reversed(verify_handles):
                kernel32.CloseHandle(verify_handle)

        return ConfigPathReadLease(kernel32, path, handles, file_handle)
    except Exception:
        for handle in reversed(handles):
            kernel32.CloseHandle(handle)
        raise


__all__ = [
    "ConfigBoundActionRequest",
    "ConfigPathReadLease",
    "ConfigActionLinearizationError",
    "TrustedConfigActionBroker",
    "acquire_config_path_read_lease",
]
