"""Unregistered I8 identity-unverified, one-shot MD diagnostic candidate.

The retained I8 wheel and isolated interpreter have code-owned pins and a
verified installed RECORD. Independent reproducibility review remains pending.
The public module entry is a supervised, one-shot launcher. Its permanent
owner-only latch blocks every retry, including after a clean exit. Its
diagnostic receipt is not preflight acceptance, and this module is not
registered or exposed by the CLI.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import stat
import sys
import ctypes
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .capability_imports import trusted_installed_capability_import_context
from .credential_resolver import (
    CredentialResolutionError,
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from .ctp_artifact_provenance import CtpArtifactProvenanceError
from .ctp_i8_oneshot_md_readonly import (
    CtpI8OneShotMdDiagnosticEvidence,
    CtpI8OneShotMdObservation,
    probe_i8_oneshot_md_readonly,
)
from .ctp_readonly_job_supervisor import (
    FailClosedLatch,
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
    ValueFreeReceiptSchema,
    parse_single_json_receipt,
    run_readonly_child,
)
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from .registry import require_effective_runtime_config_seal, validate_runtime_config


_STATUS_VALUES = ("diagnostic_complete", "incomplete", "rejected")
_REASON_VALUES = (
    "arguments_not_allowed",
    "configuration_rejected",
    "credential_rejected",
    "front_selection_rejected",
    "identity_unverified_tick_observed",
    "i8_adapter_unavailable",
    "market_observation_incomplete",
    "market_probe_rejected",
    "native_join_pending",
    "native_shutdown_uncertain",
    "runtime_policy_rejected",
    "sdk_artifact_rejected",
    "sdk_artifact_unavailable",
    "supervisor_context_required",
)
_STAGE_VALUES = (
    "arguments",
    "configuration",
    "credentials",
    "front_selection",
    "market_data",
    "sdk_artifact",
)
_EVIDENCE_LEVEL_VALUES = ("unavailable", "partial", "complete")
_CLOSE_STATE_VALUES = (
    "not_started",
    "native_stop_method_unknown",
    "stop_failed",
    "native_stop_receipt_unknown",
    "native_stop_receipt_inconsistent",
    "native_join_state_unknown",
    "native_join_pending",
    "native_stop_incomplete",
    "stop_returned",
    "unavailable",
)
_PRIMARY_ERROR_VALUES = (
    "admission_invalid",
    "credential_account_mismatch",
    "probe_deadline_expired",
    "market_client_type_required",
    "market_client_state_unavailable",
    "market_front_binding_mismatch",
    "market_client_identity_mismatch",
    "market_login_identity_mismatch",
    "market_subscription_rejected",
    "market_front_disconnected",
    "market_probe_failed",
    "market_login_timeout",
    "subscription_ack_timeout",
    "matching_tick_not_observed",
    "market_observation_incomplete",
    "unavailable",
)
_LOGIN_DISPOSITION_VALUES = (
    "none",
    "stale_spi",
    "generation_mismatch",
    "request_id_type_invalid",
    "request_id_mismatch",
    "nonterminal",
    "accepted",
    "identity_unverified",
    "provider_rejected",
    "identity_rejected",
    "terminal",
    "unavailable",
)
_LOGIN_REQUEST_RELATION_VALUES = (
    "not_observed",
    "invalid",
    "zero",
    "lower",
    "equal",
    "higher",
    "unavailable",
)
_LOGIN_RESPONSE_ERROR_VALUES = (
    "not_observed",
    "missing",
    "invalid",
    "zero",
    "nonzero",
    "unavailable",
)
_LOGIN_ID_SHAPE_VALUES = (
    "not_observed",
    "unreadable",
    "empty",
    "ascii_mismatch",
    "nonascii_or_replacement",
    "whitespace_or_control",
    "exact_match",
    "unavailable",
)
_LOGIN_TRADING_DAY_SHAPE_VALUES = (
    "not_observed",
    "unreadable",
    "empty",
    "invalid_format",
    "invalid_calendar",
    "valid",
    "unavailable",
)
_NATIVE_FIELD_SHAPE_VALUES = (
    "not_observed",
    "unreadable",
    "empty",
    "nonempty_terminated",
    "unterminated",
    "unavailable",
)
_LOGIN_CALLBACK_COUNT_VALUES = ("zero", "one", "multiple", "unavailable")
_I8_EVIDENCE_BOOL_FIELDS = (
    "client_stop_returned",
    "identity_unverified",
    "matching_tick_observed",
    "market_login_ready",
    "native_join_pending",
    "native_shutdown_uncertain",
    "probe_session_closed",
    "same_trading_day_observed",
    "subscription_acknowledged",
)
_I8_EVIDENCE_ENUM_FIELDS = {
    "close_state": _CLOSE_STATE_VALUES,
    "evidence_level": _EVIDENCE_LEVEL_VALUES,
    "login_broker_id_shape": _LOGIN_ID_SHAPE_VALUES,
    "login_callback_count": _LOGIN_CALLBACK_COUNT_VALUES,
    "login_callback_disposition": _LOGIN_DISPOSITION_VALUES,
    "login_request_id_relation": _LOGIN_REQUEST_RELATION_VALUES,
    "login_response_error_status": _LOGIN_RESPONSE_ERROR_VALUES,
    "login_trading_day_shape": _LOGIN_TRADING_DAY_SHAPE_VALUES,
    "login_user_id_shape": _LOGIN_ID_SHAPE_VALUES,
    "native_broker_id_shape": _NATIVE_FIELD_SHAPE_VALUES,
    "native_user_id_shape": _NATIVE_FIELD_SHAPE_VALUES,
}
_I8_COMPLETE_EVIDENCE_VALUES = {
    "close_state": "stop_returned",
    "evidence_level": "complete",
    "identity_unverified": True,
    "login_broker_id_shape": "empty",
    "login_callback_count": "one",
    "login_callback_disposition": "identity_unverified",
    "login_request_id_relation": "zero",
    "login_response_error_status": "zero",
    "login_trading_day_shape": "valid",
    "login_user_id_shape": "empty",
    "matching_tick_observed": True,
    "market_login_ready": False,
    "native_broker_id_shape": "empty",
    "native_join_pending": False,
    "native_shutdown_uncertain": False,
    "native_user_id_shape": "empty",
    "primary_error": None,
    "probe_session_closed": True,
    "same_trading_day_observed": True,
    "subscription_acknowledged": True,
    "client_stop_returned": True,
}

I8_CHILD_RECEIPT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "close_state": _CLOSE_STATE_VALUES,
        "evidence_level": _EVIDENCE_LEVEL_VALUES,
        "login_broker_id_shape": _LOGIN_ID_SHAPE_VALUES,
        "login_callback_count": _LOGIN_CALLBACK_COUNT_VALUES,
        "login_callback_disposition": _LOGIN_DISPOSITION_VALUES,
        "login_request_id_relation": _LOGIN_REQUEST_RELATION_VALUES,
        "login_response_error_status": _LOGIN_RESPONSE_ERROR_VALUES,
        "login_trading_day_shape": _LOGIN_TRADING_DAY_SHAPE_VALUES,
        "login_user_id_shape": _LOGIN_ID_SHAPE_VALUES,
        "native_broker_id_shape": _NATIVE_FIELD_SHAPE_VALUES,
        "native_user_id_shape": _NATIVE_FIELD_SHAPE_VALUES,
        "reason": _REASON_VALUES,
        "stage": _STAGE_VALUES,
        "status": _STATUS_VALUES,
    },
    bool_fields=("order_submission_authorized",),
    nullable_enum_fields={"primary_error": _PRIMARY_ERROR_VALUES},
    nullable_bool_fields=_I8_EVIDENCE_BOOL_FIELDS,
)

# Reviewed no-system-site-packages I8 installation. This path is code-owned;
# neither config, CLI arguments, nor environment may replace it.
_I8_RUNTIME_ROOT = Path(r"D:\temp\i8-readonly-installed-wheel-venv-a7d9b04")
_I8_INTERPRETER = _I8_RUNTIME_ROOT / "Scripts" / "python.exe"
_I8_BASE_PYTHON_ROOT = Path(r"C:\anaconda3")
_I8_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR / "state" / "i8-readonly-md-supervisor-no-retry.latch"
)
_I8_LATCH_CONTENT = b"i8-readonly-md-attempted-v1\n"
_I8_JOB_HANDLE_ENV = "bt_i8_parent_job_handle"
_I8_RETAINED_JOB_CONTROL: Optional[object] = None
_I8_CHILD_ENTRY_SOURCE = (
    "from backtrader_runtime.ctp_i8_oneshot_md_diagnostic import "
    "_run_child_entry; raise SystemExit(_run_child_entry())"
)


class _PersistentI8NoRetryLatch:
    """Owner-only permanent reservation; this diagnostic cannot be rerun."""

    _latch_content = _I8_LATCH_CONTENT

    def __init__(self, path: Path = _I8_LATCH_PATH) -> None:
        self._path = Path(path)
        self._attempt_reserved = False

    def _verify_ancestor_chain(self) -> None:
        def _scan() -> None:
            current = Path(self._path.anchor)
            for component in self._path.parts[1:-1]:
                current = current / component
                result = os.lstat(current)
                if (
                    stat.S_ISLNK(result.st_mode)
                    or bool(getattr(result, "st_file_attributes", 0) & 0x400)
                    or not stat.S_ISDIR(result.st_mode)
                ):
                    raise OSError("latch_ancestor_invalid")

        if self._path == _I8_LATCH_PATH:
            registry = iteration41_runtime_registry()
            registration = registry.require_runtime_dir(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)
            if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
                raise OSError("latch_runtime_registration_invalid")
            with registry.verified_runtime_directory(registration):
                _scan()
            return
        _scan()

    @contextmanager
    def _verified_directory(self):
        directory = self._path.parent
        self._verify_ancestor_chain()
        before = os.lstat(directory)
        if (
            stat.S_ISLNK(before.st_mode)
            or bool(getattr(before, "st_file_attributes", 0) & 0x400)
            or not stat.S_ISDIR(before.st_mode)
        ):
            raise OSError("latch_directory_invalid")
        descriptor: Optional[int] = None
        if os.name == "nt":
            from .credential_resolver import (
                _open_windows_metadata_handle,
                _windows_acl_for_handle,
                _windows_os_handle,
            )

            descriptor = _open_windows_metadata_handle(directory, is_directory=True)
            opened = os.fstat(descriptor)
            _windows_acl_for_handle(_windows_os_handle(descriptor))
        elif os.name == "posix":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(directory, flags)
            opened = os.fstat(descriptor)
            if (
                opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & ~0o700
                or stat.S_IMODE(opened.st_mode) & 0o700 != 0o700
            ):
                os.close(descriptor)
                raise OSError("latch_directory_not_private")
        else:
            raise OSError("latch_platform_unsupported")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            os.close(descriptor)
            raise OSError("latch_directory_identity_changed")
        try:
            after = os.lstat(directory)
            if (
                stat.S_ISLNK(after.st_mode)
                or bool(getattr(after, "st_file_attributes", 0) & 0x400)
                or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise OSError("latch_directory_identity_changed")
            yield descriptor if os.name == "posix" else None
            self._verify_ancestor_chain()
            after = os.lstat(directory)
            final_opened = os.fstat(descriptor)
            if (
                stat.S_ISLNK(after.st_mode)
                or bool(getattr(after, "st_file_attributes", 0) & 0x400)
                or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
                or (final_opened.st_dev, final_opened.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise OSError("latch_directory_identity_changed")
        finally:
            os.close(descriptor)

    def _read_file(self, directory_fd: Optional[int]) -> Optional[bool]:
        try:
            before = (
                os.stat(self._path.name, dir_fd=directory_fd, follow_symlinks=False)
                if directory_fd is not None
                else os.lstat(self._path)
            )
        except FileNotFoundError:
            return False
        if (
            stat.S_ISLNK(before.st_mode)
            or bool(getattr(before, "st_file_attributes", 0) & 0x400)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise OSError("latch_file_invalid")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if directory_fd is not None:
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._path.name, flags, dir_fd=directory_fd)
        else:
            descriptor = os.open(self._path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise OSError("latch_file_identity_changed")
            if os.name == "nt":
                from .credential_resolver import _windows_acl_for_handle, _windows_os_handle

                _windows_acl_for_handle(_windows_os_handle(descriptor))
            elif opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) & ~0o600:
                raise OSError("latch_file_not_private")
            content = bytearray()
            while len(content) <= len(self._latch_content):
                chunk = os.read(descriptor, len(self._latch_content) + 1 - len(content))
                if not chunk:
                    break
                content.extend(chunk)
            final = (
                os.stat(self._path.name, dir_fd=directory_fd, follow_symlinks=False)
                if directory_fd is not None
                else os.lstat(self._path)
            )
            final_opened = os.fstat(descriptor)
            if (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino) or (
                final_opened.st_dev,
                final_opened.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                raise OSError("latch_file_identity_changed")
            if bytes(content) != self._latch_content:
                raise OSError("latch_file_poisoned")
            return True
        finally:
            os.close(descriptor)

    def _read_marker(self) -> Optional[bool]:
        with self._verified_directory() as directory_fd:
            return self._read_file(directory_fd)

    def _write_marker(self) -> bool:
        with self._verified_directory() as directory_fd:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                descriptor = (
                    os.open(self._path.name, flags, 0o600, dir_fd=directory_fd)
                    if directory_fd is not None
                    else os.open(self._path, flags, 0o600)
                )
            except FileExistsError:
                return False
            try:
                if os.name == "nt":
                    self._set_windows_file_acl()
                else:
                    os.fchmod(descriptor, 0o600)
                written = os.write(descriptor, self._latch_content)
                if written != len(self._latch_content):
                    raise OSError("latch_write_incomplete")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return self._read_marker() is True

    def _set_windows_file_acl(self) -> None:
        import msvcrt
        from ctypes import wintypes

        from .ctp_private_config_setup import _set_windows_owner_acl

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
            str(self._path),
            0x00020000 | 0x00040000 | 0x80000000 | 0x40000000,
            0x00000001 | 0x00000002,
            None,
            3,
            0x00200000,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle or handle == -1:
            raise OSError(ctypes.get_last_error(), "latch_acl_handle_unavailable")
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDWR | os.O_BINARY)
        try:
            _set_windows_owner_acl(descriptor, directory=False)
        finally:
            os.close(descriptor)

    def begin_attempt(self) -> bool:
        """Atomically commit a permanent no-retry marker before child creation."""

        if self._attempt_reserved:
            return False
        if self._read_marker() is True:
            return False
        if not self._write_marker():
            return False
        self._attempt_reserved = True
        return True

    def is_tripped(self) -> bool:
        present = self._read_marker()
        return False if self._attempt_reserved and present is True else present is True

    def trip(self, _reason: str) -> bool:
        """The durable reservation itself is the no-retry trip state."""

        return self._read_marker() is True or self._write_marker()


def _emit_i8(
    *,
    status: str,
    reason: str,
    stage: str,
    evidence_level: str = "unavailable",
    close_state: str = "unavailable",
    primary_error: Optional[str] = "unavailable",
    login_callback_count: str = "unavailable",
    login_callback_disposition: str = "unavailable",
    login_request_id_relation: str = "unavailable",
    login_response_error_status: str = "unavailable",
    login_broker_id_shape: str = "unavailable",
    login_user_id_shape: str = "unavailable",
    login_trading_day_shape: str = "unavailable",
    native_broker_id_shape: str = "unavailable",
    native_user_id_shape: str = "unavailable",
    identity_unverified: Optional[bool] = None,
    market_login_ready: Optional[bool] = None,
    subscription_acknowledged: Optional[bool] = None,
    matching_tick_observed: Optional[bool] = None,
    same_trading_day_observed: Optional[bool] = None,
    client_stop_returned: Optional[bool] = None,
    native_join_pending: Optional[bool] = None,
    native_shutdown_uncertain: Optional[bool] = None,
    probe_session_closed: Optional[bool] = None,
) -> None:
    """Write only the child's strict value-free supervisor receipt."""

    payload = {
        "client_stop_returned": _nullable_bool(client_stop_returned),
        "close_state": close_state if close_state in _CLOSE_STATE_VALUES else "unavailable",
        "evidence_level": (
            evidence_level if evidence_level in _EVIDENCE_LEVEL_VALUES else "unavailable"
        ),
        "identity_unverified": _nullable_bool(identity_unverified),
        "login_broker_id_shape": (
            login_broker_id_shape
            if login_broker_id_shape in _LOGIN_ID_SHAPE_VALUES
            else "unavailable"
        ),
        "login_callback_count": (
            login_callback_count
            if login_callback_count in _LOGIN_CALLBACK_COUNT_VALUES
            else "unavailable"
        ),
        "login_callback_disposition": (
            login_callback_disposition
            if login_callback_disposition in _LOGIN_DISPOSITION_VALUES
            else "unavailable"
        ),
        "login_request_id_relation": (
            login_request_id_relation
            if login_request_id_relation in _LOGIN_REQUEST_RELATION_VALUES
            else "unavailable"
        ),
        "login_response_error_status": (
            login_response_error_status
            if login_response_error_status in _LOGIN_RESPONSE_ERROR_VALUES
            else "unavailable"
        ),
        "login_trading_day_shape": (
            login_trading_day_shape
            if login_trading_day_shape in _LOGIN_TRADING_DAY_SHAPE_VALUES
            else "unavailable"
        ),
        "login_user_id_shape": (
            login_user_id_shape if login_user_id_shape in _LOGIN_ID_SHAPE_VALUES else "unavailable"
        ),
        "matching_tick_observed": _nullable_bool(matching_tick_observed),
        "market_login_ready": _nullable_bool(market_login_ready),
        "native_broker_id_shape": (
            native_broker_id_shape
            if native_broker_id_shape in _NATIVE_FIELD_SHAPE_VALUES
            else "unavailable"
        ),
        "native_join_pending": _nullable_bool(native_join_pending),
        "native_shutdown_uncertain": _nullable_bool(native_shutdown_uncertain),
        "native_user_id_shape": (
            native_user_id_shape
            if native_user_id_shape in _NATIVE_FIELD_SHAPE_VALUES
            else "unavailable"
        ),
        "order_submission_authorized": False,
        "primary_error": (
            primary_error
            if primary_error is None or primary_error in _PRIMARY_ERROR_VALUES
            else "unavailable"
        ),
        "probe_session_closed": _nullable_bool(probe_session_closed),
        "reason": reason if reason in _REASON_VALUES else "runtime_policy_rejected",
        "same_trading_day_observed": _nullable_bool(same_trading_day_observed),
        "stage": stage if stage in _STAGE_VALUES else "configuration",
        "status": status if status in _STATUS_VALUES else "rejected",
        "subscription_acknowledged": _nullable_bool(subscription_acknowledged),
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _nullable_bool(value: object) -> Optional[bool]:
    return value if type(value) is bool else None


def _i8_evidence_receipt_fields(value: object) -> dict[str, object]:
    """Project only fields from the exact frozen adapter evidence type."""

    unavailable: dict[str, object] = dict.fromkeys(_I8_EVIDENCE_ENUM_FIELDS, "unavailable")
    unavailable["primary_error"] = "unavailable"
    unavailable.update(dict.fromkeys(_I8_EVIDENCE_BOOL_FIELDS))
    unavailable.update(
        market_login_ready=None,
        native_shutdown_uncertain=None,
        probe_session_closed=None,
    )
    if type(value) is not CtpI8OneShotMdDiagnosticEvidence:
        return unavailable

    projected = dict(unavailable)
    for name, allowed in _I8_EVIDENCE_ENUM_FIELDS.items():
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if type(item) is str and item in allowed:
            projected[name] = item
    try:
        primary_error = value.primary_error
    except Exception:
        primary_error = "unavailable"
    if primary_error is None or (
        type(primary_error) is str and primary_error in _PRIMARY_ERROR_VALUES
    ):
        projected["primary_error"] = primary_error
    for name in _I8_EVIDENCE_BOOL_FIELDS:
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if item is None or type(item) is bool:
            projected[name] = item

    close_state = projected["close_state"]
    evidence_level = projected["evidence_level"]
    if evidence_level == "complete":
        projected.update(
            market_login_ready=False,
            native_shutdown_uncertain=False,
            probe_session_closed=True,
        )
    elif close_state == "stop_returned":
        projected.update(native_shutdown_uncertain=False, probe_session_closed=True)
    elif close_state not in {"unavailable", "not_started"}:
        projected.update(native_shutdown_uncertain=True, probe_session_closed=False)
    return projected


def parse_i8_child_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    """Parse one duplicate-free I8 receipt against its exact enum schema."""

    return parse_single_json_receipt(raw, I8_CHILD_RECEIPT_SCHEMA)


def _candidate_front_pair(front_pair: object) -> tuple[str, str]:
    try:
        td_front = front_pair.get("td_front")
        md_front = front_pair.get("md_front")
    except Exception:
        td_front = md_front = None
    if type(td_front) is not str or type(md_front) is not str:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed CTP front pair is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    return td_front, md_front


def _selected_front_index(selection: object, front_pairs: tuple[Any, ...]) -> int:
    try:
        index = selection.config_index
        pair = selection.pair
        selected_pair = (pair.td_front, pair.md_front)
    except Exception:
        index = None
        selected_pair = None
    if type(index) is not int or not 0 <= index < len(front_pairs):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the selected CTP front pair index is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    if selected_pair != _candidate_front_pair(front_pairs[index]):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the selected CTP front pair does not match sealed config",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_mismatch",
        )
    return index


