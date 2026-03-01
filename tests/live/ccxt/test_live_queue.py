"""Unit tests for backtrader/channels/live_queue.py - LiveEventQueue."""

import threading
import time
import pytest
from backtrader.channels.live_queue import LiveEventQueue
from backtrader.channel import EventPriority
from backtrader.events import TickEvent


class TestLiveEventQueue:
    """Test suite for LiveEventQueue functionality.

    Tests cover basic operations, priority ordering, timestamp ordering,
    queue state management, thread safety, and drop policies.
    """

    def test_basic_put_get(self):
        """Test basic put and get operations.

        Verifies that an event can be successfully added to the queue
        and retrieved with its metadata intact.
        """
        q = LiveEventQueue()
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        q.put(tick, priority=EventPriority.TICK, channel_type='tick', channel_name='BTC/USDT')

        event = q.get(timeout=0)
        assert event is not None
        assert event.data is tick
        assert event.timestamp == 100.0

    def test_priority_ordering(self):
        """Test event ordering by priority.

        Verifies that events with higher priority (lower numeric value)
        are retrieved before events with lower priority.
        """
        q = LiveEventQueue()
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        from backtrader.events import FundingEvent
        fund = FundingEvent(timestamp=100.0, symbol='X', rate=0.0001, mark_price=50000)

        q.put(tick, priority=EventPriority.TICK, timestamp=100.0)
        q.put(fund, priority=EventPriority.FUNDING, timestamp=100.0)

        e1 = q.get(timeout=0)
        e2 = q.get(timeout=0)
        assert e1.priority == EventPriority.FUNDING
        assert e2.priority == EventPriority.TICK

    def test_timestamp_ordering(self):
        """Test event ordering by timestamp.

        Verifies that events with earlier timestamps are retrieved
        before events with later timestamps when priorities are equal.
        """
        q = LiveEventQueue()
        t1 = TickEvent(timestamp=200.0, symbol='X', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=100.0, symbol='X', price=50001, volume=1.0, direction='sell')

        q.put(t1, timestamp=200.0)
        q.put(t2, timestamp=100.0)

        e1 = q.get(timeout=0)
        e2 = q.get(timeout=0)
        assert e1.timestamp == 100.0
        assert e2.timestamp == 200.0

    def test_empty_get_returns_none(self):
        """Test get operation on empty queue.

        Verifies that attempting to get an event from an empty queue
        returns None immediately when timeout is 0.
        """
        q = LiveEventQueue()
        assert q.get(timeout=0) is None

    def test_get_timeout(self):
        """Test get operation with timeout.

        Verifies that get blocks for the specified timeout duration
        when the queue is empty.
        """
        q = LiveEventQueue()
        start = time.monotonic()
        result = q.get(timeout=0.1)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed >= 0.09

    def test_size_and_empty(self):
        """Test queue size and empty state queries.

        Verifies that size, empty status, and boolean conversion
        accurately reflect the queue state.
        """
        q = LiveEventQueue()
        assert q.empty is True
        assert q.size == 0
        assert len(q) == 0
        assert not q

        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        q.put(tick)
        assert q.empty is False
        assert q.size == 1
        assert len(q) == 1
        assert q

    def test_peek(self):
        """Test peek operation.

        Verifies that peek returns the next event without removing it
        from the queue.
        """
        q = LiveEventQueue()
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        q.put(tick)

        event = q.peek()
        assert event is not None
        assert event.timestamp == 100.0
        # Peek doesn't remove
        assert q.size == 1

    def test_peek_empty(self):
        """Test peek operation on empty queue.

        Verifies that peeking at an empty queue returns None.
        """
        q = LiveEventQueue()
        assert q.peek() is None

    def test_close(self):
        """Test queue close operation.

        Verifies that closing the queue prevents further put operations
        and updates the closed state.
        """
        q = LiveEventQueue()
        assert q.closed is False
        q.close()
        assert q.closed is True

        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        assert q.put(tick) is False

    def test_close_unblocks_get(self):
        """Test that closing unblocks waiting get operations.

        Verifies that a thread blocked in get() returns immediately
        when the queue is closed.
        """
        q = LiveEventQueue()

        result = [None]

        def consumer():
            result[0] = q.get(timeout=5.0)

        t = threading.Thread(target=consumer)
        t.start()
        time.sleep(0.05)
        q.close()
        t.join(timeout=1.0)
        assert result[0] is None

    def test_maxsize_drop_oldest(self):
        """Test maxsize with drop_oldest policy.

        Verifies that when the queue reaches maxsize, the oldest events
        are dropped to make room for new ones.
        """
        q = LiveEventQueue(maxsize=2, drop_policy='drop_oldest')
        for i in range(5):
            tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000, volume=1.0, direction='buy')
            q.put(tick, timestamp=100.0 + i)

        assert q.size == 2
        stats = q.stats
        assert stats['total_dropped'] == 3

    def test_maxsize_drop_newest(self):
        """Test maxsize with drop_newest policy.

        Verifies that when the queue reaches maxsize, new events are
        rejected and the oldest events are retained.
        """
        q = LiveEventQueue(maxsize=2, drop_policy='drop_newest')
        results = []
        for i in range(5):
            tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000, volume=1.0, direction='buy')
            results.append(q.put(tick, timestamp=100.0 + i))

        assert results[:2] == [True, True]
        assert results[2:] == [False, False, False]
        assert q.size == 2

    def test_stats(self):
        """Test queue statistics tracking.

        Verifies that the queue accurately tracks statistics such as
        total puts, gets, dropped events, and current size.
        """
        q = LiveEventQueue()
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        q.put(tick)
        q.get(timeout=0)

        stats = q.stats
        assert stats['total_put'] == 1
        assert stats['total_get'] == 1
        assert stats['total_dropped'] == 0
        assert stats['current_size'] == 0
        assert stats['closed'] is False

    def test_threaded_producer_consumer(self):
        """Test concurrent producer and consumer threads.

        Verifies that the queue operates correctly under concurrent
        access from multiple threads producing and consuming events.
        """
        q = LiveEventQueue()
        results = []
        N = 100

        def producer():
            for i in range(N):
                tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000, volume=1.0, direction='buy')
                q.put(tick, timestamp=100.0 + i)
            time.sleep(0.05)
            q.close()

        def consumer():
            while True:
                event = q.get(timeout=1.0)
                if event is None:
                    break
                results.append(event)

        t_prod = threading.Thread(target=producer)
        t_cons = threading.Thread(target=consumer)
        t_prod.start()
        t_cons.start()
        t_prod.join(timeout=5.0)
        t_cons.join(timeout=5.0)

        assert len(results) == N
        # Verify ordering
        timestamps = [e.timestamp for e in results]
        assert timestamps == sorted(timestamps)

    def test_repr(self):
        """Test string representation of the queue.

        Verifies that repr() returns a string containing the class name.
        """
        q = LiveEventQueue()
        r = repr(q)
        assert 'LiveEventQueue' in r
