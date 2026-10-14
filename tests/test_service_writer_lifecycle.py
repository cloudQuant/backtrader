"""Regression coverage for final writer reports during Cerebro shutdown."""

from __future__ import annotations

import datetime

import backtrader as bt
import pytest


class _LifecycleProbe:
    def __init__(self):
        self.events = []
        self.report_value = None
        self.writer_active = None
        self.writer_stopped = False


class _StrictBackBroker(bt.brokers.BackBroker):
    """A normal backtesting broker that rejects report reads after stop."""

    def __init__(self, probe):
        self._probe = probe
        self._active = False
        self.stop_calls = 0
        super().__init__()

    def start(self):
        self._active = True
        self._probe.events.append("broker.start")
        return super().start()

    def stop(self):
        self.stop_calls += 1
        self._probe.events.append("broker.stop")
        try:
            return super().stop()
        finally:
            self._active = False

    def getvalue(self, datas=None):
        if not self._active:
            raise RuntimeError("broker report unavailable after stop")
        return super().getvalue(datas=datas)


class _FiniteMemoryFeed(bt.feed.DataBase):
    """One deterministic bar with lifecycle calls recorded by the probe."""

    def __init__(self):
        super().__init__()
        self._index = 0
        self.probe = None
        self.stop_calls = 0

    def start(self):
        super().start()
        self._index = 0
        self.probe.events.append("data.start")

    def stop(self):
        self.stop_calls += 1
        self.probe.events.append("data.stop")
        return super().stop()

    def _load(self):
        if self._index:
            return False

        self.lines.datetime[0] = bt.date2num(datetime.datetime(2026, 10, 14, 9, 30))
        self.lines.open[0] = 100.0
        self.lines.high[0] = 101.0
        self.lines.low[0] = 99.0
        self.lines.close[0] = 100.5
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


class _TrackedStore:
    """A synthetic lifecycle leaf registered with the real Cerebro engine."""

    _cerebro_managed_lifecycle = True

    def __init__(self, probe):
        self.probe = probe
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.probe.events.append("store.start")

    def stop(self):
        self.stop_calls += 1
        self.probe.events.append("store.stop")

    def get_notifications(self):
        return ()


def _make_strategy(report_error=None, loop_error=None):
    class _ProbeStrategy(bt.Strategy):
        def next(self):
            if loop_error is not None:
                raise loop_error

        def getwriterinfo(self):
            if report_error is not None:
                raise report_error
            return super().getwriterinfo()

    return _ProbeStrategy


def _make_writer(probe, broker, report_error=None):
    class _MemoryReportWriter(bt.WriterStringIO):
        def writedict(self, dct, level=0, recurse=False):
            if not recurse:
                probe.events.append("writer.writedict")
                probe.writer_active = broker._active
                if report_error is not None:
                    raise report_error
                strategy_info = dct["Cerebro"]["Strategies"]["_ProbeStrategy"]
                probe.report_value = strategy_info["Analyzers"]["Value"]["End"]
            return super().writedict(dct, level=level, recurse=recurse)

        def stop(self):
            probe.events.append("writer.stop")
            probe.writer_stopped = True
            return super().stop()

    return _MemoryReportWriter


def _make_run(probe, strategy, writer_error=None):
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False, writer=False)
    broker = _StrictBackBroker(probe)
    feed = _FiniteMemoryFeed()
    feed.probe = probe
    store = _TrackedStore(probe)
    cerebro.setbroker(broker)
    cerebro.adddata(feed)
    cerebro.addstore(store)
    cerebro.addwriter(_make_writer(probe, broker, report_error=writer_error))
    cerebro.addstrategy(strategy)
    return cerebro, broker, feed, store


def _assert_resources_stopped(probe, broker, feed, store):
    assert broker.stop_calls == 1
    assert broker._active is False
    assert feed.stop_calls == 1
    assert store.start_calls == 1
    assert store.stop_calls == 1
    assert probe.writer_stopped is True


def test_writer_receives_final_value_while_broker_is_active():
    probe = _LifecycleProbe()
    cerebro, broker, feed, store = _make_run(probe, _make_strategy())

    results = cerebro.run()

    assert len(results) == 1
    assert probe.writer_active is True
    assert probe.report_value == broker.startingcash
    assert "End: 10000.0" in cerebro.runwriters[0].getvalue()
    assert probe.events.index("writer.writedict") < probe.events.index("broker.stop")
    _assert_resources_stopped(probe, broker, feed, store)


@pytest.mark.parametrize("failure_site", ("strategy_report", "writer_report"))
def test_report_failure_still_stops_writer_and_runtime_resources(failure_site):
    probe = _LifecycleProbe()
    error = RuntimeError("final report failed")
    strategy_error = error if failure_site == "strategy_report" else None
    writer_error = error if failure_site == "writer_report" else None
    cerebro, broker, feed, store = _make_run(
        probe,
        _make_strategy(report_error=strategy_error),
        writer_error=writer_error,
    )

    with pytest.raises(RuntimeError, match="final report failed") as raised:
        cerebro.run()

    assert raised.value is error
    if failure_site == "strategy_report":
        assert "writer.writedict" not in probe.events
    else:
        assert "writer.writedict" in probe.events
    _assert_resources_stopped(probe, broker, feed, store)


def test_run_loop_error_remains_primary_when_final_report_also_fails():
    probe = _LifecycleProbe()
    loop_error = RuntimeError("strategy loop failed")
    report_error = RuntimeError("final report failed")
    cerebro, broker, feed, store = _make_run(
        probe,
        _make_strategy(report_error=report_error, loop_error=loop_error),
    )

    with pytest.raises(RuntimeError, match="strategy loop failed") as raised:
        cerebro.run()

    assert raised.value is loop_error
    _assert_resources_stopped(probe, broker, feed, store)
