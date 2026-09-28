"""Offline HMAC review verification for the proposed SimNow action window.

This module is intentionally not imported by the runtime registry, CLI,
managed operator, Store, gateway, or SDK composition.  It verifies an injected
signed review envelope against injected trust, UTC, and replay services.  A
successful verification remains a review contract only: it does not create a
writer fence, authorize execution, or change the governing NO_WRITE decision.

The existing :mod:`ctp_simulation_execution` HMAC approval is not reused here:
it does not bind the operational window's session/day/generation, exact risk
limits, revocation epoch, issuer policy, or replay guard.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import math
import ntpath
import os
import re
import sqlite3
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, FrozenSet, Optional, Protocol

from .ctp_simnow_operational_window import (
    CtpSimNowOperationalActionRequest,
    CtpSimNowOperationalWindowError,
    CtpSimNowOperationalWindowPermit,
)


_DOMAIN = b"backtrader-ctp-simnow-operational-review-hmac-v1\0"
_REPLAY_DOMAIN = b"backtrader-ctp-simnow-operational-review-replay-v1\0"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIONS = frozenset(("SUBMIT", "CANCEL"))
_MAX_TTL_SECONDS = 60.0


def _reject(reason: str) -> None:
    raise CtpSimNowOperationalWindowError(reason) from None


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        _reject("operational_review_payload_invalid")


def _finite_utc(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        _reject("operational_review_trusted_utc_invalid")
    return float(value)


def _normalized_set(value: object, field_name: str, pattern: re.Pattern[str]) -> FrozenSet[str]:
    if isinstance(value, (str, bytes)):
        _reject("operational_review_policy_invalid")
    try:
        items = frozenset(value)  # type: ignore[arg-type]
    except TypeError:
        _reject("operational_review_policy_invalid")
    if not items or any(type(item) is not str or pattern.fullmatch(item) is None for item in items):
        _reject("operational_review_policy_invalid")
    return items


def _is_link_or_reparse(result: os.stat_result) -> bool:
    attributes = getattr(result, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_point)


def _file_identity(result: os.stat_result) -> tuple[int, int]:
    return int(result.st_dev), int(result.st_ino)


_WINDOWS_UNTRUSTED_WRITE_MASK = (
    0x00000040  # FILE_DELETE_CHILD
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x10000000  # GENERIC_ALL
    | 0x40000000  # GENERIC_WRITE
)


def _windows_drive_type(root: str) -> int:
    """Return the Win32 volume type for a normalized drive root."""

    try:
        get_drive_type = ctypes.WinDLL("Kernel32", use_last_error=True).GetDriveTypeW
        get_drive_type.argtypes = (ctypes.c_wchar_p,)
        get_drive_type.restype = ctypes.c_uint
        return int(get_drive_type(root))
    except Exception:
        return 0  # DRIVE_UNKNOWN; callers fail closed.


def _require_windows_local_volume(
    path: Path,
    *,
    drive_type_getter: Optional[Callable[[str], int]] = None,
) -> None:
    """Require a drive-letter path on a known fixed local Windows volume."""

    raw_path = os.fspath(path)
    drive, _tail = ntpath.splitdrive(raw_path)
    if not re.fullmatch(r"[A-Za-z]:", drive):
        raise RuntimeError("operational_review_replay_local_volume_required")
    root = drive + "\\"
    get_drive_type = drive_type_getter or _windows_drive_type
    if get_drive_type(root) != 3:  # DRIVE_FIXED; excludes remote/unknown volumes.
        raise RuntimeError("operational_review_replay_local_volume_required")


def _validate_windows_private_acl(
    owner_sid: str,
    current_user_sid: str,
    is_protected: bool,
    entries: tuple[tuple[int, int, int, str], ...],
) -> None:
    """Require an explicitly protected current-user ACL for stored state."""

    allowed_sids = {current_user_sid, "S-1-5-18", "S-1-5-32-544"}
    if owner_sid != current_user_sid or not is_protected:
        raise RuntimeError("operational_review_replay_windows_acl_invalid")
    for ace_type, ace_flags, _mask, trustee_sid in entries:
        if ace_type not in (0, 1) or ace_flags & 0x10 or trustee_sid not in allowed_sids:
            raise RuntimeError("operational_review_replay_windows_acl_invalid")


def _validate_windows_ancestor_acl(
    owner_sid: str,
    current_user_sid: str,
    entries: tuple[tuple[int, int, int, str], ...],
) -> None:
    """Reject path ancestors that another principal could rename or modify."""

    trusted_sids = {
        current_user_sid,
        "S-1-5-18",  # Local System
        "S-1-5-32-544",  # Builtin Administrators
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
    }
    if owner_sid not in trusted_sids:
        raise RuntimeError("operational_review_replay_windows_ancestor_acl_invalid")
    for ace_type, ace_flags, mask, trustee_sid in entries:
        if ace_type not in (0, 1) or ace_flags & ~0x1F:
            raise RuntimeError("operational_review_replay_windows_ancestor_acl_invalid")
        if ace_type == 0 and not ace_flags & 0x08 and trustee_sid not in trusted_sids:
            if mask & _WINDOWS_UNTRUSTED_WRITE_MASK:
                raise RuntimeError("operational_review_replay_windows_ancestor_acl_invalid")


def _validate_windows_sidecar_acl(
    owner_sid: str,
    current_user_sid: str,
    entries: tuple[tuple[int, int, int, str], ...],
) -> None:
    """Accept only safe inherited ACEs from the already protected DB folder."""

    allowed_sids = {current_user_sid, "S-1-5-18", "S-1-5-32-544"}
    if owner_sid != current_user_sid:
        raise RuntimeError("operational_review_replay_windows_sidecar_acl_invalid")
    for ace_type, ace_flags, _mask, trustee_sid in entries:
        if (
            ace_type not in (0, 1)
            or ace_flags & ~0x1F
            or ace_flags & 0x08
            or trustee_sid not in allowed_sids
        ):
            raise RuntimeError("operational_review_replay_windows_sidecar_acl_invalid")
    if not any(
        ace_type == 0 and trustee == current_user_sid for ace_type, _, _, trustee in entries
    ):
        raise RuntimeError("operational_review_replay_windows_sidecar_acl_invalid")


def _windows_acl_details_for_handle(
    handle: int,
) -> tuple[str, str, bool, tuple[tuple[int, int, int, str], ...]]:
    """Read an object's owner, DACL protection bit, and simple ACEs by handle."""

    try:
        from ctypes import wintypes

        from .credential_resolver import _current_windows_user_sid, _windows_sid_to_string

        advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_security_info = advapi32.GetSecurityInfo
        get_security_info.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        )
        get_security_info.restype = wintypes.DWORD
        owner_sid = ctypes.c_void_p()
        group_sid = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        sacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        result = get_security_info(
            wintypes.HANDLE(handle),
            1,
            0x00000001 | 0x00000004,
            ctypes.byref(owner_sid),
            ctypes.byref(group_sid),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if result != 0 or not descriptor:
            raise RuntimeError("operational_review_replay_windows_acl_unavailable")
        try:
            get_control = advapi32.GetSecurityDescriptorControl
            get_control.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.WORD),
                ctypes.POINTER(wintypes.DWORD),
            )
            get_control.restype = wintypes.BOOL
            control = wintypes.WORD()
            revision = wintypes.DWORD()
            if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
                raise RuntimeError("operational_review_replay_windows_acl_unavailable")

            get_owner = advapi32.GetSecurityDescriptorOwner
            get_owner.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(wintypes.BOOL),
            )
            get_owner.restype = wintypes.BOOL
            owner_defaulted = wintypes.BOOL()
            if (
                not get_owner(descriptor, ctypes.byref(owner_sid), ctypes.byref(owner_defaulted))
                or owner_defaulted.value
                or not owner_sid
            ):
                raise RuntimeError("operational_review_replay_windows_acl_invalid")

            get_dacl = advapi32.GetSecurityDescriptorDacl
            get_dacl.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.BOOL),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(wintypes.BOOL),
            )
            get_dacl.restype = wintypes.BOOL
            dacl_present = wintypes.BOOL()
            dacl_defaulted = wintypes.BOOL()
            if (
                not get_dacl(
                    descriptor,
                    ctypes.byref(dacl_present),
                    ctypes.byref(dacl),
                    ctypes.byref(dacl_defaulted),
                )
                or not dacl_present.value
                or dacl_defaulted.value
                or not dacl
            ):
                raise RuntimeError("operational_review_replay_windows_acl_invalid")

            class _AclSizeInformation(ctypes.Structure):
                _fields_ = (
                    ("AceCount", wintypes.DWORD),
                    ("AclBytesInUse", wintypes.DWORD),
                    ("AclBytesFree", wintypes.DWORD),
                )

            get_acl_information = advapi32.GetAclInformation
            get_acl_information.argtypes = (
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            get_acl_information.restype = wintypes.BOOL
            size_info = _AclSizeInformation()
            if not get_acl_information(dacl, ctypes.byref(size_info), ctypes.sizeof(size_info), 2):
                raise RuntimeError("operational_review_replay_windows_acl_unavailable")

            get_ace = advapi32.GetAce
            get_ace.argtypes = (
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            )
            get_ace.restype = wintypes.BOOL
            is_valid_sid = advapi32.IsValidSid
            is_valid_sid.argtypes = (ctypes.c_void_p,)
            is_valid_sid.restype = wintypes.BOOL
            get_length_sid = advapi32.GetLengthSid
            get_length_sid.argtypes = (ctypes.c_void_p,)
            get_length_sid.restype = wintypes.DWORD
            entries = []
            for index in range(int(size_info.AceCount)):
                ace_pointer = ctypes.c_void_p()
                if not get_ace(dacl, index, ctypes.byref(ace_pointer)) or not ace_pointer:
                    raise RuntimeError("operational_review_replay_windows_acl_unavailable")
                header = ctypes.string_at(ace_pointer, 4)
                ace_type = header[0]
                ace_flags = header[1]
                ace_size = int.from_bytes(header[2:4], byteorder="little")
                if ace_size < 8 or ace_size > int(size_info.AclBytesInUse):
                    raise RuntimeError("operational_review_replay_windows_acl_invalid")
                mask = int.from_bytes(ctypes.string_at(ace_pointer.value + 4, 4), "little")
                trustee_sid = ""
                if ace_type in (0, 1):
                    if ace_size < 12:
                        raise RuntimeError("operational_review_replay_windows_acl_invalid")
                    sid = ctypes.c_void_p(ace_pointer.value + 8)
                    if not is_valid_sid(sid) or get_length_sid(sid) > ace_size - 8:
                        raise RuntimeError("operational_review_replay_windows_acl_invalid")
                    trustee_sid = _windows_sid_to_string(advapi32, kernel32, sid)
                entries.append((ace_type, ace_flags, mask, trustee_sid))

            owner_text = _windows_sid_to_string(advapi32, kernel32, owner_sid)
            current_user = _current_windows_user_sid(advapi32, kernel32)
            return (
                owner_text,
                current_user,
                bool(control.value & 0x1000),
                tuple(entries),
            )
        finally:
            local_free = kernel32.LocalFree
            local_free.argtypes = (ctypes.c_void_p,)
            local_free.restype = ctypes.c_void_p
            local_free(descriptor)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("operational_review_replay_windows_acl_unavailable") from None


def _protect_windows_path_acl(path: Path, *, is_directory: bool) -> None:
    """Install a protected current-user ACL through an identity-checked handle."""

    before = os.lstat(str(path))
    expected_type = stat.S_ISDIR if is_directory else stat.S_ISREG
    if _is_link_or_reparse(before) or not expected_type(before.st_mode):
        raise RuntimeError("operational_review_replay_path_invalid")
    try:
        from ctypes import wintypes

        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        desired_access = 0x00020000 | 0x00040000 | 0x00080000 | 0x00000080
        share_read_write = 0x00000001 | 0x00000002
        open_reparse_point = 0x00200000
        backup_semantics = 0x02000000 if is_directory else 0
        handle = create_file(
            str(path),
            desired_access,
            share_read_write,
            None,
            3,
            open_reparse_point | backup_semantics,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle or handle == -1:
            raise RuntimeError("operational_review_replay_windows_acl_unavailable")
        descriptor = None
        try:
            descriptor = msvcrt.open_osfhandle(
                handle,
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
            )
            opened = os.fstat(descriptor)
            if _file_identity(opened) != _file_identity(before):
                raise RuntimeError("operational_review_replay_path_changed")
            from .ctp_private_config_setup import _set_windows_owner_acl

            _set_windows_owner_acl(descriptor, directory=is_directory)
            from .credential_resolver import _windows_os_handle

            owner_sid, current_user_sid, protected, entries = _windows_acl_details_for_handle(
                _windows_os_handle(descriptor)
            )
            _validate_windows_private_acl(owner_sid, current_user_sid, protected, entries)
            after = os.lstat(str(path))
            if _is_link_or_reparse(after) or _file_identity(after) != _file_identity(opened):
                raise RuntimeError("operational_review_replay_path_changed")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            else:
                kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
                kernel32.CloseHandle.restype = wintypes.BOOL
                kernel32.CloseHandle(handle)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("operational_review_replay_windows_acl_unavailable") from None


@dataclass(frozen=True, repr=False)
class CtpSimNowOperationalReviewKeyPolicy:
    """One resolved HMAC key plus the exact review authority it may exercise.

    The resolver is the trust boundary.  This value must be constructed from
    code-owned policy and protected key material by the eventual caller; tests
    use an explicit fake resolver and disposable key.
    """

    key_id: str
    review_authority_id: str
    key_bytes: bytes = field(repr=False)
    current_revocation_epoch: int
    allowed_account_fingerprints: FrozenSet[str]
    allowed_window_ids: FrozenSet[str]
    allowed_session_identity_digests: FrozenSet[str]
    allowed_trading_days: FrozenSet[str]
    allowed_risk_limits_digests: FrozenSet[str]
    allowed_action_kinds: FrozenSet[str]
    revoked: bool = False
    max_ttl_seconds: float = _MAX_TTL_SECONDS

    def __post_init__(self) -> None:
        for name in ("key_id", "review_authority_id"):
            value = getattr(self, name)
            if type(value) is not str or _ID_RE.fullmatch(value) is None:
                _reject("operational_review_policy_invalid")
        if type(self.key_bytes) is not bytes or len(self.key_bytes) < 32:
            _reject("operational_review_key_unavailable")
        if type(self.current_revocation_epoch) is not int or self.current_revocation_epoch <= 0:
            _reject("operational_review_policy_invalid")
        if type(self.revoked) is not bool:
            _reject("operational_review_policy_invalid")

        normalizers = {
            "allowed_account_fingerprints": _SHA256_RE,
            "allowed_window_ids": _ID_RE,
            "allowed_session_identity_digests": _SHA256_RE,
            "allowed_trading_days": re.compile(r"^[0-9]{8}$"),
            "allowed_risk_limits_digests": _SHA256_RE,
            "allowed_action_kinds": re.compile(r"^(SUBMIT|CANCEL)$"),
        }
        for name, pattern in normalizers.items():
            object.__setattr__(self, name, _normalized_set(getattr(self, name), name, pattern))
        if not self.allowed_action_kinds.issubset(_ACTIONS):
            _reject("operational_review_policy_invalid")
        if (
            type(self.max_ttl_seconds) not in (int, float)
            or not math.isfinite(float(self.max_ttl_seconds))
            or not 0 < float(self.max_ttl_seconds) <= _MAX_TTL_SECONDS
        ):
            _reject("operational_review_policy_invalid")
        object.__setattr__(self, "max_ttl_seconds", float(self.max_ttl_seconds))


@dataclass(frozen=True, repr=False)
class CtpSimNowSignedOperationalReview:
    """HMAC envelope around one exact operational action review."""

    permit: CtpSimNowOperationalWindowPermit = field(repr=False)
    key_id: str
    signature_hex: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.permit) is not CtpSimNowOperationalWindowPermit:
            _reject("operational_review_envelope_invalid")
        if type(self.key_id) is not str or _ID_RE.fullmatch(self.key_id) is None:
            _reject("operational_review_envelope_invalid")
        if (
            type(self.signature_hex) is not str
            or _SIGNATURE_RE.fullmatch(self.signature_hex) is None
        ):
            _reject("operational_review_envelope_invalid")

    def signed_payload(self) -> bytes:
        """Return the domain-separated canonical payload covered by HMAC."""

        permit = self.permit
        request = permit.binding
        scope = request.scope
        payload = {
            "version": 1,
            "key_id": self.key_id,
            "review_authority_id": permit.review_authority_id,
            "review_digest": permit.review_digest,
            "permit_id": permit.permit_id,
            "revocation_epoch": permit.revocation_epoch,
            "issued_at_utc": float(permit.issued_at_utc),
            "expires_at_utc": float(permit.expires_at_utc),
            "account_fingerprint_sha256": scope.account_fingerprint_sha256,
            "window_id": scope.window_id,
            "session_id": scope.session_id,
            "trading_day": scope.trading_day,
            "connection_generation": scope.connection_generation,
            "session_identity_digest": scope.session_identity_digest,
            "risk_limits_digest": scope.risk_limits.digest,
            "scope_digest": scope.scope_digest,
            "action_kind": request.action_kind,
            "action_id": request.action_id,
            "action_digest": request.action_digest,
            "approval_digest": request.approval_digest,
            "requested_quantity": request.requested_quantity,
            "requested_notional": (
                None
                if request.requested_notional is None
                else format(request.requested_notional, "f")
            ),
            "target_digest": request.target_digest,
            "target_remaining_quantity": request.target_remaining_quantity,
            "request_digest": request.request_digest,
        }
        return _DOMAIN + _canonical_bytes(payload)


class CtpSimNowOperationalReviewSource(Protocol):
    """Source of independently signed review envelopes; no source is bundled."""

    def issue_action_review(
        self, request: CtpSimNowOperationalActionRequest
    ) -> CtpSimNowSignedOperationalReview: ...


class CtpSimNowOperationalReviewKeyResolver(Protocol):
    """Resolve active key and issuer policy by key ID; missing means deny."""

    def resolve(self, key_id: str) -> Optional[CtpSimNowOperationalReviewKeyPolicy]: ...


class CtpSimNowOperationalReviewReplayGuard(Protocol):
    """Atomically reserve both permit ID and scope-bound action replay key."""

    def claim_once(self, permit_id: str, action_replay_key: str, request_digest: str) -> bool:
        """Return literal True only for the first durable claim of either key."""


class LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard:
    """Durably reserve review replay keys in an explicitly supplied local DB.

    This is a local-only storage primitive. Windows paths must be drive-letter
    paths on a volume reported as fixed local storage. Construction and import
    install no path, trust material, review source, or execution route. The
    caller must choose a database under an existing private directory and
    inject this instance into the reviewer. Claims use one SQLite transaction
    across both replay keys; any lock, permission, identity, or database error
    fails closed.
    """

    LOCAL_ONLY = True
    NO_WRITE = True

    _SCHEMA_VERSION = 1
    _SCHEMA_MARKER = "simnow-operational-review-replay-local-only-v1"
    _BUSY_TIMEOUT_SECONDS = 0.5
    _META_TABLE = "simnow_review_replay_meta"
    _PERMIT_TABLE = "simnow_review_permit_claims"
    _ACTION_TABLE = "simnow_review_action_claims"

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
            raise ValueError("operational_review_replay_path_invalid")
        if not path.name:
            raise ValueError("operational_review_replay_path_invalid")
        if os.name == "nt":
            try:
                _require_windows_local_volume(path)
            except RuntimeError as exc:
                raise ValueError(str(exc)) from None
        self._path = path
        self._lock = threading.RLock()

    def claim_once(self, permit_id: str, action_replay_key: str, request_digest: str) -> bool:
        """Atomically claim both replay keys, returning False on either duplicate."""

        if type(permit_id) is not str or _ID_RE.fullmatch(permit_id) is None:
            raise ValueError("operational_review_replay_claim_invalid")
        if (
            type(action_replay_key) is not str
            or _SHA256_RE.fullmatch(action_replay_key) is None
            or type(request_digest) is not str
            or _SHA256_RE.fullmatch(request_digest) is None
        ):
            raise ValueError("operational_review_replay_claim_invalid")

        with self._lock:
            identity = self._prepare_database_file()
            connection = None
            windows_handles = None
            try:
                if os.name == "nt":
                    windows_handles = self._open_windows_storage_handles(identity)
                    self._secure_windows_sqlite_sidecars()
                connection = sqlite3.connect(
                    str(self._path),
                    timeout=self._BUSY_TIMEOUT_SECONDS,
                    isolation_level=None,
                )
                connection.execute(
                    "PRAGMA busy_timeout = " + str(int(self._BUSY_TIMEOUT_SECONDS * 1000))
                )
                connection.execute("PRAGMA foreign_keys = ON")
                if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                    raise RuntimeError("operational_review_replay_database_invalid")
                if connection.execute("PRAGMA journal_mode").fetchone() != ("delete",):
                    raise RuntimeError("operational_review_replay_database_invalid")
                connection.execute("PRAGMA synchronous = FULL")
                self._require_current_identity(identity, windows_handles)
                self._check_database_integrity(connection)
                connection.execute("BEGIN IMMEDIATE")
                self._ensure_schema(connection)
                self._require_current_identity(identity, windows_handles)
                try:
                    connection.execute(
                        "INSERT INTO " + self._PERMIT_TABLE + " (permit_id, request_digest) "
                        "VALUES (?, ?)",
                        (permit_id, request_digest),
                    )
                    connection.execute(
                        "INSERT INTO "
                        + self._ACTION_TABLE
                        + " (action_replay_key, permit_id, request_digest) VALUES (?, ?, ?)",
                        (action_replay_key, permit_id, request_digest),
                    )
                except sqlite3.IntegrityError:
                    if os.name == "nt":
                        self._secure_windows_sqlite_sidecars()
                    connection.execute("ROLLBACK")
                    return False
                if os.name == "nt":
                    self._secure_windows_sqlite_sidecars()
                self._require_current_identity(identity, windows_handles)
                connection.execute("COMMIT")
                self._require_current_identity(identity, windows_handles)
                return True
            except (OSError, sqlite3.Error, RuntimeError) as exc:
                if connection is not None and connection.in_transaction:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise RuntimeError("operational_review_replay_unavailable") from exc
            finally:
                if connection is not None:
                    connection.close()
                if windows_handles is not None:
                    for descriptor in reversed(windows_handles):
                        os.close(descriptor)

    def _prepare_database_file(self) -> tuple[tuple[tuple[str, int, int], ...], tuple[int, int]]:
        parent_identity = self._verify_parent_directory()
        try:
            entry = os.lstat(str(self._path))
        except FileNotFoundError:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(str(self._path), flags, 0o600)
            except FileExistsError:
                descriptor = None
            if descriptor is not None:
                try:
                    if hasattr(os, "fchmod"):
                        os.fchmod(descriptor, 0o600)
                    opened = os.fstat(descriptor)
                    if not stat.S_ISREG(opened.st_mode):
                        raise RuntimeError("operational_review_replay_path_invalid")
                finally:
                    os.close(descriptor)
            entry = os.lstat(str(self._path))
        if _is_link_or_reparse(entry) or not stat.S_ISREG(entry.st_mode):
            raise RuntimeError("operational_review_replay_path_invalid")
        if getattr(entry, "st_nlink", 1) != 1:
            raise RuntimeError("operational_review_replay_path_invalid")
        self._require_private_file(entry)
        if os.name == "nt":
            # Another process may observe a newly created DB before its creator
            # finishes hardening the ACL.  The already verified private parent
            # excludes other users from creating or replacing this entry, so
            # applying the same protected owner ACL here makes initialization
            # idempotent across simultaneous first claims.
            _protect_windows_path_acl(self._path, is_directory=False)
            entry = os.lstat(str(self._path))
            if _is_link_or_reparse(entry) or not stat.S_ISREG(entry.st_mode):
                raise RuntimeError("operational_review_replay_path_invalid")
            if getattr(entry, "st_nlink", 1) != 1:
                raise RuntimeError("operational_review_replay_path_invalid")
        identity = _file_identity(entry)
        if parent_identity != self._verify_parent_directory():
            raise RuntimeError("operational_review_replay_path_changed")
        if identity != _file_identity(os.lstat(str(self._path))):
            raise RuntimeError("operational_review_replay_path_changed")
        return parent_identity, identity

    def _verify_parent_directory(self) -> tuple[tuple[str, int, int], ...]:
        if os.name == "nt":
            _require_windows_local_volume(self._path)
        absolute = Path(os.path.abspath(str(self._path.parent)))
        parts = [Path(absolute.anchor)]
        current = parts[0]
        for part in absolute.parts:
            if part == absolute.anchor:
                continue
            current = current / part
            parts.append(current)

        identities = []
        for directory in parts:
            try:
                entry = os.lstat(str(directory))
            except OSError as exc:
                raise RuntimeError("operational_review_replay_path_unavailable") from exc
            if _is_link_or_reparse(entry) or not stat.S_ISDIR(entry.st_mode):
                raise RuntimeError("operational_review_replay_path_invalid")
            identities.append((os.path.normcase(str(directory)),) + _file_identity(entry))

        if os.name != "nt":
            private_directory = os.lstat(str(self._path.parent))
            effective_uid = os.geteuid()
            if (
                private_directory.st_uid != effective_uid
                or stat.S_IMODE(private_directory.st_mode) & 0o077
                or stat.S_IMODE(private_directory.st_mode) & stat.S_IRUSR == 0
                or stat.S_IMODE(private_directory.st_mode) & stat.S_IWUSR == 0
                or stat.S_IMODE(private_directory.st_mode) & stat.S_IXUSR == 0
            ):
                raise RuntimeError("operational_review_replay_permissions_invalid")
        else:
            for directory in parts[:-1]:
                self._verify_windows_ancestor_directory(directory)
            descriptor, _opened = self._verify_windows_private_path(absolute, is_directory=True)
            os.close(descriptor)
        return tuple(identities)

    def _require_private_file(self, entry: os.stat_result) -> None:
        if os.name == "nt":
            return
        mode = stat.S_IMODE(entry.st_mode)
        if (
            entry.st_uid != os.geteuid()
            or mode & 0o077
            or mode & stat.S_IRUSR == 0
            or mode & stat.S_IWUSR == 0
        ):
            raise RuntimeError("operational_review_replay_permissions_invalid")

    def _require_current_identity(
        self,
        identity: tuple[tuple[tuple[str, int, int], ...], tuple[int, int]],
        windows_handles: Optional[tuple[int, int]] = None,
    ) -> None:
        parent_identity, database_identity = identity
        if parent_identity != self._verify_parent_directory():
            raise RuntimeError("operational_review_replay_path_changed")
        try:
            entry = os.lstat(str(self._path))
        except OSError as exc:
            raise RuntimeError("operational_review_replay_path_unavailable") from exc
        if (
            _is_link_or_reparse(entry)
            or not stat.S_ISREG(entry.st_mode)
            or database_identity != _file_identity(entry)
        ):
            raise RuntimeError("operational_review_replay_path_changed")
        self._require_private_file(entry)
        if os.name == "nt":
            self._verify_windows_private_handles(identity, windows_handles)

    def _verify_windows_ancestor_directory(self, directory: Path) -> None:
        from .credential_resolver import _open_windows_metadata_handle, _windows_os_handle

        before = os.lstat(str(directory))
        if _is_link_or_reparse(before) or not stat.S_ISDIR(before.st_mode):
            raise RuntimeError("operational_review_replay_path_invalid")
        descriptor = _open_windows_metadata_handle(directory, is_directory=True)
        try:
            opened = os.fstat(descriptor)
            if _file_identity(opened) != _file_identity(before):
                raise RuntimeError("operational_review_replay_path_changed")
            owner, current_user, _protected, entries = _windows_acl_details_for_handle(
                _windows_os_handle(descriptor)
            )
            _validate_windows_ancestor_acl(owner, current_user, entries)
            after = os.lstat(str(directory))
            if _is_link_or_reparse(after) or _file_identity(after) != _file_identity(opened):
                raise RuntimeError("operational_review_replay_path_changed")
        finally:
            os.close(descriptor)

    def _verify_windows_private_path(
        self,
        path: Path,
        *,
        is_directory: bool,
        expected_identity: Optional[tuple[int, int]] = None,
    ) -> tuple[int, os.stat_result]:
        from .credential_resolver import _open_windows_metadata_handle, _windows_os_handle

        before = os.lstat(str(path))
        expected_type = stat.S_ISDIR if is_directory else stat.S_ISREG
        if _is_link_or_reparse(before) or not expected_type(before.st_mode):
            raise RuntimeError("operational_review_replay_path_invalid")
        if not is_directory and getattr(before, "st_nlink", 1) != 1:
            raise RuntimeError("operational_review_replay_path_invalid")
        descriptor = _open_windows_metadata_handle(path, is_directory=is_directory)
        try:
            opened = os.fstat(descriptor)
            if _file_identity(opened) != _file_identity(before) or (
                expected_identity is not None and expected_identity != _file_identity(opened)
            ):
                raise RuntimeError("operational_review_replay_path_changed")
            owner, current_user, protected, entries = _windows_acl_details_for_handle(
                _windows_os_handle(descriptor)
            )
            _validate_windows_private_acl(owner, current_user, protected, entries)
            after = os.lstat(str(path))
            if _is_link_or_reparse(after) or _file_identity(after) != _file_identity(opened):
                raise RuntimeError("operational_review_replay_path_changed")
            return descriptor, opened
        except BaseException:
            os.close(descriptor)
            raise

    def _open_windows_storage_handles(
        self, identity: tuple[tuple[tuple[str, int, int], ...], tuple[int, int]]
    ) -> tuple[int, int]:
        parent_identity, database_identity = identity
        parent_descriptor, _parent_stat = self._verify_windows_private_path(
            self._path.parent,
            is_directory=True,
            expected_identity=parent_identity[-1][1:],
        )
        try:
            database_descriptor, _database_stat = self._verify_windows_private_path(
                self._path,
                is_directory=False,
                expected_identity=database_identity,
            )
        except BaseException:
            os.close(parent_descriptor)
            raise
        return parent_descriptor, database_descriptor

    def _verify_windows_private_handles(
        self,
        identity: tuple[tuple[tuple[str, int, int], ...], tuple[int, int]],
        handles: Optional[tuple[int, int]],
    ) -> None:
        if handles is None:
            raise RuntimeError("operational_review_replay_windows_acl_unavailable")
        from .credential_resolver import _windows_os_handle

        parent_identity, database_identity = identity
        for descriptor, path, expected in (
            (handles[0], self._path.parent, parent_identity[-1][1:]),
            (handles[1], self._path, database_identity),
        ):
            opened = os.fstat(descriptor)
            if _file_identity(opened) != expected:
                raise RuntimeError("operational_review_replay_path_changed")
            owner, current_user, protected, entries = _windows_acl_details_for_handle(
                _windows_os_handle(descriptor)
            )
            _validate_windows_private_acl(owner, current_user, protected, entries)
            current = os.lstat(str(path))
            if _is_link_or_reparse(current) or _file_identity(current) != expected:
                raise RuntimeError("operational_review_replay_path_changed")

    def _secure_windows_sqlite_sidecars(self) -> None:
        """Verify rollback journals and reject unsupported WAL sidecars."""

        journal_path = Path(str(self._path) + "-journal")
        for suffix in ("-wal", "-shm"):
            unsupported = Path(str(self._path) + suffix)
            try:
                entry = os.lstat(str(unsupported))
            except FileNotFoundError:
                continue
            if _is_link_or_reparse(entry) or not stat.S_ISREG(entry.st_mode):
                raise RuntimeError("operational_review_replay_sidecar_invalid")
            raise RuntimeError("operational_review_replay_wal_unsupported")

        try:
            journal_entry = os.lstat(str(journal_path))
        except FileNotFoundError:
            return
        if (
            _is_link_or_reparse(journal_entry)
            or not stat.S_ISREG(journal_entry.st_mode)
            or getattr(journal_entry, "st_nlink", 1) != 1
        ):
            raise RuntimeError("operational_review_replay_sidecar_invalid")
        if os.name == "nt":
            self._verify_windows_sidecar_path(journal_path, journal_entry)
        elif stat.S_IMODE(journal_entry.st_mode) & 0o077:
            raise RuntimeError("operational_review_replay_permissions_invalid")

    def _verify_windows_sidecar_path(self, path: Path, before: os.stat_result) -> None:
        from .credential_resolver import _open_windows_metadata_handle, _windows_os_handle

        descriptor = _open_windows_metadata_handle(path, is_directory=False)
        try:
            opened = os.fstat(descriptor)
            if _file_identity(opened) != _file_identity(before):
                raise RuntimeError("operational_review_replay_path_changed")
            owner, current_user, _protected, entries = _windows_acl_details_for_handle(
                _windows_os_handle(descriptor)
            )
            _validate_windows_sidecar_acl(owner, current_user, entries)
            after = os.lstat(str(path))
            if (
                _is_link_or_reparse(after)
                or not stat.S_ISREG(after.st_mode)
                or _file_identity(after) != _file_identity(opened)
            ):
                raise RuntimeError("operational_review_replay_path_changed")
        finally:
            os.close(descriptor)

    def _check_database_integrity(self, connection: sqlite3.Connection) -> None:
        try:
            rows = connection.execute("PRAGMA quick_check").fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError("operational_review_replay_corrupt") from exc
        if rows != [("ok",)]:
            raise RuntimeError("operational_review_replay_corrupt")

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        expected = {self._META_TABLE, self._PERMIT_TABLE, self._ACTION_TABLE}
        all_objects = connection.execute(
            "SELECT type, name FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        internal_objects = [row for row in all_objects if row[1].startswith("sqlite_")]
        if any(
            object_type != "index" or not name.startswith("sqlite_autoindex_")
            for object_type, name in internal_objects
        ):
            raise RuntimeError("operational_review_replay_schema_invalid")
        objects = [row for row in all_objects if not row[1].startswith("sqlite_")]
        if not objects:
            connection.execute(
                "CREATE TABLE "
                + self._META_TABLE
                + " (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                "schema_version INTEGER NOT NULL, marker TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE "
                + self._PERMIT_TABLE
                + " (permit_id TEXT PRIMARY KEY NOT NULL, request_digest TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE "
                + self._ACTION_TABLE
                + " (action_replay_key TEXT PRIMARY KEY NOT NULL, "
                "permit_id TEXT NOT NULL UNIQUE, request_digest TEXT NOT NULL, "
                "FOREIGN KEY (permit_id) REFERENCES " + self._PERMIT_TABLE + " (permit_id))"
            )
            connection.execute(
                "INSERT INTO "
                + self._META_TABLE
                + " (singleton, schema_version, marker) VALUES (1, ?, ?)",
                (self._SCHEMA_VERSION, self._SCHEMA_MARKER),
            )
            return

        if set(objects) != {("table", name) for name in expected} or len(objects) != len(expected):
            raise RuntimeError("operational_review_replay_schema_invalid")
        metadata = connection.execute(
            "SELECT singleton, schema_version, marker FROM " + self._META_TABLE
        ).fetchall()
        if metadata != [(1, self._SCHEMA_VERSION, self._SCHEMA_MARKER)]:
            raise RuntimeError("operational_review_replay_schema_invalid")
        expected_columns = {
            self._META_TABLE: (
                ("singleton", "INTEGER", 0, 1),
                ("schema_version", "INTEGER", 1, 0),
                ("marker", "TEXT", 1, 0),
            ),
            self._PERMIT_TABLE: (
                ("permit_id", "TEXT", 1, 1),
                ("request_digest", "TEXT", 1, 0),
            ),
            self._ACTION_TABLE: (
                ("action_replay_key", "TEXT", 1, 1),
                ("permit_id", "TEXT", 1, 0),
                ("request_digest", "TEXT", 1, 0),
            ),
        }
        for table, expected_column_rows in expected_columns.items():
            actual_column_rows = connection.execute("PRAGMA table_info(" + table + ")").fetchall()
            actual_columns = tuple(
                (row[1], row[2].upper(), row[3], row[5]) for row in actual_column_rows
            )
            if actual_columns != expected_column_rows:
                raise RuntimeError("operational_review_replay_schema_invalid")

        action_unique_indexes = []
        for _sequence, index_name, is_unique, origin, is_partial in connection.execute(
            "PRAGMA index_list(" + self._ACTION_TABLE + ")"
        ):
            if is_unique:
                index_columns = tuple(
                    row[2] for row in connection.execute("PRAGMA index_info(" + index_name + ")")
                )
                action_unique_indexes.append((index_columns, origin, is_partial))
        if set(action_unique_indexes) != {
            (("action_replay_key",), "pk", 0),
            (("permit_id",), "u", 0),
        }:
            raise RuntimeError("operational_review_replay_schema_invalid")
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(" + self._ACTION_TABLE + ")"
        ).fetchall()
        if len(foreign_keys) != 1 or (
            foreign_keys[0][2],
            foreign_keys[0][3],
            foreign_keys[0][4],
        ) != (self._PERMIT_TABLE, "permit_id", "permit_id"):
            raise RuntimeError("operational_review_replay_schema_invalid")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("operational_review_replay_corrupt")


class HmacCtpSimNowOperationalWindowReviewer:
    """Verify signed SimNow reviews with injected trust, UTC, and replay state.

    There are no default keys, policy, UTC source, review source, or replay
    store.  The signed claims bind the whole operational scope and action.
    A valid result is still not an execution capability or F14 writer fence.
    """

    def __init__(
        self,
        *,
        review_source: CtpSimNowOperationalReviewSource,
        key_resolver: CtpSimNowOperationalReviewKeyResolver,
        trusted_utc: Callable[[], object],
        replay_guard: CtpSimNowOperationalReviewReplayGuard,
    ) -> None:
        if not callable(getattr(review_source, "issue_action_review", None)):
            _reject("operational_review_source_required")
        if not callable(getattr(key_resolver, "resolve", None)):
            _reject("operational_review_key_resolver_required")
        if not callable(trusted_utc):
            _reject("operational_review_trusted_utc_required")
        if not callable(getattr(replay_guard, "claim_once", None)):
            _reject("operational_review_replay_guard_required")
        self._review_source = review_source
        self._key_resolver = key_resolver
        self._trusted_utc = trusted_utc
        self._replay_guard = replay_guard
        self._lock = threading.RLock()
        self._accepted: dict[str, CtpSimNowSignedOperationalReview] = {}

    def issue_action_review(
        self, request: CtpSimNowOperationalActionRequest
    ) -> CtpSimNowOperationalWindowPermit:
        if type(request) is not CtpSimNowOperationalActionRequest:
            _reject("operational_action_request_required")
        try:
            envelope = self._review_source.issue_action_review(request)
        except Exception:
            _reject("operational_window_review_unavailable")
        if (
            type(envelope) is not CtpSimNowSignedOperationalReview
            or envelope.permit.binding != request
        ):
            _reject("operational_window_review_scope_mismatch")
        self._verify_envelope(envelope, request)

        permit = envelope.permit
        action_replay_key = hashlib.sha256(
            _REPLAY_DOMAIN
            + _canonical_bytes(
                {"scope_digest": request.scope.scope_digest, "action_id": request.action_id}
            )
        ).hexdigest()
        with self._lock:
            if permit.permit_id in self._accepted:
                _reject("operational_window_review_replayed")
            try:
                claimed = self._replay_guard.claim_once(
                    permit.permit_id, action_replay_key, request.request_digest
                )
            except Exception:
                _reject("operational_window_replay_check_unavailable")
            if claimed is not True:
                _reject("operational_window_review_replayed")
            self._accepted[permit.permit_id] = envelope
        return permit

    def assert_action_review_current(
        self,
        permit: CtpSimNowOperationalWindowPermit,
        *,
        request: CtpSimNowOperationalActionRequest,
    ) -> bool:
        if (
            type(permit) is not CtpSimNowOperationalWindowPermit
            or type(request) is not CtpSimNowOperationalActionRequest
            or permit.binding != request
        ):
            _reject("operational_window_review_scope_mismatch")
        with self._lock:
            envelope = self._accepted.get(permit.permit_id)
        if envelope is None or envelope.permit != permit:
            _reject("operational_window_review_unavailable")
        self._verify_envelope(envelope, request)
        return True

    def _verify_envelope(
        self,
        envelope: CtpSimNowSignedOperationalReview,
        request: CtpSimNowOperationalActionRequest,
    ) -> None:
        if envelope.permit.binding != request:
            _reject("operational_window_review_scope_mismatch")
        try:
            policy = self._key_resolver.resolve(envelope.key_id)
        except Exception:
            _reject("operational_review_key_unavailable")
        if (
            type(policy) is not CtpSimNowOperationalReviewKeyPolicy
            or policy.key_id != envelope.key_id
            or policy.revoked
        ):
            _reject("operational_review_key_unavailable")
        permit = envelope.permit
        scope = request.scope
        if (
            permit.review_authority_id != policy.review_authority_id
            or permit.revocation_epoch != policy.current_revocation_epoch
            or scope.account_fingerprint_sha256 not in policy.allowed_account_fingerprints
            or scope.window_id not in policy.allowed_window_ids
            or scope.session_identity_digest not in policy.allowed_session_identity_digests
            or scope.trading_day not in policy.allowed_trading_days
            or scope.risk_limits.digest not in policy.allowed_risk_limits_digests
            or request.action_kind not in policy.allowed_action_kinds
        ):
            _reject("operational_review_issuer_policy_rejected")
        issued = permit.issued_at_utc
        expires = permit.expires_at_utc
        ttl = expires - issued
        if ttl <= 0 or ttl > policy.max_ttl_seconds:
            _reject("operational_window_review_expired")
        try:
            now = _finite_utc(self._trusted_utc())
        except Exception:
            _reject("operational_review_trusted_utc_unavailable")
        if now < issued or now >= expires:
            _reject("operational_window_review_expired")
        expected = hmac.new(policy.key_bytes, envelope.signed_payload(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, envelope.signature_hex):
            _reject("operational_window_review_signature_invalid")


__all__ = [
    "LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard",
    "CtpSimNowOperationalReviewKeyPolicy",
    "CtpSimNowOperationalReviewKeyResolver",
    "CtpSimNowOperationalReviewReplayGuard",
    "CtpSimNowOperationalReviewSource",
    "CtpSimNowSignedOperationalReview",
    "HmacCtpSimNowOperationalWindowReviewer",
]
