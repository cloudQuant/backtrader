"""Fail-closed, local credential resolution for future provider factories.

This module deliberately resolves only a narrowly scoped authentication
payload.  It does *not* import a provider SDK, open a network connection,
prove that an account exists, start preflight, or authorize any external
write.  A future provider factory must revalidate the sealed result before it
uses a value and must perform its own provider-side identity checks.

The matching credential source is selected by a code-owned
:class:`RuntimeCredentialScope`; a secret payload cannot provide or override a
provider, front, endpoint, environment, route, account fingerprint, mode, or
preset. The exact CTP ``simulation/sandbox`` route may use a loader-sealed
``ctp_simnow`` block in ``config.yaml``. That source requires a protected
runtime directory and config file on POSIX, or a current-user-owned protected
DACL on Windows, both when the registered loader reads the file and again
before credentials are released.

Two sources are intentionally narrow:

* ``runtime_secrets`` reads exactly ``<registered-runtime-dir>/secrets.yaml``
  through the registry's verified-directory lease.  It is supported only on
  POSIX, where the standard library can verify owner and restrictive mode bits
  on both the directory and file.  Windows rejects this source because Python's
  standard library cannot prove a file DACL/owner safely enough.
* ``os_secret_store:<name>`` is supported only on Windows via Credential
  Manager ``CredReadW``.  It reads the exact code-owned ``<name>`` target as a
  Generic credential, copies a bounded UTF-8 JSON blob, and calls ``CredFree``
  on every allocated result.  No environment variable, CWD, parent-directory,
  file fallback, or provider import exists.

Credential values are necessarily available to trusted in-process factory
code.  Python cannot make an in-process string a secret boundary, so this
module instead prevents accidental disclosure through public projections,
reprs, errors, and default resolution paths.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import stat
import weakref
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from .config import CtpSimNowPrivateConfig, _load_strict_yaml
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .policy import get_preset_policy
from .registry import EffectiveRuntimeConfig, RuntimeRegistry, require_effective_runtime_config_seal


RUNTIME_SECRETS_FILENAME = "secrets.yaml"
RUNTIME_SECRETS_REF = "runtime_secrets"
CONFIG_YAML_REF = "config_yaml"
OS_SECRET_STORE_PREFIX = "os_secret_store:"
MAX_RUNTIME_SECRETS_BYTES = 64 * 1024
# ``CRED_MAX_CREDENTIAL_BLOB_SIZE`` is 5 * 512 bytes.  Enforce it ourselves
# before decoding even if a platform returns a malformed credential record.
MAX_OS_SECRET_STORE_BLOB_BYTES = 5 * 512
MAX_CREDENTIAL_VALUE_BYTES = 2048

# Future CTP factories can import this code-owned tuple instead of accepting a
# caller-selected credential schema.  Every key is required when this tuple is
# used; a provider with a different reviewed authentication scheme must declare
# a separate, explicit tuple in its own composition root.
CTP_AUTHENTICATION_CREDENTIAL_KEYS = (
    "broker_id",
    "user_id",
    "password",
    "app_id",
    "auth_code",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ENVIRONMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_CREDENTIAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OS_SECRET_REF_RE = re.compile(r"^os_secret_store:([A-Za-z0-9][A-Za-z0-9._-]{0,127})$")
_CTP_SIMNOW_ENVIRONMENT = "simnow"

# These fields control a route or identity rather than authenticate.  The
# secrets payload is not allowed to smuggle any of them into a later factory.
_CONTROL_CREDENTIAL_KEYS = frozenset(
    (
        "account",
        "account_access",
        "account_fingerprint",
        "account_fingerprint_sha256",
        "account_id",
        "approval",
        "approval_receipt_digest",
        "capability",
        "capability_digest",
        "config_digest",
        "effective_config_digest",
        "endpoint",
        "environment",
        "front",
        "gateway",
        "host",
        "md_front",
        "mode",
        "order_route",
        "policy",
        "preset",
        "production",
        "provider",
        "provider_environment",
        "registration",
        "registration_digest",
        "route",
        "runtime",
        "runtime_id",
        "strategy",
        "strategy_id",
        "td_front",
        "url",
    )
)


class CredentialResolutionError(RuntimeConfigError):
    """A stable, redacted failure while locating a provider credential.

    This keeps the existing Iteration 41 error vocabulary while giving future
    factories a distinct exception type and a reason that never interpolates a
    secret value, credential-manager target, or filesystem path.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(
            PRESET_POLICY_VIOLATION,
            message,
            field_path="runtime.credentials",
            reason=reason,
        )


def _reject(reason: str, message: str) -> None:
    raise CredentialResolutionError(reason, message)


def _platform_name() -> str:
    """Small seam for platform-specific unit tests; never reads environment."""

    return os.name


def _strict_identifier(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) > 128
        or value != value.strip()
        or not _IDENTIFIER_RE.fullmatch(value)
    ):
        raise ValueError("{0} must be a non-empty code-owned identifier".format(field_name))
    return value


def _strict_provider(value: Any) -> str:
    if (
        type(value) is not str
        or len(value) > 64
        or value != value.strip()
        or not _PROVIDER_RE.fullmatch(value)
    ):
        raise ValueError("provider must be a lower-case code-owned identifier")
    return value


def _strict_environment(value: Any) -> str:
    if (
        type(value) is not str
        or len(value) > 128
        or value != value.strip()
        or not _ENVIRONMENT_RE.fullmatch(value)
    ):
        raise ValueError("provider_environment must be a code-owned environment identifier")
    return value


def _strict_digest(value: Any, field_name: str) -> str:
    if type(value) is not str or len(value) != 64 or not _SHA256_RE.fullmatch(value):
        raise ValueError("{0} must be a lower-case SHA-256 digest".format(field_name))
    return value


def _strict_secret_ref(value: Any) -> str:
    if type(value) is str and value in (RUNTIME_SECRETS_REF, CONFIG_YAML_REF):
        return value
    if type(value) is str and _OS_SECRET_REF_RE.fullmatch(value):
        return value
    raise ValueError(
        "secrets_ref must select config_yaml, runtime_secrets, or a code-owned OS secret-store name"
    )


def _strict_credential_keys(value: Any) -> Tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise ValueError("credential_keys must be a non-empty exact tuple")
    if len(value) > 16:
        raise ValueError("credential_keys contains too many values")
    normalized = []
    for key in value:
        if (
            type(key) is not str
            or len(key) > 64
            or not _CREDENTIAL_KEY_RE.fullmatch(key)
            or key in _CONTROL_CREDENTIAL_KEYS
        ):
            raise ValueError("credential_keys contains an unsafe credential field name")
        normalized.append(key)
    if len(set(normalized)) != len(normalized):
        raise ValueError("credential_keys contains duplicates")
    return tuple(normalized)