def _validate_bound_scope(
    private: object, admission: object, index: int, front_pairs: tuple[Any, ...]
) -> None:
    try:
        expected = (
            private.instrument_id,
            private.exchange_id,
            private.hedge_flag,
        )
        admitted = (
            admission.instrument_id,
            admission.exchange_id,
            admission.hedge_flag,
        )
        fronts = (admission.td_front, admission.md_front)
    except Exception:
        expected = admitted = fronts = None
    if (
        expected is None
        or admitted != expected
        or fronts != _candidate_front_pair(front_pairs[index])
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the admitted CTP scope does not match the sealed configuration",
            field_path="ctp.instrument_id",
            reason="ctp_simnow_preflight_front_selection_mismatch",
        )


def _validate_observation(observation: object, admission: object) -> bool:
    return (
        type(observation) is CtpI8OneShotMdObservation
        and _i8_evidence_receipt_fields(getattr(observation, "diagnostic_evidence", None))
        == _I8_COMPLETE_EVIDENCE_VALUES
        and type(getattr(admission, "md_front", None)) is str
        and type(getattr(admission, "instrument_id", None)) is str
        and type(getattr(admission, "exchange_id", None)) is str
        and type(getattr(admission, "account_fingerprint_sha256", None)) is str
        and observation.md_front_sha256
        == hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
        and observation.account_fingerprint_sha256 == admission.account_fingerprint_sha256
        and observation.instrument_id == admission.instrument_id
        and observation.exchange_id == admission.exchange_id
        and observation.identity_unverified is True
        and observation.market_login_ready is False
        and observation.subscription_acknowledged is True
        and observation.matching_tick_observed is True
        and observation.same_trading_day_observed is True
        and observation.client_stop_returned is True
        and observation.native_join_pending is False
        and observation.probe_session_closed is True
        and observation.order_submission_authorized is False
        and type(observation.trading_writes) is int
        and observation.trading_writes == 0
        and type(observation.settlement_writes) is int
        and observation.settlement_writes == 0
    )


