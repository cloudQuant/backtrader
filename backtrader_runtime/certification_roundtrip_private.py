"""Unintegrated Windows owner-only artifact candidate using stdlib/Win32.

No shell, credential, provider, SDK or environment loading. Newly created
directories and artifact files receive protected owner-only DACLs at creation.
SQLite-created DB/WAL/SHM files inherit the sole owner ACE from that directory;
``verify_sqlite_scope`` checks their actual handles, ownership and inherited ACLs.

This protects against other ordinary OS identities, not hostile same-SID code,
administrators, backup privileges or a compromised process. prepare_child does
not reserve a filename. Deadlines are checked around synchronous local Win32
calls, not a hard process supervisor. Failed writes retain private partial files
and are never retried or overwritten. This candidate is not used by C01 yet.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time


class PrivateArtifactError(ValueError):
    """Only fixed local codes; never OS diagnostics, paths or artifact bytes."""


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)
_MAX_BYTES = 8 * 1024 * 1024
_FULL_CONTROL = 0x1F01FF
_READ_CONTROL = 0x20000
_READ_ATTRIBUTES = 0x80
_DIRECTORY = 0x10
_REPARSE = 0x400
_INVALID_HANDLE = C.c_void_p(-1).value


def _fail(code):
    raise PrivateArtifactError(code) from None


def _deadline(value):
    if value is not None:
        if type(value) not in (float, int) or not math.isfinite(value):
            _fail("invalid_io_deadline")
        if time.monotonic() >= value:
            _fail("private_io_deadline")


def _name(value):
    if (
        type(value) is not str
        or not _NAME.fullmatch(value)
        or value.endswith(".")
        or _RESERVED.fullmatch(value)
    ):
        _fail("simple_artifact_name_required")
    return value


def _path(value):
    try:
        path = Path(value)
        if (
            os.name != "nt"
            or not path.is_absolute()
            or not re.fullmatch(r"[A-Za-z]:", path.drive)
            or ".." in path.parts
        ):
            _fail("absolute_local_path_required")
        for part in path.parts[1:]:
            if (
                part.rstrip(" .") != part
                or _RESERVED.fullmatch(part)
                or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            ):
                _fail("absolute_local_path_required")
        return path
    except PrivateArtifactError:
        raise
    except Exception:
        _fail("invalid_evidence_path")


class _SA(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]


class _FILE_INFO(C.Structure):
    _fields_ = [
        ("attributes", W.DWORD),
        ("creation", W.FILETIME),
        ("access", W.FILETIME),
        ("write", W.FILETIME),
        ("volume", W.DWORD),
        ("size_high", W.DWORD),
        ("size_low", W.DWORD),
        ("links", W.DWORD),
        ("index_high", W.DWORD),
        ("index_low", W.DWORD),
    ]


class _ACL_SIZE(C.Structure):
    _fields_ = [("count", W.DWORD), ("used", W.DWORD), ("free", W.DWORD)]


class _ACE_HEADER(C.Structure):
    _fields_ = [("kind", W.BYTE), ("flags", W.BYTE), ("size", W.WORD)]


class _Win32:
    def __init__(self):
        if os.name != "nt":
            _fail("windows_required")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.security = C.WinDLL("advapi32", use_last_error=True)
        ptr = C.c_void_p
        pptr = C.POINTER(ptr)
        pdword = C.POINTER(W.DWORD)
        declarations = {
            "CreateFileW": (
                self.kernel,
                [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(_SA), W.DWORD, W.DWORD, W.HANDLE],
                W.HANDLE,
            ),
            "CreateDirectoryW": (self.kernel, [W.LPCWSTR, C.POINTER(_SA)], W.BOOL),
            "GetFileInformationByHandle": (self.kernel, [W.HANDLE, C.POINTER(_FILE_INFO)], W.BOOL),
            "CloseHandle": (self.kernel, [W.HANDLE], W.BOOL),
            "WriteFile": (self.kernel, [W.HANDLE, ptr, W.DWORD, pdword, ptr], W.BOOL),
            "FlushFileBuffers": (self.kernel, [W.HANDLE], W.BOOL),
            "GetCurrentProcess": (self.kernel, [], W.HANDLE),
            "GetCurrentThread": (self.kernel, [], W.HANDLE),
            "LocalFree": (self.kernel, [ptr], ptr),
            "OpenProcessToken": (self.security, [W.HANDLE, W.DWORD, pptr], W.BOOL),
            "OpenThreadToken": (self.security, [W.HANDLE, W.DWORD, W.BOOL, pptr], W.BOOL),
            "GetTokenInformation": (
                self.security,
                [W.HANDLE, C.c_int, ptr, W.DWORD, pdword],
                W.BOOL,
            ),
            "ConvertSidToStringSidW": (self.security, [ptr, pptr], W.BOOL),
            "ConvertStringSecurityDescriptorToSecurityDescriptorW": (
                self.security,
                [W.LPCWSTR, W.DWORD, pptr, pdword],
                W.BOOL,
            ),
            "GetSecurityInfo": (
                self.security,
                [W.HANDLE, C.c_int, W.DWORD, pptr, pptr, pptr, pptr, pptr],
                W.DWORD,
            ),
            "GetSecurityDescriptorControl": (
                self.security,
                [ptr, C.POINTER(W.WORD), pdword],
                W.BOOL,
            ),
            "GetAclInformation": (self.security, [ptr, ptr, W.DWORD, C.c_int], W.BOOL),
            "GetAce": (self.security, [ptr, W.DWORD, pptr], W.BOOL),
            "IsValidSid": (self.security, [ptr], W.BOOL),
            "GetLengthSid": (self.security, [ptr], W.DWORD),
        }
        for name, (library, arguments, result) in declarations.items():
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result
            setattr(self, name, function)

    def sid_text(self, sid):
        value = C.c_void_p()
        if (
            not sid
            or not self.IsValidSid(sid)
            or not self.ConvertSidToStringSidW(sid, C.byref(value))
        ):
            _fail("owner_identity_unverified")
        try:
            return C.wstring_at(value)
        finally:
            self.LocalFree(value)

    def current_sid(self):
        token = C.c_void_p()
        if not self.OpenThreadToken(self.GetCurrentThread(), 0x8, True, C.byref(token)):
            if C.get_last_error() != 1008:  # ERROR_NO_TOKEN, no thread impersonation.
                _fail("owner_identity_unverified")
            if not self.OpenProcessToken(self.GetCurrentProcess(), 0x8, C.byref(token)):
                _fail("owner_identity_unverified")
        try:
            size = W.DWORD()
            self.GetTokenInformation(token, 1, None, 0, C.byref(size))
            if not 0 < size.value <= 65536:
                _fail("owner_identity_unverified")
            buffer = C.create_string_buffer(size.value)
            if not self.GetTokenInformation(token, 1, buffer, size, C.byref(size)):
                _fail("owner_identity_unverified")
            return self.sid_text(C.c_void_p.from_buffer(buffer).value)
        finally:
            if not self.CloseHandle(token):
                _fail("private_handle_close_failed")

    @contextmanager
    def descriptor(self, sid, *, directory):
        flags = "OICI" if directory else ""
        value = C.c_void_p()
        if not self.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"O:{sid}D:P(A;{flags};FA;;;{sid})", 1, C.byref(value), None
        ):
            _fail("owner_acl_unverified")
        try:
            yield _SA(C.sizeof(_SA), value, False)
        finally:
            self.LocalFree(value)

    def info(self, handle, *, directory):
        value = _FILE_INFO()
        if not self.GetFileInformationByHandle(handle, C.byref(value)):
            _fail("evidence_identity_unverified")
        if value.attributes & _REPARSE:
            _fail("reparse_path_rejected")
        if bool(value.attributes & _DIRECTORY) != directory:
            _fail("evidence_object_type")
        if not directory and value.links != 1:
            _fail("artifact_hardlink_rejected")
        return value.volume, (value.index_high << 32) | value.index_low

    @contextmanager
    def opened(self, path, *, directory, access=_READ_ATTRIBUTES | _READ_CONTROL):
        # No FILE_SHARE_DELETE: hold object identity while observing/writing.
        handle = self.CreateFileW(str(path), access, 3, None, 3, 0x02200000, None)
        if handle == _INVALID_HANDLE:
            _fail("evidence_object_unavailable")
        try:
            self.info(handle, directory=directory)
            yield handle
        finally:
            if not self.CloseHandle(handle):
                _fail("private_handle_close_failed")

    def verify_acl(self, handle, sid, *, directory=False, inherited=False):
        owner, dacl, descriptor = C.c_void_p(), C.c_void_p(), C.c_void_p()
        if self.GetSecurityInfo(
            handle, 1, 0x5, C.byref(owner), None, C.byref(dacl), None, C.byref(descriptor)
        ):
            _fail("owner_acl_unverified")
        try:
            control, revision = W.WORD(), W.DWORD()
            if (
                not self.GetSecurityDescriptorControl(
                    descriptor, C.byref(control), C.byref(revision)
                )
                or not control.value & 0x4
                or not dacl
                or bool(control.value & 0x1000) == inherited
                or self.sid_text(owner) != sid
            ):
                _fail("owner_acl_unverified")
            size = _ACL_SIZE()
            ace = C.c_void_p()
            if (
                not self.GetAclInformation(dacl, C.byref(size), C.sizeof(size), 2)
                or size.count != 1
                or not self.GetAce(dacl, 0, C.byref(ace))
            ):
                _fail("owner_acl_unverified")
            header = _ACE_HEADER.from_address(ace.value)
            expected_flags = 3 if directory else (0x10 if inherited else 0)
            if header.kind != 0 or header.flags != expected_flags or header.size < 20:
                _fail("owner_acl_unverified")
            mask = W.DWORD.from_address(ace.value + 4).value
            ace_sid = ace.value + 8
            if (
                mask != _FULL_CONTROL
                or not self.IsValidSid(ace_sid)
                or self.GetLengthSid(ace_sid) + 8 != header.size
                or self.sid_text(ace_sid) != sid
            ):
                _fail("owner_acl_unverified")
        finally:
            self.LocalFree(descriptor)


_API = None


def _api():
    global _API
    if _API is None:
        try:
            _API = _Win32()
        except PrivateArtifactError:
            raise
        except Exception:
            _fail("windows_security_api_unavailable")
    return _API


@contextmanager
def _ancestors(path, deadline=None):
    """Lock each existing ancestor against rename and reject reparse/repo paths."""
    api = _api()
    from contextlib import ExitStack

    with ExitStack() as stack:
        for ancestor in reversed(path.parents):
            _deadline(deadline)
            stack.enter_context(api.opened(ancestor, directory=True, access=_READ_ATTRIBUTES))
            if ancestor.name.lower() == ".git" or os.path.lexists(ancestor / ".git"):
                _fail("repository_output_rejected")
        yield
        _deadline(deadline)


@dataclass(frozen=True)
class PrivateArtifactDirectory:
    """Volume serial/file ID binding; current SID is re-read on every operation."""

    path: Path
    device: int
    inode: int
    operation_deadline: object = None

    def with_deadline(self, deadline):
        _deadline(deadline)
        return replace(self, operation_deadline=deadline)

    @contextmanager
    def _verified(self):
        _deadline(self.operation_deadline)
        path = _path(self.path)
        api = _api()
        try:
            with _ancestors(path, self.operation_deadline), api.opened(
                path, directory=True
            ) as handle:
                if api.info(handle, directory=True) != (self.device, self.inode):
                    _fail("evidence_directory_changed")
                if path.name.lower() == ".git" or os.path.lexists(path / ".git"):
                    _fail("repository_output_rejected")
                sid = api.current_sid()
                api.verify_acl(handle, sid, directory=True)
                _deadline(self.operation_deadline)
                yield api, sid
                _deadline(self.operation_deadline)
        except PrivateArtifactError:
            raise
        except Exception:
            _fail("evidence_directory_unavailable")

    def verify(self):
        with self._verified():
            pass

    def prepare_child(self, name):
        name = _name(name)
        with self._verified():
            target = _path(self.path / name)
            if os.path.lexists(target):
                _fail("artifact_already_exists")
            return target

    def write_json(self, name, document):
        try:
            payload = (
                json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
            ).encode("utf-8")
        except Exception:
            _fail("finite_json_document_required")
        return self.write_bytes(name, payload)

    def write_bytes(self, name, payload):
        name = _name(name)
        if type(payload) is not bytes:
            _fail("bytes_required")
        if len(payload) > _MAX_BYTES:
            _fail("artifact_size_limit")
        with self._verified() as (api, sid):
            target = _path(self.path / name)
            if os.path.lexists(target):
                _fail("artifact_already_exists")
            with api.descriptor(sid, directory=False) as attributes:
                handle = api.CreateFileW(
                    str(target),
                    0x40000000 | _READ_CONTROL | _READ_ATTRIBUTES,
                    0,
                    C.byref(attributes),
                    1,
                    0x80200000,
                    None,
                )
            if handle == _INVALID_HANDLE:
                _fail("artifact_create_failed")
            try:
                api.info(handle, directory=False)
                api.verify_acl(handle, sid)
                offset = 0
                while offset < len(payload):
                    _deadline(self.operation_deadline)
                    chunk = payload[offset : offset + 1024 * 1024]
                    count = W.DWORD()
                    if not api.WriteFile(
                        handle, chunk, len(chunk), C.byref(count), None
                    ) or count.value != len(chunk):
                        _fail("artifact_write_failed")
                    offset += count.value
                if not api.FlushFileBuffers(handle):
                    _fail("artifact_flush_failed")
                _deadline(self.operation_deadline)
                api.verify_acl(handle, sid)
            finally:
                if not api.CloseHandle(handle):
                    _fail("private_handle_close_failed")
        return hashlib.sha256(payload).hexdigest()

    def verify_sqlite_scope(self, name, *, require_wal=False):
        """Check actual SQLite files, including existing WAL/SHM/rollback journal.

        Keep the SQLite connection open with WAL active for require_wal=True.
        These inherited files are intentionally not DACL-protected; their sole
        inherited full-control ACE must match this protected directory's owner.
        """
        name = _name(name)
        if type(require_wal) is not bool:
            _fail("invalid_sqlite_check")
        present = []
        with self._verified() as (api, sid):
            for suffix in ("", "-wal", "-shm", "-journal"):
                _deadline(self.operation_deadline)
                target = _path(self.path / (name + suffix))
                if not os.path.lexists(target):
                    if not suffix or (require_wal and suffix in {"-wal", "-shm"}):
                        _fail("sqlite_scope_incomplete")
                    continue
                with api.opened(target, directory=False) as handle:
                    api.verify_acl(handle, sid, inherited=True)
                present.append(name + suffix)
        return tuple(present)


def create_private_directory(path):
    path = _path(path)
    if path.name.lower() == ".git":
        _fail("repository_output_rejected")
    try:
        if os.path.lexists(path) or not path.parent.is_dir():
            _fail("new_evidence_directory_required")
        api = _api()
        with _ancestors(path):
            sid = api.current_sid()
            with api.descriptor(sid, directory=True) as attributes:
                if not api.CreateDirectoryW(str(path), C.byref(attributes)):
                    _fail("private_directory_creation_failed")
            with api.opened(path, directory=True) as handle:
                device, inode = api.info(handle, directory=True)
                api.verify_acl(handle, sid, directory=True)
            result = PrivateArtifactDirectory(path, device, inode)
            result.verify()
            return result
    except PrivateArtifactError:
        raise
    except Exception:
        _fail("private_directory_creation_failed")
