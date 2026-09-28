"""Opt-in construction helpers for the config-pair managed SimNow port.

This module is deliberately absent from the default inventory and CLI. It
revalidates the registered, sealed ``config.yaml`` before reading its private
CTP block, and constructs an unconnected TraderClient. No SDK authority,
approval, evidence verifier, or account-wide writer fence is created here.

The result is intended for a trusted runtime process. Python private
attributes are not isolation from an untrusted in-process strategy plugin; a
deployment that loads such plugins must keep credentials and the SDK client
behind a process or service boundary.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping

from .config import CtpSimNowPrivateConfig
from .ctp_simulation_execution import (
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    require_ctp_simulation_execution_admission,
)
from .ctp_artifact_provenance import (
    CtpArtifactProvenanceError,
    verify_ctp_simnow_managed_artifact_provenance_for_fronts,
)
from .ctp_trader_client_port import (
    CtpSimulationTraderConfig,
    CtpTraderClientSimulationPort,
    create_ctp_trader_client_simulation_port,
)
from .capability_imports import trusted_installed_capability_import_context
from .registry import (
    EffectiveRuntimeConfig,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
    validate_runtime_config,
)


def _reject(reason: str) -> None:
    raise CtpSimulationExecutionError(reason)


def _resolve_sealed_ctp_simnow_private_config(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    registration: CtpSimulationExecutionRegistration,
) -> CtpSimNowPrivateConfig:
    """Validate current sealed routing scope without extracting credentials.

    The source config must be the registered ``simulation/sandbox`` runtime
    with a same-file CTP private block (``secrets_ref: config_yaml``). Current
    on-disk content is reparsed through the protected runtime-config loader;
    all addresses and instrument/hedge scope must still match the code-owned
    managed-execution registration. When ``front_pairs`` contains
    several candidates, the registration's exact MD/TD pair is the explicit
    selection; no first-entry or fallback selection is performed. The
    returned private block is not used to read credential fields until the
    artifact gate has passed.
    """

    try:
        require_effective_runtime_config_seal(effective, registry)
        require_ctp_simulation_execution_admission(effective, registry, registration)
        current = validate_runtime_config(effective.registration.runtime_dir, registry)
        require_effective_runtime_config_seal(current, registry)
        require_ctp_simulation_execution_admission(current, registry, registration)
    except CtpSimulationExecutionError:
        raise
    except Exception as exc:
        raise CtpSimulationExecutionError("sealed_ctp_runtime_config_rejected") from exc

    private = current.config.ctp_simnow
    if (
        current.registration is not effective.registration
        or current.config.config_digest != effective.config.config_digest
        or current.effective_digest != effective.effective_digest
    ):
        _reject("sealed_ctp_runtime_config_changed")

    if (
        type(private) is not CtpSimNowPrivateConfig
        or current.config.secrets_ref != "config_yaml"
        or registration.allowed_secrets_ref != "config_yaml"
    ):
        _reject("sealed_ctp_simnow_private_config_required")
    if (
        private.instrument_id != registration.instrument_id
        or private.exchange_id != registration.exchange_id
        or private.hedge_flag != registration.hedge_flag
    ):
        _reject("sealed_ctp_simnow_instrument_scope_mismatch")
    selected_pair = (registration.md_front, registration.td_front)
    configured_pairs = tuple((pair["md_front"], pair["td_front"]) for pair in private.front_pairs)
    if configured_pairs.count(selected_pair) != 1:
        _reject("sealed_ctp_front_pair_registration_mismatch")
    return private


def _trader_config_from_private(
    private: CtpSimNowPrivateConfig,
    registration: CtpSimulationExecutionRegistration,
) -> CtpSimulationTraderConfig:
    """Extract sealed credential fields after the SDK artifact gate passes."""

    config = CtpSimulationTraderConfig(
        td_front=registration.td_front,
        md_front=registration.md_front,
        broker_id=private.broker_id,
        user_id=private.user_id,
        password=private.password,
        auth_code=private.auth_code,
        app_id=private.app_id,
        auto_detect_fronts=False,
    )
    config.validate(registration)
    expected_fingerprint = hashlib.sha256(
        f"{private.broker_id}:{private.user_id}".encode("utf-8")
    ).hexdigest()[:16]
    expected_account_digest = hashlib.sha256(
        ("acct_" + expected_fingerprint).encode("ascii")
    ).hexdigest()
    if expected_account_digest != registration.account_fingerprint_sha256:
        _reject("sealed_ctp_simnow_account_scope_mismatch")
    return config


def _verify_selected_pair_artifacts(
    private: CtpSimNowPrivateConfig,
    registration: CtpSimulationExecutionRegistration,
) -> None:
    """Verify provenance for the one sealed pair selected by code."""

    selected_pair = (registration.md_front, registration.td_front)
    configured_pairs = tuple((pair["md_front"], pair["td_front"]) for pair in private.front_pairs)
    if configured_pairs.count(selected_pair) != 1:
        _reject("sealed_ctp_front_pair_registration_mismatch")
    try:
        verify_ctp_simnow_managed_artifact_provenance_for_fronts(
            td_front=registration.td_front,
            md_front=registration.md_front,
        )
    except CtpArtifactProvenanceError:
        _reject("managed_simnow_artifact_provenance_rejected")
    except Exception:
        _reject("managed_simnow_artifact_provenance_rejected")


def resolve_sealed_ctp_simnow_trader_config(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    registration: CtpSimulationExecutionRegistration,
) -> CtpSimulationTraderConfig:
    """Resolve exact sealed credentials only after artifact provenance passes."""

    private = _resolve_sealed_ctp_simnow_private_config(effective, registry, registration)
    _verify_selected_pair_artifacts(private, registration)
    return _trader_config_from_private(private, registration)


def create_sealed_ctp_simnow_managed_port(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    registration: CtpSimulationExecutionRegistration,
    *,
    execution_capability: object,
    runtime_admission_check: Callable[[], bool],
    runtime_order_binding: Callable[[str, bool], Mapping[str, Any]],
    runtime_credential_binding_factory: Callable[..., Any],
    runtime_approval_verifier: Any,
    sdk_approval_rechecker: Callable[[Any, Mapping[str, Any]], bool],
    trader_client_factory: Callable[..., Any] | None = None,
    order_field_factory: Callable[[], Any] | None = None,
    action_field_factory: Callable[[], Any] | None = None,
) -> CtpTraderClientSimulationPort:
    """Build the exact-config managed adapter without starting a provider.

    Every authority-bearing dependency is required and injected explicitly.
    This function does not issue the SDK capability, create approvals, connect
    the native API, install an action binding, or register a runnable route.
    It only constructs the SDK client and configures its persistent gate in
    the disarmed state.
    """

    required = (
        runtime_admission_check,
        runtime_order_binding,
        runtime_credential_binding_factory,
        sdk_approval_rechecker,
    )
    if execution_capability is None or any(not callable(item) for item in required):
        _reject("explicit_managed_simnow_authorities_required")
    if not callable(getattr(runtime_approval_verifier, "verify", None)):
        _reject("runtime_write_approval_verifier_required")
    private = _resolve_sealed_ctp_simnow_private_config(effective, registry, registration)
    # This code-owned gate checks the exact pair selected by the sealed
    # registration and the installed bt_api_base/bt_api_ctp artifacts before
    # credentials are extracted or any SDK import/client factory can run. The
    # managed gate includes bt_api_py because CTP lazily imports its managed
    # approval and credential-binding contracts from that separate wheel.
    # The injection seams below remain useful for offline tests, but they do
    # not bypass this artifact check.
    _verify_selected_pair_artifacts(private, registration)
    config = _trader_config_from_private(private, registration)

    # Keep every SDK import triggered by the factory and port constructor
    # pinned to the concrete installed packages that passed provenance.
    try:
        with trusted_installed_capability_import_context(
            ("bt_api_base", "bt_api_ctp", "bt_api_py")
        ):
            return create_ctp_trader_client_simulation_port(
                registration,
                config,
                trader_client_factory=trader_client_factory,
                execution_capability=execution_capability,
                runtime_admission_check=runtime_admission_check,
                runtime_order_binding=runtime_order_binding,
                runtime_credential_binding_factory=runtime_credential_binding_factory,
                runtime_approval_verifier=runtime_approval_verifier,
                sdk_approval_rechecker=sdk_approval_rechecker,
                order_field_factory=order_field_factory,
                action_field_factory=action_field_factory,
            )
    except CtpSimulationExecutionError:
        raise
    except Exception:
        _reject("managed_simnow_capability_import_rejected")


__all__ = [
    "create_sealed_ctp_simnow_managed_port",
    "resolve_sealed_ctp_simnow_trader_config",
]
