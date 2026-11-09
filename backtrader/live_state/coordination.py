"""Strategy-root coordination lock for local state (iteration 63, E020).

``rebind_identity(mode="new_instance")`` archives ``state/`` after checking
that no pending, waiting or Gateway work exists. Store reads are lock-free and
writers previously only took a lock *inside* ``state/``: a writer could commit
between that check and the rename and its record was archived silently. A lock
inside ``state/`` cannot fix this (a POSIX waiter may lock the old inode and
then use the new paths; Windows must release handles before the rename).

One persistent lock file in the strategy root, which archiving never moves, is
therefore the outermost lock of every state writer, of identity
initialization/binding/rebinding and of run-lock acquisition. Lock order:
coordination -> run lock (never waits) -> identity -> store/audit locks. It is
re-entrant per thread (the archive check itself reads the stores). After the
switch a writer still holding the old identity fails its existing
``strategy_uuid`` check instead of writing into the new state.

The protocol binds cooperating processes on one host: old versions writing
independently must be stopped before upgrade; it is not a defence against a
malicious writer, network file systems or other hosts.
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .atomic import FileLock

__all__ = ("CoordinatedFileLock", "coordinated")

_held = threading.local()


def _depths() -> dict:
    depths = getattr(_held, "depths", None)
    if depths is None:
        depths = _held.depths = {}
    return depths


@contextmanager
def coordinated(paths: Any, *, timeout: float = 10.0) -> Iterator[None]:
    """Hold the strategy-root coordination lock (re-entrant in this thread)."""
    key = os.path.normcase(os.path.realpath(paths.strategy_dir))
    depths = _depths()
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return
    lock = FileLock(paths.coordination_lock, timeout=timeout)
    lock.acquire()
    depths[key] = 1
    try:
        yield
    finally:
        depths.pop(key, None)
        lock.release()


class CoordinatedFileLock:
    """Coordination lock first, then a store's own lock inside ``state/``.

    Returned by the stores' ``_lock()``; use it as a context manager.
    """

    __slots__ = ("_paths", "_inner", "_timeout", "_outer")

    def __init__(self, paths: Any, inner_path: str, *, timeout: float) -> None:
        self._paths = paths
        self._inner = FileLock(inner_path, timeout=timeout)
        self._timeout = timeout
        self._outer = None

    @property
    def path(self) -> str:
        return self._inner.path

    @property
    def held(self) -> bool:
        return self._inner.held

    def __enter__(self) -> "CoordinatedFileLock":
        outer = coordinated(self._paths, timeout=self._timeout)
        outer.__enter__()
        try:
            self._inner.acquire()
        except BaseException:
            outer.__exit__(*sys.exc_info())
            raise
        self._outer = outer
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        outer, self._outer = self._outer, None
        try:
            self._inner.release()
        finally:
            if outer is not None:
                outer.__exit__(exc_type, exc, tb)
