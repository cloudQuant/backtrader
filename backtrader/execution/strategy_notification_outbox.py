"""Durable snapshots for future Backtrader strategy notification recovery.

This is an *unconnected* framework projection component, not an execution
journal or an authentication mechanism. A trusted caller must first bind the
account, strategy, run, source and Backtrader objects, and must supply a
versioned snapshot encoded by its own registered projection codec. This module
never unpickles or reconstructs Order, Trade, or provider facts.

One projection batch atomically stores its checkpoint and order/trade
notifications in a dedicated SQLite database. Delivery is ordered and at least
once: acknowledge only after the callback returns. A crash after the callback
but before acknowledgement redelivers the same stable event ID. A caller must
provide a single active consumer for a scope and make external effects
idempotent; this store does not fence another provider session or make user
callbacks exactly once. Scope names and hashes are not credentials.
Event IDs are unique only within the full declared scope; an external
idempotency key must include that scope as well as the event ID.

This prototype scans all retained projection batches on each operation. Its
cost grows with history; high-frequency performance has not been accepted and
it must not be wired into a production path without a separately designed,
verified bounded or incremental integrity scheme.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = [
    "NotificationOutboxError",
    "NotificationScope",
    "NotificationSnapshot",
    "ProjectionCheckpoint",
    "ProjectionCommit",
    "StrategyNotificationOutbox",
]

_VERSION = 1
_MAX_TEXT_BYTES = 256
_MAX_PAYLOAD_BYTES = 65536
_MAX_CHECKPOINT_BYTES = 1048576
_MAX_DEPTH = 16
_MAX_ITEMS = 4096
_MAX_BATCH_EVENTS = 128
_MAX_PENDING_EVENTS = 4096
_DDL = {
    "projection_meta": (
        "CREATE TABLE projection_meta (id INTEGER PRIMARY KEY CHECK(id=1), "
        "account_ref TEXT NOT NULL, route_ref TEXT NOT NULL, strategy_ref TEXT NOT NULL, run_id TEXT NOT NULL, "
        "source_epoch TEXT NOT NULL, revision INTEGER NOT NULL, next_seq INTEGER NOT NULL, "
        "ack_seq INTEGER NOT NULL)"
    ),
    "projection_batch": (
        "CREATE TABLE projection_batch (source_id TEXT PRIMARY KEY, revision INTEGER "
        "NOT NULL UNIQUE, schema_id TEXT NOT NULL, schema_version INTEGER NOT NULL, "
        "checkpoint BLOB NOT NULL, digest TEXT NOT NULL)"
    ),
    "projection_notification": (
        "CREATE TABLE projection_notification (seq INTEGER PRIMARY KEY, event_id TEXT "
        "NOT NULL UNIQUE, source_id TEXT NOT NULL REFERENCES projection_batch(source_id), "
        "kind TEXT NOT NULL, data_ref TEXT NOT NULL, order_ref TEXT NOT NULL, trade_ref TEXT, "
        "schema_id TEXT NOT NULL, schema_version INTEGER NOT NULL, payload BLOB NOT NULL)"
    ),
    "projection_ack": (
        "CREATE TABLE projection_ack (seq INTEGER PRIMARY KEY REFERENCES projection_notification(seq), "
        "event_id TEXT NOT NULL UNIQUE REFERENCES projection_notification(event_id))"
    ),
}


class NotificationOutboxError(RuntimeError):
    """A finite, value-free failure in the local notification projection."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _text(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise NotificationOutboxError("IDENTITY_INVALID")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise NotificationOutboxError("IDENTITY_INVALID") from None
    if len(encoded) > _MAX_TEXT_BYTES or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise NotificationOutboxError("IDENTITY_INVALID")
    return value


