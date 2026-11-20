"""Regression coverage for AmlIndicator's first recursive seed (R71-033)."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _flat_prices(length, price):
    return [float(price)] * length


def _run_aml(
    prices,
    runonce,
    fractal=70,
    lag=18,
    point=0.01,
    missing_close=(),
    missing_high=(),
    open_prices=None,
    high_prices=None,
    low_prices=None,
):
    prices = list(prices)
    opens = list(prices if open_prices is None else open_prices)
    highs = list(prices if high_prices is None else high_prices)
    lows = list(prices if low_prices is None else low_prices)
    closes = list(prices)
    for index in missing_close:
        closes[index] = float("nan")
    for index in missing_high:
        highs[index] = float("nan")

    frame = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2024-01-01", periods=len(prices), freq="D"),
    )
    result = {}

    class AmlProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.AmlIndicator(
                self.data, fractal=fractal, lag=lag, point=point
            )

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["values"] = [float(value) for value in self.indicator.aml.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(AmlProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _reference_aml(opens, highs, lows, closes, first_index, fractal, lag, point):
    """Apply the zero-seed recurrence and leave state untouched across data gaps."""
    values = [float("nan")] * len(closes)
    smooth_values = []
    last_aml = None
    first_smooth = None
    first_alpha = None
    first_price = None

    for index in range(first_index, len(closes)):
        price = (
            highs[index] + lows[index] + 2.0 * opens[index] + 2.0 * closes[index]
        ) / 6.0
        if not math.isfinite(price):
            continue

        recent = slice(index - fractal + 1, index + 1)
        prior = slice(index - 2 * fractal + 1, index - fractal + 1)
        full = slice(index - 2 * fractal + 1, index + 1)
        range_inputs = (
            highs[recent], lows[recent], highs[prior], lows[prior],
            highs[full], lows[full],
        )
        if not all(math.isfinite(value) for group in range_inputs for value in group):
            continue

        r1 = (max(highs[recent]) - min(lows[recent])) / fractal
        r2 = (max(highs[prior]) - min(lows[prior])) / fractal
        r3 = (max(highs[full]) - min(lows[full])) / (2 * fractal)
        dim = 0.0
        if r1 + r2 > 0.0 and r3 > 0.0:
            dim = (math.log(r1 + r2) - math.log(r3)) / math.log(2.0)
        alpha = min(1.0, max(0.01, math.exp(-lag * (dim - 1.0))))

        # The repository's independent AML reference uses zero when there is no
        # preceding smooth value, so the true first smooth need not equal price.
        previous_smooth = smooth_values[-1] if smooth_values else 0.0
        smooth = alpha * price + (1.0 - alpha) * previous_smooth
        lagged_smooth = smooth_values[-(lag + 1)] if len(smooth_values) >= lag + 1 else 0.0
        smooth_values.append(smooth)
        if first_smooth is None:
            first_smooth = smooth
            first_alpha = alpha
            first_price = price

        aml = (
            smooth
            if last_aml is None or abs(smooth - lagged_smooth) >= lag * lag * point
            else last_aml
        )
        last_aml = aml
        values[index] = aml

    return values, first_smooth, first_alpha, first_price


def _assert_same_aml(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if math.isfinite(expected_value):
            assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("price", (100.0, 0.1), ids=("ordinary-scale", "low-price"))
def test_aml_first_computable_value_seeds_at_any_price_scale(runonce, price):
    result = _run_aml(_flat_prices(171, price), runonce=runonce)
    minperiod = result["minperiod"]
    values = result["values"]

    assert len(values) == 171
    assert minperiod > 1
    assert all(math.isnan(value) for value in values[: minperiod - 1])
    assert values[minperiod - 1 :] == pytest.approx([price] * (171 - minperiod + 1))


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_aml_minperiod_boundary_seeds_on_exact_first_computable_bar(runonce):
    long_result = _run_aml(_flat_prices(171, 0.1), runonce=runonce)
    minperiod = long_result["minperiod"]

    short_result = _run_aml(
        _flat_prices(minperiod - 1, 0.1), runonce=runonce
    )
    boundary_result = _run_aml(
        _flat_prices(minperiod, 0.1), runonce=runonce
    )

    assert all(math.isnan(value) for value in short_result["values"])
    assert len(boundary_result["values"]) == minperiod
    assert all(math.isnan(value) for value in boundary_result["values"][:-1])
    assert boundary_result["values"][-1] == pytest.approx(0.1)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_aml_missing_current_price_is_nan_and_valid_values_resume(runonce):
    prices = _flat_prices(160, 100.0)
    result = _run_aml(
        prices, runonce=runonce, missing_close=(150,)
    )
    values = result["values"]
    missing_index = 150

    assert math.isfinite(values[missing_index - 1])
    assert math.isnan(values[missing_index])
    assert values[missing_index + 1 :] == pytest.approx(
        [100.0] * (len(values) - missing_index - 1)
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_aml_missing_range_input_stays_nan_until_lookback_is_complete(runonce):
    result = _run_aml(
        _flat_prices(291, 100.0), runonce=runonce, missing_high=(150,)
    )
    values = result["values"]

    assert math.isfinite(values[149])
    assert all(math.isnan(value) for value in values[150:290])
    assert values[290:] == pytest.approx([100.0])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_aml_nonflat_sequence_matches_zero_seed_reference_and_recovers_gap(runonce):
    fractal, lag, point = 2, 3, 0.00001
    prices = [0.1 + 0.008 * ((index * 3) % 7) for index in range(24)]
    opens = [price + 0.003 for price in prices]
    highs = [price + 0.05 for price in prices]
    lows = [price - 0.05 for price in prices]
    closes = [price - 0.002 for price in prices]

    result = _run_aml(
        closes,
        runonce=runonce,
        fractal=fractal,
        lag=lag,
        point=point,
        open_prices=opens,
        high_prices=highs,
        low_prices=lows,
    )
    first_index = result["minperiod"] - 1
    expected, first_smooth, first_alpha, first_price = _reference_aml(
        opens, highs, lows, closes, first_index, fractal, lag, point
    )

    assert 0.0 < first_alpha < 1.0
    assert first_smooth == pytest.approx(first_alpha * first_price)
    assert not math.isclose(first_smooth, first_price, rel_tol=1e-6, abs_tol=1e-9)
    _assert_same_aml(result["values"], expected)

    missing_index = first_index + 4
    gap_result = _run_aml(
        closes,
        runonce=runonce,
        fractal=fractal,
        lag=lag,
        point=point,
        missing_close=(missing_index,),
        open_prices=opens,
        high_prices=highs,
        low_prices=lows,
    )
    gap_closes = list(closes)
    gap_closes[missing_index] = float("nan")
    gap_expected, _, _, _ = _reference_aml(
        opens, highs, lows, gap_closes, first_index, fractal, lag, point
    )

    assert math.isnan(gap_result["values"][missing_index])
    assert math.isfinite(gap_result["values"][missing_index + 1])
    _assert_same_aml(gap_result["values"], gap_expected)
