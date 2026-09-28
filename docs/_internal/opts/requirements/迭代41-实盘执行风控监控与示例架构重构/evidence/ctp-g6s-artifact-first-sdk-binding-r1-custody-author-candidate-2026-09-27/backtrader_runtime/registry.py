"""Trusted runtime-directory bindings and effective configuration resolution.

The registry is intentionally data-oriented.  It validates an immutable
configuration and returns capability descriptors; optional execution, risk,
monitoring, gateway, and provider modules remain unimported.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Generator, Iterable, Mapping, Optional, Tuple, Union

from .config import (
    RuntimeConfig,
    _parse_verified_runtime_config_text,
    _read_config_text,
    load_runtime_config,
    require_loaded_runtime_config_seal,
    write_bootstrap_config,
)
from .errors import (
    CONFIG_EXISTS,
    ENVIRONMENT_MISMATCH,
    MODE_PRESET_MISMATCH,
    PRESET_POLICY_VIOLATION,
    RuntimeConfigError,
)
from .policy import MANAGED_WRITE_CAPABILITIES, PresetPolicy, get_preset_policy


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNNER_MODULE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
_RUNNER_ENTRYPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CAPABILITY_MODULE_RE = re.compile(r"^bt_api(?:_[A-Za-z0-9]+)+$")
_PROFILE_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _ctp_binding_snapshot(binding: Any) -> Tuple[Any, ...]:
    """Capture every reviewed binding field, including non-public values."""

    return (type(binding),) + tuple(
        (item.name, getattr(binding, item.name)) for item in fields(binding)
    )


def _canonical_dir(path: Union[str, os.PathLike]) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "strategy runtime directory is not usable",
            field_path="strategy_dir",
            reason="invalid_runtime_directory",
        ) from None


def _directory_key(path: Union[str, os.PathLike]) -> str:
    return os.path.normcase(str(_canonical_dir(path)))


def _lexical_directory_key(path: Union[str, os.PathLike]) -> str:
    """Normalise a path spelling without following a later replacement link."""

    try:
        expanded = Path(path).expanduser()
        return os.path.normcase(os.path.normpath(os.path.abspath(str(expanded))))
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "strategy runtime directory is not usable",
            field_path="strategy_dir",
            reason="invalid_runtime_directory",
        ) from None


def _is_link_or_reparse(stat_result: os.stat_result) -> bool:
    """Return whether a directory entry is a link on this platform.

    ``stat.S_ISLNK`` covers POSIX links.  Windows junctions can instead be
    directory reparse points, so reject those too when Python exposes the
    file-attribute bit.  A reviewed runtime directory must be a concrete
    directory owned by the registration, not a redirectable path.
    """

    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return stat.S_ISLNK(stat_result.st_mode) or bool(attributes & reparse_point)


@dataclass(frozen=True)
class RuntimeDirectoryIdentity:
    """The lstat identity captured for a reviewed runtime directory."""

    device: int
    inode: int
    mode: int

    @classmethod
    def capture(cls, path: Path) -> Optional["RuntimeDirectoryIdentity"]:
        """Capture a concrete directory identity without following its leaf.

        A missing directory remains representable so the bootstrap policy can
        still reject a write-capable preset before reporting availability.  It
        can never subsequently become an executable trusted directory because
        no reviewed identity was captured for it.
        """

        try:
            result = os.lstat(str(path))
        except FileNotFoundError:
            return None
        except OSError:
            raise ValueError("registered runtime directory cannot be inspected") from None
        if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
            raise ValueError("registered runtime directory must be a non-link directory")
        return cls(device=result.st_dev, inode=result.st_ino, mode=result.st_mode)

    def matches(self, result: os.stat_result) -> bool:
        return (
            not _is_link_or_reparse(result)
            and stat.S_ISDIR(result.st_mode)
            and (result.st_dev, result.st_ino, result.st_mode)
            == (self.device, self.inode, self.mode)
        )


@dataclass(frozen=True)
class UnavailableModeProfile:
    """A code-owned mode/preset pair that is recognized but cannot run."""

    mode: str
    preset: str
    reason: str

    def __post_init__(self) -> None:
        policy = get_preset_policy(self.preset) if isinstance(self.preset, str) else None
        if not isinstance(self.mode, str) or policy is None or policy.mode != self.mode:
            raise ValueError("unavailable mode profile must name a known mode/preset pair")
        if not isinstance(self.reason, str) or not _PROFILE_REASON_RE.fullmatch(self.reason):
            raise ValueError("unavailable mode profile reason must be a stable identifier")


@dataclass(frozen=True)
class RuntimeProfile:
    """One exact mode/preset contract carried by a registered runtime.

    Profile fields are deliberately complete and are never inherited from the
    enclosing runtime's legacy fields.  The enclosing registration remains the
    owner of directory and strategy identity; this value owns only the policy
    and dispatch facts for one exact mode/preset pair.
    """

    mode: str
    preset: str
    allowed_parameter_keys: Tuple[str, ...]
    allowed_secrets_refs: Tuple[str, ...]
    available_capabilities: Tuple[str, ...]
    approval_receipt_digest: Optional[str]
    runner_module: Optional[str]
    runner_entrypoint: str
    capability_modules: Tuple[str, ...]
    offline_managed_execution: bool
    sandbox_write_policy: str

    def __post_init__(self) -> None:
        policy = get_preset_policy(self.preset) if isinstance(self.preset, str) else None
        if not isinstance(self.mode, str) or policy is None or policy.mode != self.mode:
            raise ValueError("runtime profile must name a known mode/preset pair")
        for name in (
            "allowed_parameter_keys",
            "allowed_secrets_refs",
            "available_capabilities",
            "capability_modules",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if any(not isinstance(key, str) or not key for key in self.allowed_parameter_keys):
            raise ValueError("profile parameter keys must be non-empty strings")
        if len(set(self.allowed_parameter_keys)) != len(self.allowed_parameter_keys):
            raise ValueError("profile parameter keys must not contain duplicates")
        if not self.allowed_secrets_refs or any(
            not isinstance(value, str) or not value for value in self.allowed_secrets_refs
        ):
            raise ValueError("profile secret references must be non-empty strings")
        if len(set(self.allowed_secrets_refs)) != len(self.allowed_secrets_refs):
            raise ValueError("profile secret references must not contain duplicates")
        if any(not isinstance(value, str) or not value for value in self.available_capabilities):
            raise ValueError("profile capabilities must be non-empty strings")
        if len(set(self.available_capabilities)) != len(self.available_capabilities):
            raise ValueError("profile capabilities must not contain duplicates")
        if type(self.offline_managed_execution) is not bool:
            raise ValueError("profile offline_managed_execution must be a bool")
        if self.sandbox_write_policy not in ("deny", "receipt_required"):
            raise ValueError("profile sandbox_write_policy must be deny or receipt_required")
        if self.sandbox_write_policy == "receipt_required" and self.preset != "sandbox":
            raise ValueError("receipt-required profile policy needs the sandbox preset")
        if self.approval_receipt_digest is not None and not _DIGEST_RE.fullmatch(
            self.approval_receipt_digest
        ):
            raise ValueError("profile approval receipt must be a lower-case SHA-256 digest")
        if self.runner_module is not None and (
            not isinstance(self.runner_module, str)
            or not _RUNNER_MODULE_RE.fullmatch(self.runner_module)
        ):
            raise ValueError("profile runner_module must be a dotted code-owned module name")
        if not isinstance(self.runner_entrypoint, str) or not _RUNNER_ENTRYPOINT_RE.fullmatch(
            self.runner_entrypoint
        ):
            raise ValueError("profile runner_entrypoint must be a Python identifier")
        if self.runner_module is None and self.runner_entrypoint != "run_runtime":
            raise ValueError("profile runner_entrypoint requires runner_module")
        if len(set(self.capability_modules)) != len(self.capability_modules):
            raise ValueError("profile capability_modules must not contain duplicates")
        if any(
            not isinstance(module, str) or not _CAPABILITY_MODULE_RE.fullmatch(module)
            for module in self.capability_modules
        ):
            raise ValueError("profile capability_modules must be top-level bt_api package names")
        _validate_profile_offline_managed_shape(self)

    @property
    def digest(self) -> str:
        canonical = {
            "allowed_parameter_keys": self.allowed_parameter_keys,
            "allowed_secrets_refs": self.allowed_secrets_refs,
            "approval_receipt_digest": self.approval_receipt_digest,
            "available_capabilities": self.available_capabilities,
            "capability_modules": self.capability_modules,
            "mode": self.mode,
            "offline_managed_execution": self.offline_managed_execution,
            "preset": self.preset,
            "runner_entrypoint": self.runner_entrypoint,
            "runner_module": self.runner_module,
            "sandbox_write_policy": self.sandbox_write_policy,
        }
        encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegisteredRuntime:
    """A code-owned, exact binding for one runtime directory.

    ``allowed_presets`` and ``allowed_parameter_keys`` are an allow-list, not
    suggestions.  They must be supplied by reviewed code or a signed operator
    registry, never from ``config.yaml`` or a command-line flag.
    """

    runtime_dir: Path
    strategy_id: str
    allowed_presets: Tuple[str, ...]
    allowed_parameter_keys: Tuple[str, ...] = ()
    allowed_secrets_refs: Tuple[str, ...] = ("none",)
    available_capabilities: Tuple[str, ...] = ()
    offline_managed_execution: bool = False
    sandbox_write_policy: str = "deny"
    approval_receipt_digest: Optional[str] = None
    runtime_id: Optional[str] = None
    runner_module: Optional[str] = None
    runner_entrypoint: str = "run_runtime"
    capability_modules: Tuple[str, ...] = ()
    unavailable_mode_profiles: Tuple[UnavailableModeProfile, ...] = ()
    bootstrap_parameters: Tuple[Tuple[str, Any], ...] = ()
    # Appended after the original public fields so positional callers that
    # supplied bootstrap_parameters retain their constructor semantics.
    profiles: Tuple[RuntimeProfile, ...] = ()
    directory_identity: Optional[RuntimeDirectoryIdentity] = field(
        init=False, repr=False, compare=False
    )
    runtime_dir_lookup_key: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        supplied_dir = Path(self.runtime_dir).expanduser()
        # Do not permit a code registration to silently canonicalise a leaf
        # symlink or junction.  The canonical path below is retained for
        # deterministic lookup, while the identity seals the actual directory
        # selected at registry construction time.
        captured_identity = RuntimeDirectoryIdentity.capture(supplied_dir)
        resolved_dir = _canonical_dir(supplied_dir)
        object.__setattr__(self, "runtime_dir", resolved_dir)
        object.__setattr__(self, "directory_identity", captured_identity)
        object.__setattr__(self, "runtime_dir_lookup_key", _lexical_directory_key(supplied_dir))
        object.__setattr__(self, "allowed_presets", tuple(self.allowed_presets))
        object.__setattr__(self, "allowed_parameter_keys", tuple(self.allowed_parameter_keys))
        normalized_bootstrap_parameters = []
        bootstrap_parameter_keys = set()
        for item in self.bootstrap_parameters:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("bootstrap_parameters entries must be key/value pairs")
            key, value = item
            if (
                not isinstance(key, str)
                or key not in self.allowed_parameter_keys
                or key in bootstrap_parameter_keys
            ):
                raise ValueError("bootstrap_parameters must use unique allowed parameter keys")
            bootstrap_parameter_keys.add(key)
            if isinstance(value, (tuple, list)):
                normalized_value = tuple(value)
                if any(type(part) not in (str, int, bool) for part in normalized_value):
                    raise ValueError("bootstrap parameter sequences must contain scalar values")
            elif type(value) in (str, int, bool):
                normalized_value = value
            else:
                raise ValueError("bootstrap parameter values must be simple scalar sequences")
            normalized_bootstrap_parameters.append((key, normalized_value))
        object.__setattr__(self, "bootstrap_parameters", tuple(normalized_bootstrap_parameters))
        object.__setattr__(self, "allowed_secrets_refs", tuple(self.allowed_secrets_refs))
        object.__setattr__(self, "available_capabilities", tuple(self.available_capabilities))
        object.__setattr__(self, "capability_modules", tuple(self.capability_modules))
        object.__setattr__(self, "unavailable_mode_profiles", tuple(self.unavailable_mode_profiles))
        object.__setattr__(self, "profiles", tuple(self.profiles))

        if not self.strategy_id:
            raise ValueError("registered runtime strategy_id must not be empty")
        if not self.allowed_presets and not self.profiles:
            raise ValueError("registered runtime must allow at least one preset or profile")
        if len(set(self.allowed_presets)) != len(self.allowed_presets):
            raise ValueError("registered runtime has duplicate allowed presets")
        if len(set(self.allowed_parameter_keys)) != len(self.allowed_parameter_keys):
            raise ValueError("registered runtime has duplicate allowed parameter keys")
        if len(set(self.allowed_secrets_refs)) != len(self.allowed_secrets_refs):
            raise ValueError("registered runtime has duplicate allowed secret references")
        if any(get_preset_policy(name) is None for name in self.allowed_presets):
            raise ValueError("registered runtime references an unknown preset")
        _validate_unavailable_mode_profiles_shape(self)
        _validate_runtime_profiles_shape(self)
        if self.sandbox_write_policy not in ("deny", "receipt_required"):
            raise ValueError("sandbox_write_policy must be deny or receipt_required")
        if (
            self.sandbox_write_policy == "receipt_required"
            and "sandbox" not in self.allowed_presets
        ):
            raise ValueError("receipt-required sandbox policy needs the sandbox preset")
        if self.approval_receipt_digest is not None and not _DIGEST_RE.fullmatch(
            self.approval_receipt_digest
        ):
            raise ValueError("approval_receipt_digest must be a lower-case SHA-256 digest")
        if self.runtime_id is None:
            object.__setattr__(self, "runtime_id", self.strategy_id)
        if self.runner_module is not None and (
            not isinstance(self.runner_module, str)
            or not _RUNNER_MODULE_RE.fullmatch(self.runner_module)
        ):
            raise ValueError("runner_module must be a dotted code-owned module name")
        if not isinstance(self.runner_entrypoint, str) or not _RUNNER_ENTRYPOINT_RE.fullmatch(
            self.runner_entrypoint
        ):
            raise ValueError("runner_entrypoint must be a Python identifier")
        if self.runner_module is None and self.runner_entrypoint != "run_runtime":
            raise ValueError("runner_entrypoint requires runner_module")
        if len(set(self.capability_modules)) != len(self.capability_modules):
            raise ValueError("capability_modules must not contain duplicates")
        if any(
            not isinstance(module, str) or not _CAPABILITY_MODULE_RE.fullmatch(module)
            for module in self.capability_modules
        ):
            raise ValueError("capability_modules must contain top-level bt_api package names")
        _validate_offline_managed_registration_shape(self)
        if self.profiles and (
            self.allowed_presets
            or self.allowed_parameter_keys
            or self.allowed_secrets_refs != ("none",)
            or self.available_capabilities
            or self.offline_managed_execution
            or self.sandbox_write_policy != "deny"
            or self.approval_receipt_digest is not None
            or self.runner_module is not None
            or self.runner_entrypoint != "run_runtime"
            or self.capability_modules
        ):
            raise ValueError("profile-scoped runtime legacy policy fields must remain inert")

    @property
    def digest(self) -> str:
        """Return a safe digest of the reviewed registration data."""

        canonical = {
            "allowed_parameter_keys": self.allowed_parameter_keys,
            "bootstrap_parameters": self.bootstrap_parameters,
            "allowed_presets": self.allowed_presets,
            "allowed_secrets_refs": self.allowed_secrets_refs,
            "available_capabilities": self.available_capabilities,
            "capability_modules": self.capability_modules,
            "offline_managed_execution": self.offline_managed_execution,
            "approval_receipt_digest": self.approval_receipt_digest,
            "runtime_id": self.runtime_id,
            "runner_entrypoint": self.runner_entrypoint,
            "runner_module": self.runner_module,
            "sandbox_write_policy": self.sandbox_write_policy,
            "strategy_id": self.strategy_id,
            "unavailable_mode_profiles": tuple(
                (profile.mode, profile.preset, profile.reason)
                for profile in self.unavailable_mode_profiles
            ),
        }
        if self.profiles:
            canonical["profiles"] = tuple(profile.digest for profile in self.profiles)
        encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def profile_for(self, mode: str, preset: str) -> Optional[RuntimeProfile]:
        """Return the exact registered profile, if this runtime is profile-scoped."""

        return next(
            (
                profile
                for profile in self.profiles
                if (profile.mode, profile.preset) == (mode, preset)
            ),
            None,
        )


def _validate_unavailable_mode_profiles_shape(registration: RegisteredRuntime) -> None:
    """Keep unavailable profiles exact, disjoint from active presets, and inert."""

    profiles = registration.unavailable_mode_profiles
    if any(type(profile) is not UnavailableModeProfile for profile in profiles):
        raise ValueError("unavailable_mode_profiles must contain exact profile declarations")
    pairs = tuple((profile.mode, profile.preset) for profile in profiles)
    if len(set(pairs)) != len(pairs):
        raise ValueError("registered runtime has duplicate unavailable mode profiles")
    if any(profile.preset in registration.allowed_presets for profile in profiles):
        raise ValueError("an unavailable mode profile cannot also be an allowed preset")
    # Revalidate each declaration at registry/resolution boundaries because
    # frozen instances can still be altered with object.__setattr__.
    for profile in profiles:
        UnavailableModeProfile.__post_init__(profile)


def _validate_profile_offline_managed_shape(profile: RuntimeProfile) -> None:
    if not profile.offline_managed_execution:
        return
    if (profile.mode, profile.preset) != ("simulation", "replay"):
        raise ValueError("profile offline managed execution is restricted to simulation/replay")
    if profile.allowed_secrets_refs != ("none",):
        raise ValueError("profile offline managed execution must not accept provider secrets")
    if profile.available_capabilities != MANAGED_WRITE_CAPABILITIES:
        raise ValueError("profile offline managed execution requires execution, risk, and monitor")
    if profile.sandbox_write_policy != "deny":
        raise ValueError("profile offline managed execution must deny sandbox provider writes")
    if profile.approval_receipt_digest is not None:
        raise ValueError("profile offline managed execution must not carry an approval receipt")


def _validate_runtime_profiles_shape(registration: RegisteredRuntime) -> None:
    profiles = registration.profiles
    if any(type(profile) is not RuntimeProfile for profile in profiles):
        raise ValueError("profiles must contain exact RuntimeProfile declarations")
    pairs = tuple((profile.mode, profile.preset) for profile in profiles)
    if len(set(pairs)) != len(pairs):
        raise ValueError("registered runtime has duplicate profiles")
    unavailable = {
        (profile.mode, profile.preset) for profile in registration.unavailable_mode_profiles
    }
    if unavailable.intersection(pairs):
        raise ValueError("an unavailable mode profile cannot also be an available profile")
    for profile in profiles:
        RuntimeProfile.__post_init__(profile)


def _profile_policy_values(
    registration: RegisteredRuntime, profile: Optional[RuntimeProfile]
) -> Any:
    """Return the selected profile or legacy registration policy facts."""

    return registration if profile is None else profile


def _validate_offline_managed_registration_shape(registration: RegisteredRuntime) -> None:
    """Recheck the narrow offline managed shape at every registry boundary."""

    if type(registration.offline_managed_execution) is not bool:
        raise ValueError("offline_managed_execution must be a bool")
    if not registration.offline_managed_execution:
        return
    if registration.allowed_presets != ("replay",):
        raise ValueError("offline managed execution is restricted to the replay preset")
    if registration.allowed_secrets_refs != ("none",):
        raise ValueError("offline managed execution must not accept provider secrets")
    if registration.available_capabilities != MANAGED_WRITE_CAPABILITIES:
        raise ValueError("offline managed execution requires exactly execution, risk, and monitor")
    if registration.sandbox_write_policy != "deny":
        raise ValueError("offline managed execution must deny sandbox provider writes")
    if registration.approval_receipt_digest is not None:
        raise ValueError("offline managed execution must not carry an approval receipt")


@dataclass(frozen=True)
class RuntimeSet:
    """A reviewed, code-owned set of registered runtime identities.

    Batch bootstrap deliberately accepts a set *name*, never a user supplied
    list of filesystem paths.  The registry validates every identity when it
    is constructed, so an operator cannot use a batch command to discover or
    create configuration in an arbitrary directory.
    """

    name: str
    runtime_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_ids", tuple(self.runtime_ids))
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("runtime set name must not be empty")
        if not self.runtime_ids:
            raise ValueError("runtime set must contain at least one runtime identity")
        if any(
            not isinstance(runtime_id, str) or not runtime_id for runtime_id in self.runtime_ids
        ):
            raise ValueError("runtime set identities must be non-empty strings")
        if len(set(self.runtime_ids)) != len(self.runtime_ids):
            raise ValueError("runtime set has duplicate runtime identities")


@dataclass(frozen=True)
class BootstrapRuntimeSetItem:
    """A redacted, deterministic result for one batch-bootstrap target."""

    runtime_id: str
    strategy_id: str
    runtime_dir: str
    mode: str
    preset: str
    status: str
    reason: Optional[str] = None
    config_digest: Optional[str] = None

    def as_public_dict(self) -> Dict[str, Optional[str]]:
        result: Dict[str, Optional[str]] = {
            "runtime_id": self.runtime_id,
            "strategy_id": self.strategy_id,
            "runtime_dir": self.runtime_dir,
            "mode": self.mode,
            "preset": self.preset,
            "status": self.status,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        if self.config_digest is not None:
            result["config_digest"] = self.config_digest
        return result


@dataclass(frozen=True)
class BootstrapRuntimeSetResult:
    """Batch-bootstrap outcome that never includes secrets or config values."""

    runtime_set: str
    status: str
    items: Tuple[BootstrapRuntimeSetItem, ...]

    @property
    def succeeded(self) -> bool:
        return self.status == "bootstrapped"

    def as_public_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "runtime_set": self.runtime_set,
            "items": [item.as_public_dict() for item in self.items],
        }


class RuntimeRegistry:
    """An immutable collection of registered runtime directories."""

    def __init__(
        self,
        registrations: Iterable[RegisteredRuntime] = (),
        *,
        runtime_sets: Iterable[RuntimeSet] = (),
        ctp_simnow_readonly_bindings: Iterable[Any] = (),
        registry_id: str = "backtrader.runtime",
        trusted: bool = True,
    ) -> None:
        entries = tuple(registrations)
        by_directory: Dict[str, RegisteredRuntime] = {}
        by_lexical_directory: Dict[str, RegisteredRuntime] = {}
        by_runtime_id: Dict[str, RegisteredRuntime] = {}
        for registration in entries:
            if not isinstance(registration, RegisteredRuntime):
                raise TypeError("runtime registry entries must be RegisteredRuntime instances")
            _validate_offline_managed_registration_shape(registration)
            _validate_unavailable_mode_profiles_shape(registration)
            _validate_runtime_profiles_shape(registration)
            key = _directory_key(registration.runtime_dir)
            if key in by_directory:
                raise ValueError("runtime registry has duplicate runtime directories")
            lexical_key = registration.runtime_dir_lookup_key
            if lexical_key in by_lexical_directory:
                raise ValueError("runtime registry has duplicate runtime directory spellings")
            if registration.runtime_id in by_runtime_id:
                raise ValueError("runtime registry has duplicate runtime identities")
            by_directory[key] = registration
            by_lexical_directory[lexical_key] = registration
            by_runtime_id[registration.runtime_id] = registration

        named_sets = tuple(runtime_sets)
        by_set_name: Dict[str, Tuple[RegisteredRuntime, ...]] = {}
        for runtime_set in named_sets:
            if not isinstance(runtime_set, RuntimeSet):
                raise TypeError("runtime registry sets must be RuntimeSet instances")
            if runtime_set.name in by_set_name:
                raise ValueError("runtime registry has duplicate runtime set names")
            try:
                members = tuple(by_runtime_id[runtime_id] for runtime_id in runtime_set.runtime_ids)
            except KeyError:
                raise ValueError(
                    "runtime set references an unregistered runtime identity"
                ) from None
            by_set_name[runtime_set.name] = members

        readonly_bindings = tuple(ctp_simnow_readonly_bindings)
        by_ctp_simnow_runtime_id: Dict[str, Any] = {}
        ctp_simnow_binding_snapshots: Dict[str, Tuple[Any, ...]] = {}
        if readonly_bindings:
            # Keep the ordinary config/registry import path free of CTP
            # contracts.  The optional operator surface is loaded only for a
            # registry that explicitly declares a reviewed private-read route.
            from .ctp_simnow_operator import (
                CtpSimNowConfigReadOnlyBinding,
                CtpSimNowReadOnlyBinding,
            )

            for binding in readonly_bindings:
                if type(binding) not in (
                    CtpSimNowReadOnlyBinding,
                    CtpSimNowConfigReadOnlyBinding,
                ):
                    raise TypeError(
                        "CTP SimNow operator bindings must be exact code-owned binding instances"
                    )
                # A frozen dataclass can still be changed through
                # object.__setattr__.  Validate the current values and seal
                # every field before exposing this registry to a dispatcher.
                type(binding).__post_init__(binding)
                if binding.runtime_id in by_ctp_simnow_runtime_id:
                    raise ValueError("runtime has duplicate CTP SimNow read-only bindings")
                registration = by_runtime_id.get(binding.runtime_id)
                if registration is None:
                    raise ValueError("CTP SimNow binding references an unregistered runtime")
                if registration.profiles:
                    profile = registration.profile_for("simulation", "sandbox")
                    unavailable = tuple(
                        (item.mode, item.preset, item.reason)
                        for item in registration.unavailable_mode_profiles
                    )
                    profile_shape_ok = (
                        type(binding) is CtpSimNowConfigReadOnlyBinding
                        and len(registration.profiles) == 1
                        and type(profile) is RuntimeProfile
                        and registration.profiles[0] is profile
                        and profile.mode == "simulation"
                        and profile.preset == "sandbox"
                        and registration.allowed_presets == ()
                        and registration.allowed_parameter_keys == ()
                        and registration.allowed_secrets_refs == ("none",)
                        and registration.available_capabilities == ()
                        and registration.offline_managed_execution is False
                        and registration.sandbox_write_policy == "deny"
                        and registration.approval_receipt_digest is None
                        and registration.runner_module is None
                        and registration.runner_entrypoint == "run_runtime"
                        and registration.capability_modules == ()
                        and registration.bootstrap_parameters == ()
                        and profile.allowed_parameter_keys == ()
                        and profile.allowed_secrets_refs == ("config_yaml",)
                        and profile.available_capabilities == ()
                        and profile.approval_receipt_digest is None
                        and profile.runner_module is None
                        and profile.runner_entrypoint == "run_runtime"
                        and profile.capability_modules == ()
                        and profile.offline_managed_execution is False
                        and profile.sandbox_write_policy == "deny"
                        and binding.secrets_ref == "config_yaml"
                        and unavailable
                        == (
                            (
                                "live",
                                "managed_live_direct",
                                "managed_live_direct_profile_unavailable",
                            ),
                        )
                    )
                else:
                    profile_shape_ok = (
                        registration.allowed_presets == ("sandbox",)
                        and registration.allowed_parameter_keys == ()
                        and registration.allowed_secrets_refs == (binding.secrets_ref,)
                        and registration.available_capabilities == ()
                        and registration.offline_managed_execution is False
                        and registration.sandbox_write_policy == "deny"
                        and registration.approval_receipt_digest is None
                        and registration.runner_module is None
                        and registration.capability_modules == ()
                    )
                if not profile_shape_ok:
                    raise ValueError(
                        "CTP SimNow read-only binding requires an exact sandbox-only runtime with zero-write policy"
                    )
                # Reuse the admission contract's field validation while
                # binding it to the exact RegisteredRuntime object.  This is
                # local validation only; it does not load credentials or an SDK.
                if type(binding) is CtpSimNowReadOnlyBinding:
                    binding._admission(registration)
                by_ctp_simnow_runtime_id[binding.runtime_id] = binding
                ctp_simnow_binding_snapshots[binding.runtime_id] = _ctp_binding_snapshot(binding)
        if not registry_id:
            raise ValueError("registry_id must not be empty")

        self._registrations = entries
        self._by_directory = by_directory
        self._by_lexical_directory = by_lexical_directory
        self._by_runtime_id = by_runtime_id
        self._runtime_sets = named_sets
        self._by_set_name = by_set_name
        self._registration_digests = MappingProxyType(
            {registration.runtime_id: registration.digest for registration in entries}
        )
        self._ctp_simnow_readonly_bindings = readonly_bindings
        self._by_ctp_simnow_runtime_id = by_ctp_simnow_runtime_id
        self._ctp_simnow_binding_snapshots = MappingProxyType(ctp_simnow_binding_snapshots)
        self.registry_id = registry_id
        self.trusted = bool(trusted)

    @property
    def registrations(self) -> Tuple[RegisteredRuntime, ...]:
        """Return the immutable registry entries in declaration order."""

        return self._registrations

    @property
    def runtime_sets(self) -> Tuple[RuntimeSet, ...]:
        """Return reviewed batch-bootstrap set declarations in declaration order."""

        return self._runtime_sets

    @property
    def ctp_simnow_readonly_bindings(self) -> Tuple[Any, ...]:
        """Return the registry's exact code-owned CTP private-read bindings."""

        return self._ctp_simnow_readonly_bindings

    def require_ctp_simnow_readonly_binding(self, runtime_id: str) -> Any:
        """Return one exact read-only binding or reject before provider imports."""

        binding = self._by_ctp_simnow_runtime_id.get(runtime_id)
        if binding is None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "no reviewed CTP SimNow read-only route is registered for this runtime",
                field_path="runtime.preset",
                reason="ctp_simnow_preflight_route_unregistered",
            )
        if not self.trusted:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "runtime registry is not trusted for provider preflight",
                field_path="strategy_dir",
                reason="registry_not_trusted",
            )
        try:
            binding_unchanged = _ctp_binding_snapshot(
                binding
            ) == self._ctp_simnow_binding_snapshots.get(runtime_id)
        except Exception:
            binding_unchanged = False
        if not binding_unchanged:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "registered CTP SimNow read-only binding changed after registration",
                field_path="runtime.preset",
                reason="ctp_simnow_preflight_binding_invalid",
            )
        return binding

    def require_runtime_dir(self, runtime_dir: Union[str, os.PathLike]) -> RegisteredRuntime:
        """Return an exact directory registration or reject the startup."""

        registration = self._by_directory.get(_directory_key(runtime_dir))
        if registration is None:
            # If a registered path was replaced by a symlink/junction between
            # registration and lookup, resolving the caller spelling would
            # point at the attacker target.  Retain the original lexical
            # binding long enough to emit the directory-identity rejection
            # rather than treating that target as an unrelated runtime.
            registration = self._by_lexical_directory.get(_lexical_directory_key(runtime_dir))
        if registration is None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "strategy runtime directory is not registered",
                field_path="strategy_dir",
                reason="runtime_not_registered",
            )
        if not self.trusted:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "runtime registry is not trusted for execution",
                field_path="strategy_dir",
                reason="registry_not_trusted",
            )
        self._verify_registration_snapshot(registration)
        return registration

    @staticmethod
    def _registration_identity_error() -> RuntimeConfigError:
        return RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the registered runtime policy changed after registry construction",
            field_path="runtime.registration",
            reason="runtime_registration_identity_changed",
        )

    def _verify_registration_snapshot(self, registration: RegisteredRuntime) -> None:
        # Preserve legacy registration error ordering. The additive profile
        # contract needs a registry-time snapshot because profile selectors
        # are new mutable authority inputs; older registrations retain their
        # established downstream mismatch diagnostics.
        if (
            registration.profiles
            and self._registration_digests.get(registration.runtime_id) != registration.digest
        ):
            raise self._registration_identity_error()

    @staticmethod
    def _directory_identity_error() -> RuntimeConfigError:
        return RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the registered runtime directory identity changed after registration",
            field_path="strategy_dir",
            reason="config_directory_identity_changed",
        )

    @staticmethod
    def _open_windows_directory_lock(path: Path) -> int:
        """Open a Windows directory handle which denies concurrent deletion.

        ``os.open`` cannot open a directory on Windows and the stdlib offers no
        ``dir_fd`` equivalent there.  A normal ``CreateFileW`` directory handle
        is still useful: requesting ``GENERIC_READ`` while deliberately
        omitting ``FILE_SHARE_DELETE`` prevents an unprivileged peer from
        renaming or replacing that directory (or one of its parents) until the
        handle closes.  The caller converts the handle to a CRT descriptor so
        that it can compare its identity with the reviewed registration.

        This is intentionally a narrowly-scoped private primitive.  It does
        not turn Windows into a descriptor-relative filesystem API; path based
        file operations below remain safe only while this lease is held.
        """

        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes
        except (ImportError, AttributeError):
            raise OSError("Windows directory locking support is unavailable") from None

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

        generic_read = 0x80000000
        file_share_read = 0x00000001
        file_share_write = 0x00000002
        open_existing = 3
        file_flag_backup_semantics = 0x02000000
        file_flag_open_reparse_point = 0x00200000
        invalid_handle = ctypes.c_void_p(-1).value
        handle = create_file(
            str(path),
            generic_read,
            file_share_read | file_share_write,
            None,
            open_existing,
            file_flag_backup_semantics | file_flag_open_reparse_point,
            None,
        )
        if handle == invalid_handle or handle == -1:
            raise OSError(ctypes.get_last_error(), "CreateFileW could not lock runtime directory")
        try:
            # Ownership transfers to the CRT fd.  ``O_NOINHERIT`` ensures a
            # spawned provider or test process cannot accidentally retain the
            # lease after this runtime call has finished.
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_NOINHERIT", 0))
        except OSError:
            close_handle(handle)
            raise

    def verify_runtime_dir_identity(self, registration: RegisteredRuntime) -> None:
        """Fail closed when a reviewed runtime directory was replaced.

        The registration records an ``lstat`` identity, including the exact
        mode, when the code-owned registry is built.  Rechecking both the
        directory type and identity catches a directory replacement, a leaf
        symlink/junction, and a parent-path redirect before runtime config or
        runner code is used.
        """

        trusted = self._by_directory.get(_directory_key(registration.runtime_dir))
        if trusted is not registration:
            raise self._directory_identity_error()
        self._verify_registration_snapshot(registration)
        expected = registration.directory_identity
        if expected is None:
            raise self._directory_identity_error()
        try:
            current = os.lstat(str(registration.runtime_dir))
        except OSError:
            raise self._directory_identity_error() from None
        if not expected.matches(current):
            raise self._directory_identity_error()

    @contextmanager
    def verified_runtime_directory(
        self, registration: RegisteredRuntime
    ) -> Generator[Optional[int], None, None]:
        """Yield a verified runtime-directory fd where the OS supports it.

        POSIX runs use ``O_DIRECTORY`` and ``O_NOFOLLOW`` plus descriptor
        relative config opens.  Windows has no portable descriptor-relative
        API, so it holds a ``CreateFileW`` directory lease which excludes
        ``FILE_SHARE_DELETE`` for the whole operation.  That blocks normal
        cross-process directory or parent replacement while bootstrap writes
        and while a runner receives its runtime pathname.
        """

        self.verify_runtime_dir_identity(registration)
        descriptor: Optional[int] = None
        windows_lock_fd: Optional[int] = None
        if os.name == "posix" and hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(str(registration.runtime_dir), flags)
                opened = os.fstat(descriptor)
            except OSError:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                raise self._directory_identity_error() from None
            expected = registration.directory_identity
            if expected is None or not expected.matches(opened):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise self._directory_identity_error()
        elif os.name == "nt":
            try:
                windows_lock_fd = self._open_windows_directory_lock(registration.runtime_dir)
                opened = os.fstat(windows_lock_fd)
            except OSError:
                if windows_lock_fd is not None:
                    try:
                        os.close(windows_lock_fd)
                    except OSError:
                        pass
                raise self._directory_identity_error() from None
            expected = registration.directory_identity
            if expected is None or not expected.matches(opened):
                try:
                    os.close(windows_lock_fd)
                except OSError:
                    pass
                raise self._directory_identity_error()
            # The handle identity proves the path lookup selected the reviewed
            # object.  Recheck the name while the lease is now active so a
            # path change immediately before handle acquisition is also a
            # fail-closed startup error.
            try:
                self.verify_runtime_dir_identity(registration)
            except RuntimeConfigError:
                try:
                    os.close(windows_lock_fd)
                except OSError:
                    pass
                raise
        try:
            yield descriptor
        finally:
            # Validate while the Windows lease is still held.  Without this
            # ordering, closing it first would reopen a narrow window in which
            # a runner's pathname could be replaced before the final check.
            identity_error: Optional[RuntimeConfigError] = None
            try:
                self.verify_runtime_dir_identity(registration)
            except RuntimeConfigError as error:
                identity_error = error
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if windows_lock_fd is not None:
                try:
                    os.close(windows_lock_fd)
                except OSError:
                    pass
            if identity_error is not None:
                raise identity_error
            self.verify_runtime_dir_identity(registration)

    def require_runtime_set(self, name: str) -> Tuple[RegisteredRuntime, ...]:
        """Resolve a reviewed runtime-set name without accepting arbitrary paths."""

        members = self._by_set_name.get(name)
        if members is None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "runtime set is not registered",
                field_path="runtime_set",
                reason="runtime_set_not_registered",
            )
        if not self.trusted:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "runtime registry is not trusted for execution",
                field_path="runtime_set",
                reason="registry_not_trusted",
            )
        return members


