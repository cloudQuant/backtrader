"""Data channel infrastructure for tick-level backtesting.

This module provides the core channel system:
- Event / EventPriority: Event wrapper with priority for queue ordering
- DataChannel: Base class for all data channels (Tick, OrderBook, Funding)
- DataValidationResult: Result container for data validation
- StreamingEventQueue: Memory-efficient event queue with adaptive preloading
- ChannelSharingMode: Enum for channel sharing between strategies

The channel system is independent of LineSeries and uses deque for buffering,
enabling high-frequency event processing without the overhead of the
traditional bar-based data system.

Example:
    Basic event queue usage::

        queue = StreamingEventQueue(channels=[tick_channel], bars=[])
        while not queue.empty:
            event = queue.pop()
            process(event)
"""

import heapq
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EventPriority(IntEnum):
    """Event processing priority (lower value = higher priority).

    Within the same timestamp, events are processed in priority order.
    """

    SYSTEM = 0
    FUNDING = 10
    ORDERBOOK = 20
    TICK = 30
    BAR = 40


@dataclass(order=True)
class Event:
    """Event wrapper for queue ordering.

    Events are ordered by (timestamp, priority, sequence) for deterministic
    processing order. The data field is excluded from comparison.

    Attributes:
        timestamp: Event timestamp (seconds).
        priority: Processing priority (lower = first).
        sequence: Insertion sequence number for stable sort.
        channel_type: Source channel type identifier.
        channel_name: Source channel/symbol name.
        data: The actual event data (EventData subclass instance).
    """

    timestamp: float = 0.0
    priority: int = field(default=EventPriority.TICK)
    sequence: int = field(default=0, compare=True)
    channel_type: str = field(default="", compare=False)
    channel_name: str = field(default="", compare=False)
    data: Any = field(default=None, compare=False, repr=False)


class ChannelSharingMode(Enum):
    """Channel sharing mode between strategies.

    - EXCLUSIVE: One strategy owns the channel exclusively.
    - SHARED_READONLY: Multiple strategies can read, none can modify.
    - SHARED_ISOLATED: Each strategy gets its own cursor/state.
    - SHARED_FULL: Full sharing with write access (use with caution).
    """

    EXCLUSIVE = "exclusive"
    SHARED_READONLY = "shared_readonly"
    SHARED_ISOLATED = "shared_isolated"
    SHARED_FULL = "shared_full"


@dataclass
class DataValidationResult:
    """Result of data validation.

    Attributes:
        valid: Whether the data passed validation.
        errors: List of error descriptions.
        warnings: List of warning descriptions.
        auto_fixed: Whether the data was auto-fixed.
        fixed_fields: Dict of field names to (original, fixed) values.
    """

    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    auto_fixed: bool = False
    fixed_fields: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)


