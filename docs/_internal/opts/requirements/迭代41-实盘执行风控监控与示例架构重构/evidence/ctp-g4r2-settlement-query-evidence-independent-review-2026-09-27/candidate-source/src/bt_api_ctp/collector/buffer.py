"""Per-instrument tick buffer with bounded memory.

The market-data callback path only appends here.  A separate flush loop
drains the buffer and hands batches to the sink, so the callback never
performs IO.
"""

from __future__ import annotations

import threading
from collections import deque

from bt_api_ctp.collector.protocols import TickRecord

_VALID_POLICIES = ("drop", "flush")

#: ``flush`` policy keeps accepting data above the soft cap up to this
#: multiple, giving the flush loop room to drain before anything is lost.
_FLUSH_HARD_CAP_MULTIPLE = 2


class TickBuffer:
    """Bounded, thread-safe, per-instrument append buffer.

    ``per_instrument_cap`` is a hard limit under the ``drop`` policy and a
    soft watermark under ``flush`` (which keeps data until twice the cap).
    """

    def __init__(
        self,
        *,
        per_instrument_cap: int = 100_000,
        overflow_policy: str = "drop",
    ) -> None:
        if per_instrument_cap < 1:
            raise ValueError("per_instrument_cap must be >= 1")
        if overflow_policy not in _VALID_POLICIES:
            raise ValueError(f"overflow_policy must be one of {_VALID_POLICIES}")

        self._cap = int(per_instrument_cap)
        self._policy = overflow_policy
        self._hard_cap = (
            self._cap
            if overflow_policy == "drop"
            else self._cap * _FLUSH_HARD_CAP_MULTIPLE
        )
        self._buckets: dict[str, deque[TickRecord]] = {}
        self._dropped = 0
        self._flush_requested = False
        self._lock = threading.Lock()

    def append(self, tick: TickRecord) -> bool:
        """Append one tick.  Returns ``False`` when the tick was discarded."""
        with self._lock:
            bucket = self._buckets.get(tick.instrument_id)
            if bucket is None:
                bucket = deque()
                self._buckets[tick.instrument_id] = bucket

            if len(bucket) >= self._hard_cap:
                self._dropped += 1
                self._flush_requested = True
                return False

            bucket.append(tick)
            if len(bucket) >= self._cap:
                self._flush_requested = True
            return True

    def drain(self) -> dict[str, list[TickRecord]]:
        """Return all buffered ticks grouped by instrument and clear them."""
        with self._lock:
            drained = {name: list(bucket) for name, bucket in self._buckets.items() if bucket}
            self._buckets = {}
            self._flush_requested = False
            return drained

    def pending(self) -> int:
        """Return the number of buffered ticks."""
        with self._lock:
            return sum(len(bucket) for bucket in self._buckets.values())

    def dropped_count(self) -> int:
        """Return how many ticks were discarded by the hard cap."""
        with self._lock:
            return self._dropped

    def should_flush(self) -> bool:
        """Return whether any instrument reached the soft cap."""
        with self._lock:
            return self._flush_requested

    def instruments(self) -> list[str]:
        """Return instrument ids currently holding data."""
        with self._lock:
            return [name for name, bucket in self._buckets.items() if bucket]


__all__ = ["TickBuffer"]