def default_runtime_registry() -> RuntimeRegistry:
    """Return the package default registry.

    The source distribution ships only reviewed offline replay runtimes.
    Deployments add their own reviewed registrations through code or a signed
    operator integration; the loader never discovers arbitrary directories from
    CWD, environment variables, or user-editable YAML.
    """

    # Imported lazily to avoid the registry/inventory construction cycle and to
    # keep this module free of example, strategy, and provider imports.
    from .inventory import iteration41_runtime_registry

    return iteration41_runtime_registry()


@dataclass(frozen=True)
class EffectiveRuntimeConfig:
    """Read-only mode/preset policy resolved against a trusted registration."""

    config: RuntimeConfig
    registration: RegisteredRuntime
    policy: PresetPolicy
    order_route: Optional[str]
    account_access: Optional[str]
    required_capabilities: Tuple[str, ...]
    allows_network: bool
    allows_external_writes: bool
    allows_production_writes: bool
    allows_hypothetical_fills: bool
    requires_approval: bool
    requires_live_confirmation: bool
    effective_digest: str
    profile: Optional[RuntimeProfile] = None

    @property
    def strategy_id(self) -> str:
        return self.config.strategy_id

    @property
    def mode(self) -> str:
        return self.config.mode

    @property
    def preset(self) -> str:
        return self.config.preset

    @property
    def parameters(self) -> Mapping[str, Any]:
        return self.config.parameters

    @property
    def config_digest(self) -> str:
        return self.config.config_digest

    @property
    def profile_dispatch_available(self) -> bool:
        """Return whether this profile is eligible for the offline runner bridge.

        Profile dispatch currently admits only a code-owned, secret-free,
        network-free replay or local backtest runner.  In particular, the
        simulation/sandbox CTP profile remains closed even when its write
        policy is ``deny`` because that preset permits network and secret
        references.
        """

        profile = self.profile
        if profile is None:
            # Preserve the established single-profile registration path.
            return True
        if type(profile) is not RuntimeProfile:
            return False
        if profile is not self.registration.profile_for(self.mode, self.preset):
            return False
        if (profile.mode, profile.preset) not in (
            ("simulation", "replay"),
            ("backtest", "local_backtest"),
        ):
            return False
        return (
            profile.runner_module is not None
            and profile.allowed_secrets_refs == ("none",)
            and self.config.secrets_ref == "none"
            and profile.available_capabilities == ()
            and profile.capability_modules == ()
            and profile.approval_receipt_digest is None
            and profile.offline_managed_execution is False
            and profile.sandbox_write_policy == "deny"
            and self.order_route is None
            and self.account_access is None
            and self.required_capabilities == ()
            and self.allows_network is False
            and self.allows_external_writes is False
            and self.allows_production_writes is False
            and self.allows_hypothetical_fills is False
            and self.requires_approval is False
            and self.requires_live_confirmation is False
        )

    def as_public_dict(self) -> Dict[str, Any]:
        """Return a redacted, JSON-safe effective configuration summary."""

        dispatch_available = self.profile_dispatch_available
        return {
            "strategy_id": self.strategy_id,
            "mode": self.mode,
            "preset": self.preset,
            "environment": self.policy.environment,
            # Profile policy bits are visible only when the selected profile
            # is eligible for the narrow offline runner dispatch contract.
            "order_route": self.order_route if dispatch_available else None,
            "account_access": self.account_access if dispatch_available else None,
            "required_capabilities": self.required_capabilities,
            "allows_network": self.allows_network if dispatch_available else False,
            "allows_external_writes": (
                self.allows_external_writes if dispatch_available else False
            ),
            "allows_production_writes": (
                self.allows_production_writes if dispatch_available else False
            ),
            "allows_hypothetical_fills": (
                self.allows_hypothetical_fills if dispatch_available else False
            ),
            "requires_approval": self.requires_approval,
            "requires_live_confirmation": self.requires_live_confirmation,
            "config_digest": self.config_digest,
            "registration_digest": self.registration.digest,
            "effective_digest": self.effective_digest,
            "profile_dispatch_available": self.profile_dispatch_available,
            "profile_dispatch_unavailable_reason": (
                None if self.profile_dispatch_available else "profile_dispatch_unavailable"
            ),
            "profile": None
            if self.profile is None
            else {"mode": self.profile.mode, "preset": self.profile.preset},
        }


