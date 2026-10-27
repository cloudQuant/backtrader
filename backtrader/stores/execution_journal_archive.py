"""Bounded, verified SQLite snapshots for an execution decision journal.

The archive is a complete, standalone SQLite backup.  This module never
deletes or rotates the source journal and never exposes row contents in its
receipt.
"""

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple


DEFAULT_ARCHIVE_TIMEOUT_SECONDS = 30.0
MAX_ARCHIVE_TIMEOUT_SECONDS = 300.0
_BACKUP_PAGES = 128
_BACKUP_SLEEP_SECONDS = 0.01
_HASH_CHUNK_BYTES = 1024 * 1024
_REQUIRED_TABLES = frozenset(
    {
        "execution_decisions",
        "execution_decision_slots",
        "execution_decision_intents",
        "execution_native_intent_identities",
        "execution_decision_callbacks",
        "execution_intent_reconciliations",
        "execution_intent_resolutions",
        "execution_instrument_owners",
    }
)
_REQUIRED_TABLES_BY_MINIMUM_SCHEMA_VERSION = {
    12: frozenset(
        {
            "execution_durable_capacity_limits",
            "execution_durable_capacity_usage",
        }
    ),
    13: frozenset({"execution_run_loss_guards"}),
    14: frozenset({"execution_source_highwaters"}),
    15: frozenset(
        {
            "execution_fee_pair_required_scopes",
            "execution_fee_pair_scope_events",
        }
    ),
    16: frozenset(
        {
            "execution_fee_pair_candidates",
            "execution_fee_pair_candidate_events",
            "execution_fee_pair_candidate_capacity_reservations",
        }
    ),
}


def _required_tables_for_schema_version(schema_version: int) -> frozenset[str]:
    required = set(_REQUIRED_TABLES)
    for minimum_version, tables in _REQUIRED_TABLES_BY_MINIMUM_SCHEMA_VERSION.items():
        if schema_version >= minimum_version:
            required.update(tables)
    return frozenset(required)


def _validate_required_schema_objects(
    connection: sqlite3.Connection,
    schema_version: int,
    *,
    tables: Optional[Tuple[str, ...]] = None,
) -> Tuple[str, ...]:
    """Require cumulative tables and exact fee-pair schema for each version."""

    if tables is None:
        _schema_sha256, tables = _schema_fingerprint(connection)
    if not _required_tables_for_schema_version(schema_version).issubset(tables):
        raise ExecutionJournalArchiveError("ARCHIVE_SCHEMA_INCOMPLETE")
    if schema_version < 14:
        return tables

    # Import at verification time: the journal imports this archive module,
    # while its validator and declarations are authoritative for fee-pair
    # schemas. Each validator checks exact DDL/columns and rejects unexpected
    # triggers on its tables.
    from . import execution_decision_journal as journal_module

    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    try:
        journal_module.ExecutionDecisionJournal._validate_source_highwater_schema(cursor)
        if schema_version >= 15:
            journal_module.ExecutionDecisionJournal._validate_fee_pair_scope_schema(cursor)
        if schema_version >= 16:
            journal_module.ExecutionDecisionJournal._validate_fee_pair_candidate_schema(cursor)
    except journal_module.ExecutionDecisionJournalError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_SCHEMA_INCOMPLETE") from error
    finally:
        cursor.close()
    return tables


