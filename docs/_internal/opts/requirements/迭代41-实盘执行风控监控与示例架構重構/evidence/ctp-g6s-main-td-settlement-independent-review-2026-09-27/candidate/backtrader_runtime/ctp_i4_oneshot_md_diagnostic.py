"""Unregistered, one-shot composition for the I4 MD-only diagnostic.

This module intentionally adds no runtime registration or default CLI route.
It reuses the sealed Iteration 41 SimNow sandbox binding and front selector,
but requires the I4-specific installed artifact verifier and one-shot MD
adapter before releasing credentials or importing the SDK client types.
"""

from __future__ import annotations

import importlib
import hashlib
import logging
import sys
from typing import Any, Optional, Sequence

from .capability_imports import trusted_installed_capability_import_context
from .credential_resolver import (
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from .ctp_i4_oneshot_md_readonly import (
    CtpI4OneShotMdObservation,
    probe_i4_oneshot_md_readonly,
)
from .ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from .ctp_simnow_md_diagnostic import (
    _MD_LOGIN_CALLBACK_DISPOSITIONS,
    _MD_LOGIN_REQUEST_ID_RELATIONS,
    _MD_LOGIN_RESPONSE_ERROR_STATUSES,
    _CLOSE_STATES_WITH_UNCERTAIN_NATIVE_SHUTDOWN,
    _MARKET_FAILURE_REASONS,
    _close_projection,
    _discard_provider_process_output,
    _emit,
    _reason_for_exception,
)
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from .registry import require_effective_runtime_config_seal, validate_runtime_config


_I4_LOGIN_FAILURE_CATEGORIES = frozenset(
    {
        "request_id_invalid",
        "request_id_mismatch",
        "response_nonterminal",
        "provider_rejected",
        "response_invalid",
        "broker_id_mismatch",
        "user_id_mismatch",
        "trading_day_invalid",
    }
)


def _emit_i4(**kwargs: Any) -> None:
    """Keep the I4 JSON schema local while reusing the fixed value-free writer."""

    _emit(include_login_failure_category=True, **kwargs)


def _login_failure_projection(error: BaseException) -> dict[str, object]:
    """Expose only bounded SDK callback classifications from a probe failure."""

    if not isinstance(error, CtpSdkMarketReadOnlyError):
        return {}

    callback_count = error.login_callback_count
    if type(callback_count) is not int or not 0 <= callback_count <= 1_000_000:
        callback_count = None

    disposition = error.login_callback_disposition
    if type(disposition) is not str or disposition not in _MD_LOGIN_CALLBACK_DISPOSITIONS | {
        "terminal"
    }:
        disposition = None

    request_relation = error.login_request_id_relation
    if type(request_relation) is not str or request_relation not in _MD_LOGIN_REQUEST_ID_RELATIONS:
        request_relation = None

    response_status = error.login_response_error_status
    if type(response_status) is not str or response_status not in _MD_LOGIN_RESPONSE_ERROR_STATUSES:
        response_status = None

    failure_category = error.login_failure_category
    if type(failure_category) is not str or failure_category not in _I4_LOGIN_FAILURE_CATEGORIES:
        failure_category = None

    return {
        "login_callback_count": callback_count,
        "login_callback_disposition": disposition,
        "login_request_id_relation": request_relation,
        "login_response_error_status": response_status,
        "login_failure_category": failure_category,
    }


def _candidate_front_pair(front_pair: object) -> tuple[str, str]:
    """Return exact configured strings from one already sealed pair."""

    try:
        td_front = front_pair.get("td_front")
        md_front = front_pair.get("md_front")
    except Exception:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed CTP front pair is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        ) from None
    if type(td_front) is not str or type(md_front) is not str:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed CTP front pair is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    return td_front, md_front


def _validate_observation(observation: object, admission: object) -> bool:
    """Require the adapter's exact, complete, read-only observation shape."""

    return (
        type(observation) is CtpI4OneShotMdObservation
        and type(getattr(admission, "md_front", None)) is str
        and type(getattr(admission, "instrument_id", None)) is str
        and type(getattr(admission, "exchange_id", None)) is str
        and type(getattr(admission, "account_fingerprint_sha256", None)) is str
        and observation.md_front_sha256
        == hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
        and observation.instrument_id == admission.instrument_id
        and observation.exchange_id == admission.exchange_id
        and observation.account_fingerprint_sha256 == admission.account_fingerprint_sha256
        and observation.login_request_id == 0
        and observation.market_login_ready is True
        and observation.subscription_acknowledged is True
        and observation.matching_tick_observed is True
        and observation.client_stop_returned is True
        and observation.native_join_pending is False
        and observation.probe_session_closed is True
        and observation.order_submission_authorized is False
        and observation.trading_writes == 0
        and observation.settlement_writes == 0
    )


