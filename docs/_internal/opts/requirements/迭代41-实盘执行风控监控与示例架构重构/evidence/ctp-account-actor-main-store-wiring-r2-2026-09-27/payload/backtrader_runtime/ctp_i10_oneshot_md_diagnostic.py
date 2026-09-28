"""Unregistered I10 one-shot market-data diagnostic composition candidate.

This module is deliberately separate from the registered I2 preflight. Its
only worker path is a fixed Windows Job child; the child reads the exact sealed
013_3 sandbox profile, probes only configured fronts, verifies the I10 wheel,
then resolves credentials and makes one read-only MD observation. Receipts
contain fixed categories and booleans only. This is diagnostic evidence, not
runtime admission or trading authority.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import logging
import os
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .capability_imports import trusted_installed_capability_import_context
from .credential_resolver import (
    CredentialResolutionError,
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from .ctp_artifact_provenance import (
    CtpArtifactProvenanceError,
    verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts,
)
from .ctp_i10_attempt_latch import (
    I10_LATCH_PATH,
    I10_SOURCE_COMMIT,
    PersistentI10OneShotAttemptLatch,
)
from .ctp_i10_oneshot_md_readonly import (
    CtpI10OneShotMdObservation,
    probe_i10_oneshot_md_readonly,
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
from .registry import RuntimeProfile, require_effective_runtime_config_seal, validate_runtime_config


_I10_EXPECTED_SOURCE_COMMIT = "a6253a58b1ebca11f58c8836fbed757d0daf7582"
_I10_RUNTIME_ROOT = Path(r"D:\temp\i10-runtime-env-20260925")
_I10_INTERPRETER = _I10_RUNTIME_ROOT / "Scripts" / "python.exe"
_I10_WHEEL_A_ROOT = Path(r"D:\temp\i10-final-wheel-repro-20260925\artifacts\a")
_I10_BASE_PYTHON_ROOT = Path(r"C:\anaconda3")
_I10_JOB_HANDLE_ENV = "bt_i10_parent_job_handle"
_I10_CHILD_ENTRY_SOURCE = (
    "from backtrader_runtime.ctp_i10_oneshot_md_diagnostic import "
    "_run_child_entry; raise SystemExit(_run_child_entry())"
)
_I10_TOTAL_DEADLINE_SECONDS = 45.0
_I10_MARKET_DEADLINE_SECONDS = 15.0
_I10_TERMINATION_GRACE_SECONDS = 5.0
_I10_MAX_STDOUT_BYTES = 16 * 1024
_I10_RETAINED_JOB_CONTROL: object | None = None

_STATUS_VALUES = ("diagnostic_complete", "incomplete", "rejected")
_REASON_VALUES = (
    "arguments_not_allowed",
    "child_diagnostic_incomplete",
    "child_diagnostic_rejected",
    "configuration_rejected",
    "credential_rejected",
    "front_selection_rejected",
    "i10_adapter_unavailable",
    "market_observation_incomplete",
    "market_probe_rejected",
    "matching_tick_observed",
    "native_join_pending",
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
_LOGIN_IDENTITY_VALUES = ("verified", "identity_unverified", "unavailable")
_ZERO_OR_UNAVAILABLE = ("zero", "unavailable")

I10_CHILD_RECEIPT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "login_identity_state": _LOGIN_IDENTITY_VALUES,
        "reason": _REASON_VALUES,
        "stage": _STAGE_VALUES,
        "status": _STATUS_VALUES,
        "settlement_writes": _ZERO_OR_UNAVAILABLE,
        "trading_writes": _ZERO_OR_UNAVAILABLE,
    },
    nullable_enum_fields={},
    bool_fields=(
        "account_ready",
        "market_login_ready",
        "order_submission_authorized",
        "trading_ready",
    ),
    nullable_bool_fields=(
        "client_stop_returned",
        "matching_tick_observed",
        "native_join_pending",
        "probe_session_closed",
        "same_trading_day_observed",
        "subscription_acknowledged",
    ),
)


def _emit_i10(
    *,
    status: str,
    reason: str,
    stage: str,
    login_identity_state: str = "unavailable",
    client_stop_returned: Optional[bool] = None,
    matching_tick_observed: Optional[bool] = None,
    native_join_pending: Optional[bool] = None,
    probe_session_closed: Optional[bool] = None,
    same_trading_day_observed: Optional[bool] = None,
    subscription_acknowledged: Optional[bool] = None,
) -> None:
    """Emit one schema-bound receipt without values from config/provider data."""

    payload: dict[str, object] = {
        "account_ready": False,
        "client_stop_returned": _nullable_bool(client_stop_returned),
        "login_identity_state": (
            login_identity_state
            if login_identity_state in _LOGIN_IDENTITY_VALUES
            else "unavailable"
        ),
        "market_login_ready": False,
        "matching_tick_observed": _nullable_bool(matching_tick_observed),
        "native_join_pending": _nullable_bool(native_join_pending),
        "order_submission_authorized": False,
        "probe_session_closed": _nullable_bool(probe_session_closed),
        "reason": reason if reason in _REASON_VALUES else "runtime_policy_rejected",
        "same_trading_day_observed": _nullable_bool(same_trading_day_observed),
        "settlement_writes": "zero",
        "stage": stage if stage in _STAGE_VALUES else "configuration",
        "status": status if status in _STATUS_VALUES else "rejected",
        "subscription_acknowledged": _nullable_bool(subscription_acknowledged),
        "trading_ready": False,
        "trading_writes": "zero",
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _nullable_bool(value: object) -> Optional[bool]:
    return value if type(value) is bool else None


def parse_i10_child_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    """Parse one duplicate-free I10 receipt against its exact schema."""

    return parse_single_json_receipt(raw, I10_CHILD_RECEIPT_SCHEMA)


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


def _require_exact_profile(effective: object, registry: object) -> tuple[Any, Any, Any]:
    """Require the exact registered 013_3 simulation/sandbox profile."""

    try:
        config = effective.config
        registration = registry.require_runtime_dir(config.strategy_dir)
        profile = registration.profile_for("simulation", "sandbox")
        sealed_profile = effective.profile
        profile_facts = (
            type(profile) is RuntimeProfile
            and profile.mode == "simulation"
            and profile.preset == "sandbox"
            and profile.allowed_parameter_keys == ()
            and profile.allowed_secrets_refs == ("config_yaml",)
            and profile.available_capabilities == ()
            and profile.approval_receipt_digest is None
            and profile.runner_module is None
            and profile.runner_entrypoint == "run_runtime"
            and profile.capability_modules == ()
            and profile.offline_managed_execution is False
            and profile.sandbox_write_policy == "deny"
        )
    except Exception:
        config = registration = profile = sealed_profile = None
        profile_facts = False
    if (
        registration is not effective.registration
        or registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
        or effective.mode != "simulation"
        or effective.preset != "sandbox"
        or sealed_profile is not profile
        or not profile_facts
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the exact sealed I10 sandbox profile is required",
            field_path="runtime.preset",
            reason="runtime_profile_mismatch",
        )
    return config, registration, profile


def _selected_front_index(selection: object, front_pairs: tuple[Any, ...]) -> int:
    from .ctp_front_pair_probe import CtpConfiguredFrontPair, CtpFrontPairSelection

    if type(selection) is not CtpFrontPairSelection:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the configured CTP front probe did not return a selection",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    index = selection.config_index
    pair = selection.pair
    if (
        type(index) is not int
        or not 0 <= index < len(front_pairs)
        or type(pair) is not CtpConfiguredFrontPair
        or (pair.td_front, pair.md_front) != _candidate_front_pair(front_pairs[index])
    ):
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
        expected = (private.instrument_id, private.exchange_id, private.hedge_flag)
        admitted = (admission.instrument_id, admission.exchange_id, admission.hedge_flag)
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
            "the admitted CTP scope does not match sealed config",
            field_path="ctp.instrument_id",
            reason="ctp_simnow_preflight_front_selection_mismatch",
        )


def _validate_observation(observation: object, admission: object) -> bool:
    return (
        type(observation) is CtpI10OneShotMdObservation
        and type(getattr(admission, "md_front", None)) is str
        and type(getattr(admission, "instrument_id", None)) is str
        and type(getattr(admission, "exchange_id", None)) is str
        and type(getattr(admission, "account_fingerprint_sha256", None)) is str
        and type(observation.md_front_sha256) is str
        and observation.md_front_sha256
        == hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
        and type(observation.account_fingerprint_sha256) is str
        and observation.account_fingerprint_sha256 == admission.account_fingerprint_sha256
        and type(observation.instrument_id) is str
        and observation.instrument_id == admission.instrument_id
        and type(observation.exchange_id) is str
        and observation.exchange_id == admission.exchange_id
        and type(observation.connection_generation) is int
        and observation.connection_generation > 0
        and type(observation.login_identity_state) is str
        and observation.login_identity_state in {"verified", "identity_unverified"}
        and observation.subscription_acknowledged is True
        and observation.matching_tick_observed is True
        and observation.same_trading_day_observed is True
        and observation.client_stop_returned is True
        and observation.native_join_pending is False
        and observation.probe_session_closed is True
        and observation.market_login_ready is False
        and observation.account_ready is False
        and observation.trading_ready is False
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
            if getattr(error, "reason", None) == "artifact_pin_unavailable"
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


def _run_diagnostic_impl(argv: Optional[Sequence[str]] = None) -> int:
    """Private fixed-scope body that still verifies Job and latch itself."""

    if tuple(sys.argv[1:] if argv is None else argv):
        _emit_i10(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    if not _has_supervised_i10_attempt_context():
        _emit_i10(status="rejected", reason="supervisor_context_required", stage="arguments")
        return 2
    logging.disable(logging.CRITICAL)
    stage = "configuration"
    try:
        if I10_SOURCE_COMMIT != _I10_EXPECTED_SOURCE_COMMIT:
            raise RuntimeError("i10_source_commit_mismatch")
        registry = iteration41_runtime_registry()
        effective = validate_runtime_config(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, registry)
        require_effective_runtime_config_seal(effective, registry)
        config, registration, _profile = _require_exact_profile(effective, registry)
        if config.strategy_dir != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the sealed I10 profile directory changed",
                field_path="runtime.preset",
                reason="runtime_profile_mismatch",
            )

        from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding

        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        if type(binding) is not CtpSimNowConfigReadOnlyBinding:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the exact config-driven read-only binding is required",
                field_path="runtime.preset",
                reason="ctp_simnow_preflight_front_policy_required",
            )
        private, bound_registration, unvalidated_pairs = binding._sealed_private_config(
            effective, registry
        )
        if (
            bound_registration is not registration
            or type(unvalidated_pairs) is not tuple
            or not 1 <= len(unvalidated_pairs) <= 8
        ):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the sealed I10 front set is invalid",
                field_path="ctp.front_pairs",
                reason="ctp_simnow_preflight_front_selection_required",
            )

        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            candidate_td, candidate_md = _candidate_front_pair(unvalidated_pairs[0])
            # This pin check precedes configured-front network probing and all credentials.
            verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                td_front=candidate_td,
                md_front=candidate_md,
            )

            stage = "front_selection"
            from .ctp_simnow_operator import _select_configured_front_pair

            selection = _select_configured_front_pair(unvalidated_pairs)
            selected_index = _selected_front_index(selection, unvalidated_pairs)
            admission, scope = binding._route(
                effective,
                registry,
                selected_front_pair=selection.pair,
                selected_config_index=selected_index,
            )
            _validate_bound_scope(private, admission, selected_index, unvalidated_pairs)
            # Rebind the pin decision to the exact probed pair before credentials.
            verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
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
            sdk_module = importlib.import_module("bt_api_ctp.ctp.client")
            client_type = getattr(sdk_module, "OneShotMdDiagnosticClient")
            stop_receipt_type = getattr(sdk_module, "CtpNativeStopReceipt")
            observation = probe_i10_oneshot_md_readonly(
                admission=admission,
                credential_source=credential_source,
                client_type=client_type,
                stop_receipt_type=stop_receipt_type,
                timeout_seconds=_I10_MARKET_DEADLINE_SECONDS,
            )

        if not _validate_observation(observation, admission):
            join_pending = getattr(observation, "native_join_pending", None) is True
            _emit_i10(
                status="incomplete" if join_pending else "rejected",
                reason="native_join_pending" if join_pending else "market_observation_incomplete",
                stage="market_data",
                login_identity_state=getattr(observation, "login_identity_state", "unavailable"),
                client_stop_returned=getattr(observation, "client_stop_returned", None),
                matching_tick_observed=getattr(observation, "matching_tick_observed", None),
                native_join_pending=getattr(observation, "native_join_pending", None),
                probe_session_closed=getattr(observation, "probe_session_closed", None),
                same_trading_day_observed=getattr(observation, "same_trading_day_observed", None),
                subscription_acknowledged=getattr(observation, "subscription_acknowledged", None),
            )
            return 3 if join_pending else 2

        _emit_i10(
            status="diagnostic_complete",
            reason="matching_tick_observed",
            stage="market_data",
            login_identity_state=observation.login_identity_state,
            client_stop_returned=True,
            matching_tick_observed=True,
            native_join_pending=False,
            probe_session_closed=True,
            same_trading_day_observed=True,
            subscription_acknowledged=True,
        )
        return 0
    except Exception as error:
        _emit_i10(
            status="rejected",
            reason=_reason_for_exception(error, stage),
            stage=stage,
        )
        return 2


def run_diagnostic(argv: Optional[Sequence[str]] = None) -> int:
    """Reject direct calls; provider work requires the supervised child path."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    _emit_i10(
        status="rejected",
        reason="arguments_not_allowed" if arguments else "supervisor_context_required",
        stage="arguments",
    )
    return 2


