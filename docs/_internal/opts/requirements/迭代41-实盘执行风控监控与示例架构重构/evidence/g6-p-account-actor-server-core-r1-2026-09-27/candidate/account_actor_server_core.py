"""Fake-only durable core for an external CTP account-actor contract.

The module records writer epochs, verified common snapshots, idempotent logical
intents, and transactional dispatch authorizations in SQLite. It performs no
provider or SDK calls. A future service must replace the fake snapshot verifier
with its authenticated source boundary and separately implement dispatch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Optional

from account_actor_port import ActorCommandContextV1

_ACCOUNT_REF = re.compile(r"^ctp-account-ref\.v1:[0-9a-f]{64}$")
_DOMAINS = frozenset({"funds", "orders", "trades", "positions"})
_OPERATIONS = frozenset({"SUBMIT", "CANCEL"})
_SCHEMA_VERSION = 1
_SCHEMA_COLUMNS = {
    "actor_account_writers": (
        "account_ref",
        "epoch",
        "owner_id",
        "token_sha256",
        "state",
        "context_json",
    ),
    "actor_snapshots": (
        "account_ref",
        "snapshot_version",
        "source_id",
        "authority_id",
        "snapshot_digest",
        "proof_hex",
    ),
    "actor_snapshot_domains": (
        "account_ref",
        "snapshot_version",
        "domain",
        "source_id",
        "payload_json",
    ),
    "actor_current_snapshots": ("account_ref", "snapshot_version"),
    "actor_commands": (
        "account_ref",
        "operation",
        "intent_id",
        "command_digest",
        "context_json",
        "payload_json",
        "expected_snapshot_version",
        "writer_epoch",
        "state",
    ),
    "actor_dispatch_outbox": (
        "dispatch_id",
        "account_ref",
        "operation",
        "intent_id",
        "command_digest",
        "writer_epoch",
        "snapshot_version",
    ),
}
_SCHEMA_DDL = {
    "actor_account_writers": (
        "CREATE TABLE actor_account_writers("
        "account_ref TEXT PRIMARY KEY, epoch INTEGER NOT NULL CHECK(epoch > 0),"
        "owner_id TEXT NOT NULL, token_sha256 TEXT NOT NULL,"
        "state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')), context_json TEXT)"
    ),
    "actor_snapshots": (
        "CREATE TABLE actor_snapshots("
        "account_ref TEXT NOT NULL, snapshot_version INTEGER NOT NULL CHECK(snapshot_version > 0),"
        "source_id TEXT NOT NULL, authority_id TEXT NOT NULL, snapshot_digest TEXT NOT NULL,"
        "proof_hex TEXT NOT NULL, PRIMARY KEY(account_ref,snapshot_version))"
    ),
    "actor_snapshot_domains": (
        "CREATE TABLE actor_snapshot_domains("
        "account_ref TEXT NOT NULL, snapshot_version INTEGER NOT NULL, domain TEXT NOT NULL,"
        "source_id TEXT NOT NULL, payload_json TEXT NOT NULL,"
        "PRIMARY KEY(account_ref,snapshot_version,domain),"
        "FOREIGN KEY(account_ref,snapshot_version)"
        " REFERENCES actor_snapshots(account_ref,snapshot_version))"
    ),
    "actor_current_snapshots": (
        "CREATE TABLE actor_current_snapshots("
        "account_ref TEXT PRIMARY KEY, snapshot_version INTEGER NOT NULL,"
        "FOREIGN KEY(account_ref,snapshot_version)"
        " REFERENCES actor_snapshots(account_ref,snapshot_version))"
    ),
    "actor_commands": (
        "CREATE TABLE actor_commands("
        "account_ref TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('SUBMIT','CANCEL')),"
        "intent_id TEXT NOT NULL, command_digest TEXT NOT NULL, context_json TEXT NOT NULL,"
        "payload_json TEXT NOT NULL,"
        "expected_snapshot_version INTEGER NOT NULL, writer_epoch INTEGER NOT NULL,"
        "state TEXT NOT NULL CHECK(state IN ('RESERVED','AUTHORIZED','BLOCKED')),"
        "PRIMARY KEY(account_ref,operation,intent_id))"
    ),
    "actor_dispatch_outbox": (
        "CREATE TABLE actor_dispatch_outbox("
        "dispatch_id INTEGER PRIMARY KEY AUTOINCREMENT, account_ref TEXT NOT NULL,"
        "operation TEXT NOT NULL, intent_id TEXT NOT NULL, command_digest TEXT NOT NULL,"
        "writer_epoch INTEGER NOT NULL, snapshot_version INTEGER NOT NULL,"
        "UNIQUE(account_ref,operation,intent_id),"
        "FOREIGN KEY(account_ref,operation,intent_id)"
        " REFERENCES actor_commands(account_ref,operation,intent_id))"
    ),
}


class ActorServerError(RuntimeError):
    """Fixed-code, fail-closed error from the fake durable service core."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code.replace("_", " "))