@dataclass(frozen=True)
class _EffectiveRuntimeConfigSeal:
    """Private identity/snapshot for effective configs produced by this module."""

    registry: RuntimeRegistry
    config: RuntimeConfig
    registration: RegisteredRuntime
    registration_directory_identity: Optional[RuntimeDirectoryIdentity]
    registration_digest: str
    policy: PresetPolicy
    order_route: Optional[str]
    account_access: Optional[str]
    required_capabilities: Tuple[str, ...]
    allows_network: bool
    allows_external_writes: bool
    allows_production_writes: bool
    allows_hypothetical_fills: bool
    requires_approval: bool
    requires_live_confirmation: bool
    effective_digest: str
    profile: Optional[RuntimeProfile]
    profile_digest: Optional[str]


_EFFECTIVE_RUNTIME_CONFIG_SEALS: Dict[int, Tuple[Any, _EffectiveRuntimeConfigSeal]] = {}


def _seal_effective_runtime_config(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> EffectiveRuntimeConfig:
    """Record resolver provenance outside the public EffectiveRuntimeConfig fields."""

    identifier = id(effective)

    def discard(reference: Any) -> None:
        current = _EFFECTIVE_RUNTIME_CONFIG_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _EFFECTIVE_RUNTIME_CONFIG_SEALS.pop(identifier, None)

    reference = weakref.ref(effective, discard)
    _EFFECTIVE_RUNTIME_CONFIG_SEALS[identifier] = (
        reference,
        _EffectiveRuntimeConfigSeal(
            registry=registry,
            config=effective.config,
            registration=effective.registration,
            registration_directory_identity=effective.registration.directory_identity,
            registration_digest=effective.registration.digest,
            policy=effective.policy,
            order_route=effective.order_route,
            account_access=effective.account_access,
            required_capabilities=effective.required_capabilities,
            allows_network=effective.allows_network,
            allows_external_writes=effective.allows_external_writes,
            allows_production_writes=effective.allows_production_writes,
            allows_hypothetical_fills=effective.allows_hypothetical_fills,
            requires_approval=effective.requires_approval,
            requires_live_confirmation=effective.requires_live_confirmation,
            effective_digest=effective.effective_digest,
            profile=effective.profile,
            profile_digest=None if effective.profile is None else effective.profile.digest,
        ),
    )
    return effective


def require_effective_runtime_config_seal(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> None:
    """Reject forged values, cross-registry reuse, and changed directories."""

    entry = _EFFECTIVE_RUNTIME_CONFIG_SEALS.get(id(effective))
    if entry is None or entry[0]() is not effective:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the effective runtime configuration was not produced by policy resolution",
            field_path="runtime.runner",
            reason="effective_config_mismatch",
        )
    seal = entry[1]
    if (
        seal.registry is not registry
        or seal.registration_directory_identity != seal.registration.directory_identity
        or (effective.profile is not None and seal.registration_digest != seal.registration.digest)
        or effective.config is not seal.config
        or effective.registration is not seal.registration
        or effective.policy is not seal.policy
        or effective.order_route != seal.order_route
        or effective.account_access != seal.account_access
        or effective.required_capabilities is not seal.required_capabilities
        or effective.allows_network != seal.allows_network
        or effective.allows_external_writes != seal.allows_external_writes
        or effective.allows_production_writes != seal.allows_production_writes
        or effective.allows_hypothetical_fills != seal.allows_hypothetical_fills
        or effective.requires_approval != seal.requires_approval
        or effective.requires_live_confirmation != seal.requires_live_confirmation
        or effective.effective_digest != seal.effective_digest
        or effective.profile is not seal.profile
        or (None if effective.profile is None else effective.profile.digest) != seal.profile_digest
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the effective runtime configuration no longer matches policy resolution",
            field_path="runtime.runner",
            reason="effective_config_mismatch",
        )
    # The effective value was issued for this exact registry and its original
    # directory identity.  Verify that private binding before any caller-owned
    # EffectiveRuntimeConfig field is read during runner re-resolution.
    registry.verify_runtime_dir_identity(seal.registration)
    require_loaded_runtime_config_seal(effective.config, registry)


def _validate_parameters(
    config: RuntimeConfig,
    registration: RegisteredRuntime,
    profile: Optional[RuntimeProfile] = None,
) -> None:
    policy_values = _profile_policy_values(registration, profile)
    allowed = frozenset(policy_values.allowed_parameter_keys)
    for key in config.parameters:
        if key not in allowed:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "strategy parameter is not registered for this runtime",
                field_path="parameters.{0}".format(key),
                reason="parameter_not_registered",
            )


