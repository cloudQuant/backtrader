"""Pure, unregistered production per-action credential-scope contract.

This module binds one live production action to the same sealed canonical
``ctp:`` config used by the read-only and execution-scope contracts. It does
not resolve secret values, import a provider SDK, open a socket, dispatch an
action, or grant execution authority. Its approval type and verifier interface
are production-specific and cannot consume the SimNow action-approval type.

The contract is intentionally not wired into the default runtime inventory,
CLI, or a provider composition root. A future SDK adapter must add its own
reviewed artifact, credential-release, action, recovery, and writer-fencing
checks before using any native client. The optional dispatch-revalidation
seam records injected trust-source observations only; this module cannot prove
that those dependencies are deployment-owned or trusted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Tuple

from .config import RuntimeConfig
from .ctp_production_execution_admission import (
    CtpProductionExecutionAdmissionError,
    CtpProductionExecutionConfigBinding,
    CtpProductionExecutionRegistration,
    require_ctp_production_execution_config_binding,
)
from .registry import EffectiveRuntimeConfig, RuntimeRegistry


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCTION_ID_RE = re.compile(r"^ctp-production:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INTENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PRODUCTION_ENVIRONMENT = "production"
_PRODUCTION_MODE = "live"
_PRODUCTION_PRESET = "managed_live_direct"
_MAX_APPROVAL_TTL_SECONDS = 30.0


class CtpProductionActionBindingError(ValueError):
    """Redacted fail-closed rejection for a production per-action scope."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpProductionActionBindingError(reason, message) from None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


