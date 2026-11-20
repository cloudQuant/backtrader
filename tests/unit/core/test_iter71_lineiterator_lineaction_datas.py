"""Regression coverage for the LineIterator LineActions input fast path."""

from __future__ import annotations

import datetime
import math
import pickle

import pytest

import backtrader as bt
from backtrader import lineiterator as lineiterator_module
from backtrader.lineiterator import LineIterator
from backtrader.lineseries import LineSeries


class _MemoryFeed(bt.feeds.DataBase):
    params = (("bars", None),)

    def __init__(self):
        super().__init__()
        self._cursor = 0

    def start(self):
        super().start()
        self._cursor = 0

    def _load(self):
        if self._cursor >= len(self.p.bars):
            return False

        bar = self.p.bars[self._cursor]
        self.lines.datetime[0] = bt.date2num(bar[0])
        for line_name, value in zip(
            ("open", "high", "low", "close", "volume", "openinterest"),
            bar[1:],
        ):
            getattr(self.lines, line_name)[0] = value
        self._cursor += 1
        return True


def _bars(closes, step_minutes):
    start = datetime.datetime(2024, 1, 1)
    return [
        (
            start + datetime.timedelta(minutes=index * step_minutes),
            close,
            close + 1.0,
            close - 1.0,
            close,
            1000.0,
            0.0,
        )
        for index, close in enumerate(closes)
    ]


def _finite_or_none(line):
    value = float(line[0])
    if not math.isfinite(value):
        return None
    return round(value, 10)


class _SlowSignal(bt.Indicator):
    lines = ("signal",)

    def __init__(self):
        self.average = bt.indicators.SMA(self.data.close, period=2)
        self.range_average = bt.indicators.SMA(self.data.high - self.data.low, period=3)
        self.addminperiod(3)

    def next(self):
        self.lines.signal[0] = self.average[0] + self.range_average[0]


class _ClockParityStrategy(bt.Strategy):
    def __init__(self):
        self.fast_average = bt.indicators.SMA(self.data0.close, period=3)
        self.slow_signal = _SlowSignal(self.data1)
        self.trace = []

    @staticmethod
    def _phase_value(line):
        return _finite_or_none(line)

    def _capture(self, phase):
        self.trace.append(
            (
                phase,
                len(self.data0),
                len(self.data1),
                len(self.fast_average),
                len(self.slow_signal),
                self._phase_value(self.fast_average),
                self._phase_value(self.slow_signal),
                self._phase_value(self.slow_signal.average),
                self._phase_value(self.slow_signal.range_average),
            )
        )

    def prenext(self):
        self._capture("prenext")

    def nextstart(self):
        self._capture("nextstart")

    def next(self):
        self._capture("next")

    def start(self):
        # Strategy owns an explicit prefiltered tuple; indicators use None and
        # resolve/filter their own data inputs in LineIterator._next().
        self.strategy_lineaction_datas_is_tuple = isinstance(self._lineaction_datas, tuple)

    def stop(self):
        self.final_state = (
            len(self.data0),
            len(self.data1),
            len(self.fast_average),
            len(self.slow_signal),
            len(self.slow_signal.average),
            len(self.slow_signal.range_average),
            self.slow_signal._clock is self.data1,
            self.slow_signal._resolved_secondary_clock is self.data1,
        )
        iterator_dict = object.__getattribute__(
            self.slow_signal.range_average, "__dict__"
        )
        self.indicator_lineaction_datas_defaulted = (
            "_lineaction_datas" in iterator_dict
            and iterator_dict["_lineaction_datas"] is None
        )


class _ActionInputStrategy(bt.Strategy):
    """Consume a LineActions instance passed as a Strategy data argument."""

    def __init__(self):
        self.values = []

    def start(self):
        self.has_prefiltered_action_input = (
            len(self._lineaction_datas) == 1
            and self._lineaction_datas[0] is self.datas[1]
        )

    def next(self):
        self.values.append(float(self.datas[1][0]))


class _TupleOnlyActionInputStrategy(_ActionInputStrategy):
    """Isolate the Strategy._next prefiltered tuple dispatch path."""

    def _next_strategy_lineactions(self):
        # Isolate the Strategy._next tuple path. This action is also visible
        # through self.datas and would otherwise be found by the separate
        # strategy-attribute LineActions scheduler.
        pass

class _IteratorNextProbe:
    _ltype = LineIterator.IndType
    _minperiod = 1

    def __init__(self, datas, lineaction_datas):
        self.datas = datas
        self._lineaction_datas = lineaction_datas
        self._lineiterators = {LineIterator.IndType: []}
        self.next_calls = 0
        self.notify_calls = 0

    def _clk_update(self):
        return 2

    def _factor_run_callback(self, callback, _phase, *args):
        return callback(*args)

    def _notify(self):
        self.notify_calls += 1

    def next(self):
        self.next_calls += 1

    def nextstart(self):
        self.next_calls += 1

    def prenext(self):
        self.next_calls += 1


