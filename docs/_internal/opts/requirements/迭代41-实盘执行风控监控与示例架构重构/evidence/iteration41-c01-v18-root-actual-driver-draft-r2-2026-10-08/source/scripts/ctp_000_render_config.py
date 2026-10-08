"""Render the fixed EnvRef contract to a new owner-only schema-v4 config.

Only explicit names in --allow-env are read. Check/dry-run never resolves any
environment value. Rendering requires the fixed admitted image and actual owner
token; an explicit protected dotenv source may be read only after admission.
It never loads existing destination configuration or prints private bytes.
JSON encoding is a strict YAML subset accepted by the existing schema-v4 loader.
"""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
from pathlib import Path
from types import MappingProxyType


ENV_FIELDS = {
    "md_front": "SIMNOW_MD_FRONT",
    "td_front": "SIMNOW_TD_FRONT",
    "instrument_id": "SIMNOW_INSTRUMENT_ID",
    "exchange_id": "SIMNOW_EXCHANGE_ID",
    "hedge_flag": "SIMNOW_HEDGE_FLAG",
    "broker_id": "SIMNOW_BROKER_ID",
    "user_id": "SIMNOW_USER_ID",
    "password": "SIMNOW_PASSWORD",
    "app_id": "SIMNOW_APP_ID",
    "auth_code": "SIMNOW_AUTH_CODE",
}
ENV_NAMES = frozenset(ENV_FIELDS.values())
_CTP_FIELDS = {
    "md_front": "CTP_MD_FRONT",
    "td_front": "CTP_TD_FRONT",
    "instrument_id": "CTP_INSTRUMENT",
    "exchange_id": "CTP_EXCHANGE",
    "hedge_flag": "CTP_HEDGE_FLAG",
    "broker_id": "CTP_BROKER_ID",
    "user_id": "CTP_USER_ID",
    "password": "CTP_PASSWORD",
    "app_id": "CTP_APP_ID",
    "auth_code": "CTP_AUTH_CODE",
}
PAIRED_FRONT_PROFILE = "SIMNOW_ENV_ACCOUNT_CTP_SELECTED_FRONTS"
MAX_PUBLIC_PROJECTION_BYTES = 8192
_SELECTED_FRONT_FIELDS = {
    field: name for field, name in _CTP_FIELDS.items() if field not in {"md_front", "td_front"}
}
_SELECTED_FRONT_FIELDS.update(user_id="SIMNOW_USER_ID", password="SIMNOW_PASSWORD")
ENV_PROFILES = MappingProxyType(
    {
        "SIMNOW_ENV_ALL": MappingProxyType(dict(ENV_FIELDS)),
        "CTP_ENV_ALL": MappingProxyType(_CTP_FIELDS),
        "SIMNOW_ENV_ACCOUNT_CTP_SETTINGS": MappingProxyType(
            {
                **_CTP_FIELDS,
                "user_id": "SIMNOW_USER_ID",
                "password": "SIMNOW_PASSWORD",
            }
        ),
        PAIRED_FRONT_PROFILE: MappingProxyType(_SELECTED_FRONT_FIELDS),
    }
)
RECOMMENDED_PROFILE = "SIMNOW_ENV_ACCOUNT_CTP_SETTINGS"
ALL_ENV_NAMES = frozenset(name for fields in ENV_PROFILES.values() for name in fields.values())
MAX_ENV_FILE_BYTES = 64 * 1024
_ENV_FAILURES = frozenset(
    {
        "explicit_environment_source_required",
        "env_file_path_invalid",
        "env_file_unavailable",
        "env_file_size_invalid",
        "env_file_syntax_invalid",
        "env_file_selected_name_duplicate",
        "env_file_selected_name_missing",
        "env_file_value_invalid",
        "env_file_identity_invalid",
        "env_file_identity_changed",
    }
)
_FRONT_FAILURES = frozenset(
    {
        "paired_front_source_required",
        "paired_front_confirmation_required",
        "paired_front_profile_required",
        "paired_front_path_invalid",
        "paired_front_projection_unavailable",
        "paired_front_projection_invalid",
        "paired_front_selection_unavailable",
        "no_current_transport_candidate",
        "explicit_transport_probe_confirmation_required",
        "current_transport_observation_unavailable",
        "current_transport_observation_invalid",
        "current_transport_pair_binding_invalid",
        "current_transport_observation_expired",
        "transport_handoff_clock_invalid",
        "transport_handoff_projection_mismatch",
        "transport_handoff_expired",
        "transport_handoff_custody_mismatch",
        "transport_handoff_already_consumed",
    }
)


