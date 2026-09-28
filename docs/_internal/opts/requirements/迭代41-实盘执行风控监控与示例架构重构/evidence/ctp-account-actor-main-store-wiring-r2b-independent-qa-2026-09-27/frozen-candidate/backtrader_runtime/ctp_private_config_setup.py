"""Prepare the reserved local CTP SimNow config from an explicit private source.

This helper has no provider imports or network path.  It copies only a fixed
set of CTP connection fields into the Iteration 41 schema; mode, preset,
strategy identity, and destination are code-owned.  A prepared config grants
no route or trading authority.
"""

from __future__ import annotations

import json
import errno
import os
import re
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple, Union

from .config import _load_strict_yaml, _parse_verified_runtime_config_text
from .errors import CONFIG_EXISTS, CONFIG_SCHEMA_UNSUPPORTED, RuntimeConfigError


CTP_SIMNOW_PRIVATE_RUNTIME_DIR = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "013_3_sa_midfreq_simnow"
    / "runtime-ctp-private"
)
CTP_SIMNOW_PRIVATE_STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
MAX_SOURCE_BYTES = 64 * 1024
MAX_SOURCE_VALUE_BYTES = 2048

_FIELDS = (
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
_NON_FRONT_FIELDS = tuple(name for name in _FIELDS if name not in ("md_front", "td_front"))
_FRONT_PAIR_FIELDS = frozenset(("md_front", "td_front"))
_MAX_FRONT_PAIRS = 8
_ENV_SET1_FRONT_KEY_RE = re.compile(r"^CTP_SET1_(MD|TD)_FRONT_(\d+)$")
_ENV_SET2_FRONT_KEYS = {
    "CTP_SET2_MD_FRONT": "md_front",
    "CTP_SET2_TD_FRONT": "td_front",
}
_ENV_KEYS = {
    "CTP_MD_FRONT": "md_front",
    "SIMNOW_MD_FRONT": "md_front",
    "simnow_md_front": "md_front",
    "CTP_TD_FRONT": "td_front",
    "SIMNOW_TD_FRONT": "td_front",
    "simnow_td_front": "td_front",
    "CTP_INSTRUMENT": "instrument_id",
    "CTP_INSTRUMENT_ID": "instrument_id",
    "SIMNOW_INSTRUMENT_ID": "instrument_id",
    "CTP_EXCHANGE": "exchange_id",
    "CTP_EXCHANGE_ID": "exchange_id",
    "SIMNOW_EXCHANGE_ID": "exchange_id",
    "CTP_HEDGE_FLAG": "hedge_flag",
    "SIMNOW_HEDGE_FLAG": "hedge_flag",
    "CTP_BROKER_ID": "broker_id",
    "SIMNOW_BROKER_ID": "broker_id",
    "CTP_USER_ID": "user_id",
    "CTP_INVESTOR_ID": "user_id",
    "SIMNOW_USER_ID": "user_id",
    "simnow_user_id": "user_id",
    "CTP_PASSWORD": "password",
    "SIMNOW_PASSWORD": "password",
    "simnow_password": "password",
    "CTP_APP_ID": "app_id",
    "SIMNOW_APP_ID": "app_id",
    "CTP_AUTH_CODE": "auth_code",
    "SIMNOW_AUTH_CODE": "auth_code",
}
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER_RE = re.compile(r"^(?:<.*>|\$\{.*\}|(?:your|replace|change|enter)[-_ ].*)$", re.I)
_PLACEHOLDER_WORDS = frozenset(("todo", "changeme", "change-me", "replace-me", "your-password"))


@dataclass(frozen=True)
class PreparedCtpSimNowConfig:
    """A redacted summary of a successfully created private config."""

    path: Path
    config_digest: str

    def as_public_dict(self) -> Dict[str, Any]:
        return {
            "status": "prepared_offline",
            "config_path": str(self.path),
            "config_digest": self.config_digest,
            "mode": "simulation",
            "preset": "sandbox",
            "runtime_registered": True,
            "provider_io": False,
            "external_writes": False,
            "execution_authorized": False,
            "admission": "not_granted",
        }


@dataclass(frozen=True)
class _CreatedPrivateFile:
    """Identity and optional handle retained for cleanup after creation."""

    identity: os.stat_result
    retained_fd: Optional[int]


def _error(reason: str, message: str, field_path: str = "source") -> RuntimeConfigError:
    return RuntimeConfigError(
        CONFIG_SCHEMA_UNSUPPORTED,
        message,
        field_path=field_path,
        reason=reason,
    )


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _unlink_posix_created_file(directory_descriptor: int, identity: os.stat_result) -> None:
    """Unlink the target only while its entry still names this call's inode."""

    try:
        entry = os.stat("config.yaml", dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(entry.st_mode) or not _same_identity(identity, entry):
        raise OSError("config.yaml no longer names the created private file")
    os.unlink("config.yaml", dir_fd=directory_descriptor)


def _reject_source(reason: str, message: str, field_path: str = "source") -> None:
    raise _error(reason, message, field_path)


def _is_windows_reparse(result: os.stat_result) -> bool:
    attributes = getattr(result, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _windows_directory_identity_chain(runtime_dir: Path):
    """Inspect every directory component and reject Windows reparse points."""

    absolute = Path(os.path.abspath(str(runtime_dir)))
    if not absolute.anchor:
        _reject_source(
            "private_target_path_invalid",
            "reserved CTP private runtime path must be absolute",
            "config.yaml",
        )

    paths = [Path(absolute.anchor)]
    current = paths[0]
    for part in absolute.parts:
        if part == absolute.anchor:
            continue
        current = current / part
        paths.append(current)

    identities = []
    for path in paths:
        try:
            entry = os.lstat(str(path))
        except OSError:
            _reject_source(
                "private_target_directory_unavailable",
                "reserved CTP private runtime directory is unavailable",
                "config.yaml",
            )
        if stat.S_ISLNK(entry.st_mode) or _is_windows_reparse(entry):
            _reject_source(
                "private_target_directory_invalid",
                "reserved CTP private runtime path cannot contain reparse points",
                "config.yaml",
            )
        if not stat.S_ISDIR(entry.st_mode):
            _reject_source(
                "private_target_directory_invalid",
                "reserved CTP private runtime path must contain only directories",
                "config.yaml",
            )
        identities.append((path, entry))
    return tuple(identities)


def _same_directory_identity_chain(left, right) -> bool:
    return len(left) == len(right) and all(
        os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))
        and _same_identity(left_stat, right_stat)
        for (left_path, left_stat), (right_path, right_stat) in zip(left, right)
    )


def _open_posix_directory_chain(runtime_dir: Path):
    """Open each POSIX path component relative to its verified parent."""

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if (
        not runtime_dir.is_absolute()
        or any(not hasattr(os, name) for name in required_flags)
        or os.open not in getattr(os, "supports_dir_fd", set())
    ):
        _reject_source(
            "private_target_security_unavailable",
            "this POSIX platform cannot safely open every private target path component",
            "config.yaml",
        )

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    identities = []
    try:
        descriptor = os.open("/", flags)
        descriptors.append(descriptor)
        current = Path("/")
        root_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(root_stat.st_mode):
            _reject_source(
                "private_target_directory_invalid",
                "reserved CTP private runtime path must contain only directories",
                "config.yaml",
            )
        identities.append((current, root_stat))

        for component in runtime_dir.parts:
            if component == "/":
                continue
            descriptor = os.open(component, flags, dir_fd=descriptors[-1])
            descriptors.append(descriptor)
            current = current / component
            component_stat = os.fstat(descriptor)
            if not stat.S_ISDIR(component_stat.st_mode):
                _reject_source(
                    "private_target_directory_invalid",
                    "reserved CTP private runtime path must contain only directories",
                    "config.yaml",
                )
            identities.append((current, component_stat))

        final_descriptor = descriptors[-1]
        for descriptor in reversed(descriptors[:-1]):
            os.close(descriptor)
        descriptors.clear()
        return tuple(identities), final_descriptor
    except RuntimeConfigError:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError as error:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            _reject_source(
                "private_target_directory_invalid",
                "reserved CTP private runtime path cannot contain symbolic links",
                "config.yaml",
            )
        _reject_source(
            "private_target_directory_unavailable",
            "reserved CTP private runtime directory cannot be opened safely",
            "config.yaml",
        )
    except BaseException:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _source_security(descriptor: int, file_stat: os.stat_result) -> None:
    if file_stat.st_nlink != 1:
        _reject_source(
            "private_source_hardlink_not_allowed", "source must have one filesystem link"
        )
    if os.name == "posix":
        if not hasattr(os, "geteuid"):
            _reject_source(
                "private_source_security_unavailable", "source ownership cannot be verified"
            )
        uid = os.geteuid()
        mode = stat.S_IMODE(file_stat.st_mode)
        if file_stat.st_uid != uid or mode & ~0o600 or mode & stat.S_IRUSR == 0:
            _reject_source(
                "private_source_permissions_unsafe",
                "source must be owned by the current user and readable only by its owner",
            )
        return
    if os.name == "nt":
        try:
            from .credential_resolver import _windows_acl_for_handle, _windows_os_handle

            _windows_acl_for_handle(_windows_os_handle(descriptor))
        except Exception:
            _reject_source(
                "private_source_acl_unsafe",
                "Windows could not verify an owner-only source ACL",
            )
        return
    _reject_source("private_source_security_unavailable", "source security cannot be verified here")


@contextmanager
def _open_explicit_private_source(source: Path) -> Iterator[Tuple[int, os.stat_result]]:
    """Open one absolute source only after validating its identity and ACL."""

    if not source.is_absolute():
        _reject_source(
            "source_path_must_be_absolute",
            "name the local source with an absolute path; no working-directory search is used",
        )
    try:
        before = os.lstat(str(source))
    except OSError:
        _reject_source("source_unavailable", "the explicitly named source file is unavailable")
    if stat.S_ISLNK(before.st_mode) or _is_windows_reparse(before):
        _reject_source(
            "source_link_not_allowed", "source must not be a symbolic link or reparse point"
        )
    if not stat.S_ISREG(before.st_mode):
        _reject_source("source_not_regular_file", "source must be a regular local file")
    if before.st_size > MAX_SOURCE_BYTES:
        _reject_source("source_too_large", "source exceeds the supported local file size")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(source), flags)
    except OSError:
        _reject_source("source_unavailable", "the explicitly named source file cannot be opened")
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_identity(before, opened)
            or opened.st_size > MAX_SOURCE_BYTES
            or _is_windows_reparse(opened)
        ):
            _reject_source("source_identity_changed", "source identity changed while it was opened")
        _source_security(descriptor, opened)
        yield descriptor, opened
    finally:
        os.close(descriptor)