@dataclass(frozen=True)
class RuntimeCredentialScope:
    """Code-owned authentication scope for exactly one sealed runtime route.

    The scope is deliberately constructed in provider composition code, never
    parsed from YAML. ``provider_environment`` is a code-owned label; for CTP
    sandbox credentials it is exactly ``simnow`` and independent of front
    addresses, which are bound separately by the selected route. The
    ``policy_environment`` must
    match the Iteration 41 preset policy and prevents a sandbox config from
    resolving a production-labelled source.
    """

    runtime_id: str
    strategy_id: str
    provider: str
    provider_environment: str
    policy_environment: str
    mode: str
    preset: str
    account_access: str
    account_fingerprint_sha256: str = field(repr=False)
    secrets_ref: str = field(repr=False)
    credential_keys: Tuple[str, ...]
    effective_config_digest: str = field(repr=False)
    registration_digest: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_id", _strict_identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(self, "strategy_id", _strict_identifier(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "provider", _strict_provider(self.provider))
        object.__setattr__(
            self, "provider_environment", _strict_environment(self.provider_environment)
        )
        if type(self.policy_environment) is not str or self.policy_environment not in (
            "sandbox",
            "production",
        ):
            raise ValueError("policy_environment must be sandbox or production")
        if type(self.mode) is not str or type(self.preset) is not str:
            raise ValueError("mode and preset must be strings")
        policy = get_preset_policy(self.preset)
        if policy is None or policy.mode != self.mode:
            raise ValueError("mode and preset must match a reviewed policy")
        if policy.environment != self.policy_environment:
            raise ValueError("policy_environment must match the reviewed preset policy")
        if self.provider == "ctp":
            if (
                self.policy_environment == "sandbox"
                and self.provider_environment != _CTP_SIMNOW_ENVIRONMENT
            ):
                raise ValueError(
                    "a CTP sandbox credential scope must use the code-owned SimNow environment"
                )
            if (
                self.policy_environment == "production"
                and self.provider_environment != "production"
            ):
                raise ValueError("a CTP production credential scope must name exact production")
        elif self.policy_environment == "sandbox" and self.provider_environment.casefold() in {
            "production",
            "prod",
            "live",
        }:
            raise ValueError("a sandbox credential scope cannot name a production environment")
        if (
            type(self.account_access) is not str
            or len(self.account_access) > 128
            or not _IDENTIFIER_RE.fullmatch(self.account_access)
        ):
            raise ValueError("account_access must be a code-owned route identifier")
        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _strict_digest(self.account_fingerprint_sha256, "account_fingerprint_sha256"),
        )
        object.__setattr__(self, "secrets_ref", _strict_secret_ref(self.secrets_ref))
        credential_keys = _strict_credential_keys(self.credential_keys)
        if self.provider == "ctp" and credential_keys != CTP_AUTHENTICATION_CREDENTIAL_KEYS:
            raise ValueError("a CTP credential scope requires the full fixed CTP schema")
        object.__setattr__(self, "credential_keys", credential_keys)
        object.__setattr__(
            self,
            "effective_config_digest",
            _strict_digest(self.effective_config_digest, "effective_config_digest"),
        )
        object.__setattr__(
            self,
            "registration_digest",
            _strict_digest(self.registration_digest, "registration_digest"),
        )

    def __repr__(self) -> str:
        return (
            "RuntimeCredentialScope(runtime_id={!r}, strategy_id={!r}, provider={!r}, "
            "provider_environment={!r}, policy_environment={!r}, mode={!r}, preset={!r}, "
            "account_access={!r}, credential_keys={!r})"
        ).format(
            self.runtime_id,
            self.strategy_id,
            self.provider,
            self.provider_environment,
            self.policy_environment,
            self.mode,
            self.preset,
            self.account_access,
            self.credential_keys,
        )

    def as_public_dict(self) -> Dict[str, Any]:
        """Return only code-owned route metadata, never refs or account IDs."""

        return {
            "runtime_id": self.runtime_id,
            "strategy_id": self.strategy_id,
            "provider": self.provider,
            "provider_environment": self.provider_environment,
            "policy_environment": self.policy_environment,
            "mode": self.mode,
            "preset": self.preset,
            "account_access": self.account_access,
            "credential_count": len(self.credential_keys),
            "effective_config_digest": self.effective_config_digest,
            "registration_digest": self.registration_digest,
        }


def _snapshot_scope(scope: RuntimeCredentialScope) -> RuntimeCredentialScope:
    """Copy validated scope facts after rejecting subclasses and mutation."""

    if type(scope) is not RuntimeCredentialScope:
        _reject(
            "credential_scope_invalid",
            "credential scope must be a code-owned RuntimeCredentialScope",
        )
    try:
        return RuntimeCredentialScope(
            runtime_id=scope.runtime_id,
            strategy_id=scope.strategy_id,
            provider=scope.provider,
            provider_environment=scope.provider_environment,
            policy_environment=scope.policy_environment,
            mode=scope.mode,
            preset=scope.preset,
            account_access=scope.account_access,
            account_fingerprint_sha256=scope.account_fingerprint_sha256,
            secrets_ref=scope.secrets_ref,
            credential_keys=scope.credential_keys,
            effective_config_digest=scope.effective_config_digest,
            registration_digest=scope.registration_digest,
        )
    except (AttributeError, TypeError, ValueError):
        _reject("credential_scope_invalid", "credential scope is not a valid code-owned binding")
    raise AssertionError("unreachable")


def _scope_facts(scope: RuntimeCredentialScope) -> Tuple[Any, ...]:
    return (
        scope.runtime_id,
        scope.strategy_id,
        scope.provider,
        scope.provider_environment,
        scope.policy_environment,
        scope.mode,
        scope.preset,
        scope.account_access,
        scope.account_fingerprint_sha256,
        scope.secrets_ref,
        scope.credential_keys,
        scope.effective_config_digest,
        scope.registration_digest,
    )


