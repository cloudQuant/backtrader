"""External receipt-to-scope binding for a future CTP production route.

This module provides a pure, non-authorizing check for one exact
``sealed_config`` production scope.  A trusted verifier receives the pair
``(receipt digest, scope identity)`` and looks it up in independently held
trust data.  Receipt data never carries its own scope-identity claim here;
the default verifier rejects every pair.

The result records a verified mapping and its expiry.  It does not authorize
credentials, provider access, execution, or external writes, and this module
does not resolve configuration files, read secrets, import an SDK, or itself
make network calls.  The injected verifier may perform I/O; that behavior is
outside this module's purity boundary.  The caller supplies both the verifier
and ``checked_at``; this module cannot establish that either is trusted,
current, or backed by a revocation check.  A production composition must own
those injections.  The observation means only that the injected verifier
accepted the supplied receipt/scope pair at the supplied timestamp.  Scope
validation rechecks an in-memory sealed ``RuntimeConfig``; it does not detect
later edits to the protected file on disk.  Any future writer must reload and
reseal the config, or retain its verified file identity, immediately before
credential/session/write work.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple

from .config import RuntimeConfig
from .ctp_production_execution_admission import (
    CtpProductionExecutionAdmissionError,
    CtpProductionExecutionConfigBinding,
    CtpProductionExecutionRegistration,
    require_ctp_production_execution_config_binding,
)
from .registry import EffectiveRuntimeConfig, RuntimeRegistry


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCTION_ENVIRONMENT = "production"


class CtpProductionApprovalBindingError(ValueError):
    """Redacted, fail-closed rejection of a receipt-to-scope mapping."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpProductionApprovalBindingError(reason, message) from None


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_digest", "invalid {0}".format(name))
    return value


def _timestamp(value: object, name: str) -> float:
    if type(value) not in (int, float):
        _reject("invalid_timestamp", "invalid {0}".format(name))
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject("invalid_timestamp", "invalid {0}".format(name))
    if not math.isfinite(normalized):
        _reject("invalid_timestamp", "invalid {0}".format(name))
    return 0.0 if normalized == 0.0 else normalized


@dataclass(frozen=True)
class CtpProductionApprovalReceiptMetadata:
    """Trusted receipt metadata returned by the injected mapping verifier.

    This intentionally has no scope identity field.  The verifier receives
    the expected identity as a separate lookup key, so a receipt cannot assert
    which scope it approves.
    """

    receipt_sha256: str
    environment: str
    expires_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_sha256", _digest(self.receipt_sha256, "receipt_sha256"))
        if type(self.environment) is not str or not self.environment:
            _reject("invalid_environment", "invalid receipt environment")
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))


class CtpProductionApprovalBindingVerifier(Protocol):
    """Code-injected lookup over independently trusted receipt/scope pairs."""

    def verify(
        self, receipt_sha256: str, scope_identity_sha256: str
    ) -> Optional[CtpProductionApprovalReceiptMetadata]:
        """Return trusted metadata only for this exact external mapping."""


class RejectingCtpProductionApprovalBindingVerifier:
    """Default verifier; no production approval mapping is installed."""

    def verify(
        self, receipt_sha256: str, scope_identity_sha256: str
    ) -> Optional[CtpProductionApprovalReceiptMetadata]:
        del receipt_sha256, scope_identity_sha256
        return None