def _reason_for_exception(error: BaseException, stage: str) -> str:
    if isinstance(error, CtpArtifactProvenanceError):
        return (
            "sdk_artifact_unavailable"
            if error.reason == "artifact_pin_unavailable"
            else "sdk_artifact_rejected"
        )
    if isinstance(error, CredentialResolutionError):
        return "credential_rejected"
    if isinstance(error, RuntimeConfigError):
        return {
            "configuration": "configuration_rejected",
            "front_selection": "front_selection_rejected",
        }.get(stage, "runtime_policy_rejected")
    return "market_probe_rejected" if stage == "market_data" else "runtime_policy_rejected"


def _fixed_i8_child_command() -> Optional[FixedChildCommand]:
    """Build the only approved child command, failing closed if its venv moved."""

    if os.name != "nt":
        return None
    try:
        interpreter_info = os.lstat(_I8_INTERPRETER)
        venv_info = os.lstat(_I8_RUNTIME_ROOT / "pyvenv.cfg")
        if (
            not Path(_I8_INTERPRETER).is_file()
            or getattr(interpreter_info, "st_file_attributes", 0) & 0x400
            or getattr(venv_info, "st_file_attributes", 0) & 0x400
        ):
            return None
        venv_config = (_I8_RUNTIME_ROOT / "pyvenv.cfg").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    normalized = {line.strip().casefold() for line in venv_config.splitlines()}
    if (
        "include-system-site-packages = false" not in normalized
        or "version = 3.11.5" not in normalized
        or "home = c:\\anaconda3" not in normalized
    ):
        return None

    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    if type(system_root) is not str or not Path(system_root).is_absolute():
        return None
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP")
    if type(temp_dir) is not str or not Path(temp_dir).is_absolute():
        return None

    env = {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": ";".join(
            (
                str(_I8_INTERPRETER.parent),
                str(_I8_BASE_PYTHON_ROOT),
                str(Path(system_root) / "System32"),
            )
        ),
        "TEMP": temp_dir,
        "TMP": temp_dir,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
    }
    try:
        return FixedChildCommand(
            (
                str(_I8_INTERPRETER),
                "-c",
                _I8_CHILD_ENTRY_SOURCE,
            ),
            Path(__file__).resolve().parents[1],
            env,
            job_handle_env_name=_I8_JOB_HANDLE_ENV,
        )
    except (OSError, TypeError, ValueError):
        return None


