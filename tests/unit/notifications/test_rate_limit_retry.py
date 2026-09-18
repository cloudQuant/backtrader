"""AC32-13 / AC32-14: local rate limiting, retry policy and flush delivery."""

import time

import backtrader as bt
from backtrader.notifications import core as notify_core
from backtrader.notifications.channels import Attempt, ChannelSpec, Notification
from backtrader.notifications.transport import TransportError

from .conftest import FakeTransport, json_response


class _CountingDriver:
    """Driver that always succeeds and counts deliveries."""

    def __init__(self):
        """Prepare the delivery counter."""
        self.delivered = []

    def deliver(self, notification, timeout=None):
        """Record one delivered notification."""
        self.delivered.append(notification.text)
        return Attempt(True)


class _FailingDriver:
    """Driver that always fails with a fixed category."""

    def __init__(self, category):
        """Store the failure category."""
        self.category = category
        self.calls = 0

    def deliver(self, notification, timeout=None):
        """Record one call and fail."""
        self.calls += 1
        return Attempt(False, self.category, "boom")


def _runtime(spec, driver, **overrides):
    """Build a channel runtime for limiter/retry tests."""
    from backtrader.notifications.config import DEFAULT_OPTIONS

    options = dict(DEFAULT_OPTIONS)
    options.update(
        {
            "request_timeout": 0.5,
            "retry_backoff": 0.0,
            "rate_limit_scale": 1.0,
            "rate_limit_wait_timeout": 0.05,
            "max_retries": overrides.pop("max_retries", 2),
        }
    )
    options.update(overrides)
    return notify_core._ChannelRuntime("test", spec, driver, options)


def _spec(rate_limit):
    """Build a bare spec carrying only a rate limit."""
    return ChannelSpec(
        id="test",
        requires=(),
        optional=(),
        rate_limit=rate_limit,
        max_length=None,
        markdown=False,
        supports_at_all=False,
    )


def test_rate_limiter_sliding_window_uses_the_injected_clock():
    """The limiter waits exactly until the window frees up."""
    clock = {"now": 1000.0}
    limiter = notify_core._RateLimiter(2, None, 1.0, now=lambda: clock["now"])
    assert limiter.wait_time() == 0.0
    limiter.record()
    assert limiter.wait_time() == 0.0
    limiter.record()
    assert limiter.wait_time() == 60.0
    clock["now"] += 59.0
    assert round(limiter.wait_time(), 3) == 1.0
    clock["now"] += 1.0
    assert limiter.wait_time() == 0.0


def test_rate_limiter_honours_the_headroom_scale():
    """The configured scale reduces the effective threshold."""
    limiter = notify_core._RateLimiter(20, None, 0.75, now=lambda: 5.0)
    for _ in range(15):
        limiter.record()
    assert limiter.wait_time() > 0.0


def test_rate_limit_wait_beyond_timeout_fails_fast():
    """A wait longer than ``rate_limit_wait_timeout`` fails without sleeping."""
    driver = _CountingDriver()
    runtime = _runtime(_spec((1, None)), driver, rate_limit_wait_timeout=0.05)
    first = runtime.deliver(Notification(text="first"))
    assert first.ok is True

    started = time.monotonic()
    second = runtime.deliver(Notification(text="second"))
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, "must not actually wait out a 60s window"
    assert second.ok is False
    assert second.error_category == "rate_limit"
    assert second.attempts == 0
    assert runtime.stats_snapshot()["failed"] == 1


def test_rate_limit_within_timeout_waits_then_delivers():
    """A short wait is taken and the message is still delivered."""
    driver = _CountingDriver()
    runtime = _runtime(_spec((None, 1)), driver, rate_limit_wait_timeout=3.0)
    assert runtime.deliver(Notification(text="a")).ok is True
    started = time.monotonic()
    outcome = runtime.deliver(Notification(text="b"))
    elapsed = time.monotonic() - started
    assert outcome.ok is True
    assert elapsed >= 0.9, "expected roughly a one-second window wait"
    assert runtime.stats_snapshot()["rate_waited_ms"] > 0.0
    assert driver.delivered == ["a", "b"]


def test_5xx_is_retried_up_to_max_retries_then_fails():
    """Server errors are retried and finally classified as ``server``."""
    transport = FakeTransport(
        responses=[
            json_response({"errcode": 500}, status=500),
            json_response({"errcode": 500}, status=500),
            json_response({"errcode": 500}, status=500),
        ]
    )
    bt.configure_notifications(
        [{"channel": "ntfy", "topic": "t"}], transport=transport, retry_backoff=0.0, max_retries=2
    )
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.ok is False
    assert outcome.error_category == "server"
    assert outcome.attempts == 3
    assert len(transport.requests) == 3
    assert bt.notification_stats()["ntfy"]["retried"] == 2


