"""Focused ordinary runstrategies startup-failure cleanup coverage."""

import logging
import traceback

from datetime import time
from types import SimpleNamespace
import backtrader as bt
import pytest
from backtrader.feed import DataBase, FeedBase
from backtrader.brokers.bbroker import BackBroker


class _LifecycleControl:
    def __init__(self, fail_at=None, fail_stop=()):
        self.events = []
        self.fail_at = fail_at
        self.fail_stop = set(fail_stop)
        self.primary = RuntimeError("startup primary marker")

    def event(self, name):
        self.events.append(name)
        if name == self.fail_at:
            raise self.primary
        if name in self.fail_stop:
            raise RuntimeError("cleanup secondary marker")


def _capture_strategy_logs(caplog, request):
    strategy_logger = logging.getLogger("backtrader.strategy")
    strategy_logger.addHandler(caplog.handler)
    request.addfinalizer(lambda: strategy_logger.removeHandler(caplog.handler))


class _LifecycleData(DataBase):
    params = (("control", None),)

    def start(self):
        control = self.p.control
        if control is not None:
            control.event("data.start")
        super().start()

    def stop(self):
        control = self.p.control
        if control is not None:
            control.event("data.stop")

    def _start(self):
        control = self.p.control
        if control is not None:
            control.events.append("data._start")
        super()._start()

    def _load(self):
        return False


class _LifecycleFeed(FeedBase):
    def __init__(self, control, data, fail_after_start=False):
        self.control = control
        super().__init__()
        self.datas.append(data)
        data._feed = self
        self.fail_after_start = fail_after_start

    def start(self):
        self.control.event("feed.start")
        super().start()
        if self.fail_after_start:
            raise self.control.primary

    def stop(self):
        self.control.event("feed.stop")
        super().stop()


class _LifecycleBroker(BackBroker):
    def __init__(self, control):
        self.control = control
        super().__init__()

    def start(self):
        self.control.event("broker.start")
        super().start()

    def stop(self):
        self.control.event("broker.stop")
        super().stop()


class _LifecycleStore:
    def __init__(self, control, managed=True):
        self.control = control
        self._cerebro_managed_lifecycle = managed

    def start(self):
        self.control.event("store.start")

    def stop(self):
        self.control.event("store.stop")

    def get_notifications(self):
        return []


def _make_cerebro(control, *, managed_store=True, with_writer=False):
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    cerebro.setbroker(_LifecycleBroker(control))
    cerebro.addstore(_LifecycleStore(control, managed=managed_store))
    data = _LifecycleData(control=control)
    cerebro.adddata(data)

    if with_writer:

        class _LifecycleWriter:
            def __init__(self):
                self.p = SimpleNamespace(csv=False)

            def start(self):
                control.event("writer.start")

            def stop(self):
                control.event("writer.stop")

            def writedict(self, _value):
                control.event("writer.report")

        cerebro.addwriter(_LifecycleWriter)

    return cerebro, data


@pytest.mark.parametrize(
    "failure_phase,expected_stops",
    [
        ("store.start", ["store.stop"]),
        ("broker.start", ["broker.stop", "store.stop"]),
        ("data.start", ["broker.stop", "data.stop", "store.stop"]),
        ("strategy.start", ["broker.stop", "data.stop", "store.stop"]),
        (
            "writer.start",
            ["strategy.stop", "writer.stop", "broker.stop", "data.stop", "store.stop"],
        ),
    ],
)
def test_startup_failure_stops_only_attempted_components(
    failure_phase, expected_stops, monkeypatch
):
    control = _LifecycleControl(fail_at=failure_phase)
    cerebro, _data = _make_cerebro(control, with_writer=failure_phase == "writer.start")
    cerebro.addstrategy(bt.Strategy)

    if failure_phase == "strategy.start":
        monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.event("strategy.start"))
        monkeypatch.setattr(
            bt.Strategy, "stop", lambda _self: control.events.append("strategy.stop")
        )
    elif failure_phase == "writer.start":
        monkeypatch.setattr(
            bt.Strategy, "start", lambda _self: control.events.append("strategy.start")
        )
        monkeypatch.setattr(
            bt.Strategy, "stop", lambda _self: control.events.append("strategy.stop")
        )

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert [event for event in control.events if event.endswith(".stop")] == expected_stops
    if failure_phase == "strategy.start":
        assert "strategy.stop" not in control.events
        assert caught.value._backtrader_startup_cleanup_incomplete == (
            (
                "strategy._start",
                "Strategy",
                "_start did not return; child completion is unknown, so _stop was skipped",
            ),
        )


