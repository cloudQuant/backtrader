"""Unit tests for backtrader/channel.py - DataChannel, Event, StreamingEventQueue."""

import pytest
from backtrader.channel import (
    ChannelSharingMode,
    DataChannel,
    DataValidationResult,
    Event,
    EventPriority,
    StreamingEventQueue,
)
from backtrader.events import TickEvent


# ============================================================
# Event Tests
# ============================================================

class TestEvent:
    """Test cases for the Event class."""

    def test_event_ordering_by_timestamp(self):
        """Test that events are ordered by timestamp when other fields are equal."""
        e1 = Event(timestamp=100.0, priority=30, sequence=0)
        e2 = Event(timestamp=50.0, priority=30, sequence=1)
        assert e2 < e1

    def test_event_ordering_by_priority(self):
        """Test that events are ordered by priority when timestamps are equal."""
        e1 = Event(timestamp=100.0, priority=30, sequence=0)
        e2 = Event(timestamp=100.0, priority=10, sequence=1)
        assert e2 < e1

    def test_event_ordering_by_sequence(self):
        """Test that events are ordered by sequence when timestamp and priority are equal."""
        e1 = Event(timestamp=100.0, priority=30, sequence=1)
        e2 = Event(timestamp=100.0, priority=30, sequence=0)
        assert e2 < e1

    def test_event_defaults(self):
        """Test that Event objects are created with correct default values."""
        e = Event()
        assert e.timestamp == 0.0
        assert e.priority == EventPriority.TICK
        assert e.sequence == 0
        assert e.channel_type == ''
        assert e.data is None


class TestEventPriority:
    """Test cases for the EventPriority enum."""

    def test_priority_ordering(self):
        """Test that event priority levels are ordered correctly."""
        assert EventPriority.SYSTEM < EventPriority.FUNDING
        assert EventPriority.FUNDING < EventPriority.ORDERBOOK
        assert EventPriority.ORDERBOOK < EventPriority.TICK
        assert EventPriority.TICK < EventPriority.BAR


# ============================================================
# DataChannel Tests
# ============================================================