def _require_digest(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_production_action_scope", "invalid {0}".format(name))
    return value


def _require_timestamp(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        _reject("invalid_production_action_approval", "invalid {0}".format(name))
    return float(value)


def _scope_digest(scope: "CtpProductionActionCredentialScope") -> str:
    return hashlib.sha256(
        b"backtrader-ctp-production-action-credential-scope-v1\0"
        + _canonical(
            {
                "account_binding_sha256": scope.account_binding_sha256,
                "config_digest": scope.config_digest,
                "effective_digest": scope.effective_digest,
                "environment": scope.environment,
                "exchange_id": scope.exchange_id,
                "front_pair_sha256": scope.front_pair_sha256,
                "front_pair_set_sha256": scope.front_pair_set_sha256,
                "hedge_flag": scope.hedge_flag,
                "instrument_id": scope.instrument_id,
                "mode": scope.mode,
                "preset": scope.preset,
                "production_registration_digest": scope.production_registration_digest,
                "runtime_id": scope.runtime_id,
                "runtime_registration_digest": scope.runtime_registration_digest,
                "scope_identity_sha256": scope.scope_identity_sha256,
                "strategy_id": scope.strategy_id,
            }
        )
    ).hexdigest()


def _action_scope_digest(
    *,
    credential_scope_sha256: str,
    operation: str,
    request_digest: str,
    managed_intent_id: str,
    action_id: Optional[str],
) -> str:
    return hashlib.sha256(
        b"backtrader-ctp-production-per-action-scope-v1\0"
        + _canonical(
            {
                "action_id": action_id,
                "credential_scope_sha256": credential_scope_sha256,
                "managed_intent_id": managed_intent_id,
                "operation": operation,
                "request_digest": request_digest,
            }
        )
    ).hexdigest()


def ctp_production_action_scope_sha256(
    credential_scope: "CtpProductionActionCredentialScope",
    *,
    operation: str,
    request_digest: str,
    managed_intent_id: str,
    action_id: Optional[str] = None,
) -> str:
    """Return the production-domain digest a trusted signer must approve.

    This is an identity calculation only. It does not issue or verify an
    approval, inspect credentials, or authorize the action.
    """

    if type(credential_scope) is not CtpProductionActionCredentialScope:
        _reject("production_credential_scope_type_mismatch", "production credential scope required")
    if type(operation) is not str or operation not in ("SUBMIT", "CANCEL"):
        _reject("invalid_production_action_approval", "invalid production action")
    _require_digest(request_digest, "request_digest")
    if type(managed_intent_id) is not str or not _INTENT_ID_RE.fullmatch(managed_intent_id):
        _reject("invalid_production_action_approval", "invalid managed intent identity")
    if operation == "SUBMIT":
        if action_id is not None:
            _reject("invalid_production_action_approval", "submit action ID is forbidden")
    elif type(action_id) is not str or not _ACTION_ID_RE.fullmatch(action_id):
        _reject("invalid_production_action_approval", "cancel action ID is required")
    return _action_scope_digest(
        credential_scope_sha256=credential_scope.credential_scope_sha256,
        operation=operation,
        request_digest=request_digest,
        managed_intent_id=managed_intent_id,
        action_id=action_id,
    )


@dataclass(frozen=True)
class CtpProductionActionCredentialScope:
    """Private-value-free production identity for one selected CTP front pair."""

    runtime_id: str
    strategy_id: str
    config_digest: str
    effective_digest: str
    runtime_registration_digest: str
    production_registration_digest: str
    scope_identity_sha256: str
    account_binding_sha256: str = field(repr=False)
    front_pair_sha256: str
    front_pair_set_sha256: str
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    environment: str = field(default=_PRODUCTION_ENVIRONMENT, init=False)
    mode: str = field(default=_PRODUCTION_MODE, init=False)
    preset: str = field(default=_PRODUCTION_PRESET, init=False)
    credential_values_resolved: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    provider_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.runtime_id) is not str or not self.runtime_id:
            _reject("invalid_production_action_scope", "invalid runtime identity")
        if type(self.strategy_id) is not str or not self.strategy_id:
            _reject("invalid_production_action_scope", "invalid strategy identity")
        for name in (
            "config_digest",
            "effective_digest",
            "runtime_registration_digest",
            "production_registration_digest",
            "scope_identity_sha256",
            "account_binding_sha256",
            "front_pair_sha256",
            "front_pair_set_sha256",
        ):
            _require_digest(getattr(self, name), name)
        if (
            type(self.instrument_id) is not str
            or not self.instrument_id
            or type(self.exchange_id) is not str
            or not self.exchange_id
            or self.hedge_flag not in ("1", "2", "3")
        ):
            _reject("invalid_production_action_scope", "invalid production contract scope")

    @property
    def credential_scope_sha256(self) -> str:
        return _scope_digest(self)

    def __bool__(self) -> bool:
        raise TypeError("CtpProductionActionCredentialScope is non-authorizing evidence")

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "account_scope": "redacted",
            "config_digest": self.config_digest,
            "credential_access_authorized": self.credential_access_authorized,
            "credential_scope_sha256": self.credential_scope_sha256,
            "credential_values_resolved": self.credential_values_resolved,
            "effective_digest": self.effective_digest,
            "environment": self.environment,
            "execution_authorized": self.execution_authorized,
            "exchange_id": self.exchange_id,
            "external_writes_authorized": self.external_writes_authorized,
            "front_pair_sha256": self.front_pair_sha256,
            "front_pair_set_sha256": self.front_pair_set_sha256,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "mode": self.mode,
            "preset": self.preset,
            "provider_access_authorized": self.provider_access_authorized,
            "production_registration_digest": self.production_registration_digest,
            "runtime_id": self.runtime_id,
            "runtime_registration_digest": self.runtime_registration_digest,
            "scope_identity_sha256": self.scope_identity_sha256,
            "strategy_id": self.strategy_id,
        }


def derive_ctp_production_action_credential_scope(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionExecutionRegistration,
    *,
    selected_front_pair: Tuple[str, str],
    effective_runtime: EffectiveRuntimeConfig,
) -> CtpProductionActionCredentialScope:
    """Derive a scope only from the loader-sealed live config and production pin."""

    try:
        binding = require_ctp_production_execution_config_binding(
            config,
            registry,
            admission_registration,
            selected_front_pair=selected_front_pair,
            effective_runtime=effective_runtime,
        )
    except CtpProductionExecutionAdmissionError:
        _reject("production_execution_scope_rejected", "production execution scope was rejected")
    except Exception:
        _reject("production_execution_scope_rejected", "production execution scope was rejected")
    if (
        type(binding) is not CtpProductionExecutionConfigBinding
        or binding.environment != _PRODUCTION_ENVIRONMENT
        or binding.effective_digest != effective_runtime.effective_digest
        or binding.selected_front_index is None
        or binding.md_front != selected_front_pair[0]
        or binding.td_front != selected_front_pair[1]
        or config.mode != _PRODUCTION_MODE
        or config.preset != _PRODUCTION_PRESET
        or config.ctp is None
        or config.ctp_simnow is not None
        or config.ctp_production is not None
    ):
        _reject("production_execution_scope_incomplete", "production action scope is incomplete")
    return CtpProductionActionCredentialScope(
        runtime_id=binding.runtime_id,
        strategy_id=binding.strategy_id,
        config_digest=binding.config_digest,
        effective_digest=binding.effective_digest,
        runtime_registration_digest=binding.runtime_registration_digest,
        production_registration_digest=binding.registration_digest,
        scope_identity_sha256=binding.scope_identity_sha256,
        account_binding_sha256=binding.account_binding_sha256,
        front_pair_sha256=binding.front_pair_sha256,
        front_pair_set_sha256=binding.front_pair_set_sha256,
        instrument_id=binding.instrument_id,
        exchange_id=binding.exchange_id,
        hedge_flag=binding.hedge_flag,
    )


