"""Regression tests for committing dedup keys only after queue acceptance."""

import threading

import backtrader as bt

from .conftest import FakeTransport, json_response


def test_dropped_enqueue_leaves_key_available_for_concurrent_retry(notifier_env):
    """A full bounded queue must not consume the key for a later successful send."""
    worker_entered = threading.Event()
    release_worker = threading.Event()

    def handler(_request):
        worker_entered.set()
        release_worker.wait(timeout=5.0)
        return json_response({"ok": True})

    notifier, transport, _ = notifier_env(
        [{"channel": "ntfy", "topic": "dedup-test"}],
        transport=FakeTransport(handler=handler),
        queue_size=1,
        dedup_cooldown=60.0,
    )
    try:
        assert bt.send_message("hold worker").accepted is True
        assert worker_entered.wait(timeout=2.0)

        # The worker is occupied, so this message fills the only queue slot.
        assert bt.send_message("occupy queue").accepted is True
        dropped = bt.send_message("retryable", dedup_key="retry-after-drop")
        assert dropped.accepted is False
        assert dropped.dropped is True
        assert dropped.outcomes[0].error_category == "dropped"

        release_worker.set()
        assert bt.flush_notifications(timeout=5.0) is True

        # Start real concurrent producers after the queue has room. A failed
        # enqueue must leave the key unclaimed, while successful admission still
        # admits only one message for the same key.
        producer_count = 12
        start = threading.Barrier(producer_count)
        results = [None] * producer_count

        def retry(index):
            start.wait(timeout=3.0)
            results[index] = bt.send_message(
                "concurrent retry {0}".format(index), dedup_key="retry-after-drop"
            )

        threads = [threading.Thread(target=retry, args=(index,)) for index in range(producer_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5.0)

        assert all(not thread.is_alive() for thread in threads)
        assert all(result is not None for result in results)
        assert sum(result.accepted for result in results) == 1
        assert sum(
            result.outcomes[0].error_category == "deduped" for result in results
        ) == producer_count - 1

        assert bt.flush_notifications(timeout=5.0) is True
        stats = notifier.stats()["ntfy"]
        assert stats["sent"] == 3
        assert stats["dropped"] == 1
        assert stats["deduped"] == producer_count - 1
        assert len(transport.requests) == 3
    finally:
        release_worker.set()
