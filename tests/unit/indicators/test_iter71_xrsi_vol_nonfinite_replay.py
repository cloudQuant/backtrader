"""XRSI volume levels and colors under missing data and replay revisions."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.xrsi_histogram_vol_indicator import XRSIHistogramVolIndicator
from tests.functional.strategies.mean_reversion.test_0075_0251_exp_xrsi_histogram_vol import (
    ExpXRSIHistogramVolStrategy,
)


NAMES = ("value", "max_level", "up_level", "dn_level", "min_level", "color_state")


def _frame(count=100, missing=None, every="min"):
    close = [100 + i * .2 + 3 * math.sin(i * .4) for i in range(count)]
    volume = [10.0] * count
    if missing == "close":
        close[30] = math.nan
    if missing == "volume":
        volume[30] = math.nan
    return pd.DataFrame({"open": close, "high": [v + 1 for v in close],
                         "low": [v - 1 for v in close], "close": close, "volume": volume},
                        index=pd.date_range("2020-01-01", periods=count, freq=every))


def _raw(closes, volume):
    changes = [closes[-i - 1] - closes[-i - 2] for i in range(4)]
    gain = sum(max(v, 0.0) for v in changes) / 4
    loss = sum(max(-v, 0.0) for v in changes) / 4
    rsi = (100.0 if gain > 0 else 50.0) if loss <= 1e-12 else 100.0 - 100.0 / (1 + gain / loss)
    return (rsi - 50.0) * volume


def _expected(raw_history, volume_history):
    value = sum(raw_history[-3:]) / len(raw_history[-3:])
    avg = sum(volume_history[-3:]) / len(volume_history[-3:])
    levels = (17 * avg, 5 * avg, -5 * avg, -17 * avg)
    if not all(math.isfinite(x) for x in (value, *levels)):
        color = math.nan
    elif value > levels[0]:
        color = 0.0
    elif value > levels[1]:
        color = 1.0
    elif value < levels[3]:
        color = 4.0
    elif value < levels[2]:
        color = 3.0
    else:
        color = 2.0
    return (value, *levels, color)


def _assert_values(actual, expected):
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-10, abs=1e-10)


def _run(frame, once, primary=None):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = XRSIHistogramVolIndicator(self.datas[-1], rsi_period=4, ma_length=3)

    c = bt.Cerebro(runonce=once, preload=True, stdstats=False)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Strategy)
    return c.run()[0].ind


def _check_full_reference(frame, ind):
    assert ind._minperiod == 7
    assert all(math.isnan(value) for value in ind.color_state.array[:6])
    raw, volumes = [], []
    for index in range(6, len(frame)):
        vol = float(frame.volume.iloc[index])
        raw.append(_raw(list(frame.close.iloc[:index + 1]), vol))
        volumes.append(vol)
        _assert_values([getattr(ind.lines, name).array[index] for name in NAMES],
                       _expected(raw, volumes))


@pytest.mark.parametrize("volume", (math.inf, -math.inf))
def test_nonfinite_levels_do_not_project_a_neutral_or_directional_color(volume):
    class Data(SimpleNamespace):
        def __len__(self):
            return 2

    owner = SimpleNamespace(
        p=SimpleNamespace(rsi_period=1, ma_length=1, high_level2=17, high_level1=5,
                          low_level1=-5, low_level2=-17),
        data=Data(close=[100.0, 99.0], volume=[volume]),
        lines=SimpleNamespace(**{name: [0.0] for name in NAMES}),
        _scaled_history=[], _volume_history=[], _last_source_length=None,
    )
    XRSIHistogramVolIndicator.next(owner)
    assert math.isnan(owner.lines.color_state[0])


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
@pytest.mark.parametrize("missing", (None, "close", "volume"))
def test_complete_lines_match_independent_reference_and_missing_recovery(once, missing):
    frame = _frame(missing=missing)
    ind = _run(frame, once)
    _check_full_reference(frame, ind)
    if missing:
        assert ind.color_state.array[29] == 4.0
        assert math.isnan(ind.value.array[30])
        assert math.isnan(ind.color_state.array[30])
        recovery = 37 if missing == "close" else 33
        assert math.isfinite(ind.value.array[recovery])
        assert math.isfinite(ind.color_state.array[recovery])


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_short_history_does_not_publish(once):
    ind = _run(_frame(6), once)
    assert ind._minperiod == 7
    assert all(math.isnan(v) for line in ind.lines for v in line.array)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_secondary_clock_is_one_sample_per_source_bar(once):
    signal = _frame(missing="close", every="3min")
    ind = _run(signal, once, primary=_frame(300))
    assert len(ind.value.array) == len(signal)
    _check_full_reference(signal, ind)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_public_strategy_does_not_interpret_missing_or_first_recovery_as_signal(once):
    class Trace(ExpXRSIHistogramVolStrategy):
        def __init__(self):
            super().__init__()
            self.observations = []

        def next(self):
            if len(self.signal_data) >= 9:
                self.observations.append((len(self.signal_data) - 1, self._signal_state()))

    frame = _frame(missing="close")
    c = bt.Cerebro(runonce=once, preload=True, stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Trace, rsi_period=4, ma_length=3)
    strategy = c.run()[0]
    states = dict(strategy.observations)
    assert all(states[index] is None for index in range(30, 38))
    assert any(state is not None for _, state in strategy.observations)


def test_replay_every_revision_matches_independent_per_bar_windows():
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = XRSIHistogramVolIndicator(self.data, rsi_period=4, ma_length=3)
            self.raw = {}
            self.volume = {}
            self.checked = []

        def next(self):
            count = len(self.data)
            closes = [float(self.data.close[-i]) for i in range(4, -1, -1)]
            vol = float(self.data.volume[0])
            self.raw[count] = _raw(closes, vol)
            self.volume[count] = vol
            keys = range(max(7, count - 2), count + 1)
            expected = _expected([self.raw[k] for k in keys], [self.volume[k] for k in keys])
            _assert_values([float(getattr(self.ind.lines, name)[0]) for name in NAMES], expected)
            self.checked.append(count)

    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    c.replaydata(bt.feeds.PandasData(dataname=_frame(180)),
                 timeframe=bt.TimeFrame.Minutes, compression=5)
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert len(strategy.checked) > 100
    assert any(a == b for a, b in zip(strategy.checked, strategy.checked[1:]))


def test_failed_replay_revision_restores_lines_and_histories_before_retry():
    failure = RuntimeError("synthetic output failure")

    class FailOnce:
        _is_datetime_line = False

        def __init__(self):
            self.armed = False

        def updateminperiod(self, period):
            pass

        def __setitem__(self, index, value):
            if self.armed:
                self.armed = False
                raise failure

    class Indicator(XRSIHistogramVolIndicator):
        def __init__(self):
            super().__init__()
            self.binding = FailOnce()
            self.lines.color_state.addbinding(self.binding)
            self.target_calls = 0
            self.rolled_back = False

        def next(self):
            if len(self.data) == 10:
                self.target_calls += 1
                if self.target_calls == 2:
                    state = (list(self._scaled_history), list(self._volume_history),
                             self._last_source_length,
                             [float(getattr(self.lines, name)[0]) for name in NAMES])
                    self.binding.armed = True
                    with pytest.raises(RuntimeError) as caught:
                        super().next()
                    assert caught.value is failure
                    assert self._scaled_history == state[0]
                    assert self._volume_history == state[1]
                    assert self._last_source_length == state[2]
                    assert [float(getattr(self.lines, name)[0]) for name in NAMES] == state[3]
                    self.rolled_back = True
            super().next()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = Indicator(self.data, rsi_period=4, ma_length=3)
            self.raw, self.volume, self.checked = {}, {}, []

        def next(self):
            count = len(self.data)
            closes = [float(self.data.close[-i]) for i in range(4, -1, -1)]
            vol = float(self.data.volume[0])
            self.raw[count], self.volume[count] = _raw(closes, vol), vol
            keys = range(max(7, count - 2), count + 1)
            _assert_values([float(getattr(self.ind.lines, name)[0]) for name in NAMES],
                           _expected([self.raw[k] for k in keys], [self.volume[k] for k in keys]))
            self.checked.append(count)

    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    c.replaydata(bt.feeds.PandasData(dataname=_frame(140)),
                 timeframe=bt.TimeFrame.Minutes, compression=5)
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert strategy.ind.rolled_back
    assert max(strategy.checked) > 10
