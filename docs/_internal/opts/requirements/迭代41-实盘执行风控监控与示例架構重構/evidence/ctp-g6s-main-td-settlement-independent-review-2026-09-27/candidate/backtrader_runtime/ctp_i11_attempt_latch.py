"""Independent persistent latch for the I11 read-only MD diagnostic.

I11 reuses the exact SDK source commit and wheel already reviewed for I10, but
has a separate permanent attempt marker. The latch grants no provider session,
write authority, launcher, or runtime registration. Importing and constructing
it are inert; filesystem access starts only when a latch method is called with
an explicitly supplied path.
"""

from __future__ import annotations

import os
from pathlib import Path

from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)


I11_SDK_SOURCE_COMMIT = "a6253a58b1ebca11f58c8836fbed757d0daf7582"
I11_REUSED_I10_WHEEL_SHA256 = "e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4"
I11_LATCH_CONTENT = b"i11-readonly-md-attempted-v1\n"
I11_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    / "state"
    / "i11-readonly-md-supervisor-no-retry.latch"
)
I11_READ_ONLY = True
I11_ORDER_SUBMISSION_AUTHORIZED = False
I11_TRADING_CAPABILITIES: tuple[()] = ()


def _new_latch_primitive(path: Path) -> object:
    """Load the hardened file primitive only after I11's front precheck."""

    from .ctp_i8_oneshot_md_diagnostic import _PersistentI8NoRetryLatch

    class _PersistentI11LatchPrimitive(_PersistentI8NoRetryLatch):
        _latch_content = I11_LATCH_CONTENT

        def _verify_ancestor_chain(self) -> None:
            # Check normalized aliases against the fixed runtime marker
            # identity; otherwise ``state/../state`` could bypass the
            # registered-dir check. The inherited scan checks original parts.
            path_key = os.path.normcase(os.path.normpath(os.fspath(self._path)))
            canonical_key = os.path.normcase(os.path.normpath(os.fspath(I11_LATCH_PATH)))
            if path_key != canonical_key:
                super()._verify_ancestor_chain()
                return

            registry = iteration41_runtime_registry()
            registration = registry.require_runtime_dir(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)
            if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
                raise OSError("latch_runtime_registration_invalid")
            with registry.verified_runtime_directory(registration):
                super()._verify_ancestor_chain()

    return _PersistentI11LatchPrimitive(path)


class PersistentI11OneShotAttemptLatch:
    """I11-only lazy facade over the hardened I8 file protocol.

    The marker has its own path and content and never reads, resets, or changes
    I10 or earlier markers. Construction is inert; the I8 file primitive is
    imported only when a caller invokes a latch method.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._attempt_reserved = False
        self._delegate: object | None = None

    def _active_delegate(self) -> object:
        if self._delegate is None:
            self._delegate = _new_latch_primitive(self._path)
        return self._delegate

    def _verify_ancestor_chain(self) -> None:
        """Preserve the focused path-validation hook with lazy loading."""

        verify = getattr(self._active_delegate(), "_verify_ancestor_chain", None)
        if not callable(verify):
            raise OSError("latch_runtime_registration_invalid")
        verify()

    def begin_attempt(self) -> bool:
        """Atomically commit this I11 permanent no-retry marker."""

        begin = getattr(self._active_delegate(), "begin_attempt", None)
        if not callable(begin):
            raise OSError("latch_runtime_registration_invalid")
        reserved = begin()
        if reserved is True:
            self._attempt_reserved = True
        return reserved

    def is_tripped(self) -> bool:
        """Read whether the permanent I11 reservation exists."""

        is_tripped = getattr(self._active_delegate(), "is_tripped", None)
        if not callable(is_tripped):
            raise OSError("latch_runtime_registration_invalid")
        return is_tripped()

    def trip(self, reason: str) -> bool:
        """Keep parity with the shared latch primitive's fail-closed API."""

        trip = getattr(self._active_delegate(), "trip", None)
        if not callable(trip):
            raise OSError("latch_runtime_registration_invalid")
        return trip(reason)


__all__ = [
    "I11_LATCH_CONTENT",
    "I11_LATCH_PATH",
    "I11_ORDER_SUBMISSION_AUTHORIZED",
    "I11_READ_ONLY",
    "I11_REUSED_I10_WHEEL_SHA256",
    "I11_SDK_SOURCE_COMMIT",
    "I11_TRADING_CAPABILITIES",
    "PersistentI11OneShotAttemptLatch",
]
