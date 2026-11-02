"""Offline receipt binding for future provider deployment admission.

This module deliberately owns only a narrow, pure validation boundary.  It
does not resolve ``secrets_ref``, import a provider or SDK, start a preflight,
or dispatch a runner.  A matching receipt is still not deployment, execution,
or provider authorization.

There is intentionally no built-in trust implementation.  A deployment owner
must inject a verifier with its actual offline trust material.  The default
verifier rejects every receipt, so this module cannot turn a record into an
admission grant on its own.
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
from typing import Any, Optional, Protocol, Sequence, Tuple, Union


PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION = "bt-provider-deployment-receipt/v2"
ACTIVE_RECEIPT_STATUS = "active"
REVOKED_RECEIPT_STATUS = "revoked"
RECEIPT_BINDING_VALIDATED = "RECEIPT_BINDING_VALIDATED"
MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES = 64 * 1024
MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULES = 16
MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH = 128

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_STATUS_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OS_SECRET_REF_RE = re.compile(r"^os_secret_store:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CAPABILITY_MODULE_RE = re.compile(r"^bt_api(?:_[A-Za-z0-9]+)+$")
_RECEIPT_FIELDS = frozenset(
    (
        "account_fingerprint_sha256",
        "approval_receipt_digest",
        "artifact_sha256",
        "capability_receipt_digest",
        "created_at",
        "effective_config_digest",
        "environment",
        "expires_at",
        "provider",
        "receipt_id",
        "registration_id",
        "required_capability_modules",
        "revoked_at",
        "runtime_id",
        "schema_version",
        "secrets_ref",
        "status",
        "strategy_id",
    )
)


SerializedProviderDeploymentReceipt = Union[str, bytes, bytearray]


class ProviderDeploymentReceiptError(ValueError):
    """A deterministic, redacted rejection of an untrusted deployment receipt."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise ProviderDeploymentReceiptError(reason, message)


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


def _status(value: Any) -> str:
    if (
        type(value) is not str
        or len(value) > 64
        or value != value.strip()
        or not _STATUS_RE.fullmatch(value)
    ):
        _reject("invalid_status", "invalid receipt status")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if type(value) is not str or len(value) != 64 or not _SHA256_RE.fullmatch(value):
        _reject("invalid_digest", "invalid {0}".format(field_name))
    return value


def _opaque_secret_ref(value: Any, field_name: str) -> str:
    if type(value) is not str or len(value) > 144 or not _OS_SECRET_REF_RE.fullmatch(value):
        _reject("invalid_secrets_ref", "invalid {0}".format(field_name))
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


def _capability_modules(value: Any, field_name: str) -> Tuple[str, ...]:
    if type(value) not in (list, tuple) or not value:
        _reject("invalid_capability_modules", "invalid {0}".format(field_name))
    if len(value) > MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULES:
        _reject("receipt_too_large", "receipt contains too many required capability modules")
    modules = tuple(value)
    if any(
        type(module) is not str
        or len(module) > MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH
        or not _CAPABILITY_MODULE_RE.fullmatch(module)
        for module in modules
    ):
        if any(
            type(module) is str
            and len(module) > MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH
            for module in modules
        ):
            _reject("receipt_too_large", "required capability module name is too large")
        _reject("invalid_capability_modules", "invalid required capability module")
    if len(set(modules)) != len(modules):
        _reject("invalid_capability_modules", "duplicate required capability module")
    return tuple(sorted(modules))


def _registration_value(value: Any, validator, field_name: str) -> Any:
    """Convert a receipt-style validation failure into a code-registration error."""

    try:
        return validator(value, field_name)
    except ProviderDeploymentReceiptError as error:
        raise ValueError(str(error)) from None


