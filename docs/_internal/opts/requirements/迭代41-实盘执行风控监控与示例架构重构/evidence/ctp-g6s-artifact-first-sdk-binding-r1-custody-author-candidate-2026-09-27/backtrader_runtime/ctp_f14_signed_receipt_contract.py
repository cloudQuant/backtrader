"""Offline, non-authorizing verifier for a versioned F14 receipt wire contract.

This module deliberately stops before external admission.  It has no network
client, CTP query adapter, SQLite lease adapter, executor, or implementation of
``CtpF14ExternalAdmissionAuthority``.  A valid signature proves only that the
injected verifier accepts the exact bytes under an injected issuer/key pin; it
does not prove that a service controls all account writers or that a claimed
snapshot is true.  The observation returned here cannot be used as an action
admission handle.

The in-memory replay cache is process-local test/diagnostic state.  The optional
SQLite observation fence is for a host-local file only; its directory ACL,
owner, and filesystem identity are not deployment-verified.  Neither mechanism
is a durable service dedupe ledger, cross-host fence, or substitute for a real
account actor that owns credentials/session and performs the final dispatch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol, Union


_RECEIPT_SCHEMA_VERSION = "backtrader.ctp_f14.authority_receipt.v1"
_REQUIRED_COVERAGE = ("account_funds", "open_orders", "positions", "trades")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")  # Ed25519 signature, hex encoded
_MAX_WIRE_BYTES = 32 * 1024
_MAX_TTL_SECONDS = 30.0


class CtpF14ReceiptContractError(ValueError):
    """Redacted, fail-closed rejection from the offline receipt contract."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


def _reject(reason: str) -> None:
    raise CtpF14ReceiptContractError(reason)


def _id(value: object, name: str) -> str:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        _reject("invalid_" + name)
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or not _DIGEST_RE.fullmatch(value):
        _reject("invalid_" + name)
    return value


def _is_finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        _reject("invalid_canonical_receipt")
    raise AssertionError("unreachable")


def _no_duplicate_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _reject("duplicate_receipt_field")
        result[key] = value
    return result


@dataclass(frozen=True)
class CtpF14TrustedIssuerKey:
    """Code/deployment-owned issuer, key and audience pin for an offline verifier."""

    issuer_id: str
    key_id: str
    audience: str
    public_key_sha256: str

    def __post_init__(self) -> None:
        _id(self.issuer_id, "issuer_id")
        _id(self.key_id, "key_id")
        _id(self.audience, "audience")
        _digest(self.public_key_sha256, "public_key_sha256")


@dataclass(frozen=True)
class CtpF14ReceiptTrustPolicy:
    """Explicit trust pins; there is intentionally no permissive default."""

    trusted_keys: tuple[CtpF14TrustedIssuerKey, ...]
    max_ttl_seconds: float = _MAX_TTL_SECONDS

    def __post_init__(self) -> None:
        if type(self.trusted_keys) is not tuple or not self.trusted_keys:
            _reject("trusted_issuer_policy_required")
        if any(type(item) is not CtpF14TrustedIssuerKey for item in self.trusted_keys):
            _reject("trusted_issuer_policy_invalid")
        keys = tuple((item.issuer_id, item.key_id, item.audience) for item in self.trusted_keys)
        if len(set(keys)) != len(keys):
            _reject("duplicate_trusted_issuer_key")
        if (
            type(self.max_ttl_seconds) not in (int, float)
            or not _is_finite_number(self.max_ttl_seconds)
            or not 0 < self.max_ttl_seconds <= _MAX_TTL_SECONDS
        ):
            _reject("receipt_ttl_policy_invalid")

    def find(self, issuer_id: str, key_id: str, audience: str) -> CtpF14TrustedIssuerKey:
        for pin in self.trusted_keys:
            if (pin.issuer_id, pin.key_id, pin.audience) == (issuer_id, key_id, audience):
                return pin
        _reject("untrusted_receipt_issuer_or_key")


class CtpF14Ed25519Verifier(Protocol):
    """Injected verifier interface; the module includes a pinned cryptography adapter."""

    def verify_ed25519(
        self, pin: CtpF14TrustedIssuerKey, canonical_payload: bytes, signature: bytes
    ) -> bool:
        """Return literal ``True`` only when this exact payload verifies under the pin."""


