"""Backtrader-owned bounded queue for completed live bars."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, Optional, Set, Tuple


@dataclass(frozen=True, eq=False)
class _QueuedLiveBar:
    generation: Optional[int]
    bar: Any


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
        self._queues: Dict[Any, Deque[_QueuedLiveBar]] = defaultdict(
            lambda: deque(maxlen=self.capacity)
        )
        self._overflow_counts: Dict[Any, int] = {}
        self._stale_reasons: Dict[Any, str] = {}
        self._generation_symbols: Dict[int, Set[Any]] = defaultdict(set)
        self._committed_generation = -1
        self._closed_through_generation = -1

    def pop(self, symbol: Any) -> Tuple[bool, Optional[Any]]:
        """Consume the oldest completed bar, preserving a queued ``None`` value."""
        with self._lock:
            queue = self._queues[symbol]
            return (True, queue.popleft().bar) if queue else (False, None)

    def pop_entry(
        self, symbol: Any
    ) -> Tuple[bool, Optional[Any], Optional[int]]:
        """Consume a bar with its local Store generation for lifecycle checks."""
        with self._lock:
            queue = self._queues[symbol]
            if not queue:
                return False, None, None
            entry = queue.popleft()
            return True, entry.bar, entry.generation

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

    def reset(self) -> None:
        """Discard queued bars and loss state before a new Store generation."""
        with self._lock:
            self._queues.clear()
            self._overflow_counts.clear()
            self._stale_reasons.clear()
            self._generation_symbols.clear()

    def get(self, symbol: Any, default: Any = None) -> Any:
        """Return a read-only snapshot for the Store's existing Feed probe."""
        with self._lock:
            queue = self._queues.get(symbol)
            return tuple(entry.bar for entry in queue) if queue is not None else default

    def stale_reason(self, symbol: Any) -> str:
        with self._lock:
            return self._stale_reasons.get(symbol, "")

    def mark_stale(self, symbol: Any, reason: str) -> str:
        """Latch the first queue discontinuity and project it to Store health."""
        with self._lock:
            return self._mark_stale_locked(symbol, str(reason))

    def enqueue(
        self, symbol: Any, bar: Any, *, generation: Optional[int] = None
    ) -> bool:
        """Append one bar, accounting for bounded eviction and unsafe input.

        ``None`` is reserved for constructor seed bars. Runtime bars carry the
        Store generation that admitted them so an aborted start can discard
        only entries from that attempt without reconstructing already-consumed
        or overflowed seed data.
        """
        if generation is not None and (
            type(generation) is not int or generation < 0
        ):
            raise ValueError("live bar generation must be a non-negative integer")
        with self._lock:
            if (
                generation is not None
                and generation <= self._closed_through_generation
            ):
                return False
            queue = self._queues[symbol]
            if len(queue) >= self.capacity:
                evicted = queue.popleft().bar
                self._overflow_counts[symbol] = self._overflow_counts.get(symbol, 0) + 1
                self._on_evicted(symbol, evicted)
                self._mark_stale_locked(symbol, "store_live_bar_queue_overflow")
                self._mark_bar_stale(bar, "store_live_bar_queue_overflow")

            unhealthy_reason = self._unhealthy_reason(bar)
            if unhealthy_reason is not None:
                self._mark_stale_locked(symbol, unhealthy_reason)

            queue.append(_QueuedLiveBar(generation, bar))
            if generation is not None and generation > self._committed_generation:
                self._generation_symbols[generation].add(symbol)
            event_id = self._event_id(bar)
            if event_id:
                self._on_enqueued(symbol, event_id)
            return True

    def commit_generation(self, generation: int) -> None:
        """Forget temporary failure tracking after a successful Store start."""
        with self._lock:
            self._committed_generation = max(self._committed_generation, generation)
            for symbol, queue in self._queues.items():
                self._queues[symbol] = deque(
                    (
                        _QueuedLiveBar(generation, entry.bar)
                        if entry.generation is None
                        else entry
                        for entry in queue
                    ),
                    maxlen=self.capacity,
                )
            for previous in tuple(self._generation_symbols):
                if previous <= self._committed_generation:
                    self._generation_symbols.pop(previous, None)

    def discard_generation(
        self, generation: int
    ) -> Tuple[Tuple[Any, ...], Tuple[Tuple[Any, Any], ...]]:
        """Close a failed generation and remove only its still-queued bars.

        The first tuple includes symbols whose generation bars were already
        consumed or evicted. The second contains the exact queued bar objects
        removed. Existing seed bars and all queue loss counters/reasons remain
        untouched.
        """
        if type(generation) is not int or generation < 0:
            raise ValueError("live bar generation must be a non-negative integer")
        with self._lock:
            self._closed_through_generation = max(
                self._closed_through_generation, generation
            )
            symbols = set(self._generation_symbols.pop(generation, set()))
            removed = []
            for symbol, queue in self._queues.items():
                retained = deque(maxlen=self.capacity)
                for entry in queue:
                    if entry.generation == generation:
                        symbols.add(symbol)
                        removed.append((symbol, entry.bar))
                    else:
                        retained.append(entry)
                self._queues[symbol] = retained
            return tuple(symbols), tuple(removed)

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
