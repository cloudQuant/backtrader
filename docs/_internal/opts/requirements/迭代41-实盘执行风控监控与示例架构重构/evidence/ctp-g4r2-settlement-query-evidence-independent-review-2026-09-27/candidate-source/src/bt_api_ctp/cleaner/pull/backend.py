"""Transport-agnostic contract for pulling a shard's tick tree.

Every backend exposes the same operations over one host's ``remote_data_root``:
list the completed trading days, list one day's final files, copy a day locally,
and (only after the caller verified the copy) delete a day.  Keeping the
protocol this small is what lets the merge/verify/delete logic stay independent
of ssh, rsync or the local filesystem.
"""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

#: A trading-day directory name (``YYYYMMDD``).
_DAY_PATTERN = re.compile(r"^\d{8}$")

#: Runtime files that must never be pulled: they either change while we read
#: them (``*.lock``, staging segments) or are already-quarantined data.
_EXCLUDED_SUFFIXES = (".lock", ".tmp", ".bad")
_EXCLUDED_NAMES = (".staging",)


class PullError(RuntimeError):
    """A pull operation failed (connectivity, transfer or remote command)."""


@dataclass(frozen=True)
class RemoteFile:
    """One final file on the remote, relative to ``remote_data_root``."""

    rel_path: str
    size_bytes: int


@dataclass
class FetchResult:
    """Outcome of fetching one trading day."""

    day: str
    files: int = 0
    bytes: int = 0
    #: Files that were already present locally with a matching size.
    skipped: int = 0


@dataclass
class HostStatus:
    """Result of a connectivity check."""

    name: str
    backend: str
    ok: bool
    detail: str = ""
    days: list[str] = field(default_factory=list)


def is_day_name(name: str) -> bool:
    """Whether ``name`` looks like a trading-day directory."""
    return bool(_DAY_PATTERN.match(name))


def is_final_file(name: str) -> bool:
    """Whether a remote file name is part of the final data set.

    ``report.json`` marks a day as finished (the collector wrote it at close)
    and the parquet files are the data; everything else is runtime state.
    """
    if name in _EXCLUDED_NAMES:
        return False
    if name.endswith(_EXCLUDED_SUFFIXES):
        return False
    return name.endswith(".parquet") or name == "report.json"


def relative_parts(rel_path: str) -> tuple[str, ...]:
    """Split a remote relative path into its POSIX components."""
    return tuple(part for part in rel_path.replace("\\", "/").split("/") if part)


class PullBackend(Protocol):
    """One remote shard's transport."""

    name: str
    backend: str

    def check(self) -> HostStatus:
        """Verify the host is reachable and ``remote_data_root`` exists."""

    def list_days(self) -> list[str]:
        """List trading-day directories present on the remote."""

    def list_day_files(self, day: str) -> list[RemoteFile]:
        """List one day's final files (parquet + report.json)."""

    def has_report(self, day: str) -> bool:
        """Whether the remote day carries ``report.json`` (collection finished)."""

    def fetch_day(self, day: str, dest: Path) -> FetchResult:
        """Copy one day into ``dest/<day>/``, skipping files already complete."""

    def delete_day(self, day: str) -> None:
        """Remove one remote day directory.  Callers must have verified it first."""

    def close(self) -> None: ...


def plans_files(files: list[RemoteFile]) -> set[str]:
    """The relative paths that will be transferred for a day."""
    return {file.rel_path for file in files}


def is_directory(mode: int) -> bool:
    return stat.S_ISDIR(mode)


__all__ = [
    "FetchResult",
    "HostStatus",
    "PullBackend",
    "PullError",
    "RemoteFile",
    "is_day_name",
    "is_directory",
    "is_final_file",
    "relative_parts",
]
