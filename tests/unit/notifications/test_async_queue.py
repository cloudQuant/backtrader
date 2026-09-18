"""AC32-12: async queue semantics and cross-channel isolation.

The per-channel worker model exists so that one throttled channel cannot delay
another. These tests pin that behaviour down: enqueue is non-blocking, a blocking
channel does not hold up a fast one, and overflow only affects the full channel.
"""

import threading
import time

import backtrader as bt
from backtrader.notifications import core as notify_core
from backtrader.notifications.channels import Attempt, ChannelSpec, Notification

from .conftest import FakeTransport, json_response, wait_until


class _RecordingDriver:
    """Driver that records deliveries and optionally blocks them."""

    def __init__(self, gate=None):
        """Store the optional gate and prepare a delivery log.

        Args:
            gate: Optional ``threading.Event`` waited on before each delivery.
        """
        self.gate = gate
        self.delivered = []

    def deliver(self, notification, timeout=None):
        """Record the notification, honouring the gate."""
        if self.gate is not None:
            self.gate.wait(5.0)
        self.delivered.append(notification.text)
        return Attempt(True)


def _runtime(name="test", rate_limit=(None, None), driver=None, **overrides):
    """Build a channel runtime with test-friendly options."""
    from backtrader.notifications.config import DEFAULT_OPTIONS

    options = dict(DEFAULT_OPTIONS)
    options.update(
        {
            "queue_size": overrides.pop("queue_size", 4),
            "request_timeout": 0.5,
            "retry_backoff": 0.0,
            "rate_limit_scale": 1.0,
            "rate_limit_wait_timeout": 0.05,
        }
    )
    options.update(overrides)
    spec = ChannelSpec(
        id=name,
        requires=(),
        optional=(),
        rate_limit=rate_limit,
        max_length=None,
        markdown=False,
        supports_at_all=False,
    )
    return notify_core._ChannelRuntime(name, spec, driver or _RecordingDriver(), options)


def _queued_texts(runtime):
    """Return the texts currently sitting in a runtime's queue."""
    return [item.text for item in list(runtime.queue.queue) if item is not notify_core._SENTINEL]


def test_enqueue_never_blocks_the_caller():
    """A blocked worker must not slow down the enqueue path."""
    gate = threading.Event()
    runtime = _runtime(driver=_RecordingDriver(gate=gate))
    runtime.start()
    try:
        started = time.monotonic()
        for index in range(4):
            outcome = runtime.enqueue(Notification(text="m{0}".format(index)))
            assert outcome.ok is True
        elapsed = time.monotonic() - started
    finally:
        gate.set()
        runtime.stop()
    assert elapsed < 0.2, "enqueue took {0:.3f}s".format(elapsed)


def test_overflow_drop_newest_keeps_earliest_and_counts():
    """``drop_newest`` rejects the newest message once the queue is full."""
    runtime = _runtime(queue_size=2, overflow="drop_newest")
    assert runtime.enqueue(Notification(text="m0")).ok is True
    assert runtime.enqueue(Notification(text="m1")).ok is True
    outcome = runtime.enqueue(Notification(text="m2"))
    assert outcome.ok is False
    assert outcome.error_category == "dropped"
    assert _queued_texts(runtime) == ["m0", "m1"]
    assert runtime.stats_snapshot()["dropped"] == 1


def test_overflow_drop_oldest_evicts_the_head():
    """``drop_oldest`` makes room by discarding the oldest queued message."""
    runtime = _runtime(queue_size=2, overflow="drop_oldest")
    runtime.enqueue(Notification(text="m0"))
    runtime.enqueue(Notification(text="m1"))
    outcome = runtime.enqueue(Notification(text="m2"))
    assert outcome.ok is True
    assert _queued_texts(runtime) == ["m1", "m2"]
    assert runtime.stats_snapshot()["dropped"] == 1


def test_overflow_is_per_channel(notifier_env):
    """A blocked channel's overflow must not cost another channel a message."""
    gate = threading.Event()

    def handler(request):
        if "dingtalk" in request.url:
            gate.wait(5.0)
            return json_response({"errcode": 0})
        return json_response({"ok": True})

    notifier_env(
        [
            {"channel": "dingtalk", "access_token": "tok"},
            {"channel": "telegram", "bot_token": "b", "chat_id": "1"},
        ],
        transport=FakeTransport(handler=handler),
        queue_size=2,
    )
    try:
        for index in range(6):
            bt.send_message("dingtalk only {0}".format(index), channels=["dingtalk"])
        assert bt.notification_stats()["dingtalk"]["dropped"] >= 1

        accepted = bt.send_message("telegram only", channels=["telegram"])
        assert accepted.accepted is True, "telegram must still accept a message"

        gate.set()
        assert bt.flush_notifications(timeout=5.0) is True
        stats = bt.notification_stats()
        assert stats["telegram"]["dropped"] == 0
        assert stats["telegram"]["sent"] == 1
    finally:
        gate.set()
        bt.flush_notifications(timeout=5.0)


def test_blocked_channel_does_not_hold_up_another(notifier_env):
    """Channel A blocked mid-request must not delay channel B."""
    order = []
    gate = threading.Event()

    def handler(request):
        if "dingtalk" in request.url:
            gate.wait(5.0)
            order.append("dingtalk")
            return json_response({"errcode": 0})
        order.append("telegram")
        return json_response({"ok": True})

    notifier_env(
        [
            {"channel": "dingtalk", "access_token": "tok"},
            {"channel": "telegram", "bot_token": "b", "chat_id": "1"},
        ],
        transport=FakeTransport(handler=handler),
    )
    started = time.monotonic()
    result = bt.send_message("both channels")
    enqueue_elapsed = time.monotonic() - started

    assert result.accepted is True
    assert enqueue_elapsed < 0.2, "enqueue must not wait for a blocked channel"
    assert wait_until(lambda: "telegram" in order, timeout=3.0)
    assert "dingtalk" not in order, "telegram must complete while dingtalk is blocked"

    gate.set()
    assert bt.flush_notifications(timeout=5.0) is True
    assert order == ["telegram", "dingtalk"]


def test_flush_reports_timeout_then_succeeds_after_release(notifier_env):
    """``flush`` returns False while work is blocked and True once released."""
    gate = threading.Event()

    def handler(request):
        gate.wait(5.0)
        return json_response({"errcode": 0})

    notifier_env([{"channel": "ntfy", "topic": "t"}], transport=FakeTransport(handler=handler))
    bt.send_message("blocked")
    assert bt.flush_notifications(timeout=0.05) is False
    gate.set()
    assert bt.flush_notifications(timeout=5.0) is True
    assert bt.notification_stats()["ntfy"]["sent"] == 1


def test_sync_mode_returns_delivery_outcomes(notifier_env):
    """``wait=True`` returns real per-channel delivery results."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])
    result = bt.send_message("sync body", wait=True)
    assert result.mode == "sync"
    assert result.accepted is True
    assert result.outcomes[0].attempts == 1
    assert len(transport.requests) == 1

    queued = bt.send_message("async body")
    assert queued.mode == "async"
    assert len(transport.requests) == 1, "async send must not call the transport yet"
    assert bt.flush_notifications(5.0) is True
    assert len(transport.requests) == 2
