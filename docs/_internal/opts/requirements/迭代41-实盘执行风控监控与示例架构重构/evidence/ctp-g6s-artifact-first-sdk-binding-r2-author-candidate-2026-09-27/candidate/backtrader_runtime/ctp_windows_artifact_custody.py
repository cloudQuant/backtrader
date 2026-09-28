"""Windows retained-handle custody for exact installed SDK files.

This module is an isolated candidate helper. It intentionally refuses on
non-Windows hosts and on ACLs it cannot prove safe. It is not a deployment
trust root or a signed artifact pin.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import re
import threading
from collections.abc import Iterable, Mapping
from ctypes import wintypes
from dataclasses import dataclass


class WindowsArtifactCustodyError(RuntimeError):
    """A path could not be retained as the exact read-only Windows object."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_LOWER_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_READ_ATTRIBUTES = 0x00000080
_READ_CONTROL = 0x00020000
_GENERIC_READ = 0x80000000
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_ACL_SIZE_INFORMATION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_ACCESS_DENIED_ACE_TYPE = 1
_ACE_INHERIT_ONLY = 0x08
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_LOCAL_SYSTEM_SID = "S-1-5-18"
_BUILTIN_ADMINS_SID = "S-1-5-32-544"
# The Windows volume root is owned by the protected Windows Modules Installer
# service on this host. Treat that exact OS service SID as a trusted owner;
# arbitrary service/application owners remain rejected.
_TRUSTED_INSTALLER_SID = (
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
)
_AUTHENTICATED_USERS_SID = "S-1-5-11"
_FILE_ADD_SUBDIRECTORY = 0x00000004
_UNSAFE_WRITE_MASK = (
    0x00000002  # FILE_WRITE_DATA / FILE_ADD_FILE
    | 0x00000004  # FILE_APPEND_DATA / FILE_ADD_SUBDIRECTORY
    | 0x00000010  # FILE_WRITE_EA
    | 0x00000040  # FILE_DELETE_CHILD
    | 0x00000100  # FILE_WRITE_ATTRIBUTES
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x40000000  # GENERIC_WRITE
    | 0x10000000  # GENERIC_ALL
)
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


@dataclass(frozen=True)
class RetainedFileIdentity:
    path: str
    size: int
    volume_serial: int
    file_index: int
    sha256: str


def _win32() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    if os.name != "nt":
        raise WindowsArtifactCustodyError("windows_handle_custody_required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    kernel32.SetFilePointerEx.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return kernel32, advapi32


def _extended(path: str) -> str:
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _sid_string(advapi32: ctypes.WinDLL, kernel32: ctypes.WinDLL, sid: int) -> str:
    value = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(value)):
        raise WindowsArtifactCustodyError("windows_sid_conversion_failed")
    try:
        return value.value or ""
    finally:
        # ConvertSidToStringSidW allocates with LocalAlloc; LocalFree is
        # exported by kernel32, not advapi32.
        kernel32.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def _current_sid(advapi32: ctypes.WinDLL, kernel32: ctypes.WinDLL) -> str:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise WindowsArtifactCustodyError("windows_process_token_query_failed")
    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if needed.value <= ctypes.sizeof(_SidAndAttributes) or needed.value > 65536:
            raise WindowsArtifactCustodyError("windows_process_token_size_invalid")
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token, _TOKEN_USER, buffer, needed.value, ctypes.byref(needed)
        ):
            raise WindowsArtifactCustodyError("windows_process_token_query_failed")
        user = ctypes.cast(buffer, ctypes.POINTER(_SidAndAttributes)).contents
        return _sid_string(advapi32, kernel32, user.Sid)
    finally:
        kernel32.CloseHandle(token)


def _identity(
    kernel32: ctypes.WinDLL, handle: int, *, directory: bool
) -> tuple[int, int, int, int]:
    info = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise WindowsArtifactCustodyError("windows_handle_identity_unavailable")
    is_directory = bool(info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY)
    if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise WindowsArtifactCustodyError("windows_reparse_component_rejected")
    if is_directory != directory:
        raise WindowsArtifactCustodyError("windows_path_type_mismatch")
    size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
    index = (info.nFileIndexHigh << 32) | info.nFileIndexLow
    return (
        int(info.dwVolumeSerialNumber),
        int(index),
        int(size),
        int(info.dwFileAttributes),
    )


