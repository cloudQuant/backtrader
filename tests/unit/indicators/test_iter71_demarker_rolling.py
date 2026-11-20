"""Regression tests for DeMarkerRolling warmup and rolling values (R71-157)."""

import math

import backtrader as bt
import pandas as pd
import pytest


_KNOWN_HIGHS = (10.0, 12.0, 11.0, 15.0, 14.0, 13.0, 18.0, 17.0, 19.0, 18.0)
_KNOWN_LOWS = (8.0, 9.0, 7.0, 6.0, 8.0, 5.0, 7.0, 4.0, 5.0, 8.0)
_KNOWN_PERIOD3 = (
    float("nan"),
    float("nan"),
    float("nan"),
    2.0 / 3.0,
    4.0 / 7.0,
    0.5,
    5.0 / 8.0,
    5.0 / 11.0,
    0.7,
    0.4,
)


def _frame(highs, lows):
    return pd.DataFrame(
        {
            "open": [(high + low) / 2.0 for high, low in zip(highs, lows)],
            "high": highs,
            "low": lows,
            "close": [(high + low) / 2.0 for high, low in zip(highs, lows)],
            "volume": [1.0] * len(highs),
            "openinterest": [0.0] * len(highs),
        },
        index=pd.date_range("2024-01-01", periods=len(highs), freq="D"),
    )


def _run_demarker(highs, lows, *, period, runonce, upstream_period=None):
    result = {}

    class DeMarkerProbe(bt.Strategy):
        def __init__(self):
            self.demarker = bt.indicators.DeMarkerRollingIndicator(
                self.data, period=period
            )
            if upstream_period is not None:
                self.upstream = bt.indicators.SimpleMovingAverage(
                    self.demarker.lines.demarker, period=upstream_period
                )

        def stop(self):
            result["minperiod"] = self.demarker._minperiod
            result["demarker"] = [
                float(value) for value in self.demarker.lines.demarker.array
            ]
            result["dem"] = [float(value) for value in self.demarker.lines.dem.array]
            if upstream_period is not None:
                result["upstream_minperiod"] = self.upstream._minperiod
                result["upstream"] = [float(value) for value in self.upstream.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(highs, lows)))
    cerebro.addstrategy(DeMarkerProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _reference(highs, lows, period):
    """Calculate every result directly from the source OHLC window."""
    result = [float("nan")] * len(highs)
    for index in range(period, len(highs)):
        up_moves = []
        down_moves = []
        for current in range(index - period + 1, index + 1):
            high_delta = highs[current] - highs[current - 1]
            low_delta = lows[current - 1] - lows[current]
            up_moves.append(max(high_delta, 0.0))
            down_moves.append(max(low_delta, 0.0))

        up_sum = sum(up_moves)
        down_sum = sum(down_moves)
        denominator = up_sum + down_sum
        result[index] = 0.5 if denominator == 0.0 else up_sum / denominator
    return result


def _assert_series(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if math.isfinite(expected_value):
            assert actual_value == pytest.approx(expected_value)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_demarker_rolling_matches_independent_period3_values(runonce):
    result = _run_demarker(
        _KNOWN_HIGHS, _KNOWN_LOWS, period=3, runonce=runonce
    )

    assert result["minperiod"] == 4
    assert result["demarker"][: len(_KNOWN_PERIOD3)] == pytest.approx(
        _KNOWN_PERIOD3, nan_ok=True
    )
    _assert_series(result["dem"], _KNOWN_PERIOD3)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_demarker_rolling_period14_full_history_and_warmup(runonce):
    highs = [100.0 + ((index * 7) % 11) + index * 0.25 for index in range(42)]
    lows = [90.0 + ((index * 5) % 9) - index * 0.15 for index in range(42)]
    expected = _reference(highs, lows, period=14)
    result = _run_demarker(highs, lows, period=14, runonce=runonce)

    assert result["minperiod"] == 15
    assert all(math.isnan(value) for value in result["demarker"][:14])
    assert math.isfinite(result["demarker"][14])
    _assert_series(result["demarker"], expected)
    _assert_series(result["dem"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("bar_count", (3, 4))
def test_demarker_rolling_short_history_and_first_complete_window(
    runonce, bar_count
):
    highs = [10.0, 12.0, 11.0, 15.0][:bar_count]
    lows = [8.0, 9.0, 7.0, 6.0][:bar_count]
    result = _run_demarker(highs, lows, period=3, runonce=runonce)

    assert result["minperiod"] == 4
    if bar_count < 4:
        assert all(math.isnan(value) for value in result["demarker"])
        assert all(math.isnan(value) for value in result["dem"])
    else:
        assert result["demarker"][:-1] == pytest.approx(
            [float("nan")] * (bar_count - 1), nan_ok=True
        )
        assert result["demarker"][-1] == pytest.approx(2.0 / 3.0)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_demarker_rolling_minperiod_propagates_through_upstream_average(runonce):
    highs = list(_KNOWN_HIGHS) + [18.0] * 8
    lows = list(_KNOWN_LOWS) + [8.0] * 8
    result = _run_demarker(
        highs,
        lows,
        period=3,
        runonce=runonce,
        upstream_period=3,
    )
    source = _reference(highs, lows, period=3)
    expected = [float("nan")] * len(source)
    for index in range(5, len(source)):
        expected[index] = sum(source[index - 2 : index + 1]) / 3.0

    assert result["minperiod"] == 4
    assert result["upstream_minperiod"] == 6
    assert all(math.isnan(value) for value in result["upstream"][:5])
    _assert_series(result["demarker"], source)
    _assert_series(result["upstream"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_demarker_rolling_missing_ohlc_propagates_nan_then_recovers(runonce):
    highs = [100.0 + ((index * 7) % 11) for index in range(28)]
    lows = [90.0 + ((index * 5) % 9) for index in range(28)]
    highs[8] = float("nan")
    lows[17] = float("nan")
    expected = _reference(highs, lows, period=3)
    result = _run_demarker(highs, lows, period=3, runonce=runonce)

    _assert_series(result["demarker"], expected)
    _assert_series(result["dem"], expected)
    assert all(math.isnan(value) for value in result["demarker"][8:12])
    assert all(math.isfinite(value) for value in result["demarker"][12:17])
    assert all(math.isnan(value) for value in result["demarker"][17:21])
    assert math.isfinite(result["demarker"][21])