@dataclass(frozen=True)
class CtpProductionActionApproval:
    """Production-only, one-action approval claims for an injected verifier.

    This type is identity metadata. A caller-created instance is not trusted
    until the injected production verifier accepts its signed payload.
    """

    approval_id: str
    receipt_sha256: str
    credential_scope_sha256: str
    action_scope_sha256: str
    operation: str
    request_digest: str
    managed_intent_id: str
    action_id: Optional[str]
    issued_at: float
    expires_at: float
    signature_hex: str
    environment: str = field(default=_PRODUCTION_ENVIRONMENT, init=False)
    mode: str = field(default=_PRODUCTION_MODE, init=False)
    preset: str = field(default=_PRODUCTION_PRESET, init=False)

    def __post_init__(self) -> None:
        if type(self.approval_id) is not str or not _PRODUCTION_ID_RE.fullmatch(self.approval_id):
            _reject("invalid_production_action_approval", "invalid production approval identity")
        for name in (
            "receipt_sha256",
            "credential_scope_sha256",
            "action_scope_sha256",
            "request_digest",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.operation) is not str or self.operation not in ("SUBMIT", "CANCEL"):
            _reject("invalid_production_action_approval", "invalid production action")
        if type(self.managed_intent_id) is not str or not _INTENT_ID_RE.fullmatch(
            self.managed_intent_id
        ):
            _reject("invalid_production_action_approval", "invalid managed intent identity")
        if self.operation == "SUBMIT":
            if self.action_id is not None:
                _reject("invalid_production_action_approval", "submit action ID is forbidden")
        elif type(self.action_id) is not str or not _ACTION_ID_RE.fullmatch(self.action_id):
            _reject("invalid_production_action_approval", "cancel action ID is required")
        issued_at = _require_timestamp(self.issued_at, "issued_at")
        expires_at = _require_timestamp(self.expires_at, "expires_at")
        if expires_at <= issued_at or expires_at - issued_at > _MAX_APPROVAL_TTL_SECONDS:
            _reject("invalid_production_action_approval", "invalid production approval window")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        if type(self.signature_hex) is not str or _SHA256_RE.fullmatch(self.signature_hex) is None:
            _reject("invalid_production_action_approval", "invalid production approval signature")

    def signed_payload(self) -> bytes:
        return _canonical(
            {
                "action_id": self.action_id,
                "action_scope_sha256": self.action_scope_sha256,
                "approval_id": self.approval_id,
                "credential_scope_sha256": self.credential_scope_sha256,
                "environment": self.environment,
                "expires_at": self.expires_at,
                "issued_at": self.issued_at,
                "managed_intent_id": self.managed_intent_id,
                "mode": self.mode,
                "operation": self.operation,
                "preset": self.preset,
                "receipt_sha256": self.receipt_sha256,
                "request_digest": self.request_digest,
            }
        )


class CtpProductionActionApprovalVerifier(Protocol):
    """Production-only verifier for one canonical action-approval payload."""

    def verify(self, approval: CtpProductionActionApproval) -> bool:
        """Accept only a trusted production signature for this exact action."""