def _check_dacl(
    advapi32: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
    handle: int,
    path: str,
    *,
    volume_root: bool,
    current_sid: str,
) -> None:
    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    sacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetSecurityInfo(
        handle,
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        ctypes.byref(group),
        ctypes.byref(dacl),
        ctypes.byref(sacl),
        ctypes.byref(descriptor),
    )
    if status != 0 or not owner.value or not dacl.value:
        raise WindowsArtifactCustodyError("windows_acl_unavailable")
    try:
        owner_sid = _sid_string(advapi32, kernel32, owner.value)
        allowed_owners = {
            current_sid,
            _LOCAL_SYSTEM_SID,
            _BUILTIN_ADMINS_SID,
            _TRUSTED_INSTALLER_SID,
        }
        if owner_sid not in allowed_owners:
            raise WindowsArtifactCustodyError("windows_acl_owner_untrusted")
        size_info = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(size_info),
            ctypes.sizeof(size_info),
            _ACL_SIZE_INFORMATION,
        ):
            raise WindowsArtifactCustodyError("windows_acl_parse_failed")
        for index in range(size_info.AceCount):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise WindowsArtifactCustodyError("windows_acl_parse_failed")
            header = ctypes.cast(ace_pointer, ctypes.POINTER(_AceHeader)).contents
            if header.AceType == _ACCESS_DENIED_ACE_TYPE:
                continue
            if header.AceType != _ACCESS_ALLOWED_ACE_TYPE or header.AceSize < 8:
                raise WindowsArtifactCustodyError("windows_acl_ace_unclassified")
            if header.AceFlags & _ACE_INHERIT_ONLY:
                continue
            mask = ctypes.c_uint32.from_address(ace_pointer.value + 4).value
            sid_pointer = ace_pointer.value + 8
            ace_sid = _sid_string(advapi32, kernel32, sid_pointer)
            if not mask & _UNSAFE_WRITE_MASK:
                continue
            if ace_sid in {
                current_sid,
                _LOCAL_SYSTEM_SID,
                _BUILTIN_ADMINS_SID,
                _TRUSTED_INSTALLER_SID,
            }:
                continue
            # The Windows volume root commonly permits authenticated users to
            # create a new top-level directory. It cannot replace any existing
            # held path; any broader root permission remains rejected.
            if (
                volume_root
                and ace_sid == _AUTHENTICATED_USERS_SID
                and mask == _FILE_ADD_SUBDIRECTORY
            ):
                continue
            raise WindowsArtifactCustodyError("windows_acl_untrusted_write_grant")
    finally:
        if descriptor.value:
            kernel32.LocalFree(descriptor)


