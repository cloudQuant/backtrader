"""R71-051: Average must use the same accurate window sum in both modes."""

from __future__ import annotations

import datetime as dt
import math

import backtrader as bt
import pytest


class _SyntheticValues(bt.feed.DataBase):
    """In-memory values for exercising the real Cerebro indicator paths."""

    params = (("input_values", ()), ("raw_close_infinities", False))

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
        if self.p.raw_close_infinities and math.isinf(value):
            # Exercise the existing read projection after bypassing the public
            # line setter, which normalizes infinities during ordinary input.
            self.lines.close.array[-1] = value
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


class _AverageProbe(bt.Strategy):
    params = (("period", 3),)

    def __init__(self):
        self.average = bt.indicators.Average(self.data.close, period=self.p.period)

    def stop(self):
        self.result = list(self.average.lines[0].array)


def _run_average(values, *, runonce, period=3, raw_close_infinities=False):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(
        _SyntheticValues(
            input_values=values,
            raw_close_infinities=raw_close_infinities,
        ),
        name="SYNTH",
    )
    cerebro.addstrategy(_AverageProbe, period=period)
    (strategy,) = cerebro.run(runonce=runonce, preload=True)
    return strategy.result


def _reference_average(values, period):
    result = []
    for end in range(len(values)):
        start = end - period + 1
        if start < 0:
            result.append(float("nan"))
        else:
            result.append(math.fsum(values[start : end + 1]) / period)
    return result


def _assert_float_sequences_equal(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == expected_value


def test_average_modes_match_fsum_for_catastrophic_cancellation():
    values = [1e16, 1.0, -1e16, 1e16, 1.0, -1e16]
    expected = _reference_average(values, period=3)

    runnext = _run_average(values, runonce=False)
    runonce = _run_average(values, runonce=True)

    _assert_float_sequences_equal(runnext, expected)
    _assert_float_sequences_equal(runonce, expected)
    _assert_float_sequences_equal(runonce, runnext)


def test_average_modes_match_nan_propagation_and_recovery():
    values = [1.0, math.nan, 3.0, 4.0, 5.0, 6.0]
    expected = _reference_average(values, period=3)

    runnext = _run_average(values, runonce=False)
    runonce = _run_average(values, runonce=True)

    _assert_float_sequences_equal(runnext, expected)
    _assert_float_sequences_equal(runonce, expected)
    assert math.isnan(runonce[2])
    assert math.isnan(runonce[3])
    assert runonce[4] == 4.0
    assert runonce[5] == 5.0


def test_average_modes_preserve_standard_infinity_line_projection():
    values = [1.0, math.inf, -math.inf, 2.0, 3.0]
    projected_values = [1.0, 0.0, 0.0, 2.0, 3.0]
    expected = _reference_average(projected_values, period=2)

    runnext = _run_average(values, runonce=False, period=2)
    runonce = _run_average(values, runonce=True, period=2)

    _assert_float_sequences_equal(runnext, expected)
    _assert_float_sequences_equal(runonce, expected)


def test_average_modes_preserve_raw_infinity_read_projection():
    values = [math.inf, -math.inf, 4.0, 5.0]
    projected_values = [0.0, 0.0, 4.0, 5.0]
    expected = _reference_average(projected_values, period=2)

    runnext = _run_average(
        values, runonce=False, period=2, raw_close_infinities=True
    )
    runonce = _run_average(
        values, runonce=True, period=2, raw_close_infinities=True
    )

    _assert_float_sequences_equal(runnext, expected)
    _assert_float_sequences_equal(runonce, expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "once"))
def test_average_finite_overflow_raises_the_same_exception_in_both_modes(runonce):
    values = [1e308, 1e308, -1e308]

    with pytest.raises(OverflowError, match="intermediate overflow in fsum"):
        _run_average(values, runonce=runonce, period=2)
