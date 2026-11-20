"""A close must win over a producer which has not yet acquired the lock."""

import threading

from backtrader.channels.live_queue import LiveEventQueue


def test_producer_cannot_enqueue_after_close():
    timestamp_read = threading.Event()
    resume = threading.Event()
    results = []
    queue = LiveEventQueue()

    class DelayedEvent:
        @property
        def timestamp(self):
            timestamp_read.set()
            if not resume.wait(5):
                raise RuntimeError("test producer timed out")
            return 1.0

    thread = threading.Thread(target=lambda: results.append(queue.put(DelayedEvent())))
    thread.start()
    try:
        assert timestamp_read.wait(5)
        queue.close()
    finally:
        resume.set()
        thread.join(5)

    assert not thread.is_alive()
    assert results == [False]
    assert queue.get(timeout=0) is None
    assert queue.stats == {
        "total_put": 0,
        "total_get": 0,
        "total_dropped": 0,
        "current_size": 0,
        "closed": True,
    }


def test_close_preserves_events_accepted_before_close():
    queue = LiveEventQueue()
    assert queue.put("event", timestamp=1.0)
    queue.close()
    assert queue.get(timeout=0).data == "event"
    assert queue.get(timeout=0) is None
    assert not queue.put("late", timestamp=2.0)
