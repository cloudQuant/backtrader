"""Short-lived, locally signed, hash-bound capability tokens."""

import hmac
import os
import re
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .canonical import (
    atomic_write_bytes,
    atomic_write_json,
    canonical_json_bytes,
    hash_object,
    read_json,
)
from .errors import AgentError

TOKEN_KINDS = {"validation", "change", "run"}
ACTION_TOKEN_KINDS = {"change", "run"}
REQUIRED_BINDINGS = {
    "validation": {
        "artifact_record_hash",
        "dataset_hash",
        "dataset_id",
        "engine_hash",
        "environment_hash",
        "session_id",
        "spec_hash",
    },
    "change": {
        "artifact_hash",
        "artifact_record_hash",
        "change_manifest_hash",
        "dataset_hash",
        "dataset_id",
        "session_id",
        "spec_hash",
        "validation_token_hash",
        "validation_token_id",
    },
    "run": {
        "applied_artifact_hash",
        "applied_record_hash",
        "artifact_hash",
        "artifact_record_hash",
        "change_manifest_hash",
        "dataset_hash",
        "dataset_id",
        "mode",
        "session_id",
        "spec_hash",
        "validation_token_hash",
        "validation_token_id",
    },
}
APPROVAL_REQUEST_RE = re.compile(r"^aprq-[0-9a-f]{24}$")
EFFECT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,79}$")
BOUND_RECORD_KINDS = {
    "prepared-change": "prepared-change-record-v1",
    "applied-artifact": "applied-artifact-record-v1",
}
APPROVAL_SESSION_STATES = {
    "change": "APPLY_PREPARED",
    "run": "APPLIED",
}


