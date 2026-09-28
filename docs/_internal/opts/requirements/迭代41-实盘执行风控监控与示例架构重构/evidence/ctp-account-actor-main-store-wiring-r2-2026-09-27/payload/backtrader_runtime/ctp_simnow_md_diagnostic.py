"""One-shot, source-tree-only CTP SimNow market-data diagnostic.

This is intentionally not a registered runtime or a CLI route. It exists to
inspect the MD login/subscription/tick leg independently after an operator has
stopped the separate TD diagnostic process. It resolves only the registered
Iteration 41 private runtime and its sealed ``config.yaml``. The exact pair is
chosen by the same credential-free selector as the registered preflight, then
checked against the installed SDK pins before credentials are released.

The probe uses ``MdClient`` only and has no TD, order, cancel, settlement, or
strategy interface. Run it in a supervised child process: the SDK has
synchronous native calls whose wall-clock duration cannot be bounded reliably
inside this Python process.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import contextmanager
from typing import Iterator, Optional, Sequence

from .capability_imports import trusted_installed_capability_import_context
from .ctp_artifact_provenance import (
    CtpArtifactProvenanceError,
    verify_ctp_sdk_artifact_provenance_for_fronts,
)
from .credential_resolver import (
    CredentialResolutionError,
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .ctp_sdk_market_readonly import (
    _MD_LOGIN_CALLBACK_DISPOSITIONS,
    _MD_LOGIN_REQUEST_ID_RELATIONS,
    _MD_LOGIN_RESPONSE_ERROR_STATUSES,
    CtpSdkMarketReadOnlyError,
)
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from .registry import require_effective_runtime_config_seal, validate_runtime_config


_MARKET_FAILURE_REASONS = frozenset(
    {
        "account_probe_busy",
        "account_probe_lock_unavailable",
        "admission_invalid",
        "admission_required",
        "credential_account_mismatch",
        "credential_invalid",
        "credential_unavailable",
        "invalid_timeout",
        "market_client_identity_mismatch",
        "market_client_state_unavailable",
        "market_client_stop_failed",
        "market_client_type_required",
        "market_connection_generation_changed",
        "market_front_binding_mismatch",
        "market_front_disconnected",
        "market_front_rejected",
        "market_login_identity_mismatch",
        "market_login_identity_unavailable",
        "market_login_timeout",
        "market_probe_failed",
        "market_session_not_ready",
        "market_session_state_unavailable",
        "market_subscription_rejected",
        "native_join_pending",
        "native_join_state_unknown",
        "probe_deadline_expired",
        "subscription_ack_timeout",
    }
)
_CLOSE_STATES_WITH_UNCERTAIN_NATIVE_SHUTDOWN = frozenset(
    {
        "native_join_pending",
        "native_join_state_unknown",
        "native_stop_incomplete",
        "native_stop_method_invalid",
        "native_stop_method_unknown",
        "native_stop_receipt_inconsistent",
        "native_stop_receipt_unknown",
        "stop_failed",
    }
)


def _emit(
    *,
    status: str,
    reason: str,
    stage: str,
    market_login_ready: bool = False,
    subscription_acknowledged: bool = False,
    matching_tick_observed: bool = False,
    client_stop_returned: bool = False,
    probe_session_closed: bool = False,
    native_join_pending: bool = False,
    native_shutdown_uncertain: bool = False,
    probe_primary_reason: str | None = None,
    front_callback_observed: bool | None = None,
    login_callback_count: int | None = None,
    login_callback_disposition: str | None = None,
    login_request_id_relation: str | None = None,
    login_response_error_status: str | None = None,
    login_failure_category: str | None = None,
    include_login_failure_category: bool = False,
) -> None:
    """Write a fixed, value-free JSON projection to stdout."""

    payload = {
        "client_stop_returned": client_stop_returned,
        "market_login_ready": market_login_ready,
        "matching_tick_observed": matching_tick_observed,
        "native_join_pending": native_join_pending,
        "native_shutdown_uncertain": native_shutdown_uncertain,
        "order_submission_authorized": False,
        "probe_primary_reason": probe_primary_reason,
        "front_callback_observed": front_callback_observed,
        "login_callback_count": login_callback_count,
        "login_callback_disposition": login_callback_disposition,
        "login_request_id_relation": login_request_id_relation,
        "login_response_error_status": login_response_error_status,
        "probe_session_closed": probe_session_closed,
        "reason": reason,
        "settlement_writes": 0,
        "stage": stage,
        "status": status,
        "subscription_acknowledged": subscription_acknowledged,
        "trading_writes": 0,
    }
    if include_login_failure_category:
        payload["login_failure_category"] = (
            login_failure_category
            if type(login_failure_category) is str
            and login_failure_category
            in {
                "request_id_invalid",
                "request_id_mismatch",
                "response_nonterminal",
                "provider_rejected",
                "response_invalid",
                "broker_id_mismatch",
                "user_id_mismatch",
                "trading_day_invalid",
            }
            else None
        )
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


@contextmanager
def _discard_provider_process_output() -> Iterator[None]:
    """Keep SDK/native diagnostics off the operator's stdout and stderr."""

    sys.stdout.flush()
    sys.stderr.flush()
    stdout_fd = sys.stdout.fileno()
    stderr_fd = sys.stderr.fileno()
    saved_stdout_fd = os.dup(stdout_fd)
    saved_stderr_fd = os.dup(stderr_fd)
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null_fd, stdout_fd)
        os.dup2(null_fd, stderr_fd)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout_fd, stdout_fd)
        os.dup2(saved_stderr_fd, stderr_fd)
        os.close(null_fd)
        os.close(saved_stdout_fd)
        os.close(saved_stderr_fd)