class CtpProductionActionTrustSource(CtpProductionActionApprovalVerifier, Protocol):
    """Injected clock, signature, and revocation observations for final checks.

    A future reviewed deployment composition must own this dependency. This
    protocol alone does not establish that ownership or make its observations
    trusted.
    """

    def now(self) -> float:
        """Return current wall-clock seconds for approval freshness checks."""

    def is_revoked(
        self, approval_id: str, receipt_sha256: str, action_scope_sha256: str
    ) -> Optional[bool]:
        """Return an exact revocation status; ``None`` means unknown."""


class RejectingCtpProductionActionApprovalVerifier:
    """Default verifier; no production per-action approval key is installed."""

    def verify(self, approval: CtpProductionActionApproval) -> bool:
        del approval
        return False


class RejectingCtpProductionActionTrustSource:
    """Default trust source; missing clock, signature, or revocation data fails closed."""

    def now(self) -> float:
        raise RuntimeError("production action trust source is not installed")

    def verify(self, approval: CtpProductionActionApproval) -> bool:
        del approval
        return False

    def is_revoked(
        self, approval_id: str, receipt_sha256: str, action_scope_sha256: str
    ) -> Optional[bool]:
        del approval_id, receipt_sha256, action_scope_sha256
        return None


@dataclass(frozen=True)
class CtpProductionActionCredentialBinding:
    """Per-action production scope evidence; every operational authority is false."""

    credential_scope_sha256: str
    action_scope_sha256: str
    config_digest: str
    effective_digest: str
    runtime_registration_digest: str
    production_registration_digest: str
    scope_identity_sha256: str
    receipt_sha256: str
    approval_id: str
    operation: str
    request_digest: str
    managed_intent_id: str
    action_id: Optional[str]
    environment: str = field(default=_PRODUCTION_ENVIRONMENT, init=False)
    mode: str = field(default=_PRODUCTION_MODE, init=False)
    preset: str = field(default=_PRODUCTION_PRESET, init=False)
    injected_verifier_accepted: bool = field(default=True, init=False)
    credential_values_resolved: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    provider_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "credential_scope_sha256",
            "action_scope_sha256",
            "config_digest",
            "effective_digest",
            "runtime_registration_digest",
            "production_registration_digest",
            "scope_identity_sha256",
            "receipt_sha256",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.approval_id) is not str or not _PRODUCTION_ID_RE.fullmatch(self.approval_id):
            _reject("invalid_production_action_binding", "invalid production approval identity")
        if self.operation not in ("SUBMIT", "CANCEL"):
            _reject("invalid_production_action_binding", "invalid production action")
        if (
            type(self.request_digest) is not str
            or _SHA256_RE.fullmatch(self.request_digest) is None
        ):
            _reject("invalid_production_action_binding", "invalid production request digest")

    def __bool__(self) -> bool:
        raise TypeError("CtpProductionActionCredentialBinding is non-authorizing evidence")

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_scope_sha256": self.action_scope_sha256,
            "approval_id": self.approval_id,
            "injected_verifier_accepted": self.injected_verifier_accepted,
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "config_digest": self.config_digest,
            "credential_access_authorized": self.credential_access_authorized,
            "credential_scope_sha256": self.credential_scope_sha256,
            "credential_values_resolved": self.credential_values_resolved,
            "effective_digest": self.effective_digest,
            "environment": self.environment,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "managed_intent_id": self.managed_intent_id,
            "mode": self.mode,
            "operation": self.operation,
            "order_submission_authorized": self.order_submission_authorized,
            "preset": self.preset,
            "production_registration_digest": self.production_registration_digest,
            "provider_access_authorized": self.provider_access_authorized,
            "receipt_sha256": self.receipt_sha256,
            "request_digest": self.request_digest,
            "runtime_registration_digest": self.runtime_registration_digest,
            "scope_identity_sha256": self.scope_identity_sha256,
        }


