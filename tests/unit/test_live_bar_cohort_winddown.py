"""Bounded terminal maintenance for finite live-bar cohorts."""

from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research.live_cohort import LiveBarCohort, LiveCalendarSlot, LiveCohortCalendar


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class ReplayClock:
    """A deterministic source clock whose waits advance monotonic time."""

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


class InterruptibleReplayClock(ReplayClock):
    def __init__(self, now):
        super().__init__(now)
        self.waiting = threading.Event()

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        self.waits.append(timeout_seconds)
        self.waiting.set()
        try:
            return wait_for_event(timeout_seconds)
        finally:
            self.waiting.clear()


class RecordingStore:
    def __init__(self, unregister_error=None):
        self.started = False
        self.stopped = False
        self.callbacks = []
        self.registered = []
        self.unregistered = []
        self.unregister_error = unregister_error

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def get_notifications(self):
        return ()

    def _register_live_bar_event_waker(self, callback):
        token = object()
        self.callbacks.append(callback)
        self.registered.append(token)
        return token

    def _unregister_live_bar_event_waker(self, token):
        self.unregistered.append(token)
        if self.unregister_error is not None:
            raise self.unregister_error


class PollingBroker(bt.brokers.BackBroker):
    """Broker double that can poll without a new bar and emits one notice."""

    next_without_bar = True

    def __init__(self):
        super().__init__()
        self.next_calls = 0
        self._sent_notice = False

    def next(self):
        self.next_calls += 1
        runstrats = getattr(self.cerebro, "runningstrats", ())
        if runstrats and runstrats[0].next_calls and not self._sent_notice:
            self.notifs.append(SimpleNamespace(owner=runstrats[0]))
            self._sent_notice = True