def _reason_for_exception(error: BaseException, *, stage: str) -> str:
    """Map exceptions to fixed categories; never print exception text."""

    if isinstance(error, CtpSdkMarketReadOnlyError):
        return error.reason if error.reason in _MARKET_FAILURE_REASONS else "market_probe_rejected"
    if isinstance(error, CtpArtifactProvenanceError):
        return "sdk_artifact_rejected"
    if isinstance(error, CredentialResolutionError):
        return "credential_rejected"
    if isinstance(error, RuntimeConfigError):
        return {
            "configuration": "configuration_rejected",
            "front_selection": "front_selection_rejected",
        }.get(stage, "runtime_policy_rejected")
    return {
        "configuration": "configuration_rejected",
        "front_selection": "front_selection_rejected",
        "sdk_artifact": "sdk_artifact_rejected",
        "credentials": "credential_rejected",
        "market_data": "market_probe_rejected",
    }.get(stage, "diagnostic_rejected")


def _close_projection(error: BaseException) -> dict[str, bool]:
    """Keep process/SDK close fields distinct in the fixed JSON projection."""

    close_state = (
        error.close_state if isinstance(error, CtpSdkMarketReadOnlyError) else "not_started"
    )
    stop_returned = (
        error.client_stop_returned
        if isinstance(error, CtpSdkMarketReadOnlyError) and type(error.client_stop_returned) is bool
        else False
    )
    return {
        "client_stop_returned": stop_returned,
        "probe_session_closed": close_state == "stop_returned" and stop_returned,
        "native_join_pending": close_state == "native_join_pending",
        "native_shutdown_uncertain": close_state in _CLOSE_STATES_WITH_UNCERTAIN_NATIVE_SHUTDOWN,
    }


