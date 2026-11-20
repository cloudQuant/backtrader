"""Regression coverage for bounded AdaptiveMarketLevel state (R71-045)."""

import math

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import pytest
from backtrader.indicators.contrib.shared_strategy_indicators import _AdaptivePriceRange


def _ohlc(count):
    """Build deterministic OHLC input with distinct, finite values."""
    closes = [100.0 + index * 0.013 + (index * 7 % 13) * 0.037 for index in range(count)]
    opens = [close + (0.019 if index % 2 else -0.027) for index, close in enumerate(closes)]
    highs = [
        max(open_, close) + 0.061 + index % 5 * 0.009
        for index, (open_, close) in enumerate(zip(opens, closes))
    ]
    lows = [
        min(open_, close) - 0.047 - index % 7 * 0.005
        for index, (open_, close) in enumerate(zip(opens, closes))
    ]
    return opens, highs, lows, closes


def _legacy_reference(opens, highs, lows, closes, fractal, lag, point):
    """Reproduce the original list-based AML recurrence as an oracle."""
    minperiod = max(2 * fractal + lag, 1)
    values = [float("nan")] * len(closes)
    smooth_history = []
    aml_history = []

    for index in range(minperiod - 1, len(closes)):
        recent_start = index - fractal + 1
        prior_start = index - 2 * fractal + 1
        # The legacy implementation iterates ago=0, -1, -2, ...; preserving
        # this newest-to-oldest order matters because NaN comparisons are
        # order-sensitive in Python's built-in max/min.
        recent_highs = [float(value) for value in reversed(highs[recent_start : index + 1])]
        recent_lows = [float(value) for value in reversed(lows[recent_start : index + 1])]
        prior_highs = [float(value) for value in reversed(highs[prior_start : index - fractal + 1])]
        prior_lows = [float(value) for value in reversed(lows[prior_start : index - fractal + 1])]
        full_highs = [float(value) for value in reversed(highs[prior_start : index + 1])]
        full_lows = [float(value) for value in reversed(lows[prior_start : index + 1])]

        r1 = (max(recent_highs) - min(recent_lows)) / fractal
        r2 = (max(prior_highs) - min(prior_lows)) / fractal
        r3 = (max(full_highs) - min(full_lows)) / (2 * fractal)
        dimension = 0.0
        if r1 + r2 > 0.0 and r3 > 0.0:
            dimension = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896

        alpha = math.exp(-lag * (dimension - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        price = (
            float(highs[index])
            + float(lows[index])
            + 2.0 * float(opens[index])
            + 2.0 * float(closes[index])
        ) / 6.0
        previous_smooth = smooth_history[-1] if smooth_history else 0.0
        smooth = alpha * price + (1.0 - alpha) * previous_smooth
        lagged_smooth = smooth_history[-lag] if len(smooth_history) >= lag else 0.0
        previous_aml = aml_history[-1] if aml_history else smooth
        point_value = point[index] if isinstance(point, (tuple, list)) else point
        threshold = lag * lag * float(point_value)
        aml = smooth if abs(smooth - lagged_smooth) >= threshold else previous_aml

        smooth_history.append(smooth)
        aml_history.append(aml)
        values[index] = aml

    return values


class _AdaptiveMarketLevelProbe(bt.Strategy):
    params = (
        ("fractal", 7),
        ("lag", 4),
        ("point", 0.01),
        ("mutate_at", None),
        ("mutate_parameter", None),
        ("mutate_value", None),
        ("mutate_before_run", False),
        ("repeat_range_updates", 0),
    )

    def __init__(self):
        self.indicator = btind.AdaptiveMarketLevel(
            self.data,
            fractal=self.p.fractal,
            lag=self.p.lag,
            point=self.p.point,
        )
        if self.p.mutate_before_run:
            setattr(
                self.indicator.p,
                self.p.mutate_parameter,
                self.p.mutate_value,
            )

    def next(self):
        if self.p.mutate_at == len(self.data):
            setattr(
                self.indicator.p,
                self.p.mutate_parameter,
                self.p.mutate_value,
            )

    def stop(self):
        count = len(self.data)
        repeated_ranges = None
        direct_ranges = None
        if self.p.repeat_range_updates:
            fractal = int(self.p.fractal)
            for _ in range(self.p.repeat_range_updates):
                repeated_ranges = self.indicator._adaptive_ranges(fractal)
            direct_ranges = (
                self.indicator._range(fractal, 0) / fractal,
                self.indicator._range(fractal, fractal) / fractal,
                self.indicator._range(fractal * 2, 0) / (fractal * 2),
            )
        self.result = {
            "minperiod": self.indicator._min_period,
            "values": [float(value) for value in self.indicator.aml.array[:count]],
            "inputs": tuple(
                [float(value) for value in line.array[:count]]
                for line in (self.data.open, self.data.high, self.data.low, self.data.close)
            ),
            "smooth_history": self.indicator._smooth_history,
            "aml_history": self.indicator._aml_history,
            "range_windows": getattr(self.indicator, "_range_windows", None),
            "repeated_ranges": repeated_ranges,
            "direct_ranges": direct_ranges,
        }


def _run_indicator(
    runonce,
    opens,
    highs,
    lows,
    closes,
    fractal,
    lag,
    point=0.01,
    *,
    mutate_at=None,
    mutate_parameter=None,
    mutate_value=None,
    mutate_before_run=False,
    repeat_range_updates=0,
):
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        _AdaptiveMarketLevelProbe,
        fractal=fractal,
        lag=lag,
        point=point,
        mutate_at=mutate_at,
        mutate_parameter=mutate_parameter,
        mutate_value=mutate_value,
        mutate_before_run=mutate_before_run,
        repeat_range_updates=repeat_range_updates,
    )
    return cerebro.run(runonce=runonce, preload=True)[0].result


def _assert_series_equal(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        elif math.isinf(want):
            assert got == want
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("fractal,lag,point", ((5, 3, 0.01), (8, 4, 0.2)))
def test_adaptive_market_level_preserves_outputs_for_constructor_parameters(
    runonce, fractal, lag, point
):
    count = 2 * fractal + lag + 48
    opens, highs, lows, closes = _ohlc(count)

    result = _run_indicator(runonce, opens, highs, lows, closes, fractal, lag, point=point)
    expected = _legacy_reference(*result["inputs"], fractal, lag, point)

    assert result["minperiod"] == 2 * fractal + lag
    _assert_series_equal(result["values"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_adaptive_market_level_keeps_nonfinite_window_semantics(runonce):
    fractal, lag = 5, 3
    count = 2 * fractal + lag + 70
    opens, highs, lows, closes = _ohlc(count)

    # NaNs exercise the legacy max/min order and moving-window fallback. The
    # ordinary Backtrader line write maps infinities to its configured default;
    # the direct range test below covers infinite extrema and expiry.
    highs[0] = float("nan")
    lows[7] = float("nan")
    highs[29] = float("inf")
    lows[34] = float("-inf")
    opens[50] = float("nan")

    result = _run_indicator(runonce, opens, highs, lows, closes, fractal, lag)
    expected = _legacy_reference(*result["inputs"], fractal, lag, 0.01)

    _assert_series_equal(result["values"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("parameter,new_value", (("lag", 12), ("fractal", 9)))
def test_adaptive_market_level_rejects_state_parameter_changes(runonce, parameter, new_value):
    fractal, lag = 5, 3
    count = 2 * fractal + lag + 24
    opens, highs, lows, closes = _ohlc(count)
    mutation = {
        "mutate_parameter": parameter,
        "mutate_value": new_value,
        "mutate_at": None if runonce else 2 * fractal + lag + 2,
        "mutate_before_run": runonce,
    }

    with pytest.raises(RuntimeError, match="construction-time parameters"):
        _run_indicator(runonce, opens, highs, lows, closes, fractal, lag, **mutation)


def test_adaptive_market_level_keeps_point_runtime_mutable():
    fractal, lag = 5, 3
    count = 2 * fractal + lag + 24
    mutate_at = 2 * fractal + lag + 2
    opens, highs, lows, closes = _ohlc(count)
    result = _run_indicator(
        False,
        opens,
        highs,
        lows,
        closes,
        fractal,
        lag,
        point=0.01,
        mutate_at=mutate_at,
        mutate_parameter="point",
        mutate_value=10000.0,
    )
    points = [0.01] * count
    for index in range(mutate_at, count):
        points[index] = 10000.0
    expected = _legacy_reference(*result["inputs"], fractal, lag, points)
    baseline = _run_indicator(False, opens, highs, lows, closes, fractal, lag)

    _assert_series_equal(result["values"], expected)
    assert result["values"][mutate_at] == result["values"][mutate_at - 1]
    assert result["values"][mutate_at] != baseline["values"][mutate_at]


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_adaptive_market_level_history_and_ranges_remain_bounded_after_5000_bars(
    runonce,
):
    fractal, lag = 70, 18
    count = 5000
    opens, highs, lows, closes = _ohlc(count)

    result = _run_indicator(runonce, opens, highs, lows, closes, fractal, lag)
    expected = _legacy_reference(*result["inputs"], fractal, lag, 0.01)

    assert len(result["smooth_history"]) <= lag + 1
    assert result["smooth_history"].maxlen == lag + 1
    assert len(result["aml_history"]) == 1
    assert result["aml_history"].maxlen == 1
    windows = result["range_windows"]
    assert [len(window._values) for window in windows] == [
        fractal,
        fractal,
        2 * fractal,
    ]
    assert all(
        len(queue) <= window.period
        for window in windows
        for queue in (
            window._values,
            window._maxima,
            window._minima,
            window._nan_indexes,
        )
    )
    _assert_series_equal(result["values"], expected)


def test_adaptive_market_level_rebuilds_bounded_windows_on_repeated_bar():
    fractal, lag = 5, 3
    count = 2 * fractal + lag + 24
    opens, highs, lows, closes = _ohlc(count)

    result = _run_indicator(
        False,
        opens,
        highs,
        lows,
        closes,
        fractal,
        lag,
        repeat_range_updates=100,
    )

    assert result["repeated_ranges"] == pytest.approx(result["direct_ranges"])
    assert [len(window._values) for window in result["range_windows"]] == [
        fractal,
        fractal,
        2 * fractal,
    ]


def test_adaptive_market_price_range_preserves_nan_order_and_infinity_extrema():
    window = _AdaptivePriceRange(period=3)
    window.append(0, float("inf"), float("-inf"))
    window.append(1, 5.0, -4.0)
    window.append(2, 3.0, -2.0)
    assert window.value() == float("inf")

    window.append(3, 7.0, 1.0)
    assert window.value() == 11.0

    nan_window = _AdaptivePriceRange(period=3)
    nan_window.append(0, float("nan"), 3.0)
    nan_window.append(1, 5.0, float("nan"))
    nan_window.append(2, 4.0, 2.0)
    # Newest-to-oldest max/min ignore NaNs that occur after the first sample.
    assert nan_window.value() == 3.0
    nan_window.append(3, 7.0, 1.0)
    assert nan_window.value() == 6.0

    newest_nan_window = _AdaptivePriceRange(period=2)
    newest_nan_window.append(0, 5.0, 1.0)
    newest_nan_window.append(1, float("nan"), 2.0)
    assert math.isnan(newest_nan_window.value())