def _validate_secret_ref(
    config: RuntimeConfig,
    policy: PresetPolicy,
    registration: RegisteredRuntime,
    profile: Optional[RuntimeProfile] = None,
) -> None:
    policy_values = _profile_policy_values(registration, profile)
    if config.secrets_ref != "none" and not policy.accepts_provider_secrets:
        raise RuntimeConfigError(
            ENVIRONMENT_MISMATCH,
            "this mode/preset does not accept a provider secret reference",
            field_path="secrets_ref",
            reason="secrets_not_allowed_for_preset",
        )
    if config.secrets_ref not in policy_values.allowed_secrets_refs:
        raise RuntimeConfigError(
            ENVIRONMENT_MISMATCH,
            "secrets_ref is not bound to the registered runtime environment",
            field_path="secrets_ref",
            reason="secrets_ref_not_registered",
        )


def _require_approval(
    registration: RegisteredRuntime,
    field_path: str,
    profile: Optional[RuntimeProfile] = None,
) -> None:
    policy_values = _profile_policy_values(registration, profile)
    if policy_values.approval_receipt_digest is None:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the registered write-capable profile has no trusted approval receipt",
            field_path=field_path,
            reason="approval_receipt_missing",
        )


def _require_capabilities(
    registration: RegisteredRuntime,
    required_capabilities: Tuple[str, ...],
    field_path: str,
    profile: Optional[RuntimeProfile] = None,
) -> None:
    policy_values = _profile_policy_values(registration, profile)
    available = frozenset(policy_values.available_capabilities)
    missing = tuple(name for name in required_capabilities if name not in available)
    if missing:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the registered profile lacks a required managed capability",
            field_path=field_path,
            reason="required_capability_not_declared",
        )


