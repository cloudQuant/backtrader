"""Local latency gate for the BtApiStore command ingress path."""

import time

from backtrader.stores.btapistore import BtApiStore

_SAMPLE_COUNT = 100_000
_P99_LIMIT_NS = 5_000_000


def test_100k_no_network_command_enqueue_p99_below_five_ms():
    """A saturated-risk-free local queue must not wait on exchange I/O."""
    store = BtApiStore(
        provider="btapi",
        api=object(),
        config={
            "exchange_kwargs": {"OKX___SWAP": {"environment": "demo"}},
            "symbol_routes": {"BTC-USDT-SWAP": "OKX___SWAP"},
            "command_queue_size": _SAMPLE_COUNT + 1,
            "command_reserved_capacity": 0,
        },
    )

    durations_ns = []
    for index in range(_SAMPLE_COUNT):
        started_ns = time.perf_counter_ns()
        receipt = store._enqueue_sdk_command(  # local queue primitive; deliberately no SDK call
            {"operation": "reconcile", "sample": index},
            priority_name="reconcile",
            emit_event=False,
        )
        durations_ns.append(time.perf_counter_ns() - started_ns)
        assert receipt["queued"] is True

    durations_ns.sort()
    p99_ns = durations_ns[int(_SAMPLE_COUNT * 0.99) - 1]
    health = store.get_command_health()
    assert health["enqueued"] == _SAMPLE_COUNT
    assert health["queue_depth"] == _SAMPLE_COUNT
    assert p99_ns <= _P99_LIMIT_NS, f"enqueue p99={p99_ns / 1_000_000:.3f} ms"
