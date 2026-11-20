"""Post-enqueue bookkeeping failures must preserve notification admission."""

import logging
import threading
import time as real_time
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.notifications import core as notify_core
from .conftest import FakeTransport, json_response


class _RaisingHandler(logging.Handler):
    """A real logging handler that simulates a host handler failure."""

    def emit(self, _record):
        raise RuntimeError("controlled handler failure")


class _BlockingOverflowHandler(logging.Handler):
    """Pause the producer while it emits the controlled overflow warning."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def emit(self, record):
        if "notification queue full" in record.getMessage():
            self.entered.set()
            self.release.wait(timeout=5.0)


class _ReenteringOverflowHandler(logging.Handler):
    """Issue one same-key send from inside the overflow log callback."""

    def __init__(self, dedup_key):
        super().__init__()
        self.dedup_key = dedup_key
        self.result = None
        self.called = False

    def emit(self, record):
        if "notification queue full" not in record.getMessage() or self.called:
            return
        self.called = True
        self.result = bt.send_message("reentrant duplicate", dedup_key=self.dedup_key)


def _blocked_transport():
    """Return a transport whose first request holds the worker in flight."""
    entered = threading.Event()
    release = threading.Event()

    def handler(_request):
        entered.set()
        release.wait(timeout=5.0)
        return json_response({"ok": True})

    return FakeTransport(handler=handler), entered, release


def _unthrottled_warning(logger, _key, message, *args, **kwargs):
    """Make each controlled overflow exercise reach its logging handler."""
    logger.warning(message, *args, **kwargs)


def test_drop_oldest_auxiliary_failures_keep_accepted_key(notifier_env, capsys):
    """Drop stats and warning failures after replacement enqueue are nonfatal."""
    transport, entered, release = _blocked_transport()
    notifier, transport, _ = notifier_env(
        [{"channel": "ntfy", "topic": "dedup-test"}],
        transport=transport,
        queue_size=1,
        overflow="drop_oldest",
        dedup_cooldown=60.0,
    )
    logger = notify_core.logger
    handler = _RaisingHandler()
    old_level = logger.level
    runtime = notifier._runtimes["ntfy"]
    count = runtime.count

    def fail_drop_count(key, amount=1):
        if key == "dropped":
            raise RuntimeError("controlled drop counter failure")
        count(key, amount)

    try:
        assert bt.send_message("hold worker").accepted is True
        assert entered.wait(timeout=2.0)
        assert bt.send_message("message to evict").accepted is True

        runtime.count = fail_drop_count
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        accepted = bt.send_message("accepted replacement", dedup_key="drop-oldest-key")
        assert accepted.accepted is True

        duplicate = bt.send_message("duplicate", dedup_key="drop-oldest-key")
        assert duplicate.accepted is False
        assert duplicate.outcomes[0].error_category == "deduped"

        release.set()
        assert bt.flush_notifications(timeout=5.0) is True
        stats = notifier.stats()["ntfy"]
        assert stats["sent"] == 2
        assert stats["dropped"] == 0
        assert stats["deduped"] == 1
        assert len(transport.requests) == 2
        diagnostic = capsys.readouterr().err
        assert "dropped_count" in diagnostic
        assert "dropped_warning" in diagnostic
    finally:
        release.set()
        runtime.count = count
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_dedup_clock_failure_after_enqueue_keeps_key(notifier_env, monkeypatch, capsys):
    """A failed post-admission clock read falls back without reopening the key."""
    transport, entered, release = _blocked_transport()
    notifier, transport, _ = notifier_env(
        [{"channel": "ntfy", "topic": "dedup-test"}],
        transport=transport,
        queue_size=2,
        dedup_cooldown=60.0,
    )
    assert bt.send_message("hold worker").accepted is True
    assert entered.wait(timeout=2.0)

    main_thread = threading.current_thread()
    clock_calls = 0

    def monotonic():
        nonlocal clock_calls
        if threading.current_thread() is main_thread:
            clock_calls += 1
            if clock_calls == 2:
                raise RuntimeError("controlled monotonic failure")
        return real_time.monotonic()

    monkeypatch.setattr(
        notify_core,
        "time",
        SimpleNamespace(monotonic=monotonic, sleep=real_time.sleep),
    )
    try:
        accepted = bt.send_message("accepted before clock failure", dedup_key="clock-key")
        assert accepted.accepted is True

        duplicate = bt.send_message("duplicate", dedup_key="clock-key")
        assert duplicate.accepted is False
        assert duplicate.outcomes[0].error_category == "deduped"
        diagnostic = capsys.readouterr().err
        assert "dedup_timestamp_commit" in diagnostic
        assert "error_type=RuntimeError" in diagnostic
        assert "controlled monotonic failure" not in diagnostic

        release.set()
        assert bt.flush_notifications(timeout=5.0) is True
        stats = notifier.stats()["ntfy"]
        assert stats["sent"] == 2
        assert stats["deduped"] == 1
        assert len(transport.requests) == 2
    finally:
        release.set()


def test_unrelated_enqueue_exception_is_not_swallowed_or_committed(notifier_env):
    """An exception before queue acceptance propagates and leaves the key retryable."""
    notifier, transport, _ = notifier_env(
        [{"channel": "ntfy", "topic": "dedup-test"}],
        dedup_cooldown=60.0,
    )
    runtime = notifier._runtimes["ntfy"]
    enqueue = runtime.enqueue

    def fail_before_enqueue(_notification, deferred=None):
        raise RuntimeError("unrelated queue failure")

    runtime.enqueue = fail_before_enqueue
    try:
        with pytest.raises(RuntimeError, match="unrelated queue failure"):
            bt.send_message("will retry", dedup_key="unrelated-error-key")
    finally:
        runtime.enqueue = enqueue

    retried = bt.send_message("will retry", dedup_key="unrelated-error-key")
    assert retried.accepted is True
    assert bt.flush_notifications(timeout=5.0) is True
    assert len(transport.requests) == 1


def test_blocked_overflow_logger_does_not_block_another_channel(notifier_env, monkeypatch):
    """A slow channel logger must not hold the notifier-wide dedup lock."""
    worker_entered = threading.Event()
    release_worker = threading.Event()

    def transport_handler(request):
        if "ntfy.sh" in request.url:
            worker_entered.set()
            release_worker.wait(timeout=5.0)
        return json_response({"ok": True})

    notifier, transport, _ = notifier_env(
        [
            {"channel": "ntfy", "topic": "blocked"},
            {"channel": "telegram", "bot_token": "fake", "chat_id": "1"},
        ],
        transport=FakeTransport(handler=transport_handler),
        queue_size=1,
        overflow="drop_oldest",
        dedup_cooldown=60.0,
    )
    logger = notify_core.logger
    handler = _BlockingOverflowHandler()
    old_level = logger.level
    monkeypatch.setattr(notify_core, "throttled_warning", _unthrottled_warning)
    first_result = []
    second_result = []
    second_done = threading.Event()

    def enqueue_blocked_channel():
        first_result.append(
            bt.send_message("replacement", channels=["ntfy"], dedup_key="ntfy-key")
        )

    def enqueue_other_channel():
        second_result.append(
            bt.send_message("independent", channels=["telegram"], dedup_key="telegram-key")
        )
        second_done.set()

    first_thread = threading.Thread(target=enqueue_blocked_channel)
    second_thread = threading.Thread(target=enqueue_other_channel)
    try:
        assert bt.send_message("hold ntfy worker", channels=["ntfy"]).accepted is True
        assert worker_entered.wait(timeout=2.0)
        assert bt.send_message("ntfy queue slot", channels=["ntfy"]).accepted is True

        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        first_thread.start()
        assert handler.entered.wait(timeout=2.0)

        second_thread.start()
        assert second_done.wait(timeout=1.0), "other channel waited on blocked overflow logging"
        assert second_result[0].accepted is True
        assert first_thread.is_alive(), "the controlled overflow log should still be blocked"
    finally:
        handler.release.set()
        release_worker.set()
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        if first_thread.ident is not None:
            first_thread.join(timeout=3.0)
        if second_thread.ident is not None:
            second_thread.join(timeout=3.0)

    assert first_result[0].accepted is True
    assert bt.flush_notifications(timeout=5.0) is True
    assert notifier.stats()["ntfy"]["sent"] == 2
    assert notifier.stats()["telegram"]["sent"] == 1
    assert len(transport.requests) == 3


def test_overflow_log_reentry_cannot_enqueue_the_same_key_twice(notifier_env, monkeypatch):
    """A synchronous same-key send from a logger callback sees committed dedup."""
    transport, entered, release_worker = _blocked_transport()
    notifier, transport, _ = notifier_env(
        [{"channel": "ntfy", "topic": "dedup-test"}],
        transport=transport,
        queue_size=1,
        overflow="drop_oldest",
        dedup_cooldown=60.0,
    )
    logger = notify_core.logger
    handler = _ReenteringOverflowHandler("reentrant-key")
    old_level = logger.level
    monkeypatch.setattr(notify_core, "throttled_warning", _unthrottled_warning)
    try:
        assert bt.send_message("hold worker").accepted is True
        assert entered.wait(timeout=2.0)
        assert bt.send_message("message to evict").accepted is True

        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        outer = bt.send_message("outer accepted", dedup_key="reentrant-key")
        assert outer.accepted is True
        assert handler.called is True
        assert handler.result is not None
        assert handler.result.accepted is False
        assert handler.result.outcomes[0].error_category == "deduped"

        release_worker.set()
        assert bt.flush_notifications(timeout=5.0) is True
        stats = notifier.stats()["ntfy"]
        assert stats["sent"] == 2
        assert stats["dropped"] == 1
        assert stats["deduped"] == 1
        assert len(transport.requests) == 2
    finally:
        release_worker.set()
        logger.removeHandler(handler)
        logger.setLevel(old_level)
