"""Regression coverage for FramaSeries recursive seeding (R71-033)."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.frama_series import (
    FramaLinesIndicator,
    FramaSeries,
)


_LONG_CLOSES = tuple(
    100.0 + ((index * 19) % 37) + math.sin(index / 3.0)
    for index in range(171)
)


def _bars(closes):
    """Build deterministic OHLC bars, retaining missing rows as missing."""
    opens = []
    highs = []
    lows = []
    for index, close in enumerate(closes):
        if not math.isfinite(float(close)):
            opens.append(float("nan"))
            highs.append(float("nan"))
            lows.append(float("nan"))
            continue

        open_ = float(close) + (0.7 if index % 2 else -0.4)
        opens.append(open_)
        highs.append(max(open_, float(close)) + 1.0 + (index % 3) * 0.1)
        lows.append(min(open_, float(close)) - 0.8 - (index % 4) * 0.1)

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": list(closes),
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )


def _reference_frama(values, period):
    """Calculate FRAMA with a rolling finite window and a finite-value seed."""
    period = max(int(period), 2)
    half = max(period // 2, 1)
    result = [float("nan")] * len(values)

    for index in range(period - 1, len(values)):
        window = [float(value) for value in values[index - period + 1 : index + 1]]
        if not all(math.isfinite(value) for value in window):
            continue

        first = window[:half]
        second = window[-half:]
        n1 = (max(first) - min(first)) / float(half)
        n2 = (max(second) - min(second)) / float(half)
        n3 = (max(window) - min(window)) / float(period)
        if n1 > 0.0 and n2 > 0.0 and n3 > 0.0:
            dimension = (math.log(n1 + n2) - math.log(n3)) / math.log(2.0)
        else:
            dimension = 1.0
        alpha = math.exp(-4.6 * (dimension - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)

        previous = result[index - 1]
        if not math.isfinite(previous):
            previous = window[-1]
        result[index] = alpha * window[-1] + (1.0 - alpha) * previous

    return result


def _run_frama(closes, period, runonce, indicator_type=FramaSeries):
    """Run one FrAMA indicator through a real Cerebro instance."""
    frame = _bars(closes)
    result = {}

    class FramaProbe(bt.Strategy):
        def __init__(self):
            self.frama = indicator_type(self.data, period=period)

        def stop(self):
            indicator = self.frama
            result["minperiod"] = indicator._minperiod
            if indicator_type is FramaSeries:
                result["frama"] = list(indicator.frama.array)
            else:
                result["lines"] = {
                    name: list(getattr(indicator.lines, name).array)
                    for name in ("o", "h", "l", "c", "color")
                }

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(FramaProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_same_values(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if math.isfinite(expected_value):
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_frama_series_171_bars_match_seeded_reference_in_both_modes(runonce):
    """A missing prior output seeds from the current bar, not NaN."""
    period = 14
    result = _run_frama(_LONG_CLOSES, period, runonce)
    expected = _reference_frama(_LONG_CLOSES, period)

    assert result["minperiod"] == period
    assert len(result["frama"]) == 171
    assert all(math.isnan(value) for value in result["frama"][: period - 1])
    assert all(math.isfinite(value) for value in result["frama"][period - 1 :])
    assert result["frama"][period - 1] == pytest.approx(_LONG_CLOSES[period - 1])
    _assert_same_values(result["frama"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize(
    "period,length,first_valid",
    ((5, 4, None), (5, 5, 4), (5, 6, 4), (1, 1, None), (1, 2, 1)),
)
def test_frama_series_respects_minperiod_boundary(
    runonce, period, length, first_valid
):
    """Short history stays NaN and the clamped period seeds on its exact bar."""
    closes = _LONG_CLOSES[:length]
    result = _run_frama(closes, period, runonce)
    effective_period = max(period, 2)

    assert result["minperiod"] == effective_period
    if first_valid is None:
        assert all(math.isnan(value) for value in result["frama"])
    else:
        assert all(math.isnan(value) for value in result["frama"][:first_valid])
        assert math.isfinite(result["frama"][first_valid])
        _assert_same_values(result["frama"], _reference_frama(closes, period))


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize(
    "period,length,first_valid",
    ((5, 6, None), (5, 7, 6), (5, 8, 6), (1, 2, None), (1, 3, 2)),
)
def test_frama_lines_indicator_respects_its_minperiod_boundary(
    runonce, period, length, first_valid
):
    """The OHLC wrapper waits for its own period+2 minimum before writing."""
    result = _run_frama(_LONG_CLOSES[:length], period, runonce, FramaLinesIndicator)

    assert result["minperiod"] == period + 2
    if first_valid is None:
        for line_values in result["lines"].values():
            assert all(math.isnan(value) for value in line_values)
        return

    for line_values in result["lines"].values():
        assert all(math.isnan(value) for value in line_values[:first_valid])
        assert math.isfinite(line_values[first_valid])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_frama_series_nan_input_invalidates_window_then_reseeds(runonce):
    """A source NaN stays missing through its rolling window and cannot seed."""
    period = 5
    closes = list(_LONG_CLOSES[:25])
    missing_index = 7
    closes[missing_index] = float("nan")
    result = _run_frama(closes, period, runonce)
    expected = _reference_frama(closes, period)

    assert all(
        math.isfinite(value)
        for value in result["frama"][period - 1 : missing_index]
    )
    assert all(
        math.isnan(value)
        for value in result["frama"][missing_index : missing_index + period]
    )
    assert math.isfinite(result["frama"][missing_index + period])
    _assert_same_values(result["frama"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_frama_lines_indicator_matches_four_series_and_preserves_missing_color(runonce):
    """The candle wrapper aligns its warmup and keeps color NaN when OHLC is missing."""
    period = 14
    closes = list(_LONG_CLOSES)
    result = _run_frama(closes, period, runonce, FramaLinesIndicator)
    frame = _bars(closes)
    first_valid = period + 1

    assert result["minperiod"] == period + 2
    expected = {
        name: _reference_frama(frame[column].tolist(), period)
        for name, column in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))
    }
    expected["color"] = [float("nan")] * len(closes)
    expected["h"] = [
        max(expected["h"][index], expected["o"][index], expected["c"][index])
        if all(math.isfinite(expected[name][index]) for name in ("o", "h", "c"))
        else float("nan")
        for index in range(len(closes))
    ]
    expected["l"] = [
        min(expected["l"][index], expected["o"][index], expected["c"][index])
        if all(math.isfinite(expected[name][index]) for name in ("o", "l", "c"))
        else float("nan")
        for index in range(len(closes))
    ]
    for index in range(first_valid, len(closes)):
        open_value = expected["o"][index]
        close_value = expected["c"][index]
        if math.isfinite(open_value) and math.isfinite(close_value):
            expected["color"][index] = 2.0 if open_value < close_value else (
                0.0 if open_value > close_value else 1.0
            )

    for line_values in expected.values():
        line_values[:first_valid] = [float("nan")] * first_valid
    for name in ("o", "h", "l", "c", "color"):
        _assert_same_values(result["lines"][name], expected[name])

    missing_index = 20
    closes[missing_index] = float("nan")
    missing_result = _run_frama(closes, period, runonce, FramaLinesIndicator)
    missing_start = max(missing_index, first_valid)
    missing_end = missing_index + period
    for name in ("o", "h", "l", "c", "color"):
        assert all(
            math.isnan(value)
            for value in missing_result["lines"][name][missing_start:missing_end]
        )
    assert all(
        math.isfinite(missing_result["lines"][name][missing_end])
        for name in ("o", "h", "l", "c")
    )
