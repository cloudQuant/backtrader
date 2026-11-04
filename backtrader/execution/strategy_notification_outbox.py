"""Durable local projections for Backtrader strategy notification recovery.

Two framework projection stores, not execution journals or authentication
mechanisms. A trusted caller binds the account, strategy, run, source and
Backtrader objects and supplies canonical JSON encoded by its own registered
projection codec. Nothing here unpickles or reconstructs Order, Trade, or
provider facts.

``StrategyNotificationJournal`` is the hot-path store used by
``BtApiBroker.bind_strategy_notification_recovery``: one ordered, at-least-once
journal per strategy with stable caller-derived event IDs, per-entry digests,
O(1) append/acknowledge and bounded retention of acknowledged rows. Since
schema version 3 it also keeps a bounded applied-fill index (order state, fills
with their booked fees and the Trade an order last updated) written in the
same transaction as the notifications, so a late fee correction that reaches a
restarted process is booked and notified exactly once.

``StrategyNotificationOutbox`` is the older checkpoint-batch primitive: one
projection batch atomically stores its checkpoint and notifications; delivery
is ordered, acknowledged in order, and every operation audits the full
retained history, so its cost grows with history and it is not used on the
notification path.

For both: acknowledge only after the callback returns. A crash after the
callback but before acknowledgement redelivers the same stable event ID. A
caller must provide a single active consumer for a scope and make external
effects idempotent; these stores do not fence another provider session or make
user callbacks exactly once. Scope names and hashes are not credentials, and
an external idempotency key must include the scope as well as the event ID.
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
    "JournalEntry",
    "JournalIndexUpdate",
    "NotificationOutboxError",
    "NotificationScope",
    "NotificationSnapshot",
    "ProjectionCheckpoint",
    "ProjectionCommit",
    "StrategyNotificationJournal",
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


class _DedicatedSqliteStore:
    """Open a SQLite file dedicated to one store class, refusing anything else.

    The path must be dedicated to this component. Only a path this constructor
    created exclusively may be initialized; an existing database is first
    checked read-only, and unknown, empty or damaged databases are refused.
    File identity is checked while opening but is not a defense against an
    adversary with arbitrary write access to the containing directory.
    Subclasses provide ``_verify_schema``, ``_audit`` and ``_initialise_new``.
    """

    def _verify_schema(self) -> None:  # pragma: no cover - subclass contract
        raise NotImplementedError

    def _audit(self) -> None:  # pragma: no cover - subclass contract
        raise NotImplementedError

    def _initialise_new(self, path: str, identity: os.stat_result) -> None:  # pragma: no cover
        raise NotImplementedError

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


class StrategyNotificationOutbox(_DedicatedSqliteStore):
    """Ordered durable projection snapshots for one declared strategy run.

    Checkpoint-batch primitive: every operation audits the full retained
    history, so it is not used on the notification hot path (see
    ``StrategyNotificationJournal``). It does not establish the authenticity
    of the projection namespace.
    """

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


# ---------------------------------------------------------------------------
# Bounded notification journal (re-verification G3, hot path)
# ---------------------------------------------------------------------------

_JOURNAL_VERSION = 3
_JOURNAL_KINDS = ("order", "trade", "fee_correction")
_JOURNAL_V2_DDL = {
    "journal_meta": (
        "CREATE TABLE journal_meta (id INTEGER PRIMARY KEY CHECK(id=1), "
        "account_ref TEXT NOT NULL, route_ref TEXT NOT NULL, strategy_ref TEXT NOT NULL, "
        "run_id TEXT NOT NULL, source_epoch TEXT NOT NULL, next_seq INTEGER NOT NULL, "
        "pending INTEGER NOT NULL, retained INTEGER NOT NULL)"
    ),
    "journal_notification": (
        "CREATE TABLE journal_notification (seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL "
        "UNIQUE, kind TEXT NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL, "
        "acked INTEGER NOT NULL CHECK(acked IN (0, 1)))"
    ),
    "journal_pending": (
        "CREATE INDEX journal_pending ON journal_notification(acked, seq)"
    ),
}
# Version 3 (iteration 60, post-acceptance): the applied-fill index. It lets a
# restarted process recognise a late fee correction of a fill an earlier
# process applied: fill fact -> order identity and booked fee; order identity
# -> its last journaled order state and fee totals; order -> the Trade it last
# updated. Written in the same transaction as the notification it belongs to.
_JOURNAL_INDEX_DDL = {
    "journal_order": (
        "CREATE TABLE journal_order (order_key TEXT PRIMARY KEY, seq INTEGER NOT NULL, "
        "record BLOB NOT NULL, digest TEXT NOT NULL)"
    ),
    "journal_order_seq": "CREATE INDEX journal_order_seq ON journal_order(seq)",
    "journal_fill": (
        "CREATE TABLE journal_fill (fill_key TEXT PRIMARY KEY, order_key TEXT NOT NULL, "
        "record BLOB NOT NULL, digest TEXT NOT NULL)"
    ),
    "journal_fill_order": "CREATE INDEX journal_fill_order ON journal_fill(order_key)",
    "journal_link": (
        "CREATE TABLE journal_link (order_key TEXT PRIMARY KEY, trade_key TEXT NOT NULL)"
    ),
    "journal_trade": (
        "CREATE TABLE journal_trade (trade_key TEXT PRIMARY KEY, record BLOB NOT NULL, "
        "digest TEXT NOT NULL)"
    ),
}
_JOURNAL_DDL = {**_JOURNAL_V2_DDL, **_JOURNAL_INDEX_DDL}
_DEFAULT_RETAIN_ACKED = 1024
_DEFAULT_RETAIN_ORDERS = 10_000
_COMPACT_EVERY = 256
_MAX_INDEX_KEY_BYTES = 2048


def _schema_objects(ddl: dict) -> set:
    return {
        (name, "index" if sql.startswith("CREATE INDEX") else "table", sql)
        for name, sql in ddl.items()
    }


def _index_key(value: object) -> str:
    """A bounded, printable index key (fill fact, order identity or trade key)."""
    if type(value) is not str or not value or value != value.strip():
        raise NotificationOutboxError("INDEX_KEY_INVALID")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise NotificationOutboxError("INDEX_KEY_INVALID") from None
    if len(encoded) > _MAX_INDEX_KEY_BYTES or any(ord(c) < 32 for c in value):
        raise NotificationOutboxError("INDEX_KEY_INVALID")
    return value


@dataclass(frozen=True)
class JournalIndexUpdate:
    """Upserts of the applied-fill index, written with (or without) journal entries.

    ``orders``: ``(order_key, record)``; ``fills``: ``(fill_key, order_key,
    record)``; ``links``: ``(order_key, trade_key)``; ``trades``:
    ``(trade_key, record)``. Records are canonical JSON objects (bytes).
    """

    orders: tuple = ()
    fills: tuple = ()
    links: tuple = ()
    trades: tuple = ()

    def __bool__(self) -> bool:
        return bool(self.orders or self.fills or self.links or self.trades)


@dataclass(frozen=True)
class JournalEntry:
    """One journaled notification: stable ``event_id``, delivery order ``seq``."""

    seq: int
    event_id: str
    kind: str
    payload: bytes
    acked: bool


def _entry_digest(scope: NotificationScope, seq: int, event_id: str, kind: str, payload: bytes):
    value = [
        scope.account_ref,
        scope.route_ref,
        scope.strategy_ref,
        scope.run_id,
        scope.source_epoch,
        seq,
        event_id,
        kind,
        payload.hex(),
    ]
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _index_digest(scope: NotificationScope, table: str, key: str, payload: bytes) -> str:
    value = [
        scope.account_ref,
        scope.route_ref,
        scope.strategy_ref,
        scope.run_id,
        scope.source_epoch,
        table,
        key,
        payload.hex(),
    ]
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


class StrategyNotificationJournal(_DedicatedSqliteStore):
    """Bounded, ordered at-least-once journal of one strategy's notifications.

    ``append`` durably stores a notification under a caller-derived stable
    ``event_id`` *before* it is delivered; ``acknowledge`` marks it delivered
    after the callback returned; ``pending`` returns the undelivered ones in
    append order (what a restarted process redelivers). Appending the same
    ``event_id`` with the same payload again is idempotent (the existing entry
    is returned), with another payload it is refused (``EVENT_ID_CONFLICT``).

    Costs are per operation, not per history: an append is one insert, an
    acknowledgement one update; each entry carries its own digest, verified
    when read back. Acknowledged entries beyond ``retain_acked`` (most recent
    kept, for duplicate detection) are deleted in amortized batches, so the
    file stays bounded by ``max_pending + retain_acked + 256`` rows. An
    ``event_id`` compacted away is no longer recognised as a duplicate: a
    re-append after that is delivered again (still at least once).

    The declared scope is stored at creation. Opening with another
    ``source_epoch`` (the upstream journal generation) raises
    ``RESYNC_REQUIRED``: the old entries belong to another generation and
    are never mapped onto the new one. Any other scope difference raises
    ``SCOPE_MISMATCH``. Scope values are declarations, not credentials.

    Applied-fill index (schema version 3; a version 2 file is upgraded in
    place when opened). Next to the notifications the journal keeps, per
    order identity, the last journaled order state with its provider fee
    totals, the fills applied to it (fill fact -> booked fee) and the Trade it
    last updated. ``append_many(..., index=...)`` writes them in the same
    transaction as the notifications they belong to, so a restarted process
    can book a late fee correction of a fill an earlier process applied
    exactly once. The index keeps the ``retain_orders`` most recently updated
    orders with their fills; older ones are compacted in amortized batches (a
    correction for a compacted order is no longer recognised).
    """

    def __init__(
        self,
        path: str | Path,
        scope: NotificationScope,
        *,
        retain_acked: int = _DEFAULT_RETAIN_ACKED,
        max_pending: int = _MAX_PENDING_EVENTS,
        retain_orders: int = _DEFAULT_RETAIN_ORDERS,
    ) -> None:
        if type(retain_acked) is not int or retain_acked < 0:
            raise NotificationOutboxError("RETENTION_INVALID")
        if type(max_pending) is not int or not 1 <= max_pending <= 1_000_000:
            raise NotificationOutboxError("RETENTION_INVALID")
        if type(retain_orders) is not int or not 1 <= retain_orders <= 10_000_000:
            raise NotificationOutboxError("RETENTION_INVALID")
        self._retain_acked = retain_acked
        self._max_pending = max_pending
        self._retain_orders = retain_orders
        self._acks_since_compaction = 0
        self._orders_since_compaction = 0
        super().__init__(path, scope)
        with self._lock, self._transaction(immediate=True):
            if self._db.execute("PRAGMA user_version").fetchone()[0] == 2:
                for sql in _JOURNAL_INDEX_DDL.values():
                    self._db.execute(sql)
                self._db.execute(f"PRAGMA user_version={_JOURNAL_VERSION}")
            self._compact()
            self._compact_index()

    # -- schema --------------------------------------------------------------

    def _verify_schema(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        objects = set(
            self._db.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        if (version, objects) not in (
            (_JOURNAL_VERSION, _schema_objects(_JOURNAL_DDL)),
            (2, _schema_objects(_JOURNAL_V2_DDL)),
        ):
            raise NotificationOutboxError("STORE_SCHEMA_INVALID")

    def _initialise_new(self, path: str, identity: os.stat_result) -> None:
        db = self._db
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        try:
            self._check_identity(path, identity)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            objects = db.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if version != 0 or objects:
                raise NotificationOutboxError("STORE_SCHEMA_INVALID")
            for sql in _JOURNAL_DDL.values():
                db.execute(sql)
            scope = self._scope
            db.execute(
                "INSERT INTO journal_meta VALUES (1, ?, ?, ?, ?, ?, 1, 0, 0)",
                (
                    scope.account_ref,
                    scope.route_ref,
                    scope.strategy_ref,
                    scope.run_id,
                    scope.source_epoch,
                ),
            )
            db.execute(f"PRAGMA user_version={_JOURNAL_VERSION}")
            self._check_identity(path, identity)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def _meta(self) -> tuple[int, int, int]:
        rows = self._db.execute(
            "SELECT account_ref, route_ref, strategy_ref, run_id, source_epoch, next_seq, "
            "pending, retained FROM journal_meta WHERE id=1"
        ).fetchall()
        if len(rows) != 1:
            raise NotificationOutboxError("STORE_CORRUPT")
        row = rows[0]
        scope = self._scope
        declared = (
            scope.account_ref,
            scope.route_ref,
            scope.strategy_ref,
            scope.run_id,
        )
        if tuple(row[:4]) != declared:
            raise NotificationOutboxError("SCOPE_MISMATCH")
        if row[4] != scope.source_epoch:
            raise NotificationOutboxError("RESYNC_REQUIRED")
        next_seq, pending, retained = row[5:]
        if any(type(value) is not int for value in row[5:]) or not (
            next_seq >= 1 and 0 <= pending <= retained < next_seq
        ):
            raise NotificationOutboxError("STORE_CORRUPT")
        return next_seq, pending, retained

    def _row(self, row: tuple) -> JournalEntry:
        seq, event_id, kind, payload, digest, acked = row
        try:
            _text(event_id)
            if kind not in _JOURNAL_KINDS or acked not in (0, 1) or type(seq) is not int:
                raise NotificationOutboxError("STORE_CORRUPT")
            _json_blob(payload, _MAX_PAYLOAD_BYTES)
        except NotificationOutboxError:
            raise NotificationOutboxError("STORE_CORRUPT") from None
        if digest != _entry_digest(self._scope, seq, event_id, kind, payload):
            raise NotificationOutboxError("STORE_CORRUPT")
        return JournalEntry(seq, event_id, kind, payload, bool(acked))

    def _audit(self) -> None:
        """Open-time check of the retained (bounded) rows and counters."""
        db = self._db
        self._verify_schema()
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise NotificationOutboxError("STORE_CORRUPT")
        next_seq, pending, retained = self._meta()
        rows = db.execute(
            "SELECT seq, event_id, kind, payload, digest, acked FROM journal_notification "
            "ORDER BY seq"
        ).fetchall()
        unacked = 0
        for row in rows:
            entry = self._row(tuple(row))
            if entry.seq >= next_seq:
                raise NotificationOutboxError("STORE_CORRUPT")
            unacked += not entry.acked
        if len(rows) != retained or unacked != pending:
            raise NotificationOutboxError("STORE_CORRUPT")

    def _compact(self) -> None:
        """Delete acknowledged rows older than the newest ``retain_acked``."""
        db = self._db
        cut = db.execute(
            "SELECT seq FROM journal_notification WHERE acked=1 ORDER BY seq DESC "
            "LIMIT 1 OFFSET ?",
            (self._retain_acked,),
        ).fetchone()
        if cut is not None:
            deleted = db.execute(
                "DELETE FROM journal_notification WHERE acked=1 AND seq<=?", (cut[0],)
            ).rowcount
            db.execute("UPDATE journal_meta SET retained=retained-? WHERE id=1", (deleted,))
        self._acks_since_compaction = 0

    # -- operations ----------------------------------------------------------

    def append(
        self,
        event_id: str,
        kind: str,
        payload: bytes,
        *,
        keep_existing: bool = False,
        index: JournalIndexUpdate | None = None,
    ) -> tuple[JournalEntry, bool]:
        """Durably store one notification; return ``(entry, created)``."""
        return self.append_many(((event_id, kind, payload, keep_existing),), index=index)[0]

    def append_many(
        self, entries, *, index: JournalIndexUpdate | None = None
    ) -> tuple[tuple[JournalEntry, bool], ...]:
        """Store notifications and index upserts in ONE transaction, in order.

        ``entries`` are ``(event_id, kind, payload)`` or ``(event_id, kind,
        payload, keep_existing)``. An existing ``event_id`` with the same kind
        and payload is returned with ``created=False``; another payload is
        refused (``EVENT_ID_CONFLICT``) unless ``keep_existing`` is true, in
        which case the journaled entry is kept unchanged (for entries whose id
        already identifies the fact, such as a fee correction). Nothing is
        written when any entry or index update is invalid.
        """
        checked = []
        for item in entries:
            if type(item) is not tuple or len(item) not in (3, 4):
                raise NotificationOutboxError("BATCH_INVALID")
            event_id, kind, payload = item[:3]
            keep = item[3] if len(item) == 4 else False
            _text(event_id)
            if type(kind) is not str or kind not in _JOURNAL_KINDS or type(keep) is not bool:
                raise NotificationOutboxError("KIND_INVALID")
            _json_blob(payload, _MAX_PAYLOAD_BYTES)
            checked.append((event_id, kind, payload, keep))
        if len({event_id for event_id, *_rest in checked}) != len(checked):
            raise NotificationOutboxError("EVENT_ID_CONFLICT")
        statements = self._index_statements(index)
        results = []
        with self._lock, self._transaction(immediate=True, integrity_code="EVENT_ID_CONFLICT"):
            next_seq, pending, retained = self._meta()
            for event_id, kind, payload, keep in checked:
                existing = self._db.execute(
                    "SELECT seq, event_id, kind, payload, digest, acked FROM journal_notification "
                    "WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    entry = self._row(tuple(existing))
                    if entry.kind != kind or (entry.payload != payload and not keep):
                        raise NotificationOutboxError("EVENT_ID_CONFLICT")
                    results.append((entry, False))
                    continue
                if pending + 1 > self._max_pending:
                    raise NotificationOutboxError("PENDING_CAPACITY_EXCEEDED")
                digest = _entry_digest(self._scope, next_seq, event_id, kind, payload)
                self._db.execute(
                    "INSERT INTO journal_notification VALUES (?, ?, ?, ?, ?, 0)",
                    (next_seq, event_id, kind, payload, digest),
                )
                results.append((JournalEntry(next_seq, event_id, kind, payload, False), True))
                next_seq, pending, retained = next_seq + 1, pending + 1, retained + 1
            if any(created for _entry, created in results):
                self._db.execute(
                    "UPDATE journal_meta SET next_seq=?, pending=?, retained=? WHERE id=1",
                    (next_seq, pending, retained),
                )
            self._write_index(statements, next_seq)
        return tuple(results)

    # -- applied-fill index ----------------------------------------------------

    def _index_statements(self, index: JournalIndexUpdate | None) -> list:
        """Validate ``index`` before any write; return ``(table, key, extra, payload)``."""
        if index is None:
            return []
        if type(index) is not JournalIndexUpdate:
            raise NotificationOutboxError("INDEX_INVALID")
        statements = []
        try:
            for order_key, record in index.orders:
                statements.append(("order", _index_key(order_key), None, record))
            for fill_key, order_key, record in index.fills:
                statements.append(("fill", _index_key(fill_key), _index_key(order_key), record))
            for order_key, trade_key in index.links:
                statements.append(("link", _index_key(order_key), _index_key(trade_key), None))
            for trade_key, record in index.trades:
                statements.append(("trade", _index_key(trade_key), None, record))
        except (TypeError, ValueError):
            raise NotificationOutboxError("INDEX_INVALID") from None
        for _table, _key, _extra, record in statements:
            if record is not None:
                _json_blob(record, _MAX_PAYLOAD_BYTES)
        return statements

    def _write_index(self, statements: list, seq: int) -> None:
        db = self._db
        scope = self._scope
        orders = 0
        for table, key, extra, record in statements:
            if table == "order":
                orders += 1
                db.execute(
                    "INSERT INTO journal_order VALUES (?, ?, ?, ?) ON CONFLICT(order_key) DO "
                    "UPDATE SET seq=excluded.seq, record=excluded.record, digest=excluded.digest",
                    (key, seq, record, _index_digest(scope, "order", key, record)),
                )
            elif table == "fill":
                digest = _index_digest(scope, "fill", key, extra.encode() + b"\0" + record)
                db.execute(
                    "INSERT INTO journal_fill VALUES (?, ?, ?, ?) ON CONFLICT(fill_key) DO "
                    "UPDATE SET order_key=excluded.order_key, record=excluded.record, "
                    "digest=excluded.digest",
                    (key, extra, record, digest),
                )
            elif table == "link":
                db.execute(
                    "INSERT INTO journal_link VALUES (?, ?) ON CONFLICT(order_key) DO "
                    "UPDATE SET trade_key=excluded.trade_key",
                    (key, extra),
                )
            else:
                db.execute(
                    "INSERT INTO journal_trade VALUES (?, ?, ?) ON CONFLICT(trade_key) DO "
                    "UPDATE SET record=excluded.record, digest=excluded.digest",
                    (key, record, _index_digest(scope, "trade", key, record)),
                )
        if orders:
            self._orders_since_compaction += orders
            if self._orders_since_compaction >= _COMPACT_EVERY:
                self._compact_index()

    def update_index(self, index: JournalIndexUpdate) -> None:
        """Write index upserts without a notification (one transaction)."""
        statements = self._index_statements(index)
        if not statements:
            return
        with self._lock, self._transaction(immediate=True):
            next_seq, _pending, _retained = self._meta()
            self._write_index(statements, next_seq)

    def _compact_index(self) -> None:
        """Keep the ``retain_orders`` most recently updated orders, their fills and Trades."""
        db = self._db
        cut = db.execute(
            "SELECT seq FROM journal_order ORDER BY seq DESC LIMIT 1 OFFSET ?",
            (self._retain_orders,),
        ).fetchone()
        if cut is not None:
            db.execute(
                "DELETE FROM journal_fill WHERE order_key IN "
                "(SELECT order_key FROM journal_order WHERE seq<=?)",
                (cut[0],),
            )
            db.execute(
                "DELETE FROM journal_link WHERE order_key IN "
                "(SELECT order_key FROM journal_order WHERE seq<=?)",
                (cut[0],),
            )
            db.execute("DELETE FROM journal_order WHERE seq<=?", (cut[0],))
            db.execute(
                "DELETE FROM journal_trade WHERE trade_key NOT IN "
                "(SELECT trade_key FROM journal_link)"
            )
        self._orders_since_compaction = 0

    def _index_row(self, table: str, key: str, digest_payload: bytes, record, digest) -> bytes:
        if type(record) is not bytes or digest != _index_digest(
            self._scope, table, key, digest_payload
        ):
            raise NotificationOutboxError("STORE_CORRUPT")
        try:
            _json_blob(record, _MAX_PAYLOAD_BYTES)
        except NotificationOutboxError:
            raise NotificationOutboxError("STORE_CORRUPT") from None
        return record

    def indexed_fill(self, fill_key: str) -> tuple[str, bytes] | None:
        """``(order_key, record)`` of an applied fill, or ``None``."""
        key = _index_key(fill_key)
        with self._lock, self._transaction():
            self._meta()
            row = self._db.execute(
                "SELECT order_key, record, digest FROM journal_fill WHERE fill_key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        order_key, record, digest = row
        if type(order_key) is not str:
            raise NotificationOutboxError("STORE_CORRUPT")
        payload = record if type(record) is bytes else b""
        self._index_row("fill", key, order_key.encode() + b"\0" + payload, record, digest)
        return order_key, record

    def indexed_order(self, order_key: str) -> tuple[bytes | None, str | None, bytes | None]:
        """``(order record, trade key, Trade record)`` of an order; ``None`` where absent."""
        key = _index_key(order_key)
        with self._lock, self._transaction():
            self._meta()
            row = self._db.execute(
                "SELECT record, digest FROM journal_order WHERE order_key=?", (key,)
            ).fetchone()
            trade = self._db.execute(
                "SELECT t.trade_key, t.record, t.digest FROM journal_link AS l JOIN "
                "journal_trade AS t ON t.trade_key = l.trade_key WHERE l.order_key=?",
                (key,),
            ).fetchone()
        order = None if row is None else self._index_row("order", key, row[0], *row)
        trade_key = trade_record = None
        if trade is not None:
            trade_key, record, digest = trade
            if type(trade_key) is not str:
                raise NotificationOutboxError("STORE_CORRUPT")
            trade_record = self._index_row("trade", trade_key, record, record, digest)
        return order, trade_key, trade_record

    def index_stats(self) -> dict:
        """Row counts of the applied-fill index (``orders``, ``fills``, ``trades``)."""
        with self._lock, self._transaction():
            self._meta()
            return {
                name: self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for name, table in (
                    ("orders", "journal_order"),
                    ("fills", "journal_fill"),
                    ("trades", "journal_trade"),
                )
            }

    def pending(self, limit: int = _MAX_BATCH_EVENTS) -> tuple[JournalEntry, ...]:
        """Return up to ``limit`` unacknowledged entries in append order."""
        if type(limit) is not int or not 1 <= limit <= _MAX_PENDING_EVENTS:
            raise NotificationOutboxError("LIMIT_INVALID")
        with self._lock, self._transaction():
            self._meta()
            rows = self._db.execute(
                "SELECT seq, event_id, kind, payload, digest, acked FROM journal_notification "
                "WHERE acked=0 ORDER BY seq LIMIT ?",
                (limit,),
            ).fetchall()
            return tuple(self._row(tuple(row)) for row in rows)

    def acknowledge(self, event_id: str) -> bool:
        """Mark ``event_id`` delivered; ``False`` if it already was (idempotent)."""
        _text(event_id)
        with self._lock, self._transaction(immediate=True):
            _next_seq, pending, _retained = self._meta()
            row = self._db.execute(
                "SELECT acked FROM journal_notification WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise NotificationOutboxError("ACK_UNKNOWN")
            if row[0]:
                return False
            if pending < 1:
                raise NotificationOutboxError("STORE_CORRUPT")
            self._db.execute(
                "UPDATE journal_notification SET acked=1 WHERE event_id=?", (event_id,)
            )
            self._db.execute("UPDATE journal_meta SET pending=? WHERE id=1", (pending - 1,))
            self._acks_since_compaction += 1
            if self._acks_since_compaction >= _COMPACT_EVERY:
                self._compact()
            return True

    def stats(self) -> dict:
        """Counters: ``pending``, ``retained`` rows and ``next_seq``."""
        with self._lock, self._transaction():
            next_seq, pending, retained = self._meta()
        return {"next_seq": next_seq, "pending": pending, "retained": retained}

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                raise NotificationOutboxError("STORE_UNAVAILABLE") from None
