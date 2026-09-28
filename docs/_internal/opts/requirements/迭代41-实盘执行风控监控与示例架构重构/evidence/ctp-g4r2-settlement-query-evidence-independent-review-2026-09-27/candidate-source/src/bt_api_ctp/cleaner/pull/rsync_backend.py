"""rsync-over-ssh backend, for Linux shard hosts.

``rsync`` keeps a re-run cheap: a day that was half transferred continues where
it stopped instead of starting over, which matters when a day holds thousands
of small parquet files.  The remote listings and the delete still go through
plain ``ssh`` so the backend does not depend on rsync's own protocol for them.

The command runner is injectable so the argument construction can be tested
without a reachable host.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

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

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]

_SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")

#: Runtime files rsync must not copy (they are either live or already quarantined).
_RSYNC_EXCLUDES = ("*.lock", "*.tmp", "*.bad", ".staging")


def _default_runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


class RsyncBackend:
    """Pull a shard's tree with rsync, list/delete over ssh."""

    backend = "rsync"

    def __init__(self, host: HostConfig, runner: Runner | None = None) -> None:
        self.name = host.name
        self._target = host.host
        self._root = host.remote_data_root.rstrip("/")
        self._port = host.port
        self._runner = runner or _default_runner

    # -- ssh helpers ----------------------------------------------------

    @property
    def remote_root(self) -> str:
        return self._root

    def _ssh_args(self) -> list[str]:
        args = ["ssh", *_SSH_OPTIONS]
        if self._port != 22:
            args += ["-p", str(self._port)]
        return args

    def _ssh(self, remote_command: str) -> str:
        completed = self._runner([*self._ssh_args(), self._target, remote_command])
        if completed.returncode != 0:
            raise PullError(
                f"{self.name}: ssh failed ({completed.returncode}): "
                f"{(completed.stderr or '').strip()}"
            )
        return completed.stdout or ""

    def _run_rsync(self, args: list[str]) -> None:
        completed = self._runner(args)
        if completed.returncode != 0:
            raise PullError(
                f"{self.name}: rsync failed ({completed.returncode}): "
                f"{(completed.stderr or '').strip()}"
            )

    # -- PullBackend ----------------------------------------------------

    def check(self) -> HostStatus:
        try:
            self._ssh(f"test -d {shlex.quote(self._root)}")
        except PullError as error:
            return HostStatus(name=self.name, backend=self.backend, ok=False, detail=str(error))
        return HostStatus(name=self.name, backend=self.backend, ok=True, detail=self._root)

    def list_days(self) -> list[str]:
        output = self._ssh(
            f"find {shlex.quote(self._root)} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n'"
        )
        return sorted(line.strip() for line in output.splitlines() if is_day_name(line.strip()))

    def list_day_files(self, day: str) -> list[RemoteFile]:
        if not is_day_name(day):
            raise PullError(f"{self.name}: invalid trading day {day!r}")
        output = self._ssh(
            f"find {shlex.quote(self._root)} -maxdepth 3 -type f "
            f"\\( -name '*.parquet' -o -name 'report.json' \\) -printf '%P\\t%s\\n'"
        )
        files: list[RemoteFile] = []
        for line in output.splitlines():
            rel_path, _, size = line.rpartition("\t")
            if not rel_path or not size.strip():
                continue
            parts = relative_parts(rel_path)
            if not parts or parts[0] != day:
                continue
            if not is_final_file(parts[-1]):
                continue
            try:
                size_bytes = int(size)
            except ValueError:
                continue
            files.append(RemoteFile(rel_path=rel_path, size_bytes=size_bytes))
        return files

    def has_report(self, day: str) -> bool:
        output = self._ssh(
            f"test -f {shlex.quote(f'{self._root}/{day}/report.json')} && echo yes || echo no"
        )
        return output.strip() == "yes"

    def fetch_day(self, day: str, dest: Path) -> FetchResult:
        if not is_day_name(day):
            raise PullError(f"{self.name}: invalid trading day {day!r}")
        files = self.list_day_files(day)
        target_root = Path(dest) / day
        skipped = 0
        skipped_bytes = 0
        for file in files:
            local = target_root.joinpath(*relative_parts(file.rel_path)[1:])
            if local.exists() and local.stat().st_size == file.size_bytes:
                skipped += 1
                skipped_bytes += file.size_bytes

        ssh_transport = "ssh " + " ".join(_SSH_OPTIONS)
        if self._port != 22:
            ssh_transport += f" -p {self._port}"
        args = [
            "rsync",
            "-a",
            "--omit-dir-times",
            "--no-perms",
            *[f"--exclude={pattern}" for pattern in _RSYNC_EXCLUDES],
            "-e",
            ssh_transport,
            f"{self._target}:{self._root}/{day}/",
            f"{target_root}/",
        ]
        target_root.mkdir(parents=True, exist_ok=True)
        self._run_rsync(args)

        return FetchResult(
            day=day,
            files=len(files) - skipped,
            bytes=sum(file.size_bytes for file in files) - skipped_bytes,
            skipped=skipped,
        )

    def delete_day(self, day: str) -> None:
        if not is_day_name(day):
            raise PullError(f"{self.name}: refusing to delete non-day path {day!r}")
        self._ssh(f"rm -rf -- {shlex.quote(f'{self._root}/{day}')}")

    def close(self) -> None:  # pragma: no cover - no persistent connection
        return None


__all__ = ["RsyncBackend"]
