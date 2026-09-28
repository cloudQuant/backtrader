"""Typed seam for an external F14 account fence and coherent snapshot authority.

This module defines a contract only.  It contains no network client, key,
provider access, local-lock fallback, or write-route integration.  A future
code-owned composition must supply an independently authenticated authority
that atomically claims one action, fences every writer for the account, and
attests a complete account snapshot captured under that same fence/version.
Independent CTP query terminal replies cannot satisfy that snapshot contract.

The returned admission handle contains no caller-supplied proof parameter:
the authority is asked for a claim from the exact request and its response is
checked against that request.  The authority remains a critical external
dependency; a fake or caller-controlled implementation is useful for local
contract tests only and does not provide authorization.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Protocol


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUIRED_SNAPSHOT_COVERAGE = (
    "account_funds",
    "open_orders",
    "positions",
    "trades",
)
_VALID_ROUTE_PAIRS = frozenset(
    (("simnow", "simulation", "sandbox"), ("production", "live", "managed_live_direct"))
)


class CtpF14AdmissionError(ValueError):
    """Redacted, fail-closed rejection from the F14 contract seam."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


def _reject(reason: str) -> None:
    raise CtpF14AdmissionError(reason)


def _require_id(value: object, field: str) -> str:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        _reject("invalid_" + field)
    return value


def _require_digest(value: object, field: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _reject("invalid_" + field)
    return value


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class CtpF14SessionBinding:
    """Exact, non-secret native session identity supplied by the composition."""

    session_id: str
    trading_day: str
    connection_generation: int
    identity_digest: str

    def __post_init__(self) -> None:
        _require_id(self.session_id, "session_id")
        if type(self.trading_day) is not str or not re.fullmatch(r"[0-9]{8}", self.trading_day):
            _reject("invalid_session_trading_day")
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            _reject("invalid_session_connection_generation")
        _require_digest(self.identity_digest, "session_identity_digest")


@dataclass(frozen=True)
class CtpF14ActionRequest:
    """All immutable identity needed to authorize one submit or cancel action.

    ``artifact_set_digest`` must cover the exact approved base, CTP and parent
    artifacts plus their installed origins.  ``approval_digest`` names the
    fresh one-action approval.  ``target_digest`` is required for cancellation
    and forbidden for submit; it is a digest of the exact provider target.
    """

    runtime_id: str
    environment: str
    mode: str
    preset: str
    account_fingerprint_sha256: str
    config_digest: str
    effective_digest: str
    registration_digest: str
    artifact_set_digest: str
    session: CtpF14SessionBinding
    action_kind: str
    action_id: str
    action_digest: str
    approval_digest: str
    target_digest: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.runtime_id, "runtime_id")
        if (
            type(self.environment) is not str
            or type(self.mode) is not str
            or type(self.preset) is not str
            or (self.environment, self.mode, self.preset) not in _VALID_ROUTE_PAIRS
        ):
            _reject("f14_route_scope_invalid")
        for name in (
            "account_fingerprint_sha256",
            "config_digest",
            "effective_digest",
            "registration_digest",
            "artifact_set_digest",
            "action_digest",
            "approval_digest",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.session) is not CtpF14SessionBinding:
            _reject("f14_session_binding_required")
        if type(self.action_kind) is not str or self.action_kind not in ("SUBMIT", "CANCEL"):
            _reject("f14_action_kind_invalid")
        _require_id(self.action_id, "action_id")
        if self.action_kind == "CANCEL":
            _require_digest(self.target_digest, "target_digest")
        elif self.target_digest is not None:
            _reject("submit_target_digest_forbidden")

    @property
    def scope_digest(self) -> str:
        """Digest of route, account, config, artifacts and exact session."""

        return _canonical_digest(
            {
                "account_fingerprint_sha256": self.account_fingerprint_sha256,
                "artifact_set_digest": self.artifact_set_digest,
                "config_digest": self.config_digest,
                "effective_digest": self.effective_digest,
                "environment": self.environment,
                "mode": self.mode,
                "preset": self.preset,
                "registration_digest": self.registration_digest,
                "runtime_id": self.runtime_id,
                "session": {
                    "connection_generation": self.session.connection_generation,
                    "identity_digest": self.session.identity_digest,
                    "session_id": self.session.session_id,
                    "trading_day": self.session.trading_day,
                },
            }
        )

    @property
    def request_digest(self) -> str:
        """Digest of the exact action and its bound scope."""

        return _canonical_digest(
            {
                "action_digest": self.action_digest,
                "action_id": self.action_id,
                "action_kind": self.action_kind,
                "approval_digest": self.approval_digest,
                "scope_digest": self.scope_digest,
                "target_digest": self.target_digest,
            }
        )