def _effective_digest(
    config: RuntimeConfig,
    registration: RegisteredRuntime,
    policy: PresetPolicy,
    order_route: Optional[str],
    account_access: Optional[str],
    required_capabilities: Tuple[str, ...],
    allows_external_writes: bool,
    profile: Optional[RuntimeProfile] = None,
) -> str:
    canonical = {
        "account_access": account_access,
        "allows_external_writes": allows_external_writes,
        "config_digest": config.config_digest,
        "order_route": order_route,
        "policy": policy.name,
        "registration_digest": registration.digest,
        "required_capabilities": required_capabilities,
    }
    if profile is not None:
        canonical["profile_digest"] = profile.digest
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_runtime_config(
    config: RuntimeConfig, registry: RuntimeRegistry
) -> EffectiveRuntimeConfig:
    """Bind a parsed config to a reviewed registry entry without I/O.

    This is still a static phase.  It does not read secrets, inspect installed
    optional distributions, initialize a strategy, or make a network call.
    """

    if not isinstance(config, RuntimeConfig):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "runtime configuration must be a loader-produced RuntimeConfig",
            field_path="runtime.config",
            reason="config_provenance_invalid",
        )
    require_loaded_runtime_config_seal(config, registry)
    registration = registry.require_runtime_dir(config.strategy_dir)
    registry.verify_runtime_dir_identity(registration)
    if config.ctp_production is not None:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "CTP production config has parser support only and no reviewed admission route",
            field_path="ctp_production",
            reason="ctp_production_admission_unavailable",
        )
    if registration.strategy_id != config.strategy_id:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "strategy.id does not match the registered runtime identity",
            field_path="strategy.id",
            reason="strategy_id_not_registered",
        )
    _validate_unavailable_mode_profiles_shape(registration)
    for profile in registration.unavailable_mode_profiles:
        if (config.mode, config.preset) == (profile.mode, profile.preset):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the registered runtime profile is declared but unavailable",
                field_path="runtime.preset",
                reason=profile.reason,
            )
    _validate_runtime_profiles_shape(registration)
    profile = registration.profile_for(config.mode, config.preset)
    if registration.profiles and profile is None:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "runtime.mode and runtime.preset are not bound to a profile for this runtime",
            field_path="runtime.preset",
            reason="profile_not_registered",
        )
    if not registration.profiles and config.preset not in registration.allowed_presets:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "runtime.preset is not bound to this registered runtime",
            field_path="runtime.preset",
            reason="preset_not_registered",
        )

    policy = get_preset_policy(config.preset)
    if policy is None or policy.mode != config.mode:
        # This normally cannot happen because load_runtime_config checks it,
        # but retain the gate for programmatic RuntimeConfig construction.
        raise RuntimeConfigError(
            MODE_PRESET_MISMATCH,
            "runtime.mode and runtime.preset are not a permitted pair",
            field_path="runtime.preset",
            reason="mode_preset_mismatch",
        )

    policy_values = _profile_policy_values(registration, profile)
    _validate_parameters(config, registration, profile)
    _validate_secret_ref(config, policy, registration, profile)

    order_route = policy.order_route
    account_access = policy.account_access
    required_capabilities = policy.required_capabilities
    allows_external_writes = policy.allows_external_writes
    allows_production_writes = policy.allows_production_writes
    requires_approval = policy.requires_approval

    if policy_values.offline_managed_execution:
        # This is a deliberately narrow L2 fixture seam.  It is enabled only
        # by reviewed registration data; config.yaml cannot request it.  Keep
        # the replay policy's offline/no-write booleans intact while exposing
        # the three managed SDK capabilities to the adapter bridge.
        if (config.mode, config.preset) != ("simulation", "replay"):
            raise RuntimeConfigError(
                MODE_PRESET_MISMATCH,
                "offline managed execution is restricted to simulation/replay",
                field_path="runtime.preset",
                reason="offline_managed_execution_requires_replay",
            )
        if config.secrets_ref != "none":
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "offline managed execution must not accept provider secrets",
                field_path="secrets_ref",
                reason="offline_managed_execution_forbids_secrets",
            )
        required_capabilities = MANAGED_WRITE_CAPABILITIES
        _require_capabilities(registration, required_capabilities, "runtime.preset", profile)
        order_route = "managed_execution"
        account_access = "fake_provider"
    elif config.preset == "sandbox" and policy_values.sandbox_write_policy == "receipt_required":
        _require_approval(registration, "runtime.preset", profile)
        required_capabilities = MANAGED_WRITE_CAPABILITIES
        _require_capabilities(registration, required_capabilities, "runtime.preset", profile)
        order_route = "managed_execution"
        account_access = "sandbox_direct_provider"
        allows_external_writes = True
        allows_production_writes = False
        requires_approval = True
    elif required_capabilities:
        _require_approval(registration, "runtime.preset", profile)
        _require_capabilities(registration, required_capabilities, "runtime.preset", profile)

    effective_digest = _effective_digest(
        config,
        registration,
        policy,
        order_route,
        account_access,
        required_capabilities,
        allows_external_writes,
        profile,
    )
    return _seal_effective_runtime_config(
        EffectiveRuntimeConfig(
            config=config,
            registration=registration,
            policy=policy,
            order_route=order_route,
            account_access=account_access,
            required_capabilities=required_capabilities,
            allows_network=policy.allows_network,
            allows_external_writes=allows_external_writes,
            allows_production_writes=allows_production_writes,
            allows_hypothetical_fills=policy.allows_hypothetical_fills,
            requires_approval=requires_approval,
            requires_live_confirmation=policy.requires_live_confirmation,
            effective_digest=effective_digest,
            profile=profile,
        ),
        registry,
    )