def _require_matching_scope(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    scope: RuntimeCredentialScope,
) -> RuntimeCredentialScope:
    """Bind code-owned credential scope to one sealed config and registration."""

    require_effective_runtime_config_seal(effective, registry)
    if effective.profile is not None:
        from .ctp_sandbox_readonly_admission import (
            CtpSandboxReadOnlyAdmissionError,
            require_ctp_sandbox_profile_runtime,
        )

        try:
            require_ctp_sandbox_profile_runtime(effective, registry)
        except CtpSandboxReadOnlyAdmissionError:
            _reject(
                "profile_scoped_credentials_unavailable",
                "profile credentials require the exact zero-write CTP sandbox route",
            )
    snapshot = _snapshot_scope(scope)
    registration = effective.registration

    if (
        snapshot.runtime_id != registration.runtime_id
        or snapshot.strategy_id != effective.strategy_id
        or snapshot.mode != effective.mode
        or snapshot.preset != effective.preset
        or snapshot.account_access != effective.account_access
    ):
        _reject(
            "credential_scope_runtime_mismatch",
            "credential scope does not match the sealed runtime route",
        )
    if snapshot.policy_environment != effective.policy.environment:
        _reject(
            "credential_scope_environment_mismatch",
            "credential scope does not match the sealed runtime environment",
        )
    if snapshot.secrets_ref != effective.config.secrets_ref:
        _reject(
            "credential_scope_secret_ref_mismatch",
            "credential scope does not match the sealed secret reference",
        )
    if snapshot.effective_config_digest != effective.effective_digest:
        _reject(
            "credential_scope_config_mismatch",
            "credential scope does not match the sealed effective configuration",
        )
    if snapshot.registration_digest != registration.digest:
        _reject(
            "credential_scope_registration_mismatch",
            "credential scope does not match the reviewed runtime registration",
        )
    if not effective.policy.accepts_provider_secrets:
        _reject(
            "credential_scope_secrets_not_allowed",
            "the sealed runtime policy does not accept provider credentials",
        )
    if snapshot.policy_environment == "sandbox":
        if effective.allows_production_writes or (
            snapshot.provider != "ctp"
            and snapshot.provider_environment.casefold() in {"production", "prod", "live"}
        ):
            _reject(
                "credential_scope_sandbox_production_mismatch",
                "a sandbox credential scope cannot resolve a production route",
            )
    elif snapshot.policy_environment == "production":
        if not effective.allows_production_writes:
            _reject(
                "credential_scope_production_route_mismatch",
                "a production credential scope requires the sealed production route",
            )
    else:  # Defensive in case a frozen scope was mutated after validation.
        _reject(
            "credential_scope_environment_mismatch",
            "credential scope has an unsupported environment",
        )
    return snapshot


def _is_link_or_reparse(result: os.stat_result) -> bool:
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(result, "st_file_attributes", 0)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_point)


def _require_posix_directory_security(directory_fd: int) -> None:
    try:
        result = os.fstat(directory_fd)
        effective_uid = os.geteuid()
    except (AttributeError, OSError):
        _reject(
            "runtime_secrets_platform_acl_unavailable",
            "runtime_secrets requires verified POSIX owner and permission checks",
        )
    if not stat.S_ISDIR(result.st_mode) or result.st_uid != effective_uid or result.st_mode & 0o022:
        _reject(
            "runtime_secrets_directory_unsafe",
            "the registered runtime directory is not safe for credential resolution",
        )


def _require_posix_secret_security(result: os.stat_result) -> None:
    try:
        effective_uid = os.geteuid()
    except AttributeError:
        _reject(
            "runtime_secrets_platform_acl_unavailable",
            "runtime_secrets requires verified POSIX owner and permission checks",
        )
    if result.st_uid != effective_uid or result.st_mode & 0o077 or result.st_nlink != 1:
        _reject(
            "runtime_secrets_file_unsafe",
            "secrets.yaml must be an owner-only unlinked regular file",
        )


