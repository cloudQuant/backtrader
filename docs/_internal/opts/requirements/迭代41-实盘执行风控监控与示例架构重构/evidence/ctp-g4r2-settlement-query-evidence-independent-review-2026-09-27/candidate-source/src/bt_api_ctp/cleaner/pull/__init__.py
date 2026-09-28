"""Pull backends: one transport per remote shard host.

``create_backend`` is the only name the pipeline needs; the concrete backends
are selected from the host's ``backend`` field.
"""

from __future__ import annotations

__all__ = [
    "FetchResult",
    "HostStatus",
    "LocalBackend",
    "PullBackend",
    "PullError",
    "RemoteFile",
    "RsyncBackend",
    "SftpBackend",
    "create_backend",
]

from bt_api_ctp.cleaner.config import HostConfig
from bt_api_ctp.cleaner.pull.backend import (
    FetchResult,
    HostStatus,
    PullBackend,
    PullError,
    RemoteFile,
)
from bt_api_ctp.cleaner.pull.local_backend import LocalBackend
from bt_api_ctp.cleaner.pull.rsync_backend import RsyncBackend
from bt_api_ctp.cleaner.pull.sftp_backend import SftpBackend


def create_backend(host: HostConfig) -> PullBackend:
    """Build the transport declared by ``host.backend``."""
    if host.backend == "local":
        return LocalBackend(host)
    if host.backend == "rsync":
        return RsyncBackend(host)
    if host.backend == "sftp":
        return SftpBackend(host)
    raise PullError(f"unknown pull backend: {host.backend!r}")
