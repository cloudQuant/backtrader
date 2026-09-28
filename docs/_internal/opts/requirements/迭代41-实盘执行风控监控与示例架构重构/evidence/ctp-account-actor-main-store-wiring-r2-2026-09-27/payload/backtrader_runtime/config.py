"""Strict, side-effect-free schema-v4 runtime configuration loading.

Only filesystem and YAML parsing occur in this module.  It intentionally does
not import Backtrader strategy modules or any optional live-trading package,
which makes invalid configuration a proven zero-provider-I/O path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, Optional, Tuple, Union
from urllib.parse import urlsplit

from .errors import (
    CONFIG_EXISTS,
    CONFIG_REQUIRED,
    CONFIG_SCHEMA_UNSUPPORTED,
    MODE_PRESET_MISMATCH,
    PRESET_POLICY_VIOLATION,
    RuntimeConfigError,
)
from .policy import get_preset_policy


CONFIG_FILENAME = "config.yaml"
CONFIG_SCHEMA_VERSION = 4
MAX_CONFIG_BYTES = 1024 * 1024
CTP_PRODUCTION_RUNTIME_DIR = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "007_ctp"
    / "runtime-production"
)

_STRATEGY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OS_SECRET_REF_RE = re.compile(r"^os_secret_store:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ROOT_FIELDS = frozenset(
    (
        "config_schema_version",
        "strategy",
        "runtime",
        "parameters",
        "secrets_ref",
        "ctp",
        "ctp_simnow",
        "ctp_production",
    )
)
_CTP_SIMNOW_FIELDS = frozenset(
    (
        "front_pairs",
        "md_front",
        "td_front",
        "instrument_id",
        "exchange_id",
        "hedge_flag",
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
    )
)
_CTP_SIMNOW_FRONT_PAIR_FIELDS = frozenset(("md_front", "td_front"))
_MAX_CTP_SIMNOW_FRONT_PAIRS = 8
_CTP_PRODUCTION_FIELDS = frozenset(
    (
        "front_pairs",
        "md_front",
        "td_front",
        "instrument_id",
        "exchange_id",
        "hedge_flag",
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
    )
)
_CTP_PRODUCTION_FRONT_PAIR_FIELDS = frozenset(("md_front", "td_front"))
_MAX_CTP_PRODUCTION_FRONT_PAIRS = 8
_CTP_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CTP_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CTP_EXCHANGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CTP_CALENDAR_PATH_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STRATEGY_FIELDS = frozenset(("id",))
_RUNTIME_FIELDS = frozenset(("mode", "preset"))
_INLINE_SECRET_NAMES = frozenset(
    (
        "api_key",
        "apikey",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passphrase",
        "private_key",
        "secret",
        "token",
    )
)
_FORBIDDEN_CONTROL_FIELDS = frozenset(
    (
        "account_access",
        "approval",
        "approval_ref",
        "capabilities",
        "capability",
        "capability_module",
        "capability_modules",
        "connection",
        "enabled",
        "environment",
        "mode",
        "modules",
        "order_route",
        "plugins",
        "preset",
        "provider",
        "receipt",
        "route",
        "runtime",
        "write_policy",
        "zmq",
    )
)


class _DuplicateYamlKeyError(ValueError):
    """Raised internally when a strict YAML mapping repeats a key."""

    def __init__(self, key: object) -> None:
        self.key = str(key)
        super().__init__(self.key)


class _YamlAliasError(ValueError):
    """Raised internally for aliases/anchors, which are not part of v4."""


@dataclass(frozen=True)
class CtpSimNowPrivateConfig:
    """Validated CTP SimNow settings retained only for the private resolver.

    Every field is excluded from the generated representation because even
    account identifiers and connection settings belong to the private block.
    Generic dataclass serialization such as ``dataclasses.asdict`` still reads
    these fields; diagnostics must use ``RuntimeConfig.as_public_dict``.
    """

    # The legacy single-front selector fields are retained for source
    # compatibility. They are None for a multi-pair config so consumers cannot
    # accidentally treat the first pair as an implicit selection.
    md_front: Optional[str] = field(repr=False)
    td_front: Optional[str] = field(repr=False)
    front_pairs: Tuple[Mapping[str, str], ...] = field(repr=False)
    instrument_id: str = field(repr=False)
    exchange_id: str = field(repr=False)
    hedge_flag: str = field(repr=False)
    broker_id: str = field(repr=False)
    user_id: str = field(repr=False)
    password: str = field(repr=False)
    app_id: str = field(repr=False)
    auth_code: str = field(repr=False)

    def __repr__(self) -> str:
        return "CtpSimNowPrivateConfig(<redacted>)"

    def _private_facts(self) -> Tuple[Any, ...]:
        """Return internal facts for the loader provenance seal only."""

        return (
            self.md_front,
            self.td_front,
            tuple((pair["md_front"], pair["td_front"]) for pair in self.front_pairs),
            self.instrument_id,
            self.exchange_id,
            self.hedge_flag,
            self.broker_id,
            self.user_id,
            self.password,
            self.app_id,
            self.auth_code,
        )


# The canonical mode-neutral schema has the same private value shape as the
# historical SimNow parser.  Keeping one exact class preserves existing
# consumers that deliberately check ``type(value) is CtpSimNowPrivateConfig``.
CtpPrivateConfig = CtpSimNowPrivateConfig


@dataclass(frozen=True)
class CtpProductionPrivateConfig:
    """Private CTP production endpoint selectors and credentials from protected YAML.

    Explicitly configured fronts are retained as parser-only candidate
    metadata. A front_pairs list is never selected here. Parsing grants no
    route, trusted environment, receipt, approval, or provider access.
    """

    # Multi-pair input stays unresolved at this parser boundary. The scalar
    # compatibility fields are None whenever front_pairs was supplied, so a
    # later consumer cannot accidentally treat the first configured pair as
    # an operator-approved selection.
    md_front: Optional[str] = field(repr=False)
    td_front: Optional[str] = field(repr=False)
    front_pairs: Tuple[Mapping[str, str], ...] = field(repr=False)
    instrument_id: str = field(repr=False)
    exchange_id: str = field(repr=False)
    hedge_flag: str = field(repr=False)
    broker_id: str = field(repr=False)
    user_id: str = field(repr=False)
    password: str = field(repr=False)
    app_id: str = field(repr=False)
    auth_code: str = field(repr=False)

    def __repr__(self) -> str:
        return "CtpProductionPrivateConfig(<redacted>)"

    def _private_facts(self) -> Tuple[Any, ...]:
        """Return private fields only for the in-process loader seal."""

        return (
            self.md_front,
            self.td_front,
            tuple((pair["md_front"], pair["td_front"]) for pair in self.front_pairs),
            self.instrument_id,
            self.exchange_id,
            self.hedge_flag,
            self.broker_id,
            self.user_id,
            self.password,
            self.app_id,
            self.auth_code,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    """An immutable, parsed user configuration before registry resolution.

    Use :meth:`as_public_dict` for diagnostics. Generic dataclass serializers
    can expose the private CTP configuration fields.
    """

    strategy_dir: Path
    source_path: Path
    strategy_id: str
    mode: str
    preset: str
    parameters: Mapping[str, Any]
    secrets_ref: str
    config_digest: str
    ctp: Optional[CtpPrivateConfig] = field(default=None, repr=False)
    ctp_simnow: Optional[CtpSimNowPrivateConfig] = field(default=None, repr=False)
    ctp_production: Optional[CtpProductionPrivateConfig] = field(default=None, repr=False)
    _source_file_identity: Optional[Tuple[int, int]] = field(
        default=None, repr=False, compare=False
    )

    def as_public_dict(self) -> Dict[str, Any]:
        """Return a redacted summary safe for diagnostics and audit events."""

        return {
            "strategy": {"id": self.strategy_id},
            "runtime": {"mode": self.mode, "preset": self.preset},
            "parameter_keys": tuple(sorted(self.parameters)),
            "secrets_ref": "none" if self.secrets_ref == "none" else "configured",
            "config_digest": self.config_digest,
        }

    def parameter_dict(self) -> Dict[str, Any]:
        """Return a detached, JSON-safe copy of registered strategy parameters."""

        return _thaw_value(self.parameters)


@dataclass(frozen=True)
class _LoadedRuntimeConfigSeal:
    """Private identity/snapshot retained only for loader-produced configs."""

    registry: Optional[Any]
    strategy_dir: Path
    source_path: Path
    strategy_id: str
    mode: str
    preset: str
    parameters: Mapping[str, Any]
    secrets_ref: str
    config_digest: str
    ctp: Optional[CtpPrivateConfig]
    ctp_private_digest: Optional[str]
    ctp_simnow: Optional[CtpSimNowPrivateConfig]
    ctp_simnow_private_digest: Optional[str]
    ctp_production: Optional[CtpProductionPrivateConfig]
    ctp_production_private_digest: Optional[str]
    source_file_identity: Optional[Tuple[int, int]]


# ``RuntimeConfig`` intentionally remains a public, ergonomic frozen data
# class.  A public field cannot prove it came from config.yaml, so loader
# provenance lives in this private identity registry rather than on the data
# object.  The weak reference prevents stale id entries from authorising a
# later object which happens to reuse the same memory address.
_LOADED_RUNTIME_CONFIG_SEALS: Dict[int, Tuple[Any, _LoadedRuntimeConfigSeal]] = {}


def _seal_loaded_runtime_config(
    config: RuntimeConfig, registry: Optional[Any] = None
) -> RuntimeConfig:
    """Register a config that was parsed from one verified config.yaml FD."""

    identifier = id(config)

    def discard(reference: Any) -> None:
        current = _LOADED_RUNTIME_CONFIG_SEALS.get(identifier)
        if current is not None and current[0] is reference:
            _LOADED_RUNTIME_CONFIG_SEALS.pop(identifier, None)

    reference = weakref.ref(config, discard)
    _LOADED_RUNTIME_CONFIG_SEALS[identifier] = (
        reference,
        _LoadedRuntimeConfigSeal(
            registry=registry,
            strategy_dir=config.strategy_dir,
            source_path=config.source_path,
            strategy_id=config.strategy_id,
            mode=config.mode,
            preset=config.preset,
            parameters=config.parameters,
            secrets_ref=config.secrets_ref,
            config_digest=config.config_digest,
            ctp=config.ctp,
            ctp_private_digest=_digest_private_ctp_config(config.ctp),
            ctp_simnow=config.ctp_simnow,
            ctp_simnow_private_digest=_digest_private_ctp_config(config.ctp_simnow),
            ctp_production=config.ctp_production,
            ctp_production_private_digest=_digest_private_ctp_production_config(
                config.ctp_production
            ),
            source_file_identity=config._source_file_identity,
        ),
    )
    return config


def require_loaded_runtime_config_seal(
    config: RuntimeConfig, registry: Optional[Any] = None
) -> None:
    """Reject public/manual or cross-registry config objects before execution."""

    entry = _LOADED_RUNTIME_CONFIG_SEALS.get(id(config))
    if entry is None or entry[0]() is not config:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "runtime configuration was not loaded from a verified config.yaml",
            field_path="runtime.config",
            reason="config_provenance_invalid",
        )
    seal = entry[1]
    if (
        (seal.registry is not None and seal.registry is not registry)
        or config.strategy_dir != seal.strategy_dir
        or config.source_path != seal.source_path
        or config.strategy_id != seal.strategy_id
        or config.mode != seal.mode
        or config.preset != seal.preset
        or config.parameters is not seal.parameters
        or config.secrets_ref != seal.secrets_ref
        or config.config_digest != seal.config_digest
        or config.ctp is not seal.ctp
        or _digest_private_ctp_config(config.ctp) != seal.ctp_private_digest
        or config.ctp_simnow is not seal.ctp_simnow
        or _digest_private_ctp_config(config.ctp_simnow) != seal.ctp_simnow_private_digest
        or config.ctp_production is not seal.ctp_production
        or _digest_private_ctp_production_config(config.ctp_production)
        != seal.ctp_production_private_digest
        or config._source_file_identity != seal.source_file_identity
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "runtime configuration no longer matches its verified config.yaml",
            field_path="runtime.config",
            reason="config_provenance_invalid",
        )


def _config_error(message: str, field_path: Optional[str], reason: str) -> RuntimeConfigError:
    return RuntimeConfigError(
        CONFIG_SCHEMA_UNSUPPORTED,
        message,
        field_path=field_path,
        reason=reason,
    )


def _normalise_runtime_dir(strategy_dir: Union[str, os.PathLike]) -> Path:
    try:
        return Path(strategy_dir).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "strategy runtime directory is not usable",
            field_path="strategy_dir",
            reason="invalid_runtime_directory",
        ) from None


def _is_ctp_production_runtime_dir(strategy_dir: Union[str, os.PathLike]) -> bool:
    """Match only the reserved production runtime's canonical directory."""

    try:
        candidate = _normalise_runtime_dir(strategy_dir)
        expected = _normalise_runtime_dir(CTP_PRODUCTION_RUNTIME_DIR)
    except RuntimeConfigError:
        return False
    return os.path.normcase(os.fspath(candidate)) == os.path.normcase(os.fspath(expected))


