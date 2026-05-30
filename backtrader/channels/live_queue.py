"""Thread-safe live event queue for real-time trading.

LiveEventQueue provides a thread-safe priority queue for handling events
from multiple WebSocket connections or data sources in real-time. It uses
threading locks and supports timeout-based blocking reads.

Example::

    queue = LiveEventQueue(maxsize=100000)

    # Producer thread (WebSocket callback)
    queue.put(tick_event, priority=EventPriority.TICK)

    # Consumer thread (strategy processing)
    event = queue.get(timeout=1.0)
    if event:
        process(event)
"""

import heapq
import threading
import time
from typing import Optional

from ..channel import Event, EventPriority
from ..utils.log_message import get_logger

logger = get_logger(__name__)

__all__ = ["LiveEventQueue"]


class LiveEventQueue:
    """Thread-safe priority event queue for live trading.

    Events are ordered by (timestamp, priority, sequence) just like
    StreamingEventQueue, but with thread-safety for concurrent producers
    and consumers.

    Args:
        maxsize: Maximum queue capacity. 0 = unlimited.
        drop_policy: What to do when full: 'drop_oldest' or 'drop_newest'.
    """

    def __init__(self, maxsize=0, drop_policy="drop_oldest"):
        """Initialize the priority queue for live events.

        Args:
            maxsize: Maximum queue size (0 for unlimited).
            drop_policy: Policy for dropping events when full ('drop_oldest' or 'drop_newest').
        """
        self._heap = []
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._sequence = 0
        self._maxsize = maxsize
        self._drop_policy = drop_policy
        self._total_put = 0
        self._total_get = 0
        self._total_dropped = 0
        self._closed = False

    def put(
        self,
        event_data,
        priority=EventPriority.TICK,
        channel_type="",
        channel_name="",
        timestamp=None,
    ):
        """Add an event to the queue (thread-safe).

        Args:
            event_data: The event data (EventData subclass).
            priority: Event priority.
            channel_type: Source channel type.
            channel_name: Source channel/symbol name.
            timestamp: Event timestamp. If None, uses event_data.timestamp
                       or current time.

        Returns:
            True if the event was added, False if dropped.
        """
        if self._closed:
            return False

        if timestamp is None:
            timestamp = getattr(event_data, "timestamp", time.time())

        with self._lock:
            event = Event(
                timestamp=timestamp,
                priority=priority,
                sequence=self._sequence,
                channel_type=channel_type,
                channel_name=channel_name,
                data=event_data,
            )
            self._sequence += 1

            if self._maxsize > 0 and len(self._heap) >= self._maxsize:
                if self._drop_policy == "drop_oldest":
                    heapq.heapreplace(self._heap, event)
                    self._total_dropped += 1
                else:
                    self._total_dropped += 1
                    return False
            else:
                heapq.heappush(self._heap, event)

            self._total_put += 1
            self._not_empty.notify()
            return True

    def get(self, timeout=None) -> Optional[Event]:
        """Get the next event from the queue (thread-safe, blocking).

        Args:
            timeout: Maximum seconds to wait. None = block forever.
                     0 = non-blocking.

        Returns:
            The next Event, or None if timeout expired or queue is closed.
        """
        with self._not_empty:
            if timeout == 0:
                if not self._heap:
                    return None
            else:
                end_time = None if timeout is None else time.monotonic() + timeout
                while not self._heap and not self._closed:
                    if timeout is None:
                        self._not_empty.wait()
                    else:
                        remaining = end_time - time.monotonic()
                        if remaining <= 0:
                            return None
                        self._not_empty.wait(timeout=remaining)

            if not self._heap:
                return None

            event = heapq.heappop(self._heap)
            self._total_get += 1
            return event

    def peek(self) -> Optional[Event]:
        """Peek at the next event without removing it (thread-safe)."""
        with self._lock:
            return self._heap[0] if self._heap else None

    def close(self):
        """Close the queue, unblocking any waiting consumers."""
        with self._not_empty:
            self._closed = True
            self._not_empty.notify_all()

    @property
    def closed(self):
        """Whether the queue has been closed."""
        return self._closed

    @property
    def size(self):
        """Current number of events in the queue."""
        with self._lock:
            return len(self._heap)

    @property
    def empty(self):
        """Whether the queue is empty."""
        with self._lock:
            return len(self._heap) == 0

    @property
    def stats(self):
        """Queue statistics."""
        with self._lock:
            return {
                "total_put": self._total_put,
                "total_get": self._total_get,
                "total_dropped": self._total_dropped,
                "current_size": len(self._heap),
                "closed": self._closed,
            }

    def __len__(self):
        """Return the current number of events in the queue.

        Returns:
            int: Number of events currently in the queue.
        """
        with self._lock:
            return len(self._heap)

    def __bool__(self):
        """Return whether the queue has any events.

        Returns:
            bool: True if the queue has at least one event, False otherwise.
        """
        with self._lock:
            return len(self._heap) > 0

    def __repr__(self):
        """Return a string representation of the queue.

        Returns:
            str: Representation showing size and statistics.
        """
        with self._lock:
            return (
                f"LiveEventQueue(size={len(self._heap)}, "
                f"put={self._total_put}, get={self._total_get}, "
                f"dropped={self._total_dropped})"
            )
