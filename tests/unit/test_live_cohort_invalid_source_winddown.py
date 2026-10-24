from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import MappingProxyType
import traceback

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
)


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class ReplayClock:
    """Deterministic causal clock for source collection and bounded winddown."""

    def __init__(self, now):
        self.now = now
        self.monotonic = 1_000_000_000
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        elapsed_ns = max(1, round(timeout_seconds * 1_000_000_000))
        self.monotonic += elapsed_ns
        self.now += timedelta(microseconds=elapsed_ns / 1_000)


class CountingIndicator(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.calls = 0

    def next(self):
        self.calls += 1
        self.lines.value[0] = self.data.close[0]


class OrderWinddownStrategy(bt.Strategy):
    params = (("leave_order_unresolved", False), ("idle_error", None))
    instances = []

    def __init__(self):
        type(self).instances.append(self)
        self.factor = CountingIndicator(self.data)
        self.next_calls = 0
        self.idle_calls = 0
        self.shutdown_requested = False
        self.shutdown_ready = False
        self.shutdown_blocker = None
        self.order = None
        self.cancel_requested = False
        self.cancel_notified = False
        self.order_statuses = []

    def next(self):
        self.next_calls += 1
        if self.order is None:
            # This limit is deliberately outside the bar range, so it remains
            # a real Broker-owned working order until the shutdown path cancels it.
            self.order = self.buy(size=1, exectype=bt.Order.Limit, price=1.0)

    def notify_order(self, order):
        self.order_statuses.append(order.status)
        if order.ref == self.order.ref and order.status == bt.Order.Canceled:
            self.cancel_notified = True

    def request_shutdown(self):
        self.shutdown_requested = True
        self.shutdown_blocker = "SHUTDOWN_FACTS_PENDING"

    def notify_idle(self):
        self.idle_calls += 1
        if self.p.idle_error is not None:
            raise self.p.idle_error
        if self.p.leave_order_unresolved:
            self.shutdown_ready = False
            self.shutdown_blocker = "SHUTDOWN_ORDER_UNKNOWN"
            return
        if self.order is not None and self.order.alive() and not self.cancel_requested:
            self.cancel_requested = bool(self.broker.cancel(self.order))
        if self.cancel_notified and not self.broker.get_orders_open(safe=False):
            self.shutdown_ready = True
            self.shutdown_blocker = None
            self.cerebro.runstop()


class UnsupportedShutdownStrategy(bt.Strategy):
    """Control proving ordinary strategies retain immediate error behavior."""

    params = (("leave_order_unresolved", False),)

    def __init__(self):
        self.next_calls = 0

    def next(self):
        self.next_calls += 1


class NonCallableIdleShutdownStrategy(bt.Strategy):
    params = (("leave_order_unresolved", False),)
    notify_idle = None
    instances = []

    def __init__(self):
        type(self).instances.append(self)
        self.next_calls = 0
        self.shutdown_requests = 0
        self.shutdown_requested = False
        self.shutdown_ready = False

    def request_shutdown(self):
        self.shutdown_requests += 1
        self.shutdown_requested = True

    def next(self):
        self.next_calls += 1


class ShutdownCapabilityProbeStrategy(bt.Strategy):
    params = (("leave_order_unresolved", False),)

    @property
    def request_shutdown(self):
        raise AssertionError("shutdown capability was probed outside enabled cohort winddown")

    @property
    def shutdown_requested(self):
        raise AssertionError("shutdown capability was probed outside enabled cohort winddown")

    @property
    def shutdown_ready(self):
        raise AssertionError("shutdown capability was probed outside enabled cohort winddown")

    def next(self):
        pass


def _event(slot, sequence, *, close=10.5):
    return MappingProxyType(
        {
            "instrument": "A",
            "symbol": "A",
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": slot.close_time,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "invalid-source-clock",
            "connection_generation": "generation-1",
            "bar_sequence": sequence,
            "bar_id": "A-{}".format(sequence),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": close,
            "volume": 1.0,
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "finite-invalid-source-replay",
        }
    )


def _build_run(
    *, timeout, leave_order_unresolved=False, idle_error=None, strategy=OrderWinddownStrategy
):
    slots = tuple(
        LiveCalendarSlot(
            "slot-{}".format(index),
            START + timedelta(minutes=index),
            START + timedelta(minutes=index + 1),
            "2025-01-02",
            "regular",
        )
        for index in range(2)
    )
    calendar = LiveCohortCalendar(
        calendar_id="invalid-source-calendar",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="invalid-source-clock",
        session_semantics="session-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "invalid-source-cohort",
        calendar,
        max_pending_slots=1,
        max_window_bars=4,
        wait_timeout_ns=1_000_000_000,
    )
    feed = bt.feeds.BtApiFeed(
        dataname="A",
        historical_bars=(),
        live_bars=(_event(slots[0], 1), _event(slots[1], 2, close=float("nan"))),
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cohort.register_member(
        "member-A",
        feed,
        instrument="A",
        source_ref="source-A",
        line_fields=FIELDS,
        raw_fields=FIELDS,
        numeric_fields=FIELDS,
    )
    clock = ReplayClock(slots[-1].close_time)
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    broker = bt.brokers.BackBroker(cash=10_000)
    broker.next_without_bar = True
    cerebro.setbroker(broker)
    cerebro.adddata(feed, name="A")
    strategy_params = {"leave_order_unresolved": leave_order_unresolved}
    if idle_error is not None:
        strategy_params["idle_error"] = idle_error
    cerebro.addstrategy(strategy, **strategy_params)
    cerebro.add_live_bar_cohort(
        cohort,
        clock=clock,
        winddown_timeout_seconds=timeout,
    )

    feed.calls = {"collect": 0, "check": 0, "last": 0}
    original_collect = feed._cohort_collect_source
    original_check = feed._check
    original_last = feed._last
    source_errors = []

    def track_collect(*args, **kwargs):
        feed.calls["collect"] += 1
        try:
            return original_collect(*args, **kwargs)
        except LiveCohortValidationError as exc:
            source_errors.append(exc)
            raise

    def track_check(*args, **kwargs):
        feed.calls["check"] += 1
        return original_check(*args, **kwargs)

    def track_last(*args, **kwargs):
        feed.calls["last"] += 1
        return original_last(*args, **kwargs)

    feed._cohort_collect_source = track_collect
    feed._check = track_check
    feed._last = track_last
    return cerebro, cohort, feed, clock, broker, source_errors


def test_typed_invalid_source_cancels_working_order_then_reraises_original_error():
    OrderWinddownStrategy.instances.clear()
    cerebro, cohort, feed, clock, broker, source_errors = _build_run(timeout=1.0)

    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    strategy = OrderWinddownStrategy.instances[-1]
    assert len(source_errors) == 1
    assert raised.value is source_errors[0]
    assert any(
        frame.name == "_build_envelope"
        for frame in traceback.extract_tb(raised.value.__traceback__)
    )
    assert getattr(raised.value, "report", None) is None
    assert cohort.frozen is True
    assert cohort.current_batch().slot_index == 0
    assert cerebro.live_bar_cohort_winddown_status == "STOPPED"
    assert cerebro.live_bar_cohort_winddown_reason == "runstop_requested"
    assert strategy.shutdown_requested is True
    assert strategy.shutdown_ready is True
    assert strategy.shutdown_blocker is None
    assert strategy.order.status == bt.Order.Canceled
    assert strategy.cancel_notified is True
    assert not broker.get_orders_open(safe=False)
    assert strategy.next_calls == 1
    assert strategy.factor.calls == 1
    assert strategy.idle_calls >= 2
    assert len(feed) == 1
    assert feed.calls == {"collect": 2, "check": 0, "last": 0}
    assert 0 < sum(clock.waits) <= 1.0


def test_typed_invalid_source_with_unresolved_order_times_out_without_claiming_flat():
    OrderWinddownStrategy.instances.clear()
    cerebro, cohort, feed, clock, broker, source_errors = _build_run(
        timeout=0.11,
        leave_order_unresolved=True,
    )

    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    strategy = OrderWinddownStrategy.instances[-1]
    assert len(source_errors) == 1
    assert raised.value is source_errors[0]
    assert cohort.frozen is True
    assert cohort.current_batch().slot_index == 0
    assert cerebro.live_bar_cohort_winddown_status == "TIMED_OUT"
    assert cerebro.live_bar_cohort_winddown_reason == (
        "invalid_source_winddown_blocked:deadline_expired"
    )
    assert strategy.shutdown_requested is True
    assert strategy.shutdown_ready is False
    assert strategy.shutdown_blocker == "SHUTDOWN_ORDER_UNKNOWN"
    assert strategy.order.alive() is True
    assert broker.get_orders_open(safe=False)
    assert strategy.next_calls == 1
    assert strategy.factor.calls == 1
    assert strategy.idle_calls >= 1
    assert len(feed) == 1
    assert feed.calls == {"collect": 2, "check": 0, "last": 0}
    assert clock.waits
    assert sum(clock.waits) == pytest.approx(0.11)


def test_maintenance_error_does_not_mask_the_original_source_error():
    maintenance_error = RuntimeError("synthetic idle maintenance failure")
    cerebro, cohort, feed, _clock, broker, source_errors = _build_run(
        timeout=1.0,
        idle_error=maintenance_error,
    )

    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    assert len(source_errors) == 1
    assert raised.value is source_errors[0]
    assert raised.value.__cause__ is maintenance_error
    assert cohort.frozen is True
    assert cerebro.live_bar_cohort_winddown_status == "FAILED"
    assert cerebro.live_bar_cohort_winddown_reason == (
        "invalid_source_winddown_blocked:maintenance_RuntimeError"
    )
    assert broker.get_orders_open(safe=False)
    assert len(feed) == 1
    assert feed.calls == {"collect": 2, "check": 0, "last": 0}


def test_non_shutdown_strategy_keeps_immediate_typed_source_failure_behavior():
    cerebro, cohort, feed, _clock, broker, source_errors = _build_run(
        timeout=1.0,
        strategy=UnsupportedShutdownStrategy,
    )

    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    assert len(source_errors) == 1
    assert raised.value is source_errors[0]
    assert cohort.frozen is True
    assert cerebro.live_bar_cohort_winddown_status == "NOT_REACHED"
    assert broker.get_orders_open(safe=False) == []
    assert feed.calls == {"collect": 2, "check": 0, "last": 0}


def test_typed_cohort_prepare_error_does_not_enter_invalid_source_winddown():
    OrderWinddownStrategy.instances.clear()
    cerebro, cohort, feed, _clock, broker, source_errors = _build_run(timeout=1.0)
    prepare_error = LiveCohortValidationError("synthetic prepare boundary failure")

    def raise_prepare_error(*args, **kwargs):
        raise prepare_error

    cohort.prepare_round = raise_prepare_error
    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    strategy = OrderWinddownStrategy.instances[-1]
    assert raised.value is prepare_error
    assert source_errors == []
    assert strategy.shutdown_requested is False
    assert cerebro.live_bar_cohort_winddown_status == "NOT_REACHED"
    assert broker.get_orders_open(safe=False) == []
    assert feed.calls == {"collect": 0, "check": 0, "last": 0}


def test_noncallable_notify_idle_does_not_enter_invalid_source_winddown():
    NonCallableIdleShutdownStrategy.instances.clear()
    cerebro, cohort, _feed, _clock, _broker, source_errors = _build_run(
        timeout=1.0,
        strategy=NonCallableIdleShutdownStrategy,
    )

    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    strategy = NonCallableIdleShutdownStrategy.instances[-1]
    assert len(source_errors) == 1
    assert raised.value is source_errors[0]
    assert strategy.shutdown_requests == 0
    assert strategy.shutdown_requested is False
    assert cohort.frozen is True
    assert cerebro.live_bar_cohort_winddown_status == "NOT_REACHED"


@pytest.mark.parametrize("cohort_timeout", (None, 0.0))
def test_shutdown_capability_properties_are_not_probed_when_disabled(cohort_timeout):
    if cohort_timeout is None:
        frame = pd.DataFrame(
            {
                "open": (10.0, 10.5),
                "high": (11.0, 11.5),
                "low": (9.0, 9.5),
                "close": (10.5, 11.0),
                "volume": (1.0, 2.0),
                "openinterest": (0.0, 0.0),
            },
            index=pd.date_range(START, periods=2, freq="min"),
        )
        cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(ShutdownCapabilityProbeStrategy)
        assert len(cerebro.run()) == 1
        return

    cerebro, cohort, _feed, _clock, _broker, source_errors = _build_run(
        timeout=cohort_timeout,
        strategy=ShutdownCapabilityProbeStrategy,
    )
    with pytest.raises(LiveCohortValidationError) as raised:
        cerebro.run()

    assert len(source_errors) == 1
    assert raised.value is source_errors[0]
    assert cohort.frozen is True
    assert cerebro.live_bar_cohort_winddown_status == "DISABLED"