def _run_diagnostic_impl(argv: Optional[Sequence[str]] = None) -> int:
    """Private fixed-scope child body; the public function rejects direct use."""

    if tuple(sys.argv[1:] if argv is None else argv):
        _emit_i8(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    logging.disable(logging.CRITICAL)
    stage = "configuration"
    try:
        registry = iteration41_runtime_registry()
        effective = validate_runtime_config(
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
            registry,
        )
        require_effective_runtime_config_seal(effective, registry)

        from .ctp_simnow_operator import (
            CtpSimNowConfigReadOnlyBinding,
            _select_configured_front_pair,
        )

        registration = registry.require_runtime_dir(effective.config.strategy_dir)
        if (
            registration is not effective.registration
            or registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
        ):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the configured runtime registration changed",
                field_path="runtime.preset",
                reason="runtime_registration_mismatch",
            )
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        if type(binding) is not CtpSimNowConfigReadOnlyBinding:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the registered runtime does not have the config-driven CTP binding",
                field_path="runtime.preset",
                reason="ctp_simnow_preflight_front_policy_required",
            )
        private, _, unvalidated_pairs = binding._sealed_private_config(effective, registry)
        if type(unvalidated_pairs) is not tuple or not 1 <= len(unvalidated_pairs) <= 8:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the sealed CTP front pair set is invalid",
                field_path="ctp.front_pairs",
                reason="ctp_simnow_preflight_front_selection_required",
            )

        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            from .ctp_artifact_provenance import (
                verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts,
            )

            candidate_td, candidate_md = _candidate_front_pair(unvalidated_pairs[0])
            # No TCP selection, credentials, or SDK import precedes this gate.
            verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                td_front=candidate_td,
                md_front=candidate_md,
            )

            stage = "front_selection"
            selection = _select_configured_front_pair(unvalidated_pairs)
            selected_index = _selected_front_index(selection, unvalidated_pairs)
            admission, scope = binding._route(
                effective,
                registry,
                selected_front_pair=selection.pair,
            )
            _validate_bound_scope(private, admission, selected_index, unvalidated_pairs)
            verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                td_front=admission.td_front,
                md_front=admission.md_front,
            )

            stage = "credentials"
            credentials = resolve_runtime_credentials(effective, registry, scope)
            require_resolved_runtime_credentials_seal(credentials, effective, registry, scope)
            from .ctp_simnow_readonly_runtime import _SealedCtpCredentialSource

            credential_source = _SealedCtpCredentialSource(
                credentials,
                effective,
                registry,
                scope,
            )

            stage = "market_data"
            with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
                sdk_module = importlib.import_module("bt_api_ctp.ctp.client")
                client_type = getattr(sdk_module, "OneShotMdDiagnosticClient")
                stop_receipt_type = getattr(sdk_module, "CtpNativeStopReceipt")
                observation = probe_i8_oneshot_md_readonly(
                    admission=admission,
                    credential_source=credential_source,
                    client_type=client_type,
                    stop_receipt_type=stop_receipt_type,
                    expected_diagnostic_instrument=admission.instrument_id,
                    timeout_seconds=15.0,
                )

        evidence_fields = _i8_evidence_receipt_fields(
            getattr(observation, "diagnostic_evidence", None)
        )
        if not _validate_observation(observation, admission):
            join_pending = evidence_fields["native_join_pending"] is True
            _emit_i8(
                status="incomplete" if join_pending else "rejected",
                reason="native_join_pending" if join_pending else "market_observation_incomplete",
                stage="market_data",
                **evidence_fields,
            )
            return 3 if join_pending else 2

        _emit_i8(
            status="diagnostic_complete",
            reason="identity_unverified_tick_observed",
            stage="market_data",
            **evidence_fields,
        )
        return 0
    except Exception as error:
        evidence_fields = _i8_evidence_receipt_fields(
            getattr(error, "i8_diagnostic_evidence", None)
        )
        close_state = evidence_fields["close_state"]
        join_pending = close_state == "native_join_pending"
        uncertain_close = evidence_fields["native_shutdown_uncertain"] is True or (
            close_state in _CLOSE_STATE_VALUES
            and close_state not in {"unavailable", "not_started", "stop_returned"}
        )
        _emit_i8(
            status="incomplete" if uncertain_close else "rejected",
            reason=(
                "native_join_pending"
                if join_pending
                else "native_shutdown_uncertain"
                if uncertain_close
                else _reason_for_exception(error, stage)
            ),
            stage=stage,
            **evidence_fields,
        )
    return 3 if uncertain_close else 2


