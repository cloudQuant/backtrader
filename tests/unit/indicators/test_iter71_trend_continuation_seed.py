"""Regression coverage for TrendContinuationIndicator's recursive seed (R71-033)."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.trend_continuation_indicator import (
    TrendContinuationIndicator,
)


def _prices(length):
    """Build a deterministic price path with both rising and falling moves."""
    return [
        100.0 + index * 0.17 + math.sin(index * 0.31) * 4.0
        + math.cos(index * 0.13) * 1.5
        for index in range(length)
    ]


def _reference(prices, nperiod, xperiod):
    """Apply the indicator's directional sums and EMA recurrence independently."""
    nperiod = max(2, int(nperiod))
    xperiod = max(1, int(xperiod))
    minperiod = int(nperiod + xperiod + 5)
    values = {"up": [float("nan")] * len(prices),
              "down": [float("nan")] * len(prices)}
    first = minperiod - 1
    if first >= len(prices):
        return values, minperiod

    alpha = 2.0 / (xperiod + 1.0)
    previous = {"up": None, "down": None}
    for index in range(first, len(prices)):
        positive = []
        negative = []
        cumulative_positive = []
        cumulative_negative = []
        running_positive = 0.0
        running_negative = 0.0
        for offset in range(nperiod):
            diff = prices[index - offset] - prices[index - offset - 1]
            if math.isnan(diff):
                pos = neg = float("nan")
            else:
                pos = -diff if diff > 0.0 else 0.0
                neg = diff if diff < 0.0 else 0.0
            running_positive += pos
            running_negative += neg
            positive.append(pos)
            negative.append(neg)
            cumulative_positive.append(running_positive)
            cumulative_negative.append(running_negative)

        current = {
            "up": sum(positive) - sum(cumulative_negative),
            "down": sum(negative) - sum(cumulative_positive),
        }
        for line_name, component in current.items():
            if previous[line_name] is None:
                value = component
            else:
                value = alpha * component + (1.0 - alpha) * previous[line_name]
            values[line_name][index] = value
            previous[line_name] = value

    return values, minperiod


def _run_indicator(prices, runonce, **params):
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2024-01-01", periods=len(prices), freq="D"),
    )
    result = {}

    class ProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = TrendContinuationIndicator(self.data, **params)

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["up"] = [float(value) for value in self.indicator.up.array]
            result["down"] = [float(value) for value in self.indicator.down.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_line_matches(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if not math.isnan(expected_value):
            assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_trend_continuation_first_value_seeds_from_current_components(runonce):
    prices = _prices(171)
    expected, minperiod = _reference(prices, nperiod=20, xperiod=5)
    result = _run_indicator(prices, runonce=runonce)

    assert result["minperiod"] == minperiod == 30
    assert all(math.isnan(value) for value in result["up"][: minperiod - 1])
    assert all(math.isnan(value) for value in result["down"][: minperiod - 1])
    assert math.isfinite(result["up"][minperiod - 1])
    assert math.isfinite(result["down"][minperiod - 1])
    _assert_line_matches(result["up"], expected["up"])
    _assert_line_matches(result["down"], expected["down"])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_trend_continuation_midstream_nan_is_not_reseeded(runonce):
    prices = _prices(171)
    gap_index = 90
    prices[gap_index] = float("nan")
    expected, minperiod = _reference(prices, nperiod=20, xperiod=5)
    result = _run_indicator(prices, runonce=runonce)

    assert result["minperiod"] == minperiod == 30
    for line_name in ("up", "down"):
        actual = result[line_name]
        assert all(math.isnan(value) for value in actual[: minperiod - 1])
        assert all(math.isfinite(value) for value in actual[minperiod - 1 : gap_index])
        assert all(math.isnan(value) for value in actual[gap_index:])
        _assert_line_matches(actual, expected[line_name])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("length, has_seed", ((29, False), (30, True), (31, True)))
def test_trend_continuation_minperiod_boundary(runonce, length, has_seed):
    result = _run_indicator(_prices(length), runonce=runonce)

    assert result["minperiod"] == 30
    if has_seed:
        assert all(math.isnan(value) for value in result["up"][:29])
        assert all(math.isnan(value) for value in result["down"][:29])
        assert math.isfinite(result["up"][29])
        assert math.isfinite(result["down"][29])
    else:
        assert all(math.isnan(value) for value in result["up"])
        assert all(math.isnan(value) for value in result["down"])


class _InputReadError(RuntimeError):
    pass


class _FailingPriceLine:
    def __getitem__(self, index):
        raise _InputReadError("price input unavailable")


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_trend_continuation_does_not_suppress_price_input_errors(runonce):
    prices = _prices(31)
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2024-01-01", periods=len(prices), freq="D"),
    )

    class FailingProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = TrendContinuationIndicator(self.data)
            self.indicator._price = _FailingPriceLine()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(FailingProbeStrategy)

    with pytest.raises(_InputReadError, match="price input unavailable"):
        cerebro.run(runonce=runonce, preload=True)