class ExecutionJournalArchiveError(RuntimeError):
    """A verified journal snapshot could not be produced or validated."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionJournalArchiveReceipt:
    """Non-row metadata for a complete, verified journal snapshot."""

    path: Path
    sha256: str
    size_bytes: int
    schema_version: int
    schema_sha256: str
    table_row_counts: Mapping[str, int]


def validate_archive_timeout(timeout_seconds: object) -> float:
    if type(timeout_seconds) not in (int, float):
        raise ExecutionJournalArchiveError("ARCHIVE_TIMEOUT_INVALID")
    try:
        timeout = float(timeout_seconds)
    except (OverflowError, ValueError) as error:
        raise ExecutionJournalArchiveError("ARCHIVE_TIMEOUT_INVALID") from error
    if not math.isfinite(timeout) or not 0.001 <= timeout <= MAX_ARCHIVE_TIMEOUT_SECONDS:
        raise ExecutionJournalArchiveError("ARCHIVE_TIMEOUT_INVALID")
    return timeout


def create_verified_execution_journal_archive(
    source: sqlite3.Connection,
    destination: object,
    *,
    expected_schema_version: int,
    timeout_seconds: float = DEFAULT_ARCHIVE_TIMEOUT_SECONDS,
    source_path: Optional[object] = None,
) -> ExecutionJournalArchiveReceipt:
    """Back up ``source`` to an exclusive destination and verify it read-only.

    The caller owns the source connection lock.  A same-directory temporary
    database is removed on every failed path; the public destination is linked
    into place only after the snapshot passes read-only verification. The
    deadline is cooperative: it is checked between backup, verification, and
    file-read steps, but cannot interrupt a single SQLite or filesystem call.
    """

    timeout = validate_archive_timeout(timeout_seconds)
    if type(expected_schema_version) is not int or expected_schema_version < 1:
        raise ExecutionJournalArchiveError("ARCHIVE_SCHEMA_VERSION_INVALID")
    if not isinstance(source, sqlite3.Connection):
        raise ExecutionJournalArchiveError("ARCHIVE_SOURCE_INVALID")
    if source.in_transaction:
        raise ExecutionJournalArchiveError("ARCHIVE_SOURCE_TRANSACTION_ACTIVE")

    target_path = _destination_path(destination)
    if source_path is not None:
        try:
            normalized_source = Path(source_path).expanduser().resolve(strict=False)
        except (OSError, TypeError, ValueError) as error:
            raise ExecutionJournalArchiveError("ARCHIVE_SOURCE_PATH_INVALID") from error
        if target_path == normalized_source:
            raise ExecutionJournalArchiveError("ARCHIVE_DESTINATION_IS_SOURCE")
    if target_path.exists() or target_path.is_symlink():
        raise ExecutionJournalArchiveError("ARCHIVE_DESTINATION_EXISTS")
    if not target_path.parent.is_dir():
        raise ExecutionJournalArchiveError("ARCHIVE_PARENT_UNAVAILABLE")

    deadline = time.monotonic() + timeout
    temporary_path: Optional[Path] = None
    temporary_identity: Optional[Tuple[int, int]] = None
    published_identity: Optional[Tuple[int, int]] = None
    target: Optional[sqlite3.Connection] = None
    published = False
    completed = False
    try:
        try:
            descriptor, raw_temporary_path = tempfile.mkstemp(
                prefix=".execution-journal-archive-",
                suffix=".partial",
                dir=str(target_path.parent),
            )
            temporary_path = Path(raw_temporary_path)
            try:
                temporary_identity = _descriptor_identity(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise ExecutionJournalArchiveError("ARCHIVE_TEMP_CREATE_FAILED") from error

        _require_before_deadline(deadline)
        try:
            target = sqlite3.connect(str(temporary_path), isolation_level=None)
            target.execute("PRAGMA journal_mode = DELETE")
            target.execute("PRAGMA synchronous = FULL")

            def report_progress(status: int, remaining: int, total: int) -> None:
                del status, remaining, total
                _require_before_deadline(deadline)

            source.backup(
                target,
                pages=_BACKUP_PAGES,
                progress=report_progress,
                sleep=_BACKUP_SLEEP_SECONDS,
            )
            journal_mode = target.execute("PRAGMA journal_mode = DELETE").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "delete":
                raise ExecutionJournalArchiveError("ARCHIVE_JOURNAL_MODE_UNSUPPORTED")
            _require_before_deadline(deadline)
        except ExecutionJournalArchiveError:
            raise
        except (sqlite3.Error, OSError) as error:
            raise ExecutionJournalArchiveError("ARCHIVE_BACKUP_FAILED") from error
        finally:
            if target is not None:
                try:
                    target.close()
                except sqlite3.Error:
                    if temporary_path is not None:
                        _remove_if_present(temporary_path)
                    raise ExecutionJournalArchiveError("ARCHIVE_BACKUP_CLOSE_FAILED") from None
                target = None

        if temporary_path is None:
            raise ExecutionJournalArchiveError("ARCHIVE_TEMP_UNAVAILABLE")
        _require_path_identity(temporary_path, temporary_identity, "ARCHIVE_TEMP_IDENTITY_CHANGED")
        receipt = verify_execution_journal_archive(
            temporary_path,
            expected_schema_version=expected_schema_version,
            timeout_seconds=max(0.001, deadline - time.monotonic()),
        )
        _require_before_deadline(deadline)
        try:
            # Hard-link publication is atomic and fails if the destination was
            # concurrently created; it never replaces a prior archive.
            os.link(str(temporary_path), str(target_path))
            published = True
            published_identity = temporary_identity
        except FileExistsError as error:
            raise ExecutionJournalArchiveError("ARCHIVE_DESTINATION_EXISTS") from error
        except OSError as error:
            raise ExecutionJournalArchiveError("ARCHIVE_PUBLISH_FAILED") from error

        published_stat = _require_path_identity(
            target_path, published_identity, "ARCHIVE_PUBLISHED_IDENTITY_MISMATCH"
        )
        if published_stat.st_size != receipt.size_bytes:
            raise ExecutionJournalArchiveError("ARCHIVE_PUBLISHED_SIZE_MISMATCH")
        published_receipt = verify_execution_journal_archive(
            target_path,
            expected_schema_version=expected_schema_version,
            expected_sha256=receipt.sha256,
            timeout_seconds=max(0.001, deadline - time.monotonic()),
        )
        _require_path_identity(
            target_path, published_identity, "ARCHIVE_PUBLISHED_IDENTITY_MISMATCH"
        )
        if published_receipt.size_bytes != receipt.size_bytes:
            raise ExecutionJournalArchiveError("ARCHIVE_PUBLISHED_SIZE_MISMATCH")
        _unlink_if_same_identity(temporary_path, temporary_identity)
        _remove_if_present(Path(str(temporary_path) + "-wal"))
        _remove_if_present(Path(str(temporary_path) + "-shm"))
        completed = True
        return ExecutionJournalArchiveReceipt(
            path=target_path,
            sha256=published_receipt.sha256,
            size_bytes=published_receipt.size_bytes,
            schema_version=published_receipt.schema_version,
            schema_sha256=published_receipt.schema_sha256,
            table_row_counts=published_receipt.table_row_counts,
        )
    except ExecutionJournalArchiveError:
        raise
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_FILESYSTEM_FAILED") from error
    finally:
        if published and not completed and published_identity is not None:
            _unlink_if_same_identity(target_path, published_identity)
        if target is not None:
            try:
                target.close()
            except sqlite3.Error:
                pass
        if temporary_path is not None:
            _unlink_if_same_identity(temporary_path, temporary_identity)
            _remove_if_present(Path(str(temporary_path) + "-wal"))
            _remove_if_present(Path(str(temporary_path) + "-shm"))


def verify_execution_journal_archive(
    path: object,
    *,
    expected_schema_version: int,
    expected_sha256: Optional[str] = None,
    timeout_seconds: float = DEFAULT_ARCHIVE_TIMEOUT_SECONDS,
) -> ExecutionJournalArchiveReceipt:
    """Verify a standalone archive through a read-only SQLite connection.

    The deadline is cooperative between hash chunks and SQLite progress
    callbacks; it cannot interrupt an individual native filesystem or SQLite
    call.
    """

    timeout = validate_archive_timeout(timeout_seconds)
    if type(expected_schema_version) is not int or expected_schema_version < 1:
        raise ExecutionJournalArchiveError("ARCHIVE_SCHEMA_VERSION_INVALID")
    archive_path = _existing_regular_file(path)
    deadline = time.monotonic() + timeout
    before = _file_stat_tuple(archive_path)
    if expected_sha256 is not None:
        if (
            type(expected_sha256) is not str
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)
        ):
            raise ExecutionJournalArchiveError("ARCHIVE_EXPECTED_HASH_INVALID")
    digest = _sha256_file(archive_path, deadline)
    if expected_sha256 is not None:
        if digest != expected_sha256:
            raise ExecutionJournalArchiveError("ARCHIVE_HASH_MISMATCH")

    if Path(str(archive_path) + "-wal").exists() or Path(str(archive_path) + "-shm").exists():
        raise ExecutionJournalArchiveError("ARCHIVE_SIDECAR_PRESENT")

    connection: Optional[sqlite3.Connection] = None
    try:
        try:
            _require_before_deadline(deadline)
            connection = sqlite3.connect(
                archive_path.as_uri() + "?mode=ro",
                uri=True,
                timeout=max(0.001, min(1.0, deadline - time.monotonic())),
            )
            connection.execute("PRAGMA query_only = ON")

            def interrupt_expired_query() -> int:
                return int(time.monotonic() >= deadline)

            connection.set_progress_handler(interrupt_expired_query, 1000)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version != expected_schema_version:
                raise ExecutionJournalArchiveError("ARCHIVE_SCHEMA_VERSION_MISMATCH")
            integrity = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
            if integrity != ("ok",):
                raise ExecutionJournalArchiveError("ARCHIVE_INTEGRITY_CHECK_FAILED")
            if next(connection.execute("PRAGMA foreign_key_check"), None) is not None:
                raise ExecutionJournalArchiveError("ARCHIVE_FOREIGN_KEY_CHECK_FAILED")
            schema_sha256, tables = _schema_fingerprint(connection)
            _validate_required_schema_objects(connection, version, tables=tables)
            row_counts = _table_row_counts(connection, tables, deadline)
        except ExecutionJournalArchiveError:
            raise
        except (sqlite3.Error, OSError, ValueError) as error:
            if time.monotonic() >= deadline:
                raise ExecutionJournalArchiveError("ARCHIVE_DEADLINE_EXCEEDED") from error
            raise ExecutionJournalArchiveError("ARCHIVE_READ_ONLY_VERIFY_FAILED") from error
        finally:
            if connection is not None:
                connection.close()
                connection = None

        _require_before_deadline(deadline)
        after = _file_stat_tuple(archive_path)
        if before != after:
            raise ExecutionJournalArchiveError("ARCHIVE_CHANGED_DURING_VERIFY")
        final_digest = _sha256_file(archive_path, deadline)
        if final_digest != digest:
            raise ExecutionJournalArchiveError("ARCHIVE_CHANGED_DURING_VERIFY")
        return ExecutionJournalArchiveReceipt(
            path=archive_path,
            sha256=digest,
            size_bytes=after[0],
            schema_version=version,
            schema_sha256=schema_sha256,
            table_row_counts=MappingProxyType(row_counts),
        )
    except ExecutionJournalArchiveError:
        raise
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_FILESYSTEM_FAILED") from error
    finally:
        if connection is not None:
            connection.close()


def _destination_path(value: object) -> Path:
    try:
        raw_path = Path(value)  # type: ignore[arg-type]
        if not raw_path.name or str(value).strip() == "":
            raise ValueError("empty path")
        if raw_path.exists() and raw_path.is_dir():
            raise ValueError("destination is a directory")
        if raw_path.is_symlink():
            raise ValueError("destination is a symlink")
        return raw_path.expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError) as error:
        raise ExecutionJournalArchiveError("ARCHIVE_DESTINATION_INVALID") from error


def _existing_regular_file(value: object) -> Path:
    try:
        raw_path = Path(value)  # type: ignore[arg-type]
        if raw_path.is_symlink():
            raise ValueError("archive is a symlink")
        path = raw_path.expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("archive is not a regular file")
        return path
    except (OSError, TypeError, ValueError) as error:
        raise ExecutionJournalArchiveError("ARCHIVE_FILE_INVALID") from error


def _schema_fingerprint(connection: sqlite3.Connection) -> Tuple[str, Tuple[str, ...]]:
    rows = connection.execute(
        """SELECT type,name,tbl_name,sql FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name"""
    ).fetchall()
    encoded = "\n".join(
        "\x1f".join("" if value is None else str(value) for value in row) for row in rows
    )
    tables = tuple(
        row[1]
        for row in rows
        if row[0] == "table" and isinstance(row[1], str) and not row[1].startswith("sqlite_")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), tables


def _table_row_counts(
    connection: sqlite3.Connection, tables: Tuple[str, ...], deadline: float
) -> dict[str, int]:
    counts = {}
    for name in tables:
        _require_before_deadline(deadline)
        quoted_name = '"' + name.replace('"', '""') + '"'
        row = connection.execute("SELECT COUNT(*) FROM " + quoted_name).fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise ExecutionJournalArchiveError("ARCHIVE_TABLE_COUNT_INVALID")
        counts[name] = row[0]
    return counts


def _sha256_file(path: Path, deadline: float) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                _require_before_deadline(deadline)
                chunk = stream.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_READ_FAILED") from error
    return digest.hexdigest()


def _file_stat_tuple(path: Path) -> Tuple[int, int, int]:
    try:
        stat = path.stat()
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_FILE_INVALID") from error
    return stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0)


def _descriptor_identity(descriptor: int) -> Tuple[int, int]:
    try:
        details = os.fstat(descriptor)
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_TEMP_IDENTITY_UNAVAILABLE") from error
    if not stat.S_ISREG(details.st_mode) or not details.st_ino:
        raise ExecutionJournalArchiveError("ARCHIVE_TEMP_IDENTITY_UNAVAILABLE")
    return details.st_dev, details.st_ino


def _path_identity(path: Path) -> Tuple[os.stat_result, Tuple[int, int]]:
    try:
        details = path.lstat()
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_FILE_INVALID") from error
    if not stat.S_ISREG(details.st_mode) or not details.st_ino:
        raise ExecutionJournalArchiveError("ARCHIVE_FILE_NOT_REGULAR")
    return details, (details.st_dev, details.st_ino)


def _require_path_identity(
    path: Path, expected: Optional[Tuple[int, int]], error_code: str
) -> os.stat_result:
    if expected is None:
        raise ExecutionJournalArchiveError(error_code)
    details, identity = _path_identity(path)
    if identity != expected:
        raise ExecutionJournalArchiveError(error_code)
    return details


def _unlink_if_same_identity(path: Path, expected: Optional[Tuple[int, int]]) -> bool:
    if expected is None:
        return False
    try:
        _, identity = _path_identity(path)
        if identity != expected:
            return False
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except (OSError, ExecutionJournalArchiveError):
        return False


def _require_before_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ExecutionJournalArchiveError("ARCHIVE_DEADLINE_EXCEEDED")


def _remove_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ExecutionJournalArchiveError("ARCHIVE_CLEANUP_FAILED") from error