def _read_opened_private_source(
    source: Path,
    descriptor: int,
    opened: os.stat_result,
) -> str:
    """Read an already ACL-checked descriptor and recheck its file identity."""

    with os.fdopen(os.dup(descriptor), "rb") as handle:
        payload = handle.read(MAX_SOURCE_BYTES + 1)
    after = os.fstat(descriptor)
    try:
        path_after = os.lstat(str(source))
    except OSError:
        _reject_source("source_identity_changed", "source identity changed while it was read")
    if (
        len(payload) > MAX_SOURCE_BYTES
        or len(payload) != opened.st_size
        or after.st_size != opened.st_size
        or getattr(after, "st_mtime_ns", None) != getattr(opened, "st_mtime_ns", None)
        or not _same_identity(opened, after)
        or not _same_identity(opened, path_after)
    ):
        _reject_source("source_identity_changed", "source identity changed while it was read")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        _reject_source("source_encoding_invalid", "source must be valid UTF-8 text")
    raise AssertionError("unreachable")


def _read_explicit_private_source(source: Path) -> str:
    with _open_explicit_private_source(source) as (descriptor, opened):
        return _read_opened_private_source(source, descriptor, opened)


def _unquote_env_value(raw: str, line_number: int) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in "'\"":
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            _reject_source(
                "source_syntax_invalid",
                "source contains an unterminated quoted value at line {0}".format(line_number),
            )
        value = value[1:-1]
    elif value[-1] in "'\"":
        _reject_source(
            "source_syntax_invalid",
            "source contains an unmatched quote at line {0}".format(line_number),
        )
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        _reject_source("source_value_invalid", "source contains a value that is not valid UTF-8")
    if size > MAX_SOURCE_VALUE_BYTES or "\x00" in value:
        _reject_source("source_value_invalid", "source contains an unsupported field value")
    return value


