"""Trusted Iteration 41 bindings for offline AI review evidence.

The portable ``bt-api-deployment-evidence/v1`` wire is deliberately shared by
three independently packaged AI products.  None of those products may import
the Backtrader runtime registry, because doing so would turn a review helper
into an execution dependency.  This module is the narrow composition point
where Backtrader derives the consumer's expected bindings from a *currently
registered* schema-v4 ``config.yaml`` and the actual strategy artifact bytes.

It has no provider, account, execution, gateway, or AI-product import.  A
successful validation is still only ``REVIEW_REQUIRED``.  It is not an
admission receipt and cannot authorize deployment, execution, or control.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional, Union

from .config import load_runtime_config
from .registry import RuntimeRegistry, resolve_runtime_config


ITERATION41_EVIDENCE_SCHEMA_VERSION = "bt-api-deployment-evidence/v1"
REVIEW_REQUIRED = "review_required"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WIRE_FIELDS = frozenset(
    {
        "artifact_sha256",
        "config_effective_digest",
        "created_at",
        "evidence_id",
        "expires_at",
        "metadata",
        "producer",
        "review_status",
        "schema_version",
        "strategy_id",
        "tenant_id",
    }
)
_PRODUCER_FIELDS = frozenset({"commit", "product", "version", "wheel_sha256"})
_CHUNK_SIZE = 1024 * 1024

# Evidence metadata is descriptive.  It must never carry a credential,
# approval, account/control assertion, or a command-shaped field that could be
# mistaken for an admission capability.  The producer already enforces this
# family of names; repeat it at this independent consumer boundary.
_FORBIDDEN_METADATA_KEY_PARTS = (
    "accesskey",
    "accountaccess",
    "admission",
    "apikey",
    "approval",
    "approved",
    "authorization",
    "authorize",
    "control",
    "credential",
    "deploy",
    "drain",
    "executionauthorize",
    "freeze",
    "passphrase",
    "password",
    "permission",
    "permit",
    "privatekey",
    "promotion",
    "reviewed",
    "reviewstatus",
    "resume",
    "riskpermit",
    "secret",
    "submitorder",
    "token",
)

SerializedEvidence = Union[str, bytes, bytearray]


class Iteration41ReviewEvidenceError(ValueError):
    """A safe, deterministic rejection at the review-evidence boundary."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: str, message: str) -> None:
    raise Iteration41ReviewEvidenceError(reason, message)


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not _IDENTIFIER.fullmatch(value):
        _reject("invalid_identifier", "invalid {0}".format(field_name))
    return value


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        _reject("invalid_digest", "invalid {0}".format(field_name))
    return value


def _timestamp(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject("invalid_timestamp", "invalid {0}".format(field_name))
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject("invalid_timestamp", "invalid {0}".format(field_name))
    if not math.isfinite(normalized):
        _reject("invalid_timestamp", "invalid {0}".format(field_name))
    return 0.0 if normalized == 0.0 else normalized


def _normalized_key(key: str) -> str:
    return "".join(character for character in key.lower() if character.isalnum())


def _is_forbidden_metadata_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in _FORBIDDEN_METADATA_KEY_PARTS)