@dataclass(frozen=True)
class CtpProductionApprovalBindingObservation:
    """Verified metadata for one scope; every operational authority is false."""

    receipt_id: str
    receipt_sha256: str
    environment: str
    scope_identity_sha256: str
    config_digest: str
    effective_digest: str
    registration_digest: str
    runtime_registration_digest: str
    account_binding_sha256: str = field(repr=False)
    front_pair_sha256: str
    front_pair_set_sha256: str
    selected_front_index: int
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    checked_at: float
    valid_until: float
    injected_verifier_accepted: bool = field(default=True, init=False)
    provider_access_authorized: bool = field(default=False, init=False)
    credential_access_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    external_writes_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    cancellation_authorized: bool = field(default=False, init=False)
    arming_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "receipt_sha256",
            "scope_identity_sha256",
            "config_digest",
            "effective_digest",
            "registration_digest",
            "runtime_registration_digest",
            "account_binding_sha256",
            "front_pair_sha256",
            "front_pair_set_sha256",
        ):
            _digest(getattr(self, name), name)
        if self.environment != _PRODUCTION_ENVIRONMENT:
            _reject("environment_mismatch", "approval binding is not for production")
        if type(self.selected_front_index) is not int or self.selected_front_index < 0:
            _reject("selected_front_required", "approval binding requires a selected front pair")
        if type(self.checked_at) not in (int, float) or type(self.valid_until) not in (int, float):
            _reject("invalid_timestamp", "invalid approval binding time")
        checked_at = _timestamp(self.checked_at, "checked_at")
        valid_until = _timestamp(self.valid_until, "valid_until")
        if valid_until <= checked_at:
            _reject("receipt_expired", "production approval mapping has expired")
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "valid_until", valid_until)

    def __bool__(self) -> bool:
        raise TypeError("CtpProductionApprovalBindingObservation is non-authorizing evidence")

    def as_public_dict(self) -> dict:
        """Return bounded identities and status without account/front values."""

        return {
            "approval_receipt_id": self.receipt_id,
            "approval_receipt_sha256": self.receipt_sha256,
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "checked_at": self.checked_at,
            "config_digest": self.config_digest,
            "credential_access_authorized": self.credential_access_authorized,
            "environment": self.environment,
            "execution_authorized": self.execution_authorized,
            "exchange_id": self.exchange_id,
            "external_writes_authorized": self.external_writes_authorized,
            "front_pair_set_sha256": self.front_pair_set_sha256,
            "front_pair_sha256": self.front_pair_sha256,
            "hedge_flag": self.hedge_flag,
            "instrument_id": self.instrument_id,
            "order_submission_authorized": self.order_submission_authorized,
            "provider_access_authorized": self.provider_access_authorized,
            "registration_digest": self.registration_digest,
            "runtime_registration_digest": self.runtime_registration_digest,
            "scope_identity_sha256": self.scope_identity_sha256,
            "injected_verifier_accepted": self.injected_verifier_accepted,
            "selected_front_index": self.selected_front_index,
            "valid_until": self.valid_until,
        }