def validate_runtime_config(
    strategy_dir: Union[str, os.PathLike], registry: RuntimeRegistry
) -> EffectiveRuntimeConfig:
    """Run registration, strict schema, and sealed-policy validation only."""

    config = load_runtime_config(strategy_dir, registry=registry)
    return resolve_runtime_config(config, registry)


def _bootstrap_content(
    registration: RegisteredRuntime, policy: PresetPolicy, *, secrets_ref: str = "none"
) -> str:
    parameter_lines = []
    for key, value in registration.bootstrap_parameters:
        if isinstance(value, tuple):
            parameter_lines.append("  {0}:".format(key))
            parameter_lines.extend(
                "    - {0}".format(_bootstrap_yaml_scalar(item)) for item in value
            )
        else:
            parameter_lines.append("  {0}: {1}".format(key, _bootstrap_yaml_scalar(value)))
    parameters = (
        "parameters: {}" if not parameter_lines else "parameters:\n" + "\n".join(parameter_lines)
    )
    return (
        "config_schema_version: 4\n\n"
        "strategy:\n"
        "  id: {0}\n\n"
        "runtime:\n"
        "  mode: {1}\n"
        "  preset: {2}\n\n"
        "{3}\n"
        "secrets_ref: {4}\n"
    ).format(registration.strategy_id, policy.mode, policy.name, parameters, secrets_ref)