@dataclass(frozen=True)
class ProviderDeploymentRegistration:
    """A code-owned, exact deployment scope for one provider environment.

    This is intentionally not parsed from ``config.yaml``.  Its opaque secret
    references are names only; this object never locates or resolves them.
    """

    registration_id: str
    runtime_id: str
    strategy_id: str
    provider: str
    environment: str
    allowed_secrets_refs: Tuple[str, ...] = field(repr=False)
    account_fingerprint_sha256: str
    approval_receipt_digest: str
    artifact_sha256: str
    effective_config_digest: str
    capability_receipt_digest: str
    required_capability_modules: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "registration_id",
            _registration_value(self.registration_id, _identifier, "registration_id"),
        )
        object.__setattr__(
            self, "runtime_id", _registration_value(self.runtime_id, _identifier, "runtime_id")
        )
        object.__setattr__(
            self, "strategy_id", _registration_value(self.strategy_id, _identifier, "strategy_id")
        )
        object.__setattr__(
            self, "provider", _registration_value(self.provider, _provider, "provider")
        )
        object.__setattr__(
            self, "environment", _registration_value(self.environment, _provider, "environment")
        )

        if type(self.allowed_secrets_refs) not in (list, tuple):
            raise ValueError("allowed_secrets_refs must be a non-empty sequence")
        refs = tuple(self.allowed_secrets_refs)
        if not refs:
            raise ValueError("registered deployment must allow an opaque secret reference")
        try:
            normalized_refs = tuple(
                _opaque_secret_ref(reference, "allowed_secrets_refs") for reference in refs
            )
        except ProviderDeploymentReceiptError as error:
            raise ValueError(str(error)) from None
        if len(set(normalized_refs)) != len(normalized_refs):
            raise ValueError("registered deployment has duplicate allowed secret references")
        object.__setattr__(self, "allowed_secrets_refs", normalized_refs)

        object.__setattr__(
            self,
            "account_fingerprint_sha256",
            _registration_value(
                self.account_fingerprint_sha256, _sha256, "account_fingerprint_sha256"
            ),
        )
        object.__setattr__(
            self,
            "approval_receipt_digest",
            _registration_value(self.approval_receipt_digest, _sha256, "approval_receipt_digest"),
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _registration_value(self.artifact_sha256, _sha256, "artifact_sha256"),
        )
        object.__setattr__(
            self,
            "effective_config_digest",
            _registration_value(self.effective_config_digest, _sha256, "effective_config_digest"),
        )
        object.__setattr__(
            self,
            "capability_receipt_digest",
            _registration_value(
                self.capability_receipt_digest, _sha256, "capability_receipt_digest"
            ),
        )
        try:
            modules = _capability_modules(
                self.required_capability_modules, "required_capability_modules"
            )
        except ProviderDeploymentReceiptError as error:
            raise ValueError(str(error)) from None
        object.__setattr__(self, "required_capability_modules", modules)

    def as_public_dict(self) -> dict[str, Any]:
        """Return a diagnostic view that never reveals opaque reference names."""

        return {
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "approval_receipt_digest": self.approval_receipt_digest,
            "allowed_secrets_refs": tuple("configured" for _ in self.allowed_secrets_refs),
            "artifact_sha256": self.artifact_sha256,
            "capability_receipt_digest": self.capability_receipt_digest,
            "effective_config_digest": self.effective_config_digest,
            "environment": self.environment,
            "provider": self.provider,
            "registration_id": self.registration_id,
            "required_capability_modules": self.required_capability_modules,
            "runtime_id": self.runtime_id,
            "strategy_id": self.strategy_id,
        }


@dataclass(frozen=True)
class ProviderDeploymentReceipt:
    """The parsed, still-untrusted wire record for one deployment scope."""

    receipt_id: str
    registration_id: str
    runtime_id: str
    strategy_id: str
    provider: str
    environment: str
    secrets_ref: str = field(repr=False)
    account_fingerprint_sha256: str
    approval_receipt_digest: str
    artifact_sha256: str
    effective_config_digest: str
    capability_receipt_digest: str
    required_capability_modules: Tuple[str, ...]
    status: str
    created_at: float
    expires_at: float
    revoked_at: Optional[float]
    schema_version: str = PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "registration_id", _identifier(self.registration_id, "registration_id")
        )
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(self, "strategy_id", _identifier(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "provider", _provider(self.provider, "provider"))
        object.__setattr__(self, "environment", _provider(self.environment, "environment"))
        object.__setattr__(self, "secrets_ref", _opaque_secret_ref(self.secrets_ref, "secrets_ref"))
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
            self, "artifact_sha256", _sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self,
            "effective_config_digest",
            _sha256(self.effective_config_digest, "effective_config_digest"),
        )
        object.__setattr__(
            self,
            "capability_receipt_digest",
            _sha256(self.capability_receipt_digest, "capability_receipt_digest"),
        )
        object.__setattr__(
            self,
            "required_capability_modules",
            _capability_modules(self.required_capability_modules, "required_capability_modules"),
        )
        object.__setattr__(self, "status", _status(self.status))
        created_at = _timestamp(self.created_at, "created_at")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            _reject("invalid_timestamp", "receipt expiry must follow creation")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)
        if self.revoked_at is not None:
            object.__setattr__(self, "revoked_at", _timestamp(self.revoked_at, "revoked_at"))
        if (
            type(self.schema_version) is not str
            or self.schema_version != PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION
        ):
            _reject("unsupported_schema", "provider deployment receipt schema is not supported")

    def as_wire(self) -> dict[str, Any]:
        """Return the canonical field set used for digest and trust verification."""

        return {
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "approval_receipt_digest": self.approval_receipt_digest,
            "artifact_sha256": self.artifact_sha256,
            "capability_receipt_digest": self.capability_receipt_digest,
            "created_at": self.created_at,
            "effective_config_digest": self.effective_config_digest,
            "environment": self.environment,
            "expires_at": self.expires_at,
            "provider": self.provider,
            "receipt_id": self.receipt_id,
            "registration_id": self.registration_id,
            "required_capability_modules": list(self.required_capability_modules),
            "revoked_at": self.revoked_at,
            "runtime_id": self.runtime_id,
            "schema_version": self.schema_version,
            "secrets_ref": self.secrets_ref,
            "status": self.status,
            "strategy_id": self.strategy_id,
        }