def test_transient_5xx_then_success_is_reported_as_delivered():
    """A retry that succeeds yields a successful outcome with the attempt count."""
    transport = FakeTransport(
        responses=[
            json_response({"errcode": 500}, status=503),
            json_response({"errcode": 0}),
        ]
    )
    bt.configure_notifications(
        [{"channel": "ntfy", "topic": "t"}], transport=transport, retry_backoff=0.0
    )
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.ok is True
    assert outcome.attempts == 2


def test_network_error_is_retried_and_classified():
    """Transport failures are retryable and keep their kind as the category."""
    transport = FakeTransport(
        responses=[TransportError("timeout", "https://ntfy.sh/"), json_response({"errcode": 0})]
    )
    bt.configure_notifications(
        [{"channel": "ntfy", "topic": "t"}], transport=transport, retry_backoff=0.0
    )
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.ok is True
    assert outcome.attempts == 2


def test_non_retryable_categories_are_attempted_once():
    """Auth, permission, bad request and not_bound are never retried."""
    for category in ("auth", "permission", "bad_request", "not_bound"):
        driver = _FailingDriver(category)
        runtime = _runtime(_spec((None, None)), driver, max_retries=2)
        outcome = runtime.deliver(Notification(text="x"))
        assert outcome.error_category == category
        assert outcome.attempts == 1
        assert driver.calls == 1


def test_flush_delivers_everything_that_was_accepted(notifier_env):
    """After a successful flush the counters match the offered messages."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])
    for index in range(25):
        assert bt.send_message("m{0}".format(index)).accepted is True
    assert bt.flush_notifications(timeout=10.0) is True
    assert len(transport.requests) == 25
    stats = bt.notification_stats()["ntfy"]
    assert stats["sent"] == 25
    assert stats["failed"] == 0
    assert stats["dropped"] == 0


def test_dedup_windows_do_not_interfere_with_flush_counts(notifier_env):
    """A deduplicated message is counted separately, not as a failure."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}], dedup_cooldown=60.0)
    bt.send_message("same", dedup_key="k")
    bt.send_message("same", dedup_key="k")
    assert bt.flush_notifications(timeout=5.0) is True
    stats = bt.notification_stats()["ntfy"]
    assert stats["sent"] == 1
    assert stats["deduped"] == 1
    assert stats["failed"] == 0
    assert len(transport.requests) == 1


def test_dedup_requires_an_explicit_cooldown(notifier_env):
    """Without a cooldown the key is inert and nothing is suppressed."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])
    for _ in range(3):
        assert bt.send_message("same", dedup_key="k").accepted is True
    assert bt.flush_notifications(timeout=5.0) is True
    assert len(transport.requests) == 3


def test_dedup_window_expires(notifier_env):
    """After the cooldown elapses the key is delivered again."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}], dedup_cooldown=0.05)
    bt.send_message("first", dedup_key="k", wait=True)
    suppressed = bt.send_message("second", dedup_key="k", wait=True)
    assert suppressed.outcomes[0].error_category == "deduped"
    time.sleep(0.06)
    delivered = bt.send_message("third", dedup_key="k", wait=True)
    assert delivered.outcomes[0].ok is True
    assert len(transport.requests) == 2


def test_dedup_is_per_channel_instance(notifier_env):
    """The same key does not suppress a different channel."""
    _, transport, _ = notifier_env(
        [
            {"channel": "ntfy", "topic": "one"},
            {"channel": "ntfy", "topic": "two"},
        ],
        dedup_cooldown=60.0,
    )
    result = bt.send_message("hello", dedup_key="k", wait=True)
    assert len(transport.requests) == 2
    assert all(outcome.ok for outcome in result.outcomes)


def test_deduped_message_is_not_a_failure(notifier_env):
    """Suppressed sends report ``deduped`` and leave ``failed`` at zero."""
    notifier_env([{"channel": "ntfy", "topic": "t"}], dedup_cooldown=60.0)
    bt.send_message("a", dedup_key="k", wait=True)
    bt.send_message("b", dedup_key="k", wait=True)
    stats = bt.notification_stats()["ntfy"]
    assert stats["deduped"] == 1
    assert stats["failed"] == 0
    assert stats["sent"] == 1
