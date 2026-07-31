"""Cross-process advisory locks for state transitions."""

from __future__ import annotations

import fcntl
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def acquire(self, name: str) -> Iterator[None]:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        path = self.root / f"{digest}.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
