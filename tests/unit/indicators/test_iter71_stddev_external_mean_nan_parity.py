"""External-mean missing values must have the same run modes."""

from __future__ import annotations

import datetime as dt
import math

import backtrader as bt
import pytest


class _Values(bt.feed.DataBase):
    params = (("data_values", ()),)

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        if self._index >= len(self.p.data_values):
            return False

        value = float(self.p.data_values[self._index])
        moment = dt.datetime(2026, 1, 1) + dt.timedelta(days=self._index)
        self.lines.datetime[0] = bt.date2num(moment)
        self.lines.open[0] = value
        self.lines.high[0] = value
        self.lines.low[0] = value
        self.lines.close[0] = value
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


class _Probe(bt.Strategy):
    params = (("period", 3), ("movav", bt.indicators.MovAv.Exponential))

    def __init__(self):
        self.deviation = _TwoDataStandardDeviation(
            self.data0,
            self.data1,
            period=self.p.period,
            movav=self.p.movav,
        )

    def stop(self):
        self.result = list(self.deviation.stddev.array)
        self.used_external_mean = self.deviation._use_external_mean


class _TwoDataStandardDeviation(bt.indicators.StandardDeviation):
    """Expose the indicator's documented two-data branch for this probe."""

    _mindatas = 2


def _run(values, means, *, runonce, period=3, movav=bt.indicators.MovAv.Exponential):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(_Values(data_values=values), name="VALUE")
    cerebro.adddata(_Values(data_values=means), name="MEAN")
    cerebro.addstrategy(_Probe, period=period, movav=movav)
    (strategy,) = cerebro.run(runonce=runonce, preload=True)
    return strategy.result, strategy.used_external_mean


def _assert_same_float_sequence(left, right):
    assert len(left) == len(right)
    for index, (left_value, right_value) in enumerate(zip(left, right)):
        if math.isnan(left_value):
            assert math.isnan(right_value), index
        else:
            assert math.isclose(
                left_value, right_value, rel_tol=1e-13, abs_tol=1e-13
            ), (index, left_value, right_value)


@pytest.mark.parametrize(
    "means",
    (
        (10.0, math.nan, 12.0, 13.0, 14.0, 15.0, 16.0),
        (10.0, 11.0, 12.0, math.nan, 14.0, 15.0, 16.0),
        (10.0, 11.0, 12.0, 13.0, math.nan, 15.0, 16.0),
        (10.0, 11.0, 12.0, math.inf, 14.0, 15.0, 16.0),
        (10.0, 11.0, 12.0, -math.inf, 14.0, 15.0, 16.0),
    ),
    ids=(
        "warmup-mean-nan",
        "interior-mean-nan",
        "late-mean-nan",
        "positive-infinity",
        "negative-infinity",
    ),
)
@pytest.mark.parametrize(
    "movav",
    (
        bt.indicators.MovAv.Simple,
        bt.indicators.MovAv.Exponential,
        bt.indicators.MovAv.Smoothed,
    ),
    ids=("simple", "ema", "smma"),
)
def test_stddev_once_matches_next_with_external_mean_special_values(means, movav):
    values = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)

    runnext, next_uses_external_mean = _run(
        values, means, runonce=False, movav=movav
    )
    runonce, once_uses_external_mean = _run(
        values, means, runonce=True, movav=movav
    )

    assert next_uses_external_mean
    assert once_uses_external_mean
    _assert_same_float_sequence(runonce, runnext)
