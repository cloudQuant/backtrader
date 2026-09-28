"""Local-filesystem pull backend.

Reached by ``backend: local`` and used for two things: tests and one-off
migrations (copy a shard from a mounted disk or USB drive).  It is also the
reference implementation of the :class:`~bt_api_ctp.cleaner.pull.backend.PullBackend`
semantics for the network backends.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bt_api_ctp.cleaner.config import HostConfig
from bt_api_ctp.cleaner.pull.backend import (
    FetchResult,
    HostStatus,
    PullError,
    RemoteFile,
    is_day_name,
    is_final_file,
    relative_parts,
)


class LocalBackend:
    """Treat ``remote_data_root`` as a local directory."""

    backend = "local"

    def __init__(self, host: HostConfig) -> None:
        self.name = host.name
        self._root = Path(host.remote_data_root).expanduser()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def remote_root(self) -> str:
        return str(self._root)

    def check(self) -> HostStatus:
        if not self._root.is_dir():
            return HostStatus(
                name=self.name,
                backend=self.backend,
                ok=False,
                detail=f"directory not found: {self._root}",
            )
        return HostStatus(name=self.name, backend=self.backend, ok=True, detail=str(self._root))

    def list_days(self) -> list[str]:
        if not self._root.is_dir():
            raise PullError(f"remote root not found: {self._root}")
        return sorted(
            path.name for path in self._root.iterdir() if path.is_dir() and is_day_name(path.name)
        )

    def list_day_files(self, day: str) -> list[RemoteFile]:
        day_dir = self._root / day
        if not day_dir.is_dir():
            return []
        files: list[RemoteFile] = []
        for path in sorted(day_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part in (".staging",) for part in path.relative_to(day_dir).parts[:-1]):
                continue
            if not is_final_file(path.name):
                continue
            rel = path.relative_to(self._root).as_posix()
            files.append(RemoteFile(rel_path=rel, size_bytes=path.stat().st_size))
        return files

    def has_report(self, day: str) -> bool:
        return (self._root / day / "report.json").is_file()

    def fetch_day(self, day: str, dest: Path) -> FetchResult:
        day_dir = self._root / day
        if not day_dir.is_dir():
            raise PullError(f"remote day not found: {day_dir}")
        target_root = Path(dest) / day
        result = FetchResult(day=day)
        for file in self.list_day_files(day):
            target = target_root.joinpath(*relative_parts(file.rel_path)[1:])
            if target.exists() and target.stat().st_size == file.size_bytes:
                result.skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._root.joinpath(*relative_parts(file.rel_path)), target)
            result.files += 1
            result.bytes += file.size_bytes
        return result

    def delete_day(self, day: str) -> None:
        day_dir = self._root / day
        if day_dir.exists():
            shutil.rmtree(day_dir)

    def close(self) -> None:  # pragma: no cover - nothing to release
        return None


__all__ = ["LocalBackend"]
