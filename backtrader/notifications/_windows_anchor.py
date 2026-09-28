"""Handle-relative Windows persistence for notification session anchors.

No pathname is used for ACL mutation. Existing directories and files are
opened relative to validated handles with FILE_OPEN_REPARSE_POINT. New objects
receive a protected TokenUser ACL in the NtCreateFile call. Existing file ACLs
are repaired only if their ACEs grant access solely to the token user; any
external ACE is rejected before ACL mutation or content writes. ACL changes and
content writes use the opened file handle. Updates are not crash-atomic;
interruption can leave a partial anchor file.
"""

from __future__ import annotations

import ctypes
import json
import ntpath
import os
from ctypes import wintypes
from typing import Any, Optional, Tuple

_ERROR = "cannot safely persist Windows notification anchor"
_STATUS_NOT_FOUND = {0xC0000034, 0xC000003A}  # NAME_NOT_FOUND, PATH_NOT_FOUND
_STATUS_COLLISION = 0xC0000035
_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
_FILE_READ_ATTRIBUTES = 0x80
_FILE_WRITE_ATTRIBUTES = 0x100
_FILE_LIST_DIRECTORY = 0x1
_FILE_WRITE_DATA = 0x2
_FILE_TRAVERSE = 0x20
_FILE_ADD_FILE = 0x2
_FILE_ADD_SUBDIRECTORY = 0x4
_FILE_DELETE_CHILD = 0x40
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_ALL_ACCESS = 0x001F01FF
_FILE_PERSISTENT_ACLS = 0x00000008
_DANGEROUS_DIR_MASK = (
    _FILE_ADD_FILE
    | _FILE_ADD_SUBDIRECTORY
    | _FILE_WRITE_ATTRIBUTES
    | _FILE_DELETE_CHILD
    | _DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x40000000  # GENERIC_WRITE
    | 0x10000000  # GENERIC_ALL
)
_TRUSTED_ANCESTOR_SIDS = {
    "S-1-5-18",  # Local System
    "S-1-5-32-544",  # Builtin Administrators
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
}


def _windows_dll(name: str, *, use_last_error: bool = False) -> Any:
    """Load a DLL only when the Windows persistence adapter is constructed."""

    return getattr(ctypes, "WinDLL")(name, use_last_error=use_last_error)


def _win_last_error() -> int:
    """Read the calling thread's Win32 error through a Windows-only API."""

    return int(getattr(ctypes, "get_last_error")())


class _UnicodeString(ctypes.Structure):
    _fields_ = (
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    )


class _ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    )


class _IoStatusBlock(ctypes.Structure):
    _fields_ = (("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t))


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD))


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("FileAttributes", wintypes.DWORD),
        ("CreationTimeLow", wintypes.DWORD),
        ("CreationTimeHigh", wintypes.DWORD),
        ("LastAccessTimeLow", wintypes.DWORD),
        ("LastAccessTimeHigh", wintypes.DWORD),
        ("LastWriteTimeLow", wintypes.DWORD),
        ("LastWriteTimeHigh", wintypes.DWORD),
        ("VolumeSerialNumber", wintypes.DWORD),
        ("FileSizeHigh", wintypes.DWORD),
        ("FileSizeLow", wintypes.DWORD),
        ("NumberOfLinks", wintypes.DWORD),
        ("FileIndexHigh", wintypes.DWORD),
        ("FileIndexLow", wintypes.DWORD),
    )


class _TokenUser(ctypes.Structure):
    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD))


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = (("DeleteFile", wintypes.BOOLEAN),)


class _FileEndOfFileInfo(ctypes.Structure):
    _fields_ = (("EndOfFile", ctypes.c_longlong),)


def _validate_owner_only_acl(
    owner_sid: str,
    token_user_sid: str,
    protected: bool,
    entries: Tuple[Tuple[int, int, int, str], ...],
) -> None:
    """Validate the exact protected DACL used for new anchor objects."""

    if (
        owner_sid != token_user_sid
        or not protected
        or entries != ((0, 0, _FILE_ALL_ACCESS, token_user_sid),)
    ):
        raise OSError(_ERROR)


