"""Durable pull-state manifest -- the record that gates remote deletion.

Every stage advance is persisted before the next action starts, so a crash can
never leave the pipeline believing more happened than actually did.  The delete
stage reads the status from here rather than from memory, which is what makes
"only delete what was verified and merged" survive a restart.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATUS_DISCOVERED = "discovered"
STATUS_PULLED = "pulled"
STATUS_VERIFIED = "verified"
STATUS_MERGED = "merged"
STATUS_DELETED = "deleted"
STATUS_FAILED = "failed"

#: The timestamp field each status advance writes.
_STATUS_TIMESTAMP = {
    STATUS_PULLED: "pulled_at",
    STATUS_VERIFIED: "verified_at",
    STATUS_MERGED: "merged_at",
    STATUS_DELETED: "deleted_at",
}

_SCHEMA_VERSION = 1


@dataclass
class DayEntry:
    """One host's state for one trading day."""

    status: str = STATUS_DISCOVERED
    #: ``[{"rel_path": ..., "size_bytes": ..., "rows": ...}]`` as verified.
    files: list[dict[str, Any]] = field(default_factory=list)
    pulled_at: str | None = None
    verified_at: str | None = None
    merged_at: str | None = None
    deleted_at: str | None = None
    #: Set once the day's K lines were built; a crash before this is retried.
    klined_at: str | None = None
    error: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DayEntry:
        known = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        return cls(**known)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class Manifest:
    """Read-modify-write access to ``manifest.json``, always atomically."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._hosts: dict[str, dict[str, DayEntry]] = {}
        if self._path.exists():
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"manifest is not a mapping: {self._path}")
            for host, days in (payload.get("hosts") or {}).items():
                self._hosts[host] = {
                    day: DayEntry.from_payload(entry) for day, entry in days.items()
                }

    @property
    def path(self) -> Path:
        return self._path

    def entry(self, host: str, day: str) -> DayEntry | None:
        return self._hosts.get(host, {}).get(day)

    def status(self, host: str, day: str) -> str | None:
        entry = self.entry(host, day)
        return entry.status if entry else None

    def days(self, host: str) -> list[str]:
        return sorted(self._hosts.get(host, {}))

    def mark(
        self,
        host: str,
        day: str,
        status: str,
        *,
        files: list[dict[str, Any]] | None = None,
        error: str | None = None,
        save: bool = True,
    ) -> DayEntry:
        """Advance one host/day's state and persist it.

        A success status clears a previous error; ``failed`` keeps whatever the
        last good state was so a retry can decide from it.
        """
        entry = self.entry(host, day) or DayEntry()
        entry.status = status
        if files is not None:
            entry.files = files
        if error is not None:
            entry.error = error
        elif status != STATUS_FAILED:
            entry.error = None
        timestamp_field = _STATUS_TIMESTAMP.get(status)
        if timestamp_field is not None:
            setattr(entry, timestamp_field, _now_iso())
        self._hosts.setdefault(host, {})[day] = entry
        if save:
            self.save()
        return entry

    def mark_klined(self, day: str) -> None:
        """Record that ``day``'s K lines were built (K-line work is per day, not per host)."""
        for days in self._hosts.values():
            entry = days.get(day)
            if entry is not None:
                entry.klined_at = _now_iso()
        self.save()

    def days_needing_kline(self) -> list[str]:
        """Days already merged (or reclaimed) whose K lines are still missing."""
        return sorted(
            {
                day
                for days in self._hosts.values()
                for day, entry in days.items()
                if entry.klined_at is None and entry.status in (STATUS_MERGED, STATUS_DELETED)
            }
        )

    def save(self) -> None:
        payload = {
            "version": _SCHEMA_VERSION,
            "hosts": {
                host: {day: entry.to_payload() for day, entry in sorted(days.items())}
                for host, days in sorted(self._hosts.items())
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(
            f"{self._path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, self._path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


__all__ = [
    "STATUS_DELETED",
    "STATUS_DISCOVERED",
    "STATUS_FAILED",
    "STATUS_MERGED",
    "STATUS_PULLED",
    "STATUS_VERIFIED",
    "DayEntry",
    "Manifest",
]
