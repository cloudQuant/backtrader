"""Cerebro minperiod and output-line coverage for ColorBBCandles (R71-035)."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _required_minperiod(period):
    """The MA/stddev need ``period`` bars; the indicator keeps its +5 guard."""
    return max(period, period + 5)


def _reference_ema(values, period):
    result = [float("nan")] * len(values)
    if len(values) < period:
        return result

    previous = sum(values[:period]) / period
    result[period - 1] = previous
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        previous = previous * (1.0 - alpha) + values[index] * alpha
        result[index] = previous
    return result


def _reference_color_bb(closes, period):
    """Calculate EMA center, population bands, and the state thresholds."""
    mid = _reference_ema(closes, period)
    state = [float("nan")] * len(closes)
    first_state = _required_minperiod(period) - 1
    deviations = (1.0, 1.5, 2.0, 2.5, 3.0)

    for index in range(first_state, len(closes)):
        window = closes[index - period + 1 : index + 1]
        mean = sum(window) / period
        meansq = sum(value * value for value in window) / period
        stdev = math.sqrt(max(0.0, abs(meansq - mean * mean)))
        price = closes[index]
        state[index] = 5.0
        for level in range(len(deviations) - 1, -1, -1):
            deviation = deviations[level]
            if price > mid[index] + stdev * deviation:
                state[index] = float(6 + level)
                break
        else:
            for level in range(len(deviations) - 1, -1, -1):
                deviation = deviations[level]
                if price < mid[index] - stdev * deviation:
                    state[index] = float(4 - level)
                    break

    return mid, state


def _run_color_bb(closes, *, period, runonce):
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    result = {"next_indices": []}

    class ColorBBCandlesProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.ColorBBCandlesIndicator(
                self.data, period=period
            )

        def next(self):
            result["next_indices"].append(len(self.data) - 1)

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["state"] = [float(value) for value in self.indicator.state.array]
            result["price_line"] = [
                float(value) for value in self.indicator.price_line.array
            ]
            result["mid"] = [float(value) for value in self.indicator.mid.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ColorBBCandlesProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_nan_aware_series(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
@pytest.mark.parametrize("length", (104, 105, 106))
def test_color_bb_candles_default_minperiod_and_short_history(length, runonce):
    """Period-100 source windows plus the five-bar guard require 105 bars."""
    closes = [100.0 + 0.1 * index for index in range(length)]
    result = _run_color_bb(closes, period=100, runonce=runonce)

    assert result["minperiod"] == _required_minperiod(100) == 105
    assert result["next_indices"] == list(range(104, length))
    _assert_nan_aware_series(result["price_line"], closes)

    expected_mid, expected_state = _reference_color_bb(closes, period=100)
    _assert_nan_aware_series(result["mid"], expected_mid)
    _assert_nan_aware_series(result["state"], expected_state)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
def test_color_bb_candles_full_state_sequence_matches_independent_reference(
    runonce,
):
    closes = [
        10.0, 12.0, 9.0, 15.0, 13.0, 20.0, 7.0, 18.0, 11.0, 25.0,
        8.0, 22.0, 14.0, 30.0, 6.0, 19.0, 5.0, 24.0, 12.0, 27.0,
    ]
    period = 5
    result = _run_color_bb(closes, period=period, runonce=runonce)
    expected_mid, expected_state = _reference_color_bb(closes, period)

    assert result["minperiod"] == _required_minperiod(period) == 10
    assert result["next_indices"] == list(range(9, len(closes)))
    _assert_nan_aware_series(result["price_line"], closes)
    _assert_nan_aware_series(result["mid"], expected_mid)
    _assert_nan_aware_series(result["state"], expected_state)