class RenderError(ValueError):
    pass


def _source_selection(env_file, process_env):
    if type(process_env) is not bool or (env_file is None) == (not process_env):
        raise RenderError("explicit_environment_source_required")
    if env_file is None:
        return None
    if type(env_file) is not str or not 0 < len(env_file) <= 1024 or "\x00" in env_file:
        raise RenderError("env_file_path_invalid")
    # Local drive only: no UNC/device namespace, ADS, relative path or traversal.
    path = env_file.replace("/", "\\")
    drive, tail = ntpath.splitdrive(path)
    if (
        re.fullmatch(r"[A-Za-z]:", drive) is None
        or not tail.startswith("\\")
        or ":" in tail
        or ntpath.normpath(path) != path
        or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", part.split(".")[0])
            or any(ord(char) < 32 or char in '<>"|?*' for char in part)
            for part in tail[1:].split("\\")
        )
    ):
        raise RenderError("env_file_path_invalid")
    return path


def _paired_front_source(profile, paired_fronts_json, confirm_transport_only):
    if type(confirm_transport_only) is not bool:
        raise RenderError("paired_front_confirmation_required")
    if paired_fronts_json is None:
        if confirm_transport_only or profile == PAIRED_FRONT_PROFILE:
            raise RenderError("paired_front_source_required")
        return None
    if not confirm_transport_only:
        raise RenderError("paired_front_confirmation_required")
    if profile != PAIRED_FRONT_PROFILE:
        raise RenderError("paired_front_profile_required")
    if (
        type(paired_fronts_json) is not str
        or not 0 < len(paired_fronts_json) <= 1024
        or "\x00" in paired_fronts_json
    ):
        raise RenderError("paired_front_path_invalid")
    path = paired_fronts_json.replace("/", "\\")
    drive, tail = ntpath.splitdrive(path)
    if (
        re.fullmatch(r"[A-Za-z]:", drive) is None
        or not tail.startswith("\\")
        or ":" in tail
        or ntpath.normpath(path) != path
        or path[-5:].lower() != ".json"
        or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", part.split(".")[0])
            or any(ord(char) < 32 or char in '<>"|?*' for char in part)
            for part in tail[1:].split("\\")
        )
    ):
        raise RenderError("paired_front_path_invalid")
    return path


def _read_public_projection(path):
    try:
        with open(path, "rb") as stream:
            raw = stream.read(MAX_PUBLIC_PROJECTION_BYTES + 1)
    except Exception:
        raise RenderError("paired_front_projection_unavailable") from None
    if not 0 < len(raw) <= MAX_PUBLIC_PROJECTION_BYTES:
        raise RenderError("paired_front_projection_invalid")
    try:
        from scripts.ctp_000_paired_front_selector import parse_document

        parse_document(raw)
    except Exception:
        raise RenderError("paired_front_projection_invalid") from None
    return raw


