"""Offline, fail-closed contracts for a future sandbox test-execution profile.

This module is intentionally narrower than a provider adapter.  It validates a
bounded, short-lived profile and an in-memory preflight context without reading
credentials, importing a provider SDK, connecting a session, or dispatching an
order.  Even when an injected offline verifier accepts the canonical profile,
the returned observation is explicitly non-authoritative.

The contract is useful for building and testing a managed sandbox admission
path.  It is not a default runtime route and it must not be interpreted as a
simulation-account, deployment, or execution authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol, Sequence, Tuple, Union


TEST_EXECUTION_PROFILE_SCHEMA_VERSION = "bt-test-execution-profile/v2"
TEST_EXECUTION_PROFILE_PRECHECKED = "TEST_EXECUTION_PROFILE_PRECHECKED"
MAX_TEST_EXECUTION_PROFILE_BYTES = 64 * 1024
MAX_TEST_EXECUTION_PROFILE_INSTRUMENTS = 64
MAX_TEST_EXECUTION_PROFILE_INSTRUMENT_LENGTH = 128
MAX_TEST_EXECUTION_PROFILE_EXTERNAL_WRITES = 1_000
MAX_TEST_EXECUTION_PROFILE_LIFETIME_SECONDS = 24 * 60 * 60

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_SANDBOX_ENVIRONMENTS = frozenset(("demo", "sandbox", "simnow", "testnet"))
_PROFILE_FIELDS = frozenset(
    (
        "account_fingerprint_sha256",
        "allowed_instruments",
        "approval_receipt_digest",
        "artifact_sha256",
        "capability_receipt_digest",
        "cleanup_required",
        "created_at",
        "effective_config_digest",
        "environment",
        "expires_at",
        "max_external_writes",
        "max_quantity",
        "profile_id",
        "provider",
        "reconciliation_required",
        "schema_version",
        "valid_from",
    )
)


SerializedTestExecutionProfile = Union[str, bytes, bytearray]


class TestExecutionProfileError(ValueError):
    """A redacted, deterministic rejection of an offline profile check."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise TestExecutionProfileError(reason, message)


def _identifier(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) > 128
        or value != value.strip()
        or not _IDENTIFIER_RE.fullmatch(value)
    ):
        _reject("invalid_identifier", "invalid {0}".format(field_name))
    return value


def _provider(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) > 64
        or value != value.strip()
        or not _PROVIDER_RE.fullmatch(value)
    ):
        _reject("invalid_provider", "invalid {0}".format(field_name))
    return value


def _sandbox_environment(value: Any, field_name: str) -> str:
    environment = _provider(value, field_name)
    if environment == "production":
        _reject(
            "production_environment_forbidden",
            "test execution profiles must never target production",
        )
    if environment not in _SANDBOX_ENVIRONMENTS:
        _reject(
            "environment_not_sandbox",
            "test execution profile environment is not a reviewed sandbox environment",
        )
    return environment


def _sha256(value: Any, field_name: str) -> str:
    if type(value) is not str or len(value) != 64 or not _SHA256_RE.fullmatch(value):
        _reject("invalid_digest", "invalid {0}".format(field_name))
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


