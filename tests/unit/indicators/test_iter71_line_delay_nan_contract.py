"""Reproduce delayed NaN loss and its effect on a rolling window."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader import linebuffer
from backtrader.errors import FactorComputationContext, FactorComputationError
from backtrader.research.strict import computation_scope


def _feed(values):
    frame = pd.DataFrame(
        {"close": values}, index=pd.date_range("2020-01-01", periods=len(values))
    )
    return bt.feeds.PandasData(dataname=frame)


def _run_lag(values, runonce):
    class LagDifference(bt.Indicator):
        lines = ("delta",)

        def __init__(self):
            self.delayed = self.data.close(-1)
            self.lines.delta = self.data.close - self.delayed

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = LagDifference(self.data)
            self.delayed = self.indicator.delayed
            self.context = FactorComputationContext("delay-contract")
            self.samples = []

        def next(self):
            with computation_scope(self.context, "next"):
                strict_lag = self.delayed[0]
                strict_oob = self.delayed[-100]
            self.samples.append(
                (len(self.data) - 1, self.delayed[0], strict_lag, self.delayed[-100], strict_oob)
            )

        def stop(self):
            self.result = (list(self.indicator.delta.array), self.samples)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(_feed(values))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _run_weighted_sma(values, runonce, period):
    class WeightedAverage(bt.Indicator):
        lines = ("average",)

        def __init__(self):
            close = self.data.close
            self.weighted = (close + 2 * close(-1) + 2 * close(-2) + close(-3)) / 6.0
            self.lines.average = bt.indicators.SMA(self.weighted, period=period)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = WeightedAverage(self.data)

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.weighted.array),
                list(self.indicator.average.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(_feed(values))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _assert_equal(actual, expected, *, offset=0):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), f"index {index + offset}: expected NaN, got {got!r}"
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), f"index {index + offset}"


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_single_lag_propagates_a_missing_previous_value(runonce):
    values = [10.0, 11.0, 12.0, math.nan, 14.0, 15.0, 16.0, 17.0]
    actual, _samples = _run_lag(values, runonce)
    expected = [math.nan] + [
        values[index] - values[index - 1] for index in range(1, len(values))
    ]
    # The contract starts at index 1 where both values are in bounds.
    _assert_equal(actual[1:], expected[1:], offset=1)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("stage", ["weighted", "average"])
def test_weighted_sma_preserves_complete_nan_window(runonce, stage):
    values = [100.0 + index * 0.25 for index in range(40)]
    values[20] = math.nan
    period = 5
    minperiod, weighted, average = _run_weighted_sma(values, runonce, period)
    first_weighted = 3
    first_average = first_weighted + period - 1
    assert minperiod == first_average + 1

    expected_weighted = [math.nan] * first_weighted + [
        sum(weight * values[index - lag] for lag, weight in enumerate((1, 2, 2, 1))) / 6.0
        for index in range(first_weighted, len(values))
    ]
    expected_average = [math.nan] * first_average + [
        math.fsum(expected_weighted[index - period + 1 : index + 1]) / period
        for index in range(first_average, len(values))
    ]
    assert all(math.isnan(expected_weighted[index]) for index in range(20, 24))
    assert all(math.isnan(expected_average[index]) for index in range(20, 28))
    assert math.isfinite(expected_average[28])
    if stage == "weighted":
        _assert_equal(
            weighted[first_weighted:], expected_weighted[first_weighted:], offset=first_weighted
        )
    else:
        _assert_equal(average, expected_average)


def test_lag_normal_and_strict_out_of_bounds_behavior_is_preserved():
    _actual, samples = _run_lag([10.0, 11.0, 12.0, math.nan, 14.0, 15.0], False)
    by_index = {row[0]: row[1:] for row in samples}
    assert by_index[2][:2] == (11.0, 11.0)
    # Ordinary delayed reads use the legacy zero fallback for out of bounds;
    # strict factor reads use missing NaN instead.
    assert all(legacy_oob == 0.0 and math.isnan(strict_oob)
               for _index, _legacy, _strict, legacy_oob, strict_oob in samples)
    assert math.isnan(by_index[4][1])


@pytest.mark.parametrize(
    "value,expected",
    [(12.5, 12.5), (math.nan, math.nan), (None, 0.0),
     (math.inf, 0.0), (-math.inf, 0.0), (IndexError(), 0.0)],
)
def test_legacy_delay_direct_read_and_next_boundaries(value, expected):
    class Source:
        def __getitem__(self, _index):
            if isinstance(value, Exception):
                raise value
            return value

    class Carrier:
        a = Source()
        ago = -1

        def __setitem__(self, _index, item):
            self.output = item

    carrier = Carrier()
    direct = linebuffer._LineDelay.__getitem__(carrier, 0)
    linebuffer._LineDelay.next(carrier)
    if math.isnan(expected):
        assert math.isnan(direct)
        assert math.isnan(carrier.output)
    else:
        assert direct == carrier.output == expected


@pytest.mark.parametrize("value", [None, math.nan])
def test_strict_numeric_policy_treats_none_and_nan_as_missing(value):
    context = FactorComputationContext("delay-contract")
    with computation_scope(context, "next"):
        assert math.isnan(linebuffer._strict_numeric_value(context, value, "next", object()))
    assert context.failed is False


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_strict_numeric_policy_rejects_infinity(value):
    context = FactorComputationContext("delay-contract")
    with computation_scope(context, "next"), pytest.raises(FactorComputationError) as caught:
        linebuffer._strict_numeric_value(context, value, "next", object())
    assert isinstance(caught.value.__cause__, ArithmeticError)
    assert context.failed is True
