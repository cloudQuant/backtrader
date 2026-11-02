"""Backtrader-owned bounded queue for completed live bars."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any, Callable, Deque, Dict, Optional, Tuple


class StoreLiveBarQueue:
    """Own the Store's bounded completed-bar FIFO and its sticky loss state.

    SDK market subscriptions and their tick/orderbook queues live behind the
    SDK ``MarketStreamPort``. This queue only holds completed bars after they
    have crossed into Backtrader's Store projection.
    """

    _UNHEALTHY_CONTINUITY = frozenset(
        {
            "gap",
            "stale",
            "disconnected",
            "checksum_failed",
            "out_of_order",
            "invalid",
        }
    )

    def __init__(
        self,
        capacity: int,
        *,
        on_evicted: Callable[[Any, Any], None],
        on_stale: Callable[[Any, str], None],
        on_enqueued: Callable[[Any, str], None],
    ) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("live bar queue capacity must be a positive integer")
        if not all(callable(callback) for callback in (on_evicted, on_stale, on_enqueued)):
            raise TypeError("live bar queue callbacks must be callable")
        self.capacity = capacity
        self._on_evicted = on_evicted
        self._on_stale = on_stale
        self._on_enqueued = on_enqueued
        self._lock = threading.RLock()
        self._queues: Dict[Any, Deque[Any]] = defaultdict(
            lambda: deque(maxlen=self.capacity)
        )
        self._overflow_counts: Dict[Any, int] = {}
        self._stale_reasons: Dict[Any, str] = {}

    def pop(self, symbol: Any) -> Tuple[bool, Optional[Any]]:
        """Consume the oldest completed bar, preserving a queued ``None`` value."""
        with self._lock:
            queue = self._queues[symbol]
            return (True, queue.popleft()) if queue else (False, None)

    def snapshot(self, symbol: Any) -> Tuple[int, int, str]:
        """Return queue depth, total evictions, and the sticky stale reason."""
        with self._lock:
            queue = self._queues[symbol]
            return (
                len(queue),
                self._overflow_counts.get(symbol, 0),
                self._stale_reasons.get(symbol, ""),
            )

    def symbols(self) -> Tuple[Any, ...]:
        """Return symbols whose queues have been observed or populated."""
        with self._lock:
            return tuple(self._queues)

    def get(self, symbol: Any, default: Any = None) -> Any:
        """Return a read-only snapshot for the Store's existing Feed probe."""
        with self._lock:
            queue = self._queues.get(symbol)
            return tuple(queue) if queue is not None else default

    def stale_reason(self, symbol: Any) -> str:
        with self._lock:
            return self._stale_reasons.get(symbol, "")

    def mark_stale(self, symbol: Any, reason: str) -> str:
        """Latch the first queue discontinuity and project it to Store health."""
        with self._lock:
            return self._mark_stale_locked(symbol, str(reason))

    def enqueue(self, symbol: Any, bar: Any) -> None:
        """Append one bar, accounting for bounded eviction and unsafe input."""
        with self._lock:
            queue = self._queues[symbol]
            if len(queue) >= self.capacity:
                evicted = queue.popleft()
                self._overflow_counts[symbol] = self._overflow_counts.get(symbol, 0) + 1
                self._on_evicted(symbol, evicted)
                self._mark_stale_locked(symbol, "store_live_bar_queue_overflow")
                self._mark_bar_stale(bar, "store_live_bar_queue_overflow")

            unhealthy_reason = self._unhealthy_reason(bar)
            if unhealthy_reason is not None:
                self._mark_stale_locked(symbol, unhealthy_reason)

            queue.append(bar)
            event_id = self._event_id(bar)
            if event_id:
                self._on_enqueued(symbol, event_id)

    def _mark_stale_locked(self, symbol: Any, reason: str) -> str:
        self._stale_reasons.setdefault(symbol, reason)
        latched_reason = self._stale_reasons[symbol]
        self._on_stale(symbol, latched_reason)
        return latched_reason

    @staticmethod
    def _getter(value: Any) -> Callable[[str, Any], Any]:
        if isinstance(value, Mapping):
            return value.get
        return lambda key, default=None: getattr(value, key, default)

    @classmethod
    def _unhealthy_reason(cls, bar: Any) -> Optional[str]:
        getter = cls._getter(bar)
        missing = object()
        stale = getter("stale", missing)
        if stale is not missing and (type(stale) is not bool or stale):
            return (
                "store_live_bar_invalid_stale_marker"
                if type(stale) is not bool
                else "store_live_bar_stale"
            )
        continuity = getter("continuity_status", getter("continuity", missing))
        if continuity is missing or continuity is None:
            return None
        if type(continuity) is not str:
            return "store_live_bar_invalid_continuity"
        normalized = continuity.strip().lower()
        if normalized in cls._UNHEALTHY_CONTINUITY:
            return f"store_live_bar_{normalized or 'non_continuous'}"
        return None

    @staticmethod
    def _mark_bar_stale(bar: Any, reason: str) -> None:
        if isinstance(bar, dict):
            bar["stale"] = True
            bar["stale_reason"] = reason
            bar["continuity_status"] = "gap"
            return
        try:
            bar.stale = True
            bar.stale_reason = reason
            bar.continuity_status = "gap"
        except Exception:
            pass

    @classmethod
    def _event_id(cls, bar: Any) -> str:
        getter = cls._getter(bar)
        return str(getter("event_id", "") or "")
