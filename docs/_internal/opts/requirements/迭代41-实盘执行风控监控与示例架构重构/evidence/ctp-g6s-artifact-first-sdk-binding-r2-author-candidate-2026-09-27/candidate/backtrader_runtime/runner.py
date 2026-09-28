"""Code-owned dispatch for already validated Iteration 41 runtime runners.

The runtime registry carries a reviewed module and entrypoint name.  This
module reads neither a user-supplied import string nor an entry-point plugin;
it imports the runner only after schema, directory, preset, and capability
policy resolution has succeeded.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import inspect
import os
import stat
import sys
import types
import weakref
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from itertools import count
from pathlib import Path
from typing import Any, Generator, Optional, Tuple, Union, cast

from .capability_imports import (
    first_unavailable_trusted_capability_module,
    trusted_capability_import_context,
)
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .registry import (
    EffectiveRuntimeConfig,
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    resolve_runtime_config,
    validate_runtime_config,
)


_MAX_RUNNER_SOURCE_BYTES = 4 * 1024 * 1024
_PRIVATE_NAMESPACE_SEQUENCE = count()


def resolve_runner_effective_config(
    runtime_dir: Optional[Union[str, Path]],
    registry: RuntimeRegistry,
    *,
    effective: Optional[EffectiveRuntimeConfig] = None,
) -> EffectiveRuntimeConfig:
    """Return the sealed config a registered runner is allowed to consume.

    Direct runner calls must carry a sealed effective configuration.  The
    config-first dispatcher validates ``config.yaml`` and then passes sealed
    policy values into the code-owned runner.  POSIX dispatch projects those
    values into a path-free runner view; Windows retains the original object
    only while its delete-denying directory lease is held.  A runner must
    never reopen the pathname, otherwise replacing a directory or config
    between validation and strategy startup could alter its route.

    The supplied effective value is re-resolved from its in-memory immutable
    config against the same registry.  This performs no config-path read and
    detects an unrelated registry, runtime directory, or forged stale
    descriptor without re-reading ``config.yaml``.  An unsealed direct call is
    rejected before it can inspect a runtime pathname; operators use
    ``bt-runtime run`` and programmatic callers use sealed dispatch.
    """

    # POSIX dispatch supplies a path-free view plus an opaque registry token.
    # Recognise that pair before the public EffectiveRuntimeConfig type check;
    # its identity grant is the authority, and no config pathname is reopened.
    if isinstance(effective, _RunnerEffectiveConfig) or isinstance(registry, _RunnerRegistry):
        return _require_runner_dispatch_view(runtime_dir, registry, effective)

    if effective is None:
        raise _runner_error(
            "runner_dispatch_required",
            "an unsealed direct runner call is not allowed; use bt-runtime run --strategy-dir "
            "<registered-runtime-dir> or validate then dispatch the sealed configuration",
        )

    if not isinstance(effective, EffectiveRuntimeConfig):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the runner did not receive a sealed effective runtime configuration",
            field_path="runtime.runner",
            reason="effective_config_invalid",
        )

    require_effective_runtime_config_seal(effective, registry)
    resolved = resolve_runtime_config(effective.config, registry)
    if runtime_dir is not None:
        requested_registration = registry.require_runtime_dir(runtime_dir)
        if requested_registration != resolved.registration:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the supplied runtime directory does not match the sealed runtime configuration",
                field_path="strategy_dir",
                reason="effective_config_runtime_mismatch",
            )

    if (
        effective.registration != resolved.registration
        or effective.config.strategy_dir != resolved.config.strategy_dir
        or effective.config.config_digest != resolved.config.config_digest
        or effective.effective_digest != resolved.effective_digest
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed effective runtime configuration no longer matches the registry policy",
            field_path="runtime.runner",
            reason="effective_config_mismatch",
        )
    return resolved


def _runner_error(reason: str, message: str) -> RuntimeConfigError:
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        message,
        field_path="runtime.runner",
        reason=reason,
    )


def dispatch_configured_runtime(
    runtime_dir: Union[str, Path], registry: RuntimeRegistry
) -> dict[str, Any]:
    """Validate one registered config and invoke the sealed code-owned dispatcher.

    This gives retained offline script shims the same config, environment, and
    sealed-dispatch gates as ``bt-runtime run``.  It never calls a runner with
    an unsealed configuration: POSIX dispatch still withholds the mutable
    runtime pathname and Windows keeps its directory lease for the runner call.
    A configuration that requires explicit live confirmation is intentionally
    refused here; only the public CLI exposes that confirmation control.
    """

    effective = validate_runtime_config(runtime_dir, registry)
    # Import lazily to avoid a runner/CLI import cycle.  The same fixed list is
    # used by the public CLI, so a legacy standalone shim cannot become an
    # environment-override bypass.
    from .cli import _environment_override_errors

    environment_errors = _environment_override_errors(os.environ)
    if environment_errors:
        raise environment_errors[0]
    if effective.requires_live_confirmation:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "a direct config-first dispatch cannot confirm live execution; use bt-runtime run "
            "--strategy-dir <registered-runtime-dir> --confirm-live",
            field_path="--confirm-live",
            reason="live_confirmation_required",
        )
    return dispatch_registered_runtime(effective, registry)


def _runner_path_access_error() -> RuntimeConfigError:
    """Reject a runner-facing attempt to recover the mutable directory path.

    POSIX dispatch intentionally gives a runner a directory descriptor
    capability instead of the registered pathname.  The small views below
    preserve every reviewed policy value a runner needs while making an
    accidental path recovery a deterministic policy rejection rather than an
    attribute leak.
    """

    return _runner_error(
        "runner_runtime_path_access_denied",
        "a POSIX-dispatched runner must use the runtime-directory capability instead of a pathname",
    )


def _copy_runner_parameter_value(value: Any) -> Any:
    """Return a detached JSON-shaped parameter value without loader internals."""

    if isinstance(value, Mapping):
        return {key: _copy_runner_parameter_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_copy_runner_parameter_value(item) for item in value]
    return value


@dataclass(frozen=True)
class _RunnerRuntimeConfig:
    """Path-free projection of the sealed configuration for a POSIX runner."""

    strategy_id: str
    mode: str
    preset: str
    parameters: Mapping[str, Any]
    secrets_ref: str
    config_digest: str

    @property
    def strategy_dir(self) -> Path:
        raise _runner_path_access_error()

    @property
    def source_path(self) -> Path:
        raise _runner_path_access_error()

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "strategy": {"id": self.strategy_id},
            "runtime": {"mode": self.mode, "preset": self.preset},
            "parameter_keys": tuple(sorted(self.parameters)),
            "secrets_ref": "none" if self.secrets_ref == "none" else "configured",
            "config_digest": self.config_digest,
        }

    def parameter_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _copy_runner_parameter_value(self.parameters))


@dataclass(frozen=True)
class _RunnerRegistration:
    """Path-free subset of a registration required by reviewed runners."""

    strategy_id: str
    allowed_presets: Tuple[str, ...]
    allowed_parameter_keys: Tuple[str, ...]
    allowed_secrets_refs: Tuple[str, ...]
    available_capabilities: Tuple[str, ...]
    offline_managed_execution: bool
    sandbox_write_policy: str
    approval_receipt_digest: Optional[str]
    runtime_id: Optional[str]
    runner_module: Optional[str]
    runner_entrypoint: str
    capability_modules: Tuple[str, ...]
    digest: str

    @property
    def runtime_dir(self) -> Path:
        raise _runner_path_access_error()

    @property
    def directory_identity(self) -> object:
        raise _runner_path_access_error()

    @property
    def runtime_dir_lookup_key(self) -> str:
        raise _runner_path_access_error()


@dataclass(frozen=True)
class _RunnerEffectiveConfig:
    """Path-free effective-config contract for a POSIX-dispatched runner."""

    config: _RunnerRuntimeConfig
    registration: _RunnerRegistration
    policy: Any
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
        if self.profile is None:
            return self.profile_digest is None
        return self.profile_digest is not None and self.profile.digest == self.profile_digest

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "mode": self.mode,
            "preset": self.preset,
            "environment": self.policy.environment,
            "order_route": self.order_route,
            "account_access": self.account_access,
            "required_capabilities": self.required_capabilities,
            "allows_network": self.allows_network,
            "allows_external_writes": self.allows_external_writes,
            "allows_production_writes": self.allows_production_writes,
            "allows_hypothetical_fills": self.allows_hypothetical_fills,
            "requires_approval": self.requires_approval,
            "requires_live_confirmation": self.requires_live_confirmation,
            "config_digest": self.config_digest,
            "registration_digest": self.registration.digest,
            "effective_digest": self.effective_digest,
            "profile": None
            if self.profile is None
            else {"mode": self.profile.mode, "preset": self.profile.preset},
            "profile_digest": self.profile_digest,
        }


class _RunnerRegistry:
    """Opaque registry token for a POSIX-dispatched runner.

    The resolver below checks the token by object identity.  It intentionally
    has no backing registry attribute, so a runner cannot reach the reviewed
    directory bindings through the normal registry API.
    """

    __slots__ = ("__weakref__",)

    @property
    def registrations(self) -> Tuple[object, ...]:
        raise _runner_path_access_error()

    @property
    def runtime_sets(self) -> Tuple[object, ...]:
        raise _runner_path_access_error()

    def require_runtime_dir(self, *_args: Any, **_kwargs: Any) -> object:
        raise _runner_path_access_error()

    def require_runtime_set(self, *_args: Any, **_kwargs: Any) -> Tuple[object, ...]:
        raise _runner_path_access_error()


# The grant table holds only weak references to path-free view objects.  In
# particular, it never stores the original EffectiveRuntimeConfig or
# RuntimeRegistry, so normal module inspection cannot recover the mutable
# pathname which POSIX dispatch deliberately withholds.
_RUNNER_DISPATCH_GRANTS: dict[
    int, Tuple[weakref.ReferenceType, weakref.ReferenceType, Optional[str]]
] = {}


def _runner_effective_view(effective: EffectiveRuntimeConfig) -> _RunnerEffectiveConfig:
    """Project one sealed effective config without its directory-bearing fields."""

    config = effective.config
    registration = effective.registration
    profile = None if effective.profile is None else replace(effective.profile)
    return _RunnerEffectiveConfig(
        config=_RunnerRuntimeConfig(
            strategy_id=config.strategy_id,
            mode=config.mode,
            preset=config.preset,
            parameters=config.parameters,
            secrets_ref=config.secrets_ref,
            config_digest=config.config_digest,
        ),
        registration=_RunnerRegistration(
            strategy_id=registration.strategy_id,
            allowed_presets=registration.allowed_presets,
            allowed_parameter_keys=registration.allowed_parameter_keys,
            allowed_secrets_refs=registration.allowed_secrets_refs,
            available_capabilities=registration.available_capabilities,
            offline_managed_execution=registration.offline_managed_execution,
            sandbox_write_policy=registration.sandbox_write_policy,
            approval_receipt_digest=registration.approval_receipt_digest,
            runtime_id=registration.runtime_id,
            runner_module=registration.runner_module,
            runner_entrypoint=registration.runner_entrypoint,
            capability_modules=registration.capability_modules,
            digest=registration.digest,
        ),
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
        profile=profile,
        profile_digest=None if profile is None else profile.digest,
    )


@contextmanager
def _runner_dispatch_views(
    effective: EffectiveRuntimeConfig,
) -> Generator[Tuple[_RunnerEffectiveConfig, _RunnerRegistry], None, None]:
    """Yield one active, path-free POSIX runner contract.

    Identity grants are removed immediately after the runner returns.  A
    retained view therefore cannot be replayed through
    ``resolve_runner_effective_config`` outside the original dispatch.
    """

    runner_effective = _runner_effective_view(effective)
    runner_registry = _RunnerRegistry()
    effective_identifier = id(runner_effective)

    def discard(reference: weakref.ReferenceType) -> None:
        current = _RUNNER_DISPATCH_GRANTS.get(effective_identifier)
        if current is not None and current[0] is reference:
            _RUNNER_DISPATCH_GRANTS.pop(effective_identifier, None)

    effective_reference = weakref.ref(runner_effective, discard)
    registry_reference = weakref.ref(runner_registry)
    _RUNNER_DISPATCH_GRANTS[effective_identifier] = (
        effective_reference,
        registry_reference,
        runner_effective.profile_digest,
    )
    try:
        yield runner_effective, runner_registry
    finally:
        current = _RUNNER_DISPATCH_GRANTS.get(effective_identifier)
        if current is not None and current[0] is effective_reference:
            _RUNNER_DISPATCH_GRANTS.pop(effective_identifier, None)


def _require_runner_dispatch_view(
    runtime_dir: Optional[Union[str, Path]], registry: object, effective: object
) -> _RunnerEffectiveConfig:
    """Authenticate one active path-free runner view without filesystem I/O."""

    if not isinstance(effective, _RunnerEffectiveConfig) or not isinstance(
        registry, _RunnerRegistry
    ):
        raise _runner_error(
            "runner_dispatch_context_invalid",
            "the runner did not receive the active POSIX dispatch contract",
        )
    if runtime_dir is not None:
        raise _runner_path_access_error()
    grant = _RUNNER_DISPATCH_GRANTS.get(id(effective))
    if grant is None or grant[0]() is not effective or grant[1]() is not registry:
        raise _runner_error(
            "runner_dispatch_context_expired",
            "the POSIX dispatch contract is no longer active",
        )
    if (
        effective.profile_digest != grant[2]
        or (None if effective.profile is None else effective.profile.digest) != grant[2]
        or (
            effective.profile is not None
            and (effective.profile.mode, effective.profile.preset)
            != (effective.mode, effective.preset)
        )
    ):
        raise _runner_error(
            "runner_dispatch_context_expired",
            "the POSIX profile contract no longer matches its active dispatch grant",
        )
    return effective


class RuntimeDirectoryCapability:
    """A borrowed POSIX directory capability for runtime-relative local I/O.

    A descriptor continues to address the reviewed directory after another
    process renames its pathname.  Passing that descriptor as an opaque
    capability lets a runner create a small, explicitly reviewed set of local
    artifacts without reopening the mutable runtime pathname.  The capability
    deliberately does not expose a filesystem path or its file descriptor.

    It is valid only for the duration of ``dispatch_registered_runtime``.
    Every path component is opened relative to the preceding descriptor with
    ``O_NOFOLLOW``; a symlink or a ``..`` component is therefore rejected
    instead of escaping the reviewed directory.
    """

    __slots__ = ("__directory_fd", "__active")

    def __init__(self, directory_fd: int) -> None:
        if os.name != "posix" or not isinstance(directory_fd, int) or directory_fd < 0:
            raise _runner_error(
                "runtime_directory_capability_unavailable",
                "a POSIX runtime-directory capability is unavailable",
            )
        self.__directory_fd = directory_fd
        self.__active = True

    def invalidate(self) -> None:
        """Make a retained capability fail closed after its runner returns."""

        self.__active = False

    def _require_active(self) -> int:
        if not self.__active:
            raise _runner_error(
                "runtime_directory_capability_expired",
                "the runtime-directory capability is no longer valid",
            )
        return self.__directory_fd

    @staticmethod
    def _relative_parts(relative_path: Union[str, os.PathLike]) -> Tuple[str, ...]:
        try:
            value = os.fspath(relative_path)
        except TypeError:
            raise _runner_error(
                "runtime_directory_capability_path_invalid",
                "a runtime-directory capability path must be a relative string",
            ) from None
        if not isinstance(value, str) or not value or value.startswith("/"):
            raise _runner_error(
                "runtime_directory_capability_path_invalid",
                "a runtime-directory capability path must be relative",
            )
        parts = tuple(value.split("/"))
        if any(part in ("", ".", "..") for part in parts):
            raise _runner_error(
                "runtime_directory_capability_path_invalid",
                "a runtime-directory capability path contains an unsafe component",
            )
        return parts

    @contextmanager
    def _open_directory(
        self, parts: Tuple[str, ...], *, create: bool
    ) -> Generator[int, None, None]:
        """Yield a no-follow descriptor for one relative directory."""

        try:
            current = os.dup(self._require_active())
            os.set_inheritable(current, False)
        except OSError:
            raise _runner_error(
                "runtime_directory_capability_io_failed",
                "the runtime-directory capability could not be duplicated",
            ) from None

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            for part in parts:
                try:
                    child = os.open(part, flags, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o700, dir_fd=current)
                    child = os.open(part, flags, dir_fd=current)
                try:
                    child_stat = os.fstat(child)
                    if not stat.S_ISDIR(child_stat.st_mode):
                        raise NotADirectoryError(part)
                except BaseException:
                    os.close(child)
                    raise
                os.close(current)
                current = child
            yield current
        except RuntimeConfigError:
            raise
        except OSError:
            raise _runner_error(
                "runtime_directory_capability_io_failed",
                "runtime-directory capability I/O was rejected",
            ) from None
        finally:
            try:
                os.close(current)
            except OSError:
                pass

    def write_text(self, relative_path: Union[str, os.PathLike], text: str) -> None:
        """Create one UTF-8 file below the reviewed directory without overwrite.

        Parents are created at mode ``0700``.  The final file is opened with
        ``O_EXCL`` and ``O_NOFOLLOW`` so a racing entry cannot redirect or
        replace the artifact.  This intentionally small primitive is enough
        for runner-owned markers; larger legacy output trees require their own
        descriptor-aware writer before they may use this capability.
        """

        if not isinstance(text, str):
            raise _runner_error(
                "runtime_directory_capability_content_invalid",
                "runtime-directory capability text must be a string",
            )
        parts = self._relative_parts(relative_path)
        parent_parts, filename = parts[:-1], parts[-1]
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            with self._open_directory(parent_parts, create=True) as parent_fd:
                descriptor = os.open(filename, flags, 0o600, dir_fd=parent_fd)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                        handle.write(text)
                        handle.flush()
                        os.fsync(handle.fileno())
                except BaseException:
                    try:
                        os.unlink(filename, dir_fd=parent_fd)
                    except OSError:
                        pass
                    raise
        except RuntimeConfigError:
            raise
        except OSError:
            raise _runner_error(
                "runtime_directory_capability_io_failed",
                "runtime-directory capability could not create the local artifact",
            ) from None


def _runner_accepts_runtime_directory_capability(runner: Any) -> bool:
    """Return whether a runner opted into the POSIX capability keyword.

    A legacy reviewed runner which has not opted in still receives ``None`` as
    its positional runtime directory on POSIX.  It therefore fails closed if
    it tries path I/O, rather than regaining the mutable pathname merely for
    compatibility.  New runners should declare the keyword and use the
    capability for narrowly reviewed runtime-relative artifacts.
    """

    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == "runtime_directory":
            return True
    return False


def _is_link_or_reparse(stat_result: os.stat_result) -> bool:
    """Recognise both POSIX links and Windows directory/file reparse links."""

    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return stat.S_ISLNK(stat_result.st_mode) or bool(attributes & reparse_point)


def _regular_source_identity(source_path: Path) -> Tuple[int, int, int]:
    try:
        source_stat = os.lstat(str(source_path))
    except OSError:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner source is unavailable"
        ) from None
    if _is_link_or_reparse(source_stat) or not stat.S_ISREG(source_stat.st_mode):
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner source is not a regular file"
        )
    return source_stat.st_dev, source_stat.st_ino, source_stat.st_mode


def _trusted_runner_directory(directory: Path) -> None:
    try:
        directory_stat = os.lstat(str(directory))
    except OSError:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner package is unavailable"
        ) from None
    if _is_link_or_reparse(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner package is not a concrete directory"
        )


def _read_trusted_runner_source(source_path: Path) -> bytes:
    """Read a fixed runner file without allowing a leaf-path replacement."""

    path_identity = _regular_source_identity(source_path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(source_path), flags)
    except OSError:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner source cannot be opened"
        ) from None
    try:
        descriptor_stat = os.fstat(descriptor)
        descriptor_identity = (
            descriptor_stat.st_dev,
            descriptor_stat.st_ino,
            descriptor_stat.st_mode,
        )
        if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_identity != path_identity:
            raise _runner_error(
                "runner_origin_mismatch", "the reviewed runner source changed while opening"
            )
        chunks = []
        remaining = _MAX_RUNNER_SOURCE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        source = b"".join(chunks)
    except RuntimeConfigError:
        raise
    except OSError:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner source cannot be read"
        ) from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    if len(source) > _MAX_RUNNER_SOURCE_BYTES:
        raise _runner_error("runner_origin_mismatch", "the reviewed runner source is too large")
    if _regular_source_identity(source_path) != path_identity:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed runner source changed while reading"
        )
    return source


@dataclass(frozen=True)
class _InventoryRunnerBinding:
    """One exact, code-owned runner-source binding.

    ``runner_source_root`` is the directory from which the private loader
    reads a reviewed runner.  ``backtrader_source_root`` is independently the
    root that owns the matching core package.  They are the same for source
    examples, but a packaged L2 fixture lives below the installed package
    root and must still reject a CWD ``backtrader`` shadow.
    """

    runner_source_root: Path
    backtrader_source_root: Path
    module_prefix: Tuple[str, ...]
    source_path_prefix: Tuple[str, ...]


def _inventory_runner_binding(
    registration: RegisteredRuntime,
    *,
    runner_module: Optional[str] = None,
) -> Optional[_InventoryRunnerBinding]:
    """Return a fixed binding only for an exact shipped inventory record.

    Test and deployment registries may deliberately carry local in-memory
    runner modules.  No arbitrary ``backtrader_runtime.*`` module earns the
    private-loader or provenance guard: the package fixture is admitted only
    through its own two-record, code-owned registry.
    """

    module_name = registration.runner_module if runner_module is None else runner_module
    if module_name is None:
        return None
    from . import inventory

    for reviewed in inventory.iteration41_runtime_registry().registrations:
        if reviewed == registration and module_name.startswith("examples."):
            source_root = Path(inventory.SOURCE_ROOT)
            return _InventoryRunnerBinding(
                runner_source_root=source_root,
                backtrader_source_root=source_root,
                module_prefix=("examples",),
                source_path_prefix=("examples",),
            )

    package_prefix = ("backtrader_runtime", "_iteration41_l2_fixture")
    package_prefix_text = ".".join(package_prefix)
    for reviewed in inventory.iteration41_l2_fixture_registry().registrations:
        if reviewed == registration and (
            module_name == package_prefix_text or module_name.startswith(package_prefix_text + ".")
        ):
            # ``inventory.py`` is always adjacent to the installed
            # ``backtrader`` package.  Keep core-package provenance separate
            # from the fixture directory that contains the runner sources.
            installed_package_root = Path(inventory.__file__).resolve().parent.parent
            return _InventoryRunnerBinding(
                runner_source_root=Path(inventory.PACKAGE_L2_FIXTURE_ROOT),
                backtrader_source_root=installed_package_root,
                module_prefix=package_prefix,
                source_path_prefix=(),
            )
    backtest_prefix = ("backtrader_runtime", "_iteration41_backtest_fixture")
    backtest_prefix_text = ".".join(backtest_prefix)
    for reviewed in inventory.iteration41_backtest_fixture_registry().registrations:
        if reviewed == registration and (
            module_name == backtest_prefix_text
            or module_name.startswith(backtest_prefix_text + ".")
        ):
            installed_package_root = Path(inventory.__file__).resolve().parent.parent
            return _InventoryRunnerBinding(
                runner_source_root=Path(inventory.PACKAGE_BACKTEST_FIXTURE_ROOT),
                backtrader_source_root=installed_package_root,
                module_prefix=backtest_prefix,
                source_path_prefix=(),
            )
    return None


def _managed_l2_required_capability_modules(
    registration: RegisteredRuntime,
) -> Tuple[str, ...]:
    """Return required imports only for the four exact reviewed managed L2 records."""

    from . import inventory

    reviewed_registrations = (
        inventory.ITERATION41_013_3_MANAGED_REPLAY_REGISTRATION,
        inventory.ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION,
        inventory.ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_REGISTRATION,
        inventory.ITERATION41_PACKAGE_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION,
    )
    if not any(registration == reviewed for reviewed in reviewed_registrations):
        return ()
    return ("bt_api_execution", "bt_api_risk", "bt_api_monitor")


def _inventory_source_root(registration: RegisteredRuntime) -> Optional[Path]:
    """Return the fixed runner-source root for legacy callers/tests."""

    binding = _inventory_runner_binding(registration)
    return None if binding is None else binding.runner_source_root


def _path_is_within(path: object, source_root: Path) -> bool:
    try:
        candidate = Path(cast(Any, path)).resolve(strict=False)
        root = source_root.resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


def _cached_backtrader_is_trusted(source_root: Path) -> bool:
    """Check every already-cached Backtrader module without evicting it."""

    for name, module in tuple(sys.modules.items()):
        if name != "backtrader" and not name.startswith("backtrader."):
            continue
        origins = []
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            origins.append(module_file)
        module_path = getattr(module, "__path__", None)
        if module_path is not None:
            origins.extend(module_path)
        if not origins or any(not _path_is_within(origin, source_root) for origin in origins):
            return False
    return True


def _has_concrete_backtrader_package(source_root: Path) -> bool:
    """Return whether this fixed source root owns a concrete core package.

    Some unit/deployment registries intentionally point the private inventory
    loader at a small runner-only source tree.  Such a tree cannot responsibly
    assert provenance for the process-wide ``backtrader`` package, so retain
    its fixed runner-file protection without applying the core import guard.
    A source root which does contain a core package must expose only concrete,
    non-link package entries before it can be used as that provenance anchor.
    """

    package_directory = source_root / "backtrader"
    try:
        package_stat = os.lstat(str(package_directory))
    except FileNotFoundError:
        return False
    except OSError:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed Backtrader package cannot be inspected"
        ) from None
    if _is_link_or_reparse(package_stat) or not stat.S_ISDIR(package_stat.st_mode):
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed Backtrader package is not a concrete directory"
        )

    initializer = package_directory / "__init__.py"
    try:
        initializer_stat = os.lstat(str(initializer))
    except FileNotFoundError:
        return False
    except OSError:
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed Backtrader package cannot be inspected"
        ) from None
    if _is_link_or_reparse(initializer_stat) or not stat.S_ISREG(initializer_stat.st_mode):
        raise _runner_error(
            "runner_origin_mismatch", "the reviewed Backtrader package initializer is invalid"
        )
    return True


@contextmanager
def _trusted_backtrader_import_context(
    source_root: Optional[Path],
) -> Generator[None, None, None]:
    """Keep legacy imports on the reviewed source tree for one runner call."""

    if source_root is None:
        yield
        return
    _trusted_runner_directory(source_root)
    if not _has_concrete_backtrader_package(source_root):
        # The fixed private runner loader still protects every ``examples``
        # source path.  Only process-wide core import provenance is absent.
        yield
        return
    if not _cached_backtrader_is_trusted(source_root):
        raise _runner_error(
            "backtrader_origin_mismatch",
            "a cached Backtrader module is outside the reviewed runner source tree",
        )
    original_sys_path = tuple(sys.path)
    try:
        sys.path.insert(0, str(source_root))
        yield
    finally:
        sys.path[:] = original_sys_path


def _install_private_namespace(package_name: str, directory: Path) -> types.ModuleType:
    """Install a namespace package that cannot collide with ``examples``."""

    package = types.ModuleType(package_name)
    package.__package__ = package_name
    package.__path__ = [str(directory)]
    specification = importlib.machinery.ModuleSpec(package_name, loader=None, is_package=True)
    specification.submodule_search_locations = [str(directory)]
    package.__spec__ = specification
    sys.modules[package_name] = package
    if "." in package_name:
        parent_name, attribute = package_name.rsplit(".", 1)
        parent = sys.modules[parent_name]
        setattr(parent, attribute, package)
    return package


class _PrivateInventoryImportlib:
    """Expose stdlib importlib while resolving one bound runner tree privately."""

    def __init__(self, loader: "_PrivateInventoryRunnerLoader") -> None:
        self._loader = loader

    def import_module(self, name: str, package: Optional[str] = None) -> types.ModuleType:
        if self._loader.is_bound_module_name(name):
            if package is not None:
                raise _runner_error(
                    "runner_origin_mismatch",
                    "the reviewed runner requested a relative public runner import",
                )
            return self._loader.load_module(name)
        return importlib.import_module(name, package)

    def __getattr__(self, name: str) -> Any:
        return getattr(importlib, name)


class _PrivateInventoryRunnerLoader:
    """Load fixed inventory source under a one-shot private namespace.

    The public source namespace is never read, modified, or evicted.  Relative
    imports resolve under this private tree. The entry runner retains its
    canonical name for internal registration comparisons; nested modules use
    their private name so classes defined there resolve through ``sys.modules``.
    """

    def __init__(
        self,
        source_root: Path,
        *,
        root_module_name: str,
        module_prefix: Tuple[str, ...] = ("examples",),
        source_path_prefix: Tuple[str, ...] = ("examples",),
    ) -> None:
        _trusted_runner_directory(source_root)
        if (
            not module_prefix
            or any(not component for component in module_prefix)
            or any(not component for component in source_path_prefix)
        ):
            raise _runner_error("runner_origin_mismatch", "the reviewed runner module is invalid")
        self.source_root = source_root
        self.module_prefix = module_prefix
        self.source_path_prefix = source_path_prefix
        if not self.is_bound_module_name(root_module_name):
            raise _runner_error("runner_origin_mismatch", "the reviewed runner module is invalid")
        self.root_module_name = root_module_name
        self.namespace = self._new_namespace()
        _install_private_namespace(self.namespace, source_root)
        self._importlib_proxy = _PrivateInventoryImportlib(self)

    @staticmethod
    def _new_namespace() -> str:
        while True:
            candidate = "_backtrader_runtime_inventory_{0}".format(
                next(_PRIVATE_NAMESPACE_SEQUENCE)
            )
            if candidate not in sys.modules:
                return candidate

    def is_bound_module_name(self, canonical_name: str) -> bool:
        components = tuple(canonical_name.split("."))
        return components[: len(self.module_prefix)] == self.module_prefix

    def _private_name(self, source_components: Tuple[str, ...]) -> str:
        return self.namespace + "." + ".".join(source_components)

    def _source_location(self, canonical_name: str) -> Tuple[Path, Path, Tuple[str, ...]]:
        components = tuple(canonical_name.split("."))
        if (
            not components
            or any(not component for component in components)
            or components[: len(self.module_prefix)] != self.module_prefix
            or len(components) == len(self.module_prefix)
        ):
            raise _runner_error("runner_origin_mismatch", "the reviewed runner module is invalid")
        source_components = self.source_path_prefix + components[len(self.module_prefix) :]
        source_directory = self.source_root
        for component in source_components[:-1]:
            source_directory = source_directory / component
            _trusted_runner_directory(source_directory)
        return (
            source_directory,
            source_directory / (source_components[-1] + ".py"),
            source_components,
        )

    def _ensure_private_parents(self, components: Tuple[str, ...]) -> None:
        source_directory = self.source_root
        package_name = self.namespace
        for component in components[:-1]:
            source_directory = source_directory / component
            package_name = package_name + "." + component
            if package_name not in sys.modules:
                _install_private_namespace(package_name, source_directory)

    def load_module(self, canonical_name: str) -> types.ModuleType:
        source_directory, source_path, source_components = self._source_location(canonical_name)
        del source_directory
        private_name = self._private_name(source_components)
        existing = sys.modules.get(private_name)
        if isinstance(existing, types.ModuleType):
            return existing
        self._ensure_private_parents(source_components)
        source = _read_trusted_runner_source(source_path)
        loader = importlib.machinery.SourceFileLoader(private_name, str(source_path))
        specification = importlib.util.spec_from_file_location(
            private_name, str(source_path), loader=loader
        )
        if specification is None or specification.origin is None:
            raise _runner_error(
                "runner_origin_mismatch", "the reviewed runner source has no fixed origin"
            )
        if os.path.normcase(os.path.abspath(specification.origin)) != os.path.normcase(
            os.path.abspath(str(source_path))
        ):
            raise _runner_error(
                "runner_origin_mismatch", "the reviewed runner origin does not match inventory"
            )
        module = importlib.util.module_from_spec(specification)
        # Keep only the entry runner's canonical spelling for narrow runtime
        # checks. A nested module's classes use __module__ during definition;
        # that name must exist in sys.modules while the class factory runs.
        module.__name__ = (
            canonical_name if canonical_name == self.root_module_name else private_name
        )
        sys.modules[private_name] = module
        try:
            code = compile(source, str(source_path), "exec")
            exec(code, module.__dict__)
        except RuntimeConfigError:
            sys.modules.pop(private_name, None)
            raise
        except Exception:
            sys.modules.pop(private_name, None)
            raise
        module.__dict__["importlib"] = self._importlib_proxy
        parent_name, attribute = private_name.rsplit(".", 1)
        setattr(sys.modules[parent_name], attribute, module)
        return module

    def close(self) -> None:
        for module_name in tuple(sys.modules):
            if module_name == self.namespace or module_name.startswith(self.namespace + "."):
                sys.modules.pop(module_name, None)


@contextmanager
def _loaded_shipped_inventory_runner(
    module_name: str,
    source_root: Path,
    *,
    module_prefix: Tuple[str, ...] = ("examples",),
    source_path_prefix: Tuple[str, ...] = ("examples",),
) -> Generator[types.ModuleType, None, None]:
    """Yield one fixed runner and remove its private namespace afterwards."""

    loader = _PrivateInventoryRunnerLoader(
        source_root,
        root_module_name=module_name,
        module_prefix=module_prefix,
        source_path_prefix=source_path_prefix,
    )
    try:
        yield loader.load_module(module_name)
    finally:
        loader.close()


@contextmanager
def _loaded_registered_runner(
    registration: RegisteredRuntime,
    *,
    runner_module: Optional[str] = None,
    source_root: Optional[Path] = None,
    module_prefix: Tuple[str, ...] = ("examples",),
    source_path_prefix: Tuple[str, ...] = ("examples",),
) -> Generator[types.ModuleType, None, None]:
    """Yield one reviewed runner without exposing inventory imports to CWD."""

    module_name = registration.runner_module if runner_module is None else runner_module
    if module_name is None:
        raise _runner_error(
            "runner_not_registered", "the registered runtime has no code-owned runner entrypoint"
        )
    if source_root is None:
        binding = _inventory_runner_binding(registration, runner_module=module_name)
        if binding is not None:
            source_root = binding.runner_source_root
            module_prefix = binding.module_prefix
            source_path_prefix = binding.source_path_prefix
    if source_root is None:
        yield importlib.import_module(module_name)
        return
    with _loaded_shipped_inventory_runner(
        module_name,
        source_root,
        module_prefix=module_prefix,
        source_path_prefix=source_path_prefix,
    ) as module:
        yield module


def dispatch_registered_runtime(
    effective: EffectiveRuntimeConfig, registry: RuntimeRegistry
) -> dict[str, Any]:
    """Run the exact code-owned entrypoint bound to a resolved runtime.

    A Windows runner receives the immutable effective config plus the same
    trusted registry while a delete-denying directory lease remains active.
    A POSIX runner receives a sealed, path-free projection and opaque registry
    token instead, together with a descriptor capability for reviewed local
    artifacts.  It must recheck strategy-specific restrictions before
    importing legacy strategy code and must not reopen ``config.yaml`` on the
    CLI dispatch path.
    """

    # This public function can receive an object constructed outside the CLI.
    # Re-resolve it against the same trusted registry *before* looking at its
    # runner module.  In particular, never let a forged ``registration`` field
    # select an import path merely because the config portion looks valid.
    # ``resolve_runner_effective_config`` validates the object identity seal
    # before it reads any public EffectiveRuntimeConfig field.
    resolved = resolve_runner_effective_config(None, registry, effective=effective)
    registration = resolved.registration
    profile = resolved.profile
    if profile is not None and resolved.mode == "live":
        # A code-owned runner path, a digest-shaped approval field, and the
        # CLI's confirmation flag do not establish provider/account admission.
        # Keep this final dispatch boundary closed until an independently
        # verified production admission can be passed and rechecked here.
        raise _runner_error(
            "live_execution_admission_required",
            "live runner dispatch requires verified production execution admission",
        )
    if profile is not None:
        if not resolved.profile_dispatch_available:
            raise _runner_error(
                "profile_dispatch_unavailable",
                "the selected profile is outside the offline runner dispatch contract",
            )
        module_name = profile.runner_module
        entrypoint = profile.runner_entrypoint
        capability_modules = profile.capability_modules
        required_capability_modules: Tuple[str, ...] = ()
    else:
        module_name = registration.runner_module
        entrypoint = registration.runner_entrypoint
        capability_modules = registration.capability_modules
        required_capability_modules = _managed_l2_required_capability_modules(registration)
    if module_name is None:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the registered runtime has no code-owned runner entrypoint",
            field_path="runtime.runner",
            reason="runner_not_registered",
        )
    if resolved.mode == "live":
        # Preserve the historical registration diagnostic ordering: an
        # unbound legacy runner is reported before the live admission gate.
        raise _runner_error(
            "live_execution_admission_required",
            "live runner dispatch requires verified production execution admission",
        )
    with registry.verified_runtime_directory(registration) as directory_fd:
        runtime_directory: Optional[RuntimeDirectoryCapability] = None
        if directory_fd is not None:
            runtime_directory = RuntimeDirectoryCapability(directory_fd)
        elif os.name == "posix":
            # A POSIX runner must never fall back to a mutable pathname.  If a
            # platform cannot supply the descriptor opened by the registry,
            # reject before runner import or local side effects instead.
            raise _runner_error(
                "runtime_directory_capability_unavailable",
                "the POSIX runtime-directory capability is unavailable",
            )
        runner_started = False
        try:
            binding = _inventory_runner_binding(registration, runner_module=module_name)
            runner_source_root = None if binding is None else binding.runner_source_root
            backtrader_source_root = None if binding is None else binding.backtrader_source_root
            module_prefix = ("examples",) if binding is None else binding.module_prefix
            source_path_prefix = ("examples",) if binding is None else binding.source_path_prefix
            if required_capability_modules:
                if runner_source_root is None:
                    raise _runner_error(
                        "runner_not_registered",
                        "the managed replay route has no reviewed runner source binding",
                    )
                missing_module = first_unavailable_trusted_capability_module(
                    runner_source_root,
                    registration.capability_modules,
                    required_capability_modules,
                )
                if missing_module is not None:
                    raise RuntimeConfigError(
                        PRESET_POLICY_VIOLATION,
                        "the managed replay requires local capability module '{0}'; install the "
                        "reviewed SDK dependency in the bt-runtime environment, then rerun this "
                        "registered command".format(missing_module),
                        field_path="runtime.capabilities.{0}".format(missing_module),
                        reason="capability_dependency_missing",
                    )
            with _trusted_backtrader_import_context(
                backtrader_source_root
            ), trusted_capability_import_context(
                backtrader_source_root, capability_modules
            ), _loaded_registered_runner(
                registration,
                runner_module=module_name,
                source_root=runner_source_root,
                module_prefix=module_prefix,
                source_path_prefix=source_path_prefix,
            ) as module:
                runner = getattr(module, entrypoint, None)
                if not callable(runner):
                    raise RuntimeConfigError(
                        PRESET_POLICY_VIOLATION,
                        "the registered runtime runner has no callable entrypoint",
                        field_path="runtime.runner",
                        reason="runner_entrypoint_missing",
                    )
                runner_started = True
                if runtime_directory is None:
                    # Windows holds a delete-denying lease for the full call.
                    # Preserve the established pathname runner interface there.
                    report = runner(registration.runtime_dir, effective=resolved, registry=registry)
                else:
                    # An open POSIX directory does not stop rename(2).  Do not
                    # disclose a pathname that could subsequently resolve to a
                    # replacement directory.  The runner-facing effective
                    # config and registry are path-free views as well; a
                    # reviewed runner must use the explicit capability for
                    # runtime-relative local I/O.
                    with _runner_dispatch_views(resolved) as (
                        runner_effective,
                        runner_registry,
                    ):
                        if _runner_accepts_runtime_directory_capability(runner):
                            report = runner(
                                None,
                                effective=runner_effective,
                                registry=runner_registry,
                                runtime_directory=runtime_directory,
                            )
                        else:
                            report = runner(
                                None,
                                effective=runner_effective,
                                registry=runner_registry,
                            )
        except RuntimeConfigError:
            raise
        except Exception as error:
            reason = "runner_execution_failed" if runner_started else "runner_import_failed"
            message = (
                "the registered runtime runner did not complete safely"
                if runner_started
                else "the registered runtime runner is unavailable"
            )
            # The private namespace context has already restored its own
            # modules before this public error is emitted.
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                message,
                field_path="runtime.runner",
                reason=reason,
            ) from error
        finally:
            if runtime_directory is not None:
                runtime_directory.invalidate()
    if not isinstance(report, Mapping):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the registered runtime runner returned an invalid report",
            field_path="runtime.runner",
            reason="runner_report_invalid",
        )
    return dict(report)


__all__ = [
    "dispatch_configured_runtime",
    "dispatch_registered_runtime",
    "resolve_runner_effective_config",
]