@dataclass(frozen=True)
class CtpF14ExternalAdmissionClaim:
    """Typed response from an independently authenticated external authority.

    These fields are not self-authenticating.  Only a code-owned authority
    adapter that validates its remote trust root may construct/return one for
    admission.  The snapshot must be account-wide and complete at a single
    authoritative version while the returned fence epoch is held.
    """

    binding: CtpF14ActionRequest
    authority_id: str
    claim_id: str
    fence_id: str
    fence_epoch: int
    fence_scope_digest: str
    snapshot_id: str
    snapshot_version: str
    snapshot_digest: str
    snapshot_coverage_digest: str
    snapshot_account_fingerprint_sha256: str
    snapshot_fence_id: str
    snapshot_fence_epoch: int
    snapshot_coverage: tuple[str, ...]
    account_writer_exclusive: bool
    snapshot_complete: bool
    snapshot_consistent: bool
    issued_at_utc: float
    expires_at_utc: float
    authority_receipt_digest: str

    def __post_init__(self) -> None:
        if type(self.binding) is not CtpF14ActionRequest:
            _reject("external_claim_binding_invalid")
        for name in ("authority_id", "claim_id", "fence_id", "snapshot_id", "snapshot_version"):
            _require_id(getattr(self, name), name)
        for name in (
            "fence_scope_digest",
            "snapshot_digest",
            "snapshot_coverage_digest",
            "snapshot_account_fingerprint_sha256",
            "authority_receipt_digest",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.fence_epoch) is not int or self.fence_epoch <= 0:
            _reject("external_claim_fence_epoch_invalid")
        if type(self.snapshot_fence_epoch) is not int or self.snapshot_fence_epoch <= 0:
            _reject("external_claim_snapshot_fence_epoch_invalid")
        _require_id(self.snapshot_fence_id, "snapshot_fence_id")
        if type(self.snapshot_coverage) is not tuple or any(
            type(item) is not str for item in self.snapshot_coverage
        ):
            _reject("external_claim_snapshot_coverage_invalid")
        if type(self.account_writer_exclusive) is not bool:
            _reject("external_claim_fence_assertion_invalid")
        if type(self.snapshot_complete) is not bool or type(self.snapshot_consistent) is not bool:
            _reject("external_claim_snapshot_assertion_invalid")
        if (
            type(self.issued_at_utc) not in (int, float)
            or type(self.expires_at_utc) not in (int, float)
            or not math.isfinite(float(self.issued_at_utc))
            or not math.isfinite(float(self.expires_at_utc))
            or self.expires_at_utc <= self.issued_at_utc
        ):
            _reject("external_claim_time_bounds_invalid")


class CtpF14ExternalAdmissionAuthority(Protocol):
    """External, independently authenticated account control service.

    ``claim_and_verify`` must atomically: establish exclusive control over all
    account writers (including other hosts, users and direct SDK clients);
    read/verify a complete account-wide snapshot with one authoritative
    version under that fence; and consume exactly one current action grant
    bound to ``request``.  It must authenticate its source and reject stale,
    replayed or revoked state before returning.  Returning seven separately
    terminal CTP query results is insufficient.

    ``assert_active`` must freshly confirm that the one-action claim remains
    live, unrevoked and fenced before each native dispatch.  The method must
    return literal ``True`` only while all those conditions still hold.
    """

    def claim_and_verify(self, request: CtpF14ActionRequest) -> CtpF14ExternalAdmissionClaim:
        ...

    def assert_active(
        self, claim: CtpF14ExternalAdmissionClaim, *, request: CtpF14ActionRequest
    ) -> bool:
        ...


