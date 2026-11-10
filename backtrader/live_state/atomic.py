"""Crash-safe file writes, strict JSON reads and inter-process locks.

Every state file of :mod:`backtrader.live_state` is written with
:func:`atomic_write_text` (temp file in the same directory -> flush ->
``os.fsync`` -> ``os.replace`` -> best-effort directory fsync), so a reader
sees either the old or the new complete file, never a torn one.

:class:`FileLock` is an exclusive advisory lock (``fcntl.flock`` on POSIX,
``msvcrt.locking`` on Windows).  ``flock`` locks belong to an open file
description, so two ``FileLock`` objects on the same path exclude each other
even inside one process.  Locks are only reliable on local filesystems.

Durability note: ``os.fsync`` on macOS flushes to the drive but not through
the drive cache (that needs ``F_FULLFSYNC``); it survives a process crash, not
necessarily a power loss.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from typing import Any, Optional

__all__ = (
    "ERROR_CODES",
    "FileLock",
    "LiveStateCorrupt",
    "LiveStateError",
    "LiveStateIdentityMismatch",
    "LiveStateLocked",
    "LiveStateNotInitialized",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "fsync_directory",
    "read_json",
    "read_json_bytes",
)

#: The finite set of ``LiveStateError.code`` values.  Any other code passed to
#: an error constructor collapses to ``"live_state_error"``.
ERROR_CODES = frozenset(
    {
        "live_state_error",
        # file / lock / init state
        "state_corrupt",
        "state_locked",
        "state_not_initialized",
        "lock_reentry",
        "invalid_strategy_dir",
        "strategy_dir_missing",
        "state_dir_not_empty",
        "hostname_unavailable",
        "invalid_strategy_uuid",
        # identity
        "identity_already_initialized",
        "identity_mismatch",
        "hostname_mismatch",
        "strategy_dir_mismatch",
        "strategy_uuid_mismatch",
        "account_binding_mismatch",
        "account_binding_invalid",
        "account_hash_invalid",
        "rebind_invalid_mode",
        "rebind_not_required",
        "rebind_blocked_active_state",
        "operator_required",
        "reason_required",
        # content guards
        "secret_field_rejected",
        "value_not_json_safe",
        # sequence
        "invalid_ref",
        "ref_basis_shadowed",
        # pending markers
        "pending_record_invalid",
        "pending_scope_mismatch",
        "pending_duplicate_identity",
        "pending_duplicate_local_seq",
        "identity_query_invalid",
        "marker_not_found",
        "marker_not_unknown",
        "invalid_conclusion",
        "evidence_required",
        # snapshot
        "snapshot_invalid",
        "snapshot_not_legacy",
        "snapshot_foreign",
        "snapshot_mode_mismatch",
        "snapshot_account_mismatch",
        "snapshot_exchange_mismatch",
        "snapshot_strategy_mismatch",
        "yaml_unavailable",
        # waiting orders
        "waiting_invalid",
        "waiting_duplicate",
        "waiting_transition_illegal",
        # audit
        "audit_write_failed",
    }
)


class LiveStateError(RuntimeError):
    """Base error of the package; ``code`` is one of :data:`ERROR_CODES`."""

    default_code = "live_state_error"

    def __init__(self, code: str = "", detail: str = "") -> None:
        if type(code) is not str or code not in ERROR_CODES:
            if type(code) is str and code and not detail:
                detail = code
            code = self.default_code
        self.code = code
        self.detail = detail if type(detail) is str else ""
        super().__init__(code if not self.detail else f"{code}: {self.detail}")

    def __reduce__(self):
        return (LiveStateError, (self.code, self.detail))


class LiveStateCorrupt(LiveStateError):
    """A state file exists but cannot be trusted (parse, schema or version)."""

    default_code = "state_corrupt"

    def __init__(self, path: Any, reason: str) -> None:
        self.path = os.fspath(path) if path is not None else ""
        self.reason = reason if type(reason) is str and reason else "unknown"
        super().__init__("state_corrupt", f"{os.path.basename(self.path)}: {self.reason}")

    def __reduce__(self):
        return (LiveStateCorrupt, (self.path, self.reason))


class LiveStateLocked(LiveStateError):
    """Another holder owns the lock (timeout or non-blocking attempt failed)."""

    default_code = "state_locked"

    def __init__(self, path: Any, detail: str = "") -> None:
        self.path = os.fspath(path) if path is not None else ""
        super().__init__("state_locked", detail or os.path.basename(self.path))

    def __reduce__(self):
        return (LiveStateLocked, (self.path, self.detail))


class LiveStateIdentityMismatch(LiveStateError):
    """Stored identity/binding does not match the current host, path or account.

    ``code`` is the specific finite reason (for example ``hostname_mismatch`` or
    ``account_binding_mismatch``); ``reason`` repeats it.
    """

    default_code = "identity_mismatch"

    def __init__(self, reason: str = "identity_mismatch", detail: str = "") -> None:
        super().__init__(reason, detail)
        self.reason = self.code

    def __reduce__(self):
        return (LiveStateIdentityMismatch, (self.code, self.detail))


class LiveStateNotInitialized(LiveStateError):
    """A required state file is missing; explicit initialization is needed."""

    default_code = "state_not_initialized"

    def __init__(self, path: Any, detail: str = "") -> None:
        self.path = os.fspath(path) if path is not None else ""
        super().__init__("state_not_initialized", detail or os.path.basename(self.path))

    def __reduce__(self):
        return (LiveStateNotInitialized, (self.path, self.detail))


# --- durable writes -----------------------------------------------------------


def fsync_directory(path: Any) -> bool:
    """Best-effort fsync of a directory entry table (no-op on Windows)."""
    if os.name == "nt":
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError:
        return False
    try:
        os.fsync(fd)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _replace(src: str, dst: str) -> None:
    if os.name != "nt":
        os.replace(src, dst)
        return
    # Windows refuses to replace a file another process holds open; readers
    # only hold it briefly, so retry a few times before giving up.
    for attempt in range(10):  # pragma: no cover - Windows only
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02 * (attempt + 1))


def atomic_write_bytes(path: Any, data: bytes) -> None:
    """Atomically replace ``path`` with ``data`` (directory must exist)."""
    if type(data) is not bytes:
        raise TypeError("data must be bytes")
    target = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(target))
    base = os.path.basename(target)
    fd, tmp = tempfile.mkstemp(prefix=f".{base}.", suffix=".tmp", dir=directory)
    try:
        try:
            handle = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    fsync_directory(directory)


def atomic_write_text(path: Any, text: str) -> None:
    """Atomically replace ``path`` with UTF-8 ``text`` (no newline translation)."""
    if type(text) is not str:
        raise TypeError("text must be str")
    atomic_write_bytes(path, text.encode("utf-8"))


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def atomic_write_json(path: Any, obj: Any) -> None:
    """Atomically write ``obj`` as sorted, indented UTF-8 JSON (no NaN/inf)."""
    atomic_write_text(path, dumps_json(obj))


class _DuplicateKey(ValueError):
    pass


def _pairs_no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKey(key)
        out[key] = value
    return out


def _reject_constant(name):
    raise ValueError(f"non-finite constant {name}")


def read_json(path: Any) -> Any:
    """Read a strict JSON file.

    Raises ``FileNotFoundError`` if missing (callers map it to
    :class:`LiveStateNotInitialized`) and :class:`LiveStateCorrupt` for empty
    files, invalid UTF-8, parse errors, duplicate keys or NaN/Infinity.
    """
    return read_json_bytes(path)[1]


def read_json_bytes(path: Any) -> "tuple[bytes, Any]":
    """Like :func:`read_json`, also returning the exact bytes that were parsed."""
    target = os.fspath(path)
    with open(target, "rb") as handle:
        raw = handle.read()
    return raw, _parse_json_bytes(raw, target)


def _parse_json_bytes(raw: bytes, target: str) -> Any:
    if not raw.strip():
        raise LiveStateCorrupt(target, "empty_file")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise LiveStateCorrupt(target, "utf8_decode_error") from None
    try:
        return json.loads(
            text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant
        )
    except _DuplicateKey:
        raise LiveStateCorrupt(target, "duplicate_key") from None
    except ValueError:
        raise LiveStateCorrupt(target, "json_parse_error") from None


# --- inter-process lock -------------------------------------------------------

if os.name == "nt":  # pragma: no cover - Windows only
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, PermissionError):
            return False

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class FileLock:
    """Exclusive inter-process lock on ``path`` (created if missing, never deleted).

    ``with FileLock(p, timeout=10.0):`` waits up to ``timeout`` seconds and
    raises :class:`LiveStateLocked` on timeout.  :meth:`try_acquire` never
    waits.  An instance is not re-entrant; use one instance per holder.
    """

    def __init__(self, path: Any, *, timeout: float = 10.0, poll_interval: float = 0.01) -> None:
        if type(timeout) not in (int, float) or not timeout >= 0:
            raise ValueError("timeout must be a non-negative number")
        if type(poll_interval) not in (int, float) or not poll_interval > 0:
            raise ValueError("poll_interval must be a positive number")
        self.path = os.fspath(path)
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def _open(self) -> int:
        try:
            return os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except FileNotFoundError:
            raise LiveStateNotInitialized(os.path.dirname(self.path), "lock_dir_missing") from None

    def try_acquire(self) -> bool:
        """Acquire without waiting; ``True`` on success."""
        if self._fd is not None:
            raise LiveStateError("lock_reentry", os.path.basename(self.path))
        fd = self._open()
        try:
            locked = _try_lock(fd)
        except BaseException:
            os.close(fd)
            raise
        if not locked:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def acquire(self) -> "FileLock":
        """Acquire, waiting up to ``timeout``; raise :class:`LiveStateLocked`."""
        deadline = time.monotonic() + self.timeout
        while True:
            if self.try_acquire():
                return self
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LiveStateLocked(self.path)
            time.sleep(min(self.poll_interval, remaining))

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> "FileLock":
        if self._fd is None:
            self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def __del__(self):  # pragma: no cover - safety net only
        fd = getattr(self, "_fd", None)
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
