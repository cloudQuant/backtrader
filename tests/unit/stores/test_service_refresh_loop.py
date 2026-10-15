"""Offline behavior for the managed-order refresh schedule."""

from __future__ import annotations

import pytest

from backtrader.stores.service_refresh_loop import (
    ManagedOrderRefreshLoop,
    RefreshLoopError,
)
from backtrader.stores.service_execution_adapter import ServiceExecutionReadError


class _Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Broker:
    def __init__(self, results=None, error: BaseException | None = None) -> None:
        self.results = list(results or [])
        self.error = error
        self.calls: list[int] = []

    def refresh_managed_orders(self, *, limit: int = 32):
        self.calls.append(limit)
        if self.error is not None:
            raise self.error
        return self.results.pop(0) if self.results else ()


class _StubError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _loop(broker, clock, **overrides):
    arguments = {
        "interval_seconds": 1.0,
        "max_interval_seconds": 8.0,
        "backoff_factor": 2.0,
        "limit": 4,
        "monotonic_clock": clock,
    }
    arguments.update(overrides)
    return ManagedOrderRefreshLoop(broker, **arguments)


def test_the_first_pass_is_due_and_later_passes_wait_for_the_interval() -> None:
    clock = _Clock()
    broker = _Broker(results=[(1, 2)])
    loop = _loop(broker, clock)

    assert loop.due() is True
    assert loop.run_once() == (1, 2)
    assert broker.calls == [4]
    assert loop.due() is False
    assert loop.next_delay() == pytest.approx(1.0)

    clock.advance(1.0)
    assert loop.due() is True
    assert loop.run_once() == ()
    assert broker.calls == [4, 4]


def test_a_pass_that_is_not_due_does_not_call_the_broker() -> None:
    clock = _Clock()
    broker = _Broker(results=[(1,)])
    loop = _loop(broker, clock)

    loop.run_once()
    assert loop.run_once() == ()
    assert broker.calls == [4]


def test_a_failing_pass_backs_off_without_breaking_the_caller() -> None:
    clock = _Clock()
    broker = _Broker(error=_StubError("SERVICE_READ_FAILED"))
    loop = _loop(broker, clock)

    assert loop.run_once() == ()
    assert loop.stats.failures == 1
    assert loop.stats.last_error_code == "SERVICE_READ_FAILED"
    assert loop.stats.current_interval_seconds == pytest.approx(2.0)
    assert loop.next_delay() == pytest.approx(2.0)

    clock.advance(2.0)
    assert loop.run_once() == ()
    assert loop.stats.current_interval_seconds == pytest.approx(4.0)

    clock.advance(4.0)
    assert loop.run_once() == ()
    assert loop.stats.current_interval_seconds == pytest.approx(8.0)

    # The backoff is capped, so a permanently unreadable service still polls.
    clock.advance(8.0)
    assert loop.run_once() == ()
    assert loop.stats.current_interval_seconds == pytest.approx(8.0)
    assert len(broker.calls) == 4


def test_a_partial_failed_pass_counts_the_refs_already_applied() -> None:
    clock = _Clock()
    broker = _Broker(error=ServiceExecutionReadError("SCOPE_DENIED", applied_refs=(7, 8)))
    loop = _loop(broker, clock)

    assert loop.run_once() == ()
    assert loop.stats.failures == 1
    assert loop.stats.last_error_code == "SCOPE_DENIED"
    assert loop.stats.applied == 2
    assert loop.stats.last_applied_refs == (7, 8)
    assert loop.stats.current_interval_seconds == pytest.approx(2.0)


def test_a_recovered_pass_resets_the_backoff_and_counts_the_applied_refs() -> None:
    clock = _Clock()
    broker = _Broker(error=_StubError("SERVICE_READ_FAILED"))
    loop = _loop(broker, clock)

    loop.run_once()
    clock.advance(2.0)
    assert loop.stats.current_interval_seconds == pytest.approx(2.0)

    broker.error = None
    broker.results = [(7, 8, 9)]
    assert loop.run_once() == (7, 8, 9)
    assert loop.stats.current_interval_seconds == pytest.approx(1.0)
    assert loop.stats.last_error_code is None
    assert loop.stats.applied == 3
    assert loop.stats.last_applied_refs == (7, 8, 9)
    assert loop.stats.attempts == 2


def test_a_pass_without_a_result_is_still_a_successful_attempt() -> None:
    clock = _Clock()
    broker = _Broker(results=[None])
    loop = _loop(broker, clock)

    assert loop.run_once() == ()
    assert loop.stats.attempts == 1
    assert loop.stats.failures == 0
    assert loop.stats.current_interval_seconds == pytest.approx(1.0)


def test_an_unexpected_error_is_reported_by_its_type() -> None:
    clock = _Clock()
    broker = _Broker(error=RuntimeError("synthetic transport failure"))
    loop = _loop(broker, clock)

    loop.run_once()

    assert loop.stats.last_error_code == "RuntimeError"


def test_configuration_is_validated_before_any_pass() -> None:
    clock = _Clock()
    with pytest.raises(RefreshLoopError, match="BROKER_CANNOT_REFRESH"):
        ManagedOrderRefreshLoop(object(), monotonic_clock=clock)
    with pytest.raises(RefreshLoopError, match="INVALID_LIMIT"):
        _loop(_Broker(), clock, limit=0)
    with pytest.raises(RefreshLoopError, match="INVALID_INTERVAL"):
        _loop(_Broker(), clock, interval_seconds=0)
    for interval in (True, float("nan"), float("inf"), 10**400):
        with pytest.raises(RefreshLoopError, match="INVALID_INTERVAL"):
            _loop(_Broker(), clock, interval_seconds=interval)
    with pytest.raises(RefreshLoopError, match="INVALID_INTERVAL"):
        _loop(_Broker(), clock, interval_seconds=4.0, max_interval_seconds=2.0)
    for maximum in (False, float("nan"), float("inf"), 10**400):
        with pytest.raises(RefreshLoopError, match="INVALID_INTERVAL"):
            _loop(_Broker(), clock, max_interval_seconds=maximum)
    with pytest.raises(RefreshLoopError, match="INVALID_BACKOFF"):
        _loop(_Broker(), clock, backoff_factor=0.5)
    for backoff in (True, float("nan"), float("inf"), 10**400):
        with pytest.raises(RefreshLoopError, match="INVALID_BACKOFF"):
            _loop(_Broker(), clock, backoff_factor=backoff)
    with pytest.raises(RefreshLoopError, match="INVALID_CLOCK"):
        ManagedOrderRefreshLoop(_Broker(), monotonic_clock="now")


def test_the_loop_is_driven_only_by_the_caller() -> None:
    clock = _Clock()
    broker = _Broker(results=[(1,)])
    loop = _loop(broker, clock)

    assert broker.calls == []
    loop.run_once()
    assert broker.calls == [4]