def test_lineiterator_next_preserves_none_and_prefiltered_tuple_semantics(monkeypatch):
    class _FakeClock:
        def __len__(self):
            return 2

    class _FakeAction:
        def __init__(self, clock):
            self._clock = clock
            self.next_calls = 0

        def __len__(self):
            return 0

        def _next(self):
            self.next_calls += 1

    class _OrdinaryData:
        def __init__(self):
            self.next_calls = 0

        def _next(self):
            self.next_calls += 1

    monkeypatch.setattr(lineiterator_module, "LineActions", _FakeAction)
    clock = _FakeClock()

    action = _FakeAction(clock)
    ordinary = _OrdinaryData()
    fallback = _IteratorNextProbe([ordinary, action], None)
    LineIterator._next(fallback)
    assert action.next_calls == 1
    assert ordinary.next_calls == 0

    action = _FakeAction(clock)
    ordinary = _OrdinaryData()
    prefiltered = _IteratorNextProbe([ordinary], (action,))
    LineIterator._next(prefiltered)
    assert action.next_calls == 1
    assert ordinary.next_calls == 0

    action = _FakeAction(clock)
    prefiltered_empty = _IteratorNextProbe([action], ())
    LineIterator._next(prefiltered_empty)
    assert action.next_calls == 0


def _run_cerebro_action_input_strategy(strategy_cls):
    feed = _MemoryFeed(bars=_bars([10.0, 11.0, 12.0, 13.0], 60))
    action_input = feed.close + 10.0
    # Strategy treats constructor arguments exposing lines/datetime as data
    # inputs. Bind the action's datetime view to its source feed, as a
    # data-like LineActions input must do for the strategy clock contract.
    action_input.datetime = feed.datetime
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(feed)
    cerebro.addstrategy(strategy_cls, action_input)
    return cerebro.run()[0]


def test_cerebro_strategy_action_input_advances_from_prefiltered_tuple():
    strategy = _run_cerebro_action_input_strategy(_TupleOnlyActionInputStrategy)

    assert strategy.has_prefiltered_action_input
    assert strategy.values == [20.0, 21.0, 22.0, 23.0]


def test_cerebro_strategy_action_input_preserves_default_action_scheduler():
    strategy = _run_cerebro_action_input_strategy(_ActionInputStrategy)

    assert strategy.has_prefiltered_action_input
    assert strategy.values == [20.0, 21.0, 22.0, 23.0]


def test_lineiterator_next_supports_strategy_pickle_state_without_new_private_field():
    strategy = _run_cerebro_action_input_strategy(_ActionInputStrategy)

    # Strategy's existing reducer restores __dict__ state with object.__new__.
    # Removing only the newly introduced field models the corresponding older
    # saved state; the round trip proves that such a state is loadable today.
    strategy.__dict__.pop("_lineaction_datas")
    restored = pickle.loads(pickle.dumps(strategy))
    assert "_lineaction_datas" not in restored.__dict__

    previous_callback_count = len(restored.values)
    LineIterator._next(restored)
    assert len(restored.values) == previous_callback_count + 1


def _run_clock_parity_strategy(runonce, monkeypatch):
    fast_bars = _bars([10.0 + index * 0.1 for index in range(24)], 60)
    slow_bars = _bars([10.0, 11.0, 13.0, 12.0, 15.0, 20.0], 240)
    missing_attribute_probes = [0]
    probe_active = [True]
    original_getattr = LineSeries.__getattr__

    def counted_getattr(self, name):
        if probe_active[0] and name == "_lineaction_datas":
            missing_attribute_probes[0] += 1
        return original_getattr(self, name)

    monkeypatch.setattr(LineSeries, "__getattr__", counted_getattr)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(_MemoryFeed(bars=fast_bars), name="fast")
    cerebro.adddata(_MemoryFeed(bars=slow_bars), name="slow")
    cerebro.addstrategy(_ClockParityStrategy)
    try:
        strategy = cerebro.run()[0]
    finally:
        probe_active[0] = False

    return strategy, missing_attribute_probes[0]


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_lineiterator_lineaction_default_and_full_multidata_sequence(runonce, monkeypatch):
    strategy, missing_attribute_probes = _run_clock_parity_strategy(runonce, monkeypatch)

    assert missing_attribute_probes == 0
    assert strategy.strategy_lineaction_datas_is_tuple
    assert strategy.indicator_lineaction_datas_defaulted
    assert len(strategy.trace) == 24
    assert strategy.final_state == (24, 6, 24, 6, 6, 6, True, True)


def test_lineiterator_lineaction_full_multidata_sequence_matches_run_modes(monkeypatch):
    runnext, runnext_probes = _run_clock_parity_strategy(False, monkeypatch)
    runonce, runonce_probes = _run_clock_parity_strategy(True, monkeypatch)

    assert runnext.trace == runonce.trace
    assert runnext.final_state == runonce.final_state == (24, 6, 24, 6, 6, 6, True, True)
    assert runnext_probes == runonce_probes == 0
