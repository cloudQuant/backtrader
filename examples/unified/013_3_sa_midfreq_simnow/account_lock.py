"""Small, dependency-free local account lock used by the SimNow runner.

The lock deliberately imports no Backtrader or provider SDK code so a second
process can prove exclusive account ownership promptly, even when the main
runtime is busy starting. ``run.py`` re-exports both public names.
"""

from __future__ import annotations

import os
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class RunnerConfigurationError(RuntimeError):
    """Raised when configuration, environment, or admission inputs violate the frozen contract."""


class AccountLock:
    """Exclusive non-blocking file lock so only one process owns the SimNow account."""

    def __init__(self, path: Path) -> None:
        """Store ``path``; the lock file itself is created lazily on ``__enter__``."""
        self.path = path
        self.handle = None

    def __enter__(self):
        """Acquire an exclusive non-blocking lock; fail closed if it cannot be acquired."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                # ``msvcrt.locking`` locks a byte range and requires that byte
                # to exist. The sentinel stays inside the private lock file.
                self.handle.seek(0, os.SEEK_END)
                if self.handle.tell() == 0:
                    self.handle.write("\0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RunnerConfigurationError(
                "could not acquire exclusive local SimNow account lock"
            ) from exc
        return self

    def __exit__(self, *_args):
        """Release the platform lock and close the handle on context exit."""
        handle = self.handle
        self.handle = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