def _is_concrete_path(path: Path, *, directory: bool) -> bool:
    """Reject reparse points and type changes along a code-owned path."""

    if not path.is_absolute():
        return False
    parts = path.parts
    if not parts:
        return False
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            return False
        should_be_directory = index < len(parts) - 1 or directory
        if should_be_directory and not stat.S_ISDIR(info.st_mode):
            return False
        if not should_be_directory and not stat.S_ISREG(info.st_mode):
            return False
    return True


def _fixed_i10_child_command() -> Optional[FixedChildCommand]:
    """Return only the code-owned I10 wheel-A venv command on Windows."""

    if os.name != "nt" or I10_SOURCE_COMMIT != _I10_EXPECTED_SOURCE_COMMIT:
        return None
    if (
        not _is_concrete_path(_I10_RUNTIME_ROOT, directory=True)
        or not _is_concrete_path(_I10_INTERPRETER, directory=False)
        or not _is_concrete_path(_I10_RUNTIME_ROOT / "pyvenv.cfg", directory=False)
        or not _is_concrete_path(_I10_WHEEL_A_ROOT, directory=True)
    ):
        return None
    try:
        venv_config = (_I10_RUNTIME_ROOT / "pyvenv.cfg").read_text(encoding="utf-8")
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
                str(_I10_INTERPRETER.parent),
                str(_I10_BASE_PYTHON_ROOT),
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
            (str(_I10_INTERPRETER), "-c", _I10_CHILD_ENTRY_SOURCE),
            Path(__file__).resolve().parents[1],
            env,
            job_handle_env_name=_I10_JOB_HANDLE_ENV,
        )
    except (OSError, TypeError, ValueError):
        return None