@dataclass(frozen=True)
class CtpProductionActionDispatchObservation:
    """Non-authorizing receipt from an injected dispatch-time trust recheck.

    A true injected verifier result and a clear injected revocation response do
    not prove that either dependency is trusted. This receipt never grants a
    credential, provider, execution, or write capability.
    """

    approval_id: str
    receipt_sha256: str
    credential_scope_sha256: str
    action_scope_sha256: str
    checked_at: float
    rechecked_at: float
    injected_verifier_accepted: bool = field(default=True, init=False)
    injected_revocation_checker_clear: bool = field(default=True, init=False)
    deployment_trust_established: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    provider_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.approval_id) is not str or not _PRODUCTION_ID_RE.fullmatch(self.approval_id):
            _reject("invalid_production_action_observation", "invalid approval identity")
        for name in ("receipt_sha256", "credential_scope_sha256", "action_scope_sha256"):
            _require_digest(getattr(self, name), name)
        checked_at = _require_timestamp(self.checked_at, "checked_at")
        rechecked_at = _require_timestamp(self.rechecked_at, "rechecked_at")
        if rechecked_at < checked_at:
            _reject("production_action_clock_rollback", "production action clock moved backwards")
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "rechecked_at", rechecked_at)

    def __bool__(self) -> bool:
        raise TypeError("CtpProductionActionDispatchObservation is non-authorizing evidence")

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "action_scope_sha256": self.action_scope_sha256,
            "approval_id": self.approval_id,
            "checked_at": self.checked_at,
            "credential_access_authorized": self.credential_access_authorized,
            "credential_scope_sha256": self.credential_scope_sha256,
            "deployment_trust_established": self.deployment_trust_established,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "injected_revocation_checker_clear": self.injected_revocation_checker_clear,
            "injected_verifier_accepted": self.injected_verifier_accepted,
            "provider_access_authorized": self.provider_access_authorized,
            "receipt_sha256": self.receipt_sha256,
            "rechecked_at": self.rechecked_at,
        }


def require_ctp_production_action_credential_binding(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionExecutionRegistration,
    *,
    effective_runtime: EffectiveRuntimeConfig,
    selected_front_pair: Tuple[str, str],
    credential_scope: CtpProductionActionCredentialScope,
    approval: CtpProductionActionApproval,
    checked_at: float,
    verifier: Optional[CtpProductionActionApprovalVerifier] = None,
) -> CtpProductionActionCredentialBinding:
    """Verify distinct production credentials and approval scopes for one action.

    The supplied ``credential_scope`` must be freshly derived from this exact
    loader-sealed config/effective profile and production registration. The
    action approval binds that scope plus the exact action digest, intent and
    cancel identity. SimNow approval or credential objects fail the strict
    production type checks before the injected verifier is called. This helper
    uses caller-supplied ``checked_at`` and an injected verifier, so its result
    records only those inputs; it cannot establish trusted time, verifier
    ownership, revocation status, or dispatch authority.
    """

    if type(credential_scope) is not CtpProductionActionCredentialScope:
        _reject(
            "production_credential_scope_type_mismatch",
            "a production action credential scope is required",
        )
    if type(approval) is not CtpProductionActionApproval:
        _reject(
            "production_action_approval_type_mismatch",
            "a production per-action approval is required",
        )
    try:
        expected_scope = derive_ctp_production_action_credential_scope(
            config,
            registry,
            admission_registration,
            selected_front_pair=selected_front_pair,
            effective_runtime=effective_runtime,
        )
    except CtpProductionActionBindingError:
        raise
    if credential_scope != expected_scope:
        _reject("production_credential_scope_stale", "production credential scope is stale")

    request_digest = _require_digest(approval.request_digest, "request_digest")
    action_scope_sha256 = ctp_production_action_scope_sha256(
        expected_scope,
        operation=approval.operation,
        request_digest=request_digest,
        managed_intent_id=approval.managed_intent_id,
        action_id=approval.action_id,
    )
    if (
        approval.receipt_sha256 != admission_registration.approval_receipt_sha256
        or approval.credential_scope_sha256 != expected_scope.credential_scope_sha256
        or approval.action_scope_sha256 != action_scope_sha256
        or approval.environment != _PRODUCTION_ENVIRONMENT
        or approval.mode != _PRODUCTION_MODE
        or approval.preset != _PRODUCTION_PRESET
    ):
        _reject("production_action_approval_scope_mismatch", "production action scope mismatch")

    checked_at_value = _require_timestamp(checked_at, "checked_at")
    if approval.issued_at > checked_at_value or approval.expires_at <= checked_at_value:
        _reject("production_action_approval_expired", "production action approval is not current")
    selected_verifier = (
        verifier if verifier is not None else RejectingCtpProductionActionApprovalVerifier()
    )
    try:
        verified = selected_verifier.verify(approval)
    except Exception:
        _reject("production_action_approval_verifier_failed", "production action verifier failed")
    if verified is not True:
        _reject("production_action_approval_rejected", "production action approval was rejected")

    return CtpProductionActionCredentialBinding(
        credential_scope_sha256=expected_scope.credential_scope_sha256,
        action_scope_sha256=action_scope_sha256,
        config_digest=expected_scope.config_digest,
        effective_digest=expected_scope.effective_digest,
        runtime_registration_digest=expected_scope.runtime_registration_digest,
        production_registration_digest=expected_scope.production_registration_digest,
        scope_identity_sha256=expected_scope.scope_identity_sha256,
        receipt_sha256=approval.receipt_sha256,
        approval_id=approval.approval_id,
        operation=approval.operation,
        request_digest=request_digest,
        managed_intent_id=approval.managed_intent_id,
        action_id=approval.action_id,
    )