def _bootstrap_yaml_scalar(value: Any) -> str:
    """Serialize one constrained, code-owned bootstrap scalar as YAML text."""

    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    return json.dumps(value, ensure_ascii=True)


_SAFE_BOOTSTRAP_PRESETS = ("local_backtest", "replay", "shadow", "paper", "sandbox")


def select_bootstrap_preset(registration: RegisteredRuntime) -> str:
    """Select the safest reviewed non-write preset bound to one registration."""

    for preset in _SAFE_BOOTSTRAP_PRESETS:
        if preset not in registration.allowed_presets:
            continue
        if preset == "sandbox" and registration.sandbox_write_policy == "receipt_required":
            continue
        return preset
    raise RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "this runtime has no bootstrap-safe preset",
        field_path="runtime.preset",
        reason="bootstrap_safe_preset_unavailable",
    )


def _prepare_bootstrap(
    registration: RegisteredRuntime, preset: str, *, secrets_ref: str = "none"
) -> Tuple[PresetPolicy, str]:
    """Validate a no-write bootstrap request and produce its canonical text."""

    policy = get_preset_policy(preset)
    if policy is None:
        raise RuntimeConfigError(
            MODE_PRESET_MISMATCH,
            "runtime.preset is not a registered preset name",
            field_path="runtime.preset",
            reason="unsupported_preset",
        )
    if preset not in registration.allowed_presets:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "runtime.preset is not bound to this registered runtime",
            field_path="runtime.preset",
            reason="preset_not_registered",
        )
    if secrets_ref not in registration.allowed_secrets_refs:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "bootstrap has no code-owned secret reference for this runtime",
            field_path="secrets_ref",
            reason="bootstrap_secret_reference_unavailable",
        )
    if policy.allows_production_writes or (
        preset == "sandbox" and registration.sandbox_write_policy == "receipt_required"
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "bootstrap cannot generate a write-capable runtime contract",
            field_path="runtime.preset",
            reason="bootstrap_write_capable_preset_not_allowed",
        )
    if registration.directory_identity is None:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "registered runtime directory is unavailable",
            field_path="strategy_dir",
            reason="runtime_directory_unavailable",
        )
    return policy, _bootstrap_content(registration, policy, secrets_ref=secrets_ref)


def _bootstrap_secrets_ref(
    registration: RegisteredRuntime, registry: RuntimeRegistry, policy: PresetPolicy
) -> str:
    """Select only the secret ref of a code-owned CTP read-only binding."""

    if policy.name == "sandbox":
        binding = registry._by_ctp_simnow_runtime_id.get(registration.runtime_id)
        if binding is not None:
            # Neither the legacy validation-only binding nor the reviewed
            # config-driven binding can provide account, credential, contract,
            # or exact front values. Generic bootstrap must not write an
            # unusable private config or imply that it grants provider access.
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "CTP SimNow private config.yaml must be prepared by the operator",
                field_path="ctp_simnow",
                reason="ctp_simnow_private_config_required",
            )
    return "none"


def _runtime_config_entry_exists(
    registration: RegisteredRuntime, directory_fd: Optional[int]
) -> bool:
    """Check only whether config.yaml has a directory entry under the seal."""

    try:
        if directory_fd is None:
            os.lstat(str(registration.runtime_dir / "config.yaml"))
        else:
            os.lstat("config.yaml", dir_fd=directory_fd)
    except FileNotFoundError:
        return False
    except OSError:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "config.yaml cannot be inspected in the registered runtime directory",
            field_path="config.yaml",
            reason="config_directory_identity_changed",
        ) from None
    return True