class CtpF14PinnedEd25519Verifier:
    """Verify Ed25519 receipt signatures against an injected pinned-key resolver.

    The resolver must return raw 32-byte Ed25519 public-key bytes for the exact
    issuer/key pin.  This adapter verifies the SHA-256 fingerprint before the
    signature.  It does not discover or trust issuers, fetch keys, or grant
    admission; the caller still supplies the code-owned trust policy and this
    verifier still returns only a receipt-shape observation through the public
    contract function.
    """

    def __init__(self, public_key_resolver: Callable[[CtpF14TrustedIssuerKey], bytes]) -> None:
        if not callable(public_key_resolver):
            _reject("receipt_public_key_resolver_required")
        self._public_key_resolver = public_key_resolver

    def verify_ed25519(
        self, pin: CtpF14TrustedIssuerKey, canonical_payload: bytes, signature: bytes
    ) -> bool:
        if (
            type(pin) is not CtpF14TrustedIssuerKey
            or type(canonical_payload) is not bytes
            or type(signature) is not bytes
            or len(signature) != 64
        ):
            return False
        try:
            public_key_bytes = self._public_key_resolver(pin)
        except Exception:
            return False
        if type(public_key_bytes) is not bytes or len(public_key_bytes) != 32:
            return False
        key_fingerprint = hashlib.sha256(public_key_bytes).hexdigest()
        if not hmac.compare_digest(key_fingerprint, pin.public_key_sha256):
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature, canonical_payload
            )
        except Exception:
            return False
        return True


@dataclass(frozen=True)
class CtpF14ReceiptContractObservation:
    """Non-authorizing receipt-shape observation; never an admission or dispatch permit."""

    receipt_digest: str
    request_digest: str
    issuer_id: str
    key_id: str
    claim_id: str
    account_fingerprint_sha256: str
    scope_digest: str
    action_id: str
    action_kind: str
    action_digest: str
    fence_id: str
    fence_epoch: int
    snapshot_id: str
    snapshot_version: str
    snapshot_digest: str
    snapshot_coverage: tuple[str, ...]
    issued_at_utc: float
    expires_at_utc: float