def _copy_json(
    value: Any,
    *,
    path: tuple[str, ...] = (),
    allow_root_review_status: bool = False,
    ancestors: frozenset[int] = frozenset(),
) -> Any:
    """Return a finite JSON copy while rejecting authority-shaped fields."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _reject("invalid_json", "evidence contains a non-finite JSON value")
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if id(value) in ancestors:
            _reject("invalid_json", "evidence JSON must not contain cycles")
        next_ancestors = ancestors | {id(value)}
        copied: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                _reject("invalid_json", "evidence JSON object keys must be strings")
            if key in copied:
                _reject("invalid_json", "evidence JSON contains duplicate object keys")
            root_review_status = (
                allow_root_review_status and not path and _normalized_key(key) == "reviewstatus"
            )
            if _is_forbidden_metadata_key(key) and not root_review_status:
                _reject(
                    "authority_shaped_metadata",
                    "evidence metadata contains a secret or authority-shaped field",
                )
            copied[key] = _copy_json(
                nested,
                path=path + (key,),
                allow_root_review_status=allow_root_review_status,
                ancestors=next_ancestors,
            )
        return copied
    if isinstance(value, (list, tuple)):
        if id(value) in ancestors:
            _reject("invalid_json", "evidence JSON must not contain cycles")
        next_ancestors = ancestors | {id(value)}
        return [
            _copy_json(
                nested,
                path=path,
                allow_root_review_status=allow_root_review_status,
                ancestors=next_ancestors,
            )
            for nested in value
        ]
    _reject("invalid_json", "evidence contains an unsupported JSON value")


def canonical_json(value: Any) -> str:
    """Serialize v1 evidence using the independently shared canonical form."""

    allow_root_review_status = isinstance(value, Mapping) and set(value) == _WIRE_FIELDS
    copied = _copy_json(value, allow_root_review_status=allow_root_review_status)
    return json.dumps(
        copied,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def evidence_sha256(value: Any) -> str:
    """Return the SHA-256 of the full canonical v1 wire record."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_json_constant(_: str) -> None:
    _reject("invalid_json", "evidence contains a non-finite JSON value")


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("invalid_json", "evidence JSON contains duplicate object keys")
        result[key] = value
    return result


def _coerce_wire(value: Mapping[str, Any] | SerializedEvidence) -> dict[str, Any]:
    if isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            _reject("invalid_json", "evidence must be UTF-8 JSON")
    if isinstance(value, str):
        try:
            parsed = json.loads(
                value,
                object_pairs_hook=_reject_duplicate_fields,
                parse_constant=_reject_json_constant,
            )
        except Iteration41ReviewEvidenceError:
            raise
        except json.JSONDecodeError:
            _reject("invalid_json", "evidence is not valid JSON")
        if not isinstance(parsed, dict):
            _reject("invalid_wire", "evidence wire must be an object")
        return parsed
    if not isinstance(value, Mapping):
        _reject("invalid_wire", "evidence wire must be an object")
    copied = _copy_json(value, allow_root_review_status=set(value) == _WIRE_FIELDS)
    if not isinstance(copied, dict):  # Defensive: Mapping always copies to dict.
        _reject("invalid_wire", "evidence wire must be an object")
    return copied


def _artifact_sha256(path: Path) -> str:
    try:
        file_status = path.lstat()
    except OSError:
        _reject("artifact_unreadable", "strategy artifact cannot be read")
    if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(file_status.st_mode):
        _reject("artifact_not_regular", "strategy artifact must be a regular non-symlink file")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError:
        _reject("artifact_unreadable", "strategy artifact cannot be read")
    return digest.hexdigest()


@dataclass(frozen=True)
class Iteration41ReviewEvidenceBindings:
    """Independent expected values for an AI evidence consumer.

    The values are derived from a registered runtime's currently parsed v4
    config and actual artifact bytes.  They are input to a read-only consumer,
    never a credential, admission receipt, or provider capability.
    """

    tenant_id: str
    strategy_id: str
    artifact_sha256: str
    config_effective_digest: str
    registration_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "strategy_id", _identifier(self.strategy_id, "strategy_id"))
        object.__setattr__(
            self, "artifact_sha256", _sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self,
            "config_effective_digest",
            _sha256(self.config_effective_digest, "config_effective_digest"),
        )
        object.__setattr__(
            self, "registration_digest", _sha256(self.registration_digest, "registration_digest")
        )

    def as_consumer_bindings(self) -> Mapping[str, str]:
        """Return detached bindings shared by the independent read-only consumers."""

        return MappingProxyType(
            {
                "expected_tenant_id": self.tenant_id,
                "expected_strategy_id": self.strategy_id,
                "expected_artifact_sha256": self.artifact_sha256,
                "expected_config_effective_digest": self.config_effective_digest,
            }
        )