class TestDataChannel:
    """Test cases for the DataChannel class."""

    def test_basic_creation(self):
        """Test that a DataChannel is created with correct default attributes."""
        ch = DataChannel(symbol='BTC/USDT')
        assert ch.symbol == 'BTC/USDT'
        assert ch.channel_type == 'generic'
        assert ch.event_count == 0
        assert ch.buffer_size == 0
        assert ch.latest is None

    def test_push_valid_event(self):
        """Test that a valid event is successfully pushed to the channel."""
        ch = DataChannel(symbol='BTC/USDT')
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        result = ch.push(tick)
        assert result is True
        assert ch.event_count == 1
        assert ch.buffer_size == 1
        assert ch.latest is tick

    def test_push_invalid_event(self):
        """Test that an invalid event is rejected by the channel."""
        ch = DataChannel(symbol='BTC/USDT')
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=-1.0, volume=1.0, direction='buy')
        result = ch.push(tick)
        assert result is False
        assert ch.event_count == 0

    def test_push_out_of_order_auto_fix(self):
        """Test that out-of-order events have timestamps fixed when auto_fix is enabled."""
        ch = DataChannel(symbol='BTC/USDT', auto_fix=True)
        t1 = TickEvent(timestamp=200.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50001, volume=1.0, direction='sell')
        ch.push(t1)
        result = ch.push(t2)
        assert result is True
        # Timestamp should have been fixed to last known
        assert t2.timestamp == 200.0

    def test_push_out_of_order_no_auto_fix(self):
        """Test that out-of-order events are rejected when auto_fix is disabled."""
        ch = DataChannel(symbol='BTC/USDT', auto_fix=False)
        t1 = TickEvent(timestamp=200.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50001, volume=1.0, direction='sell')
        ch.push(t1)
        result = ch.push(t2)
        assert result is False

    def test_push_no_validation(self):
        """Test that events are not validated when validation is disabled."""
        ch = DataChannel(symbol='BTC/USDT', validate=False)
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=-1.0, volume=1.0, direction='buy')
        result = ch.push(tick)
        assert result is True
        assert ch.event_count == 1

    def test_buffer_maxlen(self):
        """Test that the channel buffer respects the maximum length limit."""
        ch = DataChannel(symbol='BTC/USDT', maxlen=3, validate=False)
        for i in range(5):
            tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000, volume=1.0, direction='buy')
            ch.push(tick)
        assert ch.event_count == 5
        assert ch.buffer_size == 3
        assert ch.latest.timestamp == 104.0

    def test_validation_errors(self):
        """Test that validation errors are tracked and can be cleared."""
        ch = DataChannel(symbol='BTC/USDT')
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=-1.0, volume=1.0, direction='buy')
        ch.push(tick)
        errors = ch.get_validation_errors()
        assert len(errors) == 1
        ch.clear_validation_errors()
        assert len(ch.get_validation_errors()) == 0

    def test_get_state(self):
        """Test that each strategy gets its own isolated state from the channel."""
        ch = DataChannel(symbol='BTC/USDT')
        state = ch.get_state('strategy_1')
        assert state['cursor'] == 0
        assert state['last_event'] is None
        # Same state returned on subsequent calls
        assert ch.get_state('strategy_1') is state
        # Different strategy gets different state
        state2 = ch.get_state('strategy_2')
        assert state2 is not state

    def test_sharing_mode(self):
        """Test that the channel is created with the specified sharing mode."""
        ch = DataChannel(symbol='X', sharing_mode=ChannelSharingMode.EXCLUSIVE)
        assert ch.sharing_mode == ChannelSharingMode.EXCLUSIVE

    def test_iter_and_len(self):
        """Test that the channel supports iteration and length reporting."""
        ch = DataChannel(symbol='BTC/USDT', validate=False)
        ticks = [TickEvent(timestamp=100.0 + i, symbol='X', price=50000, volume=1.0, direction='buy') for i in range(3)]
        for t in ticks:
            ch.push(t)
        assert len(ch) == 3
        assert list(ch) == ticks

    def test_repr(self):
        """Test that the channel representation contains key information."""
        ch = DataChannel(symbol='BTC/USDT')
        r = repr(ch)
        assert 'BTC/USDT' in r
        assert 'generic' in r

    def test_load_not_implemented(self):
        """Test that the default load method raises NotImplementedError."""
        ch = DataChannel(symbol='X')
        with pytest.raises(NotImplementedError):
            list(ch.load())


# ============================================================
# StreamingEventQueue Tests
# ============================================================

class _MockChannel:
    """Mock channel that yields events from a list."""

    channel_type = 'tick'

    def __init__(self, symbol, events):
        """Initialize the mock channel with a symbol and list of events.

        Args:
            symbol: The symbol identifier for this channel.
            events: List of events to yield from load().
        """
        self.symbol = symbol
        self._events = events

    def load(self):
        """Return an iterator over the stored events."""
        return iter(self._events)