def run_diagnostic(argv: Optional[Sequence[str]] = None) -> int:
    """Run the exact registered MD-only diagnostic; accept no caller scope."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    # The helper is a one-shot operator process. Keep SDK logging from adding
    # provider-specific values beside the fixed JSON result.
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
        _, _, front_pairs = binding._sealed_private_config(effective, registry)

        stage = "front_selection"
        selection = _select_configured_front_pair(front_pairs)
        admission, scope = binding._route(
            effective,
            registry,
            selected_front_pair=selection.pair,
        )

        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            verify_ctp_sdk_artifact_provenance_for_fronts(
                td_front=admission.td_front,
                md_front=admission.md_front,
            )

            stage = "credentials"
            credentials = resolve_runtime_credentials(effective, registry, scope)
            require_resolved_runtime_credentials_seal(
                credentials,
                effective,
                registry,
                scope,
            )

            # Importing the wrapper does not load the SDK. It rechecks the
            # credential seal immediately before each individual value read.
            from .ctp_simnow_readonly_runtime import _SealedCtpCredentialSource
            from .ctp_sdk_market_readonly import _probe_ctp_market_readonly

            credential_source = _SealedCtpCredentialSource(
                credentials,
                effective,
                registry,
                scope,
            )
            stage = "market_data"
            with _discard_provider_process_output():
                from bt_api_ctp.ctp.client import MdClient

                observation = _probe_ctp_market_readonly(
                    admission=admission,
                    credential_source=credential_source,
                    client_type=MdClient,
                    timeout_seconds=15.0,
                    tick_observation_seconds=5.0,
                )

        tick_observed = observation.first_tick_observed
        session_closed = observation.probe_session_closed
        join_pending = observation.native_join_pending
        if join_pending or not session_closed:
            _emit(
                status="incomplete",
                reason="native_join_pending" if join_pending else "native_shutdown_uncertain",
                stage="market_data",
                market_login_ready=observation.market_login_ready,
                subscription_acknowledged=observation.subscription_acknowledged,
                matching_tick_observed=tick_observed,
                client_stop_returned=observation.client_stop_returned,
                probe_session_closed=session_closed,
                native_join_pending=join_pending,
                native_shutdown_uncertain=True,
            )
            return 3
        if not observation.market_path_ready:
            _emit(
                status="rejected",
                reason="market_readiness_incomplete",
                stage="market_data",
                market_login_ready=observation.market_login_ready,
                subscription_acknowledged=observation.subscription_acknowledged,
                matching_tick_observed=tick_observed,
                client_stop_returned=observation.client_stop_returned,
                probe_session_closed=session_closed,
            )
            return 2
        if not tick_observed:
            _emit(
                status="incomplete",
                reason="matching_tick_not_observed",
                stage="market_data",
                market_login_ready=observation.market_login_ready,
                subscription_acknowledged=observation.subscription_acknowledged,
                matching_tick_observed=False,
                client_stop_returned=observation.client_stop_returned,
                probe_session_closed=session_closed,
            )
            return 3
        _emit(
            status="diagnostic_complete",
            reason="matching_tick_observed",
            stage="market_data",
            market_login_ready=True,
            subscription_acknowledged=True,
            matching_tick_observed=True,
            client_stop_returned=observation.client_stop_returned,
            probe_session_closed=session_closed,
            native_join_pending=False,
            native_shutdown_uncertain=False,
        )
        return 0
    except Exception as error:
        _emit(
            status="rejected",
            reason=_reason_for_exception(error, stage=stage),
            stage=stage,
            probe_primary_reason=(
                error.primary_reason
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and error.primary_reason in _MARKET_FAILURE_REASONS
                else None
            ),
            front_callback_observed=(
                error.front_callback_observed
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and type(error.front_callback_observed) is bool
                else None
            ),
            login_callback_count=(
                error.login_callback_count
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and type(error.login_callback_count) is int
                and 0 <= error.login_callback_count <= 1_000_000
                else None
            ),
            login_callback_disposition=(
                error.login_callback_disposition
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and error.login_callback_disposition in _MD_LOGIN_CALLBACK_DISPOSITIONS
                else None
            ),
            login_request_id_relation=(
                error.login_request_id_relation
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and error.login_request_id_relation in _MD_LOGIN_REQUEST_ID_RELATIONS
                else None
            ),
            login_response_error_status=(
                error.login_response_error_status
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and error.login_response_error_status in _MD_LOGIN_RESPONSE_ERROR_STATUSES
                else None
            ),
            **_close_projection(error),
        )
        return 2


def main() -> int:
    return run_diagnostic()


if __name__ == "__main__":  # pragma: no cover - exercised by the operator process
    raise SystemExit(main())


__all__ = ["main", "run_diagnostic"]