@dataclass(frozen=True)
class WriterEpochV1:
    """Opaque local capability returned only after a durable writer claim."""

    account_ref: str
    owner_id: str
    epoch: int
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_account_ref(self.account_ref)
        _require_text(self.owner_id, "owner_id")
        if type(self.epoch) is not int or self.epoch <= 0:
            raise ValueError("epoch must be a positive exact integer")
        if type(self.token) is not str or len(self.token) < 32:
            raise ValueError("token must be nonempty opaque text")


@dataclass(frozen=True)
class SnapshotDomainFactV1:
    """One canonical domain payload from a shared account snapshot."""

    account_ref: str
    snapshot_version: int
    source_id: str
    domain: str
    payload_json: str

    def __post_init__(self) -> None:
        _require_account_ref(self.account_ref)
        if type(self.snapshot_version) is not int or self.snapshot_version <= 0:
            raise ValueError("snapshot_version must be a positive exact integer")
        _require_text(self.source_id, "source_id")
        if type(self.domain) is not str or self.domain not in _DOMAINS:
            raise ValueError("unsupported snapshot domain")
        _require_canonical_object_json(self.payload_json)

    @classmethod
    def from_payload(
        cls,
        *,
        account_ref: str,
        snapshot_version: int,
        source_id: str,
        domain: str,
        payload: dict[str, Any],
    ) -> SnapshotDomainFactV1:
        return cls(
            account_ref=account_ref,
            snapshot_version=snapshot_version,
            source_id=source_id,
            domain=domain,
            payload_json=_canonical_object(payload),
        )


@dataclass(frozen=True)
class AccountSnapshotBundleV1:
    """Exactly four domain facts sharing one account/version/source tuple."""

    account_ref: str
    snapshot_version: int
    source_id: str
    facts: tuple[SnapshotDomainFactV1, ...]

    def __post_init__(self) -> None:
        _require_account_ref(self.account_ref)
        if type(self.snapshot_version) is not int or self.snapshot_version <= 0:
            raise ValueError("snapshot_version must be a positive exact integer")
        _require_text(self.source_id, "source_id")
        if type(self.facts) is not tuple or len(self.facts) != len(_DOMAINS):
            raise ValueError("snapshot must contain exactly four domain facts")
        seen: set[str] = set()
        for fact in self.facts:
            if type(fact) is not SnapshotDomainFactV1:
                raise ValueError("snapshot facts must be exact typed domain facts")
            fact.__post_init__()
            if fact.account_ref != self.account_ref:
                raise ValueError("snapshot domain account mismatch")
            if fact.snapshot_version != self.snapshot_version:
                raise ValueError("snapshot domain version mismatch")
            if fact.source_id != self.source_id:
                raise ValueError("snapshot domain source mismatch")
            if fact.domain in seen:
                raise ValueError("duplicate snapshot domain")
            seen.add(fact.domain)
        if seen != _DOMAINS:
            raise ValueError("snapshot domain set incomplete")

    @property
    def digest(self) -> str:
        self.__post_init__()
        body = {
            "account_ref": self.account_ref,
            "snapshot_version": self.snapshot_version,
            "source_id": self.source_id,
            "facts": [
                {
                    "domain": fact.domain,
                    "payload": json.loads(fact.payload_json),
                }
                for fact in sorted(self.facts, key=lambda item: item.domain)
            ],
        }
        return _sha256(_canonical_json(body))


@dataclass(frozen=True)
class SnapshotAuthorityProofV1:
    """Proof shape returned by the injected snapshot authority port."""

    authority_id: str
    account_ref: str
    snapshot_version: int
    source_id: str
    snapshot_digest: str
    proof_hex: str

    def __post_init__(self) -> None:
        _require_text(self.authority_id, "authority_id")
        _require_account_ref(self.account_ref)
        if type(self.snapshot_version) is not int or self.snapshot_version <= 0:
            raise ValueError("snapshot_version must be a positive exact integer")
        _require_text(self.source_id, "source_id")
        _require_digest(self.snapshot_digest, "snapshot_digest")
        _require_digest(self.proof_hex, "proof_hex")


