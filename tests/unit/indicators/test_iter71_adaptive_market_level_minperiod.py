"""Regression coverage for AdaptiveMarketLevel's declared warm-up (R71-043)."""

import math

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import pytest


FRACTAL = 70
LAG = 18
POINT = 0.01
MINPERIOD = 2 * FRACTAL + LAG
DOWNSTREAM_PERIOD = 3


def _ohlc(count):
    """Return a deterministic non-flat OHLC series with distinct prices."""
    closes = [
        100.0 + 0.017 * index + ((index * 13) % 11) * 0.041
        for index in range(count)
    ]
    opens = [
        close + (0.023 if index % 2 else -0.019)
        for index, close in enumerate(closes)
    ]
    highs = [
        max(open_, close) + 0.071 + (index % 5) * 0.006
        for index, (open_, close) in enumerate(zip(opens, closes))
    ]
    lows = [
        min(open_, close) - 0.053 - (index % 7) * 0.004
        for index, (open_, close) in enumerate(zip(opens, closes))
    ]
    return opens, highs, lows, closes


def _adaptive_market_level_reference(opens, highs, lows, closes):
    """Compute the legacy zero-seed recurrence from its first valid bar.

    The R71-043 fix should hide the pre-minperiod close fallback without
    changing the existing recursive sequence once AML first becomes visible.
    This reference deliberately starts with empty recursive history at bar
    ``MINPERIOD`` and calculates the range windows directly from arrays.
    """
    values = [float("nan")] * len(closes)
    smooth_history = []
    aml_history = []

    for index in range(MINPERIOD - 1, len(closes)):
        recent_start = index - FRACTAL + 1
        prior_start = index - 2 * FRACTAL + 1

        recent_highs = highs[recent_start : index + 1]
        recent_lows = lows[recent_start : index + 1]
        prior_highs = highs[prior_start : index - FRACTAL + 1]
        prior_lows = lows[prior_start : index - FRACTAL + 1]
        full_highs = highs[prior_start : index + 1]
        full_lows = lows[prior_start : index + 1]

        r1 = (max(recent_highs) - min(recent_lows)) / FRACTAL
        r2 = (max(prior_highs) - min(prior_lows)) / FRACTAL
        r3 = (max(full_highs) - min(full_lows)) / (2 * FRACTAL)

        dimension = 0.0
        if r1 + r2 > 0.0 and r3 > 0.0:
            dimension = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896

        alpha = min(max(math.exp(-LAG * (dimension - 1.0)), 0.01), 1.0)
        price = (
            highs[index] + lows[index] + 2.0 * opens[index] + 2.0 * closes[index]
        ) / 6.0
        previous_smooth = smooth_history[-1] if smooth_history else 0.0
        smooth = alpha * price + (1.0 - alpha) * previous_smooth
        lagged_smooth = smooth_history[-LAG] if len(smooth_history) >= LAG else 0.0
        previous_aml = aml_history[-1] if aml_history else smooth
        aml = (
            smooth
            if abs(smooth - lagged_smooth) >= LAG * LAG * POINT
            else previous_aml
        )

        smooth_history.append(smooth)
        aml_history.append(aml)
        values[index] = aml

    return values


def _sma_reference(values, period):
    """Calculate a simple moving average while preserving invalid warm-up."""
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        if all(math.isfinite(value) for value in window):
            result[index] = sum(window) / period
    return result


class _AdaptiveMarketLevelProbe(bt.Strategy):
    params = (
        ("downstream_period", None),
    )

    def __init__(self):
        self.indicator = btind.AdaptiveMarketLevel(
            self.data,
            fractal=FRACTAL,
            lag=LAG,
            point=POINT,
        )
        self.downstream = None
        if self.p.downstream_period is not None:
            self.downstream = btind.SimpleMovingAverage(
                self.indicator.aml,
                period=self.p.downstream_period,
            )
        self.first_next_bar = None

    def next(self):
        if self.first_next_bar is None:
            self.first_next_bar = len(self.data)

    def stop(self):
        count = len(self.data)
        self.result = {
            "feed_minperiod": self.data._minperiod,
            "indicator_minperiod": self.indicator._minperiod,
            "strategy_minperiod": self._minperiod,
            "first_next_bar": self.first_next_bar,
            "aml": [float(value) for value in self.indicator.aml.array[:count]],
            "downstream_minperiod": (
                self.downstream._minperiod if self.downstream is not None else None
            ),
            "downstream": (
                [float(value) for value in self.downstream.lines.sma.array[:count]]
                if self.downstream is not None
                else None
            ),
        }


def _run_adaptive_market_level(runonce, count, downstream_period=None):
    opens, highs, lows, closes = _ohlc(count)
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * count,
            "openinterest": [0.0] * count,
        },
        index=pd.date_range("2026-01-01", periods=count, freq="D"),
    )

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        _AdaptiveMarketLevelProbe,
        downstream_period=downstream_period,
    )
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    return opens, highs, lows, closes, strategy.result


def _assert_series_equal(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_adaptive_market_level_hides_warmup_and_preserves_recursive_sequence(runonce):
    opens, highs, lows, closes, result = _run_adaptive_market_level(
        runonce,
        count=MINPERIOD + LAG + 14,
    )
    expected = _adaptive_market_level_reference(opens, highs, lows, closes)

    assert MINPERIOD == 158
    assert result["feed_minperiod"] == 1
    assert result["indicator_minperiod"] == MINPERIOD
    assert result["strategy_minperiod"] == MINPERIOD
    assert result["first_next_bar"] == MINPERIOD
    assert all(math.isnan(value) for value in result["aml"][: MINPERIOD - 1])
    assert result["aml"][MINPERIOD - 1] != closes[MINPERIOD - 1]
    _assert_series_equal(result["aml"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_adaptive_market_level_short_history_never_exposes_close_fallback(runonce):
    _, _, _, _, result = _run_adaptive_market_level(
        runonce,
        count=MINPERIOD - 1,
    )

    assert result["indicator_minperiod"] == MINPERIOD
    assert result["first_next_bar"] is None
    assert all(math.isnan(value) for value in result["aml"])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_adaptive_market_level_minperiod_composes_with_downstream_sma(runonce):
    opens, highs, lows, closes, result = _run_adaptive_market_level(
        runonce,
        count=MINPERIOD + DOWNSTREAM_PERIOD + 4,
        downstream_period=DOWNSTREAM_PERIOD,
    )
    expected_aml = _adaptive_market_level_reference(opens, highs, lows, closes)
    expected_sma = _sma_reference(expected_aml, DOWNSTREAM_PERIOD)

    expected_downstream_minperiod = MINPERIOD + DOWNSTREAM_PERIOD - 1
    assert result["feed_minperiod"] == 1
    assert result["indicator_minperiod"] == MINPERIOD
    assert result["downstream_minperiod"] == expected_downstream_minperiod
    assert result["strategy_minperiod"] == expected_downstream_minperiod
    assert result["first_next_bar"] == expected_downstream_minperiod
    _assert_series_equal(result["aml"], expected_aml)
    _assert_series_equal(result["downstream"], expected_sma)