def run_diagnostic(argv: Optional[Sequence[str]] = None) -> int:
    """Reject direct calls; provider work is available only through the Job child."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    _emit_i8(
        status="rejected",
        reason="arguments_not_allowed" if arguments else "supervisor_context_required",
        stage="arguments",
    )
    return 2


def _supervise_i8_child(
    fail_closed_latch: Optional[FailClosedLatch],
    *,
    runner: Callable[..., SupervisedResult] = run_readonly_child,
) -> SupervisedResult:
    """Run the fixed I8 child under the strict Job supervisor.

    The caller supplies only the durable no-retry latch. The command, venv,
    repository root, and environment are code-owned. The latch must persist
    uncertainty across process restarts.
    """

    global _I8_RETAINED_JOB_CONTROL
    command = _fixed_i8_child_command()
    begin_attempt = getattr(fail_closed_latch, "begin_attempt", None)
    if command is None or not callable(begin_attempt):
        return SupervisedResult(
            "supervisor_error",
            "i8_runtime_or_latch_unavailable",
            None,
            ProcessEvidence(False, False, False, None, None, False, None, None, "unavailable"),
        )
    try:
        if begin_attempt() is not True:
            return SupervisedResult(
                "latched",
                "prior_attempt_or_poisoned_latch",
                None,
                ProcessEvidence(False, False, False, None, None, False, None, None, "latched"),
            )
        result = runner(
            command,
            parse_i8_child_receipt,
            receipt_schema=I8_CHILD_RECEIPT_SCHEMA,
            fail_closed_latch=fail_closed_latch,
            deadline_seconds=45.0,
            max_stdout_bytes=16 * 1024,
            termination_grace_seconds=5.0,
        )
    except Exception:
        return SupervisedResult(
            "supervisor_error",
            "i8_supervisor_failed",
            None,
            ProcessEvidence(False, False, False, None, None, False, None, None, "unavailable"),
        )
    if type(result) is not SupervisedResult:
        return SupervisedResult(
            "supervisor_error",
            "i8_supervisor_result_invalid",
            None,
            ProcessEvidence(False, False, False, None, None, False, None, None, "unavailable"),
        )
    if result.retained_control is not None:
        _I8_RETAINED_JOB_CONTROL = result.retained_control
    if _parent_confirms_i8_diagnostic(result):
        return SupervisedResult(
            "diagnostic_complete",
            "identity_unverified_tick_observed",
            result.sdk_receipt,
            result.process_evidence,
            result.retained_control,
        )
    exact_receipt = _exact_i8_child_receipt(result.sdk_receipt)
    if exact_receipt is not None:
        if exact_receipt["status"] == "rejected":
            status, reason = "rejected", "child_diagnostic_rejected"
        elif exact_receipt["status"] == "diagnostic_complete":
            status, reason = "incomplete", "parent_completion_evidence_missing"
        else:
            status, reason = "incomplete", "child_diagnostic_incomplete"
        return SupervisedResult(
            status,
            reason,
            exact_receipt,
            result.process_evidence,
            result.retained_control,
        )
    if result.status == "diagnostic_complete":
        return SupervisedResult(
            "incomplete",
            "parent_completion_evidence_missing",
            result.sdk_receipt,
            result.process_evidence,
            result.retained_control,
        )
    return result


def supervise_i8_child() -> SupervisedResult:
    """Launch only the code-owned one-shot child with the durable latch."""

    return _supervise_i8_child(_PersistentI8NoRetryLatch())


def _parent_confirms_i8_diagnostic(result: object) -> bool:
    """Accept only the exact successful child receipt plus parent OS evidence."""

    if type(result) is not SupervisedResult:
        return False
    receipt = result.sdk_receipt
    evidence = result.process_evidence
    exact_receipt = _exact_i8_child_receipt(receipt)
    if exact_receipt is None:
        return False
    expected_fields = (
        set(I8_CHILD_RECEIPT_SCHEMA.enum_fields)
        | set(I8_CHILD_RECEIPT_SCHEMA.bool_fields)
        | set(I8_CHILD_RECEIPT_SCHEMA.nullable_enum_fields)
        | set(I8_CHILD_RECEIPT_SCHEMA.nullable_bool_fields)
    )
    required_true = {
        "client_stop_returned",
        "identity_unverified",
        "matching_tick_observed",
        "probe_session_closed",
        "same_trading_day_observed",
        "subscription_acknowledged",
    }
    if (
        set(exact_receipt) != expected_fields
        or any(
            exact_receipt.get(name) != value for name, value in _I8_COMPLETE_EVIDENCE_VALUES.items()
        )
        or exact_receipt.get("status") != "diagnostic_complete"
        or exact_receipt.get("reason") != "identity_unverified_tick_observed"
        or exact_receipt.get("stage") != "market_data"
        or any(exact_receipt.get(name) is not True for name in required_true)
        or any(
            exact_receipt.get(name) is not False
            for name in (
                "market_login_ready",
                "native_join_pending",
                "native_shutdown_uncertain",
                "order_submission_authorized",
            )
        )
        or type(evidence) is not ProcessEvidence
    ):
        return False
    return (
        result.status == "child_exited"
        and result.reason == "child_process_exited"
        and type(evidence.process_created) is bool
        and evidence.process_created is True
        and type(evidence.job_assignment_observed) is bool
        and evidence.job_assignment_observed is True
        and type(evidence.process_resumed) is bool
        and evidence.process_resumed is True
        and type(evidence.process_exit_observed) is bool
        and evidence.process_exit_observed is True
        and type(evidence.process_exit_code) is int
        and evidence.process_exit_code == 0
        and type(evidence.job_termination_requested) is bool
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and type(evidence.job_empty_observed) is bool
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _exact_i8_child_receipt(value: object) -> Optional[dict[str, object]]:
    """Revalidate a parent-held receipt against the exact child schema."""

    if type(value) is not dict:
        return None
    try:
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    parsed = parse_i8_child_receipt(encoded)
    if type(parsed) is not dict or parsed != value:
        return None
    return parsed


def _is_current_process_in_job() -> bool:
    """Require membership in the exact inherited supervisor Job Object."""

    if os.name != "nt":
        return False
    raw_handle = os.environ.pop(_I8_JOB_HANDLE_ENV, None)
    if (
        type(raw_handle) is not str
        or not raw_handle.isdecimal()
        or len(raw_handle) > 20
        or int(raw_handle) <= 0
    ):
        return False
    job_handle = ctypes.c_void_p(int(raw_handle))
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        is_process_in_job = kernel32.IsProcessInJob
        is_process_in_job.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        )
        is_process_in_job.restype = ctypes.c_int
        in_job = ctypes.c_int()
        result = (
            bool(is_process_in_job(kernel32.GetCurrentProcess(), job_handle, ctypes.byref(in_job)))
            and in_job.value != 0
        )
        return result
    except Exception:
        return False
    finally:
        try:
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(job_handle)
        except Exception:
            pass


def _run_child_entry() -> int:
    """Private child entry; direct module execution goes through ``main``."""

    if not _is_current_process_in_job():
        _emit_i8(
            status="rejected",
            reason="supervisor_context_required",
            stage="arguments",
        )
        return 2
    return _run_diagnostic_impl(())


def _result_to_parent_payload(result: SupervisedResult) -> dict[str, object]:
    evidence = result.process_evidence
    return {
        "process_evidence": {
            "containment": evidence.containment,
            "job_assignment_observed": evidence.job_assignment_observed,
            "job_empty_observed": evidence.job_empty_observed,
            "job_termination_call_succeeded": evidence.job_termination_call_succeeded,
            "job_termination_requested": evidence.job_termination_requested,
            "process_created": evidence.process_created,
            "process_exit_code": evidence.process_exit_code,
            "process_exit_observed": evidence.process_exit_observed,
            "process_resumed": evidence.process_resumed,
        },
        "reason": result.reason,
        "sdk_receipt": result.sdk_receipt,
        "status": result.status,
    }


def main() -> int:
    """Public module entry: reserve once, supervise, and report both evidence channels."""

    if tuple(sys.argv[1:]):
        _emit_i8(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    result = supervise_i8_child()
    sys.stdout.write(json.dumps(_result_to_parent_payload(result), sort_keys=True) + "\n")
    sys.stdout.flush()
    if result.status == "diagnostic_complete":
        return 0
    return 3 if result.status in {"pending_native_join", "timed_out"} else 2


if __name__ == "__main__":  # pragma: no cover - one-shot child only
    raise SystemExit(main())


__all__ = [
    "CtpI8OneShotMdObservation",
    "I8_CHILD_RECEIPT_SCHEMA",
    "main",
    "parse_i8_child_receipt",
]