def _supervise_i10_child(
    fail_closed_latch: Optional[FailClosedLatch],
    *,
    runner: Optional[Callable[..., SupervisedResult]] = None,
) -> SupervisedResult:
    """Reserve I10 once, then use the fixed Windows Job and total deadline."""

    global _I10_RETAINED_JOB_CONTROL
    command = _fixed_i10_child_command()
    begin_attempt = getattr(fail_closed_latch, "begin_attempt", None)
    if command is None or not callable(begin_attempt):
        return SupervisedResult(
            "supervisor_error",
            "i10_runtime_or_latch_unavailable",
            None,
            _empty_evidence("unavailable"),
        )
    try:
        if begin_attempt() is not True:
            return SupervisedResult(
                "latched",
                "prior_attempt_or_poisoned_latch",
                None,
                _empty_evidence("latched"),
            )
        active_runner = runner or run_readonly_child
        result = active_runner(
            command,
            parse_i10_child_receipt,
            receipt_schema=I10_CHILD_RECEIPT_SCHEMA,
            fail_closed_latch=fail_closed_latch,
            deadline_seconds=_I10_TOTAL_DEADLINE_SECONDS,
            max_stdout_bytes=_I10_MAX_STDOUT_BYTES,
            termination_grace_seconds=_I10_TERMINATION_GRACE_SECONDS,
        )
    except Exception:
        return SupervisedResult(
            "supervisor_error",
            "i10_supervisor_failed",
            None,
            _empty_evidence("unavailable"),
        )
    if type(result) is not SupervisedResult:
        return SupervisedResult(
            "supervisor_error",
            "i10_supervisor_result_invalid",
            None,
            _empty_evidence("unavailable"),
        )
    if result.retained_control is not None:
        _I10_RETAINED_JOB_CONTROL = result.retained_control
    if _parent_confirms_i10_diagnostic(result):
        return SupervisedResult(
            "diagnostic_complete",
            "matching_tick_observed",
            _exact_i10_child_receipt(result.sdk_receipt),
            result.process_evidence,
            result.retained_control,
        )
    exact_receipt = _exact_i10_child_receipt(result.sdk_receipt)
    if exact_receipt is not None:
        if exact_receipt["status"] == "rejected":
            status, reason = "rejected", "child_diagnostic_rejected"
        elif exact_receipt["status"] == "diagnostic_complete":
            status, reason = "incomplete", "parent_completion_evidence_missing"
        else:
            status, reason = "incomplete", "child_diagnostic_incomplete"
        return SupervisedResult(
            status, reason, exact_receipt, result.process_evidence, result.retained_control
        )
    return result