def _validate_owner_only_directory_acl(
    owner_sid: str,
    token_user_sid: str,
    protected: bool,
    entries: Tuple[Tuple[int, int, int, str], ...],
) -> None:
    """Accept the owner's exact ACE with or without directory inheritance flags."""

    if (
        owner_sid != token_user_sid
        or not protected
        or len(entries) != 1
        or entries[0][0] != 0
        or entries[0][1] not in (0, 0x1 | 0x2)  # OI | CI are safe for owner-only children.
        or entries[0][2] != _FILE_ALL_ACCESS
        or entries[0][3] != token_user_sid
    ):
        raise OSError(_ERROR)


def _validate_repairable_owner_acl(
    owner_sid: str,
    token_user_sid: str,
    entries: Tuple[Tuple[int, int, int, str], ...],
) -> None:
    """Reject externally accessible existing files before changing their DACL."""

    if owner_sid != token_user_sid or not entries:
        raise OSError(_ERROR)
    # A handle opened while any external ACE granted access remains usable after
    # an ACL change. Refuse such files before tightening or writing their data.
    if any(
        ace_type != 0 or trustee_sid != token_user_sid
        for ace_type, _flags, _mask, trustee_sid in entries
    ):
        raise OSError(_ERROR)


def _validate_safe_ancestor_acl(
    owner_sid: str,
    token_user_sid: str,
    entries: Tuple[Tuple[int, int, int, str], ...],
) -> None:
    """Reject existing path ancestors writable by principals outside the user."""

    trusted = _TRUSTED_ANCESTOR_SIDS | {token_user_sid}
    if owner_sid not in trusted:
        raise OSError(_ERROR)
    for ace_type, _flags, mask, trustee_sid in entries:
        if ace_type != 0:  # Only simple ACCESS_ALLOWED_ACE records are understood.
            raise OSError(_ERROR)
        if trustee_sid not in trusted and mask & _DANGEROUS_DIR_MASK:
            raise OSError(_ERROR)


def _status_code(status: int) -> int:
    return ctypes.c_uint32(status).value


def _as_handle(handle: Any) -> Any:
    return handle if isinstance(handle, ctypes.c_void_p) else wintypes.HANDLE(handle)


def _reject_reparse(attributes: int) -> None:
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError("reparse point in notification anchor path")


