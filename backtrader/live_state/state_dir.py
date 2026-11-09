"""One-object access to the durable state of one strategy directory."""

from __future__ import annotations

from typing import Any, Optional

from ._common import StatePaths
from .atomic import FileLock, LiveStateLocked
from .audit import AuditLog
from .identity import StrategyIdentity, initialize_identity, load_identity
from .pending import PendingCommandStore
from .sequence import SequenceAllocator
from .snapshot import PositionSnapshotStore
from .waiting import WaitingOrderStore

__all__ = ("RunLock", "StrategyStateDir")


class RunLock:
    """Held ``state/run.lock``; release with :meth:`release` or ``with``."""

    __slots__ = ("_lock",)

    def __init__(self, lock: FileLock) -> None:
        self._lock = lock

    @property
    def path(self) -> str:
        return self._lock.path

    @property
    def held(self) -> bool:
        return self._lock.held

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class StrategyStateDir:
    """Identity, sequence, pending markers, snapshot, waiting orders and audit.

    Construction loads the identity (``check_host_path`` as in
    :func:`~backtrader.live_state.identity.load_identity`) and therefore raises
    :class:`LiveStateNotInitialized`, :class:`LiveStateCorrupt` or
    :class:`LiveStateIdentityMismatch` instead of creating anything.  Use
    :meth:`initialize` for the explicit first start.
    """

    def __init__(
        self, strategy_dir: Any, *, check_host_path: bool = True, lock_timeout: float = 10.0
    ) -> None:
        self.paths = StatePaths(strategy_dir)
        self.lock_timeout = lock_timeout
        self.identity: StrategyIdentity = load_identity(
            self.paths.strategy_dir, check_host_path=check_host_path
        )
        root = self.paths.strategy_dir
        uuid = self.identity.strategy_uuid
        self.sequence = SequenceAllocator(root, uuid, lock_timeout=lock_timeout)
        self.pending = PendingCommandStore(root, uuid, lock_timeout=lock_timeout)
        self.snapshot = PositionSnapshotStore(root, lock_timeout=lock_timeout)
        self.waiting = WaitingOrderStore(root, uuid, lock_timeout=lock_timeout)
        self.audit = AuditLog(root, lock_timeout=lock_timeout)

    @classmethod
    def initialize(
        cls, strategy_dir: Any, *, account_binding: Optional[dict] = None, **kwargs: Any
    ) -> "StrategyStateDir":
        """Explicit first initialization, then open the directory."""
        initialize_identity(strategy_dir, account_binding=account_binding)
        return cls(strategy_dir, **kwargs)

    @property
    def strategy_dir(self) -> str:
        return self.paths.strategy_dir

    @property
    def strategy_uuid(self) -> str:
        return self.identity.strategy_uuid

    def acquire_run_lock(self) -> RunLock:
        """Take ``state/run.lock`` now without waiting.

        Returns a held :class:`RunLock` (a context manager).  Raises
        :class:`LiveStateLocked` if another live run (any process, or another
        holder in this process) owns it.
        """
        from .atomic import LiveStateIdentityMismatch
        from .coordination import coordinated
        from .identity import load_identity

        # Under the coordination lock (E020) the run lock still never waits,
        # and an instance whose identity was archived meanwhile is refused.
        with coordinated(self.paths, timeout=self.lock_timeout):
            lock = FileLock(self.paths.run_lock, timeout=0)
            if not lock.try_acquire():
                raise LiveStateLocked(self.paths.run_lock, "live_run_active")
            try:
                current = load_identity(self.paths.strategy_dir, check_host_path=False)
                if current.strategy_uuid != self.identity.strategy_uuid:
                    raise LiveStateIdentityMismatch("strategy_uuid_mismatch", "run.lock")
            except BaseException:
                lock.release()
                raise
        return RunLock(lock)

    def summary(self) -> dict:
        """Secret-free overview used by ``python -m backtrader.live_state show``."""
        from .cli import build_summary

        return build_summary(self.paths.strategy_dir, check_host_path=False)
