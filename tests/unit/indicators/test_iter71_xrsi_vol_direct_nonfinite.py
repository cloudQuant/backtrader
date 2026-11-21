"""XRSI direct colors must not turn unavailable comparisons into signals."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.xrsi_histogram_vol_direct_indicator import (
    XRSIHistogramVolDirectIndicator,
)
from tests.functional.strategies.mean_reversion.test_0079_0257_exp_xrsi_histogram_vol_direct import (
    ExpXRSIHistogramVolDirectStrategy,
)


def _frame(count=100, *, missing=None, every="min"):
    close = [100 + i * 0.2 + 3 * math.sin(i * 0.4) for i in range(count)]
    volume = [10.0] * count
    if missing == "close":
        close[30] = math.nan
    elif missing == "volume":
        volume[30] = math.nan
    return pd.DataFrame(
        {"open": close, "high": [v + 1 for v in close],
         "low": [v - 1 for v in close], "close": close, "volume": volume},
        index=pd.date_range("2020-01-01", periods=count, freq=every),
    )


def _run(frame, once, primary=None):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = XRSIHistogramVolDirectIndicator(self.datas[-1], rsi_period=4, ma_length=3)

    c = bt.Cerebro(runonce=once, preload=True, stdstats=False)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Strategy)
    return c.run()[0].ind


def _assert_validity(ind):
    assert ind._minperiod == 7
    value, color = list(ind.value.array), list(ind.color_state.array)
    assert len(value) == len(color)
    assert all(math.isnan(v) for v in color[:7])
    for index in range(7, len(value)):
        if math.isfinite(value[index]) and math.isfinite(value[index - 1]):
            assert color[index] == (0.0 if value[index] >= value[index - 1] else 1.0)
        else:
            assert math.isnan(color[index])
    return value, color


def _reference_values(frame):
    prices, volumes = list(frame.close), list(frame.volume)
    history = []
    result = [math.nan] * 6
    for i in range(6, len(prices)):
        changes = [prices[i - k] - prices[i - k - 1] for k in range(4)]
        gains = sum(max(change, 0.0) for change in changes) / 4
        losses = sum(max(-change, 0.0) for change in changes) / 4
        rsi = 100.0 if losses <= 1e-12 and gains > 0 else (
            50.0 if losses <= 1e-12 else 100.0 - 100.0 / (1.0 + gains / losses)
        )
        history.append((rsi - 50.0) * volumes[i])
        result.append(sum(history[-3:]) / len(history[-3:]))
    return result


@pytest.mark.parametrize("volume,previous", [(math.inf, 1.0), (-math.inf, 1.0),
                                              (10.0, math.inf), (10.0, -math.inf)])
def test_infinite_current_or_previous_cannot_create_a_color(volume, previous):
    class Owner:
        def __len__(self):
            return 2

    class Data(SimpleNamespace):
        def __len__(self):
            return 2

    owner = Owner()
    owner.p = SimpleNamespace(rsi_period=1, ma_length=1)
    owner.data = Data(close=[100.0, 99.0], volume=[volume])
    owner.lines = SimpleNamespace(value=[0.0, previous], color_state=[0.0])
    owner._scaled_history = []
    owner._last_source_length = None
    XRSIHistogramVolDirectIndicator.next(owner)
    assert math.isnan(owner.lines.color_state[0])


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_finite_series_matches_independent_rsi_smoothing_and_color(once):
    frame = _frame()
    ind = _run(frame, once)
    value, color = _assert_validity(ind)
    for i, expected in enumerate(_reference_values(frame)[6:], start=6):
        assert value[i] == pytest.approx(expected)
    assert {v for v in color[7:] if math.isfinite(v)} == {0.0, 1.0}


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
@pytest.mark.parametrize("missing,recovery", [("close", 37), ("volume", 33)])
def test_missing_window_and_first_recovery_never_make_a_color(once, missing, recovery):
    value, color = _assert_validity(_run(_frame(missing=missing), once))
    assert color[29] == 0.0
    assert all(math.isnan(v) for v in value[30:recovery])
    assert all(math.isnan(v) for v in color[30:recovery + 1])
    assert math.isfinite(value[recovery])
    assert color[recovery + 1] in (0.0, 1.0)


@pytest.mark.parametrize("missing", ("close", "volume"))
def test_entire_output_is_equivalent_across_execution_modes(missing):
    results = [_run(_frame(missing=missing), once) for once in (False, True)]
    for first, second in zip(results[0].lines, results[1].lines):
        assert len(first.array) == len(second.array) == 100
        for a, b in zip(first.array, second.array):
            if math.isnan(a):
                assert math.isnan(b)
            else:
                assert b == pytest.approx(a)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_short_history_stays_unpublished(once):
    ind = _run(_frame(6), once)
    assert ind._minperiod == 7
    assert all(math.isnan(v) for v in ind.value.array)
    assert all(math.isnan(v) for v in ind.color_state.array)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_secondary_clock_preserves_missing_and_recovery(once):
    signal = _frame(missing="close", every="3min")
    ind = _run(signal, once, primary=_frame(300))
    value, color = _assert_validity(ind)
    assert len(value) == len(signal)
    assert color[29] == 0.0 and math.isnan(color[30])
    recovery = next(i for i in range(31, len(value))
                    if math.isfinite(value[i]) and not math.isfinite(value[i - 1]))
    assert math.isnan(color[recovery])
    for actual, expected in zip(value, _reference_values(signal)):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_public_strategy_does_not_submit_missing_or_first_recovery_flip(once):
    class Trace(ExpXRSIHistogramVolDirectStrategy):
        def __init__(self):
            super().__init__()
            self.submissions = []

        def _submit_entry(self, side, reason):
            self.submissions.append((len(self.signal_data) - 1, side))

    frame = _frame(missing="close")
    c = bt.Cerebro(runonce=once, preload=True, stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Trace, rsi_period=4, ma_length=3)
    strategy = c.run()[0]
    assert strategy.submissions
    assert all(not 30 <= index <= 37 for index, _ in strategy.submissions)
    assert strategy.indicator.color_state.array[29] == 0.0
    assert math.isnan(strategy.indicator.color_state.array[30])


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_public_strategy_entry_requests_on_finite_data_match_reference(once):
    class Trace(ExpXRSIHistogramVolDirectStrategy):
        def __init__(self):
            super().__init__()
            self.submissions = []

        def _submit_entry(self, side, reason):
            self.submissions.append((len(self.signal_data) - 1, side))

    frame = _frame()
    reference = _reference_values(frame)
    colors = [math.nan] * 7 + [
        0.0 if reference[i] >= reference[i - 1] else 1.0
        for i in range(7, len(reference))
    ]
    expected = []
    for index in range(8, len(colors)):
        if colors[index - 1] == 1.0 and colors[index] == 0.0:
            expected.append((index, "long"))
        elif colors[index - 1] == 0.0 and colors[index] == 1.0:
            expected.append((index, "short"))

    c = bt.Cerebro(runonce=once, preload=True, stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Trace, rsi_period=4, ma_length=3)
    actual = c.run()[0].submissions
    assert expected
    assert actual == expected


def test_replay_revisions_classify_only_finite_current_and_previous():
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = XRSIHistogramVolDirectIndicator(self.data, rsi_period=4, ma_length=3)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), float(self.ind.value[0]),
                              float(self.ind.value[-1]), float(self.ind.color_state[0])))

    frame = _frame(180)
    frame.loc[frame.index[100], "volume"] = math.nan
    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    c.replaydata(bt.feeds.PandasData(dataname=frame), timeframe=bt.TimeFrame.Minutes, compression=5)
    c.addstrategy(Strategy)
    rows = c.run()[0].rows
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    assert any(not math.isfinite(cur) or not math.isfinite(prev) for _, cur, prev, _ in rows)
    assert any(math.isfinite(cur) and math.isfinite(prev) for _, cur, prev, _ in rows)
    for _, cur, prev, color in rows:
        if math.isfinite(cur) and math.isfinite(prev):
            assert color == (0.0 if cur >= prev else 1.0)
        else:
            assert math.isnan(color)


def test_replay_every_revision_matches_independent_finalized_bar_reference():
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = XRSIHistogramVolDirectIndicator(self.data, rsi_period=4, ma_length=3)
            self.raw_by_length = {}
            self.checked = []

        def next(self):
            count = len(self.data)
            changes = [float(self.data.close[-i]) - float(self.data.close[-i - 1])
                       for i in range(4)]
            gains = sum(max(change, 0.0) for change in changes) / 4
            losses = sum(max(-change, 0.0) for change in changes) / 4
            rsi = 100.0 if losses <= 1e-12 and gains > 0 else (
                50.0 if losses <= 1e-12 else 100.0 - 100.0 / (1.0 + gains / losses)
            )
            self.raw_by_length[count] = (rsi - 50.0) * float(self.data.volume[0])
            expected = [self.raw_by_length[n] for n in range(max(7, count - 2), count + 1)]
            value = sum(expected) / len(expected)
            assert float(self.ind.value[0]) == pytest.approx(value)
            self.checked.append(count)

    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    c.replaydata(bt.feeds.PandasData(dataname=_frame(180)),
                 timeframe=bt.TimeFrame.Minutes, compression=5)
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert len(strategy.checked) > 100
    assert any(a == b for a, b in zip(strategy.checked, strategy.checked[1:]))


def test_failed_same_bar_revision_rolls_back_and_can_retry():
    failure = RuntimeError("synthetic output failure")

    class FailOnce:
        _is_datetime_line = False

        def __init__(self):
            self.armed = False

        def updateminperiod(self, minperiod):
            pass

        def __setitem__(self, index, value):
            if self.armed:
                self.armed = False
                raise failure

    class Indicator(XRSIHistogramVolDirectIndicator):
        def __init__(self):
            super().__init__()
            self.binding = FailOnce()
            self.lines.color_state.addbinding(self.binding)
            self.calls_at_target = 0
            self.rolled_back = False

        def next(self):
            if len(self.data) == 10:
                self.calls_at_target += 1
                if self.calls_at_target == 2:
                    before = (list(self._scaled_history), self._last_source_length,
                              float(self.value[0]), float(self.color_state[0]))
                    self.binding.armed = True
                    with pytest.raises(RuntimeError) as caught:
                        super().next()
                    assert caught.value is failure
                    assert (self._scaled_history, self._last_source_length,
                            float(self.value[0]), float(self.color_state[0])) == before
                    self.rolled_back = True
            super().next()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = Indicator(self.data, rsi_period=4, ma_length=3)
            self.raw_by_length = {}
            self.checked = []

        def next(self):
            count = len(self.data)
            changes = [float(self.data.close[-i]) - float(self.data.close[-i - 1])
                       for i in range(4)]
            gain = sum(max(change, 0.0) for change in changes) / 4
            loss = sum(max(-change, 0.0) for change in changes) / 4
            rsi = 100.0 if loss <= 1e-12 and gain > 0 else (
                50.0 if loss <= 1e-12 else 100.0 - 100.0 / (1.0 + gain / loss)
            )
            self.raw_by_length[count] = (rsi - 50.0) * float(self.data.volume[0])
            expected = [self.raw_by_length[n] for n in range(max(7, count - 2), count + 1)]
            assert float(self.ind.value[0]) == pytest.approx(sum(expected) / len(expected))
            self.checked.append(count)

    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    c.replaydata(bt.feeds.PandasData(dataname=_frame(140)),
                 timeframe=bt.TimeFrame.Minutes, compression=5)
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert strategy.ind.rolled_back
    assert max(strategy.checked) > 10