def _read_runtime_secrets_text(runtime_dir: Path, directory_fd: Optional[int]) -> str:
    """Read exactly one owner-protected secret file through a verified FD."""

    del runtime_dir  # A caller must not reopen the pathname outside the lease.
    if _platform_name() != "posix" or directory_fd is None:
        _reject(
            "runtime_secrets_platform_acl_unavailable",
            "runtime_secrets is unavailable until this platform can prove secret-file ownership and ACLs",
        )
    _require_posix_directory_security(directory_fd)
    try:
        path_stat = os.lstat(RUNTIME_SECRETS_FILENAME, dir_fd=directory_fd)
    except FileNotFoundError:
        _reject(
            "runtime_secrets_missing",
            "required secrets.yaml is missing from the registered runtime directory",
        )
    except OSError:
        _reject("runtime_secrets_unreadable", "secrets.yaml cannot be opened safely")
    if _is_link_or_reparse(path_stat):
        _reject("runtime_secrets_symlink_not_allowed", "secrets.yaml must not be a symbolic link")
    if not stat.S_ISREG(path_stat.st_mode):
        _reject("runtime_secrets_not_regular_file", "secrets.yaml must be a regular file")
    _require_posix_secret_security(path_stat)

    # ``lstat`` alone cannot close the replacement race between inspection and
    # open.  Do not claim the POSIX file source is safe on an implementation
    # which cannot request a non-following open of the final leaf.
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if type(no_follow) is not int or no_follow == 0:
        _reject(
            "runtime_secrets_platform_acl_unavailable",
            "runtime_secrets requires non-following descriptor-relative file opens",
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | no_follow
    try:
        descriptor = os.open(RUNTIME_SECRETS_FILENAME, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        _reject(
            "runtime_secrets_missing",
            "required secrets.yaml is missing from the registered runtime directory",
        )
    except OSError:
        _reject("runtime_secrets_unreadable", "secrets.yaml cannot be opened safely")

    descriptor_stat: Optional[os.stat_result] = None
    try:
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_stat.st_mode):
            _reject("runtime_secrets_not_regular_file", "secrets.yaml must be a regular file")
        if (path_stat.st_dev, path_stat.st_ino) != (descriptor_stat.st_dev, descriptor_stat.st_ino):
            _reject(
                "runtime_secrets_identity_changed",
                "secrets.yaml changed while it was being opened",
            )
        _require_posix_secret_security(descriptor_stat)
        chunks = []
        remaining = MAX_RUNTIME_SECRETS_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    except CredentialResolutionError:
        raise
    except OSError:
        _reject("runtime_secrets_unreadable", "secrets.yaml cannot be opened safely")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    try:
        final_stat = os.lstat(RUNTIME_SECRETS_FILENAME, dir_fd=directory_fd)
    except OSError:
        final_stat = None
    if (
        descriptor_stat is None
        or final_stat is None
        or _is_link_or_reparse(final_stat)
        or not stat.S_ISREG(final_stat.st_mode)
        or (final_stat.st_dev, final_stat.st_ino)
        != (descriptor_stat.st_dev, descriptor_stat.st_ino)
    ):
        _reject(
            "runtime_secrets_identity_changed",
            "secrets.yaml changed while it was being read",
        )
    _require_posix_secret_security(final_stat)
    if len(raw) > MAX_RUNTIME_SECRETS_BYTES:
        _reject("runtime_secrets_too_large", "secrets.yaml exceeds the supported size")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject("runtime_secrets_invalid_encoding", "secrets.yaml must be UTF-8 text")
    raise AssertionError("unreachable")


class _WindowsFileTime(ctypes.Structure):
    _fields_ = (("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD))


class _WindowsCredentialW(ctypes.Structure):
    """The documented ``CREDENTIALW`` layout used only with CredReadW."""

    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _WindowsFileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


@dataclass(frozen=True)
class _WindowsCredentialApi:
    cred_read: Any
    cred_free: Any
    generic_type: int = 1


def _validate_windows_acl_entries(
    owner_sid: str, entries: Tuple[Tuple[int, int, str], ...]
) -> None:
    """Accept only explicit allow/deny ACEs for owner, SYSTEM, or admins.

    Unknown trustees, inherited ACEs, and complex/object ACEs fail closed.
    This is intentionally stricter than Windows' full ACL inheritance model.
    """

    broad_sids = {
        "S-1-1-0",  # Everyone
        "S-1-5-7",  # Anonymous
        "S-1-5-11",  # Authenticated Users
        "S-1-5-32-545",  # Builtin Users
        "S-1-5-32-546",  # Builtin Guests
    }
    if owner_sid in broad_sids:
        _reject(
            "config_yaml_windows_acl_invalid",
            "config_yaml requires an explicit owner-only Windows ACL",
        )
    allowed_sids = {owner_sid, "S-1-5-18", "S-1-5-32-544"}
    for ace_type, ace_flags, trustee_sid in entries:
        if ace_type not in (0, 1) or ace_flags & 0x10 or trustee_sid not in allowed_sids:
            _reject(
                "config_yaml_windows_acl_invalid",
                "config_yaml requires an explicit owner-only Windows ACL",
            )


def _validate_windows_acl_owner(owner_sid: str, current_user_sid: str) -> None:
    """Require the metadata object's owner to be this process's user SID."""

    broad_or_group_sids = {
        "S-1-1-0",  # Everyone
        "S-1-5-7",  # Anonymous
        "S-1-5-11",  # Authenticated Users
        "S-1-5-32-544",  # Builtin Administrators is a group, not a user owner
        "S-1-5-32-545",  # Builtin Users
        "S-1-5-32-546",  # Builtin Guests
    }
    if owner_sid != current_user_sid or owner_sid in broad_or_group_sids:
        _reject(
            "config_yaml_windows_acl_invalid",
            "config.yaml owner must match the current process user",
        )


def _validate_windows_dacl_control(is_protected: bool) -> None:
    """Require a protected DACL so parent ACL edits cannot widen access."""

    if not is_protected:
        _reject(
            "config_yaml_windows_acl_invalid",
            "config_yaml requires a protected Windows DACL",
        )


class _WindowsAclSizeInformation(ctypes.Structure):
    _fields_ = (
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    )


def _current_windows_user_sid(advapi32: Any, kernel32: Any) -> str:
    """Return the current process token's user SID for owner binding."""

    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    open_process_token.restype = wintypes.BOOL
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not open_process_token(get_current_process(), 0x0008, ctypes.byref(token)):
        _reject(
            "config_yaml_windows_acl_unavailable",
            "Windows could not verify the private config owner",
        )
    try:
        get_token_information = advapi32.GetTokenInformation
        get_token_information.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        get_token_information.restype = wintypes.BOOL
        token_user = ctypes.create_string_buffer(64 * 1024)
        required = wintypes.DWORD()
        if not get_token_information(
            token, 1, token_user, ctypes.sizeof(token_user), ctypes.byref(required)
        ):
            _reject(
                "config_yaml_windows_acl_unavailable",
                "Windows could not verify the private config owner",
            )
        sid = ctypes.cast(token_user, ctypes.POINTER(ctypes.c_void_p))[0]
        if not sid:
            _reject(
                "config_yaml_windows_acl_unavailable",
                "Windows could not verify the private config owner",
            )
        return _windows_sid_to_string(advapi32, kernel32, sid)
    finally:
        close_handle(token)


def _windows_sid_to_string(advapi32: Any, kernel32: Any, sid: ctypes.c_void_p) -> str:
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    convert_sid.restype = wintypes.BOOL
    sid_text = wintypes.LPWSTR()
    if not convert_sid(sid, ctypes.byref(sid_text)) or not sid_text:
        _reject(
            "config_yaml_windows_acl_unavailable",
            "Windows could not verify the private config ACL",
        )
    try:
        return sid_text.value
    finally:
        local_free = kernel32.LocalFree
        local_free.argtypes = (ctypes.c_void_p,)
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(sid_text, ctypes.c_void_p))


def _windows_acl_for_handle(handle: int) -> None:
    """Inspect a Win32 handle's owner and DACL without opening file contents."""

    try:
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
            1,  # SE_FILE_OBJECT
            0x00000001 | 0x00000004,  # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
            ctypes.byref(owner_sid),
            ctypes.byref(group_sid),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if result != 0 or not descriptor:
            if descriptor:
                local_free = kernel32.LocalFree
                local_free.argtypes = (ctypes.c_void_p,)
                local_free.restype = ctypes.c_void_p
                local_free(descriptor)
            _reject(
                "config_yaml_windows_acl_unavailable",
                "Windows could not verify the private config ACL",
            )

        try:
            get_control = advapi32.GetSecurityDescriptorControl
            get_control.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.WORD),
                ctypes.POINTER(wintypes.DWORD),
            )
            get_control.restype = wintypes.BOOL
            descriptor_control = wintypes.WORD()
            descriptor_revision = wintypes.DWORD()
            if not get_control(
                descriptor,
                ctypes.byref(descriptor_control),
                ctypes.byref(descriptor_revision),
            ):
                _reject(
                    "config_yaml_windows_acl_unavailable",
                    "Windows could not verify the private config DACL",
                )
            _validate_windows_dacl_control(bool(descriptor_control.value & 0x1000))

            get_owner = advapi32.GetSecurityDescriptorOwner
            get_owner.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(wintypes.BOOL),
            )
            get_owner.restype = wintypes.BOOL
            owner_defaulted = wintypes.BOOL()
            if not get_owner(descriptor, ctypes.byref(owner_sid), ctypes.byref(owner_defaulted)):
                _reject(
                    "config_yaml_windows_acl_unavailable",
                    "Windows could not verify the private config ACL",
                )
            is_valid_sid = advapi32.IsValidSid
            is_valid_sid.argtypes = (ctypes.c_void_p,)
            is_valid_sid.restype = wintypes.BOOL
            if not owner_sid or not is_valid_sid(owner_sid):
                _reject(
                    "config_yaml_windows_acl_invalid",
                    "config_yaml requires an explicit owner-only Windows ACL",
                )
            owner_sid_text = _windows_sid_to_string(advapi32, kernel32, owner_sid)
            current_user_sid = _current_windows_user_sid(advapi32, kernel32)
            _validate_windows_acl_owner(owner_sid_text, current_user_sid)

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
                _reject(
                    "config_yaml_windows_acl_invalid",
                    "config_yaml requires an explicit owner-only Windows ACL",
                )

            get_acl_information = advapi32.GetAclInformation
            get_acl_information.argtypes = (
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            get_acl_information.restype = wintypes.BOOL
            size_info = _WindowsAclSizeInformation()
            if not get_acl_information(
                dacl,
                ctypes.byref(size_info),
                ctypes.sizeof(size_info),
                2,  # AclSizeInformation
            ):
                _reject(
                    "config_yaml_windows_acl_unavailable",
                    "Windows could not verify the private config ACL",
                )

            get_ace = advapi32.GetAce
            get_ace.argtypes = (
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            )
            get_ace.restype = wintypes.BOOL
            get_length_sid = advapi32.GetLengthSid
            get_length_sid.argtypes = (ctypes.c_void_p,)
            get_length_sid.restype = wintypes.DWORD
            entries = []
            for index in range(int(size_info.AceCount)):
                ace_pointer = ctypes.c_void_p()
                if not get_ace(dacl, index, ctypes.byref(ace_pointer)) or not ace_pointer:
                    _reject(
                        "config_yaml_windows_acl_unavailable",
                        "Windows could not verify the private config ACL",
                    )
                header = ctypes.string_at(ace_pointer, 4)
                ace_type = header[0]
                ace_flags = header[1]
                ace_size = int.from_bytes(header[2:4], byteorder="little")
                if ace_size < 12 or ace_size > int(size_info.AclBytesInUse):
                    _reject(
                        "config_yaml_windows_acl_invalid",
                        "config_yaml requires an explicit owner-only Windows ACL",
                    )
                trustee = ctypes.c_void_p(ace_pointer.value + 8)
                if not is_valid_sid(trustee) or get_length_sid(trustee) > ace_size - 8:
                    _reject(
                        "config_yaml_windows_acl_invalid",
                        "config_yaml requires an explicit owner-only Windows ACL",
                    )
                trustee_sid = _windows_sid_to_string(advapi32, kernel32, trustee)
                entries.append((ace_type, ace_flags, trustee_sid))
            _validate_windows_acl_entries(owner_sid_text, tuple(entries))
        finally:
            kernel32.LocalFree(descriptor)
    except CredentialResolutionError:
        raise
    except Exception:
        _reject(
            "config_yaml_windows_acl_unavailable",
            "Windows could not verify the private config ACL",
        )


def _open_windows_metadata_handle(path: Path, *, is_directory: bool) -> int:
    """Open a path for READ_CONTROL without granting or reading file data."""

    try:
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
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        read_control = 0x00020000
        file_read_attributes = 0x00000080
        share_read_write = 0x00000001 | 0x00000002
        open_existing = 3
        open_reparse_point = 0x00200000
        backup_semantics = 0x02000000 if is_directory else 0
        invalid_handle = ctypes.c_void_p(-1).value
        handle = create_file(
            str(path),
            read_control | file_read_attributes,
            share_read_write,
            None,
            open_existing,
            open_reparse_point | backup_semantics,
            None,
        )
        if handle == invalid_handle or handle == -1:
            _reject(
                "config_yaml_windows_acl_unavailable",
                "Windows could not open the private config metadata safely",
            )
        try:
            return msvcrt.open_osfhandle(
                handle,
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
            )
        except (OSError, ValueError):
            close_handle(handle)
            raise
    except CredentialResolutionError:
        raise
    except Exception:
        _reject(
            "config_yaml_windows_acl_unavailable",
            "Windows could not open the private config metadata safely",
        )
    raise AssertionError("unreachable")


def _require_windows_private_config_acl(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> None:
    """Verify runtime-directory and config-file ACLs under a sealed directory lease."""

    registration = effective.registration
    directory = registration.runtime_dir
    config_path = effective.config.source_path
    expected_file_identity = effective.config._source_file_identity
    if (
        expected_file_identity is None
        or config_path.parent != directory
        or config_path.name != "config.yaml"
    ):
        _reject(
            "config_yaml_windows_identity_unavailable",
            "the private config file identity could not be verified",
        )
    try:
        with registry.verified_runtime_directory(registration):
            directory_lstat = os.lstat(str(directory))
            if _is_link_or_reparse(directory_lstat) or not stat.S_ISDIR(directory_lstat.st_mode):
                _reject(
                    "config_yaml_windows_identity_invalid",
                    "the private runtime directory is not a regular directory",
                )
            directory_fd = _open_windows_metadata_handle(directory, is_directory=True)
            try:
                directory_stat = os.fstat(directory_fd)
                if not registration.directory_identity.matches(directory_stat):
                    _reject(
                        "config_yaml_windows_identity_invalid",
                        "the private runtime directory identity changed",
                    )
                _windows_acl_for_handle(_windows_os_handle(directory_fd))
                if not registration.directory_identity.matches(os.lstat(str(directory))):
                    _reject(
                        "config_yaml_windows_identity_invalid",
                        "the private runtime directory identity changed",
                    )
            finally:
                os.close(directory_fd)

            config_lstat = os.lstat(str(config_path))
            if _is_link_or_reparse(config_lstat) or not stat.S_ISREG(config_lstat.st_mode):
                _reject(
                    "config_yaml_windows_identity_invalid",
                    "the private config file is not a regular file",
                )
            config_fd = _open_windows_metadata_handle(config_path, is_directory=False)
            try:
                config_stat = os.fstat(config_fd)
                if (config_stat.st_dev, config_stat.st_ino) != expected_file_identity:
                    _reject(
                        "config_yaml_windows_identity_invalid",
                        "the private config file identity changed",
                    )
                _require_private_config_single_link(config_stat.st_nlink)
                _windows_acl_for_handle(_windows_os_handle(config_fd))
                final_config_lstat = os.lstat(str(config_path))
                if _is_link_or_reparse(final_config_lstat) or (
                    config_stat.st_dev,
                    config_stat.st_ino,
                ) != (final_config_lstat.st_dev, final_config_lstat.st_ino):
                    _reject(
                        "config_yaml_windows_identity_invalid",
                        "the private config file identity changed",
                    )
                _require_private_config_single_link(final_config_lstat.st_nlink)
            finally:
                os.close(config_fd)
    except CredentialResolutionError:
        raise
    except Exception:
        _reject(
            "config_yaml_windows_acl_unavailable",
            "Windows could not verify the private config ACL",
        )


def _require_private_config_single_link(link_count: Any) -> None:
    if type(link_count) is not int or link_count != 1:
        _reject(
            "config_yaml_identity_invalid",
            "config.yaml must have exactly one filesystem link",
        )


def _require_posix_private_config_acl(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> None:
    """Recheck private config ownership, modes and identity without reading bytes."""

    registration = effective.registration
    directory = registration.runtime_dir
    config_path = effective.config.source_path
    expected_file_identity = effective.config._source_file_identity
    if (
        expected_file_identity is None
        or config_path.parent != directory
        or config_path.name != "config.yaml"
    ):
        _reject(
            "config_yaml_identity_unavailable",
            "the private config file identity could not be verified",
        )

    no_follow = getattr(os, "O_NOFOLLOW", None)
    if _platform_name() != "posix" or type(no_follow) is not int or no_follow == 0:
        _reject(
            "config_yaml_posix_security_unavailable",
            "config_yaml requires non-following POSIX descriptor checks",
        )

    try:
        with registry.verified_runtime_directory(registration) as directory_fd:
            if directory_fd is None:
                _reject(
                    "config_yaml_posix_security_unavailable",
                    "config_yaml requires a verified runtime directory descriptor",
                )
            directory_stat = os.fstat(directory_fd)
            try:
                effective_uid = os.geteuid()
            except (AttributeError, OSError):
                _reject(
                    "config_yaml_posix_security_unavailable",
                    "config_yaml requires verified POSIX ownership checks",
                )
            directory_mode = stat.S_IMODE(directory_stat.st_mode)
            if (
                not registration.directory_identity.matches(directory_stat)
                or not stat.S_ISDIR(directory_stat.st_mode)
                or directory_stat.st_uid != effective_uid
                or directory_mode & ~0o700
                or directory_mode & 0o500 != 0o500
            ):
                _reject(
                    "config_yaml_directory_unsafe",
                    "the private runtime directory is not owner-only",
                )

            try:
                path_stat = os.lstat("config.yaml", dir_fd=directory_fd)
            except OSError:
                _reject(
                    "config_yaml_identity_invalid",
                    "the private config file is unavailable",
                )
            if _is_link_or_reparse(path_stat) or not stat.S_ISREG(path_stat.st_mode):
                _reject(
                    "config_yaml_identity_invalid",
                    "the private config file must be a regular non-link file",
                )
            descriptor = os.open(
                "config.yaml",
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | no_follow,
                dir_fd=directory_fd,
            )
            try:
                config_stat = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(config_stat.st_mode)
                    or (config_stat.st_dev, config_stat.st_ino) != expected_file_identity
                    or (path_stat.st_dev, path_stat.st_ino)
                    != (config_stat.st_dev, config_stat.st_ino)
                ):
                    _reject(
                        "config_yaml_identity_invalid",
                        "the private config file identity changed",
                    )
                _require_private_config_single_link(config_stat.st_nlink)
                _require_posix_private_config_stat(config_stat, effective_uid)
                final_stat = os.lstat("config.yaml", dir_fd=directory_fd)
                final_fd_stat = os.fstat(descriptor)
                if (
                    _is_link_or_reparse(final_stat)
                    or (final_stat.st_dev, final_stat.st_ino) != expected_file_identity
                    or (final_fd_stat.st_dev, final_fd_stat.st_ino) != expected_file_identity
                ):
                    _reject(
                        "config_yaml_identity_invalid",
                        "the private config file identity changed",
                    )
                _require_private_config_single_link(final_fd_stat.st_nlink)
                _require_private_config_single_link(final_stat.st_nlink)
                _require_posix_private_config_stat(final_fd_stat, effective_uid)
            finally:
                os.close(descriptor)
    except CredentialResolutionError:
        raise
    except Exception:
        _reject(
            "config_yaml_posix_security_unavailable",
            "POSIX could not verify the private config permissions",
        )


def _require_posix_private_config_stat(result: os.stat_result, effective_uid: int) -> None:
    file_mode = stat.S_IMODE(result.st_mode)
    if result.st_uid != effective_uid or file_mode & ~0o600 or file_mode & stat.S_IRUSR == 0:
        _reject(
            "config_yaml_file_unsafe",
            "config.yaml must be readable only by its owner",
        )


def _windows_os_handle(descriptor: int) -> int:
    try:
        import msvcrt

        return int(msvcrt.get_osfhandle(descriptor))
    except Exception:
        _reject(
            "config_yaml_windows_acl_unavailable",
            "Windows could not verify the private config ACL",
        )
    raise AssertionError("unreachable")


def _load_windows_credential_api() -> _WindowsCredentialApi:
    """Load just the documented Credential Manager functions, lazily."""

    if _platform_name() != "nt":
        _reject(
            "os_secret_store_platform_unsupported",
            "the configured OS secret store is unavailable on this platform",
        )
    try:
        library = ctypes.WinDLL("Advapi32", use_last_error=True)
        cred_read = library.CredReadW
        cred_read.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_WindowsCredentialW)),
        )
        cred_read.restype = wintypes.BOOL
        cred_free = library.CredFree
        cred_free.argtypes = (ctypes.c_void_p,)
        cred_free.restype = None
    except Exception:
        # A ctypes loader failure may embed system details.  Keep the public
        # result deterministic and avoid propagating a platform message.
        _reject(
            "os_secret_store_api_unavailable",
            "the required Windows Credential Manager API is unavailable",
        )
    return _WindowsCredentialApi(cred_read=cred_read, cred_free=cred_free)


