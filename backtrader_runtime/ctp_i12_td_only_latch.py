"""Independent persistent one-shot latch for the I12 TD-only diagnostic.

This marker is separate from every earlier diagnostic marker.  The module and
latch constructor are inert; filesystem access occurs only when a latch method
is called with its explicit path.
"""

from __future__ import annotations

import os
from pathlib import Path

from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)


I12_LATCH_CONTENT = b"i12-td-only-readonly-attempted-v1\n"
I12_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    / "state"
    / "i12-td-only-readonly-supervisor-no-retry.latch"
)
I12_READ_ONLY = True
I12_ORDER_SUBMISSION_AUTHORIZED = False
I12_TRADING_CAPABILITIES: tuple[()] = ()


def _new_latch_primitive(path: Path) -> object:
    """Load the hardened marker primitive only when the latch is used."""

    from .ctp_i8_oneshot_md_diagnostic import _PersistentI8NoRetryLatch

    class _PersistentI12LatchPrimitive(_PersistentI8NoRetryLatch):
        _latch_content = I12_LATCH_CONTENT

        def _verify_ancestor_chain(self) -> None:
            path_key = os.path.normcase(os.path.normpath(os.fspath(self._path)))
            canonical_key = os.path.normcase(os.path.normpath(os.fspath(I12_LATCH_PATH)))
            if path_key != canonical_key:
                super()._verify_ancestor_chain()
                return

            registry = iteration41_runtime_registry()
            registration = registry.require_runtime_dir(
                ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
            )
            if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
                raise OSError("latch_runtime_registration_invalid")
            with registry.verified_runtime_directory(registration):
                super()._verify_ancestor_chain()

    return _PersistentI12LatchPrimitive(path)


class PersistentI12TdOnlyAttemptLatch:
    """Lazy I12-only facade over the hardened persistent marker protocol."""

    def __init__(self, path: Path = I12_LATCH_PATH) -> None:
        self._path = Path(path)
        self._attempt_reserved = False
        self._delegate: object | None = None

    def _active_delegate(self) -> object:
        if self._delegate is None:
            self._delegate = _new_latch_primitive(self._path)
        return self._delegate

    def begin_attempt(self) -> bool:
        """Atomically reserve this I12 attempt before child creation."""

        begin = getattr(self._active_delegate(), "begin_attempt", None)
        if not callable(begin):
            raise OSError("latch_runtime_registration_invalid")
        reserved = begin()
        if reserved is True:
            self._attempt_reserved = True
        return reserved

    def is_tripped(self) -> bool:
        """Read only this I12 marker's durable no-retry state."""

        is_tripped = getattr(self._active_delegate(), "is_tripped", None)
        if not callable(is_tripped):
            raise OSError("latch_runtime_registration_invalid")
        return is_tripped()

    def trip(self, reason: str) -> bool:
        """Keep parity with the supervisor's caller-owned latch protocol."""

        trip = getattr(self._active_delegate(), "trip", None)
        if not callable(trip):
            raise OSError("latch_runtime_registration_invalid")
        return trip(reason)


__all__ = [
    "I12_LATCH_CONTENT",
    "I12_LATCH_PATH",
    "I12_ORDER_SUBMISSION_AUTHORIZED",
    "I12_READ_ONLY",
    "I12_TRADING_CAPABILITIES",
    "PersistentI12TdOnlyAttemptLatch",
]