def run_diagnostic(argv: Optional[Sequence[str]] = None) -> int:
    """Run one sealed, I4-pinned MD observation; accept no caller scope."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit_i4(status="rejected", reason="arguments_not_allowed", stage="arguments")
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
        _, _, front_pairs = binding._sealed_private_config(effective, registry)

        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            from .ctp_artifact_provenance import (
                verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts,
            )

            # The installed artifact check does not need provider I/O. Run it
            # on a sealed candidate before the selector's bounded TCP probes,
            # so a bad I4 pin is rejected without opening any network socket.
            candidate_td_front, candidate_md_front = _candidate_front_pair(front_pairs[0])
            verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts(
                td_front=candidate_td_front,
                md_front=candidate_md_front,
            )

            stage = "front_selection"
            selection = _select_configured_front_pair(front_pairs)
            admission, scope = binding._route(
                effective,
                registry,
                selected_front_pair=selection.pair,
            )

            # Recheck the selected pair itself: it must be the exact sealed
            # endpoint passed through the binding and the I4 artifact gate.
            stage = "sdk_artifact"
            verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts(
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
            from .ctp_simnow_readonly_runtime import _SealedCtpCredentialSource

            credential_source = _SealedCtpCredentialSource(
                credentials,
                effective,
                registry,
                scope,
            )

            stage = "market_data"
            with _discard_provider_process_output():
                # Import only from the installed, artifact-verified SDK, after
                # the sealed credential source has been constructed.
                sdk_client_module = importlib.import_module("bt_api_ctp.ctp.client")
                client_type = getattr(sdk_client_module, "OneShotMdDiagnosticClient")
                stop_receipt_type = getattr(sdk_client_module, "CtpNativeStopReceipt")
                observation = probe_i4_oneshot_md_readonly(
                    admission=admission,
                    credential_source=credential_source,
                    client_type=client_type,
                    stop_receipt_type=stop_receipt_type,
                    timeout_seconds=15.0,
                )

        if not _validate_observation(observation, admission):
            _emit_i4(
                status="incomplete",
                reason="market_observation_incomplete",
                stage="market_data",
                market_login_ready=(
                    observation.market_login_ready is True
                    if type(observation) is CtpI4OneShotMdObservation
                    else False
                ),
                subscription_acknowledged=(
                    observation.subscription_acknowledged is True
                    if type(observation) is CtpI4OneShotMdObservation
                    else False
                ),
                matching_tick_observed=(
                    observation.matching_tick_observed is True
                    if type(observation) is CtpI4OneShotMdObservation
                    else False
                ),
                client_stop_returned=(
                    observation.client_stop_returned is True
                    if type(observation) is CtpI4OneShotMdObservation
                    else False
                ),
                probe_session_closed=(
                    observation.probe_session_closed is True
                    if type(observation) is CtpI4OneShotMdObservation
                    else False
                ),
                native_join_pending=(
                    observation.native_join_pending is True
                    if type(observation) is CtpI4OneShotMdObservation
                    else False
                ),
                native_shutdown_uncertain=True,
            )
            return 3

        _emit_i4(
            status="diagnostic_complete",
            reason="matching_tick_observed",
            stage="market_data",
            market_login_ready=True,
            subscription_acknowledged=True,
            matching_tick_observed=True,
            client_stop_returned=True,
            probe_session_closed=True,
            native_join_pending=False,
            native_shutdown_uncertain=False,
        )
        return 0
    except Exception as error:
        close_projection = _close_projection(error)
        uncertain_close = (
            isinstance(error, CtpSdkMarketReadOnlyError)
            and error.close_state in _CLOSE_STATES_WITH_UNCERTAIN_NATIVE_SHUTDOWN
        )
        _emit_i4(
            status="incomplete" if uncertain_close else "rejected",
            reason=_reason_for_exception(error, stage=stage),
            stage=stage,
            probe_primary_reason=(
                error.primary_reason
                if isinstance(error, CtpSdkMarketReadOnlyError)
                and type(error.primary_reason) is str
                and error.primary_reason in _MARKET_FAILURE_REASONS
                else None
            ),
            **_login_failure_projection(error),
            **close_projection,
        )
        return 3 if uncertain_close else 2


def main() -> int:
    return run_diagnostic()


if __name__ == "__main__":  # pragma: no cover - one-shot operator process
    raise SystemExit(main())


__all__ = ["main", "run_diagnostic"]
