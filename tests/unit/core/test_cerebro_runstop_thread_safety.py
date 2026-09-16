"""Deterministic concurrency coverage for :meth:`Cerebro.runstop`.

The tests deliberately block at lifecycle boundaries with ``threading.Event``
instead of sleeping.  This makes the Timer/worker-thread interleavings
repeatable and guarantees each test releases a running engine before joining.
"""

import datetime
import pickle
import threading

import backtrader as bt
import pytest


class _FiniteFeed(bt.feeds.DataBase):
    """A restartable in-memory feed with a known number of bars."""

    params = (("bar_count", 8),)

    def __init__(self):
        super().__init__()
        self._index = 0

    def start(self):
        super().start()
        self._index = 0

    def _load(self):
        if self._index >= self.p.bar_count:
            return False

        value = float(100 + self._index)
        timestamp = datetime.datetime(2024, 1, 2, 9, 0) + datetime.timedelta(minutes=self._index)
        self.lines.datetime[0] = bt.date2num(timestamp)
        self.lines.open[0] = value
        self.lines.high[0] = value
        self.lines.low[0] = value
        self.lines.close[0] = value
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


class _RunControl:
    """Shared, test-owned synchronization and observation state."""

    def __init__(self, block_first_bar=False):
        self.block_first_bar = block_first_bar
        self.entered = threading.Event()
        self.release = threading.Event()
        self.counts = []


class _GateStrategy(bt.Strategy):
    """Record bars and optionally hold the first one until the test releases it."""

    params = (("control", None),)

    def next(self):
        control = self.p.control
        control.counts.append(len(self))
        if control.block_first_bar and len(self) == 1:
            control.entered.set()
            if not control.release.wait(timeout=2.0):
                raise RuntimeError("runstop test did not release the first strategy callback")


class _StartupGateCerebro(bt.Cerebro):
    """Expose the interval after run activation and before engine work begins."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.run_published = threading.Event()
        self.continue_run = threading.Event()

    def _begin_run(self):
        super()._begin_run()
        self.run_published.set()
        if not self.continue_run.wait(timeout=2.0):
            raise RuntimeError("runstop test did not release the startup gate")


class _FailOnceAfterBeginCerebro(bt.Cerebro):
    """Exercise a subclass hook which publishes a scope and then raises."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._fail_start_once = True

    def _begin_run(self):
        super()._begin_run()
        if self._fail_start_once:
            self._fail_start_once = False
            raise RuntimeError("intentional startup failure after publishing the run scope")


class _ChannelControl:
    """Observe startup and teardown for an externally driven channel session."""

    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.start_calls = 0
        self.stop_calls = 0


class _ChannelLifecycleStrategy(bt.Strategy):
    """A no-data strategy whose lifecycle is visible to the test."""

    params = (("control", None),)

    def start(self):
        control = self.p.control
        control.start_calls += 1
        control.started.set()

    def stop(self):
        control = self.p.control
        control.stop_calls += 1
        control.stopped.set()


def _make_cerebro(control, cerebro_class=bt.Cerebro, bar_count=8):
    cerebro = cerebro_class(stdstats=False, preload=False, runonce=False, maxcpus=1)
    cerebro.adddata(_FiniteFeed(bar_count=bar_count))
    cerebro.addstrategy(_GateStrategy, control=control)
    return cerebro


def _make_channel_cerebro(control):
    """Create a channel-only Cerebro instance without a bar feed."""
    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    cerebro.addstrategy(_ChannelLifecycleStrategy, control=control)
    return cerebro


def _run_in_thread(cerebro):
    outcomes = []
    errors = []

    def target():
        try:
            outcomes.append(cerebro.run())
        except BaseException as exc:  # keep the test thread joinable on engine failure
            errors.append(exc)

    thread = threading.Thread(target=target, name="cerebro-runstop-test")
    thread.start()
    return thread, outcomes, errors


