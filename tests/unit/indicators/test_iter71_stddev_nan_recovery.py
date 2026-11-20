"""Runonce parity for exponentially smoothed standard deviation with gaps."""

from __future__ import annotations

import datetime as dt
import math

import backtrader as bt
import pytest


class _SyntheticValues(bt.feed.DataBase):
    """In-memory values for exercising real Cerebro indicator paths."""

    params = (("input_values", ()),)

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        if self._index >= len(self.p.input_values):
            return False

        value = float(self.p.input_values[self._index])
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


class _StandardDeviationProbe(bt.Strategy):
    params = (("period", 3), ("movav", bt.indicators.MovAv.Exponential))

    def __init__(self):
        self.deviation = bt.indicators.StandardDeviation(
            self.data.close,
            period=self.p.period,
            movav=self.p.movav,
        )

    def stop(self):
        self.result = list(self.deviation.lines.stddev.array)


def _run_stddev(values, *, runonce, period, movav):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(_SyntheticValues(input_values=values), name="SYNTH")
    cerebro.addstrategy(_StandardDeviationProbe, period=period, movav=movav)
    (strategy,) = cerebro.run(runonce=runonce, preload=True)
    return strategy.result


def _assert_matches_next_contract(actual, expected, values, period):
    assert len(actual) == len(expected) == len(values)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        window_start = max(0, index - period + 1)
        window = values[window_start : index + 1]
        should_be_nan = index < period - 1 or any(math.isnan(value) for value in window)
        assert math.isnan(actual_value) is should_be_nan
        assert math.isnan(expected_value) is should_be_nan
        if not should_be_nan:
            assert math.isclose(actual_value, expected_value, rel_tol=1e-13, abs_tol=1e-13)


@pytest.mark.parametrize(
    "movav",
    (bt.indicators.MovAv.Exponential, bt.indicators.MovAv.Smoothed),
    ids=("ema", "smma"),
)
@pytest.mark.parametrize(
    ("period", "leading_nan_count"),
    ((3, 1), (3, 2), (5, 3)),
    ids=("one-delayed-window", "two-delayed-windows", "longer-lookback"),
)
def test_alpha_stddev_once_seeds_on_first_complete_finite_window(
    movav, period, leading_nan_count
):
    values = [math.nan] * leading_nan_count + [float(value) for value in range(1, 9)]

    runnext = _run_stddev(values, runonce=False, period=period, movav=movav)
    runonce = _run_stddev(values, runonce=True, period=period, movav=movav)
    first_valid = leading_nan_count + period - 1

    _assert_matches_next_contract(runonce, runnext, values, period)
    assert all(math.isnan(value) for value in runonce[:first_valid])
    assert all(math.isfinite(value) for value in runonce[first_valid:])


@pytest.mark.parametrize(
    "movav",
    (bt.indicators.MovAv.Exponential, bt.indicators.MovAv.Smoothed),
    ids=("ema", "smma"),
)
@pytest.mark.parametrize(
    "values",
    (
        (1.0, 2.0, 3.0, 4.0, math.nan, 6.0, 7.0, 8.0, 9.0),
        (1.0, 2.0, 3.0, math.nan, 5.0, 6.0, 7.0, math.nan, 9.0, 10.0, 11.0, 12.0),
    ),
    ids=("single-interior-gap", "multiple-interior-gaps"),
)
def test_alpha_stddev_once_matches_next_across_rolling_nan_gaps(movav, values):
    period = 3
    runnext = _run_stddev(values, runonce=False, period=period, movav=movav)
    runonce = _run_stddev(values, runonce=True, period=period, movav=movav)

    _assert_matches_next_contract(runonce, runnext, values, period)
