"""Per-strategy local order sequence and process ``Order.ref`` high-water mark.

``state/sequence.json`` holds ``{"version": 1, "strategy_uuid", "local_seq",
"ref_high_water"}``.  ``local_seq`` is the last allocated number (``0`` before
the first order).  Backtest and live runs of the same strategy directory share
the same file and lock (D62-04b2), so they never hand out the same number.

Guarantees: allocated numbers are strictly increasing and never reused.  A
number is returned only after the new state was written durably; a crash after
the write but before the caller records the number skips it (gaps are allowed,
reuse is not).  The file is created by
:func:`backtrader.live_state.identity.initialize_identity`; a missing file is
reported as :class:`LiveStateNotInitialized` instead of restarting at ``0``.
"""

from __future__ import annotations

import itertools
import threading
from typing import Any, Optional

from ._common import StatePaths, is_strict_int, is_uuid4
from .atomic import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    atomic_write_json,
    read_json,
)

__all__ = ("SEQUENCE_VERSION", "SequenceAllocator")

SEQUENCE_VERSION = 1
_KEYS = frozenset({"version", "strategy_uuid", "local_seq", "ref_high_water"})
_REF_BASIS_LOCK = threading.Lock()


def initial_sequence_state(strategy_uuid: str) -> dict:
    return {
        "version": SEQUENCE_VERSION,
        "strategy_uuid": strategy_uuid,
        "local_seq": 0,
        "ref_high_water": 0,
    }


def validate_sequence_state(raw: Any, path: str, strategy_uuid: Optional[str]) -> dict:
    """Validate a parsed sequence file; ``strategy_uuid=None`` skips the owner check."""
    if not isinstance(raw, dict):
        raise LiveStateCorrupt(path, "not_a_mapping")
    if set(raw) != _KEYS:
        raise LiveStateCorrupt(path, "unexpected_keys")
    if raw["version"] != SEQUENCE_VERSION or type(raw["version"]) is not int:
        raise LiveStateCorrupt(path, "version_unsupported")
    if not is_uuid4(raw["strategy_uuid"]):
        raise LiveStateCorrupt(path, "invalid_field:strategy_uuid")
    for key in ("local_seq", "ref_high_water"):
        if not is_strict_int(raw[key], minimum=0):
            raise LiveStateCorrupt(path, f"invalid_field:{key}")
    if strategy_uuid is not None and raw["strategy_uuid"] != strategy_uuid:
        raise LiveStateIdentityMismatch("strategy_uuid_mismatch", "sequence.json")
    return dict(raw)


def is_pristine_sequence(raw: Any, path: str) -> bool:
    try:
        state = validate_sequence_state(raw, path, None)
    except LiveStateError:
        return False
    return state["local_seq"] == 0 and state["ref_high_water"] == 0


def _check_ref(ref: Any) -> int:
    if ref is None:
        return 0
    if not is_strict_int(ref, minimum=1):
        raise LiveStateError("invalid_ref", "ref must be a positive int or None")
    return ref


class SequenceAllocator:
    """Allocate strategy-local order sequence numbers for one strategy directory."""

    def __init__(self, strategy_dir: Any, strategy_uuid: str, *, lock_timeout: float = 10.0):
        if not is_uuid4(strategy_uuid):
            raise LiveStateError("invalid_strategy_uuid")
        self.paths = StatePaths(strategy_dir)
        self.strategy_uuid = strategy_uuid
        self.lock_timeout = lock_timeout

    @property
    def path(self) -> str:
        return self.paths.sequence

    def _lock(self):
        from .coordination import CoordinatedFileLock

        return CoordinatedFileLock(self.paths, self.paths.sequence_lock, timeout=self.lock_timeout)

    def read(self) -> dict:
        """Return the validated current state (a copy)."""
        try:
            raw = read_json(self.paths.sequence)
        except FileNotFoundError:
            raise LiveStateNotInitialized(self.paths.sequence) from None
        return validate_sequence_state(raw, self.paths.sequence, self.strategy_uuid)

    def allocate(self, ref: Optional[int] = None) -> int:
        """Durably allocate and return the next local sequence number.

        ``ref`` (the ``Order.ref`` of the order being numbered, if known) also
        raises ``ref_high_water``.  Raises on any lock, corruption or I/O
        failure; no number is returned unless it was persisted.
        """
        ref_value = _check_ref(ref)
        with self._lock():
            state = self.read()
            state["local_seq"] += 1
            if ref_value > state["ref_high_water"]:
                state["ref_high_water"] = ref_value
            atomic_write_json(self.paths.sequence, state)
            return state["local_seq"]

    def observe_ref(self, ref: int) -> int:
        """Raise ``ref_high_water`` to ``ref`` if higher; return the high-water mark."""
        ref_value = _check_ref(ref)
        with self._lock():
            state = self.read()
            if ref_value > state["ref_high_water"]:
                state["ref_high_water"] = ref_value
                atomic_write_json(self.paths.sequence, state)
            return state["ref_high_water"]

    @property
    def local_seq(self) -> int:
        return self.read()["local_seq"]

    @property
    def ref_high_water(self) -> int:
        return self.read()["ref_high_water"]

    def restore_ref_basis(self) -> int:
        """Advance ``backtrader.order.OrderBase.refbasis`` past ``ref_high_water``.

        ``itertools.count`` cannot be peeked, so this consumes one value
        (``current_next = next(OrderBase.refbasis)``) and installs
        ``itertools.count(max(current_next, ref_high_water + 1))``.  One ref
        value may therefore be skipped; refs are never reused.  Returns the
        next ref that will be assigned.

        Call it at startup, before any order is created.  It is serialized
        against other ``restore_ref_basis`` calls but not against concurrent
        ``Order`` construction in other threads.  Raises
        ``LiveStateError("ref_basis_shadowed")`` if an ``OrderBase`` subclass
        defines its own ``refbasis`` (the restore would not reach it).
        """
        high_water = self.read()["ref_high_water"]
        from backtrader import order as _order_module

        base = _order_module.OrderBase
        with _REF_BASIS_LOCK:
            pending = list(base.__subclasses__())
            while pending:
                klass = pending.pop()
                if "refbasis" in vars(klass):
                    raise LiveStateError("ref_basis_shadowed", klass.__name__)
                pending.extend(klass.__subclasses__())
            current_next = next(base.refbasis)
            start = max(current_next, high_water + 1)
            base.refbasis = itertools.count(start)
            return start