def observe_ctp_production_action_dispatch_revalidation(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionExecutionRegistration,
    *,
    effective_runtime: EffectiveRuntimeConfig,
    selected_front_pair: Tuple[str, str],
    credential_scope: CtpProductionActionCredentialScope,
    approval: CtpProductionActionApproval,
    trust_source: Optional[CtpProductionActionTrustSource] = None,
) -> CtpProductionActionDispatchObservation:
    """Recheck exact action scope, injected revocation and approval freshness.

    The supplied trust source is a seam for a future code-owned deployment
    composition. An arbitrary source accepted here can produce this
    non-authorizing observation only; it cannot establish deployment trust or
    authorize a dispatch. With no source installed, the default rejects.

    The clock is read before signature verification and again after revocation
    checking. The second read rejects a clock rollback and ensures the
    approval is still current after the injected checks have completed.
    """

    source = trust_source if trust_source is not None else RejectingCtpProductionActionTrustSource()
    try:
        checked_at = _require_timestamp(source.now(), "checked_at")
    except CtpProductionActionBindingError:
        raise
    except Exception:
        _reject("production_action_trust_clock_failed", "production action clock failed")

    binding = require_ctp_production_action_credential_binding(
        config,
        registry,
        admission_registration,
        effective_runtime=effective_runtime,
        selected_front_pair=selected_front_pair,
        credential_scope=credential_scope,
        approval=approval,
        checked_at=checked_at,
        verifier=source,
    )

    try:
        revoked = source.is_revoked(
            approval.approval_id,
            approval.receipt_sha256,
            binding.action_scope_sha256,
        )
    except Exception:
        _reject(
            "production_action_revocation_check_failed",
            "production action revocation check failed",
        )
    if type(revoked) is not bool:
        _reject(
            "production_action_revocation_unknown",
            "production action revocation status is unknown",
        )
    if revoked:
        _reject("production_action_revoked", "production action approval was revoked")

    try:
        rechecked_at = _require_timestamp(source.now(), "rechecked_at")
    except CtpProductionActionBindingError:
        raise
    except Exception:
        _reject("production_action_trust_clock_failed", "production action clock failed")
    if rechecked_at < checked_at:
        _reject("production_action_clock_rollback", "production action clock moved backwards")
    if approval.issued_at > rechecked_at or approval.expires_at <= rechecked_at:
        _reject("production_action_approval_expired", "production action approval is not current")

    return CtpProductionActionDispatchObservation(
        approval_id=approval.approval_id,
        receipt_sha256=approval.receipt_sha256,
        credential_scope_sha256=binding.credential_scope_sha256,
        action_scope_sha256=binding.action_scope_sha256,
        checked_at=checked_at,
        rechecked_at=rechecked_at,
    )


__all__ = [
    "CtpProductionActionApproval",
    "CtpProductionActionApprovalVerifier",
    "CtpProductionActionBindingError",
    "CtpProductionActionCredentialBinding",
    "CtpProductionActionCredentialScope",
    "CtpProductionActionDispatchObservation",
    "CtpProductionActionTrustSource",
    "RejectingCtpProductionActionApprovalVerifier",
    "RejectingCtpProductionActionTrustSource",
    "ctp_production_action_scope_sha256",
    "derive_ctp_production_action_credential_scope",
    "observe_ctp_production_action_dispatch_revalidation",
    "require_ctp_production_action_credential_binding",
]