class DataChannel:
    """Base class for all data channels.

    Channels provide buffered, validated data streams independent of
    the LineSeries system. Each channel type (Tick, OrderBook, Funding)
    subclasses DataChannel and implements type-specific validation.

    Attributes:
        symbol: Trading pair symbol.
        channel_type: Channel type identifier (set by subclasses).
        maxlen: Maximum buffer size.
        sharing_mode: How the channel is shared between strategies.

    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        maxlen: Maximum number of events to buffer.
        validate: Whether to validate incoming events.
        auto_fix: Whether to attempt auto-fixing invalid data.
        sharing_mode: Channel sharing mode.
        **kwargs: Additional channel parameters.
    """

    channel_type = "generic"

    def __init__(
        self,
        symbol,
        maxlen=10000,
        validate=True,
        auto_fix=True,
        sharing_mode=ChannelSharingMode.SHARED_READONLY,
        **kwargs,
    ):
        """Initialize a DataChannel.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT').
            maxlen: Maximum number of events to buffer.
            validate: Whether to validate incoming events.
            auto_fix: Whether to attempt auto-fixing invalid data.
            sharing_mode: Channel sharing mode between strategies.
            **kwargs: Additional channel parameters.
        """
        self.symbol = symbol
        self.maxlen = maxlen
        self.params = kwargs
        self._buffer = deque(maxlen=maxlen)
        self._event_count = 0
        self._validate = validate
        self._auto_fix = auto_fix
        self._validation_errors = []
        self._last_timestamp = None
        self.sharing_mode = sharing_mode
        self._strategy_states = {}
        self._dataname = kwargs.get("dataname", None)

    @property
    def latest(self):
        """Get the most recent event in the buffer."""
        return self._buffer[-1] if self._buffer else None

    @property
    def event_count(self):
        """Total number of events pushed to this channel."""
        return self._event_count

    @property
    def buffer_size(self):
        """Current number of events in the buffer."""
        return len(self._buffer)

    def push(self, event) -> bool:
        """Push an event into the channel buffer.

        If validation is enabled, the event is validated (and potentially
        auto-fixed) before being added to the buffer.

        Args:
            event: An EventData subclass instance.

        Returns:
            True if the event was accepted, False if rejected.
        """
        if self._validate:
            result = self._validate_event(event)
            if not result.valid:
                self._validation_errors.append(result)
                return False
            if result.auto_fixed:
                logger.debug("Auto-fixed event for %s: %s", self.symbol, result.fixed_fields)

        self._buffer.append(event)
        self._event_count += 1
        self._last_timestamp = event.timestamp
        return True

    def _validate_event(self, event) -> DataValidationResult:
        """Validate an event. Override in subclasses for type-specific checks.

        Args:
            event: The event to validate.

        Returns:
            DataValidationResult with validation outcome.
        """
        result = DataValidationResult()

        # Basic validation
        if not hasattr(event, "timestamp"):
            result.valid = False
            result.errors.append("Event missing timestamp")
            return result

        if not hasattr(event, "validate") or not event.validate():
            result.valid = False
            result.errors.append("Event failed built-in validation")
            return result

        # Timestamp ordering check
        if self._last_timestamp is not None:
            if event.timestamp < self._last_timestamp:
                if self._auto_fix:
                    result.warnings.append(
                        f"Out-of-order timestamp: {event.timestamp} < {self._last_timestamp}"
                    )
                    result.auto_fixed = True
                    result.fixed_fields["timestamp"] = (event.timestamp, self._last_timestamp)
                    event.timestamp = self._last_timestamp
                else:
                    result.valid = False
                    result.errors.append(
                        f"Out-of-order timestamp: {event.timestamp} < {self._last_timestamp}"
                    )

        return result

    def get_state(self, strategy_id: str) -> dict:
        """Get per-strategy state for isolated sharing mode.

        Args:
            strategy_id: Unique identifier for the strategy.

        Returns:
            Dict containing the strategy's channel state.
        """
        if strategy_id not in self._strategy_states:
            self._strategy_states[strategy_id] = {
                "cursor": 0,
                "last_event": None,
            }
        return self._strategy_states[strategy_id]

    def load(self) -> Iterator:
        """Load events from the data source.

        Subclasses should override this to implement data loading from
        files, databases, or other sources.

        Yields:
            EventData instances.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement load()")

    def get_validation_errors(self) -> List[DataValidationResult]:
        """Get all validation errors encountered."""
        return list(self._validation_errors)

    def clear_validation_errors(self):
        """Clear accumulated validation errors."""
        self._validation_errors.clear()

    def __len__(self):
        """Return the current number of events in the buffer.

        Returns:
            int: Number of events currently buffered.
        """
        return len(self._buffer)

    def __iter__(self):
        """Iterate over events in the buffer.

        Returns:
            Iterator over events in insertion order.
        """
        return iter(self._buffer)

    def __repr__(self):
        """Return a string representation of the channel.

        Returns:
            str: Representation showing symbol, type, and event counts.
        """
        return (
            f"{self.__class__.__name__}(symbol={self.symbol!r}, "
            f"type={self.channel_type!r}, "
            f"events={self._event_count}, "
            f"buffered={len(self._buffer)})"
        )


class StreamingEventQueue:
    """Memory-efficient event queue with adaptive preloading.

    Merges events from multiple channels and bar data sources into a
    single ordered stream. Uses a heap (priority queue) for efficient
    merging and supports adaptive preload windows to control memory usage.

    The queue loads data in chunks rather than all at once, keeping
    memory usage bounded regardless of total data size.

    Args:
        channels: List of DataChannel instances.
        bars: List of bar data iterators.
        preload_window: Initial preload time window in seconds.
        max_memory_mb: Maximum memory target in MB.
        adaptive: Whether to adapt the preload window based on memory.
        batch_size: Number of events to load per batch from each channel.

    Example::

        queue = StreamingEventQueue(
            channels=[tick_channel, ob_channel],
            bars=[bar_data],
            preload_window=300.0,
            max_memory_mb=200,
            adaptive=True
        )
        while not queue.empty:
            event = queue.pop()
            # process event
    """

    def __init__(
        self,
        channels=None,
        bars=None,
        preload_window=300.0,
        max_memory_mb=200,
        adaptive=True,
        batch_size=10000,
    ):
        """Initialize a StreamingEventQueue.

        Args:
            channels: List of DataChannel instances.
            bars: List of bar data iterators.
            preload_window: Initial preload time window in seconds.
            max_memory_mb: Maximum memory target in MB.
            adaptive: Whether to adapt the preload window based on memory.
            batch_size: Number of events to load per batch from each channel.
        """
        self._channels = channels or []
        self._bars = bars or []
        self._window = preload_window
        self._max_memory = max_memory_mb * 1024 * 1024
        self._adaptive = adaptive
        self._batch_size = batch_size

        # Heap: (timestamp, priority, sequence, Event)
        self._heap = []
        self._sequence = 0

        # Tracking
        self._current_ts = float("-inf")
        self._preload_up_to = float("-inf")

        # Channel iterators (lazy initialized)
        self._channel_iters = {}
        self._bar_iters = {}
        self._channel_exhausted = set()
        self._bar_exhausted = set()

        # Adaptive window parameters
        self._window_min = 60.0
        self._window_max = 600.0
        self._adjustment_count = 0

        # Statistics
        self._total_events_popped = 0

        # Initialize iterators
        self._init_iterators()
        # Initial preload
        self._ensure_preload()

    def _init_iterators(self):
        """Initialize iterators for all channels and bar data."""
        for i, channel in enumerate(self._channels):
            try:
                self._channel_iters[i] = iter(channel.load())
            except Exception as e:
                logger.warning("Failed to init iterator for channel %s: %s", channel, e)
                self._channel_exhausted.add(i)

        for i, bar_data in enumerate(self._bars):
            try:
                self._bar_iters[i] = iter(bar_data)
            except Exception as e:
                logger.warning("Failed to init iterator for bar data %d: %s", i, e)
                self._bar_exhausted.add(i)

    def _ensure_preload(self):
        """Ensure events are preloaded up to the current window boundary.

        Loads events from all channels and bar data sources up to the target
        timestamp (current timestamp + preload window). Skips already-loaded
        ranges to avoid redundant work.
        """
        if self._current_ts == float("-inf"):
            # Initial load: use inf to load the first batch fully
            target_ts = float("inf")
        else:
            target_ts = self._current_ts + self._window
        if target_ts <= self._preload_up_to:
            return

        # Load from channels
        for idx, ch_iter in list(self._channel_iters.items()):
            if idx in self._channel_exhausted:
                continue
            self._load_from_channel(idx, ch_iter, target_ts)

        # Load from bar data
        for idx, bar_iter in list(self._bar_iters.items()):
            if idx in self._bar_exhausted:
                continue
            self._load_from_bars(idx, bar_iter, target_ts)

        self._preload_up_to = target_ts

    def _load_from_channel(self, idx, ch_iter, target_ts):
        """Load events from a channel iterator up to target timestamp.

        Args:
            idx: Index of the channel.
            ch_iter: Iterator for the channel.
            target_ts: Target timestamp to load up to.
        """
        channel = self._channels[idx]
        loaded = 0

        try:
            while loaded < self._batch_size:
                event = next(ch_iter)
                if not hasattr(event, "timestamp"):
                    continue

                wrapped = Event(
                    timestamp=event.timestamp,
                    priority=self._get_channel_priority(channel),
                    sequence=self._sequence,
                    channel_type=channel.channel_type,
                    channel_name=channel.symbol,
                    data=event,
                )
                self._sequence += 1
                heapq.heappush(self._heap, wrapped)
                loaded += 1

                if event.timestamp > target_ts:
                    break

        except StopIteration:
            self._channel_exhausted.add(idx)

    def _load_from_bars(self, idx, bar_iter, target_ts):
        """Load events from a bar data iterator up to target timestamp.

        Args:
            idx: Index of the bar data source.
            bar_iter: Iterator for the bar data source.
            target_ts: Target timestamp to load up to.
        """
        loaded = 0

        try:
            while loaded < self._batch_size:
                bar_event = next(bar_iter)
                if not hasattr(bar_event, "timestamp"):
                    continue

                wrapped = Event(
                    timestamp=bar_event.timestamp,
                    priority=EventPriority.BAR,
                    sequence=self._sequence,
                    channel_type="bar",
                    channel_name=getattr(bar_event, "symbol", ""),
                    data=bar_event,
                )
                self._sequence += 1
                heapq.heappush(self._heap, wrapped)
                loaded += 1

                if bar_event.timestamp > target_ts:
                    break

        except StopIteration:
            self._bar_exhausted.add(idx)

    def _get_channel_priority(self, channel) -> int:
        """Map channel type to event priority."""
        priority_map = {
            "tick": EventPriority.TICK,
            "orderbook": EventPriority.ORDERBOOK,
            "funding_rate": EventPriority.FUNDING,
            "funding": EventPriority.FUNDING,
            "bar": EventPriority.BAR,
        }
        return priority_map.get(channel.channel_type, EventPriority.TICK)

    @property
    def empty(self) -> bool:
        """Whether the queue is empty and all sources exhausted."""
        if self._heap:
            return False
        # Try loading more
        all_exhausted = self._channel_exhausted.issuperset(
            self._channel_iters.keys()
        ) and self._bar_exhausted.issuperset(self._bar_iters.keys())
        if all_exhausted:
            return True
        # Try preloading ahead
        self._preload_up_to = float("-inf")
        self._ensure_preload()
        return len(self._heap) == 0

    def pop(self) -> Optional[Event]:
        """Pop the next event from the queue.

        Returns the event with the smallest (timestamp, priority, sequence).
        Triggers preloading if needed.

        Returns:
            The next Event, or None if the queue is empty.
        """
        if not self._heap:
            if self.empty:
                return None

        if not self._heap:
            return None

        event = heapq.heappop(self._heap)
        self._current_ts = event.timestamp
        self._total_events_popped += 1

        # Trigger preload if we're getting close to the boundary
        if self._current_ts + self._window * 0.5 >= self._preload_up_to:
            self._ensure_preload()

        # Adaptive window adjustment
        if self._adaptive and self._total_events_popped % 1000 == 0:
            self._adjust_window()

        return event

    def peek(self) -> Optional[Event]:
        """Peek at the next event without removing it.

        Returns:
            The next Event, or None if the queue is empty.
        """
        if not self._heap:
            if self.empty:
                return None
        return self._heap[0] if self._heap else None

    def _adjust_window(self):
        """Adjust preload window based on current memory usage.

        Shrinks the window if memory usage exceeds 80% of the maximum,
        grows it if usage is below 30% and the window is below maximum.
        Adjustments are made gradually (multiply by 0.7 or 1.3) to avoid
        oscillation.
        """
        mem_usage = self._estimate_memory_usage()

        if mem_usage > self._max_memory * 0.8:
            # Shrink window
            self._window = max(self._window_min, self._window * 0.7)
            self._adjustment_count += 1
            logger.debug(
                "Shrinking preload window to %.0fs (memory: %.1fMB)",
                self._window,
                mem_usage / 1024 / 1024,
            )
        elif mem_usage < self._max_memory * 0.3 and self._window < self._window_max:
            # Grow window
            self._window = min(self._window_max, self._window * 1.3)
            self._adjustment_count += 1
            logger.debug(
                "Growing preload window to %.0fs (memory: %.1fMB)",
                self._window,
                mem_usage / 1024 / 1024,
            )

    def _estimate_memory_usage(self) -> int:
        """Estimate current memory usage of the heap.

        Returns:
            Estimated memory usage in bytes.
        """
        # Rough estimate: each event ~200 bytes (dataclass + heap entry)
        return len(self._heap) * 200

    @property
    def heap_size(self) -> int:
        """Current number of events in the heap."""
        return len(self._heap)

    @property
    def total_events_popped(self) -> int:
        """Total number of events popped from the queue."""
        return self._total_events_popped

    @property
    def current_timestamp(self) -> float:
        """Current processing timestamp."""
        return self._current_ts

    def __len__(self):
        """Return the current number of events in the heap.

        Returns:
            int: Number of events currently in the heap.
        """
        return len(self._heap)

    def __iter__(self):
        """Iterate over all events in timestamp order.

        Yields:
            Event: The next event in timestamp order.
        """
        while not self.empty:
            event = self.pop()
            if event is not None:
                yield event

    def __bool__(self):
        """Return whether the queue has events available.

        Returns:
            bool: True if the queue is not empty, False otherwise.
        """
        return not self.empty

    def __repr__(self):
        """Return a string representation of the queue.

        Returns:
            str: Representation showing heap size, popped count, and window.
        """
        return (
            f"StreamingEventQueue(heap={len(self._heap)}, "
            f"popped={self._total_events_popped}, "
            f"window={self._window:.0f}s)"
        )