def _parent_confirms_i10_diagnostic(result: object) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = _exact_i10_child_receipt(result.sdk_receipt)
    evidence = result.process_evidence
    if receipt is None or type(evidence) is not ProcessEvidence:
        return False
    expected_fields = (
        set(I10_CHILD_RECEIPT_SCHEMA.enum_fields)
        | set(I10_CHILD_RECEIPT_SCHEMA.bool_fields)
        | set(I10_CHILD_RECEIPT_SCHEMA.nullable_bool_fields)
    )
    if (
        set(receipt) != expected_fields
        or receipt["status"] != "diagnostic_complete"
        or receipt["reason"] != "matching_tick_observed"
        or receipt["stage"] != "market_data"
        or receipt["login_identity_state"] not in {"verified", "identity_unverified"}
        or receipt["trading_writes"] != "zero"
        or receipt["settlement_writes"] != "zero"
        or any(
            receipt[name] is not True
            for name in (
                "client_stop_returned",
                "matching_tick_observed",
                "probe_session_closed",
                "same_trading_day_observed",
                "subscription_acknowledged",
            )
        )
        or any(
            receipt[name] is not False
            for name in (
                "account_ready",
                "market_login_ready",
                "native_join_pending",
                "order_submission_authorized",
                "trading_ready",
            )
        )
    ):
        return False
    return (
        result.status == "child_exited"
        and result.reason == "child_process_exited"
        and evidence.process_created is True
        and evidence.job_assignment_observed is True
        and evidence.process_resumed is True
        and evidence.process_exit_observed is True
        and type(evidence.process_exit_code) is int
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _exact_i10_child_receipt(value: object) -> Optional[dict[str, object]]:
    if type(value) is not dict:
        return None
    try:
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    parsed = parse_i10_child_receipt(encoded)
    if type(parsed) is not dict or parsed != value:
        return None
    return parsed


def _is_current_process_in_job() -> bool:
    """Require membership in the inherited Windows Job Object handle."""

    if os.name != "nt":
        return False
    raw_handle = os.environ.pop(_I10_JOB_HANDLE_ENV, None)
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
        return bool(
            is_process_in_job(kernel32.GetCurrentProcess(), job_handle, ctypes.byref(in_job))
            and in_job.value != 0
        )
    except Exception:
        return False
    finally:
        try:
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(job_handle)
        except Exception:
            pass


def _has_supervised_i10_attempt_context() -> bool:
    """Require both inherited Job containment and the reserved canonical marker."""

    if not _is_current_process_in_job():
        return False
    try:
        return PersistentI10OneShotAttemptLatch(I10_LATCH_PATH).is_tripped() is True
    except Exception:
        return False


def _run_child_entry() -> int:
    return _run_diagnostic_impl(())


def _empty_evidence(containment: str) -> ProcessEvidence:
    return ProcessEvidence(False, False, False, None, None, False, None, None, containment)


def supervise_i10_child() -> SupervisedResult:
    """Launch once through the code-owned entry, with a permanent I10 latch.

    This operator contract does not secure arbitrary same-user Python code that
    can access the SDK and private credentials outside this entry.
    """

    return _supervise_i10_child(PersistentI10OneShotAttemptLatch(I10_LATCH_PATH))


def _result_to_parent_payload(result: SupervisedResult) -> dict[str, object]:
    evidence = result.process_evidence
    allowed_statuses = {
        "child_exited",
        "diagnostic_complete",
        "incomplete",
        "invalid_output",
        "latched",
        "pending_native_join",
        "rejected",
        "supervisor_error",
        "timed_out",
    }
    allowed_reasons = {
        "child_process_exited",
        "child_diagnostic_incomplete",
        "child_diagnostic_rejected",
        "i10_runtime_or_latch_unavailable",
        "i10_supervisor_failed",
        "i10_supervisor_result_invalid",
        "invalid_child_receipt",
        "native_join_pending",
        "parent_completion_evidence_missing",
        "prior_attempt_or_poisoned_latch",
        "stdout_limit_exceeded",
        "child_deadline_exceeded",
        "windows_required",
    }
    safe_evidence = {
        "containment": evidence.containment
        if evidence.containment
        in {"latched", "not_started", "unavailable", "uncertain", "verified"}
        else "unavailable",
        "job_assignment_observed": evidence.job_assignment_observed is True,
        "job_empty_observed": evidence.job_empty_observed
        if type(evidence.job_empty_observed) is bool
        else None,
        "job_termination_call_succeeded": evidence.job_termination_call_succeeded
        if type(evidence.job_termination_call_succeeded) is bool
        else None,
        "job_termination_requested": evidence.job_termination_requested is True,
        "process_created": evidence.process_created is True,
        "process_exit_code": evidence.process_exit_code
        if type(evidence.process_exit_code) is int
        else None,
        "process_exit_observed": evidence.process_exit_observed
        if type(evidence.process_exit_observed) is bool
        else None,
        "process_resumed": evidence.process_resumed is True,
    }
    return {
        "process_evidence": safe_evidence,
        "reason": result.reason
        if result.reason in allowed_reasons
        else "i10_supervisor_result_invalid",
        "sdk_receipt": _exact_i10_child_receipt(result.sdk_receipt),
        "status": result.status if result.status in allowed_statuses else "supervisor_error",
    }


def main() -> int:
    """Public entry: reserve once, supervise, and report value-free evidence."""

    if tuple(sys.argv[1:]):
        _emit_i10(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    result = supervise_i10_child()
    sys.stdout.write(json.dumps(_result_to_parent_payload(result), sort_keys=True) + "\n")
    sys.stdout.flush()
    if result.status == "diagnostic_complete":
        return 0
    return 3 if result.status in {"pending_native_join", "timed_out"} else 2


if __name__ == "__main__":  # pragma: no cover - only the supervised worker is launched
    raise SystemExit(main())


__all__ = ["I10_CHILD_RECEIPT_SCHEMA", "main", "parse_i10_child_receipt"]
