"""SFTP backend, for Windows shard hosts (and any host without rsync).

Windows ships an OpenSSH server as an optional feature, so SFTP is the one
transport that exists on both platforms without installing anything extra.  It
is slower than rsync on many small files, so transfers skip files whose size
already matches and the caller can cap concurrency.

The connection factory is injectable so the semantics can be tested without a
reachable host (and so paramiko stays an optional dependency of the plugin).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Protocol

from bt_api_ctp.cleaner.config import HostConfig
from bt_api_ctp.cleaner.pull.backend import (
    FetchResult,
    HostStatus,
    PullError,
    RemoteFile,
    is_day_name,
    is_directory,
    is_final_file,
    relative_parts,
)


class SftpTransport(Protocol):
    """The slice of paramiko's SFTPClient the backend relies on."""

    def listdir_attr(self, path: str): ...
    def stat(self, path: str): ...
    def get(self, remotepath: str, localpath: str) -> None: ...
    def remove(self, path: str) -> None: ...
    def rmdir(self, path: str) -> None: ...


def _default_connector(host: HostConfig) -> SftpTransport:
    try:
        import paramiko
    except ImportError as error:  # pragma: no cover - exercised only without the extra
        raise PullError(
            "the sftp backend needs paramiko; install it with: pip install 'bt_api_ctp[cleaner]'"
        ) from error

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host.host.split("@")[-1],
        port=host.port,
        username=_username(host.host),
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    transport = client.open_sftp()
    transport._joyin_client = client  # type: ignore[attr-defined]  # keep the session alive
    return transport


def _username(target: str) -> str | None:
    return target.split("@", 1)[0] if "@" in target else None


class SftpBackend:
    """Pull a shard's tree over SFTP."""

    backend = "sftp"

    def __init__(self, host: HostConfig, connector=None) -> None:
        self.name = host.name
        self._host = host
        self._root = host.remote_data_root.rstrip("/")
        self._connector = connector or _default_connector
        self._sftp: SftpTransport | None = None

    # -- connection ------------------------------------------------------

    @property
    def remote_root(self) -> str:
        return self._root

    def _transport(self) -> SftpTransport:
        if self._sftp is None:
            try:
                self._sftp = self._connector(self._host)
            except PullError:
                raise
            except Exception as error:
                raise PullError(f"{self.name}: sftp connect failed: {error}") from error
        return self._sftp

    def _remote(self, *parts: str) -> str:
        suffix = "/".join(part.strip("/") for part in parts if part)
        return f"{self._root}/{suffix}" if suffix else self._root

    # -- PullBackend -----------------------------------------------------

    def check(self) -> HostStatus:
        try:
            self._transport().listdir_attr(self._root)
        except PullError as error:
            return HostStatus(name=self.name, backend=self.backend, ok=False, detail=str(error))
        except Exception as error:
            return HostStatus(name=self.name, backend=self.backend, ok=False, detail=str(error))
        return HostStatus(name=self.name, backend=self.backend, ok=True, detail=self._root)

    def list_days(self) -> list[str]:
        entries = self._transport().listdir_attr(self._root)
        return sorted(
            entry.filename
            for entry in entries
            if is_directory(entry.st_mode) and is_day_name(entry.filename)
        )

    def _walk(self, path: str, rel_prefix: str) -> list[RemoteFile]:
        files: list[RemoteFile] = []
        for entry in self._transport().listdir_attr(path):
            rel = f"{rel_prefix}/{entry.filename}" if rel_prefix else entry.filename
            if is_directory(entry.st_mode):
                if entry.filename in (".staging",):
                    continue
                files.extend(self._walk(f"{path}/{entry.filename}", rel))
            elif is_final_file(entry.filename):
                files.append(RemoteFile(rel_path=rel, size_bytes=int(entry.st_size)))
        return files

    def list_day_files(self, day: str) -> list[RemoteFile]:
        if not is_day_name(day):
            raise PullError(f"{self.name}: invalid trading day {day!r}")
        return sorted(self._walk(self._remote(day), day), key=lambda file: file.rel_path)

    def has_report(self, day: str) -> bool:
        try:
            self._transport().stat(self._remote(day, "report.json"))
        except Exception:
            return False
        return True

    def fetch_day(self, day: str, dest: Path) -> FetchResult:
        if not is_day_name(day):
            raise PullError(f"{self.name}: invalid trading day {day!r}")
        sftp = self._transport()
        target_root = Path(dest) / day
        result = FetchResult(day=day)
        for file in self.list_day_files(day):
            local = target_root.joinpath(*relative_parts(file.rel_path)[1:])
            if local.exists() and local.stat().st_size == file.size_bytes:
                result.skipped += 1
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            partial = local.with_name(f"{local.name}.{uuid.uuid4().hex[:8]}.part")
            try:
                sftp.get(f"{self._root}/{file.rel_path}", str(partial))
                os.replace(partial, local)
            finally:
                if partial.exists():
                    partial.unlink(missing_ok=True)
            result.files += 1
            result.bytes += file.size_bytes
        return result

    def _remove_tree(self, path: str) -> None:
        sftp = self._transport()
        for entry in sftp.listdir_attr(path):
            child = f"{path}/{entry.filename}"
            if is_directory(entry.st_mode):
                self._remove_tree(child)
            else:
                sftp.remove(child)
        sftp.rmdir(path)

    def delete_day(self, day: str) -> None:
        if not is_day_name(day):
            raise PullError(f"{self.name}: refusing to delete non-day path {day!r}")
        self._remove_tree(self._remote(day))

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - best effort
                pass
            client = getattr(self._sftp, "_joyin_client", None)
            if client is not None:
                client.close()
            self._sftp = None


__all__ = ["SftpBackend"]