def _read_config_text(
    strategy_dir: Path,
    *,
    directory_fd: Optional[int] = None,
    identity_out: Optional[list] = None,
    require_private_config_security: bool = False,
    directory_identity: Optional[Any] = None,
) -> Tuple[Path, str]:
    """Read one regular config file through a verified file descriptor.

    The config path is an authorization boundary.  Checking ``Path.is_file``
    and then reopening the pathname lets a concurrent replacement change the
    bytes which are actually parsed.  Keep the descriptor that was checked,
    parse only its bytes, and verify its identity against ``lstat`` before and
    after the read.  ``O_NOFOLLOW`` closes the symlink race on platforms that
    expose it; the identity checks retain a fail-closed fallback elsewhere.
    """

    config_path = strategy_dir / CONFIG_FILENAME
    config_target: Union[str, Path] = CONFIG_FILENAME if directory_fd is not None else config_path
    try:
        if directory_fd is None:
            path_stat = os.lstat(str(config_target))
        else:
            path_stat = os.lstat(str(config_target), dir_fd=directory_fd)
    except FileNotFoundError:
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "required config.yaml is missing from the registered runtime directory",
            field_path=CONFIG_FILENAME,
            reason="missing_config",
        ) from None
    except OSError:
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "config.yaml cannot be opened",
            field_path=CONFIG_FILENAME,
            reason="config_unreadable",
        ) from None

    if stat.S_ISLNK(path_stat.st_mode):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "config.yaml must not be a symbolic link",
            field_path=CONFIG_FILENAME,
            reason="config_symlink_not_allowed",
        )
    if not stat.S_ISREG(path_stat.st_mode):
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "config.yaml must be a regular file",
            field_path=CONFIG_FILENAME,
            reason="config_not_regular_file",
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        if directory_fd is None:
            descriptor = os.open(str(config_target), flags)
        else:
            descriptor = os.open(str(config_target), flags, dir_fd=directory_fd)
    except FileNotFoundError:
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "required config.yaml is missing from the registered runtime directory",
            field_path=CONFIG_FILENAME,
            reason="missing_config",
        ) from None
    except OSError:
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "config.yaml cannot be opened",
            field_path=CONFIG_FILENAME,
            reason="config_unreadable",
        ) from None

    try:
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_stat.st_mode):
            raise RuntimeConfigError(
                CONFIG_REQUIRED,
                "config.yaml must be a regular file",
                field_path=CONFIG_FILENAME,
                reason="config_not_regular_file",
            )
        if (path_stat.st_dev, path_stat.st_ino) != (descriptor_stat.st_dev, descriptor_stat.st_ino):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "config.yaml changed while it was being opened",
                field_path=CONFIG_FILENAME,
                reason="config_identity_changed",
            )

        if require_private_config_security:
            _require_private_config_security(
                strategy_dir,
                descriptor,
                descriptor_stat,
                directory_fd=directory_fd,
                directory_identity=directory_identity,
            )

        chunks = []
        remaining = MAX_CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if require_private_config_security:
            final_descriptor_stat = os.fstat(descriptor)
            if (final_descriptor_stat.st_dev, final_descriptor_stat.st_ino) != (
                descriptor_stat.st_dev,
                descriptor_stat.st_ino,
            ):
                raise _private_config_security_error("private_config_identity_changed")
            _require_single_config_link(getattr(final_descriptor_stat, "st_nlink", None))
            _require_private_config_security(
                strategy_dir,
                descriptor,
                final_descriptor_stat,
                directory_fd=directory_fd,
                directory_identity=directory_identity,
            )
    except RuntimeConfigError:
        raise
    except OSError:
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "config.yaml cannot be opened",
            field_path=CONFIG_FILENAME,
            reason="config_unreadable",
        ) from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    try:
        if directory_fd is None:
            final_path_stat = os.lstat(str(config_target))
        else:
            final_path_stat = os.lstat(str(config_target), dir_fd=directory_fd)
    except OSError:
        final_path_stat = None
    if (
        final_path_stat is None
        or stat.S_ISLNK(final_path_stat.st_mode)
        or not stat.S_ISREG(final_path_stat.st_mode)
        or (final_path_stat.st_dev, final_path_stat.st_ino)
        != (descriptor_stat.st_dev, descriptor_stat.st_ino)
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "config.yaml changed while it was being read",
            field_path=CONFIG_FILENAME,
            reason="config_identity_changed",
        )
    if require_private_config_security:
        _require_single_config_link(getattr(final_path_stat, "st_nlink", None))

    if identity_out is not None:
        identity_out.append((descriptor_stat.st_dev, descriptor_stat.st_ino))

    if len(raw) > MAX_CONFIG_BYTES:
        raise _config_error(
            "config.yaml exceeds the maximum supported size",
            CONFIG_FILENAME,
            "config_too_large",
        )
    try:
        # The canonical runtime directory was resolved before registry lookup.
        # Avoid resolving the leaf pathname again: that would reopen the race
        # which the descriptor and identity checks above just closed.
        return config_path, raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _config_error(
            "config.yaml must be UTF-8 text",
            CONFIG_FILENAME,
            "invalid_encoding",
        ) from None
    except (OSError, RuntimeError):
        raise RuntimeConfigError(
            CONFIG_REQUIRED,
            "config.yaml cannot be resolved",
            field_path=CONFIG_FILENAME,
            reason="config_unreadable",
        ) from None