class TestStreamingEventQueue:
    """Test cases for the StreamingEventQueue class."""

    def _make_ticks(self, timestamps):
        """Create a list of TickEvents from a list of timestamps.

        Args:
            timestamps: List of timestamp values for the ticks.

        Returns:
            List of TickEvent objects with the given timestamps.
        """
        return [
            TickEvent(timestamp=ts, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
            for ts in timestamps
        ]

    def test_empty_queue(self):
        """Test that an empty queue has no events and returns None on pop."""
        q = StreamingEventQueue(channels=[], bars=[])
        assert q.empty is True
        assert q.pop() is None

    def test_single_channel_ordering(self):
        """Test that events from a single channel are ordered by timestamp."""
        events = self._make_ticks([100.0, 50.0, 75.0])
        ch = _MockChannel('BTC/USDT', events)
        q = StreamingEventQueue(channels=[ch], bars=[], preload_window=1000)

        timestamps = []
        while not q.empty:
            e = q.pop()
            timestamps.append(e.timestamp)

        # All events loaded; ordered by timestamp in heap
        assert timestamps == sorted(timestamps)
        assert len(timestamps) == 3

    def test_multiple_channels_merged(self):
        """Test that events from multiple channels are merged in timestamp order."""
        ch1 = _MockChannel('BTC/USDT', self._make_ticks([100.0, 200.0, 300.0]))
        ch2 = _MockChannel('ETH/USDT', self._make_ticks([150.0, 250.0, 350.0]))
        q = StreamingEventQueue(channels=[ch1, ch2], bars=[], preload_window=1000)

        timestamps = []
        while not q.empty:
            e = q.pop()
            timestamps.append(e.timestamp)

        assert timestamps == [100.0, 150.0, 200.0, 250.0, 300.0, 350.0]

    def test_priority_within_same_timestamp(self):
        """Test that priority determines order when timestamps are equal."""
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        from backtrader.events import OrderBookSnapshot
        ob = OrderBookSnapshot(
            timestamp=100.0, symbol='BTC/USDT',
            bids=[(50000, 1.0)], asks=[(50001, 1.0)],
        )

        ch_tick = _MockChannel('BTC/USDT', [tick])
        ch_tick.channel_type = 'tick'

        ch_ob = _MockChannel('BTC/USDT', [ob])
        ch_ob.channel_type = 'orderbook'

        q = StreamingEventQueue(channels=[ch_tick, ch_ob], bars=[], preload_window=1000)

        e1 = q.pop()
        e2 = q.pop()

        # OrderBook has higher priority (lower number) than Tick
        assert e1.priority == EventPriority.ORDERBOOK
        assert e2.priority == EventPriority.TICK

    def test_peek(self):
        """Test that peek returns the next event without removing it."""
        ch = _MockChannel('BTC/USDT', self._make_ticks([100.0, 200.0]))
        q = StreamingEventQueue(channels=[ch], bars=[], preload_window=1000)

        e = q.peek()
        assert e is not None
        assert e.timestamp == 100.0
        # Peek should not remove the event
        e2 = q.peek()
        assert e2.timestamp == 100.0

    def test_heap_size(self):
        """Test that heap_size reports the number of events in the heap."""
        ch = _MockChannel('BTC/USDT', self._make_ticks([100.0, 200.0, 300.0]))
        q = StreamingEventQueue(channels=[ch], bars=[], preload_window=1000)
        assert q.heap_size == 3

    def test_total_events_popped(self):
        """Test that total_events_popped tracks the number of popped events."""
        ch = _MockChannel('BTC/USDT', self._make_ticks([100.0, 200.0]))
        q = StreamingEventQueue(channels=[ch], bars=[], preload_window=1000)

        q.pop()
        assert q.total_events_popped == 1
        q.pop()
        assert q.total_events_popped == 2

    def test_current_timestamp(self):
        """Test that current_timestamp updates after each pop operation."""
        ch = _MockChannel('BTC/USDT', self._make_ticks([100.0, 200.0]))
        q = StreamingEventQueue(channels=[ch], bars=[], preload_window=1000)
        assert q.current_timestamp == float('-inf')

        q.pop()
        assert q.current_timestamp == 100.0
        q.pop()
        assert q.current_timestamp == 200.0

    def test_bool(self):
        """Test that the queue evaluates to False when empty and True otherwise."""
        q_empty = StreamingEventQueue(channels=[], bars=[])
        assert not q_empty

        ch = _MockChannel('BTC/USDT', self._make_ticks([100.0]))
        q = StreamingEventQueue(channels=[ch], bars=[], preload_window=1000)
        assert q

    def test_repr(self):
        """Test that the queue representation contains the class name."""
        q = StreamingEventQueue(channels=[], bars=[])
        r = repr(q)
        assert 'StreamingEventQueue' in r

    def test_adaptive_window_initialization(self):
        """Test that adaptive window mode is initialized correctly."""
        q = StreamingEventQueue(
            channels=[], bars=[],
            preload_window=300.0,
            max_memory_mb=10,
            adaptive=True,
        )
        assert q._window == 300.0
        assert q._adaptive is True

    def test_bar_data_integration(self):
        """Test that bar events are integrated into the queue correctly."""
        from backtrader.events import BarEvent
        bars = [
            BarEvent(timestamp=100.0, symbol='BTC/USDT', open=50000, high=50100, low=49900, close=50050, volume=100),
            BarEvent(timestamp=200.0, symbol='BTC/USDT', open=50050, high=50150, low=49950, close=50100, volume=200),
        ]

        q = StreamingEventQueue(channels=[], bars=[bars], preload_window=1000)

        e1 = q.pop()
        assert e1.timestamp == 100.0
        assert e1.priority == EventPriority.BAR

        e2 = q.pop()
        assert e2.timestamp == 200.0
