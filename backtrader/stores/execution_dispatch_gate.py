"""Cross-process serialization for a journaled broker dispatch interval.

The sidecar database is intentionally separate from the execution journal.
The gate spans several journal transactions and a synchronous provider call,
so holding a transaction on the main journal would prevent those operations.
SQLite releases the sidecar's EXCLUSIVE lock when its owning process exits.
"""

from __future__ import annotations

import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Union


_MIN_TIMEOUT_SECONDS = 0.001
_MAX_TIMEOUT_SECONDS = 60.0
_GATE_TABLE = "execution_dispatch_serialization_gate"


class ExecutionDispatchGateError(RuntimeError):
    """A bounded dispatch-serialization acquisition failed closed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionDispatchGateLease:
    """Whether the lease is backed by an OS-visible persistent SQLite lock."""

    cross_process: bool


def validate_dispatch_gate_timeout(timeout_seconds: float) -> float:
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or not _MIN_TIMEOUT_SECONDS <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
    ):
        raise ExecutionDispatchGateError("INVALID_DISPATCH_GATE_TIMEOUT")
    return float(timeout_seconds)


def dispatch_gate_path(database_path: Union[str, Path]) -> Path:
    """Return the one deterministic sidecar path for a file-backed journal."""

    if str(database_path) == ":memory:":
        raise ExecutionDispatchGateError("DISPATCH_GATE_REQUIRES_FILE_JOURNAL")
    journal_path = Path(database_path).expanduser().resolve(strict=False)
    return journal_path.with_name(f"{journal_path.name}.dispatch-gate.sqlite3")


@contextmanager
def acquire_dispatch_gate(
    database_path: Union[str, Path], *, timeout_seconds: float
) -> Iterator[ExecutionDispatchGateLease]:
    """Hold a bounded SQLite EXCLUSIVE lock beside ``database_path``.

    No PID, owner row, or lease expiry is written. The kernel/SQLite file lock
    is the ownership token, so process termination releases it without stale
    owner cleanup or a manual recovery declaration.
    """

    timeout = validate_dispatch_gate_timeout(timeout_seconds)
    deadline = time.monotonic() + timeout
    try:
        gate_path = dispatch_gate_path(database_path)
        if gate_path.is_symlink() or gate_path.exists() and not gate_path.is_file():
            raise ExecutionDispatchGateError("DISPATCH_GATE_PATH_UNSAFE")
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(gate_path),
            timeout=timeout,
            isolation_level=None,
            check_same_thread=False,
        )
    except ExecutionDispatchGateError:
        raise
    except (OSError, sqlite3.Error) as error:
        if _is_lock_error(error):
            raise ExecutionDispatchGateError("DISPATCH_SERIALIZATION_BUSY") from error
        raise ExecutionDispatchGateError("DISPATCH_SERIALIZATION_UNAVAILABLE") from error

    transaction_open = False
    try:
        _set_busy_timeout(connection, deadline)
        connection.execute("PRAGMA synchronous = FULL")
        # This idempotent initialization is itself serialized by SQLite. It
        # commits before the long-lived lock, keeping the journal independent.
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {_GATE_TABLE} ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton = 1))"
        )
        connection.execute(f"INSERT OR IGNORE INTO {_GATE_TABLE} VALUES (1)")

        _set_busy_timeout(connection, deadline)
        if time.monotonic() >= deadline:
            raise ExecutionDispatchGateError("DISPATCH_SERIALIZATION_BUSY")
        connection.execute("BEGIN EXCLUSIVE")
        transaction_open = True
    except ExecutionDispatchGateError:
        connection.close()
        raise
    except sqlite3.Error as error:
        connection.close()
        if _is_lock_error(error):
            raise ExecutionDispatchGateError("DISPATCH_SERIALIZATION_BUSY") from error
        raise ExecutionDispatchGateError("DISPATCH_SERIALIZATION_UNAVAILABLE") from error

    try:
        yield ExecutionDispatchGateLease(cross_process=True)
    finally:
        if transaction_open:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        try:
            connection.close()
        except sqlite3.Error:
            pass


def _set_busy_timeout(connection: sqlite3.Connection, deadline: float) -> None:
    remaining = max(0.0, deadline - time.monotonic())
    milliseconds = max(1, int(remaining * 1000))
    connection.execute(f"PRAGMA busy_timeout = {milliseconds}")


def _is_lock_error(error: BaseException) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "locked" in message or "busy" in message