def _private_config_security_error(reason: str) -> RuntimeConfigError:
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "config.yaml permissions do not protect private CTP credentials",
        field_path=CONFIG_FILENAME,
        reason=reason,
    )


def _require_private_config_security(
    strategy_dir: Path,
    config_descriptor: int,
    config_stat: os.stat_result,
    *,
    directory_fd: Optional[int],
    directory_identity: Optional[Any],
) -> None:
    """Check private config access before reading any config bytes.

    This gate is selected from the code-owned registration's allowed secret
    refs, before the YAML is parsed. POSIX uses the already-open directory and
    config descriptors. Windows checks the already-open config handle and a
    separate directory metadata handle while the registry lease is held.
    """

    if directory_identity is None:
        raise _private_config_security_error("private_config_identity_unavailable")
    _require_single_config_link(getattr(config_stat, "st_nlink", None))

    if os.name == "posix":
        if directory_fd is None or not hasattr(os, "geteuid"):
            raise _private_config_security_error("private_config_posix_security_unavailable")
        directory_stat = os.fstat(directory_fd)
        uid = os.geteuid()
        directory_mode = stat.S_IMODE(directory_stat.st_mode)
        file_mode = stat.S_IMODE(config_stat.st_mode)
        if (
            not directory_identity.matches(directory_stat)
            or directory_stat.st_uid != uid
            or directory_mode & ~0o700
            or directory_mode & 0o500 != 0o500
        ):
            raise _private_config_security_error("private_config_directory_unsafe")
        if (
            not stat.S_ISREG(config_stat.st_mode)
            or config_stat.st_uid != uid
            or file_mode & ~0o600
            or file_mode & stat.S_IRUSR == 0
        ):
            raise _private_config_security_error("private_config_file_unsafe")
        return

    if os.name == "nt":
        try:
            from .credential_resolver import (
                CredentialResolutionError,
                _open_windows_metadata_handle,
                _windows_acl_for_handle,
                _windows_os_handle,
            )

            directory_path = strategy_dir
            directory_fd_for_acl = _open_windows_metadata_handle(directory_path, is_directory=True)
            try:
                opened_directory = os.fstat(directory_fd_for_acl)
                if not directory_identity.matches(opened_directory):
                    raise _private_config_security_error(
                        "private_config_directory_identity_changed"
                    )
                _windows_acl_for_handle(_windows_os_handle(directory_fd_for_acl))
            finally:
                os.close(directory_fd_for_acl)
            _windows_acl_for_handle(_windows_os_handle(config_descriptor))
            return
        except CredentialResolutionError as error:
            raise _private_config_security_error(
                "private_config_windows_acl_invalid"
                if error.reason and "invalid" in error.reason
                else "private_config_windows_acl_unavailable"
            ) from None
        except RuntimeConfigError as error:
            raise _private_config_security_error(
                error.reason or "private_config_windows_acl_invalid"
            ) from None
        except Exception:
            raise _private_config_security_error("private_config_windows_acl_unavailable") from None

    raise _private_config_security_error("private_config_platform_unsupported")


