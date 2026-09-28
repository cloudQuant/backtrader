"""Independent persistent latch for the supported I10 MD-only operator entry.

This module records a one-shot attempt reservation for the code-owned supervisor.
It does not attest against a same-user caller deliberately invoking the SDK or
private Python functions outside that entry. It has no launcher,
provider adapter, runtime registration, credential lookup, or trading route.
Importing it and constructing a latch are inert; filesystem access starts only
when a caller invokes a latch method with an explicitly supplied path.
"""

from __future__ import annotations

import os
from pathlib import Path

from .ctp_i8_oneshot_md_diagnostic import _PersistentI8NoRetryLatch
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)


I10_SOURCE_COMMIT = "a6253a58b1ebca11f58c8836fbed757d0daf7582"
I10_LATCH_CONTENT = b"i10-readonly-md-attempted-v1\n"
I10_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    / "state"
    / "i10-readonly-md-supervisor-no-retry.latch"
)
I10_READ_ONLY = True
I10_ORDER_SUBMISSION_AUTHORIZED = False
I10_TRADING_CAPABILITIES: tuple[()] = ()


class PersistentI10OneShotAttemptLatch(_PersistentI8NoRetryLatch):
    """I10-only marker for the supported supervisor's first attempt.

    A caller must provide the path explicitly. The I10 marker has its own path
    and content and never reads or changes the I8 or I9 markers.
    """

    _latch_content = I10_LATCH_CONTENT

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def _verify_ancestor_chain(self) -> None:
        # Windows path spelling is not an identity check. In particular,
        # state/../state names the canonical marker but must not skip its
        # registered-runtime check. The inherited scan still checks every
        # original path component for a reparse point or symlink.
        path_key = os.path.normcase(os.path.normpath(os.fspath(self._path)))
        canonical_key = os.path.normcase(os.path.normpath(os.fspath(I10_LATCH_PATH)))
        if path_key != canonical_key:
            super()._verify_ancestor_chain()
            return

        registry = iteration41_runtime_registry()
        registration = registry.require_runtime_dir(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)
        if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
            raise OSError("latch_runtime_registration_invalid")
        with registry.verified_runtime_directory(registration):
            super()._verify_ancestor_chain()


__all__ = [
    "I10_LATCH_CONTENT",
    "I10_LATCH_PATH",
    "I10_ORDER_SUBMISSION_AUTHORIZED",
    "I10_READ_ONLY",
    "I10_SOURCE_COMMIT",
    "I10_TRADING_CAPABILITIES",
    "PersistentI10OneShotAttemptLatch",
]
