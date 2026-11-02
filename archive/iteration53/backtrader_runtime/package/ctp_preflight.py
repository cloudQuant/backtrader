"""Pure, injected CTP SimNow read-only session-preflight contract.

This module is intentionally a narrow composition boundary.  It does not
import a CTP SDK, resolve a secret, choose a network endpoint, or provide a
default session factory.  A caller must inject a read-only session factory
after obtaining both :class:`ProviderSessionPreflightBinding` and a verified
test-execution profile observation through the sealed runtime path.

The result is evidence that one injected session returned a stable, complete
read-only query summary.  It is not an execution permit, an order route, or a
claim that SimNow has been connected successfully in a real environment.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import hmac
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence, Tuple

from .provider_deployment import (
    ProviderDeploymentReceiptValidation,
    ProviderDeploymentReceiptVerifier,
)
from .provider_preflight import (
    ProviderSessionPreflightBinding,
    ProviderSessionPreflightRegistration,
    validate_provider_session_preflight_binding,
)
from .registry import EffectiveRuntimeConfig, RuntimeRegistry
from .test_execution_profile import (
    TEST_EXECUTION_PROFILE_PRECHECKED,
    TestExecutionPreflightContext,
    TestExecutionProfileObservation,
    TestExecutionProfileVerifier,
    validate_test_execution_profile,
)


CTP_PROVIDER = "ctp"
CTP_SIMNOW_ENVIRONMENT_PATTERN = r"^simnow(?:_set[1-9][0-9]*)?$"
REQUIRED_CTP_READ_ONLY_QUERIES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
    "margin_rates",
    "commission_rates",
)
_REQUIRED_RATE_EXCHANGE_SCOPES = ("commission_rates", "margin_rates")
_RATE_EXCHANGE_SCOPE_VALUES = frozenset(("exact", "unverified"))

_CTP_SIMNOW_ENVIRONMENT_RE = re.compile(CTP_SIMNOW_ENVIRONMENT_PATTERN)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CtpReadOnlyPreflightError(ValueError):
    """A redacted, fail-closed CTP read-only preflight rejection."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise CtpReadOnlyPreflightError(reason, message)