def require_ctp_production_approval_binding(
    config: RuntimeConfig,
    registry: RuntimeRegistry,
    admission_registration: CtpProductionExecutionRegistration,
    *,
    selected_front_pair: Tuple[str, str],
    effective_runtime: EffectiveRuntimeConfig,
    checked_at: float,
    verifier: Optional[CtpProductionApprovalBindingVerifier] = None,
) -> CtpProductionApprovalBindingObservation:
    """Verify one trusted external receipt-digest/scope-identity mapping.

    ``config``, ``registry``, and ``effective_runtime`` must be the same sealed
    production configuration.  The front pair is mandatory so the computed
    scope identity includes the exact selected pair and candidate-set digest.
    ``checked_at`` is supplied by the caller, keeping this function pure and
    making the expiry check explicit.  This value is not trusted time and may
    be backdated by a caller; revocation is not checked.  A real deployment
    must own both the verifier and time source in trusted composition.  The
    function itself makes no network calls, though the injected verifier may
    perform I/O.  The default verifier rejects.  The sealed config check is
    for this in-memory object and does not observe later on-disk edits; future
    admission must reload/reseal it or retain a verified file identity
    immediately before credential, session, or write work.

    A successful observation means only that the injected verifier accepted
    this digest/identity mapping for the caller-supplied timestamp.  The code
    does not enforce verifier authenticity, time trust, or revocation status.
    The observation never grants execution or provider authority.
    """

    if type(admission_registration) is not CtpProductionExecutionRegistration:
        _reject("registration_required", "a code-owned production registration is required")
    if admission_registration.scope_binding_mode != "sealed_config":
        _reject("sealed_config_required", "approval binding requires sealed-config production scope")
    if type(effective_runtime) is not EffectiveRuntimeConfig:
        _reject("effective_config_required", "a sealed effective production config is required")
    if type(selected_front_pair) is not tuple or len(selected_front_pair) != 2:
        _reject("selected_front_required", "an exact configured production front pair is required")
    checked_at_value = _timestamp(checked_at, "checked_at")

    try:
        binding = require_ctp_production_execution_config_binding(
            config,
            registry,
            admission_registration,
            selected_front_pair=selected_front_pair,
            effective_runtime=effective_runtime,
        )
    except CtpProductionExecutionAdmissionError:
        _reject("scope_binding_rejected", "sealed production scope failed validation")
    except Exception:
        _reject("scope_binding_rejected", "sealed production scope failed validation")

    if (
        type(binding) is not CtpProductionExecutionConfigBinding
        or binding.environment != _PRODUCTION_ENVIRONMENT
        or binding.effective_digest is None
        or binding.selected_front_index is None
        or binding.md_front is None
        or binding.td_front is None
        or binding.registration_digest != admission_registration.digest
        or binding.approval_receipt_sha256 != admission_registration.approval_receipt_sha256
    ):
        _reject("scope_binding_incomplete", "sealed production scope identity is incomplete")

    receipt_sha256 = _digest(
        admission_registration.approval_receipt_sha256, "approval_receipt_sha256"
    )
    scope_identity_sha256 = _digest(binding.scope_identity_sha256, "scope_identity_sha256")
    selected_verifier = (
        verifier if verifier is not None else RejectingCtpProductionApprovalBindingVerifier()
    )
    try:
        verified_metadata = selected_verifier.verify(receipt_sha256, scope_identity_sha256)
    except Exception:
        _reject("approval_verifier_failed", "production approval mapping verifier failed")
    if type(verified_metadata) is not CtpProductionApprovalReceiptMetadata:
        _reject("approval_mapping_untrusted", "production receipt is not mapped to this scope")

    # Copy and revalidate verifier output before retaining it.  The verifier
    # receives only primitive lookup keys and cannot supply a scope claim.
    try:
        metadata = CtpProductionApprovalReceiptMetadata(
            receipt_sha256=verified_metadata.receipt_sha256,
            environment=verified_metadata.environment,
            expires_at=verified_metadata.expires_at,
        )
    except Exception:
        _reject("approval_metadata_invalid", "production approval metadata is invalid")
    if metadata.receipt_sha256 != receipt_sha256:
        _reject("receipt_digest_mismatch", "trusted receipt digest does not match registration")
    if metadata.environment != _PRODUCTION_ENVIRONMENT:
        _reject("environment_mismatch", "trusted approval mapping is not for production")
    if metadata.expires_at <= checked_at_value:
        _reject("receipt_expired", "production approval mapping has expired")

    return CtpProductionApprovalBindingObservation(
        receipt_id=admission_registration.approval_receipt_id,
        receipt_sha256=metadata.receipt_sha256,
        environment=metadata.environment,
        scope_identity_sha256=scope_identity_sha256,
        config_digest=binding.config_digest,
        effective_digest=binding.effective_digest,
        registration_digest=binding.registration_digest,
        runtime_registration_digest=binding.runtime_registration_digest,
        account_binding_sha256=binding.account_binding_sha256,
        front_pair_sha256=binding.front_pair_sha256,
        front_pair_set_sha256=binding.front_pair_set_sha256,
        selected_front_index=binding.selected_front_index,
        instrument_id=binding.instrument_id,
        exchange_id=binding.exchange_id,
        hedge_flag=binding.hedge_flag,
        checked_at=checked_at_value,
        valid_until=metadata.expires_at,
    )


__all__ = [
    "CtpProductionApprovalBindingError",
    "CtpProductionApprovalBindingObservation",
    "CtpProductionApprovalBindingVerifier",
    "CtpProductionApprovalReceiptMetadata",
    "RejectingCtpProductionApprovalBindingVerifier",
    "require_ctp_production_approval_binding",
]