class FakeSnapshotAuthorityV1:
    """Test-only HMAC verifier; it is not a production trust root or key source."""

    def __init__(self, *, authority_id: str, source_id: str, key: bytes) -> None:
        _require_text(authority_id, "authority_id")
        _require_text(source_id, "source_id")
        if type(key) is not bytes or len(key) < 32:
            raise ValueError("fake test key must contain at least 32 bytes")
        self.authority_id = authority_id
        self.source_id = source_id
        self._key = bytes(key)

    def attest(self, bundle: AccountSnapshotBundleV1) -> SnapshotAuthorityProofV1:
        if type(bundle) is not AccountSnapshotBundleV1:
            raise ActorServerError("snapshot_bundle_type_invalid")
        bundle.__post_init__()
        if bundle.source_id != self.source_id:
            raise ActorServerError("snapshot_source_untrusted")
        digest = bundle.digest
        unsigned = {
            "authority_id": self.authority_id,
            "account_ref": bundle.account_ref,
            "snapshot_version": bundle.snapshot_version,
            "source_id": bundle.source_id,
            "snapshot_digest": digest,
        }
        proof_hex = hmac.new(
            self._key,
            b"fake-account-snapshot-v1\x00" + _canonical_json(unsigned).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SnapshotAuthorityProofV1(
            authority_id=self.authority_id,
            account_ref=bundle.account_ref,
            snapshot_version=bundle.snapshot_version,
            source_id=bundle.source_id,
            snapshot_digest=digest,
            proof_hex=proof_hex,
        )

    def verify(
        self, bundle: AccountSnapshotBundleV1, proof: SnapshotAuthorityProofV1
    ) -> bool:
        if (
            type(bundle) is not AccountSnapshotBundleV1
            or type(proof) is not SnapshotAuthorityProofV1
        ):
            return False
        try:
            bundle.__post_init__()
            proof.__post_init__()
        except (TypeError, ValueError):
            return False
        if (
            proof.authority_id != self.authority_id
            or proof.account_ref != bundle.account_ref
            or proof.snapshot_version != bundle.snapshot_version
            or proof.source_id != bundle.source_id
            or proof.snapshot_digest != bundle.digest
            or bundle.source_id != self.source_id
        ):
            return False
        expected = self.attest(bundle)
        return hmac.compare_digest(proof.proof_hex, expected.proof_hex)


@dataclass(frozen=True)
class AccountActorIntentV1:
    """Logical command; no provider/native identity is accepted here."""

    operation: str
    intent_id: str
    context: ActorCommandContextV1
    payload_json: str

    def __post_init__(self) -> None:
        if type(self.operation) is not str or self.operation not in _OPERATIONS:
            raise ValueError("operation must be SUBMIT or CANCEL")
        _require_text(self.intent_id, "intent_id")
        if type(self.context) is not ActorCommandContextV1:
            raise ValueError("context must be ActorCommandContextV1")
        self.context.__post_init__()
        _require_account_ref(self.context.account_ref)
        _require_canonical_object_json(self.payload_json)

    @classmethod
    def from_payload(
        cls,
        *,
        operation: str,
        intent_id: str,
        context: ActorCommandContextV1,
        payload: dict[str, Any],
    ) -> AccountActorIntentV1:
        return cls(
            operation=operation,
            intent_id=intent_id,
            context=context,
            payload_json=_canonical_object(payload),
        )

    @property
    def command_digest(self) -> str:
        self.__post_init__()
        return _command_digest(
            self.operation,
            self.intent_id,
            _canonical_json(self.context.to_payload()),
            self.payload_json,
        )

    @property
    def context_json(self) -> str:
        self.__post_init__()
        return _canonical_json(self.context.to_payload())


@dataclass(frozen=True)
class DurableCommandV1:
    account_ref: str
    operation: str
    intent_id: str
    command_digest: str
    expected_snapshot_version: int
    writer_epoch: int
    state: str


@dataclass(frozen=True)
class DispatchAuthorizationV1:
    """Durable local outbox acceptance; not a provider or native receipt."""

    account_ref: str
    operation: str
    intent_id: str
    command_digest: str
    writer_epoch: int
    snapshot_version: int
    dispatch_id: int
    state: str = "AUTHORIZED_LOCAL_OUTBOX"


class AccountActorServerCoreV1:
    """SQLite-backed fake service core with no provider/native dispatcher."""

    def __init__(
        self,
        database_path: str,
        *,
        snapshot_authority: Optional[FakeSnapshotAuthorityV1] = None,  # noqa: UP045 - Python 3.8
    ) -> None:
        if type(database_path) is not str or not database_path.strip():
            raise ValueError("database_path must be a nonempty filesystem path")
        if database_path == ":memory:" or database_path.startswith("file:"):
            raise ValueError(
                "durable fake service requires a plain filesystem database"
            )
        self.database_path = os.path.abspath(database_path)
        if (
            snapshot_authority is not None
            and type(snapshot_authority) is not FakeSnapshotAuthorityV1
        ):
            raise ValueError("snapshot_authority must be exact fake authority type")
        self._snapshot_authority = snapshot_authority
        self._local_lock = threading.RLock()
        self._initialize_schema()

    def close(self) -> None:
        """No retained connection; process exit leaves durable claims unchanged."""

    def claim_writer(self, account_ref: str, owner_id: str) -> WriterEpochV1:
        _require_account_ref(account_ref)
        _require_text(owner_id, "owner_id")
        token = secrets.token_urlsafe(40)
        token_hash = _sha256(token)
        with self._local_lock, self._transaction() as cursor:
            row = cursor.execute(
                "SELECT epoch, state FROM actor_account_writers WHERE account_ref=?",
                (account_ref,),
            ).fetchone()
            if row is not None and row[1] == "ACTIVE":
                raise ActorServerError("account_writer_already_claimed")
            epoch = 1 if row is None else _exact_db_int(row[0], "writer epoch") + 1
            if row is None:
                cursor.execute(
                    "INSERT INTO actor_account_writers"
                    "(account_ref, epoch, owner_id, token_sha256, state, context_json)"
                    " VALUES (?, ?, ?, ?, 'ACTIVE', NULL)",
                    (account_ref, epoch, owner_id, token_hash),
                )
            else:
                cursor.execute(
                    "UPDATE actor_account_writers SET epoch=?, owner_id=?, token_sha256=?,"
                    " state='ACTIVE', context_json=NULL WHERE account_ref=? AND state='REVOKED'",
                    (epoch, owner_id, token_hash, account_ref),
                )
                if cursor.rowcount != 1:
                    raise ActorServerError("account_writer_claim_conflict")
        return WriterEpochV1(account_ref, owner_id, epoch, token)

    def bind_session(
        self, writer: WriterEpochV1, context: ActorCommandContextV1
    ) -> None:
        """Bind one exact local session context to this epoch."""

        if type(context) is not ActorCommandContextV1:
            raise ActorServerError("session_context_type_invalid")
        try:
            context.__post_init__()
            _require_account_ref(context.account_ref)
        except (TypeError, ValueError):
            raise ActorServerError("session_context_invalid") from None
        if (
            context.account_ref != writer.account_ref
            or context.actor_epoch != writer.epoch
        ):
            raise ActorServerError("session_context_writer_mismatch")
        context_json = _canonical_json(context.to_payload())
        with self._local_lock, self._transaction() as cursor:
            self._require_writer_cursor(cursor, writer)
            current = self._session_context_json_cursor(cursor, writer.account_ref)
            if current is not None:
                if current != context_json:
                    raise ActorServerError("session_context_already_bound")
                return
            cursor.execute(
                "UPDATE actor_account_writers SET context_json=?"
                " WHERE account_ref=? AND epoch=? AND state='ACTIVE' AND context_json IS NULL",
                (context_json, writer.account_ref, writer.epoch),
            )
            if cursor.rowcount != 1:
                raise ActorServerError("session_context_bind_conflict")

    def revoke_writer(self, writer: WriterEpochV1) -> None:
        with self._local_lock, self._transaction() as cursor:
            self._require_writer_cursor(cursor, writer)
            cursor.execute(
                "UPDATE actor_account_writers SET state='REVOKED'"
                " WHERE account_ref=? AND epoch=? AND owner_id=? AND state='ACTIVE'",
                (writer.account_ref, writer.epoch, writer.owner_id),
            )
            if cursor.rowcount != 1:
                raise ActorServerError("writer_epoch_revocation_conflict")

    def publish_snapshot(
        self, writer: WriterEpochV1, bundle: AccountSnapshotBundleV1
    ) -> SnapshotAuthorityProofV1:
        authority = self._require_snapshot_authority()
        _validate_bundle_type(bundle)
        if bundle.account_ref != writer.account_ref:
            raise ActorServerError("snapshot_account_mismatch")
        proof = authority.attest(bundle)
        if type(proof) is not SnapshotAuthorityProofV1 or not authority.verify(
            bundle, proof
        ):
            raise ActorServerError("snapshot_authority_proof_invalid")
        with self._local_lock, self._transaction() as cursor:
            self._require_writer_cursor(cursor, writer)
            existing = cursor.execute(
                "SELECT source_id, authority_id, snapshot_digest, proof_hex"
                " FROM actor_snapshots WHERE account_ref=? AND snapshot_version=?",
                (bundle.account_ref, bundle.snapshot_version),
            ).fetchone()
            if existing is not None:
                if tuple(existing) == (
                    bundle.source_id,
                    proof.authority_id,
                    proof.snapshot_digest,
                    proof.proof_hex,
                ) and self._snapshot_matches_cursor(
                    cursor, bundle.account_ref, bundle.snapshot_version
                ):
                    return proof
                raise ActorServerError("snapshot_version_conflict")
            current = cursor.execute(
                "SELECT snapshot_version FROM actor_current_snapshots WHERE account_ref=?",
                (bundle.account_ref,),
            ).fetchone()
            if current is not None and bundle.snapshot_version <= current[0]:
                raise ActorServerError("snapshot_version_not_increasing")
            cursor.execute(
                "INSERT INTO actor_snapshots"
                "(account_ref, snapshot_version, source_id, authority_id, snapshot_digest, proof_hex)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    bundle.account_ref,
                    bundle.snapshot_version,
                    bundle.source_id,
                    proof.authority_id,
                    proof.snapshot_digest,
                    proof.proof_hex,
                ),
            )
            cursor.executemany(
                "INSERT INTO actor_snapshot_domains"
                "(account_ref, snapshot_version, domain, source_id, payload_json)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        bundle.account_ref,
                        bundle.snapshot_version,
                        fact.domain,
                        fact.source_id,
                        fact.payload_json,
                    )
                    for fact in bundle.facts
                ],
            )
            cursor.execute(
                "INSERT INTO actor_current_snapshots(account_ref, snapshot_version) VALUES (?, ?)"
                " ON CONFLICT(account_ref) DO UPDATE SET snapshot_version=excluded.snapshot_version",
                (bundle.account_ref, bundle.snapshot_version),
            )
        return proof

    def reserve_intent(
        self,
        writer: WriterEpochV1,
        intent: AccountActorIntentV1,
        *,
        expected_snapshot_version: int,
    ) -> DurableCommandV1:
        _validate_intent_type(intent)
        if type(expected_snapshot_version) is not int or expected_snapshot_version <= 0:
            raise ActorServerError("snapshot_version_invalid")
        self._require_context_for_writer(writer, intent)
        with self._local_lock, self._transaction() as cursor:
            self._require_writer_cursor(cursor, writer)
            self._require_session_context_cursor(cursor, writer, intent.context)
            self._require_current_verified_snapshot_cursor(
                cursor, intent.context.account_ref, expected_snapshot_version
            )
            row = cursor.execute(
                "SELECT command_digest, context_json, payload_json, expected_snapshot_version,"
                " writer_epoch, state"
                " FROM actor_commands WHERE account_ref=? AND operation=? AND intent_id=?",
                (intent.context.account_ref, intent.operation, intent.intent_id),
            ).fetchone()
            if row is not None:
                if (
                    row[0] != intent.command_digest
                    or row[3] != expected_snapshot_version
                    or not _stored_command_is_valid(
                        account_ref=intent.context.account_ref,
                        operation=intent.operation,
                        intent_id=intent.intent_id,
                        command_digest=row[0],
                        context_json=row[1],
                        payload_json=row[2],
                        expected_epoch=writer.epoch,
                        expected_context_json=self._session_context_json_cursor(
                            cursor, writer.account_ref
                        ),
                    )
                ):
                    raise ActorServerError("intent_replay_conflict")
                return DurableCommandV1(
                    intent.context.account_ref,
                    intent.operation,
                    intent.intent_id,
                    row[0],
                    row[3],
                    row[4],
                    row[5],
                )
            cursor.execute(
                "INSERT INTO actor_commands"
                "(account_ref, operation, intent_id, command_digest, context_json, payload_json,"
                " expected_snapshot_version, writer_epoch, state)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED')",
                (
                    intent.context.account_ref,
                    intent.operation,
                    intent.intent_id,
                    intent.command_digest,
                    intent.context_json,
                    intent.payload_json,
                    expected_snapshot_version,
                    writer.epoch,
                ),
            )
            return DurableCommandV1(
                intent.context.account_ref,
                intent.operation,
                intent.intent_id,
                intent.command_digest,
                expected_snapshot_version,
                writer.epoch,
                "RESERVED",
            )

    def authorize_dispatch(
        self,
        writer: WriterEpochV1,
        *,
        operation: str,
        intent_id: str,
    ) -> DispatchAuthorizationV1:
        """Atomically recheck epoch + snapshot, then append local outbox row.

        This records permission to dispatch inside the fake service's durable
        boundary. It deliberately performs no external provider or SDK call.
        """

        if type(operation) is not str or operation not in _OPERATIONS:
            raise ActorServerError("operation_invalid")
        _require_text(intent_id, "intent_id")
        authority = self._require_snapshot_authority()
        with self._local_lock, self._transaction() as cursor:
            self._require_writer_cursor(cursor, writer)
            expected_context_json = self._session_context_json_cursor(
                cursor, writer.account_ref
            )
            if expected_context_json is None:
                raise ActorServerError("writer_session_unbound")
            row = cursor.execute(
                "SELECT command_digest, context_json, payload_json, expected_snapshot_version,"
                " writer_epoch, state"
                " FROM actor_commands WHERE account_ref=? AND operation=? AND intent_id=?",
                (writer.account_ref, operation, intent_id),
            ).fetchone()
            if row is None:
                raise ActorServerError("intent_not_reserved")
            (
                command_digest,
                context_json,
                payload_json,
                snapshot_version,
                command_epoch,
                state,
            ) = row
            if command_epoch != writer.epoch:
                raise ActorServerError("command_writer_epoch_mismatch")
            if not _stored_command_is_valid(
                account_ref=writer.account_ref,
                operation=operation,
                intent_id=intent_id,
                command_digest=command_digest,
                context_json=context_json,
                payload_json=payload_json,
                expected_epoch=writer.epoch,
                expected_context_json=expected_context_json,
            ):
                raise ActorServerError("command_binding_readback_mismatch")
            if state == "AUTHORIZED":
                outbox = cursor.execute(
                    "SELECT dispatch_id, command_digest, writer_epoch, snapshot_version"
                    " FROM actor_dispatch_outbox WHERE account_ref=? AND operation=? AND intent_id=?",
                    (writer.account_ref, operation, intent_id),
                ).fetchone()
                if outbox is None or tuple(outbox[1:]) != (
                    command_digest,
                    writer.epoch,
                    snapshot_version,
                ):
                    raise ActorServerError("dispatch_outbox_readback_mismatch")
                return DispatchAuthorizationV1(
                    writer.account_ref,
                    operation,
                    intent_id,
                    command_digest,
                    writer.epoch,
                    snapshot_version,
                    _exact_db_int(outbox[0], "dispatch_id"),
                )
            if state != "RESERVED":
                raise ActorServerError("intent_state_not_dispatchable")
            self._require_current_verified_snapshot_cursor(
                cursor,
                writer.account_ref,
                snapshot_version,
                authority=authority,
            )
            cursor.execute(
                "INSERT INTO actor_dispatch_outbox"
                "(account_ref, operation, intent_id, command_digest, writer_epoch, snapshot_version)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    writer.account_ref,
                    operation,
                    intent_id,
                    command_digest,
                    writer.epoch,
                    snapshot_version,
                ),
            )
            dispatch_id = _exact_db_int(cursor.lastrowid, "dispatch_id")
            cursor.execute(
                "UPDATE actor_commands SET state='AUTHORIZED'"
                " WHERE account_ref=? AND operation=? AND intent_id=? AND state='RESERVED'",
                (writer.account_ref, operation, intent_id),
            )
            if cursor.rowcount != 1:
                raise ActorServerError("intent_authorization_conflict")
            return DispatchAuthorizationV1(
                writer.account_ref,
                operation,
                intent_id,
                command_digest,
                writer.epoch,
                snapshot_version,
                dispatch_id,
            )

    def count_dispatch_rows(self, account_ref: str) -> int:
        _require_account_ref(account_ref)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM actor_dispatch_outbox WHERE account_ref=?",
                (account_ref,),
            ).fetchone()
            return _exact_db_int(row[0], "outbox count")

    def read_writer_epoch(self, account_ref: str) -> tuple[int, str, str]:
        _require_account_ref(account_ref)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT epoch, owner_id, state FROM actor_account_writers WHERE account_ref=?",
                (account_ref,),
            ).fetchone()
        if row is None:
            raise ActorServerError("writer_not_found")
        return _exact_db_int(row[0], "writer epoch"), row[1], row[2]

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            user_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            if version == 0:
                if user_tables:
                    raise ActorServerError("database_schema_unsupported")
            elif version == _SCHEMA_VERSION:
                self._validate_schema(connection, user_tables)
                return
            else:
                raise ActorServerError("database_schema_unsupported")
            connection.executescript(
                "BEGIN IMMEDIATE;"
                + ";".join(_SCHEMA_DDL.values())
                + f";PRAGMA user_version={_SCHEMA_VERSION};COMMIT;"
            )
        finally:
            connection.close()

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection, user_tables: set[str]) -> None:
        if user_tables != set(_SCHEMA_COLUMNS):
            raise ActorServerError("database_schema_shape_invalid")
        objects = connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if len(objects) != len(_SCHEMA_DDL):
            raise ActorServerError("database_schema_shape_invalid")
        for object_type, name, sql in objects:
            expected = _SCHEMA_DDL.get(name)
            if (
                object_type != "table"
                or expected is None
                or _normalize_sql(sql) != _normalize_sql(expected)
            ):
                raise ActorServerError("database_schema_shape_invalid")
        for table, expected_columns in _SCHEMA_COLUMNS.items():
            actual_columns = tuple(
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual_columns != expected_columns:
                raise ActorServerError("database_schema_shape_invalid")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path, timeout=10.0, isolation_level=None
        )
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    class _Transaction:
        def __init__(self, core: AccountActorServerCoreV1) -> None:
            self.core = core
            self.connection: sqlite3.Connection | None = None

        def __enter__(self) -> sqlite3.Cursor:
            self.connection = self.core._connect()
            try:
                self.connection.execute("BEGIN IMMEDIATE")
            except Exception:
                self.connection.close()
                self.connection = None
                raise
            return self.connection.cursor()

        def __exit__(
            self,
            exc_type: Optional[type[BaseException]],  # noqa: UP045 - Python 3.8
            exc: Optional[BaseException],  # noqa: UP045 - Python 3.8
            tb: Optional[TracebackType],  # noqa: UP045 - Python 3.8
        ) -> bool:
            assert self.connection is not None
            try:
                if exc_type is None:
                    self.connection.commit()
                else:
                    self.connection.rollback()
            finally:
                self.connection.close()
            return False

    def _transaction(self) -> AccountActorServerCoreV1._Transaction:
        return self._Transaction(self)

    def _require_writer_cursor(
        self, cursor: sqlite3.Cursor, writer: WriterEpochV1
    ) -> None:
        if type(writer) is not WriterEpochV1:
            raise ActorServerError("writer_epoch_type_invalid")
        try:
            writer.__post_init__()
        except (TypeError, ValueError):
            raise ActorServerError("writer_epoch_invalid") from None
        row = cursor.execute(
            "SELECT epoch, owner_id, token_sha256, state FROM actor_account_writers WHERE account_ref=?",
            (writer.account_ref,),
        ).fetchone()
        if row is None or row[3] != "ACTIVE":
            raise ActorServerError("writer_epoch_inactive")
        if (
            row[0] != writer.epoch
            or row[1] != writer.owner_id
            or not hmac.compare_digest(row[2], _sha256(writer.token))
        ):
            raise ActorServerError("writer_epoch_mismatch")

    def _require_context_for_writer(
        self, writer: WriterEpochV1, intent: AccountActorIntentV1
    ) -> None:
        if type(writer) is not WriterEpochV1:
            raise ActorServerError("writer_epoch_type_invalid")
        if intent.context.account_ref != writer.account_ref:
            raise ActorServerError("intent_account_mismatch")
        if intent.context.actor_epoch != writer.epoch:
            raise ActorServerError("intent_actor_epoch_mismatch")

    def _require_session_context_cursor(
        self,
        cursor: sqlite3.Cursor,
        writer: WriterEpochV1,
        context: ActorCommandContextV1,
    ) -> None:
        expected = self._session_context_json_cursor(cursor, writer.account_ref)
        if expected is None:
            raise ActorServerError("writer_session_unbound")
        if _canonical_json(context.to_payload()) != expected:
            raise ActorServerError("intent_session_binding_mismatch")

    @staticmethod
    def _session_context_json_cursor(
        cursor: sqlite3.Cursor, account_ref: str
    ) -> Optional[str]:  # noqa: UP045 - Python 3.8
        row = cursor.execute(
            "SELECT context_json FROM actor_account_writers WHERE account_ref=?",
            (account_ref,),
        ).fetchone()
        if row is None:
            raise ActorServerError("writer_not_found")
        if row[0] is None:
            return None
        try:
            _require_canonical_object_json(row[0])
            decoded = json.loads(row[0])
            context = ActorCommandContextV1(**decoded)
            context.__post_init__()
            _require_account_ref(context.account_ref)
        except (TypeError, ValueError):
            raise ActorServerError("writer_session_binding_corrupt") from None
        return row[0]

    def _require_snapshot_authority(self) -> FakeSnapshotAuthorityV1:
        authority = self._snapshot_authority
        if type(authority) is not FakeSnapshotAuthorityV1:
            raise ActorServerError("snapshot_source_authority_unavailable")
        return authority

    def _require_current_verified_snapshot_cursor(
        self,
        cursor: sqlite3.Cursor,
        account_ref: str,
        snapshot_version: int,
        *,
        authority: Optional[FakeSnapshotAuthorityV1] = None,  # noqa: UP045 - Python 3.8
    ) -> None:
        authority = authority or self._require_snapshot_authority()
        current = cursor.execute(
            "SELECT snapshot_version FROM actor_current_snapshots WHERE account_ref=?",
            (account_ref,),
        ).fetchone()
        if current is None or current[0] != snapshot_version:
            raise ActorServerError("snapshot_not_current")
        bundle, proof = self._read_snapshot_cursor(
            cursor, account_ref, snapshot_version
        )
        if not authority.verify(bundle, proof):
            raise ActorServerError("snapshot_source_authority_invalid")

    def _snapshot_matches_cursor(
        self, cursor: sqlite3.Cursor, account_ref: str, snapshot_version: int
    ) -> bool:
        authority = self._snapshot_authority
        if type(authority) is not FakeSnapshotAuthorityV1:
            return False
        try:
            bundle, proof = self._read_snapshot_cursor(
                cursor, account_ref, snapshot_version
            )
        except (ActorServerError, TypeError, ValueError):
            return False
        return authority.verify(bundle, proof)

    def _read_snapshot_cursor(
        self, cursor: sqlite3.Cursor, account_ref: str, snapshot_version: int
    ) -> tuple[AccountSnapshotBundleV1, SnapshotAuthorityProofV1]:
        header = cursor.execute(
            "SELECT source_id, authority_id, snapshot_digest, proof_hex FROM actor_snapshots"
            " WHERE account_ref=? AND snapshot_version=?",
            (account_ref, snapshot_version),
        ).fetchone()
        if header is None:
            raise ActorServerError("snapshot_not_found")
        rows = cursor.execute(
            "SELECT domain, source_id, payload_json FROM actor_snapshot_domains"
            " WHERE account_ref=? AND snapshot_version=? ORDER BY domain",
            (account_ref, snapshot_version),
        ).fetchall()
        if len(rows) != 4 or {row[0] for row in rows} != _DOMAINS:
            raise ActorServerError("snapshot_domain_set_incomplete")
        facts = tuple(
            SnapshotDomainFactV1(
                account_ref=account_ref,
                snapshot_version=snapshot_version,
                source_id=row[1],
                domain=row[0],
                payload_json=row[2],
            )
            for row in rows
        )
        bundle = AccountSnapshotBundleV1(
            account_ref=account_ref,
            snapshot_version=snapshot_version,
            source_id=header[0],
            facts=facts,
        )
        proof = SnapshotAuthorityProofV1(
            authority_id=header[1],
            account_ref=account_ref,
            snapshot_version=snapshot_version,
            source_id=header[0],
            snapshot_digest=header[2],
            proof_hex=header[3],
        )
        if proof.snapshot_digest != bundle.digest:
            raise ActorServerError("snapshot_digest_readback_mismatch")
        return bundle, proof


