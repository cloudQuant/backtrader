"""Independent local journal for fixed read-only guardian requests.

This storage seam is intended for a future pre-start service. It has no CLI,
SDK, provider, worker, credential, or trading integration. The service must
call :meth:`GuardianRequestJournal.accept_request` after receiving a request
and may start its read-only worker only after that method returns: the method
commits and reads back the ``RUNNING`` row first.

The journal records a fixed operation name and an opaque request ID; it stores
no request payload or credentials. ``RUNNING``, ``OBSERVED``, and ``UNKNOWN``
are accounting states only. None of them grants trading authority. An
``UNKNOWN`` row is terminal in this API and cannot be upgraded by a late
callback or caller-supplied digest. The observed digest must come from a
separate trusted verifier supplied by a future service; this module does not
provide or authenticate such a verifier.

SQLite uses rollback-journal mode with ``synchronous=FULL`` and a bounded busy
timeout. That makes successful method returns wait for SQLite's configured
durability boundary, but it cannot make arbitrary filesystem, kernel, or
device stalls hard real-time bounded. A request deadline starts from a
code-owned monotonic timestamp before the durable accept transaction. It is
generation-local and is never reused after restart.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import ntpath
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


GUARDIAN_REQUEST_SCHEMA_VERSION = 1
GUARDIAN_REQUEST_DATABASE_NAME = "guardian-request-journal.sqlite3"
GUARDIAN_REQUEST_BUDGET_SECONDS = 300
GUARDIAN_REQUEST_BUDGET_NS = GUARDIAN_REQUEST_BUDGET_SECONDS * 1_000_000_000
GUARDIAN_REQUEST_BUSY_TIMEOUT_SECONDS = 0.25
GUARDIAN_FIXED_OPERATION = "ctp_readonly_preflight"
GUARDIAN_READ_ONLY_OPERATIONS = frozenset((GUARDIAN_FIXED_OPERATION,))
GUARDIAN_REQUEST_WRITE_AUTHORIZED = False
GUARDIAN_REQUEST_TRADING_CAPABILITIES: tuple[()] = ()

_IDENTITY_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REQUEST_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_UNKNOWN_REASONS = frozenset(
    (
        "deadline_expired",
        "provider_uncertain",
        "restart_recovery",
        "server_cancelled",
        "transport_uncertain",
    )
)
_APPLICATION_TABLES = frozenset(("guardian_request_meta", "guardian_requests"))
_WINDOWS_FIXED_DRIVE = 3


class GuardianRequestJournalError(RuntimeError):
    """Redacted fail-closed journal error with a stable reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GuardianRequestRecord:
    """Immutable local receipt for one fixed read-only request."""

    request_id: str
    identity: str
    operation: str
    state: str
    accepted_generation: str
    accepted_monotonic_ns: int
    deadline_monotonic_ns: int
    terminal_generation: Optional[str]
    terminal_monotonic_ns: Optional[int]
    receipt_digest: Optional[str]
    terminal_reason: Optional[str]