@dataclass(frozen=True)
class Iteration41ReviewEvidenceObservation:
    """A successful review-only observation with no authority fields set."""

    evidence_id: str
    evidence_sha256: str
    tenant_id: str
    strategy_id: str
    artifact_sha256: str
    config_effective_digest: str
    checked_at: float
    status: str = "REVIEW_REQUIRED"
    review_status: str = REVIEW_REQUIRED
    read_only: bool = True
    deployment_authorized: bool = False
    execution_authorized: bool = False
    control_authorized: bool = False

    def as_public_dict(self) -> dict[str, Any]:
        """Return the deliberately non-authoritative observation payload."""

        return {
            "artifact_sha256": self.artifact_sha256,
            "checked_at": self.checked_at,
            "config_effective_digest": self.config_effective_digest,
            "control_authorized": self.control_authorized,
            "deployment_authorized": self.deployment_authorized,
            "evidence_id": self.evidence_id,
            "evidence_sha256": self.evidence_sha256,
            "execution_authorized": self.execution_authorized,
            "read_only": self.read_only,
            "review_status": self.review_status,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "tenant_id": self.tenant_id,
        }


def resolve_iteration41_review_evidence_bindings(
    *,
    strategy_dir: Union[str, Path],
    tenant_id: str,
    artifact_path: Union[str, Path],
    registry: RuntimeRegistry,
) -> Iteration41ReviewEvidenceBindings:
    """Derive independent evidence bindings from a registered v4 runtime.

    ``load_runtime_config(..., registry=...)`` rejects an unregistered path
    *before* opening its config.  Resolution then includes the reviewed
    registration digest in the effective digest, so a changed config or
    registration cannot reuse old evidence under this Iteration 41 path.
    """

    expected_tenant = _identifier(tenant_id, "tenant_id")
    config = load_runtime_config(strategy_dir, registry=registry)
    effective = resolve_runtime_config(config, registry)
    return Iteration41ReviewEvidenceBindings(
        tenant_id=expected_tenant,
        strategy_id=effective.strategy_id,
        artifact_sha256=_artifact_sha256(Path(artifact_path)),
        config_effective_digest=effective.effective_digest,
        registration_digest=effective.registration.digest,
    )


