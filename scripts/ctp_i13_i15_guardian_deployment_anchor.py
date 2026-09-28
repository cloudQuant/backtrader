"""Fixed, fail-closed deployment anchor for the inert I13/I15 guardian.

This module is not a deployment tool and never creates the ProgramData tree,
generates a secret, reads a trading configuration, imports a CTP SDK, or starts
a process.  The production descriptor digest is deliberately unset in this
checkout.  Until a separately reviewed deployment supplies a nonzero
code-owned pin, :func:`load_fixed_deployment_anchor` rejects before opening
ProgramData or any runtime/configuration file.

When pinned, the loader uses the Windows KnownFolder API (never environment or
CWD), validates the fixed descriptor and nested parent trust descriptor,
checks owners/ACLs from retained handles, invokes the existing parent-launch
preflight and source sealer, and retains those seals through explicit close.
The worker, bootstrap, and three service-role source paths plus receipt
location are code-owned constants. Those role bytes come from the sealed
source manifest and are read through its retained lease. The service
authentication key is read only from the fixed protected ``authkey.bin``
handle and is never stored on the returned anchor or included in its repr.

The descriptor also binds the fixed ``runtime.json`` closure manifest. Its
code-owned digest is unset here, so runtime closure sealing cannot succeed
from a local descriptor alone.

This is an offline candidate contract, not an accepted production anchor.
Windows owner/DACL policy and the deployment pins still require independent
review on the target deployment host. The protected source must include the
fixed worker and bootstrap in the I13 source manifest before the anchor can be
returned. The external dependency-manifest pin is also unset, so no runnable
anchor is available in this tree.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import ntpath
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from types import MappingProxyType
from typing import Mapping, Optional, Sequence


DEPLOYMENT_SCHEMA = "ctp_i13_i15_guardian_deployment.v2"
DEPLOYMENT_OPERATION = "ctp_readonly_preflight"
WORKER_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_preflight_worker.py"
BOOTSTRAP_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
REQUEST_COORDINATOR_RELATIVE_PATH = (
    "scripts/ctp_i13_i15_readonly_request_coordinator.py"
)
RECEIPT_WRITER_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_receipt_writer.py"
TOKEN_BOOTSTRAP_RELATIVE_PATH = "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
_FIXED_ROLE_SOURCE_PATHS = frozenset(
    {
        REQUEST_COORDINATOR_RELATIVE_PATH,
        RECEIPT_WRITER_RELATIVE_PATH,
        TOKEN_BOOTSTRAP_RELATIVE_PATH,
    }
)
FIXED_PROGRAMDATA_RELATIVE = PureWindowsPath("Backtrader", "Iteration41", "ctp-readonly-guardian")
FIXED_DESCRIPTOR_NAME = "deployment.json"
FIXED_AUTHKEY_NAME = "authkey.bin"
FIXED_DEPENDENCY_MANIFEST_NAME = "dependencies.json"
FIXED_RUNTIME_MANIFEST_NAME = "runtime.json"
FIXED_PYCACHE_PREFIX_NAME = "disabled-bytecode-cache"
FIXED_RECEIPT_DIRECTORY = "receipts"
FIXED_RECEIPT_SCOPE = "ctp_i13_i15.readonly_preflight.v1"
FIXED_SERVICE_NAME = "BacktraderCtpReadonlyGuardian"
_MAX_DESCRIPTOR_BYTES = 64 * 1024
_MAX_PARENT_DESCRIPTOR_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,14}[0-9]+\Z")
_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_PIPE_RE = re.compile(r"\\\\\\.\\pipe\\backtrader-ctp-i13-i15-[0-9a-f]{32}\Z")
_PIPE_PREFIX = r"\\.\pipe\backtrader-ctp-i13-i15-"
_PIPE_RE = re.compile(re.escape(_PIPE_PREFIX) + r"[0-9a-f]{32}\Z")
_ZERO_SHA256 = "0" * 64
_ANCHOR_FACTORY_TOKEN = object()
_CLIENT_BINDING_FACTORY_TOKEN = object()

# These values are intentionally unset.  Updating them is a code/deployment
# trust change that requires a reviewed source bundle, pin and protected
# ProgramData descriptor/key; local descriptor contents cannot set these pins.
GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256 = _ZERO_SHA256
# The worker's isolated ``-I -S`` dependency closure has not been separately
# pinned.  A source SHA alone cannot establish the PyYAML/site-package closure.
WORKER_DEPENDENCY_MANIFEST_SHA256 = _ZERO_SHA256
RUNTIME_MANIFEST_SHA256 = _ZERO_SHA256

_SYSTEM_SID = "S-1-5-18"
_ADMINISTRATORS_SID = "S-1-5-32-544"
_BROAD_KEY_READER_SIDS = frozenset(
    {
        "S-1-1-0",  # Everyone
        "S-1-5-2",  # Network
        "S-1-5-4",  # Interactive
        "S-1-5-6",  # Service
        "S-1-5-7",  # Anonymous
        "S-1-5-11",  # Authenticated Users
        "S-1-5-14",  # Remote Interactive Logon
        "S-1-5-32-545",  # Builtin Users
    }
)
_GENERIC_ALL = 0x10000000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_WRITE_DATA = 0x00000002
_FILE_APPEND_DATA = 0x00000004
_FILE_WRITE_EA = 0x00000010
_FILE_DELETE_CHILD = 0x00000040
_FILE_WRITE_ATTRIBUTES = 0x00000100
_FILE_READ_DATA = 0x00000001
_FILE_READ_EA = 0x00000008
_DELETE = 0x00010000
_WRITE_DAC = 0x00040000
_WRITE_OWNER = 0x00080000
_DANGEROUS_WRITE_MASK = (
    _GENERIC_ALL
    | _GENERIC_WRITE
    | _FILE_WRITE_DATA
    | _FILE_APPEND_DATA
    | _FILE_WRITE_EA
    | _FILE_DELETE_CHILD
    | _FILE_WRITE_ATTRIBUTES
    | _DELETE
    | _WRITE_DAC
    | _WRITE_OWNER
)
_KEY_DATA_READ_MASK = _GENERIC_READ | _GENERIC_ALL | _FILE_READ_DATA | _FILE_READ_EA


class DeploymentAnchorError(ValueError):
    """A redacted, fail-closed deployment-anchor rejection."""


def _sha256(value: object, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None or value == _ZERO_SHA256:
        raise DeploymentAnchorError(reason)
    return value


def _duplicate_rejecting_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentAnchorError("descriptor_duplicate_key")
        result[key] = value
    return result


def _canonical_windows_path(value: object, reason: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 1024
        or "/" in value
        or not ntpath.isabs(value)
        or ntpath.normpath(value) != value
        or any(part in {".", ".."} for part in value.split("\\"))
    ):
        raise DeploymentAnchorError(reason)
    return value


@dataclass(frozen=True)
class _ParsedDeployment:
    source_root: str
    source_manifest_sha256: str
    python_executable: str
    python_sha256: str
    python_version: str
    python_architecture: str
    service_sid: str
    client_sid: str
    worker_sha256: str
    worker_dependency_manifest_sha256: str
    runtime_manifest_sha256: str
    pipe_address: str
    auth_key_sha256: str
    parent_trust_raw: bytes
    parent_trust_sha256: str
    descriptor_sha256: str


def _parse_deployment_descriptor(
    raw: bytes,
    *,
    expected_sha256: str,
    expected_worker_dependency_sha256: Optional[str] = None,
    expected_runtime_manifest_sha256: Optional[str] = None,
) -> _ParsedDeployment:
    """Parse the fixed canonical descriptor; tests may exercise only this pure boundary."""

    expected = _sha256(expected_sha256, "deployment_descriptor_pin_unset")
    if type(raw) is not bytes or not raw or len(raw) > _MAX_DESCRIPTOR_BYTES:
        raise DeploymentAnchorError("deployment_descriptor_size_invalid")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise DeploymentAnchorError("deployment_descriptor_digest_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_rejecting_pairs)
    except DeploymentAnchorError:
        raise
    except (UnicodeError, TypeError, ValueError):
        raise DeploymentAnchorError("deployment_descriptor_invalid") from None
    required = {
        "schema",
        "operation",
        "source_root",
        "source_manifest_sha256",
        "python",
        "service_sid",
        "client_sid",
        "worker_sha256",
        "worker_dependency_manifest_sha256",
        "runtime_manifest_sha256",
        "pipe_address",
        "auth_key_sha256",
        "parent_trust_descriptor_b64",
        "parent_trust_descriptor_sha256",
    }
    if type(value) is not dict or set(value) != required:
        raise DeploymentAnchorError("deployment_descriptor_fields_invalid")
    if value["schema"] != DEPLOYMENT_SCHEMA or value["operation"] != DEPLOYMENT_OPERATION:
        raise DeploymentAnchorError("deployment_operation_binding_invalid")
    source_root = _canonical_windows_path(value["source_root"], "source_root_invalid")
    python = value["python"]
    if type(python) is not dict or set(python) != {
        "executable",
        "sha256",
        "version",
        "architecture",
    }:
        raise DeploymentAnchorError("deployment_python_fields_invalid")
    executable = _canonical_windows_path(python["executable"], "python_executable_invalid")
    if python["version"] != "3.11.5" or python["architecture"] != "AMD64":
        raise DeploymentAnchorError("deployment_python_baseline_invalid")
    service_sid = value["service_sid"]
    client_sid = value["client_sid"]
    if (
        type(service_sid) is not str
        or _SID_RE.fullmatch(service_sid) is None
        or type(client_sid) is not str
        or _SID_RE.fullmatch(client_sid) is None
    ):
        raise DeploymentAnchorError("deployment_sid_invalid")
    pipe_address = value["pipe_address"]
    if type(pipe_address) is not str or _PIPE_RE.fullmatch(pipe_address) is None:
        raise DeploymentAnchorError("deployment_pipe_address_invalid")
    parent_b64 = value["parent_trust_descriptor_b64"]
    if type(parent_b64) is not str or len(parent_b64) > 4 * _MAX_PARENT_DESCRIPTOR_BYTES:
        raise DeploymentAnchorError("parent_trust_descriptor_invalid")
    try:
        parent_raw = base64.b64decode(parent_b64.encode("ascii"), validate=True)
    except (UnicodeError, ValueError, TypeError):
        raise DeploymentAnchorError("parent_trust_descriptor_invalid") from None
    if not parent_raw or len(parent_raw) > _MAX_PARENT_DESCRIPTOR_BYTES:
        raise DeploymentAnchorError("parent_trust_descriptor_invalid")
    parent_sha = _sha256(
        value["parent_trust_descriptor_sha256"], "parent_trust_descriptor_pin_invalid"
    )
    if not hmac.compare_digest(hashlib.sha256(parent_raw).hexdigest(), parent_sha):
        raise DeploymentAnchorError("parent_trust_descriptor_digest_mismatch")
    dependency_pin = _sha256(
        WORKER_DEPENDENCY_MANIFEST_SHA256
        if expected_worker_dependency_sha256 is None
        else expected_worker_dependency_sha256,
        "worker_dependency_closure_pin_unset",
    )
    dependency_digest = _sha256(
        value["worker_dependency_manifest_sha256"],
        "worker_dependency_manifest_pin_invalid",
    )
    if not hmac.compare_digest(dependency_pin, dependency_digest):
        raise DeploymentAnchorError("worker_dependency_manifest_pin_mismatch")
    runtime_pin = _sha256(
        RUNTIME_MANIFEST_SHA256
        if expected_runtime_manifest_sha256 is None
        else expected_runtime_manifest_sha256,
        "runtime_manifest_pin_unset",
    )
    runtime_digest = _sha256(value["runtime_manifest_sha256"], "runtime_manifest_pin_invalid")
    if not hmac.compare_digest(runtime_pin, runtime_digest):
        raise DeploymentAnchorError("runtime_manifest_pin_mismatch")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if raw != canonical:
        raise DeploymentAnchorError("deployment_descriptor_not_canonical")
    return _ParsedDeployment(
        source_root=source_root,
        source_manifest_sha256=_sha256(
            value["source_manifest_sha256"], "source_manifest_pin_invalid"
        ),
        python_executable=executable,
        python_sha256=_sha256(python["sha256"], "python_executable_pin_invalid"),
        python_version=python["version"],
        python_architecture=python["architecture"],
        service_sid=service_sid,
        client_sid=client_sid,
        worker_sha256=_sha256(value["worker_sha256"], "worker_pin_invalid"),
        worker_dependency_manifest_sha256=dependency_digest,
        runtime_manifest_sha256=runtime_digest,
        pipe_address=pipe_address,
        auth_key_sha256=_sha256(value["auth_key_sha256"], "auth_key_pin_invalid"),
        parent_trust_raw=parent_raw,
        parent_trust_sha256=parent_sha,
        descriptor_sha256=actual,
    )


def _validate_acl_facts(
    *,
    owner_sid: str,
    aces: Sequence[tuple[int, int, int, str]],
    trusted_sids: frozenset[str],
    allowed_read_sids: Optional[frozenset[str]] = None,
) -> None:
    """Pure conservative policy check for (type, flags, mask, SID) ACE facts."""

    if owner_sid not in {_SYSTEM_SID, _ADMINISTRATORS_SID}:
        raise DeploymentAnchorError("protected_path_owner_untrusted")
    if type(aces) not in (tuple, list) or not aces:
        raise DeploymentAnchorError("protected_path_dacl_invalid")
    allowed_flags = 0x01 | 0x02 | 0x04 | 0x08 | 0x10 | 0x40 | 0x80
    for ace in aces:
        if (
            type(ace) is not tuple
            or len(ace) != 4
            or type(ace[0]) is not int
            or type(ace[1]) is not int
            or type(ace[2]) is not int
            or type(ace[3]) is not str
            or ace[0] not in (0, 1)
            or ace[1] & ~allowed_flags
            or _SID_RE.fullmatch(ace[3]) is None
        ):
            raise DeploymentAnchorError("protected_path_unknown_ace")
        ace_type, _, access_mask, sid = ace
        if ace_type == 0 and sid not in trusted_sids and access_mask & _DANGEROUS_WRITE_MASK:
            raise DeploymentAnchorError("protected_path_untrusted_write_access")
        if (
            ace_type == 0
            and allowed_read_sids is not None
            and sid not in allowed_read_sids
            and access_mask & _KEY_DATA_READ_MASK
        ):
            raise DeploymentAnchorError("protected_path_untrusted_read_access")


def _auth_key_read_policy(
    path: str, service_sid: str, client_sid: str
) -> dict[str, frozenset[str]]:
    """Allow key-data reads only to the OS trust principals and fixed service."""

    canonical = _canonical_windows_path(path, "auth_key_path_invalid")
    if (
        type(service_sid) is not str
        or _SID_RE.fullmatch(service_sid) is None
        or service_sid in _BROAD_KEY_READER_SIDS
        or service_sid in {_SYSTEM_SID, _ADMINISTRATORS_SID}
        or type(client_sid) is not str
        or _SID_RE.fullmatch(client_sid) is None
        or client_sid == service_sid
    ):
        raise DeploymentAnchorError("deployment_service_sid_invalid")
    return {canonical: frozenset({_SYSTEM_SID, _ADMINISTRATORS_SID, service_sid})}


def _canonical_service_sid(value: object) -> str:
    """Require the Windows NT SERVICE SID shape for this fixed service name."""

    if type(value) is not str or _SID_RE.fullmatch(value) is None:
        raise DeploymentAnchorError("guardian_service_sid_invalid")
    parts = value.split("-")
    if len(parts) != 9 or parts[:4] != ["S", "1", "5", "80"]:
        raise DeploymentAnchorError("guardian_service_sid_invalid")
    try:
        subauthorities = tuple(int(part) for part in parts[4:])
    except ValueError:
        raise DeploymentAnchorError("guardian_service_sid_invalid") from None
    if any(number < 0 or number > 0xFFFFFFFF for number in subauthorities):
        raise DeploymentAnchorError("guardian_service_sid_invalid")
    return value


def _assert_fixed_service_sid(descriptor_sid: str, derived_sid: str) -> str:
    """Bind descriptor consistency to the SID derived from the code-owned name."""

    descriptor = _canonical_service_sid(descriptor_sid)
    derived = _canonical_service_sid(derived_sid)
    if not hmac.compare_digest(descriptor, derived):
        raise DeploymentAnchorError("guardian_service_identity_mismatch")
    return derived


def _lookup_fixed_service_sid() -> str:
    """Resolve the fixed ``NT SERVICE\\...`` account through Windows LSA."""

    if os.name != "nt" or sys.platform != "win32":
        raise DeploymentAnchorError("windows_required")
    account_name = "NT SERVICE\\" + FIXED_SERVICE_NAME
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        lookup = advapi32.LookupAccountNameW
        lookup.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lookup.restype = ctypes.c_int
        sid_size = ctypes.c_uint32(0)
        domain_size = ctypes.c_uint32(0)
        sid_use = ctypes.c_uint32(0)
        lookup(
            None,
            account_name,
            None,
            ctypes.byref(sid_size),
            None,
            ctypes.byref(domain_size),
            ctypes.byref(sid_use),
        )
        error = ctypes.get_last_error()
        if error not in (122, 234) or sid_size.value <= 0:
            raise DeploymentAnchorError("guardian_service_sid_lookup_failed")
        sid_buffer = ctypes.create_string_buffer(sid_size.value)
        domain_buffer = ctypes.create_unicode_buffer(max(1, domain_size.value))
        if not lookup(
            None,
            account_name,
            sid_buffer,
            ctypes.byref(sid_size),
            domain_buffer,
            ctypes.byref(domain_size),
            ctypes.byref(sid_use),
        ):
            raise DeploymentAnchorError("guardian_service_sid_lookup_failed")
        sid_text = ctypes.c_wchar_p()
        convert = advapi32.ConvertSidToStringSidW
        convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        convert.restype = ctypes.c_int
        if not convert(ctypes.cast(sid_buffer, ctypes.c_void_p), ctypes.byref(sid_text)):
            raise DeploymentAnchorError("guardian_service_sid_lookup_failed")
        try:
            return _canonical_service_sid(sid_text.value)
        finally:
            local_free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(sid_text, ctypes.c_void_p))
    except DeploymentAnchorError:
        raise
    except BaseException:
        raise DeploymentAnchorError("guardian_service_sid_lookup_failed") from None


class _WinFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", ctypes.c_uint32),
        ("ftCreationTimeLow", ctypes.c_uint32),
        ("ftCreationTimeHigh", ctypes.c_uint32),
        ("ftLastAccessTimeLow", ctypes.c_uint32),
        ("ftLastAccessTimeHigh", ctypes.c_uint32),
        ("ftLastWriteTimeLow", ctypes.c_uint32),
        ("ftLastWriteTimeHigh", ctypes.c_uint32),
        ("dwVolumeSerialNumber", ctypes.c_uint32),
        ("nFileSizeHigh", ctypes.c_uint32),
        ("nFileSizeLow", ctypes.c_uint32),
        ("nNumberOfLinks", ctypes.c_uint32),
        ("nFileIndexHigh", ctypes.c_uint32),
        ("nFileIndexLow", ctypes.c_uint32),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", ctypes.c_uint32),
        ("AclBytesInUse", ctypes.c_uint32),
        ("AclBytesFree", ctypes.c_uint32),
    ]


class _FileIdBothDirectoryInfo(ctypes.Structure):
    """Windows ``FILE_ID_BOTH_DIR_INFO`` prefix used for handle enumeration."""

    _fields_ = [
        ("NextEntryOffset", ctypes.c_uint32),
        ("FileIndex", ctypes.c_uint32),
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("AllocationSize", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
        ("FileNameLength", ctypes.c_uint32),
        ("EaSize", ctypes.c_uint32),
        ("ShortNameLength", ctypes.c_byte),
        ("ShortName", ctypes.c_wchar * 12),
        ("FileId", ctypes.c_int64),
        ("FileName", ctypes.c_wchar * 1),
    ]


_FILE_ID_BOTH_DIRECTORY_INFO = 0x0A
_FILE_ID_BOTH_DIRECTORY_RESTART_INFO = 0x0B
_ERROR_NO_MORE_FILES = 18
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_ATTRIBUTE_DEVICE = 0x00000040
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_MAX_DIRECTORY_ENTRIES = 100_000


def _parse_file_id_both_directory_buffer(raw: bytes) -> tuple[str, ...]:
    """Parse one bounded Win32 directory-information buffer fail-closed."""

    if type(raw) is not bytes or len(raw) < ctypes.sizeof(_FileIdBothDirectoryInfo):
        raise DeploymentAnchorError("dependency_directory_buffer_invalid")
    names = []
    offset = 0
    while True:
        if offset + _FileIdBothDirectoryInfo.FileName.offset > len(raw):
            raise DeploymentAnchorError("dependency_directory_buffer_invalid")
        try:
            entry = _FileIdBothDirectoryInfo.from_buffer_copy(raw[offset:])
        except (ValueError, TypeError):
            raise DeploymentAnchorError("dependency_directory_buffer_invalid") from None
        name_length = int(entry.FileNameLength)
        name_offset = offset + _FileIdBothDirectoryInfo.FileName.offset
        if (
            name_length <= 0
            or name_length % 2
            or name_offset + name_length > len(raw)
            or entry.FileAttributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DEVICE)
        ):
            raise DeploymentAnchorError("dependency_directory_entry_invalid")
        try:
            name = raw[name_offset : name_offset + name_length].decode("utf-16-le", "strict")
        except UnicodeError:
            raise DeploymentAnchorError("dependency_directory_entry_invalid") from None
        if not name or "/" in name or "\\" in name or "\x00" in name:
            raise DeploymentAnchorError("dependency_directory_entry_invalid")
        if name in {".", ".."}:
            if not entry.FileAttributes & 0x00000010:
                raise DeploymentAnchorError("dependency_directory_entry_invalid")
        else:
            names.append(name)
            if len(names) > _MAX_DIRECTORY_ENTRIES:
                raise DeploymentAnchorError("dependency_directory_entry_limit")

        next_offset = int(entry.NextEntryOffset)
        if next_offset == 0:
            break
        if (
            next_offset % 8
            or next_offset < _FileIdBothDirectoryInfo.FileName.offset + name_length
            or offset + next_offset + ctypes.sizeof(_FileIdBothDirectoryInfo) > len(raw)
        ):
            raise DeploymentAnchorError("dependency_directory_buffer_invalid")
        offset += next_offset
    return tuple(names)


@dataclass
class _ProtectedEntry:
    path: str
    handle: int
    identity: tuple[int, int]
    is_directory: bool
    trusted_sids: frozenset[str]
    allowed_read_sids: Optional[frozenset[str]]
    share_write: bool
    can_list_directory: bool


class _ProtectedWindowsPaths:
    """Retain ACL-checked Windows handles; failed closes remain reachable."""

    def __init__(self, trusted_sids: frozenset[str]) -> None:
        self._trusted_sids = trusted_sids
        self._entries: dict[str, _ProtectedEntry] = {}
        self._closed = False
        self._poisoned = False
        self._orphan_handles: list[int] = []
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    @staticmethod
    def _key(path: str) -> str:
        return ntpath.normcase(ntpath.normpath(path))

    def add_paths(
        self,
        paths: Sequence[str],
        *,
        directory_paths: frozenset[str] = frozenset(),
        writable_paths: frozenset[str] = frozenset(),
        listable_directory_paths: frozenset[str] = frozenset(),
        writer_sids_by_path: Optional[Mapping[str, frozenset[str]]] = None,
        reader_sids_by_path: Optional[Mapping[str, frozenset[str]]] = None,
    ) -> None:
        if self._closed or self._poisoned:
            raise DeploymentAnchorError("protected_path_lease_unavailable")
        directory_keys = {self._key(item) for item in directory_paths}
        writable_keys = {self._key(item) for item in writable_paths}
        listable_keys = {self._key(item) for item in listable_directory_paths}
        if not listable_keys.issubset(directory_keys):
            raise DeploymentAnchorError("protected_path_listable_target_not_directory")
        writer_map = {
            self._key(path): principals for path, principals in (writer_sids_by_path or {}).items()
        }
        reader_map = {
            self._key(path): principals for path, principals in (reader_sids_by_path or {}).items()
        }
        for path in paths:
            canonical = _canonical_windows_path(path, "protected_path_invalid")
            parts = PureWindowsPath(canonical).parts
            if len(parts) < 2:
                raise DeploymentAnchorError("protected_path_invalid")
            current = parts[0]
            self._open_one(current, is_directory=True)
            for index, part in enumerate(parts[1:]):
                current = ntpath.join(current, part)
                final = index == len(parts[1:]) - 1
                final_is_directory = self._key(canonical) in directory_keys
                key = self._key(current)
                self._open_one(
                    current,
                    is_directory=(not final or final_is_directory),
                    trusted_sids=writer_map.get(key, self._trusted_sids),
                    allowed_read_sids=reader_map.get(key),
                    share_write=key in writable_keys,
                    can_list_directory=(
                        key in listable_keys
                        or (key in self._entries and self._entries[key].can_list_directory)
                    ),
                )

    def _open_one(
        self,
        path: str,
        *,
        is_directory: bool,
        trusted_sids: Optional[frozenset[str]] = None,
        allowed_read_sids: Optional[frozenset[str]] = None,
        share_write: bool = False,
        can_list_directory: bool = False,
    ) -> None:
        key = self._key(path)
        trusted_sids = self._trusted_sids if trusted_sids is None else trusted_sids
        if key in self._entries:
            existing = self._entries[key]
            if (
                existing.is_directory != is_directory
                or existing.trusted_sids != trusted_sids
                or existing.allowed_read_sids != allowed_read_sids
                or existing.share_write != share_write
            ):
                raise DeploymentAnchorError("protected_path_kind_conflict")
            if can_list_directory and not existing.can_list_directory:
                raise DeploymentAnchorError("protected_path_kind_conflict")
            return
        kernel = self._kernel32
        open_file = kernel.CreateFileW
        open_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        open_file.restype = ctypes.c_void_p
        access = 0x00020000 | 0x00000080  # READ_CONTROL | FILE_READ_ATTRIBUTES
        if not is_directory:
            access |= 0x80000000  # GENERIC_READ
        elif can_list_directory:
            access |= _FILE_LIST_DIRECTORY
        flags = 0x00200000 | 0x02000000  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        share = 0x00000001 | (0x00000002 if share_write else 0)
        raw = open_file(path, access, share, None, 3, flags, None)
        if raw in (None, ctypes.c_void_p(-1).value):
            raise DeploymentAnchorError("protected_path_open_failed")
        handle = int(raw)
        try:
            info = self._file_information(handle)
            if info.dwFileAttributes & 0x00000400:  # FILE_ATTRIBUTE_REPARSE_POINT
                raise DeploymentAnchorError("protected_path_reparse_point")
            actual_directory = bool(info.dwFileAttributes & 0x00000010)
            if actual_directory != is_directory:
                raise DeploymentAnchorError("protected_path_kind_invalid")
            self._validate_handle_acl(
                handle,
                trusted_sids=trusted_sids,
                allowed_read_sids=allowed_read_sids,
            )
            identity = (
                int(info.dwVolumeSerialNumber),
                (int(info.nFileIndexHigh) << 32) | info.nFileIndexLow,
            )
            self._entries[key] = _ProtectedEntry(
                path,
                handle,
                identity,
                is_directory,
                trusted_sids,
                allowed_read_sids,
                share_write,
                can_list_directory,
            )
        except BaseException:
            if not self._close_raw(handle):
                self._poisoned = True
                _PENDING_PROTECTED_PATHS.add(self)
                raise DeploymentAnchorError("protected_path_cleanup_failed") from None
            raise

    def _file_information(self, handle: int) -> _WinFileInformation:
        info = _WinFileInformation()
        function = self._kernel32.GetFileInformationByHandle
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WinFileInformation)]
        function.restype = ctypes.c_int
        if not function(ctypes.c_void_p(handle), ctypes.byref(info)):
            raise DeploymentAnchorError("protected_path_identity_unavailable")
        return info

    def _sid_text(self, sid_pointer) -> str:
        if not sid_pointer:
            raise DeploymentAnchorError("protected_path_sid_unavailable")
        text = ctypes.c_wchar_p()
        convert = self._advapi32.ConvertSidToStringSidW
        convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        convert.restype = ctypes.c_int
        if not convert(sid_pointer, ctypes.byref(text)):
            raise DeploymentAnchorError("protected_path_sid_unavailable")
        try:
            return str(text.value)
        finally:
            local_free = self._kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(text, ctypes.c_void_p))

    def _validate_handle_acl(
        self,
        handle: int,
        *,
        trusted_sids: Optional[frozenset[str]] = None,
        allowed_read_sids: Optional[frozenset[str]] = None,
    ) -> None:
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        security_descriptor = ctypes.c_void_p()
        get_security = self._advapi32.GetSecurityInfo
        get_security.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        get_security.restype = ctypes.c_uint32
        result = get_security(
            ctypes.c_void_p(handle),
            1,  # SE_FILE_OBJECT
            0x00000001 | 0x00000004,  # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(security_descriptor),
        )
        if result != 0 or not security_descriptor.value or not dacl.value:
            raise DeploymentAnchorError("protected_path_dacl_unavailable")
        try:
            info = _AclSizeInformation()
            get_acl = self._advapi32.GetAclInformation
            get_acl.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_int,
            ]
            get_acl.restype = ctypes.c_int
            if (
                not get_acl(
                    dacl,
                    ctypes.byref(info),
                    ctypes.sizeof(info),
                    2,  # AclSizeInformation
                )
                or info.AceCount > 4096
            ):
                raise DeploymentAnchorError("protected_path_dacl_invalid")
            aces = []
            get_ace = self._advapi32.GetAce
            get_ace.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
            get_ace.restype = ctypes.c_int
            for index in range(int(info.AceCount)):
                ace_pointer = ctypes.c_void_p()
                if not get_ace(dacl, index, ctypes.byref(ace_pointer)) or not ace_pointer.value:
                    raise DeploymentAnchorError("protected_path_ace_unavailable")
                raw = ctypes.cast(ace_pointer, ctypes.POINTER(ctypes.c_ubyte))
                ace_type = int(raw[0])
                ace_flags = int(raw[1])
                if ace_type not in (0, 1):
                    raise DeploymentAnchorError("protected_path_unknown_ace")
                mask = ctypes.cast(
                    ctypes.c_void_p(ace_pointer.value + 4), ctypes.POINTER(ctypes.c_uint32)
                ).contents.value
                sid_pointer = ctypes.c_void_p(ace_pointer.value + 8)
                aces.append((ace_type, ace_flags, int(mask), self._sid_text(sid_pointer)))
            self_sid = self._sid_text(owner)
            _validate_acl_facts(
                owner_sid=self_sid,
                aces=aces,
                trusted_sids=self._trusted_sids if trusted_sids is None else trusted_sids,
                allowed_read_sids=allowed_read_sids,
            )
        finally:
            local_free = self._kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(security_descriptor)

    def read_file(self, path: str, *, max_bytes: int) -> bytes:
        if self._closed or self._poisoned:
            raise DeploymentAnchorError("protected_path_lease_unavailable")
        key = self._key(_canonical_windows_path(path, "protected_path_invalid"))
        entry = self._entries.get(key)
        if entry is None or entry.is_directory:
            raise DeploymentAnchorError("protected_file_not_leased")
        info = self._file_information(entry.handle)
        identity = (
            int(info.dwVolumeSerialNumber),
            (int(info.nFileIndexHigh) << 32) | info.nFileIndexLow,
        )
        if identity != entry.identity or info.dwFileAttributes & 0x00000400:
            raise DeploymentAnchorError("protected_file_identity_changed")
        self._validate_handle_acl(
            entry.handle,
            trusted_sids=entry.trusted_sids,
            allowed_read_sids=entry.allowed_read_sids,
        )
        size = (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow)
        if size > max_bytes:
            raise DeploymentAnchorError("protected_file_size_invalid")
        seek = self._kernel32.SetFilePointerEx
        seek.argtypes = [
            ctypes.c_void_p,
            ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong),
            ctypes.c_uint32,
        ]
        seek.restype = ctypes.c_int
        position = ctypes.c_longlong()
        if not seek(ctypes.c_void_p(entry.handle), 0, ctypes.byref(position), 0):
            raise DeploymentAnchorError("protected_file_read_failed")
        buffer = ctypes.create_string_buffer(size)
        read = self._kernel32.ReadFile
        read.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        read.restype = ctypes.c_int
        count = ctypes.c_uint32()
        if size and not read(
            ctypes.c_void_p(entry.handle), buffer, size, ctypes.byref(count), None
        ):
            raise DeploymentAnchorError("protected_file_read_failed")
        if count.value != size:
            raise DeploymentAnchorError("protected_file_read_incomplete")
        after = self._file_information(entry.handle)
        after_identity = (
            int(after.dwVolumeSerialNumber),
            (int(after.nFileIndexHigh) << 32) | int(after.nFileIndexLow),
        )
        if (
            after_identity != entry.identity
            or ((after.nFileSizeHigh << 32) | after.nFileSizeLow) != size
        ):
            raise DeploymentAnchorError("protected_file_identity_changed")
        return buffer.raw[:size]

    def verify_current(self) -> None:
        if self._closed or self._poisoned:
            raise DeploymentAnchorError("protected_path_lease_unavailable")
        for entry in self._entries.values():
            info = self._file_information(entry.handle)
            identity = (
                int(info.dwVolumeSerialNumber),
                (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow),
            )
            is_directory = bool(info.dwFileAttributes & 0x00000010)
            if (
                identity != entry.identity
                or is_directory != entry.is_directory
                or info.dwFileAttributes & 0x00000400
            ):
                raise DeploymentAnchorError("protected_path_identity_changed")
            self._validate_handle_acl(
                entry.handle,
                trusted_sids=entry.trusted_sids,
                allowed_read_sids=entry.allowed_read_sids,
            )

    def list_directory(self, directory_path: str) -> tuple[str, ...]:
        """Enumerate one explicitly retained directory through its handle.

        No path-based directory scan is used. The target directory was opened
        with ``FILE_LIST_DIRECTORY`` and without write/delete sharing. The
        retained identity and ACLs are checked before and after handle-based
        enumeration; malformed, reparse, device and case-colliding entries
        fail closed.
        """

        if self._closed or self._poisoned:
            raise DeploymentAnchorError("protected_path_lease_unavailable")
        directory = _canonical_windows_path(directory_path, "dependency_directory_invalid")
        entry = self._entries.get(self._key(directory))
        if entry is None or not entry.is_directory or not entry.can_list_directory:
            raise DeploymentAnchorError("dependency_directory_not_leased_for_listing")
        self.verify_current()

        query = self._kernel32.GetFileInformationByHandleEx
        query.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        query.restype = ctypes.c_int
        names = []
        info_class = _FILE_ID_BOTH_DIRECTORY_RESTART_INFO
        while True:
            buffer = ctypes.create_string_buffer(64 * 1024)
            if not query(ctypes.c_void_p(entry.handle), info_class, buffer, ctypes.sizeof(buffer)):
                error = ctypes.get_last_error()
                if error == _ERROR_NO_MORE_FILES:
                    break
                raise DeploymentAnchorError("dependency_directory_read_failed")
            info_class = _FILE_ID_BOTH_DIRECTORY_INFO
            names.extend(_parse_file_id_both_directory_buffer(buffer.raw))
            if len(names) > _MAX_DIRECTORY_ENTRIES:
                raise DeploymentAnchorError("dependency_directory_entry_limit")

        self.verify_current()
        folded = [name.casefold() for name in names]
        if len(folded) != len(set(folded)):
            raise DeploymentAnchorError("dependency_directory_case_collision")
        return tuple(sorted(names, key=lambda name: (name.casefold(), name)))

    def create_new_receipt(self, directory_path: str, request_id: str, raw: bytes) -> str:
        """Create one fixed-name receipt without replacement under a retained directory."""

        if self._closed or self._poisoned:
            raise DeploymentAnchorError("protected_path_lease_unavailable")
        if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
            raise DeploymentAnchorError("receipt_request_id_invalid")
        if type(raw) is not bytes or not raw or len(raw) > 1024 * 1024:
            raise DeploymentAnchorError("receipt_content_invalid")
        directory = _canonical_windows_path(directory_path, "receipt_directory_invalid")
        directory_key = self._key(directory)
        entry = self._entries.get(directory_key)
        if entry is None or not entry.is_directory or not entry.share_write:
            raise DeploymentAnchorError("receipt_directory_not_writable_lease")
        self.verify_current()
        filename = request_id + ".json"
        target = ntpath.join(directory, filename)
        create = self._kernel32.CreateFileW
        create.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create.restype = ctypes.c_void_p
        # CREATE_NEW is the Windows equivalent of O_CREAT|O_EXCL. The fixed
        # directory lease disallows delete sharing and the target itself is
        # opened without following a reparse point.
        access = 0x40000000 | 0x00000080  # GENERIC_WRITE | FILE_READ_ATTRIBUTES
        share = 0x00000001  # FILE_SHARE_READ only
        flags = 0x00200000 | 0x80000000  # OPEN_REPARSE_POINT | WRITE_THROUGH
        raw_handle = create(target, access, share, None, 1, flags, None)
        if raw_handle in (None, ctypes.c_void_p(-1).value):
            error = ctypes.get_last_error()
            if error in (80, 183):  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
                raise DeploymentAnchorError("receipt_already_exists")
            raise DeploymentAnchorError("receipt_create_failed")
        handle = int(raw_handle)
        try:
            info = self._file_information(handle)
            if info.dwFileAttributes & 0x00000400 or info.dwFileAttributes & 0x10:
                raise DeploymentAnchorError("receipt_file_kind_invalid")
            writer = self._kernel32.WriteFile
            writer.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p,
            ]
            writer.restype = ctypes.c_int
            offset = 0
            while offset < len(raw):
                chunk = raw[offset : offset + 64 * 1024]
                buffer = ctypes.create_string_buffer(chunk, len(chunk))
                written = ctypes.c_uint32()
                if not writer(
                    ctypes.c_void_p(handle),
                    buffer,
                    len(chunk),
                    ctypes.byref(written),
                    None,
                ) or written.value != len(chunk):
                    raise DeploymentAnchorError("receipt_write_failed")
                offset += written.value
            flush = self._kernel32.FlushFileBuffers
            flush.argtypes = [ctypes.c_void_p]
            flush.restype = ctypes.c_int
            if not flush(ctypes.c_void_p(handle)):
                raise DeploymentAnchorError("receipt_flush_failed")
            after = self._file_information(handle)
            size = (int(after.nFileSizeHigh) << 32) | int(after.nFileSizeLow)
            if size != len(raw) or after.dwFileAttributes & 0x00000400:
                raise DeploymentAnchorError("receipt_file_identity_changed")
            self.verify_current()
        except BaseException:
            if not self._close_raw(handle):
                self._orphan_handles.append(handle)
                self._poisoned = True
                _PENDING_PROTECTED_PATHS.add(self)
                raise DeploymentAnchorError("receipt_write_cleanup_failed") from None
            raise
        if not self._close_raw(handle):
            self._orphan_handles.append(handle)
            self._poisoned = True
            _PENDING_PROTECTED_PATHS.add(self)
            raise DeploymentAnchorError("receipt_close_failed")
        return target

    def _close_raw(self, handle: int) -> bool:
        close = self._kernel32.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = ctypes.c_int
        try:
            return bool(close(ctypes.c_void_p(handle)))
        except BaseException:
            return False

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        remaining_orphans = []
        for handle in reversed(tuple(self._orphan_handles)):
            if not self._close_raw(handle):
                failed = True
                remaining_orphans.append(handle)
        self._orphan_handles[:] = list(reversed(remaining_orphans))
        for key, entry in reversed(tuple(self._entries.items())):
            if self._close_raw(entry.handle):
                self._entries.pop(key, None)
            else:
                failed = True
        if failed:
            self._poisoned = True
            _PENDING_PROTECTED_PATHS.add(self)
            raise DeploymentAnchorError("protected_path_close_failed")
        self._closed = True
        self._poisoned = False
        _PENDING_PROTECTED_PATHS.discard(self)


_PENDING_PROTECTED_PATHS: set[_ProtectedWindowsPaths] = set()


def _program_data_path() -> str:
    if os.name != "nt":
        raise DeploymentAnchorError("windows_required")

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32),
            ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    folder = _GUID(
        0x62AB5D82,
        0xFDC1,
        0x4DC3,
        (ctypes.c_ubyte * 8)(0xA9, 0xDD, 0x07, 0x0D, 0x1D, 0x49, 0x5D, 0x97),
    )
    result = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    function = shell32.SHGetKnownFolderPath
    function.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    function.restype = ctypes.c_long
    if function(ctypes.byref(folder), 0, None, ctypes.byref(result)) != 0 or not result.value:
        raise DeploymentAnchorError("programdata_known_folder_unavailable")
    try:
        return _canonical_windows_path(result.value, "programdata_known_folder_invalid")
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        local_free = kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(result, ctypes.c_void_p))


def _fixed_paths(program_data: str) -> tuple[str, str, str, str, str, str]:
    fixed_root = ntpath.join(program_data, *(FIXED_PROGRAMDATA_RELATIVE.parts))
    descriptor = ntpath.join(fixed_root, FIXED_DESCRIPTOR_NAME)
    auth_key = ntpath.join(fixed_root, FIXED_AUTHKEY_NAME)
    dependency_manifest = ntpath.join(fixed_root, FIXED_DEPENDENCY_MANIFEST_NAME)
    runtime_manifest = ntpath.join(fixed_root, FIXED_RUNTIME_MANIFEST_NAME)
    receipt_root = ntpath.join(fixed_root, FIXED_RECEIPT_DIRECTORY)
    return fixed_root, descriptor, auth_key, dependency_manifest, runtime_manifest, receipt_root


class _RetainedDependencyPaths:
    """Relative-only retained handles rooted at the pinned venv directory."""

    __slots__ = ("__root", "__paths")

    def __init__(self, root: str, paths: _ProtectedWindowsPaths) -> None:
        self.__root = root
        self.__paths = paths

    @staticmethod
    def _relative(value: object) -> str:
        if type(value) is not str or not value or "\\" in value or ":" in value:
            raise DeploymentAnchorError("dependency_relative_path_invalid")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise DeploymentAnchorError("dependency_relative_path_invalid")
        return value

    def read_file(self, relative_path: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
            raise DeploymentAnchorError("dependency_read_bound_invalid")
        relative = self._relative(relative_path)
        path = ntpath.join(self.__root, relative.replace("/", "\\"))
        return self.__paths.read_file(path, max_bytes=max_bytes)

    def list_directory(self, relative_directory: str) -> tuple[str, ...]:
        """List a retained dependency directory; empty string means the fixed root."""

        if type(relative_directory) is not str:
            raise DeploymentAnchorError("dependency_relative_path_invalid")
        if relative_directory == "":
            path = self.__root
        else:
            relative = self._relative(relative_directory)
            path = ntpath.join(self.__root, relative.replace("/", "\\"))
        return self.__paths.list_directory(path)

    def verify_current(self) -> None:
        self.__paths.verify_current()

    def close(self) -> None:
        self.__paths.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def __repr__(self) -> str:
        return "<retained-dependency-paths>"


class _RetainedProtection:
    """Opaque references to the live path and source leases."""

    __slots__ = ("__programdata", "__receipt_paths", "__source_paths", "__source_lease")

    def __init__(self, programdata, receipt_paths, source_paths, source_lease) -> None:
        self.__programdata = programdata
        self.__receipt_paths = receipt_paths
        self.__source_paths = source_paths
        self.__source_lease = source_lease

    def __repr__(self) -> str:
        return "<retained-deployment-protection>"

    def verify_current(self) -> None:
        """Recheck retained filesystem identities and ACLs before launch/use."""

        for paths in (self.__programdata, self.__receipt_paths, self.__source_paths):
            paths.verify_current()
        verify_source = getattr(self.__source_lease, "verify_current", None)
        if callable(verify_source):
            verify_source()


@dataclass(frozen=True, repr=False)
class GuardianClientBinding:
    """Client-safe fixed service facts backed by a retained descriptor handle.

    This view never opens the shared-HMAC key, source tree, dependency closure,
    private CTP configuration, or an SDK. It is an identity binding only; the
    caller must still verify the running service process and pipe peer.
    """

    service_name: str
    service_sid: str
    client_sid: str
    pipe_address: str
    python_executable: str
    python_sha256: str
    descriptor_sha256: str
    runtime_manifest_sha256: str
    _descriptor_path: str = field(repr=False, compare=False)
    _descriptor_paths: _ProtectedWindowsPaths = field(repr=False, compare=False)
    _worker_dependency_manifest_sha256: str = field(repr=False, compare=False)
    _factory_token: object = field(repr=False, compare=False)
    _closed: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _CLIENT_BINDING_FACTORY_TOKEN:
            raise DeploymentAnchorError("guardian_client_binding_factory_rejected")
        if self.service_name != FIXED_SERVICE_NAME:
            raise DeploymentAnchorError("guardian_service_name_invalid")
        _canonical_service_sid(self.service_sid)
        if (
            type(self.client_sid) is not str
            or _SID_RE.fullmatch(self.client_sid) is None
            or self.client_sid in _BROAD_KEY_READER_SIDS
            or self.client_sid in {_SYSTEM_SID, _ADMINISTRATORS_SID, self.service_sid}
        ):
            raise DeploymentAnchorError("guardian_client_sid_invalid")
        _canonical_windows_path(self.python_executable, "python_executable_invalid")
        _sha256(self.python_sha256, "python_executable_pin_invalid")
        _sha256(self.descriptor_sha256, "deployment_descriptor_pin_invalid")
        _sha256(self.runtime_manifest_sha256, "runtime_manifest_pin_unset")
        _sha256(
            self._worker_dependency_manifest_sha256,
            "worker_dependency_closure_pin_unset",
        )

    def __repr__(self) -> str:
        return (
            "GuardianClientBinding(service_name={!r}, service_sid={!r}, client_sid={!r}, "
            "pipe_address={!r}, python_executable={!r}, python_sha256={!r}, "
            "descriptor_sha256={!r}, runtime_manifest_sha256={!r}, "
            "descriptor_lease=<retained>)"
        ).format(
            self.service_name,
            self.service_sid,
            self.client_sid,
            self.pipe_address,
            self.python_executable,
            self.python_sha256,
            self.descriptor_sha256,
            self.runtime_manifest_sha256,
        )

    def verify_current(self) -> None:
        """Recheck the exact descriptor identity, ACL and code-pinned bytes."""

        if self._closed:
            raise DeploymentAnchorError("guardian_client_binding_closed")
        self._descriptor_paths.verify_current()
        raw = self._descriptor_paths.read_file(
            self._descriptor_path, max_bytes=_MAX_DESCRIPTOR_BYTES
        )
        parsed = _parse_deployment_descriptor(
            raw,
            expected_sha256=self.descriptor_sha256,
            expected_worker_dependency_sha256=self._worker_dependency_manifest_sha256,
            expected_runtime_manifest_sha256=self.runtime_manifest_sha256,
        )
        actual_service_sid = _assert_fixed_service_sid(
            parsed.service_sid, _lookup_fixed_service_sid()
        )
        if (
            parsed.service_sid != self.service_sid
            or actual_service_sid != self.service_sid
            or parsed.client_sid != self.client_sid
            or parsed.pipe_address != self.pipe_address
            or parsed.python_executable != self.python_executable
            or parsed.python_sha256 != self.python_sha256
            or parsed.descriptor_sha256 != self.descriptor_sha256
            or parsed.runtime_manifest_sha256 != self.runtime_manifest_sha256
        ):
            raise DeploymentAnchorError("guardian_client_binding_changed")
        self._descriptor_paths.verify_current()

    def close(self) -> None:
        """Release the retained descriptor and ancestor handles."""

        if self._closed:
            return
        self._descriptor_paths.close()
        object.__setattr__(self, "_closed", True)

    def __enter__(self):
        if self._closed:
            raise DeploymentAnchorError("guardian_client_binding_closed")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def _client_binding_from_descriptor(
    parsed: _ParsedDeployment,
    *,
    descriptor_path: str,
    descriptor_paths: _ProtectedWindowsPaths,
    service_sid: str,
    worker_dependency_manifest_sha256: str,
) -> GuardianClientBinding:
    """Construct only the narrow client view from already-pinned descriptor facts."""

    expected_service_sid = _assert_fixed_service_sid(parsed.service_sid, service_sid)
    if parsed.client_sid in _BROAD_KEY_READER_SIDS or parsed.client_sid in {
        _SYSTEM_SID,
        _ADMINISTRATORS_SID,
        expected_service_sid,
    }:
        raise DeploymentAnchorError("guardian_client_sid_invalid")
    return GuardianClientBinding(
        service_name=FIXED_SERVICE_NAME,
        service_sid=expected_service_sid,
        client_sid=parsed.client_sid,
        pipe_address=parsed.pipe_address,
        python_executable=parsed.python_executable,
        python_sha256=parsed.python_sha256,
        descriptor_sha256=parsed.descriptor_sha256,
        runtime_manifest_sha256=parsed.runtime_manifest_sha256,
        _descriptor_path=descriptor_path,
        _descriptor_paths=descriptor_paths,
        _worker_dependency_manifest_sha256=worker_dependency_manifest_sha256,
        _factory_token=_CLIENT_BINDING_FACTORY_TOKEN,
    )


def load_fixed_guardian_client_binding() -> GuardianClientBinding:
    """Load fixed, non-secret service facts for the OS-authenticated pipe client.

    This deliberately opens only the code-pinned ProgramData deployment
    descriptor. It never opens authkey.bin, dependencies.json, the source tree,
    private configuration, or an SDK. The descriptor pin is intentionally
    unset in this checkout, so the production entry point rejects before
    KnownFolder lookup or filesystem access.
    """

    expected_descriptor = _sha256(
        GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256, "deployment_anchor_pin_unset"
    )
    expected_dependencies = _sha256(
        WORKER_DEPENDENCY_MANIFEST_SHA256, "worker_dependency_closure_pin_unset"
    )
    expected_runtime = _sha256(RUNTIME_MANIFEST_SHA256, "runtime_manifest_pin_unset")
    if os.name != "nt" or sys.platform != "win32":
        raise DeploymentAnchorError("windows_required")
    if sys.version_info[:3] != (3, 11, 5):
        raise DeploymentAnchorError("python_baseline_invalid")
    program_data = _program_data_path()
    _, descriptor_path, _, _, _, _ = _fixed_paths(program_data)
    protected = _ProtectedWindowsPaths(frozenset({_SYSTEM_SID, _ADMINISTRATORS_SID}))
    try:
        protected.add_paths((descriptor_path,))
        raw = protected.read_file(descriptor_path, max_bytes=_MAX_DESCRIPTOR_BYTES)
        parsed = _parse_deployment_descriptor(
            raw,
            expected_sha256=expected_descriptor,
            expected_worker_dependency_sha256=expected_dependencies,
            expected_runtime_manifest_sha256=expected_runtime,
        )
        service_sid = _lookup_fixed_service_sid()
        binding = _client_binding_from_descriptor(
            parsed,
            descriptor_path=descriptor_path,
            descriptor_paths=protected,
            service_sid=service_sid,
            worker_dependency_manifest_sha256=expected_dependencies,
        )
        binding.verify_current()
        return binding
    except BaseException as error:
        try:
            protected.close()
        except BaseException:
            raise DeploymentAnchorError("guardian_client_binding_cleanup_failed") from None
        if isinstance(error, DeploymentAnchorError):
            raise
        raise DeploymentAnchorError("guardian_client_binding_load_failed") from None


@dataclass(frozen=True, repr=False)
class GuardianDeploymentAnchor:
    """Immutable facts plus retained source/path seals for the guardian.

    Instances are created only by the fixed loader. Tests should exercise the
    pure parser and ACL policy, not synthesize a wire-capable anchor.
    """

    source_root: str
    source_manifest_sha256: str
    i13_manifest_sha256: str
    i15_manifest_sha256: str
    python_executable: str
    python_sha256: str
    python_version: str
    python_architecture: str
    service_sid: str
    client_sid: str
    worker_sha256: str
    _i13_pin_sha256: str
    _i15_pin_sha256: str
    pipe_address: str
    auth_key_sha256: str
    worker_dependency_manifest_sha256: str
    runtime_manifest_sha256: str
    runtime_base_root: str
    runtime_venv_root: str
    pyvenv_cfg_sha256: str
    stdlib_paths: tuple[str, ...]
    receipt_root: str
    receipt_scope: str
    descriptor_sha256: str
    protection: object
    _programdata_paths: _ProtectedWindowsPaths
    _receipt_paths: _ProtectedWindowsPaths
    _source_seal: object
    _source_paths: _ProtectedWindowsPaths
    _descriptor_path: str
    _auth_key_path: str
    _dependency_manifest_path: str
    _runtime_manifest_path: str
    _acl_trusted_sids: frozenset[str]
    _dependency_seal: object
    _runtime_closure_seal: object
    _factory_token: object = field(repr=False, compare=False)
    _closed: bool = False
    _execution_close_attempted: bool = False
    _execution_close_failed: bool = False
    _receipt_closed: bool = False

    def __post_init__(self) -> None:
        if self._factory_token is not _ANCHOR_FACTORY_TOKEN:
            raise DeploymentAnchorError("deployment_anchor_factory_rejected")

    def __repr__(self) -> str:
        return (
            "GuardianDeploymentAnchor(source_root={!r}, source_manifest_sha256={!r}, "
            "python_executable={!r}, service_sid={!r}, client_sid={!r}, "
            "worker_sha256={!r}, pipe_address={!r}, auth_key_sha256={!r}, "
            "worker_dependency_manifest_sha256={!r}, receipt_root={!r}, "
            "runtime_manifest_sha256={!r}, receipt_scope={!r}, descriptor_sha256={!r}, "
            "protection=<retained>)"
        ).format(
            self.source_root,
            self.source_manifest_sha256,
            self.python_executable,
            self.service_sid,
            self.client_sid,
            self.worker_sha256,
            self.pipe_address,
            self.auth_key_sha256,
            self.worker_dependency_manifest_sha256,
            self.receipt_root,
            self.runtime_manifest_sha256,
            self.receipt_scope,
            self.descriptor_sha256,
        )

    @property
    def i13_pin_sha256(self) -> str:
        return self._i13_pin_sha256

    @property
    def i15_pin_sha256(self) -> str:
        return self._i15_pin_sha256

    @property
    def runtime_descriptor_facts(self) -> Mapping[str, object]:
        """Immutable, verified parent-interpreter facts for the closure checker."""

        return MappingProxyType(
            {
                "python_executable": self.python_executable,
                "python_sha256": self.python_sha256,
                "python_version": self.python_version,
                "python_architecture": self.python_architecture,
                "python_home": self.runtime_base_root,
                "venv_root": self.runtime_venv_root,
                "pyvenv_cfg_sha256": self.pyvenv_cfg_sha256,
                "stdlib_paths": self.stdlib_paths,
            }
        )

    @property
    def pycache_prefix(self) -> str:
        """Return the only permitted, intentionally absent bytecode-cache path."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        return ntpath.join(self.runtime_base_root, FIXED_PYCACHE_PREFIX_NAME)

    def read_worker_source(self) -> bytes:
        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        files = getattr(self._source_seal, "files", None)
        lease = getattr(self._source_seal, "source_lease", None)
        reader = getattr(lease, "read_source", None)
        if not isinstance(files, Mapping) or files.get(WORKER_RELATIVE_PATH) != self.worker_sha256:
            raise DeploymentAnchorError("worker_not_in_pinned_source_manifest")
        if not callable(reader):
            raise DeploymentAnchorError("worker_source_lease_unavailable")
        try:
            raw = reader(WORKER_RELATIVE_PATH, expected_sha256=self.worker_sha256)
        except Exception:
            raise DeploymentAnchorError("worker_source_read_failed") from None
        if type(raw) is not bytes or not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), self.worker_sha256
        ):
            raise DeploymentAnchorError("worker_source_digest_mismatch")
        return raw

    @property
    def bootstrap_relative_path(self) -> str:
        return BOOTSTRAP_RELATIVE_PATH

    @property
    def bootstrap_sha256(self) -> str:
        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        files = getattr(self._source_seal, "files", None)
        if not isinstance(files, Mapping):
            raise DeploymentAnchorError("bootstrap_not_in_pinned_source_manifest")
        return _sha256(
            files.get(BOOTSTRAP_RELATIVE_PATH), "bootstrap_not_in_pinned_source_manifest"
        )

    def read_bootstrap_source(self) -> bytes:
        """Read the fixed bootstrap bytes from the retained source-tree seal."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        expected = self.bootstrap_sha256
        lease = getattr(self._source_seal, "source_lease", None)
        reader = getattr(lease, "read_source", None)
        if not callable(reader):
            raise DeploymentAnchorError("bootstrap_source_lease_unavailable")
        try:
            raw = reader(BOOTSTRAP_RELATIVE_PATH, expected_sha256=expected)
        except Exception:
            raise DeploymentAnchorError("bootstrap_source_read_failed") from None
        if type(raw) is not bytes or not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), expected
        ):
            raise DeploymentAnchorError("bootstrap_source_digest_mismatch")
        return raw

    def _read_fixed_role_source(self, relative_path: str) -> bytes:
        """Read one exact service-role source from the retained I13 lease."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        if relative_path not in _FIXED_ROLE_SOURCE_PATHS:
            raise DeploymentAnchorError("readonly_role_source_not_fixed")
        files = getattr(self._source_seal, "files", None)
        lease = getattr(self._source_seal, "source_lease", None)
        reader = getattr(lease, "read_source", None)
        if not isinstance(files, Mapping) or not callable(reader):
            raise DeploymentAnchorError("readonly_role_source_lease_unavailable")
        expected = _sha256(files.get(relative_path), "readonly_role_source_not_pinned")
        try:
            raw = reader(relative_path, expected_sha256=expected)
        except Exception:
            raise DeploymentAnchorError("readonly_role_source_read_failed") from None
        if type(raw) is not bytes or not raw or len(raw) > 256 * 1024:
            raise DeploymentAnchorError("readonly_role_source_size_invalid")
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
            raise DeploymentAnchorError("readonly_role_source_digest_mismatch")
        return raw

    def _fixed_role_source_sha256(self, relative_path: str) -> str:
        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        if relative_path not in _FIXED_ROLE_SOURCE_PATHS:
            raise DeploymentAnchorError("readonly_role_source_not_fixed")
        files = getattr(self._source_seal, "files", None)
        if not isinstance(files, Mapping):
            raise DeploymentAnchorError("readonly_role_source_not_pinned")
        return _sha256(files.get(relative_path), "readonly_role_source_not_pinned")

    @property
    def request_coordinator_sha256(self) -> str:
        return self._fixed_role_source_sha256(REQUEST_COORDINATOR_RELATIVE_PATH)

    def read_request_coordinator_source(self) -> bytes:
        return self._read_fixed_role_source(REQUEST_COORDINATOR_RELATIVE_PATH)

    @property
    def receipt_writer_sha256(self) -> str:
        return self._fixed_role_source_sha256(RECEIPT_WRITER_RELATIVE_PATH)

    def read_receipt_writer_source(self) -> bytes:
        return self._read_fixed_role_source(RECEIPT_WRITER_RELATIVE_PATH)

    @property
    def token_bootstrap_sha256(self) -> str:
        return self._fixed_role_source_sha256(TOKEN_BOOTSTRAP_RELATIVE_PATH)

    def read_token_bootstrap_source(self) -> bytes:
        return self._read_fixed_role_source(TOKEN_BOOTSTRAP_RELATIVE_PATH)

    def read_auth_key(self) -> bytes:
        """Read the exact protected key file through its retained file handle."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        raw = self._programdata_paths.read_file(self._auth_key_path, max_bytes=32)
        if len(raw) != 32 or not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), self.auth_key_sha256
        ):
            raise DeploymentAnchorError("auth_key_digest_mismatch")
        return raw

    @property
    def dependency_root(self) -> str:
        venv_root = ntpath.dirname(ntpath.dirname(self.python_executable))
        return ntpath.join(venv_root, "Lib", "site-packages")

    def read_worker_dependency_manifest(self) -> bytes:
        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        raw = self._programdata_paths.read_file(
            self._dependency_manifest_path, max_bytes=1024 * 1024
        )
        if not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), self.worker_dependency_manifest_sha256
        ):
            raise DeploymentAnchorError("worker_dependency_manifest_digest_mismatch")
        return raw

    def read_runtime_manifest(self) -> bytes:
        """Read the exact fixed runtime closure manifest through its retained handle."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        raw = self._programdata_paths.read_file(
            self._runtime_manifest_path, max_bytes=4 * 1024 * 1024
        )
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), self.runtime_manifest_sha256):
            raise DeploymentAnchorError("runtime_manifest_digest_mismatch")
        return raw

    @property
    def dependency_seal(self):
        return self._dependency_seal

    def retain_dependency_paths(
        self,
        relative_files: Sequence[str],
        relative_directories: Sequence[str],
    ) -> _RetainedDependencyPaths:
        if self._closed:
            raise DeploymentAnchorError("deployment_anchor_closed")
        if (
            type(relative_files) not in (tuple, list)
            or type(relative_directories) not in (tuple, list)
            or not relative_files
            or len(relative_files) + len(relative_directories) > 100_000
        ):
            raise DeploymentAnchorError("dependency_path_set_invalid")
        checked_files = tuple(_RetainedDependencyPaths._relative(path) for path in relative_files)
        checked_directories = tuple(
            _RetainedDependencyPaths._relative(path) for path in relative_directories
        )
        checked_directories = tuple(
            sorted(checked_directories, key=lambda path: (path.count("/"), path.casefold()))
        )
        folded = [ntpath.normcase(path.replace("/", "\\")) for path in checked_files]
        if len(folded) != len(set(folded)):
            raise DeploymentAnchorError("dependency_path_set_invalid")
        root = self.dependency_root
        paths = _ProtectedWindowsPaths(self._acl_trusted_sids)
        try:
            paths.add_paths(
                (root,),
                directory_paths=frozenset({root}),
                listable_directory_paths=frozenset({root}),
            )
            for relative in checked_directories:
                path = ntpath.join(root, relative.replace("/", "\\"))
                paths.add_paths(
                    (path,),
                    directory_paths=frozenset({path}),
                    listable_directory_paths=frozenset({path}),
                )
            for relative in checked_files:
                path = ntpath.join(root, relative.replace("/", "\\"))
                paths.add_paths((path,))
            return _RetainedDependencyPaths(root, paths)
        except BaseException:
            try:
                paths.close()
            except Exception:
                pass
            raise

    def retain_runtime_paths(
        self,
        root_kind: str,
        relative_files: Sequence[str],
        relative_directories: Sequence[str],
    ) -> _RetainedDependencyPaths:
        """Retain only a manifest-selected file set beneath a fixed runtime root."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        if root_kind == "base":
            root = self.runtime_base_root
        elif root_kind == "venv":
            root = self.runtime_venv_root
        else:
            raise DeploymentAnchorError("runtime_root_kind_invalid")
        if (
            type(relative_files) not in (tuple, list)
            or type(relative_directories) not in (tuple, list)
            or len(relative_files) + len(relative_directories) > 100_000
        ):
            raise DeploymentAnchorError("runtime_path_set_invalid")
        checked_files = tuple(_RetainedDependencyPaths._relative(path) for path in relative_files)
        checked_directories = tuple(
            _RetainedDependencyPaths._relative(path) for path in relative_directories
        )
        normalized = [
            ntpath.normcase(path.replace("/", "\\"))
            for path in (*checked_files, *checked_directories)
        ]
        if len(normalized) != len(set(normalized)):
            raise DeploymentAnchorError("runtime_path_set_invalid")
        checked_directories = tuple(
            sorted(checked_directories, key=lambda path: (path.count("/"), path.casefold()))
        )
        paths = _ProtectedWindowsPaths(self._acl_trusted_sids)
        try:
            paths.add_paths(
                (root,),
                directory_paths=frozenset({root}),
                listable_directory_paths=frozenset({root}),
            )
            for relative in checked_directories:
                path = ntpath.join(root, relative.replace("/", "\\"))
                paths.add_paths(
                    (path,),
                    directory_paths=frozenset({path}),
                    listable_directory_paths=frozenset({path}),
                )
            for relative in checked_files:
                path = ntpath.join(root, relative.replace("/", "\\"))
                paths.add_paths((path,))
            return _RetainedDependencyPaths(root, paths)
        except BaseException:
            try:
                paths.close()
            except Exception:
                pass
            raise

    def verify_dependencies_current(self) -> None:
        if self._dependency_seal is None:
            raise DeploymentAnchorError("worker_dependency_seal_unavailable")
        try:
            self._dependency_seal.verify_current()
        except Exception:
            raise DeploymentAnchorError("worker_dependency_seal_changed") from None

    def verify_current(self) -> None:
        """Revalidate all retained trust roots before service launch or use."""

        if self._closed or self._execution_close_attempted:
            raise DeploymentAnchorError("deployment_anchor_closed")
        try:
            self.protection.verify_current()
            descriptor = self._programdata_paths.read_file(
                self._descriptor_path, max_bytes=_MAX_DESCRIPTOR_BYTES
            )
            if not hmac.compare_digest(
                hashlib.sha256(descriptor).hexdigest(), self.descriptor_sha256
            ):
                raise DeploymentAnchorError("deployment_descriptor_digest_mismatch")
            self.read_auth_key()
            self.read_worker_dependency_manifest()
            self.read_runtime_manifest()
            executable = self._source_paths.read_file(
                self.python_executable, max_bytes=16 * 1024 * 1024
            )
            if not hmac.compare_digest(hashlib.sha256(executable).hexdigest(), self.python_sha256):
                raise DeploymentAnchorError("python_executable_digest_mismatch")
            self.read_worker_source()
            self.read_bootstrap_source()
            self.verify_dependencies_current()
            if self._runtime_closure_seal is None:
                raise DeploymentAnchorError("runtime_closure_seal_unavailable")
            self._runtime_closure_seal.verify_current()
        except DeploymentAnchorError:
            raise
        except Exception:
            raise DeploymentAnchorError("deployment_anchor_changed") from None

    def create_receipt(self, request_id: str, raw: bytes) -> str:
        """Persist a receipt under the fixed retained directory without replacement.

        Call only after :meth:`close_execution_leases` has attempted to close
        the worker, dependency, source and deployment-input leases. A failed
        close remains visible to the caller, while this separate output lease
        remains available to persist an UNKNOWN receipt.
        """

        if self._closed or self._receipt_closed:
            raise DeploymentAnchorError("receipt_lease_closed")
        if not self._execution_close_attempted:
            raise DeploymentAnchorError("execution_leases_not_closed_before_receipt")
        try:
            return self._receipt_paths.create_new_receipt(self.receipt_root, request_id, raw)
        except DeploymentAnchorError:
            raise
        except Exception:
            raise DeploymentAnchorError("receipt_create_failed") from None

    def close_execution_leases(self) -> None:
        """Close input/trust leases before the service publishes its receipt."""

        if self._closed:
            return
        if self._execution_close_attempted and not self._execution_close_failed:
            return
        errors = []
        if self._runtime_closure_seal is not None:
            try:
                self._runtime_closure_seal.close()
            except Exception:
                errors.append("runtime_closure_seal_close_failed")
        if self._dependency_seal is not None:
            try:
                self._dependency_seal.close()
            except Exception:
                errors.append("dependency_seal_close_failed")
        try:
            self._source_seal.close()
        except Exception:
            errors.append("source_seal_close_failed")
        try:
            self._source_paths.close()
        except Exception:
            errors.append("source_paths_close_failed")
        try:
            self._programdata_paths.close()
        except Exception:
            errors.append("programdata_handle_close_failed")
        object.__setattr__(self, "_execution_close_attempted", True)
        object.__setattr__(self, "_execution_close_failed", bool(errors))
        if errors:
            raise DeploymentAnchorError("deployment_anchor_execution_close_failed")

    def close_receipt_lease(self) -> None:
        """Close the separate receipt-output directory lease after response."""

        if self._receipt_closed:
            return
        try:
            self._receipt_paths.close()
        except Exception:
            raise DeploymentAnchorError("receipt_path_handle_close_failed") from None
        object.__setattr__(self, "_receipt_closed", True)

    def close(self) -> None:
        if self._closed:
            return
        errors = []
        try:
            self.close_execution_leases()
        except Exception:
            errors.append("execution_leases_close_failed")
        try:
            self.close_receipt_lease()
        except Exception:
            errors.append("receipt_path_handle_close_failed")
        if errors:
            raise DeploymentAnchorError("deployment_anchor_close_failed")
        object.__setattr__(self, "_closed", True)

    def __enter__(self):
        if self._closed:
            raise DeploymentAnchorError("deployment_anchor_closed")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def load_fixed_deployment_anchor() -> GuardianDeploymentAnchor:
    """Load only the code-pinned ProgramData deployment, never caller paths.

    The unset code-owned digest makes this checkout intentionally fail closed.
    No private configuration, SDK, network or provider operation is reachable
    through this loader.
    """

    expected_descriptor = _sha256(
        GUARDIAN_DEPLOYMENT_DESCRIPTOR_SHA256, "deployment_anchor_pin_unset"
    )
    _sha256(WORKER_DEPENDENCY_MANIFEST_SHA256, "worker_dependency_closure_pin_unset")
    expected_runtime = _sha256(RUNTIME_MANIFEST_SHA256, "runtime_manifest_pin_unset")
    if os.name != "nt" or sys.platform != "win32":
        raise DeploymentAnchorError("windows_required")
    if sys.version_info[:3] != (3, 11, 5):
        raise DeploymentAnchorError("python_baseline_invalid")
    program_data = _program_data_path()
    (
        _,
        descriptor_path,
        auth_key_path,
        dependency_manifest_path,
        runtime_manifest_path,
        receipt_root,
    ) = _fixed_paths(program_data)
    integrity_sids = frozenset({_SYSTEM_SID, _ADMINISTRATORS_SID})
    protected = _ProtectedWindowsPaths(integrity_sids)
    source_seal = None
    source_paths = None
    receipt_paths = None
    dependency_seal = None
    runtime_closure_seal = None
    try:
        protected.add_paths((descriptor_path, dependency_manifest_path, runtime_manifest_path))
        raw = protected.read_file(descriptor_path, max_bytes=_MAX_DESCRIPTOR_BYTES)
        descriptor = _parse_deployment_descriptor(
            raw,
            expected_sha256=expected_descriptor,
            expected_runtime_manifest_sha256=expected_runtime,
        )
        receipt_paths = _ProtectedWindowsPaths(integrity_sids)
        receipt_paths.add_paths(
            (receipt_root,),
            directory_paths=frozenset({receipt_root}),
            writable_paths=frozenset({receipt_root}),
            writer_sids_by_path={
                receipt_root: frozenset({_SYSTEM_SID, _ADMINISTRATORS_SID, descriptor.service_sid})
            },
        )
        for entry in protected._entries.values():
            protected._validate_handle_acl(entry.handle, trusted_sids=entry.trusted_sids)
        protected.add_paths(
            (auth_key_path,),
            reader_sids_by_path=_auth_key_read_policy(
                auth_key_path, descriptor.service_sid, descriptor.client_sid
            ),
        )
        if not hmac.compare_digest(
            hashlib.sha256(protected.read_file(auth_key_path, max_bytes=32)).hexdigest(),
            descriptor.auth_key_sha256,
        ):
            raise DeploymentAnchorError("auth_key_digest_mismatch")
        if not hmac.compare_digest(
            hashlib.sha256(
                protected.read_file(dependency_manifest_path, max_bytes=1024 * 1024)
            ).hexdigest(),
            descriptor.worker_dependency_manifest_sha256,
        ):
            raise DeploymentAnchorError("worker_dependency_manifest_digest_mismatch")
        if not hmac.compare_digest(
            hashlib.sha256(
                protected.read_file(runtime_manifest_path, max_bytes=4 * 1024 * 1024)
            ).hexdigest(),
            descriptor.runtime_manifest_sha256,
        ):
            raise DeploymentAnchorError("runtime_manifest_digest_mismatch")

        # These imports are deliberately after the fixed descriptor/key ACL
        # checks. Both modules are source-only and perform no config/provider IO.
        from scripts import ctp_i13_i15_parent_launcher as parent_launcher
        from scripts import ctp_i13_i15_sealed_import as sealed_import

        parent_descriptor = parent_launcher.ExternallyPinnedDescriptor(
            raw_bytes=descriptor.parent_trust_raw,
            sha256=descriptor.parent_trust_sha256,
            external_anchor_id="ctp-i13-i15-guardian-deployment-v1",
        )
        parent_facts = parent_launcher.parse_trust_descriptor(parent_descriptor)
        if (
            ntpath.normcase(parent_facts.source_root) != ntpath.normcase(descriptor.source_root)
            or ntpath.normcase(parent_facts.python_executable)
            != ntpath.normcase(descriptor.python_executable)
            or parent_facts.python_sha256 != descriptor.python_sha256
            or parent_facts.python_version != descriptor.python_version
            or parent_facts.python_architecture != descriptor.python_architecture
            or parent_facts.candidates["i13_md"]["manifest_sha256"]
            != descriptor.source_manifest_sha256
        ):
            raise DeploymentAnchorError("parent_deployment_binding_mismatch")

        candidate = parent_facts.candidates["i13_md"]
        source_paths = _ProtectedWindowsPaths(integrity_sids)
        source_paths.add_paths(
            (
                descriptor.source_root,
                parent_facts.python_executable,
                ntpath.join(parent_facts.venv_root, "pyvenv.cfg"),
                ntpath.join(
                    parent_facts.source_root, candidate["manifest_path"].replace("/", "\\")
                ),
                ntpath.join(parent_facts.source_root, candidate["pin_path"].replace("/", "\\")),
                ntpath.join(parent_facts.source_root, "scripts\\ctp_i13_i15_parent_launcher.py"),
            ),
            directory_paths=frozenset({descriptor.source_root}),
        )
        launcher_bytes = source_paths.read_file(
            ntpath.join(parent_facts.source_root, "scripts\\ctp_i13_i15_parent_launcher.py"),
            max_bytes=2 * 1024 * 1024,
        )
        actual_executable = os.path.abspath(sys.executable)
        actual_version = "{}.{}.{}".format(*sys.version_info[:3])
        import platform

        actual_architecture = platform.machine()
        plan = parent_launcher.preflight_parent_launch(
            parent_descriptor,
            candidate="i13_md",
            captured_launcher_bytes=launcher_bytes,
            actual_executable=actual_executable,
            actual_version=actual_version,
            actual_architecture=actual_architecture,
            actual_sys_path=tuple(sys.path),
        )
        source_seal = sealed_import.seal_candidate_source_tree(
            "i13_md",
            plan.source_root,
            expected_manifest_sha256=plan.manifest_sha256,
            expected_pin_sha256s=dict(plan.pin_source_sha256s),
            stdlib_paths=plan.stdlib_paths,
        )
        if (
            source_seal.candidate != "i13_md"
            or source_seal.manifest_sha256 != descriptor.source_manifest_sha256
            or source_seal.files.get(WORKER_RELATIVE_PATH) != descriptor.worker_sha256
        ):
            raise DeploymentAnchorError("worker_or_source_manifest_binding_mismatch")
        _sha256(
            source_seal.files.get(BOOTSTRAP_RELATIVE_PATH),
            "bootstrap_not_in_pinned_source_manifest",
        )
        for relative, sha256 in source_seal.files.items():
            source_paths.add_paths((ntpath.join(plan.source_root, relative.replace("/", "\\")),))
            if not hmac.compare_digest(
                hashlib.sha256(
                    source_paths.read_file(
                        ntpath.join(plan.source_root, relative.replace("/", "\\")),
                        max_bytes=16 * 1024 * 1024,
                    )
                ).hexdigest(),
                sha256,
            ):
                raise DeploymentAnchorError("protected_source_digest_mismatch")
        anchor = GuardianDeploymentAnchor(
            source_root=plan.source_root,
            source_manifest_sha256=plan.manifest_sha256,
            i13_manifest_sha256=parent_facts.candidates["i13_md"]["manifest_sha256"],
            i15_manifest_sha256=parent_facts.candidates["i15_td"]["manifest_sha256"],
            python_executable=plan.python_executable,
            python_sha256=descriptor.python_sha256,
            python_version=descriptor.python_version,
            python_architecture=descriptor.python_architecture,
            service_sid=descriptor.service_sid,
            client_sid=descriptor.client_sid,
            worker_sha256=descriptor.worker_sha256,
            _i13_pin_sha256=_sha256(
                plan.pin_source_sha256s.get("i13"), "i13_parent_pin_unavailable"
            ),
            _i15_pin_sha256=_sha256(
                plan.pin_source_sha256s.get("i15"), "i15_parent_pin_unavailable"
            ),
            pipe_address=descriptor.pipe_address,
            auth_key_sha256=descriptor.auth_key_sha256,
            worker_dependency_manifest_sha256=descriptor.worker_dependency_manifest_sha256,
            runtime_manifest_sha256=descriptor.runtime_manifest_sha256,
            runtime_base_root=parent_facts.python_home,
            runtime_venv_root=parent_facts.venv_root,
            pyvenv_cfg_sha256=parent_facts.pyvenv_cfg_sha256,
            stdlib_paths=parent_facts.stdlib_paths,
            receipt_root=receipt_root,
            receipt_scope=FIXED_RECEIPT_SCOPE,
            descriptor_sha256=descriptor.descriptor_sha256,
            protection=_RetainedProtection(
                protected, receipt_paths, source_paths, source_seal.source_lease
            ),
            _programdata_paths=protected,
            _receipt_paths=receipt_paths,
            _source_seal=source_seal,
            _source_paths=source_paths,
            _descriptor_path=descriptor_path,
            _auth_key_path=auth_key_path,
            _dependency_manifest_path=dependency_manifest_path,
            _runtime_manifest_path=runtime_manifest_path,
            _acl_trusted_sids=integrity_sids,
            _dependency_seal=None,
            _runtime_closure_seal=None,
            _factory_token=_ANCHOR_FACTORY_TOKEN,
        )
        from backtrader_runtime.ctp_i13_worker_dependency_seal import (
            seal_fixed_worker_dependencies,
        )

        dependency_seal = seal_fixed_worker_dependencies(anchor)
        if dependency_seal is None:
            raise DeploymentAnchorError("worker_dependency_seal_unavailable")
        object.__setattr__(anchor, "_dependency_seal", dependency_seal)
        from scripts.ctp_i13_i15_runtime_closure import seal_fixed_runtime_closure

        runtime_closure_seal = seal_fixed_runtime_closure(anchor)
        if runtime_closure_seal is None:
            raise DeploymentAnchorError("runtime_closure_seal_unavailable")
        object.__setattr__(anchor, "_runtime_closure_seal", runtime_closure_seal)
        return anchor
    except BaseException:
        close_errors = []
        if runtime_closure_seal is not None:
            try:
                runtime_closure_seal.close()
            except Exception:
                close_errors.append("runtime_closure_seal")
        if dependency_seal is not None:
            try:
                dependency_seal.close()
            except Exception:
                close_errors.append("dependency_seal")
        if source_seal is not None:
            try:
                source_seal.close()
            except Exception:
                close_errors.append("source_seal")
        if source_paths is not None:
            try:
                source_paths.close()
            except Exception:
                close_errors.append("source_paths")
        if receipt_paths is not None:
            try:
                receipt_paths.close()
            except Exception:
                close_errors.append("receipt_paths")
        try:
            protected.close()
        except Exception:
            close_errors.append("programdata_paths")
        if close_errors:
            raise DeploymentAnchorError("deployment_anchor_cleanup_failed") from None
        if isinstance(sys.exc_info()[1], DeploymentAnchorError):
            raise
        raise DeploymentAnchorError("deployment_anchor_load_failed") from None


__all__ = [
    "DEPLOYMENT_OPERATION",
    "DEPLOYMENT_SCHEMA",
    "DeploymentAnchorError",
    "BOOTSTRAP_RELATIVE_PATH",
    "FIXED_RUNTIME_MANIFEST_NAME",
    "FIXED_PYCACHE_PREFIX_NAME",
    "FIXED_SERVICE_NAME",
    "GuardianDeploymentAnchor",
    "GuardianClientBinding",
    "RUNTIME_MANIFEST_SHA256",
    "WORKER_RELATIVE_PATH",
    "load_fixed_guardian_client_binding",
    "load_fixed_deployment_anchor",
]