class ProviderDeploymentReceiptVerifier(Protocol):
    """A deployment-owner supplied, pure verifier for a parsed receipt.

    Implementations receive a canonical byte payload and may use preloaded,
    offline trust material.  They must not resolve secrets, import a provider
    SDK, contact a provider, or start a provider preflight.
    """

    def verify(self, receipt: ProviderDeploymentReceipt, canonical_payload: bytes) -> bool:
        """Return whether this exact canonical receipt is trusted."""


class RejectingProviderDeploymentReceiptVerifier:
    """The default fail-closed verifier when no real trust implementation exists."""

    def verify(self, receipt: ProviderDeploymentReceipt, canonical_payload: bytes) -> bool:
        del receipt, canonical_payload
        return False


@dataclass(frozen=True)
class ProviderDeploymentReceiptValidation:
    """A verified binding observation that deliberately has no admission authority."""

    receipt_id: str
    receipt_sha256: str
    registration_id: str
    runtime_id: str
    strategy_id: str
    provider: str
    environment: str
    account_fingerprint_sha256: str
    approval_receipt_digest: str
    artifact_sha256: str
    effective_config_digest: str
    capability_receipt_digest: str
    required_capability_modules: Tuple[str, ...]
    checked_at: float
    valid_until: float
    status: str = RECEIPT_BINDING_VALIDATED
    receipt_binding_valid: bool = True
    deployment_authorized: bool = False
    execution_authorized: bool = False
    secrets_resolved: bool = False
    provider_preflight_started: bool = False

    def __post_init__(self) -> None:
        checked_at = _timestamp(self.checked_at, "checked_at")
        valid_until = _timestamp(self.valid_until, "valid_until")
        if (
            self.status != RECEIPT_BINDING_VALIDATED
            or self.receipt_binding_valid is not True
            or self.deployment_authorized is not False
            or self.execution_authorized is not False
            or self.secrets_resolved is not False
            or self.provider_preflight_started is not False
        ):
            raise ValueError("provider deployment validation cannot grant admission or execution")
        if valid_until <= checked_at:
            raise ValueError(
                "provider deployment validation must retain a future validity deadline"
            )
        object.__setattr__(
            self,
            "approval_receipt_digest",
            _sha256(self.approval_receipt_digest, "approval_receipt_digest"),
        )
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "valid_until", valid_until)

    def __bool__(self) -> bool:
        """Reject truthiness so a binding observation cannot become an approval gate.

        A successful receipt-binding check is deliberately non-authoritative.
        Future session factories must inspect their own explicit, provider-owned
        admission result rather than accidentally treating this object as a
        permission token in ``if validation:`` code.
        """

        raise TypeError(
            "ProviderDeploymentReceiptValidation is not an admission decision; "
            "do not use it as a boolean"
        )

    def as_public_dict(self) -> dict[str, Any]:
        """Return a redacted observation safe for offline diagnostics."""

        return {
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "approval_receipt_digest": self.approval_receipt_digest,
            "artifact_sha256": self.artifact_sha256,
            "capability_receipt_digest": self.capability_receipt_digest,
            "checked_at": self.checked_at,
            "deployment_authorized": self.deployment_authorized,
            "effective_config_digest": self.effective_config_digest,
            "environment": self.environment,
            "execution_authorized": self.execution_authorized,
            "provider": self.provider,
            "provider_preflight_started": self.provider_preflight_started,
            "receipt_binding_valid": self.receipt_binding_valid,
            "receipt_id": self.receipt_id,
            "receipt_sha256": self.receipt_sha256,
            "registration_id": self.registration_id,
            "required_capability_modules": self.required_capability_modules,
            "runtime_id": self.runtime_id,
            "secrets_resolved": self.secrets_resolved,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "valid_until": self.valid_until,
        }