def _parse_env_source(text: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    grouped_fronts: Dict[Tuple[str, int, str], str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            _reject_source(
                "source_syntax_invalid",
                "source line {0} must use KEY=VALUE syntax".format(line_number),
            )
        name, raw_value = line.split("=", 1)
        key = name.strip()
        if not _ENV_KEY_RE.fullmatch(key):
            _reject_source(
                "source_syntax_invalid",
                "source contains an invalid key name at line {0}".format(line_number),
            )
        set1_match = _ENV_SET1_FRONT_KEY_RE.fullmatch(key)
        if set1_match:
            endpoint = set1_match.group(1).lower() + "_front"
            try:
                index = int(set1_match.group(2))
            except ValueError:
                _reject_source(
                    "source_front_pair_invalid",
                    "source has an invalid CTP_SET1 front pair index",
                    "ctp_simnow.front_pairs",
                )
            if index < 1:
                _reject_source(
                    "source_front_pair_invalid",
                    "CTP_SET1 front pair indexes must start at 1",
                    "ctp_simnow.front_pairs",
                )
            grouped_key = ("set1", index, endpoint)
        elif key in _ENV_SET2_FRONT_KEYS:
            grouped_key = ("set2", 1, _ENV_SET2_FRONT_KEYS[key])
        else:
            grouped_key = None

        if grouped_key is not None:
            value = _unquote_env_value(raw_value, line_number)
            if grouped_key in grouped_fronts and grouped_fronts[grouped_key] != value:
                _reject_source(
                    "source_duplicate_field",
                    "source has conflicting values for ctp_simnow.front_pairs",
                    "ctp_simnow.front_pairs",
                )
            grouped_fronts[grouped_key] = value
            continue

        if key.startswith(
            (
                "CTP_SET1_MD_FRONT",
                "CTP_SET1_TD_FRONT",
                "CTP_SET2_MD_FRONT",
                "CTP_SET2_TD_FRONT",
            )
        ):
            _reject_source(
                "source_front_pair_invalid",
                "source has an unsupported CTP_SET front key",
                "ctp_simnow.front_pairs",
            )

        target = _ENV_KEYS.get(key)
        if target is None:
            # Legacy mode/profile and approval variables are deliberately not
            # consulted. In particular they can never select a SimNow set.
            continue
        value = _unquote_env_value(raw_value, line_number)
        if target in values and values[target] != value:
            _reject_source(
                "source_duplicate_field",
                "source has conflicting values for aliases mapped to ctp_simnow.{0}".format(target),
                "ctp_simnow.{0}".format(target),
            )
        values[target] = value

    has_current_front = bool(_FRONT_PAIR_FIELDS.intersection(values))
    has_grouped_front = bool(grouped_fronts)
    if has_grouped_front and has_current_front and not _FRONT_PAIR_FIELDS.issubset(values):
        _reject_source(
            "source_front_pair_incomplete",
            "source must provide both CTP_MD_FRONT and CTP_TD_FRONT",
            "ctp_simnow.front_pairs",
        )

    if has_grouped_front:
        grouped_pairs = []
        ordered_fronts = sorted(
            grouped_fronts,
            key=lambda item: (0 if item[0] == "set1" else 1, item[1], item[2]),
        )
        seen_slots = set()
        ordered_slots = []
        for group, index, _endpoint in ordered_fronts:
            slot = (group, index)
            if slot not in seen_slots:
                seen_slots.add(slot)
                ordered_slots.append(slot)
        for group, index in ordered_slots:
            md_key = (group, index, "md_front")
            td_key = (group, index, "td_front")
            if md_key not in grouped_fronts or td_key not in grouped_fronts:
                _reject_source(
                    "source_front_pair_incomplete",
                    "source must provide both MD and TD fronts for every explicit CTP_SET pair",
                    "ctp_simnow.front_pairs",
                )
            grouped_pairs.append(
                {"md_front": grouped_fronts[md_key], "td_front": grouped_fronts[td_key]}
            )

        candidates = []
        if has_current_front:
            candidates.append(
                {"md_front": values.pop("md_front"), "td_front": values.pop("td_front")}
            )
        candidates.extend(grouped_pairs)
        unique_pairs = []
        seen_pairs = set()
        for pair in candidates:
            identity = (pair["md_front"], pair["td_front"])
            if identity not in seen_pairs:
                seen_pairs.add(identity)
                unique_pairs.append(pair)
        if len(unique_pairs) > _MAX_FRONT_PAIRS:
            _reject_source(
                "source_front_pair_invalid",
                "source must contain no more than {0} unique CTP front pairs".format(
                    _MAX_FRONT_PAIRS
                ),
                "ctp_simnow.front_pairs",
            )
        values["front_pairs"] = tuple(unique_pairs)
    return values


def _parse_yaml_source(text: str) -> Dict[str, Any]:
    try:
        document = _load_strict_yaml(text)
    except RuntimeConfigError:
        _reject_source("source_yaml_invalid", "source YAML is invalid or contains duplicate keys")
    if type(document) is not dict:
        _reject_source(
            "source_yaml_schema_invalid",
            "source YAML must contain one private CTP mapping with the required CTP fields",
        )
    has_canonical = "ctp" in document
    has_legacy = "ctp_simnow" in document
    if has_canonical and has_legacy:
        _reject_source(
            "source_yaml_schema_invalid",
            "source YAML must contain only one private CTP mapping",
            "ctp",
        )
    block_name = "ctp" if has_canonical else "ctp_simnow"
    if type(document.get(block_name)) is not dict:
        _reject_source(
            "source_yaml_schema_invalid",
            "source YAML must contain one private CTP mapping with the required CTP fields",
            block_name,
        )
    block = document[block_name]
    if any(type(name) is not str for name in block):
        _reject_source(
            "source_yaml_schema_invalid",
            "source {0} field names must be strings".format(block_name),
            block_name,
        )
    allowed_fields = set(_FIELDS) | {"front_pairs"}
    unknown = sorted(set(block) - allowed_fields)
    if unknown:
        _reject_source(
            "source_yaml_schema_invalid",
            "source YAML has unsupported {0} fields: {1}".format(
                block_name, ", ".join(unknown)
            ),
            block_name,
        )
    has_front_pairs = "front_pairs" in block
    has_legacy_fronts = bool(_FRONT_PAIR_FIELDS.intersection(block))
    if has_front_pairs and has_legacy_fronts:
        _reject_source(
            "source_front_form_conflict",
            "source YAML must use either front_pairs or the legacy md_front/td_front pair",
            "{0}.front_pairs".format(block_name),
        )

    values: Dict[str, Any] = {}
    for name, value in block.items():
        if name == "front_pairs":
            values[name] = _parse_yaml_front_pairs(value, field_prefix=block_name)
            continue
        if type(name) is not str or type(value) is not str:
            _reject_source(
                "source_yaml_schema_invalid",
                "source {0} fields must be strings".format(block_name),
                block_name,
            )
        values[name] = value
    return values


def _parse_yaml_front_pairs(
    value: Any, *, field_prefix: str = "ctp_simnow"
) -> Tuple[Mapping[str, str], ...]:
    """Validate an explicit front-pair list without choosing a candidate."""

    if type(value) is not list or not 1 <= len(value) <= _MAX_FRONT_PAIRS:
        _reject_source(
            "source_yaml_schema_invalid",
            "source YAML {0}.front_pairs must contain between 1 and {1} pairs".format(
                field_prefix, _MAX_FRONT_PAIRS
            ),
            "{0}.front_pairs".format(field_prefix),
        )
    pairs = []
    for index, raw_pair in enumerate(value):
        field_path = "{0}.front_pairs[{1}]".format(field_prefix, index)
        if type(raw_pair) is not dict or any(type(name) is not str for name in raw_pair):
            _reject_source(
                "source_yaml_schema_invalid",
                "source YAML {0}.front_pairs entries must be mappings".format(field_prefix),
                field_path,
            )
        if set(raw_pair) != _FRONT_PAIR_FIELDS:
            _reject_source(
                "source_yaml_schema_invalid",
                "source YAML {0}.front_pairs entries must contain md_front and td_front only".format(
                    field_prefix
                ),
                field_path,
            )
        if any(type(raw_pair[name]) is not str for name in _FRONT_PAIR_FIELDS):
            _reject_source(
                "source_yaml_schema_invalid",
                "source YAML {0}.front_pairs endpoints must be strings".format(field_prefix),
                field_path,
            )
        pairs.append({"md_front": raw_pair["md_front"], "td_front": raw_pair["td_front"]})
    return tuple(pairs)


def _parse_collector_yaml_source(text: str) -> Dict[str, str]:
    """Read only the explicit CTP connection fields of a collector config.

    The collector's ``env`` label and timeout never choose fronts or mode.
    Contract, exchange and HedgeFlag must arrive from the other explicit
    source; the collector format does not contain them.
    """

    try:
        document = _load_strict_yaml(text)
    except RuntimeConfigError:
        _reject_source("source_yaml_invalid", "collector YAML is invalid or has duplicate keys")
    if type(document) is not dict or type(document.get("ctp")) is not dict:
        _reject_source("source_yaml_schema_invalid", "collector YAML must have one ctp mapping")
    block = document["ctp"]
    fields = frozenset(
        ("md_front", "td_front", "broker_id", "user_id", "password", "app_id", "auth_code")
    )
    allowed = fields | {"env", "login_timeout_sec"}
    if any(type(name) is not str for name in block) or set(block) - allowed:
        _reject_source("source_yaml_schema_invalid", "collector ctp mapping has unsupported fields")
    values: Dict[str, str] = {}
    for name in fields & set(block):
        value = block[name]
        if type(value) is not str:
            _reject_source(
                "source_yaml_schema_invalid",
                "collector ctp.{0} must be a string".format(name),
                "ctp.{0}".format(name),
            )
        values[name] = value
    return values


def _is_placeholder(value: str) -> bool:
    return value.casefold() in _PLACEHOLDER_WORDS or bool(_PLACEHOLDER_RE.fullmatch(value))


def _require_complete_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    has_front_pairs = "front_pairs" in values
    has_legacy_fronts = bool(_FRONT_PAIR_FIELDS.intersection(values))
    if has_front_pairs and has_legacy_fronts:
        _reject_source(
            "source_front_form_conflict",
            "explicit sources must use either front_pairs or the legacy md_front/td_front pair",
            "ctp_simnow.front_pairs",
        )
    required_fields = _NON_FRONT_FIELDS + (() if has_front_pairs else ("md_front", "td_front"))
    missing = [name for name in required_fields if not values.get(name)]
    if missing:
        keys = ", ".join("ctp_simnow.{0}".format(name) for name in missing)
        raise _error(
            "ctp_private_source_incomplete",
            "no config.yaml was written; source is missing required non-empty fields: {0}".format(
                keys
            ),
            "ctp_simnow",
        )
    for name in required_fields:
        value = values[name]
        if type(value) is not str or value != value.strip() or "\x00" in value:
            _reject_source(
                "source_value_invalid",
                "source contains an unsupported value for ctp_simnow.{0}".format(name),
                "ctp_simnow.{0}".format(name),
            )
        try:
            encoded_size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            _reject_source(
                "source_value_invalid",
                "source contains an unsupported value for ctp_simnow.{0}".format(name),
                "ctp_simnow.{0}".format(name),
            )
        if encoded_size > MAX_SOURCE_VALUE_BYTES:
            _reject_source(
                "source_value_invalid",
                "source value is too large for ctp_simnow.{0}".format(name),
                "ctp_simnow.{0}".format(name),
            )
        if _is_placeholder(value):
            _reject_source(
                "source_placeholder_value",
                "placeholder values are not accepted for ctp_simnow.{0}".format(name),
                "ctp_simnow.{0}".format(name),
            )
    complete: Dict[str, Any] = {name: values[name] for name in _NON_FRONT_FIELDS}
    if has_front_pairs:
        # The authoritative runtime parser performs canonical TCP endpoint and
        # duplicate-pair validation before the target directory is changed.
        complete["front_pairs"] = values["front_pairs"]
    else:
        complete["md_front"] = values["md_front"]
        complete["td_front"] = values["td_front"]
    return complete


def _render_config(values: Mapping[str, Any]) -> str:
    lines = [
        "config_schema_version: 4",
        "strategy:",
        "  id: " + json.dumps(CTP_SIMNOW_PRIVATE_STRATEGY_ID),
        "runtime:",
        "  mode: simulation",
        "  preset: sandbox",
        "parameters: {}",
        "secrets_ref: config_yaml",
        "ctp:",
    ]
    if "front_pairs" in values:
        lines.extend(
            (
                "  front_pairs:",
                *(
                    "    - md_front: {0}\n      td_front: {1}".format(
                        json.dumps(pair["md_front"], ensure_ascii=True),
                        json.dumps(pair["td_front"], ensure_ascii=True),
                    )
                    for pair in values["front_pairs"]
                ),
            )
        )
        scalar_fields = _NON_FRONT_FIELDS
    else:
        scalar_fields = _FIELDS
    lines.extend(
        "  {0}: {1}".format(name, json.dumps(values[name], ensure_ascii=True))
        for name in scalar_fields
    )
    return "\n".join(lines) + "\n"


def _same_directory_entry(directory_fd: int, target_dir: Path, name: str = "config.yaml") -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except (NotImplementedError, TypeError):
        try:
            os.lstat(str(target_dir / name))
            return True
        except FileNotFoundError:
            return False


def _windows_user_sid() -> Tuple[Any, Any, str]:
    """Return the current user SID and loaded Win32 libraries for ACL creation."""

    try:
        import ctypes

        advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        from .credential_resolver import _current_windows_user_sid

        sid_text = _current_windows_user_sid(advapi32, kernel32)
        return advapi32, kernel32, sid_text
    except Exception:
        _reject_source(
            "private_target_acl_unavailable", "Windows could not establish a private target ACL"
        )
    raise AssertionError("unreachable")


def _set_windows_owner_acl(descriptor: int, *, directory: bool) -> None:
    """Install a protected owner/SYSTEM/Administrators ACL before writing bytes."""

    try:
        import ctypes
        from ctypes import wintypes

        from .credential_resolver import _windows_acl_for_handle, _windows_os_handle

        advapi32, kernel32, user_sid = _windows_user_sid()
        inheritable = "OICI;FA" if directory else ";FA"
        sddl = "O:{0}D:P(A;{1};;;{0})(A;{1};;;SY)(A;{1};;;BA)".format(user_sid, inheritable)
        security_descriptor = ctypes.c_void_p()
        convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        )
        convert.restype = wintypes.BOOL
        if not convert(sddl, 1, ctypes.byref(security_descriptor), None):
            raise OSError(ctypes.get_last_error())
        try:
            get_dacl = advapi32.GetSecurityDescriptorDacl
            get_dacl.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.BOOL),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(wintypes.BOOL),
            )
            get_dacl.restype = wintypes.BOOL
            dacl = ctypes.c_void_p()
            dacl_present = wintypes.BOOL()
            dacl_defaulted = wintypes.BOOL()
            if (
                not get_dacl(
                    security_descriptor,
                    ctypes.byref(dacl_present),
                    ctypes.byref(dacl),
                    ctypes.byref(dacl_defaulted),
                )
                or not dacl_present.value
                or not dacl
            ):
                raise OSError("private ACL has no DACL")
            set_security = advapi32.SetSecurityInfo
            set_security.argtypes = (
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )
            set_security.restype = wintypes.DWORD
            result = set_security(
                wintypes.HANDLE(_windows_os_handle(descriptor)),
                1,
                0x00000004 | 0x80000000,
                None,
                None,
                dacl,
                None,
            )
            if result != 0:
                raise OSError(result, "SetSecurityInfo failed")
            _windows_acl_for_handle(_windows_os_handle(descriptor))
        finally:
            kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
            kernel32.LocalFree.restype = ctypes.c_void_p
            kernel32.LocalFree(security_descriptor)
    except RuntimeConfigError:
        raise
    except Exception:
        _reject_source(
            "private_target_acl_unavailable",
            "Windows could not install and verify the private owner-only ACL",
            "config.yaml",
        )