def _require_single_config_link(link_count: Any) -> None:
    """Reject private config leaves that have another hard-link name."""

    if type(link_count) is not int or link_count != 1:
        raise _private_config_security_error("private_config_hardlink_not_allowed")


def _load_strict_yaml(text: str) -> Any:
    """Load YAML without aliases, dynamic tags, or duplicate mapping keys."""

    try:
        import yaml
    except ImportError:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the required YAML parser is not installed",
            field_path=CONFIG_FILENAME,
            reason="yaml_dependency_missing",
        ) from None

    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None):
                raise _YamlAliasError()

        def validate_mapping_nodes(node: Any, field_path: str) -> None:
            if isinstance(node, yaml.nodes.MappingNode):
                seen = set()
                for key_node, value_node in node.value:
                    if (
                        not isinstance(key_node, yaml.nodes.ScalarNode)
                        or key_node.tag != "tag:yaml.org,2002:str"
                    ):
                        raise _config_error(
                            "configuration mapping keys must be strings",
                            field_path or CONFIG_FILENAME,
                            "non_string_mapping_key",
                        )
                    key = key_node.value
                    child_path = key if not field_path else "{0}.{1}".format(field_path, key)
                    if key in seen:
                        raise _DuplicateYamlKeyError(child_path)
                    seen.add(key)
                    validate_mapping_nodes(value_node, child_path)
            elif isinstance(node, yaml.nodes.SequenceNode):
                for index, item in enumerate(node.value):
                    validate_mapping_nodes(item, "{0}[{1}]".format(field_path, index))

        document = yaml.compose(text, Loader=yaml.SafeLoader)
        if document is not None:
            validate_mapping_nodes(document, "")

        class StrictSafeLoader(yaml.SafeLoader):
            pass

        def construct_mapping(loader: Any, node: Any, deep: bool = False) -> Dict[str, Any]:
            mapping: Dict[str, Any] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if not isinstance(key, str):
                    raise _config_error(
                        "configuration mapping keys must be strings",
                        CONFIG_FILENAME,
                        "non_string_mapping_key",
                    )
                if key in mapping:
                    raise _DuplicateYamlKeyError(key)
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        StrictSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping,
        )
        return yaml.load(text, Loader=StrictSafeLoader)
    except RuntimeConfigError:
        raise
    except _DuplicateYamlKeyError as exc:
        field_path = (
            "ctp"
            if exc.key == "ctp" or exc.key.startswith("ctp.")
            else "ctp_simnow"
            if exc.key == "ctp_simnow" or exc.key.startswith("ctp_simnow.")
            else "ctp_production"
            if exc.key == "ctp_production" or exc.key.startswith("ctp_production.")
            else exc.key
        )
        raise _config_error(
            "config.yaml contains a duplicate field",
            field_path,
            "duplicate_field",
        ) from None
    except _YamlAliasError:
        raise _config_error(
            "config.yaml must not use YAML aliases or anchors",
            CONFIG_FILENAME,
            "yaml_alias_not_allowed",
        ) from None
    except Exception:
        # Parser errors can reproduce raw source lines.  Do not expose them in
        # operator output because a malformed file could contain a secret.
        raise _config_error(
            "config.yaml is not a supported strict YAML document",
            CONFIG_FILENAME,
            "invalid_yaml",
        ) from None


