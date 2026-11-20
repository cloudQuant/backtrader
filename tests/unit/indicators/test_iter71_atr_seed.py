"""Regression coverage for ATR's first valid true-range seed."""

import math

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind


def _run_atr(period, high, low, close, runonce):
    """Return the complete ATR line for synthetic OHLC data."""
    size = len(close)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1.0] * size,
            "openinterest": [0.0] * size,
        },
        index=pd.date_range("2020-01-01", periods=size, freq="D"),
    )
    values = {}

    class ATRProbeStrategy(bt.Strategy):
        def __init__(self):
            self.atr = btind.ATR(self.data, period=period)

        def stop(self):
            values["atr"] = [float(value) for value in self.atr.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ATRProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return values["atr"]


def _expected_atr(period, high, low, close):
    """Build a small reference series using prior-close true ranges."""
    result = [float("nan")] * len(close)
    if len(close) <= period:
        return result

    true_ranges = [
        max(high[index], close[index - 1]) - min(low[index], close[index - 1])
        for index in range(1, len(close))
    ]
    previous = sum(true_ranges[:period]) / period
    result[period] = previous
    alpha = 1.0 / period
    alpha1 = 1.0 - alpha
    for index in range(period + 1, len(close)):
        previous = previous * alpha1 + true_ranges[index - 1] * alpha
        result[index] = previous
    return result


@pytest.mark.parametrize(
    ("period", "high", "low", "close"),
    [
        pytest.param(
            3,
            [101.0, 103.0, 102.0, 105.0, 108.0, 107.0],
            [99.0, 98.0, 99.0, 103.0, 104.0, 105.0],
            [100.0, 101.0, 100.0, 104.0, 106.0, 106.0],
            id="upward-gap-on-seed-bar",
        ),
        pytest.param(
            3,
            [111.0, 110.0, 112.0, 107.0, 109.0, 110.0],
            [109.0, 108.0, 109.0, 105.0, 106.0, 105.0],
            [110.0, 109.0, 110.0, 106.0, 108.0, 107.0],
            id="downward-gap-on-seed-bar",
        ),
        pytest.param(
            3,
            [101.0, 103.0, 105.0, 106.0, 108.0, 105.0],
            [99.0, 100.0, 101.0, 103.0, 104.0, 102.0],
            [100.0, 101.0, 104.0, 105.0, 106.0, 104.0],
            id="no-gap-on-seed-bar",
        ),
        pytest.param(
            1,
            [101.0, 103.0, 102.0, 100.0],
            [99.0, 102.0, 98.0, 97.0],
            [100.0, 102.0, 99.0, 98.0],
            id="period-one",
        ),
        pytest.param(
            5,
            [101.0, 103.0, 104.0, 103.0, 106.0, 112.0, 110.0, 111.0],
            [99.0, 100.0, 101.0, 100.0, 100.0, 109.0, 107.0, 108.0],
            [100.0, 101.0, 102.0, 101.0, 103.0, 110.0, 108.0, 109.0],
            id="period-five-seed-gap",
        ),
    ],
)
def test_atr_nextstart_seed_matches_once_over_full_sequence(
    period, high, low, close
):
    """Seed gaps and later smoothing agree across next and once execution."""
    expected = _expected_atr(period, high, low, close)
    runnext_values = _run_atr(period, high, low, close, runonce=False)
    runonce_values = _run_atr(period, high, low, close, runonce=True)

    assert len(runnext_values) == len(runonce_values) == len(expected)
    for actual, batch in zip(runnext_values, runonce_values):
        assert math.isnan(actual) == math.isnan(batch)
    for actual, batch, reference in zip(runnext_values, runonce_values, expected):
        if math.isnan(reference):
            assert math.isnan(actual)
            assert math.isnan(batch)
        else:
            assert actual == pytest.approx(reference)
            assert batch == pytest.approx(reference)


@pytest.mark.parametrize(
    ("period", "length"),
    [(1, 1), (3, 1), (3, 2), (3, 3), (5, 4), (5, 5)],
)
def test_atr_short_history_runonce_runnext_parity(period, length):
    """Histories shorter than the first valid index stay all NaN in both modes."""
    close = [100.0 + index for index in range(length)]
    high = [value + 1.0 for value in close]
    low = [value - 1.0 for value in close]

    runnext_values = _run_atr(period, high, low, close, runonce=False)
    runonce_values = _run_atr(period, high, low, close, runonce=True)

    assert len(runnext_values) == len(runonce_values) == length
    assert all(math.isnan(value) for value in runnext_values)
    assert all(math.isnan(value) for value in runonce_values)