def _reject_json_constant(_: str) -> None:
    _reject("invalid_json", "receipt contains a non-finite JSON value")


def _reject_duplicate_fields(pairs: Sequence[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("invalid_json", "receipt JSON contains duplicate object keys")
        result[key] = value
    return result


def _coerce_receipt_wire(
    value: Union[Mapping[str, Any], SerializedProviderDeploymentReceipt]
) -> Mapping[str, Any]:
    if type(value) is bytearray:
        if len(value) > MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES:
            _reject("receipt_too_large", "receipt exceeds the maximum supported size")
        value = bytes(value)
    if type(value) is bytes:
        if len(value) > MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES:
            _reject("receipt_too_large", "receipt exceeds the maximum supported size")
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            _reject("invalid_json", "receipt must be UTF-8 JSON")
    if type(value) is str:
        if len(value) > MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES:
            _reject("receipt_too_large", "receipt exceeds the maximum supported size")
        try:
            encoded_length = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            _reject("invalid_json", "receipt must be UTF-8 JSON")
        if encoded_length > MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES:
            _reject("receipt_too_large", "receipt exceeds the maximum supported size")
        try:
            parsed = json.loads(
                value,
                object_pairs_hook=_reject_duplicate_fields,
                parse_constant=_reject_json_constant,
            )
        except ProviderDeploymentReceiptError:
            raise
        except (json.JSONDecodeError, RecursionError, ValueError):
            _reject("invalid_json", "receipt is not valid JSON")
        if type(parsed) is not dict:
            _reject("invalid_wire", "receipt wire must be an object")
        return parsed
    # Do not invoke arbitrary Mapping implementations here.  This is an
    # offline parsing boundary, so accepting a lazy/stateful Mapping would let
    # its __iter__ or __getitem__ implementation perform side effects while a
    # receipt is merely being validated.  A plain dict is the only supported
    # in-memory wire form; serialized JSON remains the interchange form.
    if type(value) is not dict:
        _reject("invalid_wire", "receipt wire must be a plain JSON object")
    return dict(value)


def parse_provider_deployment_receipt(
    value: Union[Mapping[str, Any], SerializedProviderDeploymentReceipt]
) -> ProviderDeploymentReceipt:
    """Strictly parse a receipt without contacting a trust or provider system."""

    wire = _coerce_receipt_wire(value)
    keys = tuple(wire)
    if any(type(key) is not str for key in keys) or set(keys) != _RECEIPT_FIELDS:
        _reject("invalid_wire", "receipt wire fields do not match the deployment contract")
    receipt = ProviderDeploymentReceipt(
        receipt_id=wire["receipt_id"],
        registration_id=wire["registration_id"],
        runtime_id=wire["runtime_id"],
        strategy_id=wire["strategy_id"],
        provider=wire["provider"],
        environment=wire["environment"],
        secrets_ref=wire["secrets_ref"],
        account_fingerprint_sha256=wire["account_fingerprint_sha256"],
        approval_receipt_digest=wire["approval_receipt_digest"],
        artifact_sha256=wire["artifact_sha256"],
        effective_config_digest=wire["effective_config_digest"],
        capability_receipt_digest=wire["capability_receipt_digest"],
        required_capability_modules=wire["required_capability_modules"],
        status=wire["status"],
        created_at=wire["created_at"],
        expires_at=wire["expires_at"],
        revoked_at=wire["revoked_at"],
        schema_version=wire["schema_version"],
    )
    if len(canonical_provider_deployment_receipt(receipt)) > MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES:
        _reject("receipt_too_large", "receipt exceeds the maximum supported size")
    return receipt


def canonical_provider_deployment_receipt(receipt: ProviderDeploymentReceipt) -> bytes:
    """Return the deterministic payload supplied to the injected trust verifier."""

    if type(receipt) is not ProviderDeploymentReceipt:
        raise TypeError("receipt must be a ProviderDeploymentReceipt")
    return json.dumps(
        ProviderDeploymentReceipt.as_wire(receipt),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def provider_deployment_receipt_sha256(receipt: ProviderDeploymentReceipt) -> str:
    """Return the SHA-256 of the complete canonical receipt wire."""

    return hashlib.sha256(canonical_provider_deployment_receipt(receipt)).hexdigest()


def _require_bound(receipt_value: str, registered_value: str, reason: str, message: str) -> None:
    if receipt_value != registered_value:
        _reject(reason, message)


def _require_bound_digest(
    receipt_value: str, registered_value: str, reason: str, message: str
) -> None:
    if not hmac.compare_digest(receipt_value, registered_value):
        _reject(reason, message)


def _validate_receipt_binding(
    receipt: ProviderDeploymentReceipt, registration: ProviderDeploymentRegistration
) -> None:
    _require_bound(
        receipt.registration_id,
        registration.registration_id,
        "registration_mismatch",
        "receipt registration does not match the reviewed deployment scope",
    )
    _require_bound(
        receipt.runtime_id,
        registration.runtime_id,
        "runtime_mismatch",
        "receipt runtime does not match the reviewed deployment scope",
    )
    _require_bound(
        receipt.strategy_id,
        registration.strategy_id,
        "strategy_mismatch",
        "receipt strategy does not match the reviewed deployment scope",
    )
    _require_bound(
        receipt.provider,
        registration.provider,
        "provider_mismatch",
        "receipt provider does not match the reviewed deployment scope",
    )
    _require_bound(
        receipt.environment,
        registration.environment,
        "environment_mismatch",
        "receipt environment does not match the reviewed deployment scope",
    )
    if receipt.secrets_ref not in registration.allowed_secrets_refs:
        _reject(
            "secrets_ref_not_registered", "receipt secret reference is not in the reviewed scope"
        )
    _require_bound_digest(
        receipt.account_fingerprint_sha256,
        registration.account_fingerprint_sha256,
        "account_fingerprint_mismatch",
        "receipt account fingerprint does not match the reviewed deployment scope",
    )
    _require_bound_digest(
        receipt.approval_receipt_digest,
        registration.approval_receipt_digest,
        "approval_receipt_digest_mismatch",
        "receipt approval binding does not match the reviewed deployment scope",
    )
    _require_bound_digest(
        receipt.artifact_sha256,
        registration.artifact_sha256,
        "artifact_mismatch",
        "receipt artifact does not match the reviewed deployment scope",
    )
    _require_bound_digest(
        receipt.effective_config_digest,
        registration.effective_config_digest,
        "effective_config_digest_mismatch",
        "receipt effective configuration does not match the reviewed deployment scope",
    )
    _require_bound_digest(
        receipt.capability_receipt_digest,
        registration.capability_receipt_digest,
        "capability_receipt_digest_mismatch",
        "receipt capability receipt does not match the reviewed deployment scope",
    )
    if receipt.required_capability_modules != registration.required_capability_modules:
        _reject(
            "required_capability_modules_mismatch",
            "receipt capability modules do not match the reviewed deployment scope",
        )


def _validate_receipt_lifecycle(receipt: ProviderDeploymentReceipt, checked_at: float) -> None:
    if receipt.status == REVOKED_RECEIPT_STATUS or receipt.revoked_at is not None:
        _reject("receipt_revoked", "provider deployment receipt is revoked")
    if receipt.status != ACTIVE_RECEIPT_STATUS:
        _reject("unsupported_receipt_status", "provider deployment receipt status is not supported")
    if checked_at < receipt.created_at:
        _reject("receipt_not_yet_valid", "provider deployment receipt is not yet valid")
    if checked_at >= receipt.expires_at:
        _reject("receipt_expired", "provider deployment receipt has expired")


def validate_provider_deployment_receipt(
    value: Union[Mapping[str, Any], SerializedProviderDeploymentReceipt],
    *,
    registration: ProviderDeploymentRegistration,
    verifier: Optional[ProviderDeploymentReceiptVerifier] = None,
) -> ProviderDeploymentReceiptValidation:
    """Validate one receipt's offline binding before any secret or provider work.

    The injected verifier is called only after exact wire parsing, scope,
    revocation, status, and expiry checks pass.  A successful return remains a
    non-authoritative observation: it does not resolve a secret, initiate a
    provider session, or permit a runner to dispatch.
    """

    if type(registration) is not ProviderDeploymentRegistration:
        raise TypeError("registration must be a ProviderDeploymentRegistration")
    # Frozen dataclasses can still be changed with object.__setattr__.  Take a
    # validated copy at this boundary so malformed code-owned scope cannot be
    # smuggled past construction-time checks.
    registration = ProviderDeploymentRegistration(
        registration_id=registration.registration_id,
        runtime_id=registration.runtime_id,
        strategy_id=registration.strategy_id,
        provider=registration.provider,
        environment=registration.environment,
        allowed_secrets_refs=registration.allowed_secrets_refs,
        account_fingerprint_sha256=registration.account_fingerprint_sha256,
        approval_receipt_digest=registration.approval_receipt_digest,
        artifact_sha256=registration.artifact_sha256,
        effective_config_digest=registration.effective_config_digest,
        capability_receipt_digest=registration.capability_receipt_digest,
        required_capability_modules=registration.required_capability_modules,
    )
    receipt = parse_provider_deployment_receipt(value)
    _validate_receipt_binding(receipt, registration)
    checked_at = _timestamp(time.time(), "now")
    _validate_receipt_lifecycle(receipt, checked_at)

    # The verifier receives an isolated copy.  Frozen dataclasses can still
    # be modified through object.__setattr__, so retain a canonical snapshot
    # for the returned observation and reject a verifier that changes its
    # input.  The canonical bytes are also the exact payload the verifier
    # attests to.
    canonical_payload = canonical_provider_deployment_receipt(receipt)
    snapshot_receipt = parse_provider_deployment_receipt(canonical_payload)
    verifier_receipt = parse_provider_deployment_receipt(canonical_payload)

    selected_verifier: ProviderDeploymentReceiptVerifier
    if verifier is None:
        selected_verifier = RejectingProviderDeploymentReceiptVerifier()
    else:
        selected_verifier = verifier
    try:
        trusted = selected_verifier.verify(verifier_receipt, canonical_payload)
    except Exception:
        _reject("receipt_verifier_failed", "provider deployment receipt verifier failed")
    if trusted is not True:
        _reject("receipt_untrusted", "provider deployment receipt is not trusted")
    try:
        post_verifier_payload = canonical_provider_deployment_receipt(verifier_receipt)
    except Exception:
        _reject(
            "receipt_mutated_by_verifier", "provider deployment receipt verifier changed its input"
        )
    if not hmac.compare_digest(canonical_payload, post_verifier_payload):
        _reject(
            "receipt_mutated_by_verifier", "provider deployment receipt verifier changed its input"
        )

    # A real verifier can take time.  Recheck expiry after it returns and
    # expose the deadline so a future provider session factory must obtain a
    # fresh validation rather than treating this observation as durable.
    post_verify_checked_at = _timestamp(time.time(), "post_verify_now")
    _validate_receipt_lifecycle(snapshot_receipt, post_verify_checked_at)

    return ProviderDeploymentReceiptValidation(
        receipt_id=snapshot_receipt.receipt_id,
        receipt_sha256=hashlib.sha256(canonical_payload).hexdigest(),
        registration_id=registration.registration_id,
        runtime_id=snapshot_receipt.runtime_id,
        strategy_id=snapshot_receipt.strategy_id,
        provider=snapshot_receipt.provider,
        environment=snapshot_receipt.environment,
        account_fingerprint_sha256=snapshot_receipt.account_fingerprint_sha256,
        approval_receipt_digest=snapshot_receipt.approval_receipt_digest,
        artifact_sha256=snapshot_receipt.artifact_sha256,
        effective_config_digest=snapshot_receipt.effective_config_digest,
        capability_receipt_digest=snapshot_receipt.capability_receipt_digest,
        required_capability_modules=snapshot_receipt.required_capability_modules,
        checked_at=post_verify_checked_at,
        valid_until=snapshot_receipt.expires_at,
    )


__all__ = [
    "ACTIVE_RECEIPT_STATUS",
    "MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULES",
    "MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH",
    "MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES",
    "PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION",
    "RECEIPT_BINDING_VALIDATED",
    "REVOKED_RECEIPT_STATUS",
    "ProviderDeploymentReceipt",
    "ProviderDeploymentReceiptError",
    "ProviderDeploymentReceiptValidation",
    "ProviderDeploymentReceiptVerifier",
    "ProviderDeploymentRegistration",
    "RejectingProviderDeploymentReceiptVerifier",
    "canonical_provider_deployment_receipt",
    "parse_provider_deployment_receipt",
    "provider_deployment_receipt_sha256",
    "validate_provider_deployment_receipt",
]