def test_feed_start_failure_uses_one_feed_owned_data_stop():
    control = _LifecycleControl()
    cerebro, data = _make_cerebro(control)
    feed = _LifecycleFeed(control, data, fail_after_start=True)
    cerebro.feeds.append(feed)
    cerebro.addstrategy(bt.Strategy)

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert control.events == [
        "store.start",
        "broker.start",
        "feed.start",
        "data.start",
        "broker.stop",
        "feed.stop",
        "data.stop",
        "store.stop",
    ]


def test_timer_start_failure_cleans_prior_starts_and_reports_no_timer_stop_api(monkeypatch):
    control = _LifecycleControl(fail_at="timer.start")
    cerebro, _data = _make_cerebro(control, with_writer=True)
    cerebro.addstrategy(bt.Strategy)
    monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.events.append("strategy.start"))
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: control.events.append("strategy.stop"))
    timer = cerebro.add_timer(when=time(9, 30))
    monkeypatch.setattr(timer, "start", lambda _data: control.event("timer.start"))

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert [event for event in control.events if event.endswith(".stop")] == [
        "strategy.stop",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]
    assert caught.value._backtrader_startup_cleanup_incomplete == (
        (
            "timer.start",
            "Timer",
            "runstrategies has no timer stop step; start state may be partial",
        ),
    )


def test_cleanup_errors_do_not_replace_primary_or_block_later_stops(monkeypatch):
    control = _LifecycleControl(
        fail_at="writer.start",
        fail_stop={
            "writer.stop",
            "broker.stop",
            "data.stop",
            "store.stop",
        },
    )
    cerebro, _data = _make_cerebro(control, with_writer=True)
    cerebro.addstrategy(bt.Strategy)
    monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.events.append("strategy.start"))
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: control.events.append("strategy.stop"))

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert [event for event in control.events if event.endswith(".stop")] == [
        "strategy.stop",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]
    failures = caught.value._backtrader_startup_cleanup_errors
    assert [
        (phase, component, exception_type) for phase, component, exception_type, _ in failures
    ] == [
        ("writer[0].stop", "_LifecycleWriter", "RuntimeError"),
        ("broker[0].stop", "_LifecycleBroker", "RuntimeError"),
        ("data[0].stop", "_LifecycleData", "RuntimeError"),
        ("store[0].stop", "_LifecycleStore", "RuntimeError"),
    ]
    assert all(locations for _phase, _component, _error, locations in failures)
    primary_frames = {frame.name for frame in traceback.extract_tb(caught.value.__traceback__)}
    assert "event" in primary_frames
    assert "runstrategies" in primary_frames


def test_predata_failure_does_not_directly_stop_unstarted_data(monkeypatch):
    control = _LifecycleControl(fail_at="strategy.start")
    cerebro, _data = _make_cerebro(control)
    cerebro._resolve_run_flags()
    monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.event("strategy.start"))
    with pytest.raises(RuntimeError) as caught:
        cerebro.runstrategies(iter(((bt.Strategy, (), {}),)), predata=True)

    assert caught.value is control.primary
    assert control.events == [
        "store.start",
        "broker.start",
        "strategy.start",
        "broker.stop",
        "store.stop",
    ]


def test_unmanaged_store_is_started_but_not_stopped_after_failure():
    control = _LifecycleControl(fail_at="broker.start")
    cerebro, _data = _make_cerebro(control, managed_store=False)
    cerebro.addstrategy(bt.Strategy)

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert "store.start" in control.events
    assert "store.stop" not in control.events
    assert caught.value._backtrader_startup_cleanup_incomplete == (
        (
            "store[0].stop",
            "_LifecycleStore",
            "unmanaged Store remains under its external lifecycle owner",
        ),
    )


def test_strategy_stop_failure_marks_child_teardown_unknown(monkeypatch):
    control = _LifecycleControl(fail_at="writer.start", fail_stop={"strategy.stop"})
    cerebro, _data = _make_cerebro(control, with_writer=True)
    cerebro.addstrategy(bt.Strategy)
    cerebro.addanalyzer(bt.analyzers.Returns)
    cerebro.addobserver(bt.observers.Broker)
    monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.events.append("strategy.start"))
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: control.event("strategy.stop"))

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert control.events[5:] == [
        "writer.start",
        "strategy.stop",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]
    assert (
        "strategy[0]._stop",
        "Strategy",
        "_stop raised; analyzer/observer teardown completion is unknown",
    ) in caught.value._backtrader_startup_cleanup_incomplete