def _read_windows_credential_blob(
    target: str, api: Optional[_WindowsCredentialApi] = None
) -> bytes:
    """Copy an exact Generic credential blob and always free the OS allocation.

    ``api`` is a private test seam.  Production calls always use the lazily
    loaded Win32 functions; no test or normal path enumerates credentials.
    """

    if api is None:
        api = _load_windows_credential_api()
    if type(api) is not _WindowsCredentialApi:
        _reject("os_secret_store_api_unavailable", "the OS secret-store API is unavailable")
    credential_pointer = ctypes.POINTER(_WindowsCredentialW)()
    allocation_received = False
    result: Optional[bytes] = None
    error: Optional[CredentialResolutionError] = None
    try:
        success = api.cred_read(target, api.generic_type, 0, ctypes.byref(credential_pointer))
        allocation_received = bool(credential_pointer)
        if not success:
            _reject(
                "os_secret_store_credential_missing",
                "the code-owned OS secret-store credential could not be read",
            )
        if not allocation_received:
            _reject(
                "os_secret_store_credential_invalid",
                "the OS secret-store credential returned no readable payload",
            )
        credential = credential_pointer.contents
        if credential.Type != api.generic_type or credential.TargetName != target:
            _reject(
                "os_secret_store_credential_scope_mismatch",
                "the OS secret-store credential does not match the code-owned scope",
            )
        if (
            credential.Flags != 0
            or credential.Comment
            or credential.AttributeCount != 0
            or credential.UserName
            or credential.TargetAlias
        ):
            _reject(
                "os_secret_store_credential_metadata_invalid",
                "the OS secret-store credential has unsupported metadata",
            )
        size = int(credential.CredentialBlobSize)
        if size <= 0 or size > MAX_OS_SECRET_STORE_BLOB_BYTES or not credential.CredentialBlob:
            _reject(
                "os_secret_store_blob_invalid",
                "the OS secret-store credential has an invalid bounded payload",
            )
        result = ctypes.string_at(credential.CredentialBlob, size)
    except CredentialResolutionError as caught:
        error = caught
    except Exception:
        # A foreign ctypes callback or a mocked WinAPI can surface arbitrary
        # exception text.  It must never carry a Credential Manager payload
        # into a caller-visible error.
        error = CredentialResolutionError(
            "os_secret_store_credential_invalid",
            "the OS secret-store credential could not be read safely",
        )
    finally:
        # A malformed/mock API can raise after assigning the output pointer.
        # Test the pointer again so every allocation that reached Python gets
        # released, including failure paths before ``allocation_received`` was
        # updated.
        if allocation_received or bool(credential_pointer):
            try:
                api.cred_free(ctypes.cast(credential_pointer, ctypes.c_void_p))
            except Exception:
                if error is None:
                    error = CredentialResolutionError(
                        "os_secret_store_free_failed",
                        "the OS secret-store credential could not be released safely",
                    )
    if error is not None:
        raise error
    if result is None:
        _reject(
            "os_secret_store_credential_invalid",
            "the OS secret-store credential returned no readable payload",
        )
    return result