def _quantity(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) > 64
        or value != value.strip()
        or not _DECIMAL_RE.fullmatch(value)
    ):
        _reject("invalid_quantity", "invalid {0}".format(field_name))
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        _reject("invalid_quantity", "invalid {0}".format(field_name))
    if not parsed.is_finite() or parsed <= Decimal("0"):
        _reject("invalid_quantity", "invalid {0}".format(field_name))
    rendered = format(parsed.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _max_external_writes(value: Any, field_name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        _reject("invalid_external_write_count", "invalid {0}".format(field_name))
    if value < 0 or value > MAX_TEST_EXECUTION_PROFILE_EXTERNAL_WRITES:
        _reject("invalid_external_write_count", "invalid {0}".format(field_name))
    return value


def _instruments(value: Any, field_name: str) -> Tuple[str, ...]:
    if type(value) not in (list, tuple) or not value:
        _reject("invalid_instruments", "invalid {0}".format(field_name))
    if len(value) > MAX_TEST_EXECUTION_PROFILE_INSTRUMENTS:
        _reject("profile_too_large", "profile contains too many allowed instruments")
    instruments = tuple(value)
    if any(
        type(instrument) is not str
        or len(instrument) > MAX_TEST_EXECUTION_PROFILE_INSTRUMENT_LENGTH
        or instrument != instrument.strip()
        or not _INSTRUMENT_RE.fullmatch(instrument)
        for instrument in instruments
    ):
        if any(
            type(instrument) is str
            and len(instrument) > MAX_TEST_EXECUTION_PROFILE_INSTRUMENT_LENGTH
            for instrument in instruments
        ):
            _reject("profile_too_large", "allowed instrument name is too large")
        _reject("invalid_instruments", "invalid allowed instrument")
    if len(set(instruments)) != len(instruments):
        _reject("invalid_instruments", "duplicate allowed instrument")
    return tuple(sorted(instruments))


def _required_true(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        _reject("invalid_boolean", "invalid {0}".format(field_name))
    if value is not True:
        _reject("required_safety_control_missing", "{0} must be true".format(field_name))
    return True


def _boolean(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        _reject("invalid_boolean", "invalid {0}".format(field_name))
    return value


@dataclass(frozen=True)
class TestExecutionProfile:
    """A parsed, still-untrusted bounded sandbox test profile.

    This class contains neither credentials nor a secret reference.  Account
    identity is represented only by a SHA-256 fingerprint and remains redacted
    from the public diagnostic projection.
    """

    profile_id: str
    provider: str
    environment: str
    account_fingerprint_sha256: str = field(repr=False)
    approval_receipt_digest: str
    effective_config_digest: str
    artifact_sha256: str
    capability_receipt_digest: str
    allowed_instruments: Tuple[str, ...]
    max_quantity: str
    max_external_writes: int
    cleanup_required: bool
    reconciliation_required: bool
    created_at: float
    valid_from: float
    expires_at: float
    schema_version: str = TEST_EXECUTION_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _identifier(self.profile_id, "profile_id"))
        object.__setattr__(self, "provider", _provider(self.provider, "provider"))
        object.__setattr__(
            self, "environment", _sandbox_environment(self.environment, "environment")
        )
        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256"),
        )
        object.__setattr__(
            self,
            "approval_receipt_digest",
            _sha256(self.approval_receipt_digest, "approval_receipt_digest"),
        )
        object.__setattr__(
            self,
            "effective_config_digest",
            _sha256(self.effective_config_digest, "effective_config_digest"),
        )
        object.__setattr__(
            self, "artifact_sha256", _sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self,
            "capability_receipt_digest",
            _sha256(self.capability_receipt_digest, "capability_receipt_digest"),
        )
        object.__setattr__(
            self,
            "allowed_instruments",
            _instruments(self.allowed_instruments, "allowed_instruments"),
        )
        object.__setattr__(self, "max_quantity", _quantity(self.max_quantity, "max_quantity"))
        object.__setattr__(
            self,
            "max_external_writes",
            _max_external_writes(self.max_external_writes, "max_external_writes"),
        )
        object.__setattr__(
            self, "cleanup_required", _required_true(self.cleanup_required, "cleanup_required")
        )
        object.__setattr__(
            self,
            "reconciliation_required",
            _required_true(self.reconciliation_required, "reconciliation_required"),
        )
        created_at = _timestamp(self.created_at, "created_at")
        valid_from = _timestamp(self.valid_from, "valid_from")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if valid_from < created_at:
            _reject("invalid_timestamp", "profile validity cannot precede creation")
        if expires_at <= valid_from:
            _reject("invalid_timestamp", "profile expiry must follow its validity start")
        if expires_at - valid_from > MAX_TEST_EXECUTION_PROFILE_LIFETIME_SECONDS:
            _reject("profile_lifetime_too_long", "test execution profile lifetime is too long")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "expires_at", expires_at)
        if (
            type(self.schema_version) is not str
            or self.schema_version != TEST_EXECUTION_PROFILE_SCHEMA_VERSION
        ):
            _reject("unsupported_schema", "test execution profile schema is not supported")

    def as_wire(self) -> dict[str, Any]:
        """Return the exact canonical field set for the offline verifier."""

        return {
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "allowed_instruments": list(self.allowed_instruments),
            "approval_receipt_digest": self.approval_receipt_digest,
            "artifact_sha256": self.artifact_sha256,
            "capability_receipt_digest": self.capability_receipt_digest,
            "cleanup_required": self.cleanup_required,
            "created_at": self.created_at,
            "effective_config_digest": self.effective_config_digest,
            "environment": self.environment,
            "expires_at": self.expires_at,
            "max_external_writes": self.max_external_writes,
            "max_quantity": self.max_quantity,
            "profile_id": self.profile_id,
            "provider": self.provider,
            "reconciliation_required": self.reconciliation_required,
            "schema_version": self.schema_version,
            "valid_from": self.valid_from,
        }

    def as_public_dict(self) -> dict[str, Any]:
        """Return a diagnostic projection that does not expose account identity."""

        return {
            "account_fingerprint_bound": True,
            "allowed_instruments": self.allowed_instruments,
            "approval_receipt_digest": self.approval_receipt_digest,
            "artifact_sha256": self.artifact_sha256,
            "capability_receipt_digest": self.capability_receipt_digest,
            "cleanup_required": self.cleanup_required,
            "effective_config_digest": self.effective_config_digest,
            "environment": self.environment,
            "expires_at": self.expires_at,
            "max_external_writes": self.max_external_writes,
            "max_quantity": self.max_quantity,
            "profile_id": self.profile_id,
            "provider": self.provider,
            "reconciliation_required": self.reconciliation_required,
            "valid_from": self.valid_from,
        }


@dataclass(frozen=True)
class TestExecutionPreflightContext:
    """Pure in-memory facts that a future provider preflight must bind exactly.

    ``cleanup_ready`` and ``reconciliation_ready`` only describe that a future
    caller supplied a plan/evidence handle.  They do not run cleanup, reconcile
    an account, or establish a provider session.
    """

    provider: str
    environment: str
    account_fingerprint_sha256: str = field(repr=False)
    approval_receipt_digest: str
    effective_config_digest: str
    artifact_sha256: str
    capability_receipt_digest: str
    instrument: str
    quantity: str
    requested_external_writes: int
    cleanup_ready: bool
    reconciliation_ready: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _provider(self.provider, "provider"))
        object.__setattr__(
            self, "environment", _sandbox_environment(self.environment, "environment")
        )
        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _sha256(self.account_fingerprint_sha256, "account_fingerprint_sha256"),
        )
        object.__setattr__(
            self,
            "approval_receipt_digest",
            _sha256(self.approval_receipt_digest, "approval_receipt_digest"),
        )
        object.__setattr__(
            self,
            "effective_config_digest",
            _sha256(self.effective_config_digest, "effective_config_digest"),
        )
        object.__setattr__(
            self, "artifact_sha256", _sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self,
            "capability_receipt_digest",
            _sha256(self.capability_receipt_digest, "capability_receipt_digest"),
        )
        instrument = _instruments((self.instrument,), "instrument")
        object.__setattr__(self, "instrument", instrument[0])
        object.__setattr__(self, "quantity", _quantity(self.quantity, "quantity"))
        object.__setattr__(
            self,
            "requested_external_writes",
            _max_external_writes(self.requested_external_writes, "requested_external_writes"),
        )
        object.__setattr__(self, "cleanup_ready", _boolean(self.cleanup_ready, "cleanup_ready"))
        object.__setattr__(
            self,
            "reconciliation_ready",
            _boolean(self.reconciliation_ready, "reconciliation_ready"),
        )


