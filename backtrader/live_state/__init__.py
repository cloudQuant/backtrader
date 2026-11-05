"""Durable local state of one live strategy instance (iteration 62 direct mode).

One strategy instance is one strategy directory::

    state/identity.json        strategy UUID4, host, resolved path, account binding (hash only)
    state/sequence.json        strategy-local order sequence + process Order.ref high-water
    state/pending.json         pre-dispatch pending command markers
    state/waiting_orders.json  orders waiting for the next trading session
    state/audit.log            append-only JSON-lines audit
    state/run.lock             held while a live run is active
    logs/current_position.yaml versioned position snapshot

All writes are atomic (temp file, fsync, ``os.replace``, directory fsync);
inter-process locks guard every read-modify-write.  The package stores only
local framework facts; it never contacts an account or provider and proves
nothing about venue state.  Operator CLI: ``python -m backtrader.live_state``.
"""

from .atomic import (
    ERROR_CODES,
    FileLock,
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateLocked,
    LiveStateNotInitialized,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    read_json,
)
from .audit import AuditLog, append_audit, read_audit
from .identity import (
    StrategyIdentity,
    bind_account,
    hash_account_id,
    initialize_identity,
    load_identity,
    rebind_identity,
)
from .pending import (
    ACTIVE_STATUSES,
    MANUAL_CONCLUSIONS,
    STATUS_ACCEPTED,
    STATUS_DISPATCHED,
    STATUS_PREPARED,
    STATUS_TERMINAL,
    STATUS_UNKNOWN,
    BoundPreDispatchPort,
    PendingCommandStore,
)
from .sequence import SequenceAllocator
from .snapshot import LegacyPositions, PositionSnapshotStore
from .state_dir import RunLock, StrategyStateDir
from .waiting import WAITING_STATUSES, WaitingOrderStore

__all__ = (
    "ACTIVE_STATUSES",
    "AuditLog",
    "BoundPreDispatchPort",
    "ERROR_CODES",
    "FileLock",
    "LegacyPositions",
    "LiveStateCorrupt",
    "LiveStateError",
    "LiveStateIdentityMismatch",
    "LiveStateLocked",
    "LiveStateNotInitialized",
    "MANUAL_CONCLUSIONS",
    "PendingCommandStore",
    "PositionSnapshotStore",
    "RunLock",
    "STATUS_ACCEPTED",
    "STATUS_DISPATCHED",
    "STATUS_PREPARED",
    "STATUS_TERMINAL",
    "STATUS_UNKNOWN",
    "SequenceAllocator",
    "StrategyIdentity",
    "StrategyStateDir",
    "WAITING_STATUSES",
    "WaitingOrderStore",
    "append_audit",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "bind_account",
    "hash_account_id",
    "initialize_identity",
    "load_identity",
    "read_audit",
    "read_json",
    "rebind_identity",
)