class TokenAuthority:
    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)
        self.secret_path = self.state_root / "token-secret.key"
        self.approval_root = self.state_root / "approvals"

    def _secret(self) -> bytes:
        if not self.secret_path.exists():
            secret = secrets.token_bytes(32)
            atomic_write_bytes(self.secret_path, secret, create_only=True)
            try:
                self.secret_path.chmod(0o600)
            except OSError:
                pass
        secret = self.secret_path.read_bytes()
        if len(secret) != 32:
            raise AgentError("BTAG-TOKEN-SECRET", "local token secret has invalid length")
        return secret

    def _signature(self, payload: Dict[str, Any]) -> str:
        return hmac.new(self._secret(), canonical_json_bytes(payload), "sha256").hexdigest()

    def sign_product_record(self, record: Dict[str, Any]) -> str:
        """Seal an internal product record with a domain-separated local signature."""

        return self._signature({"domain": "backtrader-agent-product-record-v1", "record": record})

    def verify_product_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        signature = record.get("signature")
        payload = {key: value for key, value in record.items() if key != "signature"}
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, self.sign_product_record(payload)
        ):
            raise AgentError(
                "BTAG-PROVENANCE-SIGNATURE",
                "product-generated artifact record signature is invalid",
            )
        return payload

    def _bound_record_path(self, kind: str, session_id: str, subject_hash: str) -> Path:
        if kind not in BOUND_RECORD_KINDS:
            raise AgentError("BTAG-RECORD-KIND", "bound product record kind is not allowlisted")
        if not SESSION_RE.fullmatch(session_id) or not HASH_RE.fullmatch(subject_hash):
            raise AgentError("BTAG-RECORD-ID", "bound product record identifiers are malformed")
        return self.state_root / "sessions" / session_id / "records" / kind / f"{subject_hash}.json"

    def store_bound_record(
        self,
        kind: str,
        session_id: str,
        subject_hash: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist an immutable, signed product record for an approval subject."""

        if "record_hash" in payload or "signature" in payload:
            raise AgentError(
                "BTAG-RECORD-FIELDS",
                "bound product record payload contains reserved fields",
            )
        portable = {
            **payload,
            "schema_version": BOUND_RECORD_KINDS.get(kind),
            "record_kind": kind,
            "generated_by": "backtrader-agent",
            "session_id": session_id,
            "subject_hash": subject_hash,
        }
        if portable["schema_version"] is None:
            raise AgentError("BTAG-RECORD-KIND", "bound product record kind is not allowlisted")
        portable["record_hash"] = hash_object(portable)
        record = {
            **portable,
            "signature": self.sign_product_record(portable),
        }
        path = self._bound_record_path(kind, session_id, subject_hash)
        if path.exists():
            if path.is_symlink() or not path.is_file() or read_json(path) != record:
                raise AgentError(
                    "BTAG-RECORD-CONFLICT",
                    "bound product record conflicts with immutable product state",
                )
        else:
            atomic_write_json(path, record, create_only=True)
        return portable

    def load_bound_record(
        self,
        kind: str,
        session_id: str,
        subject_hash: str,
    ) -> Dict[str, Any]:
        """Load and authenticate a product-owned approval/apply record."""

        path = self._bound_record_path(kind, session_id, subject_hash)
        if not path.is_file() or path.is_symlink():
            raise AgentError(
                "BTAG-RECORD-MISSING",
                "approval subject has no product-owned signed record",
            )
        payload = self.verify_product_record(read_json(path))
        expected_hash = payload.get("record_hash")
        actual_hash = hash_object(
            {key: value for key, value in payload.items() if key != "record_hash"}
        )
        if (
            expected_hash != actual_hash
            or payload.get("schema_version") != BOUND_RECORD_KINDS[kind]
            or payload.get("record_kind") != kind
            or payload.get("generated_by") != "backtrader-agent"
            or payload.get("session_id") != session_id
            or payload.get("subject_hash") != subject_hash
        ):
            raise AgentError(
                "BTAG-RECORD-BINDING",
                "bound product record is inconsistent with its approval subject",
            )
        return payload

    def _validate_approval_context(
        self,
        kind: str,
        subject_hash: str,
        bindings: Dict[str, str],
    ) -> None:
        """Recompute approval context from signed records and session state."""

        from .sessions import SessionStore

        if kind == "run" and bindings.get("mode") not in {"runonce", "runnext"}:
            raise AgentError("BTAG-RUN-MODE", "mode must be runonce or runnext")
        session_id = bindings["session_id"]
        session = SessionStore(self.state_root).load(session_id)
        expected_state = APPROVAL_SESSION_STATES[kind]
        if session.get("state") != expected_state:
            raise AgentError(
                "BTAG-APPROVAL-SESSION",
                "session is not ready for this approval",
                details={"expected_state": expected_state, "state": session.get("state")},
            )
        artifacts = session.get("artifacts", {})
        if kind == "change":
            record = self.load_bound_record("prepared-change", session_id, subject_hash)
            manifest = record.get("change_manifest")
            if not isinstance(manifest, dict):
                raise AgentError(
                    "BTAG-APPROVAL-RECORD",
                    "prepared change record has no canonical manifest",
                )
            expected_bindings = {
                "artifact_hash": manifest.get("artifact_hash"),
                "artifact_record_hash": manifest.get("artifact_record_hash"),
                "change_manifest_hash": manifest.get("manifest_hash"),
                "dataset_hash": manifest.get("dataset_manifest_hash"),
                "dataset_id": manifest.get("dataset_id"),
                "session_id": manifest.get("session_id"),
                "spec_hash": manifest.get("spec_hash"),
                "validation_token_hash": manifest.get("validation_token_hash"),
                "validation_token_id": manifest.get("validation_token_id"),
            }
            expected_session = {
                "artifact_hash": manifest.get("artifact_hash"),
                "artifact_record_hash": manifest.get("artifact_record_hash"),
                "approved_spec_hash": manifest.get("spec_hash"),
                "change_manifest_hash": manifest.get("manifest_hash"),
                "dataset_id": manifest.get("dataset_id"),
                "dataset_manifest_hash": manifest.get("dataset_manifest_hash"),
                "validation_token_hash": manifest.get("validation_token_hash"),
                "validation_token_id": manifest.get("validation_token_id"),
            }
            if (
                manifest.get("manifest_hash") != subject_hash
                or record.get("validation_token_hash") != manifest.get("validation_token_hash")
                or any(bindings.get(key) != value for key, value in expected_bindings.items())
                or any(artifacts.get(key) != value for key, value in expected_session.items())
            ):
                raise AgentError(
                    "BTAG-APPROVAL-BINDING",
                    "change approval does not match the signed prepared change and session",
                )
            return

        applied_hash = bindings["applied_artifact_hash"]
        record = self.load_bound_record("applied-artifact", session_id, applied_hash)
        applied = record.get("applied_artifact")
        if not isinstance(applied, dict):
            raise AgentError(
                "BTAG-APPROVAL-RECORD",
                "applied artifact record has no canonical artifact",
            )
        expected_bindings = {
            "applied_artifact_hash": applied.get("applied_artifact_hash"),
            "applied_record_hash": record.get("record_hash"),
            "artifact_hash": applied.get("artifact_hash"),
            "artifact_record_hash": applied.get("artifact_record_hash"),
            "change_manifest_hash": applied.get("change_manifest_hash"),
            "dataset_hash": applied.get("dataset_manifest_hash"),
            "dataset_id": applied.get("dataset_id"),
            "mode": bindings.get("mode"),
            "session_id": applied.get("session_id"),
            "spec_hash": applied.get("spec_hash"),
            "validation_token_hash": applied.get("validation_token_hash"),
            "validation_token_id": applied.get("validation_token_id"),
        }
        expected_session = {
            "applied_artifact_hash": applied.get("applied_artifact_hash"),
            "applied_record_hash": record.get("record_hash"),
            "artifact_hash": applied.get("artifact_hash"),
            "artifact_record_hash": applied.get("artifact_record_hash"),
            "approved_spec_hash": applied.get("spec_hash"),
            "change_manifest_hash": applied.get("change_manifest_hash"),
            "dataset_id": applied.get("dataset_id"),
            "dataset_manifest_hash": applied.get("dataset_manifest_hash"),
            "validation_token_hash": applied.get("validation_token_hash"),
            "validation_token_id": applied.get("validation_token_id"),
        }
        expected_subject = hash_object(
            {
                "applied_artifact_hash": applied.get("applied_artifact_hash"),
                "dataset_manifest_hash": applied.get("dataset_manifest_hash"),
                "validation_token_id": applied.get("validation_token_id"),
                "mode": bindings.get("mode"),
                "profile": "controlled-runner-v1",
            }
        )
        if (
            expected_subject != subject_hash
            or any(bindings.get(key) != value for key, value in expected_bindings.items())
            or any(artifacts.get(key) != value for key, value in expected_session.items())
        ):
            raise AgentError(
                "BTAG-APPROVAL-BINDING",
                "run approval does not match the signed applied artifact and session",
            )

    @contextmanager
    def _approval_lock(self, request_id: str) -> Iterator[None]:
        if not APPROVAL_REQUEST_RE.fullmatch(request_id):
            raise AgentError("BTAG-APPROVAL-ID", "approval request ID is malformed")
        lock_path = self.approval_root / f"{request_id}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise AgentError(
                "BTAG-APPROVAL-BUSY", "approval request is already being updated"
            ) from exc
        try:
            os.close(descriptor)
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def _approval_path(self, request_id: str) -> Path:
        if not APPROVAL_REQUEST_RE.fullmatch(request_id):
            raise AgentError("BTAG-APPROVAL-ID", "approval request ID is malformed")
        return self.approval_root / f"{request_id}.json"

    @staticmethod
    def _validate_bindings(kind: str, bindings: Dict[str, str]) -> None:
        if kind not in TOKEN_KINDS:
            raise AgentError("BTAG-TOKEN-KIND", "token kind is not allowlisted")
        missing = REQUIRED_BINDINGS[kind] - set(bindings)
        if missing:
            raise AgentError(
                "BTAG-TOKEN-BINDING",
                "required token bindings are missing",
                details={"missing": sorted(missing)},
            )

    def issue_validation(
        self,
        subject_hash: str,
        bindings: Dict[str, str],
        *,
        ttl_seconds: int = 900,
    ) -> Dict[str, Any]:
        if ttl_seconds < 1 or ttl_seconds > 3600:
            raise AgentError("BTAG-TOKEN-TTL", "token TTL must be between 1 and 3600 seconds")
        self._validate_bindings("validation", bindings)
        now = int(time.time())
        payload: Dict[str, Any] = {
            "schema_version": "action-token-v1",
            "token_id": f"tok-{secrets.token_hex(12)}",
            "kind": "validation",
            "subject_hash": subject_hash,
            "bindings": dict(sorted(bindings.items())),
            "issuer": "deterministic-validator",
            "issued_at": now,
            "expires_at": now + ttl_seconds,
        }
        payload["signature"] = self._signature(payload)
        return payload

    def issue(
        self,
        kind: str,
        subject_hash: str,
        bindings: Dict[str, str],
        *,
        approval: str,
        ttl_seconds: int = 900,
    ) -> Dict[str, Any]:
        """Compatibility shim restricted to deterministic validation tokens.

        Action tokens must come from ``prepare_approval`` then ``grant_approval``;
        accepting a caller-provided label for change/run was not an approval boundary.
        """

        if kind != "validation" or approval != "validator":
            raise AgentError(
                "BTAG-APPROVAL-REQUIRED",
                "change and run tokens require a persisted local approval request",
            )
        return self.issue_validation(subject_hash, bindings, ttl_seconds=ttl_seconds)

    def prepare_approval(
        self,
        kind: str,
        subject_hash: str,
        bindings: Dict[str, str],
        *,
        ttl_seconds: int = 900,
    ) -> Dict[str, Any]:
        if kind not in ACTION_TOKEN_KINDS:
            raise AgentError(
                "BTAG-APPROVAL-KIND", "only change or run actions may request approval"
            )
        if ttl_seconds < 1 or ttl_seconds > 3600:
            raise AgentError("BTAG-TOKEN-TTL", "token TTL must be between 1 and 3600 seconds")
        normalized_bindings = {str(key): str(value) for key, value in bindings.items()}
        self._validate_bindings(kind, normalized_bindings)
        self._validate_approval_context(kind, subject_hash, normalized_bindings)
        now = int(time.time())
        request: Dict[str, Any] = {
            "schema_version": "approval-request-v1",
            "request_id": f"aprq-{secrets.token_hex(12)}",
            "kind": kind,
            "subject_hash": subject_hash,
            "bindings": dict(sorted(normalized_bindings.items())),
            "state": "PENDING",
            "created_at": now,
            "expires_at": now + ttl_seconds,
        }
        request["request_hash"] = hash_object(request)
        atomic_write_json(
            self._approval_path(request["request_id"]),
            request,
            create_only=True,
        )
        return request

    def grant_approval(
        self,
        request_id: str,
        *,
        approver: str,
        confirmed: bool,
    ) -> Dict[str, Any]:
        if not confirmed:
            raise AgentError(
                "BTAG-APPROVAL-CONFIRM", "local approval requires explicit confirmation"
            )
        if not approver.strip():
            raise AgentError("BTAG-APPROVAL-ACTOR", "approver identity is required")
        path = self._approval_path(request_id)
        with self._approval_lock(request_id):
            if not path.is_file():
                raise AgentError("BTAG-APPROVAL-NOT-FOUND", "approval request does not exist")
            request = read_json(path)
            portable = {key: value for key, value in request.items() if key != "request_hash"}
            if hash_object(portable) != request.get("request_hash"):
                raise AgentError("BTAG-APPROVAL-HASH", "approval request hash is invalid")
            if request.get("state") != "PENDING":
                raise AgentError("BTAG-APPROVAL-STATE", "approval request is no longer pending")
            bindings = request.get("bindings")
            if not isinstance(bindings, dict):
                raise AgentError("BTAG-APPROVAL-BINDING", "approval bindings are malformed")
            normalized_bindings = {str(key): str(value) for key, value in bindings.items()}
            self._validate_bindings(str(request.get("kind")), normalized_bindings)
            self._validate_approval_context(
                str(request.get("kind")),
                str(request.get("subject_hash")),
                normalized_bindings,
            )
            now = int(time.time())
            if int(request.get("expires_at", 0)) < now:
                request["state"] = "EXPIRED"
                request["expired_at"] = now
                request["request_hash"] = hash_object(
                    {key: value for key, value in request.items() if key != "request_hash"}
                )
                atomic_write_json(path, request)
                raise AgentError("BTAG-APPROVAL-EXPIRED", "approval request has expired")
            approval_id = f"approval-{secrets.token_hex(12)}"
            token: Dict[str, Any] = {
                "schema_version": "action-token-v1",
                "token_id": f"tok-{secrets.token_hex(12)}",
                "kind": request["kind"],
                "subject_hash": request["subject_hash"],
                "bindings": request["bindings"],
                "approval_request_id": request_id,
                "approval_id": approval_id,
                "approver_hash": hash_object({"approver": approver.strip()}),
                "issued_at": now,
                "expires_at": request["expires_at"],
            }
            token["signature"] = self._signature(token)
            request.update(
                {
                    "state": "ISSUED",
                    "approval_id": approval_id,
                    "approver_hash": token["approver_hash"],
                    "token_id": token["token_id"],
                    "token_hash": hash_object(token),
                    "token": token,
                    "approved_at": now,
                }
            )
            request["request_hash"] = hash_object(
                {key: value for key, value in request.items() if key != "request_hash"}
            )
            atomic_write_json(path, request)
            if request["kind"] == "run":
                from .sessions import SessionStore

                try:
                    SessionStore(self.state_root).transition(
                        request["bindings"]["session_id"],
                        "RUN_APPROVED",
                        "run-approve",
                        {
                            "approval_request": request["request_hash"],
                            "run_subject": request["subject_hash"],
                        },
                        approval_token_id=token["token_id"],
                        effect_references={"run_approval_id": approval_id},
                    )
                except AgentError:
                    request["state"] = "REVOKED"
                    request["revoked_at"] = int(time.time())
                    request["request_hash"] = hash_object(
                        {key: value for key, value in request.items() if key != "request_hash"}
                    )
                    atomic_write_json(path, request)
                    raise
            return {
                "schema_version": "approval-grant-v1",
                "approval_id": approval_id,
                "request_id": request_id,
                "token": token,
            }

    def _action_record(self, token: Dict[str, Any]) -> Dict[str, Any]:
        request_id = token.get("approval_request_id")
        if not isinstance(request_id, str):
            raise AgentError(
                "BTAG-APPROVAL-REQUIRED", "action token has no persisted approval request"
            )
        path = self._approval_path(request_id)
        if not path.is_file():
            raise AgentError("BTAG-APPROVAL-NOT-FOUND", "persisted approval record does not exist")
        record = read_json(path)
        portable = {key: value for key, value in record.items() if key != "request_hash"}
        if hash_object(portable) != record.get("request_hash"):
            raise AgentError("BTAG-APPROVAL-HASH", "approval record hash is invalid")
        if record.get("token_hash") != hash_object(token):
            raise AgentError("BTAG-APPROVAL-TOKEN", "token does not match its approval record")
        if record.get("token") != token:
            raise AgentError("BTAG-APPROVAL-TOKEN", "persisted token bytes do not match")
        return record

    def verify(
        self,
        token: Dict[str, Any],
        *,
        kind: str,
        subject_hash: str,
        required_bindings: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(token, dict):
            raise AgentError("BTAG-TOKEN-TYPE", "token must be an object")
        payload = {key: value for key, value in token.items() if key != "signature"}
        signature = token.get("signature")
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, self._signature(payload)
        ):
            raise AgentError("BTAG-TOKEN-SIGNATURE", "token signature is invalid")
        if token.get("kind") != kind:
            raise AgentError("BTAG-TOKEN-KIND", "token cannot be reused for another action")
        if token.get("subject_hash") != subject_hash:
            raise AgentError("BTAG-TOKEN-BINDING", "token subject hash no longer matches")
        if int(token.get("expires_at", 0)) < int(time.time()):
            raise AgentError("BTAG-TOKEN-EXPIRED", "token has expired")
        bindings = token.get("bindings", {})
        for key, expected in (required_bindings or {}).items():
            if bindings.get(key) != expected:
                raise AgentError("BTAG-TOKEN-BINDING", "token context no longer matches")
        if kind in ACTION_TOKEN_KINDS:
            record = self._action_record(token)
            if record.get("kind") != kind or record.get("subject_hash") != subject_hash:
                raise AgentError(
                    "BTAG-APPROVAL-BINDING", "approval record no longer matches the action"
                )
            if record.get("state") not in {"ISSUED", "CONSUMED"}:
                raise AgentError("BTAG-APPROVAL-STATE", "approval is not usable")
        return token

    def require_issued(self, token: Dict[str, Any]) -> None:
        record = self._action_record(token)
        if record.get("state") != "ISSUED":
            raise AgentError("BTAG-TOKEN-CONSUMED", "action token was already consumed or revoked")

    def consume(self, token: Dict[str, Any], *, effect_id: str) -> Dict[str, Any]:
        if not EFFECT_ID_RE.fullmatch(effect_id):
            raise AgentError("BTAG-TOKEN-EFFECT", "effect ID must be a SHA-256 hash")
        request_id = token.get("approval_request_id")
        if not isinstance(request_id, str):
            raise AgentError(
                "BTAG-APPROVAL-REQUIRED", "action token has no persisted approval request"
            )
        path = self._approval_path(request_id)
        with self._approval_lock(request_id):
            record = self._action_record(token)
            if record.get("state") == "CONSUMED":
                if record.get("effect_id") == effect_id:
                    return record
                raise AgentError(
                    "BTAG-TOKEN-CONSUMED",
                    "action token was already consumed by another effect",
                )
            if record.get("state") != "ISSUED":
                raise AgentError(
                    "BTAG-TOKEN-CONSUMED", "action token was already consumed or revoked"
                )
            now = int(time.time())
            if int(record.get("expires_at", 0)) < now:
                record["state"] = "EXPIRED"
                record["expired_at"] = now
                record["request_hash"] = hash_object(
                    {key: value for key, value in record.items() if key != "request_hash"}
                )
                atomic_write_json(path, record)
                raise AgentError("BTAG-TOKEN-EXPIRED", "action token has expired")
            record.update(
                {
                    "state": "CONSUMED",
                    "consumed_at": now,
                    "effect_id": effect_id,
                }
            )
            record["request_hash"] = hash_object(
                {key: value for key, value in record.items() if key != "request_hash"}
            )
            atomic_write_json(path, record)
            return record
