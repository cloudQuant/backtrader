"""R71-033 regression coverage for VininITrendLRMAIndicator seeding."""

import math

import backtrader as bt
import pandas as pd
import pytest


_BAR_COUNT = 171
_LRMA_PERIOD = 13
_MA_PERIODS = tuple(3 + index * 10 for index in range(10))
_SMOOTH_PERIOD = 20
_MINPERIOD = _LRMA_PERIOD + max(_MA_PERIODS) + _SMOOTH_PERIOD + 5


def _close_values(count):
    return tuple(
        100.0 + index * 0.05 + 3.0 * math.sin(index * 0.31)
        + 1.2 * math.cos(index * 0.11)
        for index in range(count)
    )


_CLOSES = _close_values(_BAR_COUNT)


def _run_indicator(closes, *, runonce):
    """Run the production indicator through Cerebro and capture full lines."""
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2025-01-01", periods=len(closes), freq="D"),
    )
    captured = {}

    class IndicatorProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.VininITrendLRMAIndicator(self.data)

        def stop(self):
            captured["minperiod"] = self.indicator._minperiod
            captured["trend"] = [float(value) for value in self.indicator.trend.array]
            captured["lrma"] = [
                float(value) for value in self.indicator._lrma.lrma.array
            ]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(IndicatorProbe)
    cerebro.run(runonce=runonce, preload=True)
    return captured


def _reference_lrma(values, period):
    """Project an independent least-squares fit to each complete window."""
    result = [float("nan")] * len(values)
    xs = list(range(period))
    mean_x = sum(xs) / period
    denominator = sum((x - mean_x) ** 2 for x in xs)

    for end in range(period, len(values) + 1):
        window = values[end - period : end]
        if not all(math.isfinite(value) for value in window):
            continue
        mean_y = sum(window) / period
        numerator = sum(
            (x - mean_x) * (value - mean_y)
            for x, value in zip(xs, window)
        )
        slope = numerator / denominator if denominator else 0.0
        result[end - 1] = mean_y + slope * (period - 1 - mean_x)

    return result


def _reference_trend(closes):
    """Calculate the SMA fan score and its raw-seeded EMA recurrence."""
    lrma = _reference_lrma(closes, _LRMA_PERIOD)
    averages = []
    for period in _MA_PERIODS:
        average = [float("nan")] * len(closes)
        for end in range(period, len(closes) + 1):
            window = lrma[end - period : end]
            if all(math.isfinite(value) for value in window):
                average[end - 1] = sum(window) / period
        averages.append(average)

    trend = [float("nan")] * len(closes)
    previous = None
    alpha = 2.0 / (_SMOOTH_PERIOD + 1.0)
    for index in range(_MINPERIOD - 1, len(closes)):
        compared = [lrma[index]] + [average[index] for average in averages]
        if not all(math.isfinite(value) for value in compared):
            previous = None
            continue

        score = sum(1 if lrma[index] > average[index] else -1 for average in averages)
        raw = 100.0 * score / len(averages)
        previous = raw if previous is None else alpha * raw + (1.0 - alpha) * previous
        trend[index] = previous

    return lrma, trend


def _raw_score(lrma, index):
    """Compute the current fan score without using the trend recurrence."""
    values = []
    for period in _MA_PERIODS:
        window = lrma[index - period + 1 : index + 1]
        assert all(math.isfinite(value) for value in window)
        values.append(sum(window) / period)
    score = sum(1 if lrma[index] > value else -1 for value in values)
    return 100.0 * score / len(values)


def _assert_float_series(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), (
                f"bar {index}: expected NaN, got {actual_value!r}"
            )
        else:
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            ), f"bar {index}"


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_vinin_lrma_trend_matches_raw_seeded_reference_for_171_bars(runonce):
    """Both Cerebro modes emit the finite raw score as the first trend value."""
    result = _run_indicator(_CLOSES, runonce=runonce)
    expected_lrma, expected_trend = _reference_trend(_CLOSES)

    assert result["minperiod"] == _MINPERIOD == 131
    _assert_float_series(result["lrma"], expected_lrma)
    _assert_float_series(result["trend"], expected_trend)
    assert all(math.isnan(value) for value in result["trend"][: _MINPERIOD - 1])
    assert math.isfinite(result["lrma"][_MINPERIOD - 1])
    assert math.isfinite(result["trend"][_MINPERIOD - 1])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("bar_count, has_first_trend", ((130, False), (131, True)))
def test_vinin_lrma_trend_obeys_minperiod_boundary(runonce, bar_count, has_first_trend):
    """A finite LRMA before minperiod does not bypass trend's warm-up contract."""
    result = _run_indicator(_CLOSES[:bar_count], runonce=runonce)

    assert result["minperiod"] == _MINPERIOD == 131
    assert math.isfinite(result["lrma"][-1])
    if has_first_trend:
        assert all(math.isnan(value) for value in result["trend"][:-1])
        assert math.isfinite(result["trend"][-1])
    else:
        assert all(math.isnan(value) for value in result["trend"])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_vinin_lrma_trend_keeps_real_missing_input_missing(runonce):
    """A real gap stays missing through fan recovery, then reseeds from raw."""
    missing_index = 150
    recovery_index = missing_index + _LRMA_PERIOD + max(_MA_PERIODS) - 1
    bar_count = recovery_index + 4
    closes = list(_close_values(bar_count))
    closes[missing_index] = float("nan")
    result = _run_indicator(closes, runonce=runonce)
    expected_lrma, expected_trend = _reference_trend(closes)

    assert result["minperiod"] == _MINPERIOD == 131
    _assert_float_series(result["lrma"], expected_lrma)
    _assert_float_series(result["trend"], expected_trend)
    assert all(
        math.isfinite(value)
        for value in result["trend"][_MINPERIOD - 1 : missing_index]
    )
    assert all(
        math.isnan(value)
        for value in result["lrma"][missing_index : missing_index + _LRMA_PERIOD]
    )
    assert math.isfinite(result["lrma"][missing_index + _LRMA_PERIOD])
    assert all(
        math.isnan(value)
        for value in result["trend"][missing_index:recovery_index]
    )
    assert math.isnan(result["lrma"][missing_index])
    assert math.isnan(result["trend"][missing_index])
    assert result["trend"][recovery_index] == pytest.approx(
        _raw_score(expected_lrma, recovery_index)
    )
    assert result["trend"][recovery_index + 1 :] == pytest.approx(
        expected_trend[recovery_index + 1 :]
    )