@contextmanager
def _verified_target_directory(
    runtime_dir: Path, on_identity_change: Optional[Callable[[], None]] = None
) -> Iterator[int]:
    before_chain = None
    if os.name == "posix":
        before_chain, descriptor = _open_posix_directory_chain(runtime_dir)
        before = before_chain[-1][1]
    elif os.name == "nt":
        before_chain = _windows_directory_identity_chain(runtime_dir)
        before = before_chain[-1][1]
    else:
        _reject_source(
            "private_target_security_unavailable",
            "private target security is unsupported on this platform",
            "config.yaml",
        )
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_windows_reparse(before)
        or not stat.S_ISDIR(before.st_mode)
    ):
        _reject_source(
            "private_target_directory_invalid",
            "reserved CTP private runtime path must be a real directory",
            "config.yaml",
        )
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes

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
            handle = create_file(
                str(runtime_dir),
                0x80000000 | 0x00040000 | 0x00000002,
                0x00000001 | 0x00000002,
                None,
                3,
                0x02000000 | 0x00200000,
                None,
            )
            invalid_handle = ctypes.c_void_p(-1).value
            if handle == invalid_handle or handle == -1:
                raise OSError(ctypes.get_last_error())
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_NOINHERIT", 0))
        except Exception:
            _reject_source(
                "private_target_directory_unavailable",
                "Windows could not lock the reserved CTP private runtime directory",
                "config.yaml",
            )

    def cleanup_created_file() -> None:
        if on_identity_change is not None:
            on_identity_change()

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
            _reject_source(
                "private_target_identity_changed",
                "reserved CTP private runtime directory identity changed",
                "config.yaml",
            )
        if os.name == "nt" and not _same_directory_identity_chain(
            before_chain, _windows_directory_identity_chain(runtime_dir)
        ):
            _reject_source(
                "private_target_identity_changed",
                "reserved CTP private runtime directory identity changed",
                "config.yaml",
            )
        try:
            yield descriptor
        except BaseException:
            cleanup_created_file()
            raise
        try:
            after = os.fstat(descriptor)
            if os.name == "nt":
                current_chain = _windows_directory_identity_chain(runtime_dir)
                current = current_chain[-1][1]
            elif os.name == "posix":
                current_chain, current_descriptor = _open_posix_directory_chain(runtime_dir)
                try:
                    current = os.fstat(current_descriptor)
                finally:
                    os.close(current_descriptor)
            else:
                current = os.lstat(str(runtime_dir))
        except RuntimeConfigError:
            cleanup_created_file()
            _reject_source(
                "private_target_identity_changed",
                "reserved CTP private runtime directory identity changed",
                "config.yaml",
            )
        except OSError:
            cleanup_created_file()
            _reject_source(
                "private_target_identity_changed",
                "reserved CTP private runtime directory identity changed",
                "config.yaml",
            )
        identity_changed = not _same_identity(opened, after) or not _same_identity(opened, current)
        if os.name in ("nt", "posix"):
            identity_changed = identity_changed or not _same_directory_identity_chain(
                before_chain, current_chain
            )
        if identity_changed:
            cleanup_created_file()
            _reject_source(
                "private_target_identity_changed",
                "reserved CTP private runtime directory identity changed",
                "config.yaml",
            )
    finally:
        os.close(descriptor)