class _DuplicateJsonFieldError(ValueError):
    pass


def _load_secret_store_json(raw: bytes) -> Any:
    if type(raw) is not bytes or not raw or len(raw) > MAX_OS_SECRET_STORE_BLOB_BYTES:
        _reject(
            "os_secret_store_blob_invalid", "the OS secret-store credential has an invalid payload"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject("os_secret_store_blob_invalid", "the OS secret-store payload must be UTF-8 JSON")

    def object_pairs(pairs: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonFieldError()
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        del value
        raise ValueError("JSON constants are not allowed")

    try:
        return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except Exception:
        # JSON parser diagnostics can quote source text, which may contain a
        # credential.  Collapse every parser failure to one redacted reason.
        _reject("os_secret_store_blob_invalid", "the OS secret-store payload is not supported JSON")
    raise AssertionError("unreachable")


def _load_runtime_secrets_yaml(text: str) -> Any:
    try:
        return _load_strict_yaml(text)
    except RuntimeConfigError:
        _reject(
            "runtime_secrets_invalid_yaml", "secrets.yaml is not a supported strict YAML document"
        )
    raise AssertionError("unreachable")


def _validate_credential_value(value: Any) -> str:
    if type(value) is not str or not value or "\x00" in value:
        _reject("credential_value_invalid", "a required credential value is missing or invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _reject("credential_value_invalid", "a required credential value is missing or invalid")
    if len(encoded) > MAX_CREDENTIAL_VALUE_BYTES:
        _reject("credential_value_too_large", "a credential value exceeds the supported size")
    return value


def _credential_document_values(document: Any, scope: RuntimeCredentialScope) -> Mapping[str, str]:
    """Accept only ``{credentials: {<exact code-owned keys>: string}}``."""

    if type(document) is not dict:
        _reject("credential_document_invalid", "credential payload must be a mapping")
    if set(document) != {"credentials"}:
        _reject(
            "credential_document_controls_forbidden",
            "credential payload may contain only the credentials mapping",
        )
    credentials = document.get("credentials")
    if type(credentials) is not dict:
        _reject("credential_document_invalid", "credentials must be a mapping")
    keys = tuple(credentials.keys())
    if any(type(key) is not str for key in keys):
        _reject("credential_document_invalid", "credential field names must be strings")
    if any(key in _CONTROL_CREDENTIAL_KEYS for key in keys):
        _reject(
            "credential_document_controls_forbidden",
            "credential payload may not contain runtime control fields",
        )
    if set(keys) != set(scope.credential_keys) or len(keys) != len(scope.credential_keys):
        _reject(
            "credential_schema_mismatch",
            "credential payload does not match the code-owned authentication schema",
        )
    result: Dict[str, str] = {}
    for key in scope.credential_keys:
        result[key] = _validate_credential_value(credentials[key])
    return MappingProxyType(result)


@dataclass(frozen=True)
class ResolvedRuntimeCredentials:
    """Private credential material plus explicit non-authority status fields.

    Raw values are held in an internal attribute, never appear in a repr or
    public projection, and are not process-isolated from trusted in-process
    factory code.  A provider factory must call
    :func:`require_resolved_runtime_credentials_seal` before using
    :meth:`require_credential`; resolving a value does not prove account
    identity or grant preflight, connection, or execution authority.
    """

    scope: RuntimeCredentialScope
    source: str
    _values: Mapping[str, str] = field(repr=False, compare=False)
    credentials_resolved: bool = True
    provider_connected: bool = False
    account_identity_verified: bool = False
    preflight_authorized: bool = False
    execution_authorized: bool = False
    external_writes_authorized: bool = False

    def __post_init__(self) -> None:
        snapshot = _snapshot_scope(self.scope)
        if self.source not in (CONFIG_YAML_REF, RUNTIME_SECRETS_REF, "os_secret_store"):
            raise ValueError("credential source is unsupported")
        if type(self._values) not in (dict, MappingProxyType):
            raise ValueError("credential values must be a private mapping")
        values = _credential_document_values({"credentials": dict(self._values)}, snapshot)
        object.__setattr__(self, "scope", snapshot)
        object.__setattr__(self, "_values", values)
        if (
            self.credentials_resolved is not True
            or self.provider_connected is not False
            or self.account_identity_verified is not False
            or self.preflight_authorized is not False
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
        ):
            raise ValueError("credential resolution cannot grant provider or execution authority")

    def __bool__(self) -> bool:
        raise TypeError(
            "ResolvedRuntimeCredentials is not an account, preflight, or execution authorization; "
            "do not use it as a boolean"
        )

    def __repr__(self) -> str:
        return (
            "ResolvedRuntimeCredentials(scope={!r}, source={!r}, credentials_resolved=True, "
            "provider_connected=False, account_identity_verified=False, preflight_authorized=False, "
            "execution_authorized=False, external_writes_authorized=False)"
        ).format(self.scope, self.source)

    @property
    def credential_names(self) -> Tuple[str, ...]:
        """Return only the reviewed schema names, never authentication values."""

        return self.scope.credential_keys

    def require_credential(self, key: str) -> str:
        """Return one value to a trusted factory after seal verification."""

        if type(key) is not str or key not in self.scope.credential_keys:
            _reject("credential_name_not_available", "the requested credential is not available")
        try:
            return self._values[key]
        except (KeyError, TypeError):
            _reject(
                "credential_resolution_invalid", "resolved credential material is no longer valid"
            )
        raise AssertionError("unreachable")

    def as_public_dict(self) -> Dict[str, Any]:
        """Return a safe state projection that cannot be treated as admission."""

        return {
            "runtime_id": self.scope.runtime_id,
            "strategy_id": self.scope.strategy_id,
            "provider": self.scope.provider,
            "provider_environment": self.scope.provider_environment,
            "policy_environment": self.scope.policy_environment,
            "mode": self.scope.mode,
            "preset": self.scope.preset,
            "account_access": self.scope.account_access,
            "credential_count": len(self.scope.credential_keys),
            "credentials_resolved": self.credentials_resolved,
            "provider_connected": self.provider_connected,
            "account_identity_verified": self.account_identity_verified,
            "preflight_authorized": self.preflight_authorized,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
        }


@dataclass(frozen=True)
class _ResolvedCredentialSeal:
    registry: RuntimeRegistry
    effective: EffectiveRuntimeConfig
    scope_facts: Tuple[Any, ...]
    source: str
    values: Mapping[str, str]


_RESOLVED_CREDENTIAL_SEALS: Dict[int, Tuple[Any, _ResolvedCredentialSeal]] = {}


def _seal_resolved_credentials(
    resolved: ResolvedRuntimeCredentials,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
) -> ResolvedRuntimeCredentials:
    identifier = id(resolved)

    def discard(reference: Any) -> None:
        current = _RESOLVED_CREDENTIAL_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _RESOLVED_CREDENTIAL_SEALS.pop(identifier, None)

    reference = weakref.ref(resolved, discard)
    _RESOLVED_CREDENTIAL_SEALS[identifier] = (
        reference,
        _ResolvedCredentialSeal(
            registry=registry,
            effective=effective,
            scope_facts=_scope_facts(resolved.scope),
            source=resolved.source,
            values=resolved._values,
        ),
    )
    return resolved


def require_resolved_runtime_credentials_seal(
    resolved: ResolvedRuntimeCredentials,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    scope: RuntimeCredentialScope,
) -> None:
    """Reject forged, cross-route, or mutated credential-resolution results.

    This is intentionally a separate factory-facing gate.  It verifies the
    sealed effective config again, then confirms that the resolution came from
    this module for the exact code-owned credential scope supplied to the
    future provider factory.
    """

    # Repeat the complete route binding, not just the effective-config object
    # seal.  Frozen dataclasses can still be mutated through hostile Python
    # code, and a registration digest change after resolution must invalidate
    # every later credential access.
    expected_scope = _require_matching_scope(effective, registry, scope)
    if type(resolved) is not ResolvedRuntimeCredentials:
        _reject(
            "credential_resolution_provenance_invalid",
            "credential resolution was not produced by the trusted resolver",
        )
    entry = _RESOLVED_CREDENTIAL_SEALS.get(id(resolved))
    if entry is None or entry[0]() is not resolved:
        _reject(
            "credential_resolution_provenance_invalid",
            "credential resolution was not produced by the trusted resolver",
        )
    seal = entry[1]
    if (
        seal.registry is not registry
        or seal.effective is not effective
        or seal.scope_facts != _scope_facts(expected_scope)
        or _scope_facts(resolved.scope) != seal.scope_facts
        or resolved.source != seal.source
        or resolved._values is not seal.values
        or resolved.credentials_resolved is not True
        or resolved.provider_connected is not False
        or resolved.account_identity_verified is not False
        or resolved.preflight_authorized is not False
        or resolved.execution_authorized is not False
        or resolved.external_writes_authorized is not False
    ):
        _reject(
            "credential_resolution_provenance_invalid",
            "credential resolution no longer matches the sealed runtime scope",
        )


def resolve_runtime_credentials(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    scope: RuntimeCredentialScope,
) -> ResolvedRuntimeCredentials:
    """Resolve one exact credential schema without provider activity.

    A successful return only establishes that a local credential source matched
    the caller's code-owned scope.  It is neither a connection, a provider
    account check, a receipt check, nor an execution permit.
    """

    matched_scope = _require_matching_scope(effective, registry, scope)
    if matched_scope.secrets_ref == CONFIG_YAML_REF:
        # ``_require_matching_scope`` has already revalidated registry,
        # effective-config, and loader provenance seals.  Read the sealed
        # private object directly; never reopen config.yaml or consult env.
        private = effective.config.ctp_simnow
        if (
            matched_scope.provider != "ctp"
            or matched_scope.policy_environment != "sandbox"
            or matched_scope.mode != "simulation"
            or matched_scope.preset != "sandbox"
            or type(private) is not CtpSimNowPrivateConfig
        ):
            _reject(
                "credential_scope_secret_ref_mismatch",
                "config_yaml credentials require a sealed CTP sandbox configuration",
            )
        if _platform_name() == "nt":
            _require_windows_private_config_acl(effective, registry)
        elif _platform_name() == "posix":
            _require_posix_private_config_acl(effective, registry)
        else:
            _reject(
                "config_yaml_platform_unsupported",
                "config_yaml credentials require verified local file permissions",
            )
        document = {
            "credentials": {
                key: getattr(private, key) for key in CTP_AUTHENTICATION_CREDENTIAL_KEYS
            }
        }
        source = CONFIG_YAML_REF
    elif matched_scope.secrets_ref == RUNTIME_SECRETS_REF:
        with registry.verified_runtime_directory(effective.registration) as directory_fd:
            text = _read_runtime_secrets_text(effective.registration.runtime_dir, directory_fd)
        document = _load_runtime_secrets_yaml(text)
        source = RUNTIME_SECRETS_REF
    else:
        match = _OS_SECRET_REF_RE.fullmatch(matched_scope.secrets_ref)
        if match is None:
            _reject(
                "credential_scope_secret_ref_mismatch",
                "credential scope has an invalid secret source",
            )
        if _platform_name() != "nt":
            _reject(
                "os_secret_store_platform_unsupported",
                "the configured OS secret store is unavailable on this platform",
            )
        blob = _read_windows_credential_blob(match.group(1))
        document = _load_secret_store_json(blob)
        source = "os_secret_store"
    values = _credential_document_values(document, matched_scope)
    return _seal_resolved_credentials(
        ResolvedRuntimeCredentials(scope=matched_scope, source=source, _values=values),
        effective,
        registry,
    )


__all__ = [
    "CTP_AUTHENTICATION_CREDENTIAL_KEYS",
    "CONFIG_YAML_REF",
    "CredentialResolutionError",
    "MAX_OS_SECRET_STORE_BLOB_BYTES",
    "MAX_RUNTIME_SECRETS_BYTES",
    "OS_SECRET_STORE_PREFIX",
    "RUNTIME_SECRETS_FILENAME",
    "RUNTIME_SECRETS_REF",
    "ResolvedRuntimeCredentials",
    "RuntimeCredentialScope",
    "require_resolved_runtime_credentials_seal",
    "resolve_runtime_credentials",
]