def _validate_claim(request: CtpF14ActionRequest, claim: object) -> CtpF14ExternalAdmissionClaim:
    if type(claim) is not CtpF14ExternalAdmissionClaim:
        _reject("external_admission_claim_invalid")
    if claim.binding != request or claim.fence_scope_digest != request.scope_digest:
        _reject("external_admission_scope_mismatch")
    if (
        claim.account_writer_exclusive is not True
        or claim.snapshot_complete is not True
        or claim.snapshot_consistent is not True
    ):
        _reject("external_admission_evidence_incomplete")
    if claim.snapshot_coverage != _REQUIRED_SNAPSHOT_COVERAGE:
        _reject("external_admission_snapshot_coverage_incomplete")
    if (
        claim.snapshot_account_fingerprint_sha256 != request.account_fingerprint_sha256
        or claim.snapshot_fence_id != claim.fence_id
        or claim.snapshot_fence_epoch != claim.fence_epoch
    ):
        _reject("external_admission_snapshot_scope_mismatch")
    return claim


class CtpF14ActionAdmission:
    """Ephemeral claim handle; call :meth:`assert_active` before native use."""

    __slots__ = ("_authority", "_request", "_claim")

    def __init__(
        self,
        authority: CtpF14ExternalAdmissionAuthority,
        request: CtpF14ActionRequest,
        claim: CtpF14ExternalAdmissionClaim,
        *,
        _construction_key: object,
    ) -> None:
        if _construction_key is not _ADMISSION_CONSTRUCTION_KEY:
            _reject("f14_admission_factory_required")
        self._authority = authority
        self._request = request
        self._claim = claim

    @property
    def request_digest(self) -> str:
        return self._request.request_digest

    @property
    def scope_digest(self) -> str:
        return self._request.scope_digest

    def assert_active(self) -> None:
        """Recheck external fence and one-action claim; any uncertainty rejects."""

        try:
            result = self._authority.assert_active(self._claim, request=self._request)
        except Exception:
            _reject("external_admission_recheck_unavailable")
        if result is not True:
            _reject("external_admission_no_longer_active")


_ADMISSION_CONSTRUCTION_KEY = object()


def claim_f14_action(
    authority: CtpF14ExternalAdmissionAuthority,
    request: CtpF14ActionRequest,
) -> CtpF14ActionAdmission:
    """Ask the external authority to claim one exact action and validate its response.

    No receipt/evidence argument is accepted.  This function is an offline
    integration seam only; it grants no runtime capability until a reviewed,
    code-owned composition binds a pinned authority implementation and calls
    :meth:`CtpF14ActionAdmission.assert_active` immediately before dispatch.
    """

    if type(request) is not CtpF14ActionRequest:
        _reject("f14_action_request_required")
    claim_method = getattr(authority, "claim_and_verify", None)
    active_method = getattr(authority, "assert_active", None)
    if not callable(claim_method) or not callable(active_method):
        _reject("external_admission_authority_required")
    try:
        claim = claim_method(request)
    except Exception:
        _reject("external_admission_authority_unavailable")
    validated = _validate_claim(request, claim)
    return CtpF14ActionAdmission(
        authority,
        request,
        validated,
        _construction_key=_ADMISSION_CONSTRUCTION_KEY,
    )


__all__ = [
    "CtpF14ActionAdmission",
    "CtpF14ActionRequest",
    "CtpF14AdmissionError",
    "CtpF14ExternalAdmissionAuthority",
    "CtpF14ExternalAdmissionClaim",
    "CtpF14SessionBinding",
    "claim_f14_action",
]
