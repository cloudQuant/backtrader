"""Linear-regression slope windows count replay revisions as one bar."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.linear_reg_slope_v2_indicator import (
    LinearRegSlopeV2Indicator,
)


PERIOD = 4
SHIFT = 1
MINPERIOD = PERIOD + SHIFT + 3


def _reference(closes):
    """SMA then least-squares endpoint at the indicator's configured shift."""
    smooth = [math.nan] * (PERIOD - 1)
    smooth += [sum(closes[i - PERIOD + 1 : i + 1]) / PERIOD
               for i in range(PERIOD - 1, len(closes))]
    slopes = [math.nan] * len(closes)
    for i in range(MINPERIOD + PERIOD - 2, len(closes)):
        ys = smooth[i - PERIOD + 1 : i + 1]
        mean_x = (PERIOD - 1) / 2.0
        mean_y = sum(ys) / PERIOD
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(ys))
        denominator = sum((x - mean_x) ** 2 for x in range(PERIOD))
        slope = numerator / denominator
        slopes[i] = mean_y + slope * ((PERIOD - 1 - SHIFT) - mean_x)
    trigger = [math.nan] * len(closes)
    for i in range(SHIFT, len(closes)):
        trigger[i] = 2 * slopes[i] - slopes[i - SHIFT]
    return slopes, trigger


def _frame(values, replay):
    days = pd.date_range('2024-01-01', periods=len(values), freq='D')
    if replay:
        times = [day + pd.Timedelta(hours=h) for day in days for h in (9, 10)]
        closes = [x for v in values for x in (v - 0.2, v)]
    else:
        times, closes = days, values
    return pd.DataFrame({name: closes for name in ('open', 'high', 'low', 'close')}, index=times)


def _run(values, *, replay=False, once=False, exactbars=0):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = LinearRegSlopeV2Indicator(self.data, sl_length=PERIOD, trigger_shift=SHIFT)
            self.prices = []
            self.samples = []

        def prenext(self):
            self._record()

        def nextstart(self):
            self._record()

        def next(self):
            self._record()

        def _record(self):
            if len(self.prices) == len(self.data):
                self.prices[-1] = float(self.data.close[0])
            else:
                self.prices.append(float(self.data.close[0]))
            self.samples.append((list(self.prices), float(self.ind.reg_slope[0]),
                                 float(self.ind.trigger[0])))

    c = bt.Cerebro(runonce=once, preload=not replay and not exactbars,
                   exactbars=exactbars, stdstats=False)
    feed = bt.feeds.PandasData(dataname=_frame(values, replay),
                               timeframe=bt.TimeFrame.Minutes if replay else bt.TimeFrame.Days,
                               compression=60 if replay else 1)
    if replay:
        c.replaydata(feed, timeframe=bt.TimeFrame.Days, compression=1)
    else:
        c.adddata(feed)
    c.addstrategy(Probe)
    return c.run()[0]


def _assert_value(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize('once', (False, True), ids=('next', 'once'))
@pytest.mark.parametrize('missing', (False, True), ids=('finite', 'missing'))
def test_independent_reference_and_missing_recovery(once, missing):
    values = [100 + i * .21 + math.sin(i * .41) * 4 for i in range(45)]
    if missing:
        values[20] = math.nan
    result = _run(values, once=once)
    slopes, triggers = _reference(values)
    assert result.ind._minperiod == MINPERIOD
    for i, (slope, trigger) in enumerate(zip(result.ind.reg_slope.array, result.ind.trigger.array)):
        _assert_value(slope, slopes[i])
        _assert_value(trigger, triggers[i])
    assert math.isfinite(result.ind.reg_slope.array[-1])


def test_bounded_history_matches_independent_reference():
    values = [100 + i * .21 + math.sin(i * .41) * 4 for i in range(45)]
    result = _run(values, exactbars=1)
    for prices, slope, trigger in result.samples:
        expected_slope, expected_trigger = _reference(prices)
        _assert_value(slope, expected_slope[-1])
        _assert_value(trigger, expected_trigger[-1])


def test_replay_each_update_and_finalized_bar_matches_independent_reference():
    values = [100 + i * .21 + math.sin(i * .41) * 4 for i in range(45)]
    result = _run(values, replay=True)
    assert len(result.samples) >= 2 * len(values) - 1
    for prices, slope, trigger in result.samples:
        expected_slope, expected_trigger = _reference(prices)
        _assert_value(slope, expected_slope[-1])
        _assert_value(trigger, expected_trigger[-1])
    slopes, triggers = _reference(values)
    for slope, trigger, expected_slope, expected_trigger in zip(
        result.ind.reg_slope.array, result.ind.trigger.array, slopes, triggers
    ):
        _assert_value(slope, expected_slope)
        _assert_value(trigger, expected_trigger)
