"""Smoothed RVI's delayed-input window and existing zero projection."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _frame():
    count = 120
    close = [
        100.0 + i * 0.1 + 2.0 * math.sin(i * 0.21) + (i % 7) * 0.2
        for i in range(count)
    ]
    open_ = [value - math.sin(i * 0.57) * 1.4 for i, value in enumerate(close)]
    high = [max(a, b) + 0.8 + (i % 3) * 0.2 for i, (a, b) in enumerate(zip(open_, close))]
    low = [min(a, b) - 0.7 - (i % 4) * 0.1 for i, (a, b) in enumerate(zip(open_, close))]
    for values in (open_, high, low, close):
        values[70] = math.nan
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": [1000.0] * count},
        index=pd.date_range("2020-01-01", periods=count),
    )


def _run(runonce, frame):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.SmoothedRelativeVigorIndex(self.data, period=13)

        def stop(self):
            averages = [
                child
                for child in self.indicator._lineiterators[0]
                if isinstance(child, bt.indicators.SimpleMovingAverage)
            ]
            assert len(averages) == 2
            self.result = (
                self.indicator._minperiod,
                [list(child.data.array) for child in averages],
                [list(child.array) for child in averages],
                list(self.indicator.rvi.array),
                list(self.indicator.signal.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _assert_equal(actual, expected, *, start=0):
    assert len(actual) == len(expected)
    for index in range(start, len(actual)):
        got, want = actual[index], expected[index]
        if math.isnan(want):
            assert math.isnan(got), f"index {index}: expected NaN, got {got!r}"
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), f"index {index}"


def _weighted(values):
    return [math.nan] * 3 + [
        sum(weight * values[index - lag] for lag, weight in enumerate((1, 2, 2, 1))) / 6.0
        for index in range(3, len(values))
    ]


def _average(values, period):
    first = 3 + period - 1
    return [math.nan] * first + [
        math.fsum(values[index - period + 1 : index + 1]) / period
        for index in range(first, len(values))
    ]


def test_missing_ohlc_keeps_child_windows_and_current_zero_projection_in_both_modes():
    frame = _frame()
    runnext = _run(False, frame)
    runonce = _run(True, frame)
    assert runnext[0] == runonce[0] == 19

    numerator = [c - o for c, o in zip(frame["close"], frame["open"])]
    denominator = [h - low for h, low in zip(frame["high"], frame["low"])]
    weighted = [_weighted(numerator), _weighted(denominator)]
    averages = [_average(values, 13) for values in weighted]

    for result in (runnext, runonce):
        for actual, expected in zip(result[1], weighted):
            _assert_equal(actual, expected, start=3)
            assert all(math.isnan(actual[index]) for index in range(70, 74))
            assert math.isfinite(actual[74])
        for actual, expected in zip(result[2], averages):
            _assert_equal(actual, expected)
            assert all(math.isnan(actual[index]) for index in range(70, 86))
            assert math.isfinite(actual[86])

        # Current If behavior projects the unavailable averages to zero; it
        # does not claim that the published RVI preserves missingness.
        rvi, signal = result[3:]
        assert all(rvi[index] == 0.0 for index in range(70, 86))
        assert all(signal[index] == 0.0 for index in range(73, 86))
        for index in range(18, len(frame)):
            expected_signal = (
                rvi[index] + 2.0 * rvi[index - 1]
                + 2.0 * rvi[index - 2] + rvi[index - 3]
            ) / 6.0
            assert signal[index] == pytest.approx(expected_signal, rel=1e-12, abs=1e-12)

    for first, second in zip(runnext[1], runonce[1]):
        _assert_equal(first, second, start=18)
    for first, second in zip(runnext[2], runonce[2]):
        _assert_equal(first, second, start=18)
    _assert_equal(runnext[3], runonce[3], start=18)
    _assert_equal(runnext[4], runonce[4], start=18)