class TestExecutionProfileVerifier(Protocol):
    """A deployment-owner supplied, offline verifier for an exact profile.

    Implementations may inspect preloaded trust material only.  They must not
    resolve credentials, import provider SDKs, start a provider preflight, or
    turn a profile into execution authority.
    """

    def verify(self, profile: TestExecutionProfile, canonical_payload: bytes) -> bool:
        """Return whether the exact profile has offline trust binding."""


class RejectingTestExecutionProfileVerifier:
    """Default verifier: reject every profile until a deployment owner supplies trust."""

    def verify(self, profile: TestExecutionProfile, canonical_payload: bytes) -> bool:
        del profile, canonical_payload
        return False


@dataclass(frozen=True)
class TestExecutionProfileObservation:
    """A verified offline observation that cannot grant any execution authority."""

    profile_id: str
    profile_sha256: str
    provider: str
    environment: str
    approval_receipt_digest: str
    instrument: str
    quantity: str
    requested_external_writes: int
    checked_at: float
    valid_until: float
    status: str = TEST_EXECUTION_PROFILE_PRECHECKED
    profile_binding_valid: bool = True
    profile_verifier_accepted: bool = True
    preflight_authorized: bool = False
    execution_authorized: bool = False
    provider_preflight_started: bool = False
    provider_connected: bool = False
    external_writes_started: bool = False

    def __post_init__(self) -> None:
        if (
            self.status != TEST_EXECUTION_PROFILE_PRECHECKED
            or self.profile_binding_valid is not True
            or self.profile_verifier_accepted is not True
            or self.preflight_authorized is not False
            or self.execution_authorized is not False
            or self.provider_preflight_started is not False
            or self.provider_connected is not False
            or self.external_writes_started is not False
        ):
            raise ValueError("test execution profile observation cannot grant authority")
        checked_at = _timestamp(self.checked_at, "checked_at")
        valid_until = _timestamp(self.valid_until, "valid_until")
        if valid_until <= checked_at:
            raise ValueError("test execution profile observation must retain a future deadline")
        object.__setattr__(self, "profile_id", _identifier(self.profile_id, "profile_id"))
        object.__setattr__(self, "profile_sha256", _sha256(self.profile_sha256, "profile_sha256"))
        object.__setattr__(self, "provider", _provider(self.provider, "provider"))
        object.__setattr__(
            self,
            "approval_receipt_digest",
            _sha256(self.approval_receipt_digest, "approval_receipt_digest"),
        )
        object.__setattr__(
            self, "environment", _sandbox_environment(self.environment, "environment")
        )
        instrument = _instruments((self.instrument,), "instrument")
        object.__setattr__(self, "instrument", instrument[0])
        object.__setattr__(self, "quantity", _quantity(self.quantity, "quantity"))
        object.__setattr__(
            self,
            "requested_external_writes",
            _max_external_writes(self.requested_external_writes, "requested_external_writes"),
        )
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "valid_until", valid_until)

    def __bool__(self) -> bool:
        """Prevent a successful offline check from being used as a permission token."""

        raise TypeError(
            "TestExecutionProfileObservation is not an admission decision; do not use it as a boolean"
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return a safe, explicit non-authoritative diagnostic projection."""

        return {
            "checked_at": self.checked_at,
            "environment": self.environment,
            "execution_authorized": self.execution_authorized,
            "external_writes_started": self.external_writes_started,
            "instrument": self.instrument,
            "preflight_authorized": self.preflight_authorized,
            "profile_binding_valid": self.profile_binding_valid,
            "profile_id": self.profile_id,
            "profile_sha256": self.profile_sha256,
            "profile_verifier_accepted": self.profile_verifier_accepted,
            "provider": self.provider,
            "approval_receipt_digest": self.approval_receipt_digest,
            "provider_connected": self.provider_connected,
            "provider_preflight_started": self.provider_preflight_started,
            "quantity": self.quantity,
            "requested_external_writes": self.requested_external_writes,
            "status": self.status,
            "valid_until": self.valid_until,
        }


def _reject_json_constant(_: str) -> None:
    _reject("invalid_json", "profile contains a non-finite JSON value")


def _reject_duplicate_fields(pairs: Sequence[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("invalid_json", "profile JSON contains duplicate object keys")
        result[key] = value
    return result


def _coerce_profile_wire(
    value: Union[Mapping[str, Any], SerializedTestExecutionProfile]
) -> Mapping[str, Any]:
    if type(value) is bytearray:
        if len(value) > MAX_TEST_EXECUTION_PROFILE_BYTES:
            _reject("profile_too_large", "profile exceeds the maximum supported size")
        value = bytes(value)
    if type(value) is bytes:
        if len(value) > MAX_TEST_EXECUTION_PROFILE_BYTES:
            _reject("profile_too_large", "profile exceeds the maximum supported size")
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            _reject("invalid_json", "profile must be UTF-8 JSON")
    if type(value) is str:
        if len(value) > MAX_TEST_EXECUTION_PROFILE_BYTES:
            _reject("profile_too_large", "profile exceeds the maximum supported size")
        try:
            encoded_length = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            _reject("invalid_json", "profile must be UTF-8 JSON")
        if encoded_length > MAX_TEST_EXECUTION_PROFILE_BYTES:
            _reject("profile_too_large", "profile exceeds the maximum supported size")
        try:
            parsed = json.loads(
                value,
                object_pairs_hook=_reject_duplicate_fields,
                parse_constant=_reject_json_constant,
            )
        except TestExecutionProfileError:
            raise
        except (json.JSONDecodeError, RecursionError, ValueError):
            _reject("invalid_json", "profile is not valid JSON")
        # JSON decoders can accept different nesting depths when pytest
        # plugins or applications change the process recursion limit.  This
        # wire is shallow by contract, so reject deep containers explicitly
        # before classifying a successfully decoded non-object value.
        pending = [(parsed, 0)]
        while pending:
            node, depth = pending.pop()
            if depth > 64:
                _reject("invalid_json", "profile JSON nesting exceeds the supported limit")
            if type(node) is dict:
                pending.extend((child, depth + 1) for child in node.values())
            elif type(node) is list:
                pending.extend((child, depth + 1) for child in node)
        if type(parsed) is not dict:
            _reject("invalid_wire", "profile wire must be an object")
        return parsed
    if type(value) is not dict:
        _reject("invalid_wire", "profile wire must be a plain JSON object")
    return dict(value)


def parse_test_execution_profile(
    value: Union[Mapping[str, Any], SerializedTestExecutionProfile]
) -> TestExecutionProfile:
    """Strictly parse a profile without consulting a trust store or provider."""

    wire = _coerce_profile_wire(value)
    keys = tuple(wire)
    if any(type(key) is not str for key in keys) or set(keys) != _PROFILE_FIELDS:
        _reject("invalid_wire", "profile wire fields do not match the test execution contract")
    profile = TestExecutionProfile(
        profile_id=wire["profile_id"],
        provider=wire["provider"],
        environment=wire["environment"],
        account_fingerprint_sha256=wire["account_fingerprint_sha256"],
        approval_receipt_digest=wire["approval_receipt_digest"],
        effective_config_digest=wire["effective_config_digest"],
        artifact_sha256=wire["artifact_sha256"],
        capability_receipt_digest=wire["capability_receipt_digest"],
        allowed_instruments=wire["allowed_instruments"],
        max_quantity=wire["max_quantity"],
        max_external_writes=wire["max_external_writes"],
        cleanup_required=wire["cleanup_required"],
        reconciliation_required=wire["reconciliation_required"],
        created_at=wire["created_at"],
        valid_from=wire["valid_from"],
        expires_at=wire["expires_at"],
        schema_version=wire["schema_version"],
    )
    if len(canonical_test_execution_profile(profile)) > MAX_TEST_EXECUTION_PROFILE_BYTES:
        _reject("profile_too_large", "profile exceeds the maximum supported size")
    return profile


def canonical_test_execution_profile(profile: TestExecutionProfile) -> bytes:
    """Return the exact deterministic bytes supplied to an offline verifier."""

    if type(profile) is not TestExecutionProfile:
        raise TypeError("profile must be a TestExecutionProfile")
    return json.dumps(
        TestExecutionProfile.as_wire(profile),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_execution_profile_sha256(profile: TestExecutionProfile) -> str:
    """Return a stable profile digest suitable for an offline audit record."""

    return hashlib.sha256(canonical_test_execution_profile(profile)).hexdigest()


# Keep this public API discoverable without letting pytest mistake it for a
# test when a consumer imports it into a ``test_*.py`` module.
test_execution_profile_sha256.__test__ = False


def _require_equal(actual: str, expected: str, reason: str, message: str) -> None:
    if actual != expected:
        _reject(reason, message)


def _require_digest_equal(actual: str, expected: str, reason: str, message: str) -> None:
    if not hmac.compare_digest(actual, expected):
        _reject(reason, message)


def _validate_profile_lifecycle(profile: TestExecutionProfile, checked_at: float) -> None:
    if checked_at < profile.valid_from:
        _reject("profile_not_yet_valid", "test execution profile is not yet valid")
    if checked_at >= profile.expires_at:
        _reject("profile_expired", "test execution profile has expired")


def _validate_profile_context(
    profile: TestExecutionProfile, context: TestExecutionPreflightContext
) -> None:
    _require_equal(
        context.provider,
        profile.provider,
        "provider_mismatch",
        "preflight provider does not match the test execution profile",
    )
    _require_equal(
        context.environment,
        profile.environment,
        "environment_mismatch",
        "preflight environment does not match the test execution profile",
    )
    _require_digest_equal(
        context.account_fingerprint_sha256,
        profile.account_fingerprint_sha256,
        "account_fingerprint_mismatch",
        "preflight account fingerprint does not match the test execution profile",
    )
    _require_digest_equal(
        context.approval_receipt_digest,
        profile.approval_receipt_digest,
        "approval_receipt_digest_mismatch",
        "preflight approval binding does not match the test execution profile",
    )
    _require_digest_equal(
        context.effective_config_digest,
        profile.effective_config_digest,
        "effective_config_digest_mismatch",
        "preflight configuration does not match the test execution profile",
    )
    _require_digest_equal(
        context.artifact_sha256,
        profile.artifact_sha256,
        "artifact_mismatch",
        "preflight artifact does not match the test execution profile",
    )
    _require_digest_equal(
        context.capability_receipt_digest,
        profile.capability_receipt_digest,
        "capability_receipt_digest_mismatch",
        "preflight capability receipt does not match the test execution profile",
    )
    if context.instrument not in profile.allowed_instruments:
        _reject("instrument_not_allowed", "preflight instrument is not allowed by the test profile")
    if Decimal(context.quantity) > Decimal(profile.max_quantity):
        _reject("quantity_limit_exceeded", "preflight quantity exceeds the test profile limit")
    if context.requested_external_writes > profile.max_external_writes:
        _reject(
            "external_write_limit_exceeded",
            "preflight external write count exceeds the test profile limit",
        )
    if context.cleanup_ready is not True:
        _reject("cleanup_not_ready", "test execution profile requires a cleanup plan")
    if context.reconciliation_ready is not True:
        _reject("reconciliation_not_ready", "test execution profile requires reconciliation")


def validate_test_execution_profile(
    value: Union[Mapping[str, Any], SerializedTestExecutionProfile],
    *,
    context: TestExecutionPreflightContext,
    verifier: Optional[TestExecutionProfileVerifier] = None,
) -> TestExecutionProfileObservation:
    """Check an offline profile/context binding before any provider preflight.

    The default verifier rejects.  A verifier that accepts only produces a
    non-authoritative observation: it never resolves credentials, connects a
    provider, starts a preflight, or permits an external write.
    """

    if type(context) is not TestExecutionPreflightContext:
        raise TypeError("context must be a TestExecutionPreflightContext")
    profile = parse_test_execution_profile(value)
    checked_at = _timestamp(time.time(), "now")
    _validate_profile_lifecycle(profile, checked_at)
    _validate_profile_context(profile, context)

    canonical_payload = canonical_test_execution_profile(profile)
    snapshot_profile = parse_test_execution_profile(canonical_payload)
    verifier_profile = parse_test_execution_profile(canonical_payload)
    selected_verifier: TestExecutionProfileVerifier
    if verifier is None:
        selected_verifier = RejectingTestExecutionProfileVerifier()
    else:
        selected_verifier = verifier
    try:
        trusted = selected_verifier.verify(verifier_profile, canonical_payload)
    except Exception:
        _reject("profile_verifier_failed", "test execution profile verifier failed")
    if trusted is not True:
        _reject("profile_untrusted", "test execution profile is not trusted")
    try:
        post_verifier_payload = canonical_test_execution_profile(verifier_profile)
    except Exception:
        _reject("profile_mutated_by_verifier", "test execution profile verifier changed its input")
    if not hmac.compare_digest(canonical_payload, post_verifier_payload):
        _reject("profile_mutated_by_verifier", "test execution profile verifier changed its input")

    post_verify_checked_at = _timestamp(time.time(), "post_verify_now")
    _validate_profile_lifecycle(snapshot_profile, post_verify_checked_at)
    return TestExecutionProfileObservation(
        profile_id=snapshot_profile.profile_id,
        profile_sha256=hashlib.sha256(canonical_payload).hexdigest(),
        provider=snapshot_profile.provider,
        environment=snapshot_profile.environment,
        approval_receipt_digest=snapshot_profile.approval_receipt_digest,
        instrument=context.instrument,
        quantity=context.quantity,
        requested_external_writes=context.requested_external_writes,
        checked_at=post_verify_checked_at,
        valid_until=snapshot_profile.expires_at,
    )


__all__ = [
    "MAX_TEST_EXECUTION_PROFILE_BYTES",
    "MAX_TEST_EXECUTION_PROFILE_EXTERNAL_WRITES",
    "MAX_TEST_EXECUTION_PROFILE_INSTRUMENT_LENGTH",
    "MAX_TEST_EXECUTION_PROFILE_INSTRUMENTS",
    "MAX_TEST_EXECUTION_PROFILE_LIFETIME_SECONDS",
    "RejectingTestExecutionProfileVerifier",
    "TEST_EXECUTION_PROFILE_PRECHECKED",
    "TEST_EXECUTION_PROFILE_SCHEMA_VERSION",
    "TestExecutionPreflightContext",
    "TestExecutionProfile",
    "TestExecutionProfileError",
    "TestExecutionProfileObservation",
    "TestExecutionProfileVerifier",
    "canonical_test_execution_profile",
    "parse_test_execution_profile",
    "test_execution_profile_sha256",
    "validate_test_execution_profile",
]