def _protect_target_directory(descriptor: int) -> None:
    if os.name == "posix":
        opened = os.fstat(descriptor)
        if opened.st_uid != os.geteuid():
            _reject_source(
                "private_target_owner_mismatch",
                "reserved CTP private runtime directory must be owned by the current user",
                "config.yaml",
            )
        try:
            os.fchmod(descriptor, 0o700)
        except OSError:
            _reject_source(
                "private_target_protection_failed",
                "could not restrict the reserved CTP private runtime directory permissions",
                "config.yaml",
            )
        mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
        if mode & ~0o700 or mode & 0o500 != 0o500:
            _reject_source(
                "private_target_protection_failed",
                "reserved CTP private runtime directory is not owner-only",
                "config.yaml",
            )
    elif os.name == "nt":
        _set_windows_owner_acl(descriptor, directory=True)


def _mark_windows_handle_for_deletion(handle: int) -> None:
    """Mark an opened Windows file for deletion without resolving its path again."""

    import ctypes
    from ctypes import wintypes

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = (("delete_file", wintypes.BOOLEAN),)

    disposition = _FileDispositionInfo(True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_info = kernel32.SetFileInformationByHandle
    set_info.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    set_info.restype = wintypes.BOOL
    if not set_info(
        wintypes.HANDLE(handle),
        4,  # FileDispositionInfo
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise OSError(ctypes.get_last_error(), "could not remove partial private config")


def _mark_windows_file_for_deletion(descriptor: int) -> None:
    """Mark a CRT-opened Windows file for deletion by its handle."""

    from .credential_resolver import _windows_os_handle

    _mark_windows_handle_for_deletion(_windows_os_handle(descriptor))


def _cleanup_windows_handle_conversion(output_handle, output_fd, kernel32) -> bool:
    """Delete and close whichever object owns a newly created file handle."""

    cleanup_failed = False
    if output_fd is not None:
        # Once open_osfhandle returns, the CRT descriptor owns the native
        # handle even if interruption lands before output_handle is cleared.
        try:
            _mark_windows_file_for_deletion(output_fd)
        except BaseException:
            cleanup_failed = True
        try:
            os.close(output_fd)
        except BaseException:
            cleanup_failed = True
    elif output_handle is not None and output_handle.value:
        from ctypes import wintypes

        try:
            _mark_windows_handle_for_deletion(output_handle.value)
        except BaseException:
            cleanup_failed = True
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        try:
            close_succeeded = kernel32.CloseHandle(output_handle)
        except BaseException:
            close_succeeded = False
        if not close_succeeded:
            cleanup_failed = True
    return cleanup_failed


def _create_windows_private_file_descriptor(directory_descriptor: int) -> int:
    """Create an empty protected file relative to the verified directory handle."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    from .credential_resolver import _windows_acl_for_handle, _windows_os_handle

    advapi32, kernel32, user_sid = _windows_user_sid()
    sddl = "O:{0}D:P(A;;FA;;;{0})(A;;FA;;;SY)(A;;FA;;;BA)".format(user_sid)
    security_descriptor = ctypes.c_void_p()
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    )
    convert.restype = wintypes.BOOL
    if not convert(sddl, 1, ctypes.byref(security_descriptor), None):
        raise OSError(ctypes.get_last_error())

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.USHORT),
            ("maximum_length", wintypes.USHORT),
            ("buffer", wintypes.LPWSTR),
        )

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.ULONG),
            ("root_directory", wintypes.HANDLE),
            ("object_name", ctypes.POINTER(_UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security_descriptor", ctypes.c_void_p),
            ("security_quality_of_service", ctypes.c_void_p),
        )

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = (("status", ctypes.c_void_p), ("information", ctypes.c_size_t))

    output_fd = None
    output_handle = None
    ntdll = ctypes.WinDLL("ntdll")
    cleanup_failed = False
    try:
        filename_buffer = ctypes.create_unicode_buffer("config.yaml")
        filename = _UnicodeString(
            len("config.yaml") * ctypes.sizeof(wintypes.WCHAR),
            (len("config.yaml") + 1) * ctypes.sizeof(wintypes.WCHAR),
            ctypes.cast(filename_buffer, wintypes.LPWSTR),
        )
        object_attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            wintypes.HANDLE(_windows_os_handle(directory_descriptor)),
            ctypes.pointer(filename),
            0x40,  # OBJ_CASE_INSENSITIVE
            security_descriptor,
            None,
        )
        io_status = _IoStatusBlock()
        create_file = ntdll.NtCreateFile
        create_file.argtypes = (
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
        create_file.restype = wintypes.LONG
        output_handle = wintypes.HANDLE()
        status = create_file(
            ctypes.byref(output_handle),
            0x40000000 | 0x00020000 | 0x00010000 | 0x00100000 | 0x00000080,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            0x00000080,  # FILE_ATTRIBUTE_NORMAL
            0,
            2,  # FILE_CREATE (fail if the name already exists)
            0x00000040 | 0x00000020,  # FILE_NON_DIRECTORY_FILE | synchronous I/O
            None,
            0,
        )
        if status < 0:
            if ctypes.c_uint32(status).value == 0xC0000035:  # STATUS_OBJECT_NAME_COLLISION
                raise FileExistsError(183, "config.yaml already exists")
            to_dos_error = ntdll.RtlNtStatusToDosError
            to_dos_error.argtypes = (wintypes.LONG,)
            to_dos_error.restype = wintypes.ULONG
            error_code = int(to_dos_error(status))
            raise OSError(error_code, "config.yaml could not be created")
        output_fd = msvcrt.open_osfhandle(
            output_handle.value,
            os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
        )
        output_handle = None  # the CRT descriptor now owns the Win32 handle
    finally:
        if output_handle is not None:
            cleanup_failed = (
                _cleanup_windows_handle_conversion(output_handle, output_fd, kernel32)
                or cleanup_failed
            )
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(security_descriptor)
        if cleanup_failed:
            _reject_source(
                "private_config_cleanup_failed",
                "config.yaml could not be safely removed after handle conversion failed",
                "config.yaml",
            )

    try:
        _windows_acl_for_handle(_windows_os_handle(output_fd))
    except BaseException:
        cleanup_failed = False
        try:
            _mark_windows_file_for_deletion(output_fd)
        except BaseException:
            cleanup_failed = True
        try:
            os.close(output_fd)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            _reject_source(
                "private_config_cleanup_failed",
                "config.yaml could not be safely removed after ACL verification failed",
                "config.yaml",
            )
        raise
    return output_fd


def _create_private_file(descriptor: int, target: Path, content: bytes) -> _CreatedPrivateFile:
    if os.name == "posix":
        try:
            output_fd = os.open(
                "config.yaml",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=descriptor,
            )
        except FileExistsError:
            raise RuntimeConfigError(
                CONFIG_EXISTS,
                "config.yaml already exists and will not be overwritten",
                field_path="config.yaml",
                reason="config_exists",
            ) from None
        except OSError:
            _reject_source(
                "private_config_create_failed",
                "config.yaml could not be created safely",
                "config.yaml",
            )
    else:
        try:
            output_fd = _create_windows_private_file_descriptor(descriptor)
        except FileExistsError:
            raise RuntimeConfigError(
                CONFIG_EXISTS,
                "config.yaml already exists and will not be overwritten",
                field_path="config.yaml",
                reason="config_exists",
            ) from None
        except OSError:
            _reject_source(
                "private_config_create_failed",
                "config.yaml could not be created safely",
                "config.yaml",
            )
        except RuntimeConfigError:
            raise

    retained_fd = None
    output = None
    descriptor_owned = True
    cleanup_failed = False
    delete_requested = False
    created_stat = None

    def request_delete(file_descriptor: int) -> None:
        nonlocal cleanup_failed, delete_requested
        if os.name != "nt" or delete_requested:
            return
        try:
            _mark_windows_file_for_deletion(file_descriptor)
        except BaseException:
            cleanup_failed = True
        else:
            delete_requested = True

    try:
        created_stat = os.fstat(output_fd)
        output = os.fdopen(output_fd, "wb")
        descriptor_owned = False
        with output:
            try:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
                written_stat = os.fstat(output.fileno())
                if os.name == "posix":
                    entry_stat = os.stat("config.yaml", dir_fd=descriptor, follow_symlinks=False)
                else:
                    entry_stat = os.lstat(str(target))
                    from .credential_resolver import _windows_acl_for_handle, _windows_os_handle

                    _windows_acl_for_handle(_windows_os_handle(output.fileno()))
                if (
                    not _same_identity(created_stat, written_stat)
                    or not _same_identity(created_stat, entry_stat)
                    or written_stat.st_nlink != 1
                    or written_stat.st_size != len(content)
                ):
                    raise OSError("created private config identity changed")
                if os.name == "posix" and (
                    written_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(written_stat.st_mode) & ~0o600
                    or stat.S_IMODE(written_stat.st_mode) & stat.S_IRUSR == 0
                ):
                    raise OSError("created private config permissions are unsafe")
                if os.name == "nt":
                    retained_fd = os.dup(output.fileno())
            except BaseException:
                request_delete(output.fileno())
                raise
    except BaseException as failure:
        if descriptor_owned:
            request_delete(output_fd)
            try:
                os.close(output_fd)
            except OSError:
                cleanup_failed = True
        elif output is not None and not output.closed:
            request_delete(output.fileno())
            try:
                output.close()
            except OSError:
                cleanup_failed = True
        if retained_fd is not None:
            request_delete(retained_fd)
            try:
                os.close(retained_fd)
            except BaseException:
                cleanup_failed = True
            retained_fd = None
        if os.name == "posix":
            try:
                if created_stat is None:
                    raise OSError("created file identity could not be verified")
                _unlink_posix_created_file(descriptor, created_stat)
            except BaseException:
                cleanup_failed = True
        if cleanup_failed:
            _reject_source(
                "private_config_cleanup_failed",
                "config.yaml could not be confirmed removed after a write failure",
                "config.yaml",
            )
        if not isinstance(failure, Exception):
            raise
        _reject_source(
            "private_config_write_failed",
            "config.yaml could not be written completely; partial file cleanup was completed",
            "config.yaml",
        )
    return _CreatedPrivateFile(created_stat, retained_fd)


def _normalize_source_specs(
    sources: Sequence[Tuple[Union[os.PathLike, str], str]],
) -> Tuple[Tuple[Path, str], ...]:
    if isinstance(sources, (str, bytes)):
        _reject_source(
            "source_list_invalid", "explicit sources must be supplied as path/format pairs"
        )
    try:
        items = tuple(sources)
    except TypeError:
        _reject_source(
            "source_list_invalid", "explicit sources must be supplied as path/format pairs"
        )
    if not items or len(items) > 2:
        _reject_source(
            "source_count_invalid",
            "provide one explicit source or two different explicit source formats",
        )

    normalized = []
    seen_formats = set()
    seen_paths = set()
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            _reject_source(
                "source_list_invalid",
                "each explicit source must name a path and its env, yaml or collector_yaml format",
            )
        source_path, source_format = item
        if source_format not in ("env", "yaml", "collector_yaml"):
            _reject_source("source_format_invalid", "source format must be explicitly named")
        if source_format in seen_formats:
            _reject_source(
                "source_format_duplicate",
                "provide at most one source of each explicit format",
            )
        seen_formats.add(source_format)
        try:
            source = Path(source_path).expanduser()
        except (TypeError, ValueError):
            _reject_source("source_path_invalid", "source path must be an explicit local file path")
        if not source.is_absolute():
            _reject_source(
                "source_path_must_be_absolute",
                "name the local source with an absolute path; no working-directory search is used",
            )
        identity = os.path.normcase(os.path.normpath(str(source)))
        if identity in seen_paths:
            _reject_source(
                "source_path_duplicate",
                "the same local source path cannot be supplied more than once",
            )
        seen_paths.add(identity)
        normalized.append((source, source_format))
    return tuple(normalized)


def prepare_ctp_simnow_config_sources(
    sources: Sequence[Tuple[Union[os.PathLike, str], str]],
    *,
    runtime_dir: Optional[Union[os.PathLike, str]] = None,
) -> PreparedCtpSimNowConfig:
    """Create one protected config from one or two explicitly named sources.

    Every source must be an absolute owner-only local file. All source file
    descriptors and ACLs are validated before any source bytes are read. If
    fields appear in both sources, the values must match exactly. One explicit
    exception combines a YAML ``front_pairs`` list with the complete legacy
    pair in an ``.env`` source only when that exact pair is already a listed
    candidate; the complete YAML list is retained without selecting a pair.
    The function never reads ``os.environ``, searches for files, derives
    endpoints from a profile, overwrites an existing config, or starts a
    provider.
    """

    source_specs = _normalize_source_specs(sources)
    target_dir = Path(runtime_dir) if runtime_dir is not None else CTP_SIMNOW_PRIVATE_RUNTIME_DIR
    if not target_dir.is_absolute():
        raise _error(
            "private_target_path_invalid",
            "private runtime target must be an absolute code-owned path",
            "config.yaml",
        )
    target_dir = Path(os.path.abspath(str(target_dir)))

    created_file = None
    target_descriptor = None

    def cleanup_created_file() -> None:
        nonlocal created_file
        if created_file is None:
            return
        cleanup_failed = False
        if os.name == "nt":
            retained_fd = created_file.retained_fd
            if retained_fd is None:
                return
            try:
                _mark_windows_file_for_deletion(retained_fd)
            except BaseException:
                cleanup_failed = True
            finally:
                try:
                    os.close(retained_fd)
                except BaseException:
                    cleanup_failed = True
                created_file = None
        else:
            try:
                if target_descriptor is None:
                    raise OSError("private target directory handle is unavailable")
                _unlink_posix_created_file(target_descriptor, created_file.identity)
            except BaseException:
                cleanup_failed = True
            else:
                created_file = None
        if cleanup_failed:
            _reject_source(
                "private_config_cleanup_failed",
                "config.yaml could not be confirmed removed after a target identity change",
                "config.yaml",
            )

    with _verified_target_directory(target_dir, cleanup_created_file) as target_fd:
        target_descriptor = target_fd
        if _same_directory_entry(target_fd, target_dir):
            raise RuntimeConfigError(
                CONFIG_EXISTS,
                "config.yaml already exists and will not be overwritten",
                field_path="config.yaml",
                reason="config_exists",
            )

        # Establish every source's type, identity, ownership and access policy
        # before reading even the first source's bytes. Keeping the opened
        # handles pins the validated identities through the merge.
        with ExitStack() as source_stack:
            opened_sources = []
            for source, source_format in source_specs:
                descriptor, opened = source_stack.enter_context(
                    _open_explicit_private_source(source)
                )
                opened_sources.append((source, source_format, descriptor, opened))

            values: Dict[str, Any] = {}
            source_values_by_format: Dict[str, Mapping[str, Any]] = {}
            front_pairs_source_format = None
            legacy_front_source_formats: Dict[str, str] = {}
            for source, source_format, descriptor, opened in opened_sources:
                text = _read_opened_private_source(source, descriptor, opened)
                if source_format == "env":
                    source_values = _parse_env_source(text)
                elif source_format == "collector_yaml":
                    source_values = _parse_collector_yaml_source(text)
                else:
                    source_values = _parse_yaml_source(text)
                source_values_by_format[source_format] = source_values
                if "front_pairs" in source_values:
                    front_pairs_source_format = source_format
                for name in _FRONT_PAIR_FIELDS.intersection(source_values):
                    legacy_front_source_formats[name] = source_format
                for name, value in source_values.items():
                    if name in values and values[name] != value:
                        _reject_source(
                            "source_field_conflict",
                            "explicit sources disagree on ctp_simnow.{0}".format(name),
                            "ctp_simnow.{0}".format(name),
                        )
                    values[name] = value

        if "front_pairs" in values and legacy_front_source_formats:
            env_source_values = source_values_by_format.get("env", {})
            env_has_complete_pair = all(
                name in env_source_values for name in ("md_front", "td_front")
            )
            allowed_env_pair = (
                front_pairs_source_format == "yaml"
                and env_has_complete_pair
                and legacy_front_source_formats.get("md_front") == "env"
                and legacy_front_source_formats.get("td_front") == "env"
            )
            if not allowed_env_pair:
                _reject_source(
                    "source_front_form_conflict",
                    "front_pairs may be combined with legacy fronts only from an .env pair already listed in YAML",
                    "ctp_simnow.front_pairs",
                )
            env_pair = (env_source_values["md_front"], env_source_values["td_front"])
            yaml_pairs = tuple(
                (pair["md_front"], pair["td_front"]) for pair in values["front_pairs"]
            )
            if env_pair not in yaml_pairs:
                _reject_source(
                    "source_front_pair_not_in_candidates",
                    "the explicit .env front pair must exactly match a YAML front_pairs candidate",
                    "ctp_simnow.front_pairs",
                )
            # Both environment endpoints have been explicitly checked against
            # the list, so the generated config uses the full YAML candidate
            # list and cannot lose or reorder alternatives.
            values.pop("md_front")
            values.pop("td_front")

        complete = _require_complete_values(values)
        content = _render_config(complete)
        # Run the authoritative schema parser before changing target ACLs or
        # creating a file. Errors report field names only, never source values.
        parsed = _parse_verified_runtime_config_text(
            content,
            target_dir,
            target_dir / "config.yaml",
        )
        _protect_target_directory(target_fd)
        created_file = _create_private_file(
            target_fd, target_dir / "config.yaml", content.encode("utf-8")
        )
        if os.name == "posix":
            os.fsync(target_fd)
        prepared = PreparedCtpSimNowConfig(target_dir / "config.yaml", parsed.config_digest)
    if created_file is not None and created_file.retained_fd is not None:
        os.close(created_file.retained_fd)
    return prepared


def prepare_ctp_simnow_config(
    source_path: Union[os.PathLike, str],
    *,
    source_format: str,
    runtime_dir: Optional[Union[os.PathLike, str]] = None,
) -> PreparedCtpSimNowConfig:
    """Create one protected schema-v4 SimNow config from one explicit source."""

    return prepare_ctp_simnow_config_sources(
        ((source_path, source_format),),
        runtime_dir=runtime_dir,
    )