class _WindowsAnchorApi:
    """Small ctypes boundary kept separate so policy has pure fake tests."""

    def __init__(self) -> None:
        self.kernel32 = _windows_dll("Kernel32", use_last_error=True)
        self.advapi32 = _windows_dll("Advapi32", use_last_error=True)
        self.ntdll = _windows_dll("ntdll")
        self._bind()

    def _bind(self) -> None:
        k = self.kernel32
        a = self.advapi32
        n = self.ntdll
        k.GetCurrentProcess.argtypes = ()
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.restype = wintypes.BOOL
        k.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        k.CreateFileW.restype = wintypes.HANDLE
        k.GetFileInformationByHandle.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        )
        k.GetFileInformationByHandle.restype = wintypes.BOOL
        k.GetFileInformationByHandleEx.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        k.GetFileInformationByHandleEx.restype = wintypes.BOOL
        k.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
        k.GetDriveTypeW.restype = wintypes.UINT
        k.GetVolumeInformationW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        )
        k.GetVolumeInformationW.restype = wintypes.BOOL
        k.WriteFile.argtypes = (
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        )
        k.WriteFile.restype = wintypes.BOOL
        k.ReadFile.argtypes = (
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        )
        k.ReadFile.restype = wintypes.BOOL
        k.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
        k.GetFileSizeEx.restype = wintypes.BOOL
        k.SetFilePointerEx.argtypes = (
            wintypes.HANDLE,
            ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.DWORD,
        )
        k.SetFilePointerEx.restype = wintypes.BOOL
        k.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
        k.FlushFileBuffers.restype = wintypes.BOOL
        k.SetFileInformationByHandle.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        k.SetFileInformationByHandle.restype = wintypes.BOOL
        a.OpenProcessToken.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        )
        a.OpenProcessToken.restype = wintypes.BOOL
        a.GetTokenInformation.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        a.GetTokenInformation.restype = wintypes.BOOL
        a.IsValidSid.argtypes = (ctypes.c_void_p,)
        a.IsValidSid.restype = wintypes.BOOL
        a.GetLengthSid.argtypes = (ctypes.c_void_p,)
        a.GetLengthSid.restype = wintypes.DWORD
        a.ConvertSidToStringSidW.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        )
        a.ConvertSidToStringSidW.restype = wintypes.BOOL
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        )
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        a.GetSecurityInfo.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        )
        a.GetSecurityInfo.restype = wintypes.DWORD
        a.SetSecurityInfo.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        a.SetSecurityInfo.restype = wintypes.DWORD
        a.GetSecurityDescriptorControl.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.WORD),
            ctypes.POINTER(wintypes.DWORD),
        )
        a.GetSecurityDescriptorControl.restype = wintypes.BOOL
        a.GetSecurityDescriptorOwner.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        )
        a.GetSecurityDescriptorOwner.restype = wintypes.BOOL
        a.GetSecurityDescriptorDacl.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        )
        a.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        a.GetAclInformation.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        a.GetAclInformation.restype = wintypes.BOOL
        a.GetAce.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
        a.GetAce.restype = wintypes.BOOL
        n.NtCreateFile.argtypes = (
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
        )
        n.NtCreateFile.restype = wintypes.LONG
        n.RtlNtStatusToDosError.argtypes = (wintypes.LONG,)
        n.RtlNtStatusToDosError.restype = wintypes.ULONG

    def close(self, handle: Any) -> None:
        if handle and not self.kernel32.CloseHandle(_as_handle(handle)):
            raise OSError(_win_last_error(), _ERROR)

    def free_security_descriptor(self, descriptor: Any) -> None:
        self.kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        self.kernel32.LocalFree.restype = ctypes.c_void_p
        self.kernel32.LocalFree(descriptor)

    def token_user_sid(self) -> str:
        """Read the SID from TOKEN_USER; environment account names are ignored."""

        token = wintypes.HANDLE()
        if not self.advapi32.OpenProcessToken(
            self.kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            raise OSError(_win_last_error(), _ERROR)
        try:
            buffer = ctypes.create_string_buffer(64 * 1024)
            required = wintypes.DWORD()
            if not self.advapi32.GetTokenInformation(
                token, 1, buffer, ctypes.sizeof(buffer), ctypes.byref(required)
            ):
                raise OSError(_win_last_error(), _ERROR)
            token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
            sid = token_user.Sid
            if not sid or not self.advapi32.IsValidSid(sid):
                raise OSError(_ERROR)
            sid_size = int(self.advapi32.GetLengthSid(sid))
            buffer_start = ctypes.addressof(buffer)
            buffer_end = buffer_start + min(int(required.value), ctypes.sizeof(buffer))
            if sid < buffer_start or sid + sid_size > buffer_end:
                raise OSError(_ERROR)
            text = wintypes.LPWSTR()
            if not self.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)) or not text:
                raise OSError(_win_last_error(), _ERROR)
            try:
                return str(text.value)
            finally:
                self.kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
                self.kernel32.LocalFree.restype = ctypes.c_void_p
                self.kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            self.close(token)

    def security_descriptor(self, sid: str) -> ctypes.c_void_p:
        if not sid.startswith("S-1-") or any(ch not in "S-1234567890-" for ch in sid):
            raise OSError(_ERROR)
        descriptor = ctypes.c_void_p()
        sddl = "O:{0}D:P(A;;FA;;;{0})".format(sid)
        if not self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise OSError(_win_last_error(), _ERROR)
        return descriptor

    def acl(self, handle: Any) -> Tuple[str, bool, Tuple[Tuple[int, int, int, str], ...]]:
        owner = ctypes.c_void_p()
        group = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        sacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        result = self.advapi32.GetSecurityInfo(
            _as_handle(handle),
            1,  # SE_FILE_OBJECT
            0x1 | 0x4,  # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if result or not descriptor:
            raise OSError(int(result or _win_last_error()), _ERROR)
        try:
            control = wintypes.WORD()
            revision = wintypes.DWORD()
            if not self.advapi32.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            ):
                raise OSError(_win_last_error(), _ERROR)
            owner_defaulted = wintypes.BOOL()
            if (
                not self.advapi32.GetSecurityDescriptorOwner(
                    descriptor, ctypes.byref(owner), ctypes.byref(owner_defaulted)
                )
                or owner_defaulted.value
                or not owner
            ):
                raise OSError(_ERROR)
            owner_sid = self._sid_string(owner)
            dacl_present = wintypes.BOOL()
            dacl_defaulted = wintypes.BOOL()
            if (
                not self.advapi32.GetSecurityDescriptorDacl(
                    descriptor,
                    ctypes.byref(dacl_present),
                    ctypes.byref(dacl),
                    ctypes.byref(dacl_defaulted),
                )
                or not dacl_present.value
                or dacl_defaulted.value
                or not dacl
            ):
                raise OSError(_ERROR)

            class _AclSizeInformation(ctypes.Structure):
                _fields_ = (
                    ("AceCount", wintypes.DWORD),
                    ("AclBytesInUse", wintypes.DWORD),
                    ("AclBytesFree", wintypes.DWORD),
                )

            info = _AclSizeInformation()
            if not self.advapi32.GetAclInformation(
                dacl, ctypes.byref(info), ctypes.sizeof(info), 2
            ):
                raise OSError(_win_last_error(), _ERROR)
            entries = []
            for index in range(int(info.AceCount)):
                pointer = ctypes.c_void_p()
                if not self.advapi32.GetAce(dacl, index, ctypes.byref(pointer)):
                    raise OSError(_win_last_error(), _ERROR)
                pointer_value = pointer.value
                if pointer_value is None:
                    raise OSError(_ERROR)
                header = ctypes.string_at(pointer, 4)
                ace_type, ace_flags = header[0], header[1]
                ace_size = int.from_bytes(header[2:4], "little")
                if ace_size < 8 or ace_size > int(info.AclBytesInUse):
                    raise OSError(_ERROR)
                mask = int.from_bytes(ctypes.string_at(pointer_value + 4, 4), "little")
                trustee_sid = ""
                if ace_type in (0, 1):
                    if ace_size < 12:
                        raise OSError(_ERROR)
                    trustee = ctypes.c_void_p(pointer_value + 8)
                    if not self.advapi32.IsValidSid(trustee):
                        raise OSError(_ERROR)
                    sid_size = int(self.advapi32.GetLengthSid(trustee))
                    if sid_size > ace_size - 8:
                        raise OSError(_ERROR)
                    trustee_sid = self._sid_string(trustee)
                entries.append((ace_type, ace_flags, mask, trustee_sid))
            return owner_sid, bool(control.value & 0x1000), tuple(entries)
        finally:
            self.kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
            self.kernel32.LocalFree.restype = ctypes.c_void_p
            self.kernel32.LocalFree(descriptor)

    def set_owner_only_acl(self, handle: Any, descriptor: Any) -> None:
        """Protect the owner-only DACL through this already-open handle."""

        dacl_present = wintypes.BOOL()
        dacl_defaulted = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if (
            not self.advapi32.GetSecurityDescriptorDacl(
                descriptor,
                ctypes.byref(dacl_present),
                ctypes.byref(dacl),
                ctypes.byref(dacl_defaulted),
            )
            or not dacl_present.value
            or dacl_defaulted.value
            or not dacl
        ):
            raise OSError(_ERROR)
        security_information = 0x4 | 0x80000000  # DACL | PROTECTED_DACL; owner was verified.
        result = self.advapi32.SetSecurityInfo(
            _as_handle(handle),
            1,  # SE_FILE_OBJECT
            security_information,
            None,
            None,
            dacl,
            None,
        )
        if result:
            raise OSError(int(result), _ERROR)

    def _sid_string(self, sid: ctypes.c_void_p) -> str:
        output = wintypes.LPWSTR()
        if not self.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(output)) or not output:
            raise OSError(_win_last_error(), _ERROR)
        try:
            return str(output.value)
        finally:
            self.kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
            self.kernel32.LocalFree.restype = ctypes.c_void_p
            self.kernel32.LocalFree(ctypes.cast(output, ctypes.c_void_p))

    def attributes(self, handle: Any) -> int:
        info = _FileAttributeTagInfo()
        if not self.kernel32.GetFileInformationByHandleEx(
            _as_handle(handle), 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError(_win_last_error(), _ERROR)
        _reject_reparse(int(info.FileAttributes))
        return int(info.FileAttributes)

    def identity(self, handle: Any) -> Tuple[int, int, int, int]:
        info = _ByHandleFileInformation()
        if not self.kernel32.GetFileInformationByHandle(_as_handle(handle), ctypes.byref(info)):
            raise OSError(_win_last_error(), _ERROR)
        return (
            int(info.VolumeSerialNumber),
            int(info.FileIndexHigh),
            int(info.FileIndexLow),
            int(info.NumberOfLinks),
        )

    def _relative(
        self,
        parent: Any,
        name: str,
        access: int,
        disposition: int,
        options: int,
        share: int = _FILE_SHARE_ALL,
        security_descriptor: Any = None,
    ) -> Any:
        name_buffer = ctypes.create_unicode_buffer(name)
        name_bytes = len(name.encode("utf-16-le"))
        unicode_name = _UnicodeString(
            name_bytes,
            name_bytes + ctypes.sizeof(wintypes.WCHAR),
            ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            _as_handle(parent),
            ctypes.pointer(unicode_name),
            0x40,  # OBJ_CASE_INSENSITIVE
            security_descriptor,
            None,
        )
        io_status = _IoStatusBlock()
        handle = wintypes.HANDLE()
        status = int(
            self.ntdll.NtCreateFile(
                ctypes.byref(handle),
                access,
                ctypes.byref(attributes),
                ctypes.byref(io_status),
                None,
                0x80,  # FILE_ATTRIBUTE_NORMAL
                share,
                disposition,
                options,
                None,
                0,
            )
        )
        if status < 0:
            raise OSError(_status_code(status), _ERROR)
        return handle

    def open_root(self, drive: str) -> Any:
        path = drive + "\\"
        handle = self.kernel32.CreateFileW(
            path,
            _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _READ_CONTROL | _SYNCHRONIZE,
            _FILE_SHARE_ALL,
            None,
            3,  # OPEN_EXISTING
            0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(_win_last_error(), _ERROR)
        try:
            self.attributes(handle)
        except BaseException:
            self.close(handle)
            raise
        return handle

    def volume_supports_persistent_acls(self, drive: str) -> bool:
        """Read FILE_PERSISTENT_ACLS from GetVolumeInformationW for a drive."""

        volume_name = ctypes.create_unicode_buffer(261)
        filesystem_name = ctypes.create_unicode_buffer(261)
        serial_number = wintypes.DWORD()
        max_component_length = wintypes.DWORD()
        filesystem_flags = wintypes.DWORD()
        if not self.kernel32.GetVolumeInformationW(
            drive + "\\",
            volume_name,
            len(volume_name),
            ctypes.byref(serial_number),
            ctypes.byref(max_component_length),
            ctypes.byref(filesystem_flags),
            filesystem_name,
            len(filesystem_name),
        ):
            raise OSError(_win_last_error(), _ERROR)
        return bool(filesystem_flags.value & _FILE_PERSISTENT_ACLS)

    def open_or_create_directory(
        self,
        parent: Any,
        name: str,
        *,
        is_final: bool,
        token_sid: str,
        descriptor: ctypes.c_void_p,
    ) -> Tuple[Any, bool]:
        access = (
            _FILE_LIST_DIRECTORY
            | _FILE_TRAVERSE
            | _FILE_READ_ATTRIBUTES
            | _READ_CONTROL
            | _SYNCHRONIZE
        )
        if is_final:
            access |= _FILE_ADD_FILE | _FILE_DELETE_CHILD | _DELETE
        options = _FILE_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT
        try:
            handle = self._relative(parent, name, access, _FILE_OPEN, options)
            created = False
        except OSError as error:
            if (
                getattr(error, "winerror", None) not in _STATUS_NOT_FOUND
                and error.args[0] not in _STATUS_NOT_FOUND
            ):
                raise
            try:
                handle = self._relative(
                    parent, name, access, _FILE_CREATE, options, security_descriptor=descriptor
                )
                created = True
            except OSError as create_error:
                status = create_error.args[0] if create_error.args else -1
                if status != _STATUS_COLLISION:
                    raise
                handle = self._relative(parent, name, access, _FILE_OPEN, options)
                created = False
        try:
            attributes = self.attributes(handle)
            if not attributes & _FILE_ATTRIBUTE_DIRECTORY:
                raise OSError(_ERROR)
            owner, protected, entries = self.acl(handle)
            if is_final:
                _validate_owner_only_directory_acl(owner, token_sid, protected, entries)
            elif created and owner == token_sid and protected:
                _validate_owner_only_acl(owner, token_sid, protected, entries)
            else:
                _validate_safe_ancestor_acl(owner, token_sid, entries)
        except BaseException:
            self.close(handle)
            raise
        return handle, created

    def open_relative_file(self, parent: Any, name: str) -> Any:
        return self._relative(
            parent,
            name,
            _FILE_READ_ATTRIBUTES | _READ_CONTROL | _SYNCHRONIZE,
            _FILE_OPEN,
            _FILE_NON_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT,
        )

    def open_relative_update_file(self, parent: Any, name: str) -> Any:
        """Open a file or reparse object for same-handle ACL and content update."""

        return self._relative(
            parent,
            name,
            _FILE_WRITE_DATA
            | _FILE_READ_ATTRIBUTES
            | _READ_CONTROL
            | _WRITE_DAC
            | _DELETE
            | _SYNCHRONIZE,
            _FILE_OPEN,
            _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT,
        )

    def open_relative_read_file(self, parent: Any, name: str) -> Any:
        return self._relative(
            parent,
            name,
            0x1 | _FILE_READ_ATTRIBUTES | _READ_CONTROL | _SYNCHRONIZE,
            _FILE_OPEN,
            _FILE_NON_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT,
        )

    def read_handle_bytes(self, handle: Any) -> bytes:
        size = ctypes.c_longlong()
        if not self.kernel32.GetFileSizeEx(_as_handle(handle), ctypes.byref(size)):
            raise OSError(_win_last_error(), _ERROR)
        if size.value < 0 or size.value > 1024 * 1024:
            raise OSError(_ERROR)
        buffer = ctypes.create_string_buffer(max(1, int(size.value)))
        read = wintypes.DWORD()
        if (
            not self.kernel32.ReadFile(
                _as_handle(handle), buffer, int(size.value), ctypes.byref(read), None
            )
            or read.value != size.value
        ):
            raise OSError(_win_last_error(), _ERROR)
        return buffer.raw[: read.value]

    def create_relative_file(self, parent: Any, name: str, descriptor: Any) -> Any:
        return self._relative(
            parent,
            name,
            0x2 | _FILE_READ_ATTRIBUTES | _READ_CONTROL | _DELETE | _SYNCHRONIZE,
            _FILE_CREATE,
            _FILE_NON_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT,
            security_descriptor=descriptor,
        )

    def write_and_flush(self, handle: Any, payload: bytes) -> None:
        if len(payload) > 0xFFFFFFFF:
            raise OSError(_ERROR)
        buffer = ctypes.create_string_buffer(payload, max(1, len(payload)))
        written = wintypes.DWORD()
        if not self.kernel32.WriteFile(
            _as_handle(handle), buffer, len(payload), ctypes.byref(written), None
        ) or written.value != len(payload):
            raise OSError(_win_last_error(), _ERROR)
        if not self.kernel32.FlushFileBuffers(_as_handle(handle)):
            raise OSError(_win_last_error(), _ERROR)

    def seek_start(self, handle: Any) -> None:
        if not self.kernel32.SetFilePointerEx(_as_handle(handle), 0, None, 0):
            raise OSError(_win_last_error(), _ERROR)

    def truncate_and_write(self, handle: Any, payload: bytes) -> None:
        end = _FileEndOfFileInfo(0)
        if not self.kernel32.SetFileInformationByHandle(
            _as_handle(handle), 6, ctypes.byref(end), ctypes.sizeof(end)  # FileEndOfFileInfo
        ):
            raise OSError(_win_last_error(), _ERROR)
        self.seek_start(handle)
        self.write_and_flush(handle, payload)

    def mark_for_delete(self, handle: Any) -> None:
        info = _FileDispositionInfo(True)
        if not self.kernel32.SetFileInformationByHandle(
            _as_handle(handle), 4, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError(_win_last_error(), _ERROR)


def _absolute_parts(path: str) -> Tuple[str, Tuple[str, ...], str]:
    absolute = ntpath.abspath(path)
    drive, tail = ntpath.splitdrive(absolute)
    if not drive or not drive.endswith(":") or not tail.startswith("\\"):
        raise OSError("anchor path must be on a drive-letter local volume")
    if any(part in ("", ".", "..") for part in tail.split("\\")[1:] if part):
        raise OSError(_ERROR)
    parts = tuple(part for part in tail.split("\\") if part)
    if not parts:
        raise OSError("anchor path cannot be a volume root")
    leaf = parts[-1]
    if any(ch in leaf for ch in "\\/:\x00") or leaf.endswith((" ", ".")):
        raise OSError(_ERROR)
    return drive.upper(), parts[:-1], leaf


def _open_secure_directory(
    api: _WindowsAnchorApi, path: str, token_sid: str, descriptor: Any
) -> Tuple[Any, list]:
    absolute = ntpath.abspath(path)
    drive, tail = ntpath.splitdrive(absolute)
    if not drive or not drive.endswith(":") or not tail.startswith("\\"):
        raise OSError("anchor directory must be on a drive-letter local volume")
    parts = tuple(part for part in tail.split("\\") if part)
    if not parts:
        raise OSError("anchor directory cannot be a volume root")
    if int(api.kernel32.GetDriveTypeW(drive + "\\")) != 3:  # DRIVE_FIXED
        raise OSError("anchor path must be on a fixed local volume")
    if not api.volume_supports_persistent_acls(drive):
        raise OSError("anchor path requires persistent ACL support")
    root = api.open_root(drive)
    handles = [root]
    try:
        parent = root
        for index, component in enumerate(parts):
            child, _created = api.open_or_create_directory(
                parent,
                component,
                is_final=index == len(parts) - 1,
                token_sid=token_sid,
                descriptor=descriptor,
            )
            handles.append(child)
            parent = child
        return parent, handles
    except BaseException:
        for handle in reversed(handles):
            try:
                api.close(handle)
            except Exception:
                pass
        raise


def _write_in_directory(
    api: _WindowsAnchorApi,
    directory_handle: Any,
    leaf: str,
    token_sid: str,
    descriptor: Any,
    payload: bytes,
) -> None:
    """Secure and update one regular file relative to a verified private handle."""

    target_handle = None
    created = False
    completed = False
    try:
        for _attempt in range(4):
            try:
                target_handle = api.open_relative_update_file(directory_handle, leaf)
                break
            except OSError as error:
                if not error.args or error.args[0] not in _STATUS_NOT_FOUND:
                    raise
                try:
                    target_handle = api.create_relative_file(directory_handle, leaf, descriptor)
                    created = True
                    break
                except OSError as create_error:
                    if create_error.args and create_error.args[0] == _STATUS_COLLISION:
                        continue
                    raise
        if target_handle is None:
            raise OSError(_ERROR)

        attributes = api.attributes(target_handle)
        identity = api.identity(target_handle)
        if attributes & _FILE_ATTRIBUTE_DIRECTORY or identity[3] != 1:
            raise OSError(_ERROR)
        owner, protected, entries = api.acl(target_handle)
        if owner != token_sid:
            raise OSError("anchor file is not owned by the current token user")
        if created:
            _validate_owner_only_acl(owner, token_sid, protected, entries)
        else:
            _validate_repairable_owner_acl(owner, token_sid, entries)
            api.set_owner_only_acl(target_handle, descriptor)
            owner, protected, entries = api.acl(target_handle)
            _validate_owner_only_acl(owner, token_sid, protected, entries)

        api.truncate_and_write(target_handle, payload)

        final_attributes = api.attributes(target_handle)
        final_identity = api.identity(target_handle)
        if (
            final_attributes & _FILE_ATTRIBUTE_DIRECTORY
            or identity[:3] != final_identity[:3]
            or final_identity[3] != 1
        ):
            raise OSError("anchor file identity changed during update")
        owner, protected, entries = api.acl(target_handle)
        _validate_owner_only_acl(owner, token_sid, protected, entries)
        completed = True
    finally:
        if target_handle is not None:
            if created and not completed:
                try:
                    api.mark_for_delete(target_handle)
                except Exception:
                    pass
            api.close(target_handle)


def persist_anchor(path: str, data: Any, *, api: Optional[_WindowsAnchorApi] = None) -> str:
    """Write an anchor through a verified handle after enforcing its owner-only ACL."""

    api = api or _WindowsAnchorApi()
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    absolute = ntpath.abspath(os.fspath(path))
    drive, parent_parts, leaf = _absolute_parts(absolute)
    del drive, parent_parts
    parent_path = ntpath.dirname(absolute)
    token_sid = api.token_user_sid()
    descriptor = api.security_descriptor(token_sid)
    directory_handles: list[Any] = []
    directory_handle = None
    try:
        directory_handle, directory_handles = _open_secure_directory(
            api, parent_path, token_sid, descriptor
        )
        _write_in_directory(api, directory_handle, leaf, token_sid, descriptor, payload)
        return path
    finally:
        for handle in reversed(directory_handles):
            api.close(handle)
        api.free_security_descriptor(descriptor)