def test_swallowed_observer_stop_error_is_reported_without_logging_message(monkeypatch, caplog, request):
    control = _LifecycleControl(fail_at="writer.start")
    cerebro, _data = _make_cerebro(control, with_writer=True)
    cerebro.addstrategy(bt.Strategy)
    cerebro.addobserver(bt.observers.Broker)
    monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.events.append("strategy.start"))
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: control.events.append("strategy.stop"))
    caplog.set_level(logging.WARNING, logger="backtrader.strategy")
    _capture_strategy_logs(caplog, request)

    observer_stop_calls = []
    observer_sentinel = "PRIVATE_OBSERVER_STOP_SENTINEL"

    def fail_observer_stop(_observer):
        observer_stop_calls.append("attempted")
        raise RuntimeError(observer_sentinel)

    monkeypatch.setattr(bt.observers.Broker, "stop", fail_observer_stop)

    with pytest.raises(RuntimeError) as caught:
        cerebro.run()

    assert caught.value is control.primary
    assert observer_stop_calls == ["attempted"]
    observer_failures = caught.value._backtrader_startup_cleanup_errors
    assert [
        (phase, component, exception_type)
        for phase, component, exception_type, _locations in observer_failures
    ] == [
        ("strategy[0]._stop.observer[0].stop", "Broker", "RuntimeError"),
    ]
    assert observer_failures[0][3]
    assert observer_sentinel not in caplog.text
    assert (
        "strategy[0]._stop.observers",
        "Strategy",
        "Strategy._stop suppresses observer.stop exceptions; outcome is unobservable",
    ) in caught.value._backtrader_startup_cleanup_incomplete


def test_normal_run_keeps_legacy_observer_stop_exception_suppression(monkeypatch, caplog, request):
    control = _LifecycleControl()
    cerebro, _data = _make_cerebro(control)
    cerebro.addstrategy(bt.Strategy)
    cerebro.addobserver(bt.observers.Broker)
    caplog.set_level(logging.WARNING, logger="backtrader.strategy")
    _capture_strategy_logs(caplog, request)
    observer_stop_calls = []
    observer_sentinel = "NORMAL_OBSERVER_STOP_SENTINEL"

    def fail_observer_stop(_observer):
        observer_stop_calls.append("attempted")
        raise RuntimeError(observer_sentinel)

    monkeypatch.setattr(bt.observers.Broker, "stop", fail_observer_stop)

    result = cerebro.run()

    assert len(result) == 1
    assert observer_stop_calls == ["attempted"]
    assert observer_sentinel in caplog.text


def test_nested_observer_stop_failure_does_not_pollute_outer_cleanup(monkeypatch, caplog, request):
    outer_control = _LifecycleControl(fail_at="writer.start")
    outer_cerebro, _outer_data = _make_cerebro(outer_control, with_writer=True)
    outer_cerebro.addstrategy(bt.Strategy)
    outer_cerebro.addobserver(bt.observers.Broker)

    inner_control = _LifecycleControl()
    inner_cerebro, _inner_data = _make_cerebro(inner_control)

    class _NestedObserver(bt.Observer):
        lines = ("value",)

    inner_cerebro.addstrategy(bt.Strategy)
    inner_cerebro.addobserver(_NestedObserver)
    caplog.set_level(logging.WARNING, logger="backtrader.strategy")
    _capture_strategy_logs(caplog, request)

    observer_stop_calls = []
    inner_results = []
    inner_sentinel = "NESTED_OBSERVER_STOP_SENTINEL"
    outer_sentinel = "OUTER_OBSERVER_STOP_SENTINEL"

    def fail_inner_observer_stop(_observer):
        observer_stop_calls.append("inner")
        inner_control.events.append("nested.observer.stop")
        raise RuntimeError(inner_sentinel)

    def fail_outer_observer_stop(_observer):
        observer_stop_calls.append("outer")
        outer_control.events.append("outer.observer.stop")
        inner_results.append(inner_cerebro.run())
        raise RuntimeError(outer_sentinel)

    monkeypatch.setattr(_NestedObserver, "stop", fail_inner_observer_stop)
    monkeypatch.setattr(bt.observers.Broker, "stop", fail_outer_observer_stop)

    with pytest.raises(RuntimeError) as caught:
        outer_cerebro.run()

    assert caught.value is outer_control.primary
    assert [len(result) for result in inner_results] == [1]
    assert observer_stop_calls == ["outer", "inner"]
    observer_failures = caught.value._backtrader_startup_cleanup_errors
    assert [
        (phase, component, exception_type)
        for phase, component, exception_type, _locations in observer_failures
    ] == [
        ("strategy[0]._stop.observer[0].stop", "Broker", "RuntimeError"),
    ]
    assert inner_sentinel not in caplog.text
    assert outer_sentinel not in caplog.text
    assert [event for event in outer_control.events if event.endswith(".stop")] == [
        "outer.observer.stop",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]