class CountingIndicator(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.calls = 0

    def next(self):
        self.calls += 1
        self.lines.value[0] = self.data.close[0]


class WinddownStrategy(bt.Strategy):
    params = (("stop_on_idle", False), ("idle_error", None), ("wake_after_wait", None))
    instances = []

    def __init__(self):
        type(self).instances.append(self)
        self.factor = CountingIndicator(self.data)
        self.next_calls = 0
        self.idle_calls = 0
        self.order_notifications = []
        self.shutdown_ready = False

    def next(self):
        self.next_calls += 1
        if self.p.wake_after_wait is not None:
            self.p.wake_after_wait(self)

    def _addnotification(self, order, quicknotify=False):
        self.order_notifications.append(order)

    def notify_idle(self):
        self.idle_calls += 1
        if self.p.idle_error is not None:
            raise self.p.idle_error
        if self.p.stop_on_idle:
            self.shutdown_ready = True
        if self.shutdown_ready:
            self.cerebro.runstop()


def _build_run(
    *,
    timeout=0,
    stop_on_idle=False,
    idle_error=None,
    with_store=False,
    bind_cohort=True,
    clock=None,
    wake_after_wait=None,
):
    WinddownStrategy.instances.clear()
    close_time = START + timedelta(minutes=1)
    slot = LiveCalendarSlot(
        "slot-0",
        START,
        close_time,
        "2025-01-02",
        "regular",
    )
    calendar = LiveCohortCalendar(
        calendar_id="winddown-calendar",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="winddown-clock",
        session_semantics="session-v1",
        slots=(slot,),
    )
    cohort = LiveBarCohort(
        "winddown-cohort",
        calendar,
        max_pending_slots=1,
        max_window_bars=2,
        wait_timeout_ns=1_000_000_000,
    )
    event = MappingProxyType(
        {
            "instrument": "A",
            "symbol": "A",
            "timestamp": close_time.timestamp(),
            "datetime": close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": close_time,
            "available_at": close_time,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "winddown-clock",
            "connection_generation": "generation-1",
            "bar_sequence": 1,
            "bar_id": "A-1",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1.0,
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "finite-winddown-replay",
        }
    )
    feed = bt.feeds.BtApiFeed(
        dataname="A",
        historical_bars=(event,),
        live_bars=(),
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
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    cerebro.adddata(feed, name="A")
    cerebro.addstrategy(
        WinddownStrategy,
        stop_on_idle=stop_on_idle,
        idle_error=idle_error,
        wake_after_wait=wake_after_wait,
    )
    clock = clock or ReplayClock(close_time)
    if bind_cohort:
        cerebro.add_live_bar_cohort(
            cohort,
            clock=clock,
            winddown_timeout_seconds=timeout,
        )
    store = None
    if with_store:
        store = RecordingStore()
        cerebro.addstore(store)
    return cerebro, cohort, feed, clock, store


def _track_feed_nonadvancing_paths(feed):
    feed.last_calls = 0
    feed.check_calls = 0
    original_last = feed._last
    original_check = feed._check

    def tracked_last(*args, **kwargs):
        feed.last_calls += 1
        return original_last(*args, **kwargs)

    def tracked_check(*args, **kwargs):
        feed.check_calls += 1
        return original_check(*args, **kwargs)

    feed._last = tracked_last
    feed._check = tracked_check


def test_final_batch_runs_broker_and_idle_until_ready_without_advancing_feeds_or_factors():
    cerebro, cohort, feed, clock, store = _build_run(
        timeout=2.0,
        stop_on_idle=True,
        with_store=True,
    )
    broker = PollingBroker()
    cerebro.setbroker(broker)
    _track_feed_nonadvancing_paths(feed)

    strategy = cerebro.run()[0]

    assert cohort.current_batch() is not None
    assert cohort.current_batch().status == "COMPLETE"
    assert cerebro.live_bar_cohort_winddown_status == "STOPPED"
    assert cerebro.live_bar_cohort_winddown_reason == "runstop_requested"
    assert strategy.shutdown_ready is True
    assert strategy.next_calls == 1
    assert strategy.factor.calls == 1
    assert strategy.idle_calls == 1
    assert strategy.order_notifications
    assert broker.next_calls == 2
    assert len(feed) == 1
    assert feed.last_calls == 0
    assert feed.check_calls == 0
    assert clock.waits == []
    assert store.started is True
    assert store.stopped is True
    assert store.unregistered == store.registered


def test_final_batch_times_out_with_persisted_blocking_result_and_no_extra_feed_progress():
    cerebro, cohort, feed, clock, store = _build_run(timeout=0.25, with_store=True)
    broker = PollingBroker()
    cerebro.setbroker(broker)
    _track_feed_nonadvancing_paths(feed)

    with pytest.raises(TimeoutError, match="shutdown winddown timed out"):
        cerebro.run()

    strategy = WinddownStrategy.instances[-1]
    assert cohort.current_batch() is not None
    assert cohort.current_batch().status == "COMPLETE"
    assert cerebro.live_bar_cohort_winddown_status == "TIMED_OUT"
    assert cerebro.live_bar_cohort_winddown_reason == "winddown_deadline_expired"
    assert strategy.next_calls == 1
    assert strategy.factor.calls == 1
    # Winddown maintenance is now serviced in 50ms turns so a fresh quote
    # may be consumed without waiting through the whole shutdown deadline.
    assert strategy.idle_calls == 5
    assert broker.next_calls == 6  # one final-bar call plus five maintenance turns
    assert len(feed) == 1
    assert feed.last_calls == 0
    assert feed.check_calls == 0
    assert clock.waits == [pytest.approx(0.05)] * 5
    assert store.unregistered == store.registered


def test_store_event_wake_interrupts_terminal_wait_until_strategy_is_ready():
    clock = InterruptibleReplayClock(START + timedelta(minutes=1))
    waker_threads = []

    def start_waker(strategy):
        def wake_after_wait():
            if clock.waiting.wait(timeout=1.0):
                strategy.shutdown_ready = True
                strategy.wake_result = strategy.cerebro.wake_live_bar_cohort()

        thread = threading.Thread(target=wake_after_wait)
        waker_threads.append(thread)
        thread.start()

    cerebro, _cohort, feed, _clock, store = _build_run(
        timeout=2.0,
        with_store=True,
        clock=clock,
        wake_after_wait=start_waker,
    )
    broker = PollingBroker()
    cerebro.setbroker(broker)

    strategy = cerebro.run()[0]

    for thread in waker_threads:
        thread.join(timeout=1.0)
        assert not thread.is_alive()
    assert strategy.wake_result is True
    assert cerebro.live_bar_cohort_winddown_status == "STOPPED"
    assert strategy.shutdown_ready is True
    assert strategy.next_calls == 1
    assert strategy.factor.calls == 1
    assert strategy.idle_calls == 2
    assert broker.next_calls == 3
    assert len(feed) == 1
    assert len(clock.waits) == 1
    assert store.unregistered == store.registered


def test_notify_idle_exception_is_preserved_and_all_wakers_are_unbound():
    failure = RuntimeError("synthetic idle callback failure")
    cerebro, _cohort, _feed, _clock, _store = _build_run(
        timeout=2.0,
        idle_error=failure,
        with_store=True,
    )
    first_store = cerebro.stores[0]
    second_store = RecordingStore(unregister_error=OSError("synthetic unbind failure"))
    cerebro.addstore(second_store)
    cerebro.setbroker(PollingBroker())

    with pytest.raises(RuntimeError, match="synthetic idle callback failure") as raised:
        cerebro.run()

    assert raised.value is failure
    assert cerebro.live_bar_cohort_winddown_status == "FAILED"
    assert cerebro.live_bar_cohort_winddown_reason == "winddown_failed:RuntimeError"
    assert first_store.unregistered == first_store.registered
    assert second_store.unregistered == second_store.registered


def test_zero_timeout_keeps_finite_source_eof_behavior():
    cerebro, cohort, feed, clock, _store = _build_run()

    strategy = cerebro.run()[0]

    assert cerebro.live_bar_cohort_winddown_status == "DISABLED"
    assert cerebro.live_bar_cohort_winddown_reason == "disabled"
    assert cohort.current_batch() is not None
    assert cohort.current_batch().status == "COMPLETE"
    assert len(feed) == 1
    assert strategy.next_calls == 1
    assert strategy.factor.calls == 1
    assert clock.waits == []


@pytest.mark.parametrize(
    "timeout, error",
    (
        (True, TypeError),
        (math.nan, ValueError),
        (math.inf, ValueError),
        (-0.01, ValueError),
        (threading.TIMEOUT_MAX + 1.0, ValueError),
    ),
)
def test_winddown_timeout_is_validated_before_cohort_sealing(timeout, error):
    cerebro, cohort, _feed, clock, _store = _build_run(bind_cohort=False)

    with pytest.raises(error):
        cerebro.add_live_bar_cohort(
            cohort,
            clock=clock,
            winddown_timeout_seconds=timeout,
        )

    assert cohort._sealed is False
    assert cerebro.live_bar_cohort is None


def test_positive_winddown_requires_polling_broker_before_resources_start():
    cerebro, cohort, feed, clock, _store = _build_run(timeout=1.0)
    store = RecordingStore()
    cerebro.addstore(store)
    cerebro.setbroker(bt.brokers.BackBroker())

    with pytest.raises(ValueError, match="next_without_bar=True"):
        cerebro.run()

    assert store.started is False
    assert cohort._sealed is True
    assert feed.live_bar_cohort is None
