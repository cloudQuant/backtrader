"""Historical I9 artifact and independent attempt-latch evidence.

This module deliberately contains no child command, provider call, CLI entry,
or launcher. The I9 SDK wheel is pinned for audit evidence only; its login
submit and login-state publication boundaries remain under review.
"""

from __future__ import annotations

from pathlib import Path

from .ctp_i8_oneshot_md_diagnostic import _PersistentI8NoRetryLatch
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)


I9_SOURCE_COMMIT = "157d0c0cffa4c8a86e196159cdf227e9014e9118"
I9_LATCH_CONTENT = b"i9-readonly-md-attempted-v1\n"
I9_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR / "state" / "i9-readonly-md-supervisor-no-retry.latch"
)


class PersistentI9OneShotAttemptLatch(_PersistentI8NoRetryLatch):
    """Independent I9 marker using the reviewed owner-only file protocol.

    The instance reads and writes only ``I9_LATCH_PATH``. Sharing the hardened
    file protocol does not share, inspect, or mutate the I8 marker. A caller
    must supply a path explicitly so importing or casually constructing this
    audit-only candidate cannot touch the real runtime latch.
    """

    _latch_content = I9_LATCH_CONTENT

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def _verify_ancestor_chain(self) -> None:
        if self._path != I9_LATCH_PATH:
            super()._verify_ancestor_chain()
            return

        registry = iteration41_runtime_registry()
        registration = registry.require_runtime_dir(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)
        if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
            raise OSError("latch_runtime_registration_invalid")
        with registry.verified_runtime_directory(registration):
            super()._verify_ancestor_chain()


__all__ = [
    "I9_LATCH_CONTENT",
    "I9_LATCH_PATH",
    "I9_SOURCE_COMMIT",
    "PersistentI9OneShotAttemptLatch",
]