def _require_mapping(value: Any, field_path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _config_error(
            "{0} must be a mapping".format(field_path),
            field_path,
            "expected_mapping",
        )
    return value


def _reject_unknown_fields(
    mapping: Dict[str, Any], allowed: Iterable[str], field_path: str
) -> None:
    allowed_fields = frozenset(allowed)
    for key in mapping:
        if key not in allowed_fields:
            path = key if not field_path else "{0}.{1}".format(field_path, key)
            if field_path in ("ctp", "ctp_simnow", "ctp_production"):
                path = field_path
            raise _config_error(
                "configuration field is not allowed by schema v4",
                path,
                "field_not_allowed",
            )


def _require_field(mapping: Dict[str, Any], key: str, field_path: str) -> Any:
    if key not in mapping:
        path = key if not field_path else "{0}.{1}".format(field_path, key)
        raise _config_error(
            "required configuration field is missing",
            path,
            "required_field_missing",
        )
    return mapping[key]


def _normalise_value(value: Any, field_path: str) -> Any:
    """Convert YAML values into a finite JSON-compatible tree."""

    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and "${" in value:
            raise _config_error(
                "environment interpolation is not supported in config.yaml",
                field_path,
                "environment_interpolation_not_allowed",
            )
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _config_error(
                "configuration numbers must be finite",
                field_path,
                "non_finite_number",
            )
        return value
    if isinstance(value, list):
        return [
            _normalise_value(item, "{0}[{1}]".format(field_path, index))
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        normalised: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _config_error(
                    "configuration mapping keys must be strings",
                    field_path,
                    "non_string_mapping_key",
                )
            child_path = "{0}.{1}".format(field_path, key)
            normalised[key] = _normalise_value(item, child_path)
        return normalised
    raise _config_error(
        "configuration values must be JSON-compatible scalars, lists, or mappings",
        field_path,
        "unsupported_value_type",
    )


def _forbidden_name(name: str) -> bool:
    normalised = name.casefold().replace("-", "_")
    if normalised in _INLINE_SECRET_NAMES or normalised in _FORBIDDEN_CONTROL_FIELDS:
        return True
    return normalised.endswith(("_token", "_password", "_passphrase", "_private_key", "_secret"))


def _reject_inline_secrets_and_controls(value: Any, field_path: str) -> None:
    if not isinstance(value, dict):
        if isinstance(value, list):
            for index, item in enumerate(value):
                _reject_inline_secrets_and_controls(item, "{0}[{1}]".format(field_path, index))
        return

    for key, item in value.items():
        child_path = "{0}.{1}".format(field_path, key)
        normalised = key.casefold().replace("-", "_")
        if normalised in _INLINE_SECRET_NAMES or normalised.endswith(
            ("_token", "_password", "_passphrase", "_private_key", "_secret")
        ):
            raise _config_error(
                "inline credentials are not allowed in config.yaml",
                child_path,
                "inline_secret",
            )
        if normalised in _FORBIDDEN_CONTROL_FIELDS:
            raise _config_error(
                "runtime control fields are not allowed in parameters",
                child_path,
                "runtime_control_field_not_allowed",
            )
        _reject_inline_secrets_and_controls(item, child_path)


def _digest_private_ctp_config(value: Optional[CtpSimNowPrivateConfig]) -> Optional[str]:
    """Fingerprint private fields for the in-process config provenance seal.

    This digest is never included in ``config_digest`` or a public projection.
    Keeping it in the identity seal lets later gates detect illicit mutation of
    a frozen credential object without publishing a low-entropy password hash.
    """

    if value is None:
        return None
    serialized = json.dumps(value._private_facts(), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _digest_private_ctp_production_config(
    value: Optional[CtpProductionPrivateConfig],
) -> Optional[str]:
    """Fingerprint private production fields for the local provenance seal."""

    if value is None:
        return None
    serialized = json.dumps(value._private_facts(), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _required_private_string(
    mapping: Dict[str, Any],
    key: str,
    *,
    secret: bool = False,
    field_prefix: str = "ctp_simnow",
) -> str:
    reason_prefix = field_prefix.split(".", 1)[0]
    value = _require_field(mapping, key, field_prefix)
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _config_error(
            "{0}.{1} must be a non-empty string".format(field_prefix, key),
            "{0}.{1}".format(field_prefix, key),
            "invalid_{0}_value".format(reason_prefix),
        )
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        size = MAX_CONFIG_BYTES + 1
    if size > (2048 if secret else 128):
        raise _config_error(
            "{0}.{1} exceeds the supported size".format(field_prefix, key),
            "{0}.{1}".format(field_prefix, key),
            "invalid_{0}_value".format(reason_prefix),
        )
    return value


def _required_ctp_front(
    mapping: Dict[str, Any], key: str, *, field_prefix: str = "ctp_simnow"
) -> str:
    """Parse one bounded, explicit TCP front without importing the SDK."""

    reason_prefix = field_prefix.split(".", 1)[0]
    value = _required_private_string(mapping, key, field_prefix=field_prefix)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        port = None
        parsed = None
    if (
        parsed is None
        or parsed.scheme != "tcp"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(character.isspace() or ord(character) < 0x20 for character in value)
        or value != "tcp://{0}:{1}".format(parsed.hostname, port)
    ):
        raise _config_error(
            "{0}.{1} must be a canonical tcp://host:port front".format(field_prefix, key),
            "{0}.{1}".format(field_prefix, key),
            "invalid_{0}_front".format(reason_prefix),
        )
    return value


def _parse_ctp_private_config(
    value: Any, *, field_prefix: str = "ctp"
) -> CtpPrivateConfig:
    """Parse the shared private CTP fields without selecting a front pair."""

    block_name = field_prefix
    mapping = _require_mapping(value, block_name)
    _reject_unknown_fields(mapping, _CTP_SIMNOW_FIELDS, block_name)
    normalized = _normalise_value(mapping, block_name)
    # Required lookups and type/format checks intentionally use stable field
    # paths and never echo malformed values into CLI errors.
    has_front_pairs = "front_pairs" in normalized
    has_legacy_fronts = "md_front" in normalized or "td_front" in normalized
    if has_front_pairs and has_legacy_fronts:
        raise _config_error(
            "{0} must use either front_pairs or the legacy md_front/td_front pair".format(
                block_name
            ),
            "{0}.front_pairs".format(block_name),
            "mixed_{0}_front_forms".format(block_name),
        )
    if has_front_pairs:
        raw_pairs = normalized["front_pairs"]
        if type(raw_pairs) is not list or not 1 <= len(raw_pairs) <= _MAX_CTP_SIMNOW_FRONT_PAIRS:
            raise _config_error(
                "{0}.front_pairs must contain between 1 and {1} pairs".format(
                    block_name, _MAX_CTP_SIMNOW_FRONT_PAIRS
                ),
                "{0}.front_pairs".format(block_name),
                "invalid_{0}_front_pairs".format(block_name),
            )
        parsed_pairs = []
        seen_pairs = set()
        for index, raw_pair in enumerate(raw_pairs):
            pair_path = "{0}.front_pairs[{1}]".format(block_name, index)
            pair_mapping = _require_mapping(raw_pair, pair_path)
            _reject_unknown_fields(pair_mapping, _CTP_SIMNOW_FRONT_PAIR_FIELDS, pair_path)
            md_front_value = _required_ctp_front(
                pair_mapping, "md_front", field_prefix=pair_path
            )
            td_front_value = _required_ctp_front(
                pair_mapping, "td_front", field_prefix=pair_path
            )
            pair_key = (md_front_value, td_front_value)
            if pair_key in seen_pairs:
                raise _config_error(
                    "{0}.front_pairs must not repeat an exact pair".format(block_name),
                    pair_path,
                    "duplicate_{0}_front_pair".format(block_name),
                )
            seen_pairs.add(pair_key)
            parsed_pairs.append(
                MappingProxyType(
                    {"md_front": md_front_value, "td_front": td_front_value}
                )
            )
        md_front = None
        td_front = None
        front_pairs = tuple(parsed_pairs)
    else:
        md_front = _required_ctp_front(
            normalized, "md_front", field_prefix=block_name
        )
        td_front = _required_ctp_front(
            normalized, "td_front", field_prefix=block_name
        )
        front_pairs = (MappingProxyType({"md_front": md_front, "td_front": td_front}),)
    def required(key: str, *, secret: bool = False) -> str:
        return _required_private_string(
            normalized, key, secret=secret, field_prefix=block_name
        )

    instrument_id = required("instrument_id")
    exchange_id = required("exchange_id")
    hedge_flag = required("hedge_flag")
    broker_id = required("broker_id", secret=True)
    user_id = required("user_id", secret=True)
    password = required("password", secret=True)
    app_id = required("app_id", secret=True)
    auth_code = required("auth_code", secret=True)

    if not _CTP_INSTRUMENT_RE.fullmatch(instrument_id):
        raise _config_error(
            "{0}.instrument_id is not a supported identifier".format(block_name),
            "{0}.instrument_id".format(block_name),
            "invalid_{0}_value".format(block_name),
        )
    if not _CTP_EXCHANGE_RE.fullmatch(exchange_id):
        raise _config_error(
            "{0}.exchange_id is not a supported identifier".format(block_name),
            "{0}.exchange_id".format(block_name),
            "invalid_{0}_value".format(block_name),
        )
    if hedge_flag not in ("1", "2", "3"):
        raise _config_error(
            "{0}.hedge_flag must be 1, 2, or 3".format(block_name),
            "{0}.hedge_flag".format(block_name),
            "invalid_{0}_value".format(block_name),
        )
    # The credential strings are authenticated by the private seal; this
    # additional identifier check keeps malformed account selectors bounded.
    for key, identifier in (("broker_id", broker_id), ("user_id", user_id)):
        if not _CTP_IDENTIFIER_RE.fullmatch(identifier):
            raise _config_error(
                "{0}.{1} is not a supported identifier".format(block_name, key),
                "{0}.{1}".format(block_name, key),
                "invalid_{0}_value".format(block_name),
            )
    return CtpSimNowPrivateConfig(
        md_front=md_front,
        td_front=td_front,
        front_pairs=front_pairs,
        instrument_id=instrument_id,
        exchange_id=exchange_id,
        hedge_flag=hedge_flag,
        broker_id=broker_id,
        user_id=user_id,
        password=password,
        app_id=app_id,
        auth_code=auth_code,
    )


def _parse_ctp_simnow_private_config(value: Any) -> CtpSimNowPrivateConfig:
    """Keep the historical SimNow entry point and its error paths stable."""

    return _parse_ctp_private_config(value, field_prefix="ctp_simnow")


def _parse_ctp_production_private_config(value: Any) -> CtpProductionPrivateConfig:
    """Parse private CTP values without selecting from a configured front list."""

    mapping = _require_mapping(value, "ctp_production")
    _reject_unknown_fields(mapping, _CTP_PRODUCTION_FIELDS, "ctp_production")
    normalized = _normalise_value(mapping, "ctp_production")

    def required(key: str, *, secret: bool = False) -> str:
        return _required_private_string(
            normalized,
            key,
            secret=secret,
            field_prefix="ctp_production",
        )

    has_front_pairs = "front_pairs" in normalized
    has_legacy_fronts = "md_front" in normalized or "td_front" in normalized
    if has_front_pairs and has_legacy_fronts:
        raise _config_error(
            "ctp_production must use either front_pairs or the legacy md_front/td_front pair",
            "ctp_production.front_pairs",
            "mixed_ctp_production_front_forms",
        )
    if has_front_pairs:
        raw_pairs = normalized["front_pairs"]
        if (
            type(raw_pairs) is not list
            or not 1 <= len(raw_pairs) <= _MAX_CTP_PRODUCTION_FRONT_PAIRS
        ):
            raise _config_error(
                "ctp_production.front_pairs must contain between 1 and {0} pairs".format(
                    _MAX_CTP_PRODUCTION_FRONT_PAIRS
                ),
                "ctp_production.front_pairs",
                "invalid_ctp_production_front_pairs",
            )
        parsed_pairs = []
        seen_pairs = set()
        for index, raw_pair in enumerate(raw_pairs):
            pair_path = "ctp_production.front_pairs[{0}]".format(index)
            pair_mapping = _require_mapping(raw_pair, pair_path)
            _reject_unknown_fields(
                pair_mapping, _CTP_PRODUCTION_FRONT_PAIR_FIELDS, pair_path
            )
            md_front_value = _required_ctp_front(
                pair_mapping, "md_front", field_prefix=pair_path
            )
            td_front_value = _required_ctp_front(
                pair_mapping, "td_front", field_prefix=pair_path
            )
            pair_key = (md_front_value, td_front_value)
            if pair_key in seen_pairs:
                raise _config_error(
                    "ctp_production.front_pairs must not repeat an exact pair",
                    pair_path,
                    "duplicate_ctp_production_front_pair",
                )
            seen_pairs.add(pair_key)
            parsed_pairs.append(
                MappingProxyType(
                    {"md_front": md_front_value, "td_front": td_front_value}
                )
            )
        # Deliberately do not populate the legacy scalars with the first pair.
        md_front = None
        td_front = None
        front_pairs = tuple(parsed_pairs)
    else:
        md_front = _required_ctp_front(
            normalized, "md_front", field_prefix="ctp_production"
        )
        td_front = _required_ctp_front(
            normalized, "td_front", field_prefix="ctp_production"
        )
        front_pairs = (MappingProxyType({"md_front": md_front, "td_front": td_front}),)
    instrument_id = required("instrument_id")
    exchange_id = required("exchange_id")
    hedge_flag = required("hedge_flag")
    broker_id = required("broker_id", secret=True)
    user_id = required("user_id", secret=True)
    password = required("password", secret=True)
    app_id = required("app_id", secret=True)
    auth_code = required("auth_code", secret=True)

    for key, identifier, pattern in (
        ("instrument_id", instrument_id, _CTP_INSTRUMENT_RE),
        ("exchange_id", exchange_id, _CTP_EXCHANGE_RE),
        ("broker_id", broker_id, _CTP_IDENTIFIER_RE),
        ("user_id", user_id, _CTP_IDENTIFIER_RE),
    ):
        if not pattern.fullmatch(identifier):
            raise _config_error(
                "ctp_production.{0} is not a supported identifier".format(key),
                "ctp_production.{0}".format(key),
                "invalid_ctp_production_value",
            )
    if hedge_flag not in ("1", "2", "3"):
        raise _config_error(
            "ctp_production.hedge_flag must be 1, 2, or 3",
            "ctp_production.hedge_flag",
            "invalid_ctp_production_value",
        )
    return CtpProductionPrivateConfig(
        md_front=md_front,
        td_front=td_front,
        front_pairs=front_pairs,
        instrument_id=instrument_id,
        exchange_id=exchange_id,
        hedge_flag=hedge_flag,
        broker_id=broker_id,
        user_id=user_id,
        password=password,
        app_id=app_id,
        auth_code=auth_code,
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


def _thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value


def _digest_config(
    strategy_id: str,
    mode: str,
    preset: str,
    parameters: Dict[str, Any],
    secrets_ref: str,
    ctp_simnow: Optional[CtpSimNowPrivateConfig] = None,
    ctp_production: Optional[CtpProductionPrivateConfig] = None,
    ctp: Optional[CtpPrivateConfig] = None,
) -> str:
    canonical = {
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "parameters": parameters,
        "runtime": {"mode": mode, "preset": preset},
        "secrets_ref": secrets_ref,
        "strategy": {"id": strategy_id},
    }
    if ctp_simnow is not None:
        # Front addresses and contract selectors are public route metadata;
        # account identifiers and authentication values remain private.
        simnow_scope: Dict[str, Any] = {
            "instrument_id": ctp_simnow.instrument_id,
            "exchange_id": ctp_simnow.exchange_id,
            "hedge_flag": ctp_simnow.hedge_flag,
        }
        if ctp_simnow.md_front is not None and ctp_simnow.td_front is not None:
            # Preserve the canonical digest of existing single-pair configs.
            simnow_scope["md_front"] = ctp_simnow.md_front
            simnow_scope["td_front"] = ctp_simnow.td_front
        else:
            simnow_scope["front_pairs"] = [
                {"md_front": pair["md_front"], "td_front": pair["td_front"]}
                for pair in ctp_simnow.front_pairs
            ]
        canonical["ctp_simnow"] = simnow_scope
    if ctp_production is not None:
        # Configured fronts are bound into the digest so an endpoint change
        # changes config identity. A front_pairs list stays unresolved and is
        # never projected as a selected front. The code-owned production pin
        # remains a separate admission check; accounts and credentials stay
        # private.
        production_scope: Dict[str, Any] = {
            "instrument_id": ctp_production.instrument_id,
            "exchange_id": ctp_production.exchange_id,
            "hedge_flag": ctp_production.hedge_flag,
        }
        if ctp_production.md_front is not None and ctp_production.td_front is not None:
            # Preserve the canonical digest for existing explicit single-pair configs.
            production_scope["md_front"] = ctp_production.md_front
            production_scope["td_front"] = ctp_production.td_front
        else:
            production_scope["front_pairs"] = [
                {"md_front": pair["md_front"], "td_front": pair["td_front"]}
                for pair in ctp_production.front_pairs
            ]
        canonical["ctp_production"] = production_scope
    if ctp is not None:
        # The canonical mode-neutral block binds its configured front set and
        # contract scope while keeping account selectors and credentials out
        # of the public digest.
        ctp_scope: Dict[str, Any] = {
            "instrument_id": ctp.instrument_id,
            "exchange_id": ctp.exchange_id,
            "hedge_flag": ctp.hedge_flag,
        }
        if ctp.md_front is not None and ctp.td_front is not None:
            ctp_scope["md_front"] = ctp.md_front
            ctp_scope["td_front"] = ctp.td_front
        else:
            ctp_scope["front_pairs"] = [
                {"md_front": pair["md_front"], "td_front": pair["td_front"]}
                for pair in ctp.front_pairs
            ]
        canonical["ctp"] = ctp_scope
    serialized = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_schema(
    data: Any,
    strategy_dir: Path,
    source_path: Path,
    source_file_identity: Optional[Tuple[int, int]] = None,
) -> RuntimeConfig:
    if data is None:
        raise _config_error("config.yaml must not be empty", CONFIG_FILENAME, "empty_config")
    root = _require_mapping(data, CONFIG_FILENAME)
    _reject_unknown_fields(root, _ROOT_FIELDS, "")

    version = _require_field(root, "config_schema_version", "")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != CONFIG_SCHEMA_VERSION
    ):
        raise _config_error(
            "only config schema version 4 is supported",
            "config_schema_version",
            "unsupported_schema_version",
        )

    strategy = _require_mapping(_require_field(root, "strategy", ""), "strategy")
    _reject_unknown_fields(strategy, _STRATEGY_FIELDS, "strategy")
    strategy_id = _require_field(strategy, "id", "strategy")
    if not isinstance(strategy_id, str) or not _STRATEGY_ID_RE.fullmatch(strategy_id):
        raise _config_error(
            "strategy.id must be a non-empty stable identifier",
            "strategy.id",
            "invalid_strategy_id",
        )

    runtime = _require_mapping(_require_field(root, "runtime", ""), "runtime")
    _reject_unknown_fields(runtime, _RUNTIME_FIELDS, "runtime")
    mode = _require_field(runtime, "mode", "runtime")
    preset = _require_field(runtime, "preset", "runtime")
    if not isinstance(mode, str) or mode not in ("backtest", "simulation", "live"):
        raise RuntimeConfigError(
            MODE_PRESET_MISMATCH,
            "runtime.mode is not one of the supported modes",
            field_path="runtime.mode",
            reason="unsupported_mode",
        )
    if not isinstance(preset, str) or get_preset_policy(preset) is None:
        raise RuntimeConfigError(
            MODE_PRESET_MISMATCH,
            "runtime.preset is not a registered preset name",
            field_path="runtime.preset",
            reason="unsupported_preset",
        )
    policy = get_preset_policy(preset)
    if policy is None or policy.mode != mode:
        raise RuntimeConfigError(
            MODE_PRESET_MISMATCH,
            "runtime.mode and runtime.preset are not a permitted pair",
            field_path="runtime.preset",
            reason="mode_preset_mismatch",
        )

    has_ctp = "ctp" in root
    has_ctp_simnow = "ctp_simnow" in root
    has_ctp_production = "ctp_production" in root
    if has_ctp and (has_ctp_simnow or has_ctp_production):
        raise _config_error(
            "canonical and legacy CTP private blocks are mutually exclusive",
            "ctp",
            "ctp_private_blocks_mutually_exclusive",
        )
    if has_ctp_simnow and has_ctp_production:
        raise _config_error(
            "CTP SimNow and production private blocks are mutually exclusive",
            "ctp_production",
            "ctp_private_blocks_mutually_exclusive",
        )

    ctp: Optional[CtpPrivateConfig] = None
    if has_ctp:
        if (mode, preset) not in (
            ("simulation", "sandbox"),
            ("live", "managed_live_direct"),
        ):
            raise _config_error(
                "ctp is allowed only for simulation/sandbox or live/managed_live_direct",
                "ctp",
                "ctp_scope_not_allowed",
            )
        ctp = _parse_ctp_private_config(root["ctp"])

    ctp_simnow: Optional[CtpSimNowPrivateConfig] = None
    if "ctp_simnow" in root:
        if mode != "simulation" or preset != "sandbox":
            raise _config_error(
                "ctp_simnow is allowed only for simulation/sandbox",
                "ctp_simnow",
                "ctp_simnow_scope_not_allowed",
            )
        ctp_simnow = _parse_ctp_simnow_private_config(root["ctp_simnow"])

    ctp_production: Optional[CtpProductionPrivateConfig] = None
    if has_ctp_production:
        if not _is_ctp_production_runtime_dir(strategy_dir):
            raise _config_error(
                "ctp_production is allowed only in the reserved production runtime directory",
                "ctp_production",
                "ctp_production_runtime_path_mismatch",
            )
        if mode != "live" or preset != "managed_live_direct":
            raise _config_error(
                "ctp_production is allowed only for live/managed_live_direct",
                "ctp_production",
                "ctp_production_scope_not_allowed",
            )
        ctp_production = _parse_ctp_production_private_config(root["ctp_production"])

    parameters_raw = root.get("parameters", {})
    parameters = _normalise_value(_require_mapping(parameters_raw, "parameters"), "parameters")
    _reject_inline_secrets_and_controls(parameters, "parameters")

    secrets_ref = root.get("secrets_ref", "none")
    if not isinstance(secrets_ref, str) or not (
        secrets_ref in ("none", "runtime_secrets", "config_yaml")
        or _OS_SECRET_REF_RE.fullmatch(secrets_ref)
    ):
        raise _config_error(
            "secrets_ref must be none, runtime_secrets, or an opaque OS secret-store reference",
            "secrets_ref",
            "invalid_secrets_ref",
        )
    if "${" in secrets_ref:
        raise _config_error(
            "environment interpolation is not supported in config.yaml",
            "secrets_ref",
            "environment_interpolation_not_allowed",
        )

    # The old SimNow attribute remains an exact-type compatibility view for a
    # canonical sandbox block; both names refer to one object and one set of
    # credentials.  The canonical live block has no legacy alias.
    if ctp is not None and mode == "simulation":
        ctp_simnow = ctp

    has_private_ctp_block = (
        ctp is not None or ctp_simnow is not None or ctp_production is not None
    )
    if has_private_ctp_block and secrets_ref != "config_yaml":
        block_name = (
            "ctp"
            if ctp is not None
            else "ctp_production"
            if ctp_production is not None
            else "ctp_simnow"
        )
        raise _config_error(
            "secrets_ref config_yaml is required for the private {0} block".format(block_name),
            block_name,
            "ctp_secret_source_mismatch"
            if ctp is not None
            else "ctp_production_secret_source_mismatch"
            if ctp_production is not None
            else "ctp_simnow_secret_source_mismatch",
        )
    if not has_private_ctp_block and secrets_ref == "config_yaml":
        raise _config_error(
            "secrets_ref config_yaml requires a private CTP block",
            "secrets_ref",
            "ctp_simnow_secret_source_mismatch",
        )

    digest = _digest_config(
        strategy_id,
        mode,
        preset,
        parameters,
        secrets_ref,
        ctp_simnow if has_ctp_simnow else None,
        ctp_production,
        ctp,
    )
    return RuntimeConfig(
        strategy_dir=strategy_dir,
        source_path=source_path,
        strategy_id=strategy_id,
        mode=mode,
        preset=preset,
        parameters=_freeze_value(parameters),
        secrets_ref=secrets_ref,
        config_digest=digest,
        ctp=ctp,
        ctp_simnow=ctp_simnow,
        ctp_production=ctp_production,
        _source_file_identity=source_file_identity,
    )


def _parse_verified_runtime_config_text(
    text: str,
    strategy_dir: Path,
    source_path: Path,
    *,
    registry: Optional[Any] = None,
    source_file_identity: Optional[Tuple[int, int]] = None,
) -> RuntimeConfig:
    """Parse bytes already read through a verified config descriptor.

    Bootstrap-set preflight uses this to compare and validate the *same* sealed
    bytes.  It must not re-open config.yaml after deciding that the bytes match
    the reviewed canonical bootstrap content.
    """

    return _seal_loaded_runtime_config(
        _validate_schema(_load_strict_yaml(text), strategy_dir, source_path, source_file_identity),
        registry,
    )


def load_runtime_config(
    strategy_dir: Union[str, os.PathLike],
    *,
    registry: Optional[Any] = None,
) -> RuntimeConfig:
    """Read and strictly validate ``<strategy_dir>/config.yaml``.

    Passing a registry binds the parsed config to that exact trusted registry
    and checks its directory before opening the file.  Omitting it supports
    safe two-stage inspection; later resolution still checks the chosen
    registry and runtime identity.  The function deliberately performs no
    network, secret-store, plugin, provider, or strategy import.
    """

    resolved_dir = _normalise_runtime_dir(strategy_dir)
    if registry is None:
        if _is_ctp_production_runtime_dir(resolved_dir):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "ctp_production requires a registered runtime before private config can be read",
                field_path="ctp_production",
                reason="private_config_registration_required",
            )
        identity_out = []
        source_path, text = _read_config_text(resolved_dir, identity_out=identity_out)
        config = _parse_verified_runtime_config_text(
            text,
            resolved_dir,
            source_path,
            source_file_identity=identity_out[0],
        )
        if config.ctp is not None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "ctp requires a code-owned runtime registration before private config can be returned or used",
                field_path="ctp",
                reason="private_config_registration_required",
            )
        if config.ctp_simnow is not None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "ctp_simnow requires a code-owned runtime registration before private config can be returned or used",
                field_path="ctp_simnow",
                reason="private_config_registration_required",
            )
        if config.ctp_production is not None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "ctp_production requires a code-owned runtime registration before private config can be returned or used",
                field_path="ctp_production",
                reason="private_config_registration_required",
            )
        return config

    # After lookup, use only the canonical directory held by the trusted
    # registration.  In particular, never reopen the caller's spelling of a
    # path after it has been authorised.
    registration = registry.require_runtime_dir(resolved_dir)
    with registry.verified_runtime_directory(registration) as directory_fd:
        identity_out = []
        source_path, text = _read_config_text(
            registration.runtime_dir,
            directory_fd=directory_fd,
            identity_out=identity_out,
            require_private_config_security=(
                "config_yaml" in registration.allowed_secrets_refs
                or any(
                    "config_yaml" in profile.allowed_secrets_refs
                    for profile in registration.profiles
                )
            ),
            directory_identity=registration.directory_identity,
        )
        config = _parse_verified_runtime_config_text(
            text,
            registration.runtime_dir,
            source_path,
            registry=registry,
            source_file_identity=identity_out[0],
        )
    return config


def write_bootstrap_config(
    path: Union[str, os.PathLike], content: str, *, directory_fd: Optional[int] = None
) -> Path:
    """Atomically create a new local config file without overwriting one.

    This low-level writer is used by the registry-aware bootstrap helper.  It
    does not create parents, merge files, or write secrets.
    """

    target = Path(path)
    target_name = CONFIG_FILENAME if directory_fd is not None else str(target)
    try:
        if directory_fd is None:
            descriptor = os.open(target_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        else:
            descriptor = os.open(
                target_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
    except FileExistsError:
        raise RuntimeConfigError(
            CONFIG_EXISTS,
            "config.yaml already exists and will not be overwritten",
            field_path=CONFIG_FILENAME,
            reason="config_exists",
        ) from None
    except OSError:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "config.yaml cannot be created in the registered runtime directory",
            field_path=CONFIG_FILENAME,
            reason="config_create_failed",
        ) from None

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            if directory_fd is None:
                target.unlink()
            else:
                os.unlink(CONFIG_FILENAME, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    return target