class WindowsArtifactCustody:
    """Retain exact files and ancestors with share-read-only handles.

    Handles stay open until ``close``. A compatible Python read handle can be
    opened, while new write/delete handles and renames are denied by Windows.
    """

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self._kernel32, self._advapi32 = _win32()
        self._current_sid = _current_sid(self._advapi32, self._kernel32)
        self._handles: list[int] = []
        self._directories: dict[str, tuple[int, tuple[int, int]]] = {}
        self._files: dict[str, tuple[int, RetainedFileIdentity]] = {}
        self._read_lock = threading.RLock()
        self._closed = False

    @classmethod
    def acquire(
        cls,
        root: str,
        relative_files: Iterable[str],
        *,
        expected_sha256: Mapping[str, str],
        max_file_bytes: int = 128 * 1024 * 1024,
    ) -> WindowsArtifactCustody:
        custody = cls(root)
        try:
            paths = tuple(sorted(set(relative_files)))
            if not paths or set(paths) != set(expected_sha256):
                raise WindowsArtifactCustodyError("windows_custody_file_set_invalid")
            for relative in paths:
                if (
                    type(relative) is not str
                    or not relative
                    or "\\" in relative
                    or "\x00" in relative
                    or relative.startswith("/")
                    or any(part in {"", ".", ".."} for part in relative.split("/"))
                ):
                    raise WindowsArtifactCustodyError(
                        "windows_custody_relative_path_invalid"
                    )
                digest = expected_sha256.get(relative)
                if type(digest) is not str or not _LOWER_HEX64.fullmatch(digest):
                    raise WindowsArtifactCustodyError("windows_custody_hash_invalid")
                path = os.path.join(custody.root, *relative.split("/"))
                custody._retain_ancestors(path)
                custody._retain_file(relative, path, digest, max_file_bytes)
            custody.verify_current()
            return custody
        except BaseException:
            custody.close()
            raise

    def _open(self, path: str, *, directory: bool) -> int:
        access = (
            (_FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES | _READ_CONTROL)
            if directory
            else (_GENERIC_READ | _FILE_READ_ATTRIBUTES | _READ_CONTROL)
        )
        flags = _FILE_FLAG_OPEN_REPARSE_POINT | (
            _FILE_FLAG_BACKUP_SEMANTICS if directory else 0
        )
        handle = self._kernel32.CreateFileW(
            _extended(path), access, _FILE_SHARE_READ, None, _OPEN_EXISTING, flags, None
        )
        value = ctypes.cast(handle, ctypes.c_void_p).value
        if value == _INVALID_HANDLE_VALUE or value is None:
            error = ctypes.get_last_error()
            reason = (
                "windows_share_violation" if error == 32 else "windows_path_open_failed"
            )
            raise WindowsArtifactCustodyError(reason)
        self._handles.append(value)
        _identity(self._kernel32, value, directory=directory)
        _check_dacl(
            self._advapi32,
            self._kernel32,
            value,
            path,
            volume_root=os.path.dirname(path) == path,
            current_sid=self._current_sid,
        )
        return value

    def _retain_ancestors(self, path: str) -> None:
        drive, tail = os.path.splitdrive(os.path.abspath(path))
        if not drive or not drive.endswith(":"):
            raise WindowsArtifactCustodyError("windows_nonlocal_volume_rejected")
        current = drive + os.sep
        self._retain_directory(current)
        parts = [part for part in tail.split(os.sep) if part]
        for part in parts[:-1]:
            current = os.path.join(current, part)
            self._retain_directory(current)

    def _retain_directory(self, path: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key in self._directories:
            return
        handle = self._open(path, directory=True)
        volume, index, _size, _attrs = _identity(self._kernel32, handle, directory=True)
        self._directories[key] = (handle, (volume, index))

    def _retain_file(
        self, relative: str, path: str, expected_sha256: str, max_file_bytes: int
    ) -> None:
        handle = self._open(path, directory=False)
        volume, index, size, _attrs = _identity(self._kernel32, handle, directory=False)
        if size < 0 or size > max_file_bytes:
            raise WindowsArtifactCustodyError("windows_file_size_out_of_bounds")
        raw = self._read_handle(handle, size)
        actual = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual, expected_sha256):
            raise WindowsArtifactCustodyError("windows_file_hash_mismatch")
        identity = RetainedFileIdentity(
            path=os.path.abspath(path),
            size=size,
            volume_serial=volume,
            file_index=index,
            sha256=actual,
        )
        self._files[relative] = (handle, identity)

    def _read_handle(self, handle: int, size: int) -> bytes:
        with self._read_lock:
            if not self._kernel32.SetFilePointerEx(handle, 0, None, 0):
                raise WindowsArtifactCustodyError("windows_file_seek_failed")
            remaining = size
            chunks: list[bytes] = []
            while remaining:
                amount = min(remaining, 1024 * 1024)
                buffer = ctypes.create_string_buffer(amount)
                read = wintypes.DWORD()
                if not self._kernel32.ReadFile(
                    handle, buffer, amount, ctypes.byref(read), None
                ):
                    raise WindowsArtifactCustodyError("windows_file_read_failed")
                if read.value <= 0 or read.value > amount:
                    raise WindowsArtifactCustodyError("windows_file_read_short")
                chunks.append(buffer.raw[: read.value])
                remaining -= read.value
            return b"".join(chunks)

    def read(self, relative: str, *, max_bytes: int = 128 * 1024 * 1024) -> bytes:
        if self._closed:
            raise WindowsArtifactCustodyError("windows_custody_closed")
        entry = self._files.get(relative)
        if entry is None:
            raise WindowsArtifactCustodyError("windows_file_not_retained")
        handle, identity = entry
        if identity.size > max_bytes:
            raise WindowsArtifactCustodyError("windows_file_size_out_of_bounds")
        raw = self._read_handle(handle, identity.size)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), identity.sha256):
            raise WindowsArtifactCustodyError("windows_retained_handle_content_changed")
        return raw

    def verify_current(self) -> None:
        if self._closed:
            raise WindowsArtifactCustodyError("windows_custody_closed")
        for path, (handle, identity) in self._directories.items():
            _identity(self._kernel32, handle, directory=True)
            check = self._open(path, directory=True)
            try:
                volume, index, _size, _attrs = _identity(
                    self._kernel32, check, directory=True
                )
                if (volume, index) != identity:
                    raise WindowsArtifactCustodyError(
                        "windows_directory_path_identity_changed"
                    )
            finally:
                self._kernel32.CloseHandle(check)
                self._handles.remove(check)
        for relative, (handle, identity) in self._files.items():
            volume, index, size, _attrs = _identity(
                self._kernel32, handle, directory=False
            )
            if (volume, index, size) != (
                identity.volume_serial,
                identity.file_index,
                identity.size,
            ):
                raise WindowsArtifactCustodyError(
                    "windows_file_handle_identity_changed"
                )
            path_handle = self._open(identity.path, directory=False)
            try:
                path_volume, path_index, path_size, _attrs = _identity(
                    self._kernel32, path_handle, directory=False
                )
                if (path_volume, path_index, path_size) != (volume, index, size):
                    raise WindowsArtifactCustodyError(
                        "windows_file_path_identity_changed"
                    )
            finally:
                self._kernel32.CloseHandle(path_handle)
                self._handles.remove(path_handle)
            self.read(relative, max_bytes=identity.size)

    @property
    def files(self) -> Mapping[str, RetainedFileIdentity]:
        return {
            relative: identity for relative, (_handle, identity) in self._files.items()
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        while self._handles:
            handle = self._handles.pop()
            if not self._kernel32.CloseHandle(handle) and first_error is None:
                first_error = WindowsArtifactCustodyError("windows_handle_close_failed")
        self._directories.clear()
        self._files.clear()
        if first_error is not None:
            raise first_error

    def __enter__(self):
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()