def _parse_env_file(raw, expected):
    """Restricted literal dotenv grammar; decode only selected-name values.

    Single-line NAME=value / export NAME=value, optional enclosing quotes and
    comments are supported. No escapes, interpolation or command substitution
    are evaluated. Unselected assignment bodies are never decoded or resolved.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ENV_FILE_BYTES:
        raise RenderError("env_file_size_invalid")
    values = {}
    for line in raw.removeprefix(b"\xef\xbb\xbf").splitlines():
        line = line.strip()
        if not line or line.startswith(b"#"):
            continue
        match = re.match(rb"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=", line)
        if match is None:
            raise RenderError("env_file_syntax_invalid")
        name = match[1].decode("ascii").upper()
        if name not in expected:
            continue
        if name in values:
            raise RenderError("env_file_selected_name_duplicate")
        value = line[match.end() :].strip()
        if value[:1] in (b"'", b'"'):
            quote = value[:1]
            end = value.find(quote, 1)
            if end < 0 or (
                value[end + 1 :].strip() and not value[end + 1 :].strip().startswith(b"#")
            ):
                raise RenderError("env_file_syntax_invalid")
            value = value[1:end]
        else:
            value = re.split(rb"[ \t]+#", value, maxsplit=1)[0].rstrip()
        if any(token in value for token in (b"${", b"$(", b"`", b"\x00", b"\r", b"\n")):
            raise RenderError("env_file_value_invalid")
        try:
            text = value.decode("utf-8")
        except UnicodeError:
            raise RenderError("env_file_value_invalid") from None
        if not 0 < len(text) <= 1024:
            raise RenderError("env_file_value_invalid")
        values[name] = text
    if set(values) != set(expected):
        raise RenderError("env_file_selected_name_missing")
    return values


def _private_paths(principals):
    from scripts.ctp_i13_i15_guardian_deployment_anchor import _ProtectedWindowsPaths

    class PrivatePaths(_ProtectedWindowsPaths):
        def _open_one(self, *args, **kwargs):
            self._opening = True
            try:
                return super()._open_one(*args, **kwargs)
            finally:
                self._opening = False

        def _close_raw(self, handle):
            closed = super()._close_raw(handle)
            # The base acquisition path has not inserted an ACL-rejected handle
            # into _entries yet. Retain a failed close there; already registered
            # handles stay in _entries and must not also become duplicate orphans.
            if (
                not closed
                and getattr(self, "_opening", False)
                and handle not in self._orphan_handles
                and not any(entry.handle == handle for entry in self._entries.values())
            ):
                self._orphan_handles.append(handle)
            return closed

    return PrivatePaths(principals)


class _PrivateEnvFile:
    """Retain existing protected Windows handles until destination work ends."""

    def __init__(self, path, owner_sid, expected):
        self.values = {}
        principals = frozenset({owner_sid, "S-1-5-18", "S-1-5-32-544"})
        self.paths = _private_paths(principals)
        try:
            # This opens every ancestor and the file with no write/delete sharing.
            self.paths.add_paths([path], reader_sids_by_path={path: principals})
            self.entry = self.paths._entries[self.paths._key(path)]
            self.snapshot = self._facts()
            raw = self.paths.read_file(path, max_bytes=MAX_ENV_FILE_BYTES)
            self.verify_current()
            self.values = _parse_env_file(raw, expected)
        except BaseException:
            self.close()
            raise

    def _facts(self):
        from backtrader_runtime.credential_resolver import _windows_acl_for_handle

        self.paths.verify_current()
        info = self.paths._file_information(self.entry.handle)
        size = (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow)
        if info.nNumberOfLinks != 1 or info.dwFileAttributes & (0x400 | 0x10):
            raise RenderError("env_file_identity_invalid")
        if not 0 < size <= MAX_ENV_FILE_BYTES:
            raise RenderError("env_file_size_invalid")
        # Exact actual process owner, protected DACL, only owner/SYSTEM/admin ACEs.
        _windows_acl_for_handle(self.entry.handle)
        return (
            int(info.dwVolumeSerialNumber),
            int(info.nFileIndexHigh),
            int(info.nFileIndexLow),
            size,
            int(info.ftLastWriteTimeHigh),
            int(info.ftLastWriteTimeLow),
        )

    def verify_current(self):
        if self._facts() != self.snapshot:
            raise RenderError("env_file_identity_changed")

    def close(self):
        self.values.clear()
        self.paths.close()  # Existing helper retains failed-close handles for retry.


def _selected_fields(profile, allow_env):
    if type(profile) is not str or profile not in ENV_PROFILES:
        raise RenderError("explicit_envref_profile_required")
    if any(type(name) is not str or not name.isascii() for name in allow_env):
        raise RenderError("exact_envref_grants_required")
    names = [name.upper() for name in allow_env]
    expected = set(ENV_PROFILES[profile].values())
    if len(names) != len(set(names)) or set(names) != expected:
        raise RenderError("exact_envref_grants_required")
    return ENV_PROFILES[profile]


def _windows_env_keys(environment, expected):
    """Normalize names only, rejecting case-colliding synthetic/dotenv mappings.

    Real Windows os.environ uppercases keys. This explicit adapter gives inert
    mappings the same semantics without silently preferring one spelling. No
    unselected variable value is read and no credential-namespace fallback exists.
    """
    selected = {}
    for name in environment.keys():
        if type(name) is not str or not name.isascii() or name.upper() not in expected:
            continue
        canonical = name.upper()
        if canonical in selected:
            raise RenderError("ambiguous_environment_name")
        selected[canonical] = name
    if set(selected) != set(expected):
        raise RenderError("selected_environment_name_missing")
    return selected


def _render_bytes(allow_env, environment, config_path, *, profile=None, selected_front_pair=None):
    # This function returns private in-memory bytes to the fixed writer only;
    # it neither seals a runtime nor grants provider or trading authority.
    selected_fields = _selected_fields(profile, allow_env)
    try:
        selected_keys = _windows_env_keys(environment, set(selected_fields.values()))
        fields = {}
        for field, name in selected_fields.items():
            value = environment[selected_keys[name]]
            if (
                type(value) is not str
                or not 0 < len(value) <= 1024
                or any(c in value for c in "\x00\r\n")
            ):
                raise RenderError("envref_value_invalid")
            fields[field] = value
        if profile == PAIRED_FRONT_PROFILE:
            from scripts.ctp_000_front_handoff import SelectedFrontPair

            if (
                type(selected_front_pair) is not SelectedFrontPair
                or selected_front_pair.execution_authority != "NONE"
                or type(selected_front_pair.config_index) is not int
                or type(selected_front_pair.md_front) is not str
                or type(selected_front_pair.td_front) is not str
                or type(selected_front_pair.degraded_candidate) is not bool
            ):
                raise RenderError("paired_front_selection_unavailable")
            fronts = [
                {
                    "md_front": selected_front_pair.md_front,
                    "td_front": selected_front_pair.td_front,
                }
            ]
        else:
            if selected_front_pair is not None:
                raise RenderError("paired_front_profile_required")
            fronts = [{"md_front": fields.pop("md_front"), "td_front": fields.pop("td_front")}]
        value = {
            "config_schema_version": 4,
            "strategy": {"id": "example.000_live_certification.simnow_penetration"},
            "runtime": {"mode": "simulation", "preset": "sandbox"},
            "parameters": {},
            "secrets_ref": "config_yaml",
            "ctp": {"front_pairs": fronts, **fields},
        }
        from backtrader_runtime.config import _validate_schema

        path = Path(config_path)
        _validate_schema(value, path.parent, path)
        return (
            json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("ascii")
    except Exception:
        raise RenderError("envref_or_schema_invalid") from None


def render_fixed_config(
    allow_env,
    *,
    profile=None,
    env_file=None,
    process_env=False,
    paired_fronts_json=None,
    confirm_transport_only=False,
):
    fields = _selected_fields(profile, allow_env)
    env_file = _source_selection(env_file, process_env)
    paired_fronts_json = _paired_front_source(profile, paired_fronts_json, confirm_transport_only)
    from scripts.ctp_000_install_admission import load_install_context
    from scripts.ctp_000_install_windows import WindowsInstallApi
    from backtrader_runtime.credential_resolver import (
        _open_windows_metadata_handle,
        _windows_acl_for_handle,
        _windows_os_handle,
    )
    from scripts.ctp_i13_i15_guardian_deployment_anchor import _ProtectedWindowsPaths

    # Pins, actual process/image and owner custody all precede environment reads.
    with load_install_context() as context:
        api = WindowsInstallApi()
        sid = api.current_user_sid()
        if sid in {"S-1-5-18", "S-1-5-32-544"} or sid != context.client_sid:
            raise RenderError("config_owner_scope_mismatch")
        path = Path(context.config_path)
        ancestors = _ProtectedWindowsPaths(frozenset({"S-1-5-18", "S-1-5-32-544"}))
        parent = None
        created = None
        source = None
        try:
            directory = str(path.parent)
            ancestors.add_paths(
                [directory],
                directory_paths=frozenset({directory}),
                writer_sids_by_path={directory: frozenset({sid, "S-1-5-18", "S-1-5-32-544"})},
            )
            parent = _open_windows_metadata_handle(path.parent, is_directory=True)
            _windows_acl_for_handle(_windows_os_handle(parent))
            if path.exists():
                raise RenderError("existing_private_config_refused")
            context.verify_current()
            selected_front_pair = None
            if paired_fronts_json is not None:
                # Current selection and exact-byte handoff precede any
                # credential-source read or process-environment lookup.
                projection = _read_public_projection(paired_fronts_json)
                from scripts.ctp_000_front_handoff import (
                    FrontHandoffError,
                    create_current_handoff,
                )

                try:
                    current = create_current_handoff(
                        projection, confirm_transport_only=confirm_transport_only
                    )
                    selected_front_pair = current.consume(projection)
                except FrontHandoffError as error:
                    reason = str(error)
                    if reason in _FRONT_FAILURES:
                        raise RenderError(reason) from None
                    raise RenderError("paired_front_selection_unavailable") from None
            if env_file is not None:
                try:
                    source = _PrivateEnvFile(env_file, sid, set(fields.values()))
                except RenderError:
                    raise
                except Exception:
                    raise RenderError("env_file_unavailable") from None
                environment = source.values
            else:
                environment = os.environ
            context.verify_current()
            raw = _render_bytes(
                allow_env,
                environment,
                path,
                profile=profile,
                selected_front_pair=selected_front_pair,
            )
            created = api.create_file(str(path), owner_sid=sid)
            created.verify_owner_acl()
            identity = created.identity()  # single-link, non-reparse retained file
            created.write(raw)
            created.verify_owner_acl()
            if created.identity() != identity:
                raise RenderError("private_config_identity_changed")
            ancestors.verify_current()
            context.verify_current()
            if source is not None:
                source.verify_current()
            # Never emit a config digest: it would fingerprint low-entropy secrets.
            return {
                "status": "CONFIG_CREATED",
                "authority": "NO_WRITE / LIVE_NO_GO",
                "provider_started": False,
            }
        except RenderError:
            raise
        except Exception:
            # A created incomplete file stays owner-only and is never overwritten,
            # read back, removed by guessed path, or reported as successful.
            raise RenderError("private_config_creation_unverified") from None
        finally:
            try:
                if created is not None:
                    created.close()
            finally:
                try:
                    if source is not None:
                        source.close()
                finally:
                    try:
                        if parent is not None:
                            os.close(parent)
                    finally:
                        ancestors.close()


def _grant_argument(name):
    if not name.isascii():
        raise argparse.ArgumentTypeError("ASCII environment name required")
    return name.upper()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("check", "dry-run", "render"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--envref-profile", choices=sorted(ENV_PROFILES))
    parser.add_argument("--paired-fronts-json", metavar="PUBLIC_PATH")
    parser.add_argument("--confirm-transport-only", action="store_true")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--env-file", metavar="PRIVATE_PATH")
    source.add_argument("--process-env", action="store_true")
    parser.add_argument(
        "--allow-env",
        action="append",
        type=_grant_argument,
        choices=sorted(ALL_ENV_NAMES),
        default=[],
    )
    args = parser.parse_args(argv)
    try:
        if not args.render:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "selected_profile": args.envref_profile,
                        "recommended_profile": RECOMMENDED_PROFILE,
                        "profiles": {name: dict(fields) for name, fields in ENV_PROFILES.items()},
                        "environment_read": False,
                        "env_file_read": False,
                        "selected_source": "file"
                        if args.env_file is not None
                        else "process"
                        if args.process_env
                        else None,
                        "paired_front_source_supplied": args.paired_fronts_json is not None,
                        "transport_probe_confirmed": args.confirm_transport_only,
                        "transport_probe_started": False,
                        "private_created": False,
                        "authority": "NO_WRITE / LIVE_NO_GO",
                    }
                )
            )
            return 2
        result = render_fixed_config(
            args.allow_env,
            profile=args.envref_profile,
            env_file=args.env_file,
            process_env=args.process_env,
            paired_fronts_json=args.paired_fronts_json,
            confirm_transport_only=args.confirm_transport_only,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_OR_INCOMPLETE",
                    "reason": str(error)
                    if type(error) is RenderError
                    and str(error) in (_ENV_FAILURES | _FRONT_FAILURES)
                    else "fixed_config_render_unavailable",
                    "provider_started": False,
                }
            )
        )
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
