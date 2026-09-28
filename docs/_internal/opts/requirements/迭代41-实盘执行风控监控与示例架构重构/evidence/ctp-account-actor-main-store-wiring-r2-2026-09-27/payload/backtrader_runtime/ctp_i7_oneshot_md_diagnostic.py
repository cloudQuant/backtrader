"""Unregistered, one-shot composition for the I7 MD-only diagnostic.

I7 reuses the I4 one-shot read-only adapter while requiring its own installed
artifact pin. The selected config index is bound to the exact sealed front
pair before credentials or SDK modules are exposed. This module adds no
runtime registration or default CLI route.
"""

from __future__ import annotations

import hashlib
import importlib
import json
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
    _CLOSE_STATES_WITH_UNCERTAIN_NATIVE_SHUTDOWN,
    _MARKET_FAILURE_REASONS,
    _MD_LOGIN_CALLBACK_DISPOSITIONS,
    _MD_LOGIN_REQUEST_ID_RELATIONS,
    _MD_LOGIN_RESPONSE_ERROR_STATUSES,
    _close_projection,
    _discard_provider_process_output,
    _reason_for_exception,
)
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from .registry import require_effective_runtime_config_seal, validate_runtime_config


_I7_LOGIN_FAILURE_CATEGORIES = frozenset(
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
_I7_LOGIN_BROKER_ID_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    }
)
_I7_LOGIN_USER_ID_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    }
)
_I7_LOGIN_TRADING_DAY_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "invalid_format",
        "invalid_calendar",
        "valid",
    }
)
_I7_NATIVE_FIELD_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "nonempty_terminated",
        "unterminated",
    }
)