def test_threading_timer_stops_running_cerebro_without_hang():
    """A Timer request after ``next`` starts stops the active run at that bar."""
    control = _RunControl(block_first_bar=True)
    cerebro = _make_cerebro(control)
    timer_observed_start = []

    def stop_after_first_callback_starts():
        timer_observed_start.append(control.entered.wait(timeout=2.0))
        if timer_observed_start[-1]:
            cerebro.runstop()
        control.release.set()

    timer = threading.Timer(0.0, stop_after_first_callback_starts)
    timer.daemon = True
    timer.start()
    try:
        result = cerebro.run()
    finally:
        control.release.set()
        timer.join(timeout=2.0)

    assert not timer.is_alive()
    assert timer_observed_start == [True]
    assert control.counts == [1]
    assert len(result) == 1


def test_concurrent_runstop_requests_are_idempotent():
    """Several concurrent callers can request the same active stop safely."""
    control = _RunControl(block_first_bar=True)
    cerebro = _make_cerebro(control)
    runner, outcomes, run_errors = _run_in_thread(cerebro)
    callers = 8
    barrier = threading.Barrier(callers + 1)
    stop_calls = []
    stop_errors = []

    def request_stop():
        try:
            barrier.wait(timeout=2.0)
            cerebro.runstop()
            stop_calls.append(threading.get_ident())
        except BaseException as exc:  # make a broken barrier an assertion failure, not a hang
            stop_errors.append(exc)

    stop_threads = [
        threading.Thread(target=request_stop, name=f"runstop-caller-{index}")
        for index in range(callers)
    ]
    for thread in stop_threads:
        thread.start()

    try:
        assert control.entered.wait(timeout=2.0)
        barrier.wait(timeout=2.0)
        for thread in stop_threads:
            thread.join(timeout=2.0)
        assert all(not thread.is_alive() for thread in stop_threads)
    finally:
        control.release.set()
        runner.join(timeout=2.0)

    assert not runner.is_alive()
    assert not stop_errors
    assert len(stop_calls) == callers
    assert not run_errors
    assert len(outcomes) == 1
    assert control.counts == [1]


def test_rejected_concurrent_run_does_not_retire_the_active_scope():
    """A rejected re-entry cannot clear the other thread's active run token."""
    control = _RunControl(block_first_bar=True)
    cerebro = _make_cerebro(control)
    runner, outcomes, run_errors = _run_in_thread(cerebro)

    try:
        assert control.entered.wait(timeout=2.0)
        active_token = cerebro._run_scope_token
        active_owner = cerebro._run_scope_owner

        with pytest.raises(RuntimeError, match="already running"):
            cerebro.run()

        assert cerebro._run_active
        assert cerebro._run_scope_token == active_token
        assert cerebro._run_scope_owner == active_owner
    finally:
        control.release.set()
        runner.join(timeout=2.0)

    assert not runner.is_alive()
    assert not run_errors
    assert len(outcomes) == 1


def test_stop_during_startup_interleaving_is_not_lost():
    """A stop after activation but before engine work is observed by the run."""
    control = _RunControl()
    cerebro = _make_cerebro(control, cerebro_class=_StartupGateCerebro)
    runner, outcomes, run_errors = _run_in_thread(cerebro)
    stopper = threading.Thread(target=cerebro.runstop, name="startup-runstop-caller")

    try:
        assert cerebro.run_published.wait(timeout=2.0)
        stopper.start()
        stopper.join(timeout=2.0)
        assert not stopper.is_alive()
    finally:
        cerebro.continue_run.set()
        runner.join(timeout=2.0)

    assert not runner.is_alive()
    assert not run_errors
    assert len(outcomes) == 1
    assert control.counts == []


def test_failed_startup_hook_does_not_latch_the_run_scope():
    """A subclass failure after ``super()._begin_run`` leaves the instance reusable."""
    control = _RunControl()
    cerebro = _make_cerebro(control, cerebro_class=_FailOnceAfterBeginCerebro, bar_count=3)

    try:
        cerebro.run()
    except RuntimeError as exc:
        assert "intentional startup failure" in str(exc)
    else:
        raise AssertionError("the first startup hook should fail")

    assert not cerebro._run_active
    assert not cerebro._event_stop

    result = cerebro.run()

    assert len(result) == 1
    assert control.counts == [1, 2, 3]