def _json_blob(value: object, maximum: int) -> bytes:
    """Require a bounded, canonical JSON object, never pickle or custom code."""
    if type(value) is not bytes or not value or len(value) > maximum:
        raise NotificationOutboxError("SNAPSHOT_INVALID")

    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    try:
        data = json.loads(value.decode("utf-8", errors="strict"), object_pairs_hook=unique)
        if type(data) is not dict:
            raise ValueError("object required")
        stack = [(data, 0)]
        items = 0
        while stack:
            current, depth = stack.pop()
            if depth > _MAX_DEPTH:
                raise ValueError("depth")
            items += 1
            if items > _MAX_ITEMS:
                raise ValueError("items")
            if type(current) is dict:
                for key in current:
                    key.encode("utf-8", errors="strict")
                stack.extend((item, depth + 1) for item in current.values())
            elif type(current) is list:
                stack.extend((item, depth + 1) for item in current)
            elif type(current) is float and not math.isfinite(current):
                raise ValueError("nonfinite")
            elif type(current) is str:
                current.encode("utf-8", errors="strict")
            elif type(current) not in (str, int, float, bool, type(None)):
                raise ValueError("type")
        encoded = json.dumps(
            data, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if encoded != value:
            raise ValueError("noncanonical")
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        raise NotificationOutboxError("SNAPSHOT_INVALID") from None
    return value


@dataclass(frozen=True)
class NotificationScope:
    """Declared projection namespace; values do not authenticate their owner."""

    account_ref: str
    route_ref: str
    strategy_ref: str
    run_id: str
    source_epoch: str

    def __post_init__(self) -> None:
        for value in (
            self.account_ref,
            self.route_ref,
            self.strategy_ref,
            self.run_id,
            self.source_epoch,
        ):
            _text(value)


@dataclass(frozen=True)
class NotificationSnapshot:
    """Opaque callback snapshot; a trusted codec must validate object binding."""

    event_id: str
    kind: str
    data_ref: str
    order_ref: str
    trade_ref: str | None
    schema_id: str
    schema_version: int
    payload: bytes

    def __post_init__(self) -> None:
        for value in (self.event_id, self.data_ref, self.order_ref, self.schema_id):
            _text(value)
        if type(self.kind) is not str or self.kind not in ("order", "trade"):
            raise NotificationOutboxError("KIND_INVALID")
        if self.kind == "order" and self.trade_ref is not None:
            raise NotificationOutboxError("TRADE_BINDING_INVALID")
        if self.kind == "trade":
            _text(self.trade_ref)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise NotificationOutboxError("SCHEMA_UNSUPPORTED")
        _json_blob(self.payload, _MAX_PAYLOAD_BYTES)


@dataclass(frozen=True)
class ProjectionCheckpoint:
    """Versioned, opaque projection state; it is not an authenticated proof."""

    schema_id: str
    schema_version: int
    payload: bytes

    def __post_init__(self) -> None:
        _text(self.schema_id)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise NotificationOutboxError("SCHEMA_UNSUPPORTED")
        _json_blob(self.payload, _MAX_CHECKPOINT_BYTES)


@dataclass(frozen=True)
class ProjectionCommit:
    """Current checkpoint revision and data supplied by the projection owner."""

    revision: int
    checkpoint: ProjectionCheckpoint | None


def _digest(
    scope: NotificationScope,
    source_id: str,
    revision: int,
    checkpoint: ProjectionCheckpoint,
    events: tuple[NotificationSnapshot, ...],
) -> str:
    value = {
        "scope": [
            scope.account_ref,
            scope.route_ref,
            scope.strategy_ref,
            scope.run_id,
            scope.source_epoch,
        ],
        "source_id": source_id,
        "revision": revision,
        "checkpoint": [checkpoint.schema_id, checkpoint.schema_version, checkpoint.payload.hex()],
        "events": [
            [
                e.event_id,
                e.kind,
                e.data_ref,
                e.order_ref,
                e.trade_ref,
                e.schema_id,
                e.schema_version,
                e.payload.hex(),
            ]
            for e in events
        ],
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


class StrategyNotificationOutbox:
    """Ordered durable projection snapshots for one declared strategy run.

    The path must be dedicated to this component. Only a path this constructor
    created exclusively may be initialized; an existing database is first
    checked read-only, and unknown, empty or damaged databases are refused.
    File identity is checked while opening but is not a defense against an
    adversary with arbitrary write access to the containing directory. This
    class does not establish the authenticity of the projection namespace.
    """

    def __init__(self, path: str | Path, scope: NotificationScope) -> None:
        if type(scope) is not NotificationScope:
            raise NotificationOutboxError("SCOPE_INVALID")
        scope.__post_init__()
        self._scope = scope
        self._lock = threading.RLock()
        descriptor = None
        try:
            raw_path = os.fspath(path)
            if (
                type(raw_path) is not str
                or not raw_path
                or raw_path == ":memory:"
                or raw_path.startswith("file:")
            ):
                raise NotificationOutboxError("STORE_PATH_INVALID")
            absolute_path = os.path.abspath(raw_path)
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            try:
                descriptor = os.open(absolute_path, flags, 0o600)
                created = True
            except FileExistsError:
                descriptor = os.open(
                    absolute_path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                )
                created = False
            identity = os.fstat(descriptor)
            if not stat.S_ISREG(identity.st_mode):
                raise NotificationOutboxError("STORE_PATH_INVALID")
            self._check_identity(absolute_path, identity)
            uri = Path(absolute_path).as_uri()

            if not created:
                if identity.st_size == 0:
                    raise NotificationOutboxError("STORE_SCHEMA_INVALID")
                self._db = sqlite3.connect(
                    uri + "?mode=ro", uri=True, isolation_level=None, check_same_thread=False
                )
                self._check_identity(absolute_path, identity)
                self._db.execute("PRAGMA query_only=ON")
                self._db.execute("PRAGMA foreign_keys=ON")
                self._db.execute("BEGIN")
                try:
                    self._verify_schema()
                    self._audit()
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise
                self._db.close()
                del self._db
                self._check_identity(absolute_path, identity)

            self._db = sqlite3.connect(
                uri + "?mode=rw", uri=True, isolation_level=None, check_same_thread=False
            )
            self._check_identity(absolute_path, identity)
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA synchronous=FULL")
            if created:
                self._initialise_new(absolute_path, identity)
            self._db.execute("BEGIN")
            try:
                self._verify_schema()
                self._audit()
                self._check_identity(absolute_path, identity)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        except NotificationOutboxError:
            if hasattr(self, "_db"):
                self._db.close()
            raise
        except (sqlite3.Error, OSError, TypeError, ValueError):
            if hasattr(self, "_db"):
                self._db.close()
            raise NotificationOutboxError("STORE_INVALID") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _check_identity(path: str, opened: os.stat_result) -> None:
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError:
            raise NotificationOutboxError("STORE_PATH_CHANGED") from None
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_dev != opened.st_dev
            or current.st_ino != opened.st_ino
        ):
            raise NotificationOutboxError("STORE_PATH_CHANGED")

    def _verify_schema(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        objects = self._db.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if version != _VERSION or set(objects) != {
            (name, "table", sql) for name, sql in _DDL.items()
        }:
            raise NotificationOutboxError("STORE_SCHEMA_INVALID")

    def _initialise_new(self, path: str, identity: os.stat_result) -> None:
        db = self._db
        db.execute("BEGIN IMMEDIATE")
        try:
            self._check_identity(path, identity)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            objects = db.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if version != 0 or objects:
                raise NotificationOutboxError("STORE_SCHEMA_INVALID")
            for sql in _DDL.values():
                db.execute(sql)
            db.execute(
                "INSERT INTO projection_meta VALUES (1, ?, ?, ?, ?, ?, 0, 1, 0)",
                (
                    self._scope.account_ref,
                    self._scope.route_ref,
                    self._scope.strategy_ref,
                    self._scope.run_id,
                    self._scope.source_epoch,
                ),
            )
            db.execute("PRAGMA user_version=1")
            self._check_identity(path, identity)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    @staticmethod
    def _event(row: tuple) -> NotificationSnapshot:
        try:
            return NotificationSnapshot(*row)
        except (TypeError, ValueError, NotificationOutboxError):
            raise NotificationOutboxError("STORE_CORRUPT") from None

    def _meta(self) -> tuple:
        rows = self._db.execute(
            "SELECT account_ref, route_ref, strategy_ref, run_id, source_epoch, revision, next_seq, ack_seq "
            "FROM projection_meta WHERE id=1"
        ).fetchall()
        if len(rows) != 1:
            raise NotificationOutboxError("STORE_CORRUPT")
        row = rows[0]
        if tuple(row[:5]) != (
            self._scope.account_ref,
            self._scope.route_ref,
            self._scope.strategy_ref,
            self._scope.run_id,
            self._scope.source_epoch,
        ):
            raise NotificationOutboxError("SCOPE_MISMATCH")
        if any(type(value) is not int for value in row[5:]) or not (
            0 <= row[7] < row[6] and row[5] >= 0
        ):
            raise NotificationOutboxError("STORE_CORRUPT")
        return row

    def _audit(self) -> None:
        db = self._db
        self._verify_schema()
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise NotificationOutboxError("STORE_CORRUPT")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise NotificationOutboxError("STORE_CORRUPT")
        _, _, _, _, _, revision, next_seq, ack_seq = self._meta()
        if db.execute("SELECT COUNT(*) FROM projection_batch").fetchone()[0] != revision:
            raise NotificationOutboxError("STORE_CORRUPT")
        batches = db.execute(
            "SELECT source_id, revision, schema_id, schema_version, checkpoint, digest "
            "FROM projection_batch ORDER BY revision"
        )
        count = 0
        for expected_revision, (
            source_id,
            actual_revision,
            schema_id,
            schema_version,
            payload,
            digest,
        ) in enumerate(batches, 1):
            try:
                _text(source_id)
                checkpoint = ProjectionCheckpoint(schema_id, schema_version, payload)
                if actual_revision != expected_revision:
                    raise NotificationOutboxError("STORE_CORRUPT")
                rows = db.execute(
                    "SELECT seq, event_id, kind, data_ref, order_ref, trade_ref, schema_id, schema_version, payload "
                    "FROM projection_notification WHERE source_id=? ORDER BY seq",
                    (source_id,),
                ).fetchall()
                if len(rows) > _MAX_BATCH_EVENTS:
                    raise NotificationOutboxError("STORE_CORRUPT")
                events = tuple(self._event(tuple(row[1:])) for row in rows)
                if digest != _digest(self._scope, source_id, actual_revision, checkpoint, events):
                    raise NotificationOutboxError("STORE_CORRUPT")
                for row in rows:
                    count += 1
                    if row[0] != count:
                        raise NotificationOutboxError("STORE_CORRUPT")
            except NotificationOutboxError:
                raise NotificationOutboxError("STORE_CORRUPT") from None
        if count != next_seq - 1:
            raise NotificationOutboxError("STORE_CORRUPT")
        acks = db.execute("SELECT seq, event_id FROM projection_ack ORDER BY seq").fetchall()
        if len(acks) != ack_seq:
            raise NotificationOutboxError("STORE_CORRUPT")
        for expected, (seq, event_id) in enumerate(acks, 1):
            event = db.execute(
                "SELECT event_id FROM projection_notification WHERE seq=?", (seq,)
            ).fetchone()
            if seq != expected or event != (event_id,):
                raise NotificationOutboxError("STORE_CORRUPT")

    @contextmanager
    def _transaction(self, *, immediate: bool = False, integrity_code: str = "STORE_UNAVAILABLE"):
        """Rollback unsuccessful operations and expose finite storage failures."""
        db = self._db
        try:
            db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield
            db.execute("COMMIT")
        except BaseException as error:
            try:
                if db.in_transaction:
                    db.execute("ROLLBACK")
            except sqlite3.Error:
                raise NotificationOutboxError("STORE_UNAVAILABLE") from None
            if isinstance(error, sqlite3.IntegrityError):
                raise NotificationOutboxError(integrity_code) from None
            if isinstance(error, sqlite3.Error):
                raise NotificationOutboxError("STORE_UNAVAILABLE") from None
            raise

    def checkpoint(self) -> ProjectionCommit:
        with self._lock, self._transaction():
            self._audit()
            revision = self._meta()[5]
            row = (
                None
                if not revision
                else self._db.execute(
                    "SELECT schema_id, schema_version, checkpoint FROM projection_batch WHERE revision=?",
                    (revision,),
                ).fetchone()
            )
            if revision and row is None:
                raise NotificationOutboxError("STORE_CORRUPT")
            return ProjectionCommit(revision, None if row is None else ProjectionCheckpoint(*row))

    def commit(
        self,
        *,
        source_id: str,
        expected_revision: int,
        checkpoint: ProjectionCheckpoint,
        notifications: tuple[NotificationSnapshot, ...],
    ) -> ProjectionCommit:
        """Atomically commit a validated projection checkpoint and callbacks.

        The source ID is an upstream-provided stable correlation key. A repeat
        with exactly the same checkpoint and notifications is idempotent; a
        different result for that ID is refused even after acknowledgement.
        """
        _text(source_id)
        if type(checkpoint) is not ProjectionCheckpoint:
            raise NotificationOutboxError("SNAPSHOT_INVALID")
        checkpoint.__post_init__()
        if type(expected_revision) is not int or expected_revision < 0:
            raise NotificationOutboxError("REVISION_INVALID")
        if type(notifications) is not tuple or len(notifications) > _MAX_BATCH_EVENTS:
            raise NotificationOutboxError("BATCH_INVALID")
        if any(type(event) is not NotificationSnapshot for event in notifications):
            raise NotificationOutboxError("BATCH_INVALID")
        for event in notifications:
            event.__post_init__()
        if len({event.event_id for event in notifications}) != len(notifications):
            raise NotificationOutboxError("EVENT_ID_CONFLICT")
        with self._lock:
            db = self._db
            with self._transaction(immediate=True, integrity_code="EVENT_ID_CONFLICT"):
                self._audit()
                _, _, _, _, _, revision, next_seq, ack_seq = self._meta()
                existing = db.execute(
                    "SELECT revision, digest FROM projection_batch WHERE source_id=?", (source_id,)
                ).fetchone()
                if existing is not None:
                    if existing[1] != _digest(
                        self._scope, source_id, existing[0], checkpoint, notifications
                    ):
                        raise NotificationOutboxError("SOURCE_ID_CONFLICT")
                    return ProjectionCommit(existing[0], checkpoint)
                if expected_revision != revision:
                    raise NotificationOutboxError("REVISION_CONFLICT")
                if next_seq - 1 - ack_seq + len(notifications) > _MAX_PENDING_EVENTS:
                    raise NotificationOutboxError("PENDING_CAPACITY_EXCEEDED")
                digest = _digest(self._scope, source_id, revision + 1, checkpoint, notifications)
                db.execute(
                    "INSERT INTO projection_batch VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        source_id,
                        revision + 1,
                        checkpoint.schema_id,
                        checkpoint.schema_version,
                        checkpoint.payload,
                        digest,
                    ),
                )
                for offset, event in enumerate(notifications):
                    db.execute(
                        "INSERT INTO projection_notification VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            next_seq + offset,
                            event.event_id,
                            source_id,
                            event.kind,
                            event.data_ref,
                            event.order_ref,
                            event.trade_ref,
                            event.schema_id,
                            event.schema_version,
                            event.payload,
                        ),
                    )
                db.execute(
                    "UPDATE projection_meta SET revision=?, next_seq=? WHERE id=1",
                    (revision + 1, next_seq + len(notifications)),
                )
                self._audit()
                return ProjectionCommit(revision + 1, checkpoint)

    def pending(self) -> NotificationSnapshot | None:
        """Return the first unacknowledged snapshot without advancing it."""
        with self._lock, self._transaction():
            self._audit()
            meta = self._meta()
            ack_seq = meta[7]
            row = self._db.execute(
                "SELECT event_id, kind, data_ref, order_ref, trade_ref, schema_id, schema_version, payload "
                "FROM projection_notification WHERE seq=?",
                (ack_seq + 1,),
            ).fetchone()
            if row is None and ack_seq + 1 != meta[6]:
                raise NotificationOutboxError("STORE_CORRUPT")
            return None if row is None else self._event(tuple(row))

    def acknowledge(self, event_id: str) -> None:
        """Advance exactly the first pending event after its callback succeeds."""
        _text(event_id)
        with self._lock:
            db = self._db
            with self._transaction(immediate=True):
                self._audit()
                ack_seq = self._meta()[7]
                row = db.execute(
                    "SELECT seq FROM projection_notification WHERE event_id=?", (event_id,)
                ).fetchone()
                if row is None or row[0] > ack_seq + 1:
                    raise NotificationOutboxError("ACK_OUT_OF_ORDER")
                if row[0] == ack_seq + 1:
                    db.execute("INSERT INTO projection_ack VALUES (?, ?)", (row[0], event_id))
                    db.execute("UPDATE projection_meta SET ack_seq=? WHERE id=1", (row[0],))
                self._audit()

    def deliver_next(self, handler: Callable[[NotificationSnapshot], object]) -> bool:
        """Deliver one event and acknowledge it only after a normal return."""
        if not callable(handler):
            raise NotificationOutboxError("HANDLER_INVALID")
        event = self.pending()
        if event is None:
            return False
        handler(event)
        self.acknowledge(event.event_id)
        return True

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                raise NotificationOutboxError("STORE_UNAVAILABLE") from None
