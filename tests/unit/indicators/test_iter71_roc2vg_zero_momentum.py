"""ROC2's momentum branch remains subtraction even when its prior value is zero."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.roc2_vg_indicator import ROC2VGIndicator, _calc_roc


@pytest.mark.parametrize("current", [12.5, -4.0, 0.0, math.nan])
def test_momentum_zero_previous_is_subtraction(current):
    actual = _calc_roc(current, 0.0, 1)
    if math.isnan(current):
        assert math.isnan(actual)
    else:
        assert actual == current


@pytest.mark.parametrize("roc_type", [2, 3, 4, 5, 99])
@pytest.mark.parametrize("current", [12.5, 0.0, math.nan])
def test_ratio_zero_denominator_preserves_existing_projection(roc_type, current):
    assert _calc_roc(current, 0.0, roc_type) == 0.0


def _frame(values, replay=False):
    times = pd.date_range("2024-01-01 09:00", periods=len(values), freq="D")
    if replay:
        timestamps = [day + pd.Timedelta(hours=h) for day in times for h in (0, 1)]
        closes = [x for value in values for x in (value, value)]
    else:
        timestamps, closes = times, values
    return pd.DataFrame({name: closes for name in ("open", "high", "low", "close")},
                        index=timestamps)


@pytest.mark.parametrize("runonce", [False, True])
def test_cerebro_momentum_matches_difference_with_zero_and_missing(runonce):
    values = [100.0 + i * 0.5 for i in range(40)]
    values[12] = 0.0
    values[22] = math.nan
    values[30] = 0.0

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ROC2VGIndicator(self.data, roc_period1=2, roc_type1=1,
                                       roc_period2=5, roc_type2=1)

    engine = bt.Cerebro(runonce=runonce, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    engine.addstrategy(Probe)
    ind = engine.run()[0].ind
    for period, line in ((2, ind.roc1), (5, ind.roc2)):
        for index in range(ind._minperiod - 1, len(values)):
            expected = values[index] - values[index - period]
            actual = float(line.array[index])
            if math.isnan(expected):
                assert math.isnan(actual), index
            else:
                assert actual == pytest.approx(expected), index
    assert ind.roc1.array[14] == pytest.approx(values[14])
    assert ind.roc2.array[17] == pytest.approx(values[17])


def test_replay_each_revision_uses_visible_zero_and_missing_history():
    values = [100.0 + i * 0.5 for i in range(40)]
    values[12] = 0.0
    values[22] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ROC2VGIndicator(self.data, roc_period1=2, roc_type1=1,
                                       roc_period2=5, roc_type2=1)
            self.samples = []

        def next(self):
            current = float(self.data.close[0])
            expected = [current - float(self.data.close[-period]) for period in (2, 5)]
            actual = [float(self.ind.roc1[0]), float(self.ind.roc2[0])]
            self.samples.append((actual, expected))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=_frame(values, replay=True),
                               timeframe=bt.TimeFrame.Minutes, compression=60)
    engine.replaydata(feed, timeframe=bt.TimeFrame.Days)
    engine.addstrategy(Probe)
    samples = engine.run()[0].samples
    assert len(samples) > len(values)
    for actual, expected in samples:
        for x, y in zip(actual, expected):
            if math.isnan(y):
                assert math.isnan(x)
            else:
                assert x == pytest.approx(y)