class GuardianRequestJournal:
    """Durable, identity-bound state for a single pre-start service journal.

    ``state_dir`` must already exist and be private. On POSIX it must be owned
    by the current user and have no group/world permissions. On Windows it
    must be on a fixed local volume, contain no reparse-point path component,
    and have a protected owner-only ACL. The database is a fixed child of that
    directory so callers cannot redirect the journal to an arbitrary path.

    Opening an existing journal creates a new process generation and changes
    every old ``RUNNING`` row to terminal ``UNKNOWN`` in one durable
    transaction. A shared database opened by a second process similarly
    fences the first process by changing the generation; the older instance
    then fails closed.
    """

    LOCAL_ONLY = True
    NO_WRITE = True
    ORDER_SUBMISSION_AUTHORIZED = False
    TRADING_CAPABILITIES: tuple[()] = ()

    _META_TABLE = "guardian_request_meta"
    _REQUEST_TABLE = "guardian_requests"
    _BUSY_TIMEOUT_MS = int(GUARDIAN_REQUEST_BUSY_TIMEOUT_SECONDS * 1000)

    def __init__(self, state_dir: Path, identity: str) -> None:
        if (
            not isinstance(state_dir, Path)
            or not state_dir.is_absolute()
            or ".." in state_dir.parts
        ):
            raise GuardianRequestJournalError("guardian_journal_config_invalid")
        if type(identity) is not str or _IDENTITY_RE.fullmatch(identity) is None:
            raise GuardianRequestJournalError("guardian_journal_identity_invalid")

        self._state_dir = Path(os.path.abspath(os.fspath(state_dir)))
        self._path = self._state_dir / GUARDIAN_REQUEST_DATABASE_NAME
        self._identity = identity
        self._generation = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._closed = False
        self._directory_identity = self._verify_state_directory()
        self._database_identity = self._prepare_database_file()
        self._initialize_and_recover()

    @property
    def identity(self) -> str:
        """The fixed non-secret identity bound to this database."""

        return self._identity

    @property
    def generation(self) -> str:
        """The current process generation; old monotonic deadlines are invalid."""

        return self._generation

    def persist_accepted(
        self,
        request_id: str,
        *,
        service_t0_monotonic_ns: int,
        deadline_monotonic_ns: int,
    ) -> bool:
        """Persist service acceptance and verify it through a fresh read.

        This method matches the future service's ``persist_accepted`` seam.
        Call it only after the server receives and authenticates its fixed
        request. The service must sample T0 first and may start its worker only
        when this method returns literal ``True``. The only accepted operation
        is :data:`GUARDIAN_FIXED_OPERATION`, and D must equal the code-owned
        ``T0 + GUARDIAN_REQUEST_BUDGET_NS``.
        """

        self._ensure_open()
        self._validate_request_id(request_id)
        if (
            type(service_t0_monotonic_ns) is not int
            or service_t0_monotonic_ns < 0
            or type(deadline_monotonic_ns) is not int
            or deadline_monotonic_ns != service_t0_monotonic_ns + GUARDIAN_REQUEST_BUDGET_NS
        ):
            raise GuardianRequestJournalError("guardian_request_deadline_invalid")
        try:
            with self._transaction(write=True) as connection:
                self._assert_current_generation(connection)
                duplicate = connection.execute(
                    "SELECT 1 FROM " + self._REQUEST_TABLE + " WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if duplicate is not None:
                    raise GuardianRequestJournalError("guardian_request_id_duplicate")
                blocker = connection.execute(
                    "SELECT state FROM "
                    + self._REQUEST_TABLE
                    + " WHERE state IN ('RUNNING', 'UNKNOWN') LIMIT 1"
                ).fetchone()
                if blocker is not None:
                    reason = (
                        "guardian_request_unknown_blocks"
                        if blocker[0] == "UNKNOWN"
                        else "guardian_request_in_flight"
                    )
                    raise GuardianRequestJournalError(reason)
                if time.monotonic_ns() >= deadline_monotonic_ns:
                    raise GuardianRequestJournalError("guardian_request_deadline_expired")
                connection.execute(
                    "INSERT INTO "
                    + self._REQUEST_TABLE
                    + " (request_id, operation, state, accepted_generation, "
                    "accepted_monotonic_ns, deadline_monotonic_ns) "
                    "VALUES (?, ?, 'RUNNING', ?, ?, ?)",
                    (
                        request_id,
                        GUARDIAN_FIXED_OPERATION,
                        self._generation,
                        service_t0_monotonic_ns,
                        deadline_monotonic_ns,
                    ),
                )
        except GuardianRequestJournalError:
            raise

        # A second connection is the read-back gate for any future worker.
        # No provider request is issued by this module.
        record = self.get_request(request_id)
        if (
            record is None
            or record.state != "RUNNING"
            or record.accepted_generation != self._generation
            or record.accepted_monotonic_ns != service_t0_monotonic_ns
            or record.deadline_monotonic_ns != deadline_monotonic_ns
        ):
            raise GuardianRequestJournalError("guardian_request_accept_readback_failed")
        if time.monotonic_ns() >= deadline_monotonic_ns:
            self.mark_unknown(request_id, "deadline_expired")
            return False
        return True

    def record_observed(self, request_id: str, receipt_digest: str) -> GuardianRequestRecord:
        """Persist a verified observation before its fixed monotonic deadline.

        The digest is only a content identifier. This module cannot authenticate
        the receipt or mint trusted evidence. In particular, no call can move
        a terminal ``UNKNOWN`` row to ``OBSERVED``.
        """

        self._ensure_open()
        self._validate_request_id(request_id)
        if type(receipt_digest) is not str or _SHA256_RE.fullmatch(receipt_digest) is None:
            raise GuardianRequestJournalError("guardian_request_receipt_digest_invalid")

        now_ns = time.monotonic_ns()
        deadline_expired = False
        try:
            with self._transaction(write=True) as connection:
                self._assert_current_generation(connection)
                row = self._select_request(connection, request_id)
                if row is None:
                    raise GuardianRequestJournalError("guardian_request_not_found")
                record = self._record_from_row(row)
                if record.state == "UNKNOWN":
                    raise GuardianRequestJournalError("guardian_request_unknown_terminal")
                if record.state == "OBSERVED":
                    if record.receipt_digest != receipt_digest:
                        raise GuardianRequestJournalError(
                            "guardian_request_terminal_digest_conflict"
                        )
                    return record
                if record.accepted_generation != self._generation:
                    raise GuardianRequestJournalError("guardian_request_generation_lost")
                if now_ns >= record.deadline_monotonic_ns:
                    self._write_unknown(
                        connection,
                        record,
                        reason="deadline_expired",
                        terminal_ns=now_ns,
                    )
                    deadline_expired = True
                else:
                    connection.execute(
                        "UPDATE "
                        + self._REQUEST_TABLE
                        + " SET state = 'OBSERVED', terminal_generation = ?, "
                        "terminal_monotonic_ns = ?, receipt_digest = ?, terminal_reason = NULL "
                        "WHERE request_id = ? AND state = 'RUNNING'",
                        (self._generation, now_ns, receipt_digest, request_id),
                    )
        except GuardianRequestJournalError:
            raise

        if deadline_expired:
            raise GuardianRequestJournalError("guardian_request_deadline_expired")

        record = self.get_request(request_id)
        if record is None or record.state != "OBSERVED" or record.receipt_digest != receipt_digest:
            raise GuardianRequestJournalError("guardian_request_observation_readback_failed")
        # A slow commit/read-back that crossed D is conservatively downgraded.
        # SQLite FULL cannot bound arbitrary device or kernel stalls, so this
        # guard is best effort and is not a hard real-time guarantee.
        if time.monotonic_ns() >= record.deadline_monotonic_ns:
            self._downgrade_late_observation(record)
            raise GuardianRequestJournalError("guardian_request_deadline_expired")
        return record

    def mark_unknown(self, request_id: str, reason: str) -> GuardianRequestRecord:
        """Make an in-flight request terminally uncertain; never clears UNKNOWN."""

        self._ensure_open()
        self._validate_request_id(request_id)
        if type(reason) is not str or reason not in _UNKNOWN_REASONS:
            raise GuardianRequestJournalError("guardian_request_unknown_reason_invalid")
        now_ns = time.monotonic_ns()
        try:
            with self._transaction(write=True) as connection:
                self._assert_current_generation(connection)
                row = self._select_request(connection, request_id)
                if row is None:
                    raise GuardianRequestJournalError("guardian_request_not_found")
                record = self._record_from_row(row)
                if record.state == "UNKNOWN":
                    return record
                if record.state == "OBSERVED":
                    raise GuardianRequestJournalError("guardian_request_terminal_state")
                if record.accepted_generation != self._generation:
                    raise GuardianRequestJournalError("guardian_request_generation_lost")
                self._write_unknown(connection, record, reason=reason, terminal_ns=now_ns)
        except GuardianRequestJournalError:
            raise
        record = self.get_request(request_id)
        if record is None or record.state != "UNKNOWN":
            raise GuardianRequestJournalError("guardian_request_unknown_readback_failed")
        return record

    def get_request(self, request_id: str) -> Optional[GuardianRequestRecord]:
        """Read one local request record, raising if durable state is unavailable."""

        self._ensure_open()
        self._validate_request_id(request_id)
        try:
            with self._transaction(write=False) as connection:
                row = self._select_request(connection, request_id)
                return None if row is None else self._record_from_row(row)
        except GuardianRequestJournalError:
            raise

    def has_blocker(self) -> bool:
        """Return whether any in-flight or unknown row blocks further admission."""

        self._ensure_open()
        try:
            with self._transaction(write=False) as connection:
                row = connection.execute(
                    "SELECT 1 FROM "
                    + self._REQUEST_TABLE
                    + " WHERE state IN ('RUNNING', 'UNKNOWN') LIMIT 1"
                ).fetchone()
                return row is not None
        except GuardianRequestJournalError:
            raise

    def close(self) -> None:
        """Close this handle; the class holds no long-lived SQLite connection."""

        self._closed = True

    def __enter__(self) -> "GuardianRequestJournal":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _initialize_and_recover(self) -> None:
        try:
            with self._transaction(write=True, initializing=True) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()
                if version not in ((0,), (GUARDIAN_REQUEST_SCHEMA_VERSION,)):
                    raise GuardianRequestJournalError("guardian_journal_schema_invalid")
                if version == (0,):
                    names = frozenset(
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table' "
                            "AND name NOT LIKE 'sqlite_%'"
                        ).fetchall()
                    )
                    if names:
                        raise GuardianRequestJournalError("guardian_journal_schema_invalid")
                    self._create_schema(connection)
                    connection.execute(
                        "INSERT INTO "
                        + self._META_TABLE
                        + " (singleton, schema_version, identity, generation) VALUES (1, ?, ?, ?)",
                        (GUARDIAN_REQUEST_SCHEMA_VERSION, self._identity, self._generation),
                    )
                    connection.execute(
                        "PRAGMA user_version = " + str(GUARDIAN_REQUEST_SCHEMA_VERSION)
                    )
                    return

                self._validate_schema(connection)
                meta = connection.execute(
                    "SELECT schema_version, identity FROM "
                    + self._META_TABLE
                    + " WHERE singleton = 1"
                ).fetchone()
                if meta != (GUARDIAN_REQUEST_SCHEMA_VERSION, self._identity):
                    raise GuardianRequestJournalError("guardian_journal_identity_mismatch")

                now_ns = time.monotonic_ns()
                rows = connection.execute(
                    "SELECT request_id, operation, accepted_generation, accepted_monotonic_ns, "
                    "deadline_monotonic_ns, terminal_generation, terminal_monotonic_ns, "
                    "receipt_digest, terminal_reason "
                    "FROM " + self._REQUEST_TABLE + " WHERE state = 'RUNNING'"
                ).fetchall()
                for row in rows:
                    record = self._record_from_row((row[0], row[1], "RUNNING") + tuple(row[2:]))
                    self._write_unknown(
                        connection,
                        record,
                        reason="restart_recovery",
                        terminal_ns=now_ns,
                    )
                connection.execute(
                    "UPDATE " + self._META_TABLE + " SET generation = ? WHERE singleton = 1",
                    (self._generation,),
                )
        except GuardianRequestJournalError:
            raise

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE "
            + self._META_TABLE
            + " (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "schema_version INTEGER NOT NULL, identity TEXT NOT NULL, generation TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE "
            + self._REQUEST_TABLE
            + " (request_id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
            "state TEXT NOT NULL CHECK (state IN ('RUNNING', 'OBSERVED', 'UNKNOWN')), "
            "accepted_generation TEXT NOT NULL, accepted_monotonic_ns INTEGER NOT NULL, "
            "deadline_monotonic_ns INTEGER NOT NULL, terminal_generation TEXT, "
            "terminal_monotonic_ns INTEGER, receipt_digest TEXT, terminal_reason TEXT, "
            "CHECK (deadline_monotonic_ns > accepted_monotonic_ns), "
            "CHECK ((state = 'RUNNING' AND terminal_generation IS NULL "
            "AND terminal_monotonic_ns IS NULL AND receipt_digest IS NULL "
            "AND terminal_reason IS NULL) OR (state IN ('OBSERVED', 'UNKNOWN') "
            "AND terminal_generation IS NOT NULL AND terminal_monotonic_ns IS NOT NULL "
            "AND receipt_digest IS NOT NULL)))"
        )

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        names = frozenset(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        if names != _APPLICATION_TABLES:
            raise GuardianRequestJournalError("guardian_journal_schema_invalid")
        meta_columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(" + self._META_TABLE + ")")
        )
        request_columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(" + self._REQUEST_TABLE + ")")
        )
        if meta_columns != ("singleton", "schema_version", "identity", "generation"):
            raise GuardianRequestJournalError("guardian_journal_schema_invalid")
        if request_columns != (
            "request_id",
            "operation",
            "state",
            "accepted_generation",
            "accepted_monotonic_ns",
            "deadline_monotonic_ns",
            "terminal_generation",
            "terminal_monotonic_ns",
            "receipt_digest",
            "terminal_reason",
        ):
            raise GuardianRequestJournalError("guardian_journal_schema_invalid")

    @contextmanager
    def _transaction(
        self, *, write: bool, initializing: bool = False
    ) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._ensure_open()
            connection: Optional[sqlite3.Connection] = None
            try:
                self._verify_database_identity()
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                if not initializing:
                    self._assert_identity(connection)
                    if write:
                        self._assert_current_generation(connection)
                yield connection
                self._verify_database_identity()
                connection.execute("COMMIT")
                self._verify_database_identity()
            except GuardianRequestJournalError:
                if connection is not None and connection.in_transaction:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise
            except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
                if connection is not None and connection.in_transaction:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise GuardianRequestJournalError("guardian_journal_unavailable") from exc
            finally:
                if connection is not None:
                    connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection: Optional[sqlite3.Connection] = None
        try:
            connection = sqlite3.connect(
                str(self._path),
                timeout=GUARDIAN_REQUEST_BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            connection.execute("PRAGMA busy_timeout = " + str(self._BUSY_TIMEOUT_MS))
            connection.execute("PRAGMA foreign_keys = ON")
            if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                raise GuardianRequestJournalError("guardian_journal_database_invalid")
            if connection.execute("PRAGMA journal_mode = DELETE").fetchone() != ("delete",):
                raise GuardianRequestJournalError("guardian_journal_database_invalid")
            connection.execute("PRAGMA synchronous = FULL")
            if connection.execute("PRAGMA synchronous").fetchone() != (2,):
                raise GuardianRequestJournalError("guardian_journal_database_invalid")
            check = connection.execute("PRAGMA quick_check").fetchall()
            if check != [("ok",)]:
                raise GuardianRequestJournalError("guardian_journal_database_corrupt")
            self._verify_database_identity()
            return connection
        except BaseException:
            if connection is not None:
                connection.close()
            raise

    def _assert_identity(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()
        meta = connection.execute(
            "SELECT schema_version, identity FROM " + self._META_TABLE + " WHERE singleton = 1"
        ).fetchone()
        if version != (GUARDIAN_REQUEST_SCHEMA_VERSION,) or meta != (
            GUARDIAN_REQUEST_SCHEMA_VERSION,
            self._identity,
        ):
            raise GuardianRequestJournalError("guardian_journal_identity_mismatch")

    def _assert_current_generation(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT generation FROM " + self._META_TABLE + " WHERE singleton = 1"
        ).fetchone()
        if row != (self._generation,):
            raise GuardianRequestJournalError("guardian_request_generation_lost")

    def _select_request(
        self, connection: sqlite3.Connection, request_id: str
    ) -> Optional[tuple[object, ...]]:
        return connection.execute(
            "SELECT request_id, operation, state, accepted_generation, "
            "accepted_monotonic_ns, deadline_monotonic_ns, terminal_generation, "
            "terminal_monotonic_ns, receipt_digest, terminal_reason "
            "FROM " + self._REQUEST_TABLE + " WHERE request_id = ?",
            (request_id,),
        ).fetchone()

    def _record_from_row(self, row: tuple[object, ...]) -> GuardianRequestRecord:
        return GuardianRequestRecord(
            request_id=str(row[0]),
            identity=self._identity,
            operation=str(row[1]),
            state=str(row[2]),
            accepted_generation=str(row[3]),
            accepted_monotonic_ns=int(row[4]),
            deadline_monotonic_ns=int(row[5]),
            terminal_generation=None if row[6] is None else str(row[6]),
            terminal_monotonic_ns=None if row[7] is None else int(row[7]),
            receipt_digest=None if row[8] is None else str(row[8]),
            terminal_reason=None if row[9] is None else str(row[9]),
        )

    def _public_record(self, row: tuple[object, ...]) -> GuardianRequestRecord:
        record = self._record_from_row(row)
        return GuardianRequestRecord(
            request_id=record.request_id,
            identity=self._identity,
            operation=record.operation,
            state=record.state,
            accepted_generation=record.accepted_generation,
            accepted_monotonic_ns=record.accepted_monotonic_ns,
            deadline_monotonic_ns=record.deadline_monotonic_ns,
            terminal_generation=record.terminal_generation,
            terminal_monotonic_ns=record.terminal_monotonic_ns,
            receipt_digest=record.receipt_digest,
            terminal_reason=record.terminal_reason,
        )

    def _write_unknown(
        self,
        connection: sqlite3.Connection,
        record: GuardianRequestRecord,
        *,
        reason: str,
        terminal_ns: int,
    ) -> None:
        digest = _unknown_receipt_digest(
            identity=self._identity,
            request_id=record.request_id,
            operation=record.operation,
            accepted_generation=record.accepted_generation,
            terminal_generation=self._generation,
            reason=reason,
            terminal_ns=terminal_ns,
        )
        cursor = connection.execute(
            "UPDATE "
            + self._REQUEST_TABLE
            + " SET state = 'UNKNOWN', terminal_generation = ?, terminal_monotonic_ns = ?, "
            "receipt_digest = ?, terminal_reason = ? "
            "WHERE request_id = ? AND state = 'RUNNING'",
            (self._generation, terminal_ns, digest, reason, record.request_id),
        )
        if cursor.rowcount != 1:
            raise GuardianRequestJournalError("guardian_request_transition_conflict")

    def _downgrade_late_observation(self, record: GuardianRequestRecord) -> None:
        now_ns = time.monotonic_ns()
        try:
            with self._transaction(write=True) as connection:
                row = self._select_request(connection, record.request_id)
                if row is None:
                    raise GuardianRequestJournalError("guardian_request_not_found")
                current = self._public_record(row)
                if current.state == "UNKNOWN":
                    return
                if (
                    current.state != "OBSERVED"
                    or current.receipt_digest != record.receipt_digest
                    or current.accepted_generation != self._generation
                    or current.terminal_generation != self._generation
                ):
                    raise GuardianRequestJournalError("guardian_request_transition_conflict")
                digest = _unknown_receipt_digest(
                    identity=self._identity,
                    request_id=current.request_id,
                    operation=current.operation,
                    accepted_generation=current.accepted_generation,
                    terminal_generation=self._generation,
                    reason="deadline_expired",
                    terminal_ns=now_ns,
                )
                cursor = connection.execute(
                    "UPDATE "
                    + self._REQUEST_TABLE
                    + " SET state = 'UNKNOWN', terminal_generation = ?, "
                    "terminal_monotonic_ns = ?, receipt_digest = ?, terminal_reason = ? "
                    "WHERE request_id = ? AND state = 'OBSERVED' "
                    "AND accepted_generation = ? AND terminal_generation = ? "
                    "AND receipt_digest = ?",
                    (
                        self._generation,
                        now_ns,
                        digest,
                        "deadline_expired",
                        current.request_id,
                        self._generation,
                        self._generation,
                        record.receipt_digest,
                    ),
                )
                if cursor.rowcount != 1:
                    raise GuardianRequestJournalError("guardian_request_transition_conflict")
        except GuardianRequestJournalError:
            raise

    def _verify_state_directory(self) -> tuple[tuple[str, int, int], ...]:
        absolute = self._state_dir
        if not absolute.is_absolute() or not absolute.name:
            raise GuardianRequestJournalError("guardian_journal_config_invalid")
        if os.name == "nt":
            self._require_windows_fixed_volume(absolute)

        current = Path(absolute.anchor)
        paths = [current]
        for part in absolute.parts:
            if part == absolute.anchor:
                continue
            current = current / part
            paths.append(current)

        identities = []
        for directory in paths:
            try:
                entry = os.lstat(str(directory))
            except OSError as exc:
                raise GuardianRequestJournalError("guardian_journal_config_invalid") from exc
            if _is_link_or_reparse(entry) or not stat.S_ISDIR(entry.st_mode):
                raise GuardianRequestJournalError("guardian_journal_config_invalid")
            identities.append((os.path.normcase(str(directory)),) + _file_identity(entry))

        state_entry = os.lstat(str(absolute))
        if os.name != "nt":
            mode = stat.S_IMODE(state_entry.st_mode)
            if (
                state_entry.st_uid != os.geteuid()
                or mode & 0o077
                or mode & stat.S_IRUSR == 0
                or mode & stat.S_IWUSR == 0
                or mode & stat.S_IXUSR == 0
            ):
                raise GuardianRequestJournalError("guardian_journal_permissions_invalid")
        else:
            self._verify_windows_private_directory(absolute)
        return tuple(identities)

    def _prepare_database_file(self) -> tuple[int, int]:
        created = False
        try:
            entry = os.lstat(str(self._path))
        except FileNotFoundError:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(str(self._path), flags, 0o600)
            except FileExistsError:
                descriptor = None
            if descriptor is not None:
                created = True
                try:
                    if hasattr(os, "fchmod"):
                        os.fchmod(descriptor, 0o600)
                    opened = os.fstat(descriptor)
                    if not stat.S_ISREG(opened.st_mode):
                        raise GuardianRequestJournalError("guardian_journal_path_invalid")
                finally:
                    os.close(descriptor)
            try:
                entry = os.lstat(str(self._path))
            except OSError as exc:
                raise GuardianRequestJournalError("guardian_journal_path_invalid") from exc
        except OSError as exc:
            raise GuardianRequestJournalError("guardian_journal_path_invalid") from exc

        if _is_link_or_reparse(entry) or not stat.S_ISREG(entry.st_mode):
            raise GuardianRequestJournalError("guardian_journal_path_invalid")
        if getattr(entry, "st_nlink", 1) != 1:
            raise GuardianRequestJournalError("guardian_journal_path_invalid")
        if os.name != "nt":
            mode = stat.S_IMODE(entry.st_mode)
            if (
                entry.st_uid != os.geteuid()
                or mode & 0o077
                or mode & stat.S_IRUSR == 0
                or mode & stat.S_IWUSR == 0
            ):
                raise GuardianRequestJournalError("guardian_journal_permissions_invalid")
        else:
            if created:
                self._secure_windows_database(entry)
            else:
                self._verify_windows_private_database(entry)
        return _file_identity(entry)

    def _verify_database_identity(self) -> None:
        if self._verify_state_directory() != self._directory_identity:
            raise GuardianRequestJournalError("guardian_journal_path_changed")
        try:
            entry = os.lstat(str(self._path))
        except OSError as exc:
            raise GuardianRequestJournalError("guardian_journal_path_unavailable") from exc
        if (
            _is_link_or_reparse(entry)
            or not stat.S_ISREG(entry.st_mode)
            or getattr(entry, "st_nlink", 1) != 1
            or _file_identity(entry) != self._database_identity
        ):
            raise GuardianRequestJournalError("guardian_journal_path_changed")
        if os.name != "nt":
            mode = stat.S_IMODE(entry.st_mode)
            if (
                entry.st_uid != os.geteuid()
                or mode & 0o077
                or mode & stat.S_IRUSR == 0
                or mode & stat.S_IWUSR == 0
            ):
                raise GuardianRequestJournalError("guardian_journal_permissions_invalid")
        else:
            self._verify_windows_private_database(entry)
        self._verify_sidecars()

    def _secure_windows_database(self, entry: os.stat_result) -> None:
        """Harden a new SQLite file and verify its own handle ACL."""

        try:
            from .ctp_simnow_signed_review import _protect_windows_path_acl

            _protect_windows_path_acl(self._path, is_directory=False)
            after = os.lstat(str(self._path))
            if _is_link_or_reparse(after) or _file_identity(after) != _file_identity(entry):
                raise GuardianRequestJournalError("guardian_journal_path_changed")
            self._verify_windows_private_database(after)
        except GuardianRequestJournalError:
            raise
        except Exception as exc:
            raise GuardianRequestJournalError("guardian_journal_permissions_invalid") from exc

    def _verify_windows_private_database(self, entry: os.stat_result) -> None:
        """Verify the database file's own protected owner-only ACL by handle."""

        try:
            from .credential_resolver import _open_windows_metadata_handle, _windows_acl_for_handle
            from .credential_resolver import _windows_os_handle

            descriptor = _open_windows_metadata_handle(self._path, is_directory=False)
            try:
                opened = os.fstat(descriptor)
                if _file_identity(opened) != _file_identity(entry):
                    raise GuardianRequestJournalError("guardian_journal_path_changed")
                _windows_acl_for_handle(_windows_os_handle(descriptor))
                after = os.lstat(str(self._path))
                if _is_link_or_reparse(after) or _file_identity(after) != _file_identity(opened):
                    raise GuardianRequestJournalError("guardian_journal_path_changed")
            finally:
                os.close(descriptor)
        except GuardianRequestJournalError:
            raise
        except Exception as exc:
            raise GuardianRequestJournalError("guardian_journal_permissions_invalid") from exc

    def _verify_sidecars(self) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(self._path) + suffix)
            try:
                entry = os.lstat(str(sidecar))
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise GuardianRequestJournalError("guardian_journal_sidecar_invalid") from exc
            if (
                _is_link_or_reparse(entry)
                or not stat.S_ISREG(entry.st_mode)
                or getattr(entry, "st_nlink", 1) != 1
            ):
                raise GuardianRequestJournalError("guardian_journal_sidecar_invalid")
            if os.name != "nt" and stat.S_IMODE(entry.st_mode) & 0o077:
                raise GuardianRequestJournalError("guardian_journal_permissions_invalid")
            if os.name == "nt":
                self._verify_windows_private_sidecar(sidecar, entry)
            if suffix in ("-wal", "-shm"):
                raise GuardianRequestJournalError("guardian_journal_wal_unsupported")

    def _verify_windows_private_sidecar(self, path: Path, entry: os.stat_result) -> None:
        """Check rollback-journal owner and every ACE on the opened handle.

        A rollback journal inherits the already-verified private directory ACL.
        Windows may mark its DACL inherited rather than protected, so this
        accepts inherited ACEs only for the current user, SYSTEM, and local
        Administrators. Broad trustees fail closed.
        """

        try:
            from .credential_resolver import _open_windows_metadata_handle, _windows_os_handle
            from .ctp_simnow_signed_review import _windows_acl_details_for_handle

            descriptor = _open_windows_metadata_handle(path, is_directory=False)
            try:
                opened = os.fstat(descriptor)
                if _file_identity(opened) != _file_identity(entry):
                    raise GuardianRequestJournalError("guardian_journal_path_changed")
                owner, current_user, _protected, entries = _windows_acl_details_for_handle(
                    _windows_os_handle(descriptor)
                )
                _validate_windows_sqlite_sidecar_acl(owner, current_user, entries)
                after = os.lstat(str(path))
                if _is_link_or_reparse(after) or _file_identity(after) != _file_identity(opened):
                    raise GuardianRequestJournalError("guardian_journal_path_changed")
            finally:
                os.close(descriptor)
        except GuardianRequestJournalError:
            raise
        except Exception as exc:
            raise GuardianRequestJournalError("guardian_journal_permissions_invalid") from exc

    def _verify_windows_private_directory(self, directory: Path) -> None:
        try:
            from .credential_resolver import _open_windows_metadata_handle, _windows_acl_for_handle
            from .credential_resolver import _windows_os_handle

            descriptor = _open_windows_metadata_handle(directory, is_directory=True)
            try:
                _windows_acl_for_handle(_windows_os_handle(descriptor))
                if _is_link_or_reparse(os.lstat(str(directory))):
                    raise GuardianRequestJournalError("guardian_journal_config_invalid")
            finally:
                os.close(descriptor)
        except GuardianRequestJournalError:
            raise
        except Exception as exc:
            raise GuardianRequestJournalError("guardian_journal_permissions_invalid") from exc

    @staticmethod
    def _require_windows_fixed_volume(path: Path) -> None:
        drive, _tail = ntpath.splitdrive(os.fspath(path))
        if not re.fullmatch(r"[A-Za-z]:", drive):
            raise GuardianRequestJournalError("guardian_journal_local_volume_required")
        try:
            get_drive_type = ctypes.WinDLL("Kernel32", use_last_error=True).GetDriveTypeW
            get_drive_type.argtypes = (ctypes.c_wchar_p,)
            get_drive_type.restype = ctypes.c_uint
            drive_type = int(get_drive_type(drive + "\\"))
        except Exception as exc:
            raise GuardianRequestJournalError("guardian_journal_local_volume_required") from exc
        if drive_type != _WINDOWS_FIXED_DRIVE:
            raise GuardianRequestJournalError("guardian_journal_local_volume_required")

    @staticmethod
    def _validate_request_id(request_id: str) -> None:
        if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
            raise GuardianRequestJournalError("guardian_request_id_invalid")

    def _ensure_open(self) -> None:
        if self._closed:
            raise GuardianRequestJournalError("guardian_journal_closed")


def _is_link_or_reparse(result: os.stat_result) -> bool:
    attributes = getattr(result, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_point)


def _file_identity(result: os.stat_result) -> tuple[int, int]:
    return int(result.st_dev), int(result.st_ino)


def _unknown_receipt_digest(
    *,
    identity: str,
    request_id: str,
    operation: str,
    accepted_generation: str,
    terminal_generation: str,
    reason: str,
    terminal_ns: int,
) -> str:
    """Hash a local UNKNOWN transition marker; this is not provider evidence."""

    payload = json.dumps(
        {
            "accepted_generation": accepted_generation,
            "identity": identity,
            "operation": operation,
            "reason": reason,
            "request_id": request_id,
            "terminal_generation": terminal_generation,
            "terminal_monotonic_ns": terminal_ns,
            "version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(b"guardian-request-unknown-v1\0" + payload).hexdigest()


def _validate_windows_sqlite_sidecar_acl(
    owner_sid: str,
    current_user_sid: str,
    entries: tuple[tuple[int, int, int, str], ...],
) -> None:
    """Require a rollback sidecar ACL inherited only from the private root."""

    allowed_sids = {current_user_sid, "S-1-5-18", "S-1-5-32-544"}
    if owner_sid != current_user_sid or not entries:
        raise GuardianRequestJournalError("guardian_journal_permissions_invalid")
    for ace_type, ace_flags, _mask, trustee_sid in entries:
        if ace_type not in (0, 1) or ace_flags & ~0x1F or trustee_sid not in allowed_sids:
            raise GuardianRequestJournalError("guardian_journal_permissions_invalid")


__all__ = [
    "GUARDIAN_READ_ONLY_OPERATIONS",
    "GUARDIAN_REQUEST_BUDGET_NS",
    "GUARDIAN_REQUEST_BUDGET_SECONDS",
    "GUARDIAN_REQUEST_DATABASE_NAME",
    "GUARDIAN_REQUEST_SCHEMA_VERSION",
    "GUARDIAN_REQUEST_TRADING_CAPABILITIES",
    "GUARDIAN_REQUEST_WRITE_AUTHORIZED",
    "GuardianRequestJournal",
    "GuardianRequestJournalError",
    "GuardianRequestRecord",
]
