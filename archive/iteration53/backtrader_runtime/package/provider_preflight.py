"""Sealed, offline binding for a future provider-session preflight.

This module closes the gap between a configuration-first runtime and the
standalone provider-deployment receipt contract.  It deliberately does not
resolve a secret, import a provider SDK, open a socket, create a provider
client, or authorize a write.  A provider-specific composition root may use a
successful binding only as one input to its own later read-only session
preflight.

Keeping this boundary separate matters: a receipt binding proves that a
reviewed deployment record still matches a sealed runtime configuration.  It
does not prove that the named account is reachable, that a provider accepts a
credential, or that a session may submit an order.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple, Union

from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .policy import MANAGED_WRITE_CAPABILITIES, get_preset_policy
from .provider_deployment import (
    ProviderDeploymentReceiptError,
    ProviderDeploymentReceiptValidation,
    ProviderDeploymentReceiptVerifier,
    ProviderDeploymentRegistration,
    validate_provider_deployment_receipt,
)
from .registry import (
    EffectiveRuntimeConfig,
    RuntimeRegistry,
    require_effective_runtime_config_seal,
)


_SANDBOX_ACCOUNT_ACCESS = "sandbox_direct_provider"
_MANAGED_PRESETS = frozenset(("sandbox", "managed_live_direct", "managed_live_gateway"))
_CTP_SIMNOW_ENVIRONMENT_RE = re.compile(r"^simnow(?:_set[1-9][0-9]*)?$")
_SANDBOX_ENVIRONMENTS_BY_PROVIDER = {
    "okx": frozenset(("demo", "testnet")),
    "binance": frozenset(("demo", "testnet")),
}


def _binding_error(reason: str, message: str) -> RuntimeConfigError:
    """Return a redacted policy error without exposing a secret reference."""

    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        message,
        field_path="runtime.provider_preflight",
        reason=reason,
    )


def _exact_modules(value: Tuple[str, ...]) -> Tuple[str, ...]:
    """Normalize a code-owned module tuple without accepting arbitrary iterables."""

    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise ValueError("capability_modules must be an exact tuple of strings")
    return tuple(sorted(value))


def _validate_provider_environment(provider: str, environment: str, preset: str) -> None:
    """Require a code-owned provider environment for the selected route."""

    if preset == "sandbox":
        if provider == "ctp":
            valid = _CTP_SIMNOW_ENVIRONMENT_RE.fullmatch(environment) is not None
        else:
            valid = environment in _SANDBOX_ENVIRONMENTS_BY_PROVIDER.get(provider, ())
        if not valid:
            raise ValueError(
                "provider sandbox preflight environment is not a reviewed non-production target"
            )
        return

    if environment != "production":
        raise ValueError("provider live preflight environment must be exact production")


def _snapshot_registration(
    registration: "ProviderSessionPreflightRegistration",
) -> "ProviderSessionPreflightRegistration":
    """Re-run code-owned checks after construction to catch frozen-object mutation."""

    deployment = registration.deployment
    if type(deployment) is not ProviderDeploymentRegistration:
        raise TypeError("deployment must be a ProviderDeploymentRegistration")
    deployment_snapshot = ProviderDeploymentRegistration(
        registration_id=deployment.registration_id,
        runtime_id=deployment.runtime_id,
        strategy_id=deployment.strategy_id,
        provider=deployment.provider,
        environment=deployment.environment,
        allowed_secrets_refs=deployment.allowed_secrets_refs,
        account_fingerprint_sha256=deployment.account_fingerprint_sha256,
        approval_receipt_digest=deployment.approval_receipt_digest,
        artifact_sha256=deployment.artifact_sha256,
        effective_config_digest=deployment.effective_config_digest,
        capability_receipt_digest=deployment.capability_receipt_digest,
        required_capability_modules=deployment.required_capability_modules,
    )
    return ProviderSessionPreflightRegistration(
        deployment=deployment_snapshot,
        mode=registration.mode,
        preset=registration.preset,
        account_access=registration.account_access,
    )


@dataclass(frozen=True)
class ProviderSessionPreflightRegistration:
    """Code-owned policy linking one deployment record to one runtime route.

    ``deployment`` deliberately carries the provider-specific environment,
    account-fingerprint digest, artifact digest, capability receipt and opaque
    secret references.  This wrapper adds the exact Iteration 41
    mode/preset/route shape.  Neither object is parsed from ``config.yaml``.
    """

    deployment: ProviderDeploymentRegistration
    mode: str
    preset: str
    account_access: str

    def __post_init__(self) -> None:
        if type(self.deployment) is not ProviderDeploymentRegistration:
            raise TypeError("deployment must be a ProviderDeploymentRegistration")
        if any(type(value) is not str for value in (self.mode, self.preset, self.account_access)):
            raise ValueError("provider session preflight route fields must be strings")
        if self.preset not in _MANAGED_PRESETS:
            raise ValueError(
                "provider session preflight supports only managed sandbox or live presets"
            )
        policy = get_preset_policy(self.preset)
        if policy is None or policy.mode != self.mode:
            raise ValueError(
                "provider session preflight mode and preset must match reviewed policy"
            )
        if self.preset == "sandbox":
            expected_account_access = _SANDBOX_ACCOUNT_ACCESS
        else:
            expected_account_access = policy.account_access
        if self.account_access != expected_account_access:
            raise ValueError("provider session preflight account access must match reviewed policy")
        _validate_provider_environment(
            self.deployment.provider, self.deployment.environment, self.preset
        )
        if not self.deployment.required_capability_modules:
            raise ValueError("provider session preflight requires capability modules")

    def as_public_dict(self) -> dict[str, Any]:
        """Return a redacted static diagnostic view."""

        return {
            "account_access": self.account_access,
            "deployment": self.deployment.as_public_dict(),
            "mode": self.mode,
            "preset": self.preset,
        }


@dataclass(frozen=True)
class ProviderSessionPreflightBinding:
    """A verified binding observation with intentionally no execution authority.

    The result is not a session object or a permit.  Its explicit false
    authority fields and disabled truthiness prevent accidental use as an
    approval token by an integration runner.
    """

    receipt_validation: ProviderDeploymentReceiptValidation
    mode: str
    preset: str
    account_access: str
    preflight_binding_valid: bool = True
    provider_preflight_started: bool = False
    secrets_resolved: bool = False
    session_connected: bool = False
    execution_authorized: bool = False
    external_writes_authorized: bool = False

    def __post_init__(self) -> None:
        if type(self.receipt_validation) is not ProviderDeploymentReceiptValidation:
            raise TypeError("receipt_validation must be a ProviderDeploymentReceiptValidation")
        if (
            self.preflight_binding_valid is not True
            or self.provider_preflight_started is not False
            or self.secrets_resolved is not False
            or self.session_connected is not False
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
        ):
            raise ValueError(
                "provider preflight binding cannot grant session or execution authority"
            )

    def __bool__(self) -> bool:
        raise TypeError(
            "ProviderSessionPreflightBinding is not a session or execution authorization; "
            "do not use it as a boolean"
        )

    @property
    def valid_until(self) -> float:
        """Return the receipt deadline a later session preflight must recheck."""

        return self.receipt_validation.valid_until

    def as_public_dict(self) -> dict[str, Any]:
        """Return an offline-safe status projection with no opaque secret reference."""

        return {
            "account_access": self.account_access,
            "deployment": self.receipt_validation.as_public_dict(),
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "mode": self.mode,
            "preflight_binding_valid": self.preflight_binding_valid,
            "provider_preflight_started": self.provider_preflight_started,
            "preset": self.preset,
            "secrets_resolved": self.secrets_resolved,
            "session_connected": self.session_connected,
            "valid_until": self.valid_until,
        }


def _require_matching_runtime_contract(
    effective: EffectiveRuntimeConfig,
    registration: ProviderSessionPreflightRegistration,
) -> None:
    """Require all code-owned route facts before validating a receipt wire."""

    deployment = registration.deployment
    if effective.mode != registration.mode or effective.preset != registration.preset:
        raise _binding_error(
            "provider_runtime_mode_preset_mismatch",
            "provider preflight registration does not match the sealed runtime mode and preset",
        )
    if effective.order_route != "managed_execution":
        raise _binding_error(
            "provider_runtime_route_not_managed",
            "provider preflight requires a sealed managed execution route",
        )
    if effective.account_access != registration.account_access:
        raise _binding_error(
            "provider_runtime_account_access_mismatch",
            "provider preflight registration does not match the sealed account access route",
        )
    if not effective.allows_external_writes or not effective.requires_approval:
        raise _binding_error(
            "provider_runtime_write_admission_missing",
            "provider preflight requires an approved write-capable managed runtime",
        )
    if effective.registration.approval_receipt_digest is None:
        raise _binding_error(
            "provider_runtime_approval_missing",
            "provider preflight requires a reviewed runtime approval binding",
        )
    if not hmac.compare_digest(
        effective.registration.approval_receipt_digest,
        deployment.approval_receipt_digest,
    ):
        raise _binding_error(
            "provider_approval_receipt_digest_mismatch",
            "provider deployment does not match the sealed runtime approval binding",
        )
    if effective.registration.runtime_id != deployment.runtime_id:
        raise _binding_error(
            "provider_runtime_id_mismatch",
            "provider deployment does not match the sealed runtime identity",
        )
    if effective.strategy_id != deployment.strategy_id:
        raise _binding_error(
            "provider_strategy_id_mismatch",
            "provider deployment does not match the sealed strategy identity",
        )
    if not hmac.compare_digest(effective.effective_digest, deployment.effective_config_digest):
        raise _binding_error(
            "provider_effective_config_mismatch",
            "provider deployment does not match the sealed effective configuration",
        )
    if effective.config.secrets_ref not in deployment.allowed_secrets_refs:
        raise _binding_error(
            "provider_secrets_ref_mismatch",
            "provider deployment does not allow this sealed opaque secret reference",
        )
    if (
        _exact_modules(effective.registration.capability_modules)
        != deployment.required_capability_modules
    ):
        raise _binding_error(
            "provider_capability_modules_mismatch",
            "provider deployment modules do not match the sealed runtime registration",
        )

    policy = get_preset_policy(effective.preset)
    if policy is None:
        raise _binding_error(
            "provider_runtime_policy_missing",
            "provider preflight runtime policy is unavailable",
        )
    if effective.preset == "sandbox":
        if (
            effective.mode != "simulation"
            or effective.policy.environment != "sandbox"
            or effective.allows_production_writes
            or effective.required_capabilities != MANAGED_WRITE_CAPABILITIES
        ):
            raise _binding_error(
                "provider_sandbox_contract_mismatch",
                "provider sandbox preflight requires the sealed non-production managed contract",
            )
        try:
            _validate_provider_environment(
                deployment.provider, deployment.environment, registration.preset
            )
        except (TypeError, ValueError):
            raise _binding_error(
                "provider_environment_mismatch",
                "provider sandbox registration does not target a reviewed non-production environment",
            ) from None
        return

    if (
        effective.mode != "live"
        or effective.policy.environment != "production"
        or not effective.allows_production_writes
        or effective.required_capabilities != policy.required_capabilities
    ):
        raise _binding_error(
            "provider_live_contract_mismatch",
            "provider live preflight requires the sealed reviewed live managed contract",
        )
    try:
        _validate_provider_environment(
            deployment.provider, deployment.environment, registration.preset
        )
    except (TypeError, ValueError):
        raise _binding_error(
            "provider_environment_mismatch",
            "provider live registration must target the reviewed production environment",
        ) from None


def validate_provider_session_preflight_binding(
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    registration: ProviderSessionPreflightRegistration,
    receipt: Union[Mapping[str, Any], bytes, bytearray, str],
    *,
    verifier: Optional[ProviderDeploymentReceiptVerifier] = None,
) -> ProviderSessionPreflightBinding:
    """Bind a trusted deployment receipt to one sealed managed runtime.

    This executes only local validation.  It rechecks effective-config
    provenance and directory identity before inspecting any public effective
    field, then validates the full receipt lifecycle with the injected offline
    verifier.  A successful result still leaves secret resolution, provider
    session construction, account queries, reconciliation, and all external
    writes unavailable.
    """

    if type(effective) is not EffectiveRuntimeConfig:
        raise TypeError("effective must be an EffectiveRuntimeConfig")
    if type(registry) is not RuntimeRegistry:
        raise TypeError("registry must be a RuntimeRegistry")
    if type(registration) is not ProviderSessionPreflightRegistration:
        raise TypeError("registration must be a ProviderSessionPreflightRegistration")
    require_effective_runtime_config_seal(effective, registry)
    try:
        registration = _snapshot_registration(registration)
    except (TypeError, ValueError):
        raise _binding_error(
            "provider_preflight_registration_invalid",
            "provider preflight registration no longer matches its code-owned contract",
        ) from None
    _require_matching_runtime_contract(effective, registration)
    validation = validate_provider_deployment_receipt(
        receipt,
        registration=registration.deployment,
        verifier=verifier,
    )
    if (
        validation.deployment_authorized is not False
        or validation.execution_authorized is not False
        or validation.secrets_resolved is not False
        or validation.provider_preflight_started is not False
    ):
        raise _binding_error(
            "provider_receipt_authority_invalid",
            "provider deployment receipt validation cannot grant session or execution authority",
        )
    return ProviderSessionPreflightBinding(
        receipt_validation=validation,
        mode=effective.mode,
        preset=effective.preset,
        account_access=effective.account_access,
    )


__all__ = [
    "ProviderSessionPreflightBinding",
    "ProviderSessionPreflightRegistration",
    "ProviderDeploymentReceiptError",
    "validate_provider_session_preflight_binding",
]