class CtpF14LocalReceiptObservationCache:
    """Process-local replay/epoch regression guard for offline contract tests only.

    A restart clears this state and separate instances do not coordinate.  It
    cannot reject a replay at the service or provider boundary.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claims: set[tuple[str, str]] = set()
        self._nonces: set[tuple[str, str]] = set()
        self._actions: set[tuple[str, str]] = set()
        self._receipts: set[tuple[str, str]] = set()
        self._fence_snapshots: set[tuple[str, str, int, str, str, str]] = set()
        self._highest_epoch: dict[str, int] = {}

    def observe_once(
        self,
        *,
        account_fingerprint_sha256: str,
        issuer_id: str,
        claim_id: str,
        nonce: str,
        action_id: str,
        request_digest: str,
        fence_epoch: int,
        fence_id: str,
        snapshot_id: str,
        snapshot_version: str,
        receipt_digest: str,
    ) -> None:
        claim_key = (issuer_id, claim_id)
        nonce_key = (issuer_id, nonce)
        action_key = (account_fingerprint_sha256, action_id)
        receipt_key = (issuer_id, receipt_digest)
        fence_snapshot_key = (
            account_fingerprint_sha256,
            fence_id,
            fence_epoch,
            snapshot_id,
            snapshot_version,
            action_id,
        )
        with self._lock:
            highest = self._highest_epoch.get(account_fingerprint_sha256, 0)
            if fence_epoch < highest:
                _reject("fence_epoch_rollback")
            if (
                claim_key in self._claims
                or nonce_key in self._nonces
                or receipt_key in self._receipts
                or fence_snapshot_key in self._fence_snapshots
            ):
                _reject("receipt_replay")
            if action_key in self._actions:
                _reject("action_replay")
            self._claims.add(claim_key)
            self._nonces.add(nonce_key)
            self._actions.add(action_key)
            self._receipts.add(receipt_key)
            self._fence_snapshots.add(fence_snapshot_key)
            self._highest_epoch[account_fingerprint_sha256] = max(highest, fence_epoch)


class CtpF14HostLocalSqliteObservationFence:
    """Persistent replay fence for receipt observations on one local host.

    The file must reside on a host-local filesystem. UNC and Windows mapped
    network drives are rejected where detectable. Database directory ACL,
    owner, hard-link identity and non-Windows network-mount status are not
    verified, so deployments must protect the file and this class is not a
    production or cross-host fencing guarantee. The file stores opaque
    fingerprints, IDs and digests only; it never stores credentials or receipt
    payloads.
    """

    _BUSY_TIMEOUT_SECONDS = 0.5
    _SCHEMA_VERSION = "1"
    _EXPECTED_COLUMNS = {
        "contract_meta": ("key", "value"),
        "observed_receipts": (
            "account_fingerprint_sha256",
            "action_id",
            "request_digest",
            "issuer_id",
            "claim_id",
            "nonce",
            "fence_id",
            "fence_epoch",
            "snapshot_id",
            "snapshot_version",
            "receipt_digest",
        ),
        "account_fence_epochs": ("account_fingerprint_sha256", "highest_epoch"),
    }
    _EXPECTED_UNIQUE_KEYS = {
        "contract_meta": {("key",)},
        "observed_receipts": {
            ("account_fingerprint_sha256", "action_id"),
            ("issuer_id", "claim_id"),
            ("issuer_id", "nonce"),
            ("receipt_digest",),
            (
                "account_fingerprint_sha256",
                "fence_id",
                "fence_epoch",
                "snapshot_id",
                "snapshot_version",
                "action_id",
            ),
        },
        "account_fence_epochs": {("account_fingerprint_sha256",)},
    }

    def __init__(self, database_path: Union[str, os.PathLike]) -> None:
        try:
            raw_path = os.fspath(database_path)
        except Exception:
            _reject("local_observation_database_path_invalid")
        if (
            type(raw_path) is not str
            or not raw_path
            or raw_path.lower().startswith("file:")
            or raw_path.startswith(("\\\\", "//"))
        ):
            _reject("local_observation_database_path_invalid")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            _reject("local_observation_database_path_must_be_absolute")
        self._check_local_path(path)
        self._path = str(path.resolve(strict=False))
        self._initialize()

    @staticmethod
    def _check_local_path(path: Path) -> None:
        resolved = path.resolve(strict=False)
        if str(resolved).startswith(("\\\\", "//")):
            _reject("local_observation_database_remote_path_forbidden")
        if os.name == "nt":
            try:
                import ctypes

                drive_root = path.anchor
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_root)
            except Exception:
                _reject("local_observation_database_volume_unverified")
            if drive_type == 4:
                _reject("local_observation_database_remote_path_forbidden")
            if drive_type not in (2, 3, 6):
                _reject("local_observation_database_volume_unverified")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=self._BUSY_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 500")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @classmethod
    def _create_schema(cls, connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE contract_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            """CREATE TABLE observed_receipts (
                account_fingerprint_sha256 TEXT NOT NULL,
                action_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                issuer_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                fence_id TEXT NOT NULL,
                fence_epoch INTEGER NOT NULL,
                snapshot_id TEXT NOT NULL,
                snapshot_version TEXT NOT NULL,
                receipt_digest TEXT NOT NULL,
                PRIMARY KEY (account_fingerprint_sha256, action_id),
                UNIQUE (issuer_id, claim_id),
                UNIQUE (issuer_id, nonce),
                UNIQUE (receipt_digest),
                UNIQUE (
                    account_fingerprint_sha256,
                    fence_id,
                    fence_epoch,
                    snapshot_id,
                    snapshot_version,
                    action_id
                )
            )"""
        )
        connection.execute(
            """CREATE TABLE account_fence_epochs (
                account_fingerprint_sha256 TEXT PRIMARY KEY,
                highest_epoch INTEGER NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO contract_meta (key, value) VALUES (?, ?)",
            ("schema_version", cls._SCHEMA_VERSION),
        )

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            _reject("persistent_observation_fence_corrupt")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != set(cls._EXPECTED_COLUMNS):
            _reject("persistent_observation_fence_schema_invalid")
        for table, expected_columns in cls._EXPECTED_COLUMNS.items():
            columns = tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")'))
            if columns != expected_columns:
                _reject("persistent_observation_fence_schema_invalid")
            unique_keys: set[tuple[str, ...]] = set()
            indexes = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
            for index in indexes:
                if index[2] != 1:
                    continue
                index_name = index[1].replace('"', '""')
                index_columns = tuple(
                    row[2] for row in connection.execute(f'PRAGMA index_info("{index_name}")')
                )
                unique_keys.add(index_columns)
            if unique_keys != cls._EXPECTED_UNIQUE_KEYS[table]:
                _reject("persistent_observation_fence_schema_invalid")
        version = connection.execute(
            "SELECT value FROM contract_meta WHERE key = ?", ("schema_version",)
        ).fetchone()
        if version != (cls._SCHEMA_VERSION,):
            _reject("persistent_observation_fence_schema_version_unsupported")

    def _initialize(self) -> None:
        path = Path(self._path)
        if not path.parent.is_dir():
            _reject("local_observation_database_parent_missing")
        existed = path.exists()
        if existed and (not path.is_file() or path.stat().st_size == 0):
            _reject("persistent_observation_fence_corrupt")
        connection: Optional[sqlite3.Connection] = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if not tables:
                if existed:
                    _reject("persistent_observation_fence_schema_missing")
                self._create_schema(connection)
            self._validate_schema(connection)
            connection.commit()
        except CtpF14ReceiptContractError:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise
        except Exception:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            _reject("persistent_observation_fence_unavailable")
        finally:
            if connection is not None:
                connection.close()

    def observe_once(
        self,
        *,
        account_fingerprint_sha256: str,
        issuer_id: str,
        claim_id: str,
        nonce: str,
        action_id: str,
        request_digest: str,
        fence_epoch: int,
        fence_id: str,
        snapshot_id: str,
        snapshot_version: str,
        receipt_digest: str,
    ) -> None:
        _digest(account_fingerprint_sha256, "account_fingerprint_sha256")
        _id(issuer_id, "issuer_id")
        _id(claim_id, "claim_id")
        _id(nonce, "nonce")
        _id(action_id, "action_id")
        _digest(request_digest, "request_digest")
        if type(fence_epoch) is not int or fence_epoch <= 0:
            _reject("fence_epoch_invalid")
        _id(fence_id, "fence_id")
        _id(snapshot_id, "snapshot_id")
        _id(snapshot_version, "snapshot_version")
        _digest(receipt_digest, "receipt_digest")

        connection: Optional[sqlite3.Connection] = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            self._validate_schema(connection)
            prior = connection.execute(
                "SELECT highest_epoch FROM account_fence_epochs WHERE account_fingerprint_sha256 = ?",
                (account_fingerprint_sha256,),
            ).fetchone()
            if prior is not None and fence_epoch < prior[0]:
                _reject("fence_epoch_rollback")
            connection.execute(
                """INSERT INTO observed_receipts (
                    account_fingerprint_sha256, action_id, request_digest,
                    issuer_id, claim_id, nonce, fence_id, fence_epoch,
                    snapshot_id, snapshot_version, receipt_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_fingerprint_sha256,
                    action_id,
                    request_digest,
                    issuer_id,
                    claim_id,
                    nonce,
                    fence_id,
                    fence_epoch,
                    snapshot_id,
                    snapshot_version,
                    receipt_digest,
                ),
            )
            if prior is None:
                connection.execute(
                    "INSERT INTO account_fence_epochs VALUES (?, ?)",
                    (account_fingerprint_sha256, fence_epoch),
                )
            elif fence_epoch > prior[0]:
                connection.execute(
                    "UPDATE account_fence_epochs SET highest_epoch = ? WHERE account_fingerprint_sha256 = ?",
                    (fence_epoch, account_fingerprint_sha256),
                )
            connection.commit()
        except CtpF14ReceiptContractError:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.IntegrityError:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            _reject("receipt_replay")
        except Exception:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            _reject("persistent_observation_fence_unavailable")
        finally:
            if connection is not None:
                connection.close()


def verify_f14_receipt_contract(
    request: object,
    wire: bytes,
    *,
    trust_policy: CtpF14ReceiptTrustPolicy,
    signature_verifier: CtpF14Ed25519Verifier,
    observation_cache: Union[
        CtpF14LocalReceiptObservationCache, CtpF14HostLocalSqliteObservationFence
    ],
    now_utc: float,
) -> CtpF14ReceiptContractObservation:
    """Verify canonical bytes and request bindings without granting admission.

    The expected request type is imported lazily to keep this receipt contract
    independent of any authority/client implementation.  The only output is a
    shape observation.  There is no ``admitted`` result, external-authority
    implementation, or executor callback in this function.
    """

    from backtrader_runtime.ctp_f14_external_admission import CtpF14ActionRequest

    if type(request) is not CtpF14ActionRequest:
        _reject("f14_action_request_required")
    if type(wire) is not bytes or not 0 < len(wire) <= _MAX_WIRE_BYTES:
        _reject("receipt_wire_invalid")
    if type(trust_policy) is not CtpF14ReceiptTrustPolicy:
        _reject("trusted_issuer_policy_required")
    if not callable(getattr(signature_verifier, "verify_ed25519", None)):
        _reject("receipt_signature_verifier_required")
    if type(observation_cache) not in (
        CtpF14LocalReceiptObservationCache,
        CtpF14HostLocalSqliteObservationFence,
    ):
        _reject("receipt_observation_fence_required")
    if not _is_finite_number(now_utc):
        _reject("receipt_verification_time_invalid")

    try:
        envelope = json.loads(wire.decode("ascii"), object_pairs_hook=_no_duplicate_object_pairs)
    except CtpF14ReceiptContractError:
        raise
    except Exception:
        _reject("receipt_wire_invalid")
    if type(envelope) is not dict or set(envelope) != {"payload", "signature_ed25519_hex"}:
        _reject("receipt_envelope_invalid")
    payload = envelope["payload"]
    if type(payload) is not dict:
        _reject("receipt_payload_invalid")
    if _canonical(envelope) != wire:
        _reject("receipt_wire_not_canonical")
    signature_hex = envelope["signature_ed25519_hex"]
    if type(signature_hex) is not str or not _SIGNATURE_RE.fullmatch(signature_hex):
        _reject("receipt_signature_invalid")
    signature = bytes.fromhex(signature_hex)
    payload_bytes = _canonical(payload)

    expected_fields = {
        "schema_version",
        "issuer_id",
        "key_id",
        "audience",
        "claim_id",
        "nonce",
        "request_digest",
        "account_fingerprint_sha256",
        "scope_digest",
        "action_id",
        "action_kind",
        "action_digest",
        "approval_digest",
        "target_digest",
        "fence_id",
        "fence_epoch",
        "fence_scope_digest",
        "snapshot_id",
        "snapshot_version",
        "snapshot_digest",
        "snapshot_coverage",
        "snapshot_collection_versions",
        "snapshot_pagination_complete",
        "snapshot_account_fingerprint_sha256",
        "snapshot_fence_id",
        "snapshot_fence_epoch",
        "snapshot_trading_day",
        "snapshot_connection_generation",
        "account_writer_exclusive",
        "snapshot_complete",
        "snapshot_consistent",
        "issued_at_utc",
        "expires_at_utc",
    }
    if set(payload) != expected_fields:
        _reject("receipt_payload_fields_invalid")
    if payload["schema_version"] != _RECEIPT_SCHEMA_VERSION:
        _reject("receipt_schema_unsupported")

    issuer_id = _id(payload["issuer_id"], "issuer_id")
    key_id = _id(payload["key_id"], "key_id")
    audience = _id(payload["audience"], "audience")
    pin = trust_policy.find(issuer_id, key_id, audience)
    try:
        verified = signature_verifier.verify_ed25519(pin, payload_bytes, signature)
    except Exception:
        _reject("receipt_signature_verification_unavailable")
    if verified is not True:
        _reject("receipt_signature_invalid")

    # These are signed assertions, not independently established facts.
    claim_id = _id(payload["claim_id"], "claim_id")
    nonce = _id(payload["nonce"], "nonce")
    fence_id = _id(payload["fence_id"], "fence_id")
    snapshot_id = _id(payload["snapshot_id"], "snapshot_id")
    snapshot_version = _id(payload["snapshot_version"], "snapshot_version")
    for name in (
        "request_digest",
        "account_fingerprint_sha256",
        "scope_digest",
        "action_digest",
        "approval_digest",
        "fence_scope_digest",
        "snapshot_digest",
        "snapshot_account_fingerprint_sha256",
    ):
        _digest(payload[name], name)
    if payload["target_digest"] is not None:
        _digest(payload["target_digest"], "target_digest")
    if type(payload["action_kind"]) is not str or payload["action_kind"] not in (
        "SUBMIT",
        "CANCEL",
    ):
        _reject("receipt_action_kind_invalid")
    if (
        type(payload["snapshot_coverage"]) is not list
        or tuple(payload["snapshot_coverage"]) != _REQUIRED_COVERAGE
    ):
        _reject("receipt_snapshot_coverage_incomplete")
    collection_versions = payload["snapshot_collection_versions"]
    pagination_complete = payload["snapshot_pagination_complete"]
    if (
        type(collection_versions) is not dict
        or set(collection_versions) != set(_REQUIRED_COVERAGE)
        or any(value != snapshot_version for value in collection_versions.values())
        or type(pagination_complete) is not dict
        or set(pagination_complete) != set(_REQUIRED_COVERAGE)
        or any(value is not True for value in pagination_complete.values())
    ):
        _reject("receipt_snapshot_partial_or_mixed")
    if (
        type(payload["fence_epoch"]) is not int
        or payload["fence_epoch"] <= 0
        or type(payload["snapshot_fence_epoch"]) is not int
        or payload["snapshot_fence_epoch"] != payload["fence_epoch"]
    ):
        _reject("receipt_fence_epoch_mismatch")
    if (
        type(payload["snapshot_connection_generation"]) is not int
        or payload["snapshot_connection_generation"] <= 0
    ):
        _reject("receipt_snapshot_connection_generation_invalid")
    if (
        payload["account_writer_exclusive"] is not True
        or payload["snapshot_complete"] is not True
        or payload["snapshot_consistent"] is not True
    ):
        _reject("receipt_external_assertions_incomplete")
    if (
        payload["request_digest"] != request.request_digest
        or payload["account_fingerprint_sha256"] != request.account_fingerprint_sha256
        or payload["scope_digest"] != request.scope_digest
        or payload["fence_scope_digest"] != request.scope_digest
        or payload["action_id"] != request.action_id
        or payload["action_kind"] != request.action_kind
        or payload["action_digest"] != request.action_digest
        or payload["approval_digest"] != request.approval_digest
        or payload["target_digest"] != request.target_digest
        or payload["snapshot_account_fingerprint_sha256"] != request.account_fingerprint_sha256
        or payload["snapshot_fence_id"] != fence_id
        or payload["snapshot_trading_day"] != request.session.trading_day
        or payload["snapshot_connection_generation"] != request.session.connection_generation
    ):
        _reject("receipt_request_or_snapshot_binding_mismatch")

    issued_at = payload["issued_at_utc"]
    expires_at = payload["expires_at_utc"]
    if (
        type(issued_at) not in (int, float)
        or type(expires_at) not in (int, float)
        or not _is_finite_number(issued_at)
        or not _is_finite_number(expires_at)
        or issued_at > now_utc
        or expires_at <= now_utc
        or expires_at <= issued_at
        or expires_at - issued_at > trust_policy.max_ttl_seconds
    ):
        _reject("receipt_time_window_invalid")

    observation_cache.observe_once(
        account_fingerprint_sha256=request.account_fingerprint_sha256,
        issuer_id=issuer_id,
        claim_id=claim_id,
        nonce=nonce,
        action_id=request.action_id,
        request_digest=request.request_digest,
        fence_epoch=payload["fence_epoch"],
        fence_id=fence_id,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        receipt_digest=hashlib.sha256(wire).hexdigest(),
    )
    return CtpF14ReceiptContractObservation(
        receipt_digest=hashlib.sha256(wire).hexdigest(),
        request_digest=request.request_digest,
        issuer_id=issuer_id,
        key_id=key_id,
        claim_id=claim_id,
        account_fingerprint_sha256=request.account_fingerprint_sha256,
        scope_digest=request.scope_digest,
        action_id=request.action_id,
        action_kind=request.action_kind,
        action_digest=request.action_digest,
        fence_id=fence_id,
        fence_epoch=payload["fence_epoch"],
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        snapshot_digest=payload["snapshot_digest"],
        snapshot_coverage=_REQUIRED_COVERAGE,
        issued_at_utc=float(issued_at),
        expires_at_utc=float(expires_at),
    )


__all__ = [
    "CtpF14Ed25519Verifier",
    "CtpF14HostLocalSqliteObservationFence",
    "CtpF14LocalReceiptObservationCache",
    "CtpF14PinnedEd25519Verifier",
    "CtpF14ReceiptContractError",
    "CtpF14ReceiptContractObservation",
    "CtpF14ReceiptTrustPolicy",
    "CtpF14TrustedIssuerKey",
    "verify_f14_receipt_contract",
]
