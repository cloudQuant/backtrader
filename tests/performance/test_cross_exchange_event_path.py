from decimal import Decimal
import gc
from importlib import import_module
import time

from bt_api_py import CrossVenueLeg as InstrumentRule

event_strategy = import_module("examples.012_2_event_driven_cross_exchange.strategy")
D = Decimal
EVENT_COUNT = 100_000
P99_LIMIT_NS = 5_000_000


def test_event_engine_100k_update_and_decision_diagnostic_p99():
    rules = {
        venue: InstrumentRule(D("1"), D(".001"), D(".001"), D("0"), D(".1"), D("0"))
        for venue in event_strategy.VENUE_SYMBOLS
    }
    risk = event_strategy.EventDrivenRisk(
        depth_fraction=D("1"),
        exit_reserve_bps=D("0"),
        latency_reserve_bps=D("0"),
        failure_reserve_bps=D("0"),
        model_buffer_bps=D("0"),
    )
    engine = event_strategy.EventArbitrageEngine(rules, risk)
    latencies = [0] * EVENT_COUNT
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for index in range(EVENT_COUNT):
            observed_at = D(index) / D("1000000")
            sequence = index + 1
            books = (
                event_strategy.EventBook(
                    "okx",
                    ((D("100"), D(".1")),),
                    ((D("100.1"), D(".1")),),
                    observed_at,
                    observed_at,
                    sequence,
                    continuity_status="continuous",
                ),
                event_strategy.EventBook(
                    "binance",
                    ((D("100"), D(".1")),),
                    ((D("100.1"), D(".1")),),
                    observed_at,
                    observed_at,
                    sequence,
                    continuity_status="continuous",
                ),
            )
            started = time.perf_counter_ns()
            engine.update_book(books[0])
            engine.update_book(books[1])
            decision = engine.evaluate(observed_at)
            latencies[index] = time.perf_counter_ns() - started
    finally:
        if was_enabled:
            gc.enable()

    latencies.sort()
    p50 = latencies[int(EVENT_COUNT * 0.50)]
    p95 = latencies[int(EVENT_COUNT * 0.95)]
    p99 = latencies[int(EVENT_COUNT * 0.99)]
    assert decision is None
    assert engine.reject_reasons["net_edge"] == EVENT_COUNT
    assert p50 <= p95 <= p99
    assert p99 <= P99_LIMIT_NS, {
        "events": EVENT_COUNT,
        "p50_ms": p50 / 1_000_000,
        "p95_ms": p95 / 1_000_000,
        "p99_ms": p99 / 1_000_000,
        "scope": "pure_event_engine_update_and_decision_no_order_or_network",
    }
