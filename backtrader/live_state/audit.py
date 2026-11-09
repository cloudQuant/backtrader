"""Append-only JSON-lines audit log at ``state/audit.log``.

Records identity initialization/rebind, account binding and manual UNKNOWN
resolution.  Each line is one JSON object with a UTC timestamp, the writing
pid and host.  Records are checked with a key-name secret guard (no
credentials, no raw account ids); free-text values such as evidence
references are the operator's responsibility.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Mapping, Optional

from ._common import (
    StatePaths,
    current_hostname,
    ensure_no_secret_keys,
    is_text,
    json_safe_copy,
    utc_now_iso,
)
from .atomic import (
    FileLock,
    LiveStateCorrupt,
    LiveStateError,
    LiveStateNotInitialized,
    fsync_directory,
)

__all__ = ("AuditLog", "append_audit", "read_audit")

_RESERVED = ("ts_utc", "pid", "host")


def append_audit(strategy_dir: Any, record: Mapping[str, Any], *, lock_timeout: float = 10.0):
    """Durably append ``record`` (must contain a text ``event``); return the line dict.

    Raises :class:`LiveStateError` (``secret_field_rejected``,
    ``value_not_json_safe``, ``live_state_error``) for invalid records,
    :class:`LiveStateNotInitialized` if ``state/`` is missing, and the
    underlying ``OSError`` if the append could not be made durable.
    """
    if not isinstance(record, Mapping):
        raise LiveStateError("live_state_error", "audit_record_not_mapping")
    if not is_text(record.get("event"), max_len=128):
        raise LiveStateError("live_state_error", "audit_event_required")
    for key in _RESERVED:
        if key in record:
            raise LiveStateError("live_state_error", f"audit_reserved_key:{key}")
    ensure_no_secret_keys(record, "audit")
    entry = json_safe_copy(record, "audit")
    entry["ts_utc"] = utc_now_iso()
    entry["pid"] = os.getpid()
    entry["host"] = current_hostname()
    line = (
        json.dumps(
            entry, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    paths = StatePaths(strategy_dir)
    if not os.path.isdir(paths.state_dir):
        raise LiveStateNotInitialized(paths.state_dir, "state_dir_missing")
    from .coordination import coordinated

    with coordinated(paths, timeout=lock_timeout), FileLock(paths.audit_lock, timeout=lock_timeout):
        created = not os.path.exists(paths.audit)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(paths.audit, flags, 0o600)
        try:
            view = memoryview(line)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            fsync_directory(paths.state_dir)
    return entry


def read_audit(strategy_dir: Any, *, limit: Optional[int] = None) -> List[dict]:
    """Return audit records (oldest first; the last ``limit`` if given).

    A missing log returns ``[]``; an unparsable line raises
    :class:`LiveStateCorrupt`.
    """
    paths = StatePaths(strategy_dir)
    try:
        with open(paths.audit, "rb") as handle:
            raw_lines = handle.read().splitlines()
    except FileNotFoundError:
        return []
    records = []
    for number, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LiveStateCorrupt(paths.audit, f"line_{number}_unparsable") from None
        if not isinstance(item, dict):
            raise LiveStateCorrupt(paths.audit, f"line_{number}_not_object")
        records.append(item)
    if limit is not None:
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a non-negative int")
        records = records[-limit:] if limit else []
    return records


class AuditLog:
    """Audit log of one strategy directory."""

    def __init__(self, strategy_dir: Any, *, lock_timeout: float = 10.0) -> None:
        self.paths = StatePaths(strategy_dir)
        self.lock_timeout = lock_timeout

    @property
    def path(self) -> str:
        return self.paths.audit

    def append(self, record: Mapping[str, Any]) -> dict:
        return append_audit(self.paths.strategy_dir, record, lock_timeout=self.lock_timeout)

    def records(self, *, limit: Optional[int] = None) -> List[dict]:
        return read_audit(self.paths.strategy_dir, limit=limit)