def _validate_bundle_type(bundle: AccountSnapshotBundleV1) -> None:
    if type(bundle) is not AccountSnapshotBundleV1:
        raise ActorServerError("snapshot_bundle_type_invalid")
    try:
        bundle.__post_init__()
    except (TypeError, ValueError):
        raise ActorServerError("snapshot_bundle_invalid") from None


def _validate_intent_type(intent: AccountActorIntentV1) -> None:
    if type(intent) is not AccountActorIntentV1:
        raise ActorServerError("intent_type_invalid")
    try:
        intent.__post_init__()
    except (TypeError, ValueError):
        raise ActorServerError("intent_invalid") from None


def _require_account_ref(value: str) -> None:
    if type(value) is not str or _ACCOUNT_REF.fullmatch(value) is None:
        raise ValueError("account_ref must be canonical ctp-account-ref.v1 SHA-256")


def _require_text(value: str, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be nonempty exact text")


def _require_digest(value: str, name: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")


def _canonical_object(value: dict[str, Any]) -> str:
    if type(value) is not dict:
        raise ValueError("payload must be an exact dict")
    return _canonical_json(value)


def _require_canonical_object_json(value: str) -> None:
    if type(value) is not str:
        raise ValueError("canonical payload must be exact text")
    try:
        decoded = json.loads(value)
        if type(decoded) is not dict or _canonical_json(decoded) != value:
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("payload must be canonical JSON object") from None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _command_digest(
    operation: str, intent_id: str, context_json: str, payload_json: str
) -> str:
    _require_canonical_object_json(context_json)
    _require_canonical_object_json(payload_json)
    return _sha256(
        _canonical_json(
            {
                "operation": operation,
                "intent_id": intent_id,
                "context": json.loads(context_json),
                "payload": json.loads(payload_json),
            }
        )
    )


def _stored_command_is_valid(
    *,
    account_ref: str,
    operation: str,
    intent_id: str,
    command_digest: str,
    context_json: str,
    payload_json: str,
    expected_epoch: int,
    expected_context_json: Optional[str],  # noqa: UP045 - Python 3.8
) -> bool:
    try:
        if expected_context_json is None or context_json != expected_context_json:
            return False
        _require_account_ref(account_ref)
        _require_canonical_object_json(context_json)
        _require_canonical_object_json(payload_json)
        context = ActorCommandContextV1(**json.loads(context_json))
        context.__post_init__()
        if context.account_ref != account_ref or context.actor_epoch != expected_epoch:
            return False
        return hmac.compare_digest(
            command_digest,
            _command_digest(operation, intent_id, context_json, payload_json),
        )
    except (TypeError, ValueError, ActorServerError):
        return False


def _normalize_sql(value: str) -> str:
    if type(value) is not str:
        return ""
    return re.sub(r"\s+", "", value).lower()


def _exact_db_int(value: Any, name: str) -> int:
    if type(value) is not int:
        raise ActorServerError(f"{name.replace(' ', '_')}_invalid")
    return value