def test_unknown_feed_owner_skips_direct_data_stop_and_marks_cleanup_incomplete():
    class _SlotData:
        __slots__ = ("stop_calls",)

        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    class _Feed:
        __slots__ = ("stop_calls",)

        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    cerebro = bt.Cerebro()
    data = _SlotData()
    feed = _Feed()
    primary = RuntimeError("startup primary marker")
    attempts = {
        "stores": [],
        "brokers": [],
        "feeds": [feed],
        "datas": [data],
        "strategy_attempts": [],
        "started_strategies": [],
        "writers": [],
        "timers": [],
    }

    cerebro._cleanup_startup_attempts(attempts, primary, predata=False)

    assert data.stop_calls == 0
    assert feed.stop_calls == 1
    assert (
        "data.stop",
        "_SlotData",
        "feed ownership is unknown; direct stop was skipped to avoid a duplicate",
    ) in primary._backtrader_startup_cleanup_incomplete
    assert any(
        phase == "data.feed_owner" and error_type == "TypeError"
        for phase, _component, error_type, _locations in primary._backtrader_startup_cleanup_errors
    )


def test_successful_run_preserves_existing_start_and_stop_order(monkeypatch):
    control = _LifecycleControl()
    cerebro, data = _make_cerebro(control, with_writer=True)
    feed = _LifecycleFeed(control, data)
    cerebro.feeds.append(feed)
    cerebro.addstrategy(bt.Strategy)
    cerebro.addobserver(bt.observers.Broker)
    monkeypatch.setattr(bt.Strategy, "start", lambda _self: control.events.append("strategy.start"))
    monkeypatch.setattr(bt.Strategy, "stop", lambda _self: control.events.append("strategy.stop"))
    monkeypatch.setattr(
        bt.observers.Broker, "start", lambda _self: control.events.append("observer.start")
    )
    monkeypatch.setattr(
        bt.observers.Broker, "stop", lambda _self: control.events.append("observer.stop")
    )

    result = cerebro.run()

    assert len(result) == 1
    assert control.events == [
        "store.start",
        "broker.start",
        "feed.start",
        "data.start",
        "data._start",
        "data.start",
        "observer.start",
        "strategy.start",
        "writer.start",
        "strategy.stop",
        "observer.stop",
        "writer.report",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "feed.stop",
        "data.stop",
        "store.stop",
    ]


def test_nested_run_and_followup_run_keep_startup_cleanup_run_local(monkeypatch):
    outer_control = _LifecycleControl(fail_at="writer.start")
    inner_control = _LifecycleControl()
    inner_cerebro, _inner_data = _make_cerebro(inner_control)
    inner_cerebro.addstrategy(bt.Strategy)
    outer_cerebro, _outer_data = _make_cerebro(outer_control, with_writer=True)
    outer_cerebro.addstrategy(bt.Strategy)

    class _NestedLifecycleStore(_LifecycleStore):
        def __init__(self, control, nested_cerebro):
            super().__init__(control)
            self.nested_cerebro = nested_cerebro
            self.start_calls = 0

        def start(self):
            super().start()
            self.start_calls += 1
            if self.start_calls == 1:
                self.nested_cerebro.run()

    outer_cerebro.stores[0] = _NestedLifecycleStore(outer_control, inner_cerebro)

    def strategy_start(strategy):
        strategy.datas[0].p.control.events.append("strategy.start")

    def strategy_stop(strategy):
        strategy.datas[0].p.control.events.append("strategy.stop")

    monkeypatch.setattr(bt.Strategy, "start", strategy_start)
    monkeypatch.setattr(bt.Strategy, "stop", strategy_stop)

    with pytest.raises(RuntimeError) as caught:
        outer_cerebro.run()

    assert caught.value is outer_control.primary
    assert inner_control.events == [
        "store.start",
        "broker.start",
        "data._start",
        "data.start",
        "strategy.start",
        "strategy.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]
    assert outer_control.events == [
        "store.start",
        "broker.start",
        "data._start",
        "data.start",
        "strategy.start",
        "writer.start",
        "strategy.stop",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]

    # Reusing this Cerebro after a failed startup gets a fresh run-local record.
    outer_control.fail_at = None
    result = outer_cerebro.run()

    assert len(result) == 1
    assert outer_control.events[11:] == [
        "store.start",
        "broker.start",
        "data._start",
        "data.start",
        "strategy.start",
        "writer.start",
        "strategy.stop",
        "writer.report",
        "writer.stop",
        "broker.stop",
        "data.stop",
        "store.stop",
    ]
    assert inner_control.events.count("store.stop") == 1
    assert inner_control.events.count("broker.stop") == 1
    assert inner_control.events.count("data.stop") == 1