def validate_iteration41_review_evidence(
    evidence: Union[Mapping[str, Any], SerializedEvidence],
    *,
    expected_evidence_sha256: str,
    bindings: Iteration41ReviewEvidenceBindings,
    now: Optional[float] = None,
) -> Iteration41ReviewEvidenceObservation:
    """Validate one v1 record against an independent registered-runtime scope.

    This is intentionally an Iteration 41 profile, not a replacement for the
    three products' broader portable v1 reader APIs.  Legacy evidence may be
    read by its original product, but it cannot pass this config-v4 binding
    unless it is a fresh, unexpired ``review_required`` record for the exact
    registered runtime and artifact.
    """

    expected_digest = _sha256(expected_evidence_sha256, "expected_evidence_sha256")
    wire = _coerce_wire(evidence)
    if set(wire) != _WIRE_FIELDS:
        _reject("invalid_wire", "evidence wire fields do not match the v1 contract")
    producer = wire.get("producer")
    if not isinstance(producer, Mapping) or set(producer) != _PRODUCER_FIELDS:
        _reject("invalid_wire", "evidence producer fields do not match the v1 contract")
    if wire["schema_version"] != ITERATION41_EVIDENCE_SCHEMA_VERSION:
        _reject("unsupported_schema", "evidence schema version is not supported")

    evidence_id = _identifier(wire["evidence_id"], "evidence_id")
    tenant_id = _identifier(wire["tenant_id"], "tenant_id")
    strategy_id = _identifier(wire["strategy_id"], "strategy_id")
    for field_name in ("product", "version", "commit"):
        _identifier(producer[field_name], "producer.{0}".format(field_name))
    artifact_sha256 = _sha256(wire["artifact_sha256"], "artifact_sha256")
    config_effective_digest = _sha256(wire["config_effective_digest"], "config_effective_digest")
    _sha256(producer["wheel_sha256"], "producer.wheel_sha256")
    if wire["review_status"] != REVIEW_REQUIRED:
        _reject(
            "review_status_not_review_required",
            "Iteration 41 evidence must remain review_required",
        )
    if not isinstance(wire["metadata"], Mapping):
        _reject("invalid_wire", "evidence metadata must be an object")
    created_at = _timestamp(wire["created_at"], "created_at")
    expires_at = _timestamp(wire["expires_at"], "expires_at")
    if expires_at <= created_at:
        _reject("invalid_timestamp", "evidence expiry must follow creation")

    digest = evidence_sha256(wire)
    if not hmac.compare_digest(digest, expected_digest):
        _reject("evidence_digest_mismatch", "evidence does not match its trusted digest")
    if tenant_id != bindings.tenant_id:
        _reject("tenant_mismatch", "evidence tenant does not match the registered review scope")
    if strategy_id != bindings.strategy_id:
        _reject("strategy_mismatch", "evidence strategy does not match the registered runtime")
    if not hmac.compare_digest(artifact_sha256, bindings.artifact_sha256):
        _reject("artifact_mismatch", "evidence artifact does not match the reviewed artifact bytes")
    if not hmac.compare_digest(config_effective_digest, bindings.config_effective_digest):
        _reject(
            "config_effective_digest_mismatch",
            "evidence config does not match the current registered configuration",
        )

    checked_at = _timestamp(time.time() if now is None else now, "now")
    if checked_at < created_at:
        _reject("evidence_not_yet_valid", "evidence is not yet valid")
    if checked_at >= expires_at:
        _reject("evidence_expired", "evidence has expired")

    return Iteration41ReviewEvidenceObservation(
        evidence_id=evidence_id,
        evidence_sha256=digest,
        tenant_id=tenant_id,
        strategy_id=strategy_id,
        artifact_sha256=artifact_sha256,
        config_effective_digest=config_effective_digest,
        checked_at=checked_at,
    )


def validate_registered_iteration41_review_evidence(
    evidence: Union[Mapping[str, Any], SerializedEvidence],
    *,
    expected_evidence_sha256: str,
    strategy_dir: Union[str, Path],
    tenant_id: str,
    artifact_path: Union[str, Path],
    registry: RuntimeRegistry,
    now: Optional[float] = None,
) -> Iteration41ReviewEvidenceObservation:
    """Resolve current config-v4 bindings and validate one review-only record.

    This convenience API is the admission-facing call site: it recomputes the
    expected scope immediately before validation, preventing a caller from
    reusing bindings captured from an earlier config or artifact revision.
    """

    bindings = resolve_iteration41_review_evidence_bindings(
        strategy_dir=strategy_dir,
        tenant_id=tenant_id,
        artifact_path=artifact_path,
        registry=registry,
    )
    return validate_iteration41_review_evidence(
        evidence,
        expected_evidence_sha256=expected_evidence_sha256,
        bindings=bindings,
        now=now,
    )


__all__ = [
    "ITERATION41_EVIDENCE_SCHEMA_VERSION",
    "REVIEW_REQUIRED",
    "Iteration41ReviewEvidenceBindings",
    "Iteration41ReviewEvidenceError",
    "Iteration41ReviewEvidenceObservation",
    "canonical_json",
    "evidence_sha256",
    "resolve_iteration41_review_evidence_bindings",
    "validate_iteration41_review_evidence",
    "validate_registered_iteration41_review_evidence",
]