def test_stop_called_between_runs_does_not_poison_a_later_run():
    """A request made after one run ends is ignored before the next run starts."""
    control = _RunControl()
    cerebro = _make_cerebro(control, bar_count=4)

    first_result = cerebro.run()
    assert len(first_result) == 1
    assert control.counts == [1, 2, 3, 4]

    late_timer = threading.Timer(0.0, cerebro.runstop)
    late_timer.start()
    late_timer.join(timeout=2.0)
    assert not late_timer.is_alive()
    assert not cerebro._event_stop

    control.counts.clear()
    second_result = cerebro.run()
    assert len(second_result) == 1
    assert control.counts == [1, 2, 3, 4]


def test_cerebro_pickle_round_trip_recreates_process_local_stop_state():
    """The synchronization primitives do not break optimization worker pickling."""
    restored = pickle.loads(pickle.dumps(bt.Cerebro(stdstats=False)))

    restored.runstop()
    assert not restored._event_stop


def test_external_channel_runstop_signals_until_owner_closes_session():
    """``channel=True`` retains the scope until its owner performs teardown."""
    control = _ChannelControl()
    cerebro = _make_channel_cerebro(control)

    strategies = cerebro.run(channel=True)

    assert strategies and control.started.is_set()
    assert cerebro._run_active
    assert not control.stopped.is_set()

    cerebro.runstop()

    assert cerebro._event_stop
    assert not control.stopped.is_set()
    assert cerebro.close_channel() is True
    assert control.stopped.is_set()
    assert control.stop_calls == 1
    assert not cerebro._run_active
    assert not cerebro._event_stop


def test_foreign_runstop_only_signals_external_channel_without_teardown():
    """A foreign thread cannot race the owner while it tears a channel down."""
    control = _ChannelControl()
    cerebro = _make_channel_cerebro(control)
    cerebro.run(channel=True)
    stopper = threading.Thread(target=cerebro.runstop, name="external-channel-stopper")
    close_errors = []

    def close_from_foreign_thread():
        try:
            cerebro.close_channel()
        except BaseException as exc:  # retain the exact cross-thread failure for assertion
            close_errors.append(exc)

    closer = threading.Thread(target=close_from_foreign_thread, name="external-channel-closer")

    stopper.start()
    stopper.join(timeout=2.0)
    closer.start()
    closer.join(timeout=2.0)

    assert not stopper.is_alive()
    assert not closer.is_alive()
    assert cerebro._event_stop
    assert cerebro._run_active
    assert control.stop_calls == 0
    assert len(close_errors) == 1
    assert isinstance(close_errors[0], RuntimeError)
    assert str(close_errors[0]) == "Cerebro external channel must be closed by its owner thread"
    assert cerebro.close_channel() is True
    assert control.stop_calls == 1


def test_external_channel_reentry_is_rejected_until_owner_closes_session():
    """A returned external channel session is still an active Cerebro run."""
    control = _ChannelControl()
    cerebro = _make_channel_cerebro(control)
    cerebro.run(channel=True)

    with pytest.raises(RuntimeError, match="already running"):
        cerebro.run(channel=True)

    assert cerebro._run_active
    assert control.stop_calls == 0
    assert cerebro.close_channel() is True


def test_late_stop_after_external_channel_close_does_not_poison_next_run():
    """A post-close signal cannot stop a later, finite channel run."""
    control = _ChannelControl()
    cerebro = _make_channel_cerebro(control)
    cerebro.run(channel=True)
    assert cerebro.close_channel() is True

    cerebro.runstop()

    assert not cerebro._run_active
    assert not cerebro._event_stop
    cerebro.run(channel=[])
    assert control.start_calls == 2
    assert control.stop_calls == 2
    assert not cerebro._run_active
    assert not cerebro._event_stop


def test_finite_channel_iterable_tears_down_and_retires_its_scope_automatically():
    """Iterable channel runs keep the regular synchronous teardown behavior."""
    control = _ChannelControl()
    cerebro = _make_channel_cerebro(control)

    cerebro.run(channel=[])

    assert control.start_calls == 1
    assert control.stop_calls == 1
    assert not cerebro._run_active
    assert not cerebro._event_stop
    assert cerebro.close_channel() is False