def _sha256(value: Any, field_name: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _reject("invalid_digest", "invalid {0}".format(field_name))
    return value


def _simnow_environment(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or value != value.strip()
        or not _CTP_SIMNOW_ENVIRONMENT_RE.fullmatch(value)
    ):
        _reject("environment_not_simnow", "invalid SimNow {0}".format(field_name))
    return value


def _trading_day(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{8}", value):
        _reject("invalid_trading_day", "invalid CTP trading day")
    try:
        _datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError:
        _reject("invalid_trading_day", "invalid CTP trading day")
    return value


def _connection_generation(value: Any) -> int:
    if type(value) is not int or value <= 0 or value > (2**63 - 1):
        _reject("invalid_connection_generation", "invalid CTP connection generation")
    return value


def _timestamp(value: Any, field_name: str) -> float:
    if type(value) not in (int, float):
        _reject("invalid_timestamp", "invalid {0}".format(field_name))
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject("invalid_timestamp", "invalid {0}".format(field_name))
    if not math.isfinite(normalized):
        _reject("invalid_timestamp", "invalid {0}".format(field_name))
    return 0.0 if normalized == 0.0 else normalized


@dataclass(frozen=True)
class CtpReadOnlySessionIdentity:
    """The non-secret identity facts returned by one CTP session."""

    provider: str
    environment: str
    account_fingerprint_sha256: str = field(repr=False)
    trading_day: str
    connection_generation: int

    def __post_init__(self) -> None:
        if self.provider != CTP_PROVIDER:
            _reject("provider_not_ctp", "CTP read-only preflight requires provider ctp")
        object.__setattr__(
            self, "environment", _simnow_environment(self.environment, "environment")
        )
        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256"),
        )
        object.__setattr__(self, "trading_day", _trading_day(self.trading_day))
        object.__setattr__(
            self, "connection_generation", _connection_generation(self.connection_generation)
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return session facts without a reversible low-entropy account hash."""

        return {
            "account_scope": "redacted",
            "connection_generation": self.connection_generation,
            "environment": self.environment,
            "provider": self.provider,
            "trading_day": self.trading_day,
        }


def _normalise_identity(value: Any, field_name: str) -> CtpReadOnlySessionIdentity:
    if type(value) is not CtpReadOnlySessionIdentity:
        _reject("invalid_session_identity", "invalid {0}".format(field_name))
    return CtpReadOnlySessionIdentity(
        provider=value.provider,
        environment=value.environment,
        account_fingerprint_sha256=value.account_fingerprint_sha256,
        trading_day=value.trading_day,
        connection_generation=value.connection_generation,
    )


def _normalise_query_digests(value: Any) -> Tuple[Tuple[str, str], ...]:
    if type(value) not in (tuple, list):
        _reject("invalid_query_snapshot", "query snapshot must contain query digest pairs")

    pairs = tuple(value)
    names = []
    normalized = []
    for pair in pairs:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            _reject("invalid_query_snapshot", "invalid CTP query digest pair")
        name, digest = pair
        if type(name) is not str or name not in REQUIRED_CTP_READ_ONLY_QUERIES:
            _reject("unexpected_query", "CTP query snapshot contains an unsupported query")
        names.append(name)
        normalized.append((name, _sha256(digest, "query_digest")))

    if len(set(names)) != len(names):
        _reject("duplicate_query", "CTP query snapshot contains a duplicate query")
    missing = tuple(name for name in REQUIRED_CTP_READ_ONLY_QUERIES if name not in names)
    if missing:
        _reject("missing_required_query", "CTP query snapshot is incomplete")
    if len(names) != len(REQUIRED_CTP_READ_ONLY_QUERIES):
        _reject("invalid_query_snapshot", "CTP query snapshot has an invalid query count")
    return tuple(sorted(normalized))


def _normalise_rate_exchange_scopes(value: Any) -> Tuple[Tuple[str, str], ...]:
    if type(value) not in (tuple, list):
        _reject("invalid_rate_exchange_scope", "invalid CTP rate exchange scope summary")
    normalized = []
    for pair in value:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            _reject("invalid_rate_exchange_scope", "invalid CTP rate exchange scope pair")
        query_name, scope = pair
        if (
            type(query_name) is not str
            or query_name not in _REQUIRED_RATE_EXCHANGE_SCOPES
            or type(scope) is not str
            or scope not in _RATE_EXCHANGE_SCOPE_VALUES
        ):
            _reject("invalid_rate_exchange_scope", "invalid CTP rate exchange scope value")
        normalized.append((query_name, scope))
    if len(normalized) not in (0, len(_REQUIRED_RATE_EXCHANGE_SCOPES)):
        _reject("missing_rate_exchange_scope", "CTP rate exchange scope summary is incomplete")
    names = tuple(name for name, _scope in normalized)
    if len(set(names)) != len(names):
        _reject("duplicate_rate_exchange_scope", "CTP rate exchange scope summary has duplicates")
    if normalized and set(names) != set(_REQUIRED_RATE_EXCHANGE_SCOPES):
        _reject("missing_rate_exchange_scope", "CTP rate exchange scope summary is incomplete")
    return tuple(sorted(normalized))


def _canonical_snapshot_payload(
    identity: CtpReadOnlySessionIdentity,
    query_digests: Tuple[Tuple[str, str], ...],
    native_certificate_sha256: Optional[str] = None,
    rate_exchange_scopes: Tuple[Tuple[str, str], ...] = (),
) -> bytes:
    payload = {
        "identity": identity.as_public_dict(),
        "query_digests": [[name, digest] for name, digest in query_digests],
    }
    if native_certificate_sha256 is not None:
        payload["native_certificate_sha256"] = native_certificate_sha256
    if rate_exchange_scopes:
        payload["rate_exchange_scopes"] = [list(pair) for pair in rate_exchange_scopes]
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class CtpReadOnlyQuerySnapshot:
    """Digest-only complete summary of the required read-only CTP queries."""

    identity: CtpReadOnlySessionIdentity
    query_digests: Tuple[Tuple[str, str], ...]
    snapshot_sha256: str
    native_certificate_sha256: Optional[str] = None
    rate_exchange_scopes: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        identity = _normalise_identity(self.identity, "query snapshot identity")
        query_digests = _normalise_query_digests(self.query_digests)
        snapshot_sha256 = _sha256(self.snapshot_sha256, "snapshot_sha256")
        native_certificate_sha256 = (
            None
            if self.native_certificate_sha256 is None
            else _sha256(self.native_certificate_sha256, "native_certificate_sha256")
        )
        rate_exchange_scopes = _normalise_rate_exchange_scopes(self.rate_exchange_scopes)
        if native_certificate_sha256 is None and rate_exchange_scopes:
            _reject(
                "rate_exchange_scope_requires_certificate",
                "CTP rate exchange scopes require native certificate provenance",
            )
        if native_certificate_sha256 is not None and not rate_exchange_scopes:
            _reject(
                "missing_rate_exchange_scope",
                "native CTP certificate is missing rate exchange scope evidence",
            )
        expected_digest = hashlib.sha256(
            _canonical_snapshot_payload(
                identity, query_digests, native_certificate_sha256, rate_exchange_scopes
            )
        ).hexdigest()
        if not hmac.compare_digest(snapshot_sha256, expected_digest):
            _reject(
                "snapshot_digest_mismatch", "CTP query snapshot digest does not match its summary"
            )
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "query_digests", query_digests)
        object.__setattr__(self, "snapshot_sha256", snapshot_sha256)
        object.__setattr__(self, "native_certificate_sha256", native_certificate_sha256)
        object.__setattr__(self, "rate_exchange_scopes", rate_exchange_scopes)

    @classmethod
    def from_query_digests(
        cls,
        identity: CtpReadOnlySessionIdentity,
        query_digests: Sequence[Tuple[str, str]],
        *,
        native_certificate_sha256: Optional[str] = None,
        rate_exchange_scopes: Sequence[Tuple[str, str]] = (),
    ) -> "CtpReadOnlyQuerySnapshot":
        """Build a canonical snapshot after validating complete query coverage."""

        normalized_identity = _normalise_identity(identity, "query snapshot identity")
        normalized_digests = _normalise_query_digests(query_digests)
        normalized_certificate_sha256 = (
            None
            if native_certificate_sha256 is None
            else _sha256(native_certificate_sha256, "native_certificate_sha256")
        )
        normalized_rate_exchange_scopes = _normalise_rate_exchange_scopes(rate_exchange_scopes)
        if normalized_certificate_sha256 is None and normalized_rate_exchange_scopes:
            _reject(
                "rate_exchange_scope_requires_certificate",
                "CTP rate exchange scopes require native certificate provenance",
            )
        if normalized_certificate_sha256 is not None and not normalized_rate_exchange_scopes:
            _reject(
                "missing_rate_exchange_scope",
                "native CTP certificate is missing rate exchange scope evidence",
            )
        digest = hashlib.sha256(
            _canonical_snapshot_payload(
                normalized_identity,
                normalized_digests,
                normalized_certificate_sha256,
                normalized_rate_exchange_scopes,
            )
        ).hexdigest()
        return cls(
            identity=normalized_identity,
            query_digests=normalized_digests,
            snapshot_sha256=digest,
            native_certificate_sha256=normalized_certificate_sha256,
            rate_exchange_scopes=normalized_rate_exchange_scopes,
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return digest-only evidence; query payloads are deliberately absent."""

        result = {
            "identity": self.identity.as_public_dict(),
            "query_digests": self.query_digests,
            "snapshot_sha256": self.snapshot_sha256,
        }
        if self.native_certificate_sha256 is not None:
            result["native_certificate_sha256"] = self.native_certificate_sha256
        if self.rate_exchange_scopes:
            result["rate_exchange_scopes"] = self.rate_exchange_scopes
        return result


def _normalise_snapshot(value: Any) -> CtpReadOnlyQuerySnapshot:
    if type(value) is not CtpReadOnlyQuerySnapshot:
        _reject("invalid_query_snapshot", "invalid CTP query snapshot")
    return CtpReadOnlyQuerySnapshot(
        identity=value.identity,
        query_digests=value.query_digests,
        snapshot_sha256=value.snapshot_sha256,
        native_certificate_sha256=value.native_certificate_sha256,
        rate_exchange_scopes=value.rate_exchange_scopes,
    )


@dataclass(frozen=True)
class CtpReadOnlySessionRequest:
    """The minimal, non-secret request handed to an injected session factory."""

    provider: str
    environment: str
    account_fingerprint_sha256: str = field(repr=False)
    valid_until: float

    def __post_init__(self) -> None:
        if self.provider != CTP_PROVIDER:
            _reject("provider_not_ctp", "CTP read-only preflight requires provider ctp")
        object.__setattr__(
            self, "environment", _simnow_environment(self.environment, "environment")
        )
        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256"),
        )
        object.__setattr__(self, "valid_until", _timestamp(self.valid_until, "valid_until"))


class CtpReadOnlySession(Protocol):
    """The only session operations this contract can invoke.

    Implementations may use a provider-specific client internally, but this
    boundary has no method for execution, cancellation, settlement, or arming.
    """

    def read_identity(self) -> CtpReadOnlySessionIdentity:
        """Return the current, non-secret CTP session identity."""

    def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
        """Return one complete digest-only summary of required read-only queries."""

    def close_read_only(self) -> None:
        """Close the read-only session without performing a provider write."""


class CtpReadOnlySessionFactory(Protocol):
    """Injected factory; this module intentionally supplies no SDK-backed default."""

    def open_read_only(self, request: CtpReadOnlySessionRequest) -> CtpReadOnlySession:
        """Create one read-only session for an already validated request."""


@dataclass(frozen=True)
class CtpReadOnlyPreflightResult:
    """Stable read-only evidence with explicit non-execution authority fields."""

    receipt_id: str
    test_profile_id: str
    test_profile_sha256: str
    test_profile_valid_until: float
    provider: str
    environment: str
    account_fingerprint_sha256: str = field(repr=False)
    trading_day: str
    connection_generation: int
    query_snapshot: CtpReadOnlyQuerySnapshot
    provider_preflight_started: bool = True
    session_connected: bool = True
    execution_authorized: bool = False
    external_writes_authorized: bool = False
    order_submission_authorized: bool = False
    cancellation_authorized: bool = False
    settlement_authorized: bool = False
    arming_authorized: bool = False

    def __post_init__(self) -> None:
        if type(self.receipt_id) is not str or not self.receipt_id:
            _reject("invalid_receipt", "invalid preflight receipt identity")
        if type(self.test_profile_id) is not str or not self.test_profile_id:
            _reject("invalid_test_profile", "invalid test execution profile identity")
        object.__setattr__(
            self,
            "test_profile_sha256",
            _sha256(self.test_profile_sha256, "test_profile_sha256"),
        )
        object.__setattr__(
            self,
            "test_profile_valid_until",
            _timestamp(self.test_profile_valid_until, "test_profile_valid_until"),
        )
        if self.provider != CTP_PROVIDER:
            _reject("provider_not_ctp", "CTP read-only preflight requires provider ctp")
        environment = _simnow_environment(self.environment, "environment")
        account_fingerprint = _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256")
        trading_day = _trading_day(self.trading_day)
        generation = _connection_generation(self.connection_generation)
        snapshot = _normalise_snapshot(self.query_snapshot)
        expected_identity = CtpReadOnlySessionIdentity(
            provider=self.provider,
            environment=environment,
            account_fingerprint_sha256=account_fingerprint,
            trading_day=trading_day,
            connection_generation=generation,
        )
        if snapshot.identity != expected_identity:
            _reject(
                "snapshot_identity_mismatch", "CTP query snapshot identity does not match session"
            )
        if (
            self.provider_preflight_started is not True
            or self.session_connected is not True
            or self.execution_authorized is not False
            or self.external_writes_authorized is not False
            or self.order_submission_authorized is not False
            or self.cancellation_authorized is not False
            or self.settlement_authorized is not False
            or self.arming_authorized is not False
        ):
            raise ValueError("CTP read-only preflight cannot grant execution or write authority")
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "account_fingerprint_sha256", account_fingerprint)
        object.__setattr__(self, "trading_day", trading_day)
        object.__setattr__(self, "connection_generation", generation)
        object.__setattr__(self, "query_snapshot", snapshot)

    def __bool__(self) -> bool:
        raise TypeError(
            "CtpReadOnlyPreflightResult is read-only evidence, not an execution authorization; "
            "do not use it as a boolean"
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return digest-only evidence with explicit false execution/write fields."""

        return {
            "account_scope": "redacted",
            "arming_authorized": self.arming_authorized,
            "cancellation_authorized": self.cancellation_authorized,
            "connection_generation": self.connection_generation,
            "environment": self.environment,
            "execution_authorized": self.execution_authorized,
            "external_writes_authorized": self.external_writes_authorized,
            "order_submission_authorized": self.order_submission_authorized,
            "provider": self.provider,
            "provider_preflight_started": self.provider_preflight_started,
            "query_snapshot": self.query_snapshot.as_public_dict(),
            "receipt_id": self.receipt_id,
            "session_connected": self.session_connected,
            "settlement_authorized": self.settlement_authorized,
            "test_profile_id": self.test_profile_id,
            "test_profile_sha256": self.test_profile_sha256,
            "test_profile_valid_until": self.test_profile_valid_until,
            "trading_day": self.trading_day,
        }


def _binding_request(binding: Any) -> CtpReadOnlySessionRequest:
    """Validate a potentially tampered frozen binding before constructing a session."""

    if type(binding) is not ProviderSessionPreflightBinding:
        _reject("binding_required", "a ProviderSessionPreflightBinding is required")
    validation = binding.receipt_validation
    if type(validation) is not ProviderDeploymentReceiptValidation:
        _reject("binding_invalid", "provider preflight binding receipt validation is invalid")
    if (
        binding.preflight_binding_valid is not True
        or binding.provider_preflight_started is not False
        or binding.secrets_resolved is not False
        or binding.session_connected is not False
        or binding.execution_authorized is not False
        or binding.external_writes_authorized is not False
        or validation.receipt_binding_valid is not True
        or validation.deployment_authorized is not False
        or validation.execution_authorized is not False
        or validation.secrets_resolved is not False
        or validation.provider_preflight_started is not False
    ):
        _reject("binding_invalid", "provider preflight binding cannot grant session authority")
    if (
        binding.mode != "simulation"
        or binding.preset != "sandbox"
        or binding.account_access != "sandbox_direct_provider"
    ):
        _reject(
            "binding_not_simnow_sandbox", "binding is not the reviewed CTP SimNow sandbox route"
        )
    if validation.provider != CTP_PROVIDER:
        _reject("provider_not_ctp", "provider receipt does not describe CTP")

    valid_until = _timestamp(validation.valid_until, "binding valid_until")
    checked_at = _timestamp(time.time(), "now")
    if valid_until <= checked_at:
        _reject("binding_expired", "provider preflight binding has expired")
    return CtpReadOnlySessionRequest(
        provider=validation.provider,
        environment=validation.environment,
        account_fingerprint_sha256=validation.account_fingerprint_sha256,
        valid_until=valid_until,
    )


def _matching_identity(
    expected: CtpReadOnlySessionRequest, identity: CtpReadOnlySessionIdentity
) -> bool:
    return (
        identity.provider == expected.provider
        and identity.environment == expected.environment
        and hmac.compare_digest(
            identity.account_fingerprint_sha256, expected.account_fingerprint_sha256
        )
    )


def _normalise_test_profile_context(
    value: Any,
    binding: ProviderSessionPreflightBinding,
    registration: ProviderSessionPreflightRegistration,
) -> TestExecutionPreflightContext:
    """Bind a zero-write profile context to the sealed deployment facts.

    The test-profile verifier validates the raw profile against this context.
    Reconstructing the frozen context also detects unsafe ``object.__setattr__``
    mutation before any factory receives a request.
    """

    if type(value) is not TestExecutionPreflightContext:
        _reject("test_profile_context_required", "a test execution profile context is required")
    try:
        context = TestExecutionPreflightContext(
            provider=value.provider,
            environment=value.environment,
            account_fingerprint_sha256=value.account_fingerprint_sha256,
            approval_receipt_digest=value.approval_receipt_digest,
            effective_config_digest=value.effective_config_digest,
            artifact_sha256=value.artifact_sha256,
            capability_receipt_digest=value.capability_receipt_digest,
            instrument=value.instrument,
            quantity=value.quantity,
            requested_external_writes=value.requested_external_writes,
            cleanup_ready=value.cleanup_ready,
            reconciliation_ready=value.reconciliation_ready,
        )
    except Exception:
        _reject("test_profile_context_invalid", "test execution profile context is invalid")

    deployment = registration.deployment
    validation = binding.receipt_validation
    if context.provider != CTP_PROVIDER:
        _reject(
            "test_profile_provider_mismatch", "test execution profile context provider is not CTP"
        )
    if context.environment != "simnow":
        _reject(
            "test_profile_environment_mismatch",
            "test execution profile context is not in the SimNow environment class",
        )
    if context.requested_external_writes != 0:
        _reject(
            "test_profile_writes_not_zero",
            "CTP read-only preflight requires zero requested external writes",
        )

    expected_digests = (
        (
            context.approval_receipt_digest,
            deployment.approval_receipt_digest,
            validation.approval_receipt_digest,
        ),
        (
            context.account_fingerprint_sha256,
            deployment.account_fingerprint_sha256,
            validation.account_fingerprint_sha256,
        ),
        (
            context.effective_config_digest,
            deployment.effective_config_digest,
            validation.effective_config_digest,
        ),
        (context.artifact_sha256, deployment.artifact_sha256, validation.artifact_sha256),
        (
            context.capability_receipt_digest,
            deployment.capability_receipt_digest,
            validation.capability_receipt_digest,
        ),
    )
    if any(
        not hmac.compare_digest(actual, deployment_value)
        or not hmac.compare_digest(actual, receipt_value)
        for actual, deployment_value, receipt_value in expected_digests
    ):
        _reject(
            "test_profile_context_binding_mismatch",
            "test execution profile context does not match sealed provider binding",
        )
    return context


def _normalise_test_profile_observation(
    value: Any,
    request: CtpReadOnlySessionRequest,
    expected_approval_receipt_digest: str,
) -> TestExecutionProfileObservation:
    """Require an independently verified, zero-write SimNow profile observation.

    ``TestExecutionProfileObservation`` deliberately redacts the account
    fingerprint, so the exact fingerprint continues to be bound by the
    deployment receipt/session identity.  The profile supplies a separate,
    verified sandbox and zero-write constraint; its canonical environment is
    ``simnow`` while the deployment route may name a reviewed SimNow front set
    such as ``simnow_set2``.
    """

    if type(value) is not TestExecutionProfileObservation:
        _reject(
            "test_profile_required",
            "a verified TestExecutionProfileObservation is required",
        )
    try:
        observation = TestExecutionProfileObservation(
            profile_id=value.profile_id,
            profile_sha256=value.profile_sha256,
            provider=value.provider,
            environment=value.environment,
            approval_receipt_digest=value.approval_receipt_digest,
            instrument=value.instrument,
            quantity=value.quantity,
            requested_external_writes=value.requested_external_writes,
            checked_at=value.checked_at,
            valid_until=value.valid_until,
            status=value.status,
            profile_binding_valid=value.profile_binding_valid,
            profile_verifier_accepted=value.profile_verifier_accepted,
            preflight_authorized=value.preflight_authorized,
            execution_authorized=value.execution_authorized,
            provider_preflight_started=value.provider_preflight_started,
            provider_connected=value.provider_connected,
            external_writes_started=value.external_writes_started,
        )
    except Exception:
        _reject("test_profile_invalid", "test execution profile observation is invalid")

    if (
        observation.status != TEST_EXECUTION_PROFILE_PRECHECKED
        or observation.profile_binding_valid is not True
        or observation.profile_verifier_accepted is not True
        or observation.preflight_authorized is not False
        or observation.execution_authorized is not False
        or observation.provider_preflight_started is not False
        or observation.provider_connected is not False
        or observation.external_writes_started is not False
    ):
        _reject("test_profile_invalid", "test execution profile cannot grant provider authority")
    if observation.provider != request.provider:
        _reject(
            "test_profile_provider_mismatch", "test execution profile provider does not match CTP"
        )
    if not hmac.compare_digest(
        observation.approval_receipt_digest, expected_approval_receipt_digest
    ):
        _reject(
            "test_profile_approval_mismatch",
            "test execution profile approval does not match provider receipt",
        )
    if observation.environment != "simnow":
        _reject(
            "test_profile_environment_mismatch",
            "test execution profile environment is not the SimNow class",
        )
    if observation.requested_external_writes != 0:
        _reject(
            "test_profile_writes_not_zero",
            "CTP read-only preflight requires a zero-write test execution profile",
        )
    checked_at = _timestamp(time.time(), "now")
    if observation.valid_until <= checked_at:
        _reject("test_profile_expired", "test execution profile observation has expired")
    return observation


def _monotonic_session_deadline(valid_until: float) -> float:
    """Pin the verified wall-clock remainder to a monotonic clock as well."""

    remaining = valid_until - _timestamp(time.time(), "now")
    if remaining <= 0:
        _reject("session_deadline_expired", "CTP read-only preflight deadline has expired")
    return _timestamp(time.monotonic(), "monotonic_now") + remaining


def _require_session_deadline(valid_until: float, monotonic_deadline: float) -> None:
    """Recheck both clocks after every blocking session step."""

    if (
        _timestamp(time.time(), "now") >= valid_until
        or _timestamp(time.monotonic(), "monotonic_now") >= monotonic_deadline
    ):
        _reject("session_deadline_expired", "CTP read-only preflight deadline has expired")


def _run_ctp_simnow_readonly_preflight_from_verified(
    binding: ProviderSessionPreflightBinding,
    test_profile: TestExecutionProfileObservation,
    session_factory: Optional[CtpReadOnlySessionFactory] = None,
) -> CtpReadOnlyPreflightResult:
    """Run the session half after public inputs have been independently validated.

    Both non-authoritative offline observations are completely checked before
    the factory is touched.  The factory, session identity and query summary
    are each checked again at this boundary.  Any malformed, duplicate,
    incomplete, changing, or exceptional observation rejects the entire
    preflight and never produces an authority result.
    """

    request = _binding_request(binding)
    profile_observation = _normalise_test_profile_observation(
        test_profile, request, binding.receipt_validation.approval_receipt_digest
    )
    request = CtpReadOnlySessionRequest(
        provider=request.provider,
        environment=request.environment,
        account_fingerprint_sha256=request.account_fingerprint_sha256,
        valid_until=min(request.valid_until, profile_observation.valid_until),
    )
    monotonic_deadline = _monotonic_session_deadline(request.valid_until)
    _require_session_deadline(request.valid_until, monotonic_deadline)
    if session_factory is None:
        _reject(
            "session_factory_required",
            "CTP read-only preflight requires an injected session factory",
        )
    try:
        open_read_only = getattr(session_factory, "open_read_only", None)
    except Exception:
        _reject("invalid_session_factory", "invalid CTP read-only session factory")
    if not callable(open_read_only):
        _reject("invalid_session_factory", "invalid CTP read-only session factory")

    try:
        session = open_read_only(request)
    except CtpReadOnlyPreflightError:
        raise
    except Exception:
        _reject("session_factory_failed", "unable to open CTP read-only session")
    if session is None:
        _reject("invalid_session", "CTP read-only session factory returned no session")

    result: Optional[CtpReadOnlyPreflightResult] = None
    error: Optional[CtpReadOnlyPreflightError] = None
    close_read_only = None
    try:
        try:
            # Capture the close operation first. A broken read method attribute
            # may raise before any query starts, but a captured close still runs.
            close_read_only = getattr(session, "close_read_only", None)
            if not callable(close_read_only):
                _reject("invalid_session", "CTP read-only session has no close operation")
            _require_session_deadline(request.valid_until, monotonic_deadline)
            read_identity = getattr(session, "read_identity", None)
            read_snapshot = getattr(session, "read_query_snapshot", None)
            if not callable(read_identity) or not callable(read_snapshot):
                _reject("invalid_session", "CTP read-only session has an invalid protocol")

            first_identity = _normalise_identity(read_identity(), "session identity")
            _require_session_deadline(request.valid_until, monotonic_deadline)
            if not _matching_identity(request, first_identity):
                _reject(
                    "session_identity_mismatch",
                    "CTP session identity does not match receipt binding",
                )

            snapshot = _normalise_snapshot(read_snapshot())
            _require_session_deadline(request.valid_until, monotonic_deadline)
            if snapshot.identity != first_identity:
                _reject(
                    "snapshot_identity_mismatch",
                    "CTP query snapshot identity does not match session",
                )

            final_identity = _normalise_identity(read_identity(), "final session identity")
            _require_session_deadline(request.valid_until, monotonic_deadline)
            if final_identity != first_identity:
                _reject("session_identity_changed", "CTP session identity changed during preflight")

            result = CtpReadOnlyPreflightResult(
                receipt_id=validation_receipt_id(binding),
                test_profile_id=profile_observation.profile_id,
                test_profile_sha256=profile_observation.profile_sha256,
                test_profile_valid_until=profile_observation.valid_until,
                provider=first_identity.provider,
                environment=first_identity.environment,
                account_fingerprint_sha256=first_identity.account_fingerprint_sha256,
                trading_day=first_identity.trading_day,
                connection_generation=first_identity.connection_generation,
                query_snapshot=snapshot,
            )
        except CtpReadOnlyPreflightError as caught:
            error = caught
        except Exception:
            error = CtpReadOnlyPreflightError(
                "read_only_session_failed", "CTP read-only session preflight failed"
            )
    finally:
        if callable(close_read_only):
            try:
                close_read_only()
            except Exception:
                if error is None:
                    error = CtpReadOnlyPreflightError(
                        "session_close_failed", "unable to close CTP read-only session"
                    )
    if error is None:
        try:
            _require_session_deadline(request.valid_until, monotonic_deadline)
        except CtpReadOnlyPreflightError as caught:
            error = caught
    if error is not None:
        raise error
    if result is None:
        _reject("read_only_session_failed", "CTP read-only session preflight failed")
    return result


def run_ctp_simnow_readonly_preflight(
    *,
    effective: EffectiveRuntimeConfig,
    registry: RuntimeRegistry,
    provider_registration: ProviderSessionPreflightRegistration,
    provider_receipt: Any,
    provider_receipt_verifier: Optional[ProviderDeploymentReceiptVerifier] = None,
    test_profile: Any,
    test_profile_context: TestExecutionPreflightContext,
    test_profile_verifier: Optional[TestExecutionProfileVerifier] = None,
    session_factory: Optional[CtpReadOnlySessionFactory] = None,
) -> CtpReadOnlyPreflightResult:
    """Validate sealed inputs, then run one injected CTP SimNow read-only session.

    This is the only public route.  It accepts raw receipt/profile wires and
    their offline verifiers, derives both non-authoritative observations at
    this boundary, and performs every seal/profile check before constructing a
    session.  Passing a hand-built observation is deliberately not supported.
    """

    try:
        binding = validate_provider_session_preflight_binding(
            effective,
            registry,
            provider_registration,
            provider_receipt,
            verifier=provider_receipt_verifier,
        )
    except Exception:
        _reject(
            "provider_binding_validation_failed",
            "sealed provider receipt binding validation failed",
        )
    context = _normalise_test_profile_context(
        test_profile_context,
        binding,
        provider_registration,
    )
    try:
        profile_observation = validate_test_execution_profile(
            test_profile,
            context=context,
            verifier=test_profile_verifier,
        )
    except Exception:
        _reject(
            "test_profile_validation_failed",
            "sealed test execution profile validation failed",
        )
    return _run_ctp_simnow_readonly_preflight_from_verified(
        binding,
        profile_observation,
        session_factory=session_factory,
    )


def validation_receipt_id(binding: ProviderSessionPreflightBinding) -> str:
    """Read the already validated receipt identifier without using binding truthiness."""

    receipt_id = binding.receipt_validation.receipt_id
    if type(receipt_id) is not str or not receipt_id:
        _reject("invalid_receipt", "invalid preflight receipt identity")
    return receipt_id


__all__ = [
    "CTP_PROVIDER",
    "CTP_SIMNOW_ENVIRONMENT_PATTERN",
    "REQUIRED_CTP_READ_ONLY_QUERIES",
    "CtpReadOnlyPreflightError",
    "CtpReadOnlyPreflightResult",
    "CtpReadOnlyQuerySnapshot",
    "CtpReadOnlySession",
    "CtpReadOnlySessionFactory",
    "CtpReadOnlySessionIdentity",
    "CtpReadOnlySessionRequest",
    "run_ctp_simnow_readonly_preflight",
]