def _matching_bootstrap_config(
    registration: RegisteredRuntime,
    registry: RuntimeRegistry,
    content: str,
    *,
    directory_fd: Optional[int] = None,
) -> Optional[RuntimeConfig]:
    """Return a validated config only when it is byte-for-byte bootstrap content.

    Batch retries intentionally do not rewrite or normalize an operator-edited
    file.  A canonical file created by a prior batch is safe to skip; every
    other existing path is reported as a conflict during preflight.
    """

    try:
        source_path, existing = _read_config_text(
            registration.runtime_dir, directory_fd=directory_fd
        )
    except RuntimeConfigError:
        return None
    if existing != content:
        return None
    try:
        # Match and schema-validate the same descriptor-sealed text.  A second
        # path read here could turn a changed file into an `already_matching`
        # result after the comparison had already succeeded.
        return _parse_verified_runtime_config_text(
            existing, registration.runtime_dir, source_path, registry=registry
        )
    except RuntimeConfigError:
        return None


def _require_matching_bootstrap_config(
    registration: RegisteredRuntime,
    registry: RuntimeRegistry,
    content: str,
    *,
    directory_fd: Optional[int] = None,
) -> RuntimeConfig:
    """Return one post-write config only when its sealed bytes are canonical.

    The writer and parser share the caller's already verified directory
    descriptor on POSIX.  In particular, do not call ``load_runtime_config``
    here: it would reopen the path after creation and could report a digest
    for a different, concurrently replaced file.
    """

    config = _matching_bootstrap_config(registration, registry, content, directory_fd=directory_fd)
    if config is not None:
        return config
    raise RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "config.yaml changed after bootstrap creation",
        field_path="config.yaml",
        reason="config_identity_changed",
    )


def bootstrap_runtime_set(runtime_set: str, registry: RuntimeRegistry) -> BootstrapRuntimeSetResult:
    """Create canonical safe configs for one reviewed set of runtime identities.

    All targets are inspected before any file is written.  Existing canonical
    configs are idempotent ``already_matching`` results.  Any preflight
    conflict leaves every missing target untouched.  After a successful
    preflight each target is created with the existing O_EXCL writer, so a
    concurrent creator can only affect that one target and never cause an
    overwrite or rollback of unrelated configurations.
    """

    registrations = registry.require_runtime_set(runtime_set)
    prepared = []
    preflight_items = []
    has_conflict = False
    for registration in registrations:
        try:
            preset = select_bootstrap_preset(registration)
            preview_policy = get_preset_policy(preset)
            secrets_ref = (
                "none"
                if preview_policy is None
                else _bootstrap_secrets_ref(registration, registry, preview_policy)
            )
            policy, content = _prepare_bootstrap(registration, preset, secrets_ref=secrets_ref)
            with registry.verified_runtime_directory(registration) as directory_fd:
                has_existing_config = _runtime_config_entry_exists(registration, directory_fd)
                existing = (
                    _matching_bootstrap_config(
                        registration,
                        registry,
                        content,
                        directory_fd=directory_fd,
                    )
                    if has_existing_config
                    else None
                )
        except RuntimeConfigError as error:
            preflight_items.append(
                BootstrapRuntimeSetItem(
                    runtime_id=registration.runtime_id or registration.strategy_id,
                    strategy_id=registration.strategy_id,
                    runtime_dir=str(registration.runtime_dir),
                    mode="",
                    preset="",
                    status="conflict",
                    reason=error.reason or "bootstrap_preflight_failed",
                )
            )
            has_conflict = True
            continue

        if has_existing_config:
            if existing is None:
                preflight_items.append(
                    BootstrapRuntimeSetItem(
                        runtime_id=registration.runtime_id or registration.strategy_id,
                        strategy_id=registration.strategy_id,
                        runtime_dir=str(registration.runtime_dir),
                        mode=policy.mode,
                        preset=policy.name,
                        status="conflict",
                        reason="existing_config_differs",
                    )
                )
                has_conflict = True
            else:
                preflight_items.append(
                    BootstrapRuntimeSetItem(
                        runtime_id=registration.runtime_id or registration.strategy_id,
                        strategy_id=registration.strategy_id,
                        runtime_dir=str(registration.runtime_dir),
                        mode=policy.mode,
                        preset=policy.name,
                        status="already_matching",
                        config_digest=existing.config_digest,
                    )
                )
            continue
        prepared.append((registration, policy, content))
        preflight_items.append(
            BootstrapRuntimeSetItem(
                runtime_id=registration.runtime_id or registration.strategy_id,
                strategy_id=registration.strategy_id,
                runtime_dir=str(registration.runtime_dir),
                mode=policy.mode,
                preset=policy.name,
                status="pending",
            )
        )

    if has_conflict:
        items = []
        for item in preflight_items:
            if item.status == "pending":
                items.append(
                    BootstrapRuntimeSetItem(
                        runtime_id=item.runtime_id,
                        strategy_id=item.strategy_id,
                        runtime_dir=item.runtime_dir,
                        mode=item.mode,
                        preset=item.preset,
                        status="not_written",
                        reason="batch_preflight_failed",
                    )
                )
            else:
                items.append(item)
        return BootstrapRuntimeSetResult(
            runtime_set=runtime_set,
            status="preflight_failed",
            items=tuple(items),
        )

    created_by_runtime_id: Dict[str, BootstrapRuntimeSetItem] = {}
    creation_failed = False
    for registration, policy, content in prepared:
        runtime_id = registration.runtime_id or registration.strategy_id
        try:
            with registry.verified_runtime_directory(registration) as directory_fd:
                write_bootstrap_config(
                    registration.runtime_dir / "config.yaml",
                    content,
                    directory_fd=directory_fd,
                )
                config = _require_matching_bootstrap_config(
                    registration,
                    registry,
                    content,
                    directory_fd=directory_fd,
                )
            created_by_runtime_id[runtime_id] = BootstrapRuntimeSetItem(
                runtime_id=runtime_id,
                strategy_id=registration.strategy_id,
                runtime_dir=str(registration.runtime_dir),
                mode=policy.mode,
                preset=policy.name,
                status="created",
                config_digest=config.config_digest,
            )
        except RuntimeConfigError as error:
            # A successful create followed by a non-matching descriptor must
            # never be relabelled ``already_matching`` by reopening a later
            # pathname.  Only an O_EXCL/concurrent-create failure may inspect
            # one current descriptor to recognise an independently-created
            # canonical file.
            existing = None
            if error.reason != "config_identity_changed":
                try:
                    with registry.verified_runtime_directory(registration) as directory_fd:
                        existing = _matching_bootstrap_config(
                            registration,
                            registry,
                            content,
                            directory_fd=directory_fd,
                        )
                except RuntimeConfigError:
                    existing = None
            if existing is not None:
                created_by_runtime_id[runtime_id] = BootstrapRuntimeSetItem(
                    runtime_id=runtime_id,
                    strategy_id=registration.strategy_id,
                    runtime_dir=str(registration.runtime_dir),
                    mode=policy.mode,
                    preset=policy.name,
                    status="already_matching",
                    config_digest=existing.config_digest,
                )
            else:
                created_by_runtime_id[runtime_id] = BootstrapRuntimeSetItem(
                    runtime_id=runtime_id,
                    strategy_id=registration.strategy_id,
                    runtime_dir=str(registration.runtime_dir),
                    mode=policy.mode,
                    preset=policy.name,
                    status="creation_failed",
                    reason=error.reason or "config_create_failed",
                )
                creation_failed = True

    items = []
    for item in preflight_items:
        if item.status == "pending":
            items.append(created_by_runtime_id[item.runtime_id])
        else:
            items.append(item)
    return BootstrapRuntimeSetResult(
        runtime_set=runtime_set,
        status="partial" if creation_failed else "bootstrapped",
        items=tuple(items),
    )


def bootstrap_runtime_config(
    strategy_dir: Union[str, os.PathLike],
    registry: RuntimeRegistry,
    preset: str = "local_backtest",
) -> RuntimeConfig:
    """Create a reviewed safe default config with atomic no-overwrite semantics."""

    registration = registry.require_runtime_dir(strategy_dir)
    preview_policy = get_preset_policy(preset)
    if preview_policy is None:
        policy, content = _prepare_bootstrap(registration, preset)
    else:
        secrets_ref = _bootstrap_secrets_ref(registration, registry, preview_policy)
        policy, content = _prepare_bootstrap(registration, preset, secrets_ref=secrets_ref)

    with registry.verified_runtime_directory(registration) as directory_fd:
        if _runtime_config_entry_exists(registration, directory_fd):
            raise RuntimeConfigError(
                CONFIG_EXISTS,
                "config.yaml already exists and will not be overwritten",
                field_path="config.yaml",
                reason="config_exists",
            )
        write_bootstrap_config(
            registration.runtime_dir / "config.yaml", content, directory_fd=directory_fd
        )
        config = _require_matching_bootstrap_config(
            registration,
            registry,
            content,
            directory_fd=directory_fd,
        )
    return config