def _emit_i7(
    *,
    status: str,
    reason: str,
    stage: str,
    selected_config_index: Optional[int] = None,
    market_login_ready: bool = False,
    subscription_acknowledged: bool = False,
    matching_tick_observed: bool = False,
    client_stop_returned: bool = False,
    probe_session_closed: bool = False,
    native_join_pending: bool = False,
    native_shutdown_uncertain: bool = False,
    probe_primary_reason: Optional[str] = None,
    front_callback_observed: Optional[bool] = None,
    login_callback_count: Optional[int] = None,
    login_callback_disposition: Optional[str] = None,
    login_request_id_relation: Optional[str] = None,
    login_response_error_status: Optional[str] = None,
    login_failure_category: Optional[str] = None,
    login_broker_id_shape: Optional[str] = None,
    login_user_id_shape: Optional[str] = None,
    login_trading_day_shape: Optional[str] = None,
    native_broker_id_shape: Optional[str] = None,
    native_user_id_shape: Optional[str] = None,
) -> None:
    """Write I7's fixed, versioned, value-free JSON projection."""

    if type(login_callback_count) is not int or not 0 <= login_callback_count <= 1024:
        login_callback_count = None

    payload = {
        "schema_version": "iteration41.ctp-i7-md-oneshot-diagnostic.v1",
        "client_stop_returned": client_stop_returned,
        "front_callback_observed": front_callback_observed,
        "login_broker_id_shape": (
            login_broker_id_shape
            if type(login_broker_id_shape) is str
            and login_broker_id_shape in _I7_LOGIN_BROKER_ID_SHAPES
            else None
        ),
        "login_user_id_shape": (
            login_user_id_shape
            if type(login_user_id_shape) is str and login_user_id_shape in _I7_LOGIN_USER_ID_SHAPES
            else None
        ),
        "login_trading_day_shape": (
            login_trading_day_shape
            if type(login_trading_day_shape) is str
            and login_trading_day_shape in _I7_LOGIN_TRADING_DAY_SHAPES
            else None
        ),
        "native_broker_id_shape": (
            native_broker_id_shape
            if type(native_broker_id_shape) is str
            and native_broker_id_shape in _I7_NATIVE_FIELD_SHAPES
            else None
        ),
        "native_user_id_shape": (
            native_user_id_shape
            if type(native_user_id_shape) is str
            and native_user_id_shape in _I7_NATIVE_FIELD_SHAPES
            else None
        ),
        "login_callback_count": login_callback_count,
        "login_callback_disposition": login_callback_disposition,
        "login_failure_category": (
            login_failure_category
            if type(login_failure_category) is str
            and login_failure_category in _I7_LOGIN_FAILURE_CATEGORIES
            else None
        ),
        "login_request_id_relation": login_request_id_relation,
        "login_response_error_status": login_response_error_status,
        "market_login_ready": market_login_ready,
        "matching_tick_observed": matching_tick_observed,
        "native_join_pending": native_join_pending,
        "native_shutdown_uncertain": native_shutdown_uncertain,
        "order_submission_authorized": False,
        "probe_primary_reason": probe_primary_reason,
        "probe_session_closed": probe_session_closed,
        "reason": reason,
        "selected_config_index": (
            selected_config_index
            if type(selected_config_index) is int and 0 <= selected_config_index <= 7
            else None
        ),
        "settlement_writes": 0,
        "stage": stage,
        "status": status,
        "subscription_acknowledged": subscription_acknowledged,
        "trading_writes": 0,
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _login_failure_projection(error: BaseException) -> dict[str, object]:
    """Expose only bounded callback enums and I7's identifier-shape values."""

    if not isinstance(error, CtpSdkMarketReadOnlyError):
        return {}

    callback_count = error.login_callback_count
    if type(callback_count) is not int or not 0 <= callback_count <= 1024:
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
    if type(failure_category) is not str or failure_category not in _I7_LOGIN_FAILURE_CATEGORIES:
        failure_category = None

    broker_id_shape = getattr(error, "login_broker_id_shape", None)
    if type(broker_id_shape) is not str or broker_id_shape not in _I7_LOGIN_BROKER_ID_SHAPES:
        broker_id_shape = None

    user_id_shape = getattr(error, "login_user_id_shape", None)
    if type(user_id_shape) is not str or user_id_shape not in _I7_LOGIN_USER_ID_SHAPES:
        user_id_shape = None

    trading_day_shape = getattr(error, "login_trading_day_shape", None)
    if type(trading_day_shape) is not str or trading_day_shape not in _I7_LOGIN_TRADING_DAY_SHAPES:
        trading_day_shape = None

    native_broker_id_shape = getattr(error, "native_broker_id_shape", None)
    if (
        type(native_broker_id_shape) is not str
        or native_broker_id_shape not in _I7_NATIVE_FIELD_SHAPES
    ):
        native_broker_id_shape = None

    native_user_id_shape = getattr(error, "native_user_id_shape", None)
    if type(native_user_id_shape) is not str or native_user_id_shape not in _I7_NATIVE_FIELD_SHAPES:
        native_user_id_shape = None

    return {
        "login_callback_count": callback_count,
        "login_callback_disposition": disposition,
        "login_request_id_relation": request_relation,
        "login_response_error_status": response_status,
        "login_failure_category": failure_category,
        "login_broker_id_shape": broker_id_shape,
        "login_user_id_shape": user_id_shape,
        "login_trading_day_shape": trading_day_shape,
        "native_broker_id_shape": native_broker_id_shape,
        "native_user_id_shape": native_user_id_shape,
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


def _validate_front_pairs(front_pairs: object) -> tuple[Any, ...]:
    """Require the sealed configuration's bounded, ordered candidate tuple."""

    if type(front_pairs) is not tuple or not 1 <= len(front_pairs) <= 8:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed CTP front pair set is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    return front_pairs


def _selected_front_index(selection: object, front_pairs: tuple[Any, ...]) -> int:
    """Bind the selector index and exact selected pair to sealed config."""

    try:
        config_index = selection.config_index
        selected_pair = selection.pair
        selected_td_front = selected_pair.td_front
        selected_md_front = selected_pair.md_front
    except Exception:
        config_index = None
        selected_td_front = None
        selected_md_front = None
    if (
        type(config_index) is not int
        or not 0 <= config_index <= 7
        or config_index >= len(front_pairs)
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the selected CTP front pair index is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    sealed_td_front, sealed_md_front = _candidate_front_pair(front_pairs[config_index])
    if (
        type(selected_td_front) is not str
        or type(selected_md_front) is not str
        or (selected_td_front, selected_md_front) != (sealed_td_front, sealed_md_front)
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the selected CTP front pair does not match its sealed config index",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_mismatch",
        )
    return config_index


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
    """Run one sealed, I7-pinned MD observation; accept no caller scope."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit_i7(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    logging.disable(logging.CRITICAL)

    stage = "configuration"
    selected_config_index: Optional[int] = None
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
        _, _, unvalidated_front_pairs = binding._sealed_private_config(effective, registry)
        front_pairs = _validate_front_pairs(unvalidated_front_pairs)

        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            from .ctp_artifact_provenance import (
                verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts,
            )

            # Reject an unpinned install before the credential-free TCP selector.
            candidate_td_front, candidate_md_front = _candidate_front_pair(front_pairs[0])
            verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts(
                td_front=candidate_td_front,
                md_front=candidate_md_front,
            )

            stage = "front_selection"
            selection = _select_configured_front_pair(front_pairs)
            config_index = _selected_front_index(selection, front_pairs)
            admission, scope = binding._route(
                effective,
                registry,
                selected_front_pair=selection.pair,
            )
            sealed_td_front, sealed_md_front = _candidate_front_pair(front_pairs[config_index])
            if (
                type(getattr(admission, "td_front", None)) is not str
                or type(getattr(admission, "md_front", None)) is not str
                or (admission.td_front, admission.md_front) != (sealed_td_front, sealed_md_front)
            ):
                raise RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "the admitted CTP front pair does not match the selected sealed pair",
                    field_path="ctp.front_pairs",
                    reason="ctp_simnow_preflight_front_selection_mismatch",
                )
            selected_config_index = config_index

            # Verify the exact selected pair that the binding admitted.
            stage = "sdk_artifact"
            verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts(
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
                # Import the installed, I7-pinned client only after all sealed
                # config, selected-pair, artifact, and credential gates pass.
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
            _emit_i7(
                status="incomplete",
                reason="market_observation_incomplete",
                stage="market_data",
                selected_config_index=selected_config_index,
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

        # The shared I4 observation has no callback-shape snapshot. Keep the
        # versioned shape fields present and null on success; failed probes
        # copy only the SDK's allowlisted shape enums from the redacted error.
        _emit_i7(
            status="diagnostic_complete",
            reason="matching_tick_observed",
            stage="market_data",
            selected_config_index=selected_config_index,
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
        _emit_i7(
            status="incomplete" if uncertain_close else "rejected",
            reason=_reason_for_exception(error, stage=stage),
            stage=stage,
            selected_config_index=selected_config_index,
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
