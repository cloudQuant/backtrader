"""Extreme-scale contracts for rolling float64 covariance and correlation."""

from decimal import Decimal, localcontext
from fractions import Fraction
import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.operators import (
    OperatorReason,
    RollingCorrelation,
    RollingCovariance,
)


def _frame(left, right):
    index = pd.date_range("2020-01-01", periods=len(left), freq="D")
    return pd.DataFrame(
        {
            "open": right,
            "high": left,
            "low": left,
            "close": left,
            "volume": [1.0] * len(left),
            "openinterest": [0.0] * len(left),
        },
        index=index,
    )


def _evaluate(left, right, *, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.covariance = RollingCovariance(self.data.close, self.data.open, period=len(left))
            self.correlation = RollingCorrelation(self.data.close, self.data.open, period=len(left))
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    (self.covariance.value[0], int(self.covariance.reason[0])),
                    (self.correlation.value[0], int(self.correlation.reason[0])),
                )
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(left, right)))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].rows[-1]


def _exact_covariance(left, right):
    x = [Fraction.from_float(value) for value in left]
    y = [Fraction.from_float(value) for value in right]
    mean_x = sum(x, Fraction(0)) / len(x)
    mean_y = sum(y, Fraction(0)) / len(y)
    return float(
        sum(
            ((a - mean_x) * (b - mean_y) for a, b in zip(x, y)),
            Fraction(0),
        )
        / len(x)
    )


def _exact_correlation(left, right):
    x = [Fraction.from_float(value) for value in left]
    y = [Fraction.from_float(value) for value in right]
    mean_x = sum(x, Fraction(0)) / len(x)
    mean_y = sum(y, Fraction(0)) / len(y)
    centered_x = [value - mean_x for value in x]
    centered_y = [value - mean_y for value in y]
    cross = sum((a * b for a, b in zip(centered_x, centered_y)), Fraction(0))
    sum_xx = sum((value * value for value in centered_x), Fraction(0))
    sum_yy = sum((value * value for value in centered_y), Fraction(0))
    with localcontext() as context:
        context.prec = 120
        decimal_cross = Decimal(cross.numerator) / Decimal(cross.denominator)
        decimal_xx = Decimal(sum_xx.numerator) / Decimal(sum_xx.denominator)
        decimal_yy = Decimal(sum_yy.numerator) / Decimal(sum_yy.denominator)
        return float(decimal_cross / (decimal_xx * decimal_yy).sqrt())


@pytest.mark.parametrize("runonce", [False, True])
def test_correlation_survives_square_product_overflow_at_1e100(runonce):
    left = [1e100, 2e100, 3e100, 4e100]
    right = [2e100, 4e100, 6e100, 8e100]

    covariance, correlation = _evaluate(left, right, runonce=runonce)

    assert correlation == (1.0, OperatorReason.READY)
    assert covariance == (_exact_covariance(left, right), OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_correlation_survives_subnormal_deviations(runonce):
    smallest = float.fromhex("0x0.0000000000001p-1022")
    left = [0.0, smallest, 2.0 * smallest, 3.0 * smallest]
    right = [0.0, 2.0 * smallest, 4.0 * smallest, 6.0 * smallest]

    covariance, correlation = _evaluate(left, right, runonce=runonce)

    assert correlation == (1.0, OperatorReason.READY)
    assert covariance == (_exact_covariance(left, right), OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_covariance_restores_independent_scales_without_false_overflow(runonce):
    left = [1e200, 2e200, 3e200, 4e200]
    right = [1e-200, 2e-200, 3e-200, 4e-200]

    covariance, correlation = _evaluate(left, right, runonce=runonce)

    assert covariance == (1.25, OperatorReason.READY)
    assert correlation == (1.0, OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_covariance_underflow_rounds_to_finite_zero(runonce):
    smallest = float.fromhex("0x0.0000000000001p-1022")

    covariance, _ = _evaluate([0.0, smallest, 0.0], [0.0, smallest, 0.0], runonce=runonce)

    assert covariance == (0.0, OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_covariance_final_overflow_keeps_domain_error_reason(runonce):
    values = [1e200, 2e200, 3e200, 4e200]

    covariance, correlation = _evaluate(values, values, runonce=runonce)

    assert math.isnan(covariance[0])
    assert covariance[1] == OperatorReason.DOMAIN_ERROR
    assert correlation == (1.0, OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_anchor_centering_preserves_large_bias_ulp_variation(runonce):
    base = float.fromhex("0x1.1ccf385ebc8ap+1023")  # 1e308
    ulp = float.fromhex("0x1.0p+971")
    left = [base + step * ulp for step in range(4)]
    right = [base + 2 * step * ulp for step in range(4)]

    _, correlation = _evaluate(left, right, runonce=runonce)

    assert correlation == (1.0, OperatorReason.READY)


@pytest.mark.parametrize("runonce", [False, True])
def test_constant_inputs_have_explicit_covariance_and_correlation_results(runonce):
    covariance, correlation = _evaluate([3.0] * 4, [1.0, 2.0, 4.0, 8.0], runonce=runonce)

    assert covariance == (0.0, OperatorReason.READY)
    assert math.isnan(correlation[0])
    assert correlation[1] == OperatorReason.DOMAIN_ERROR


@pytest.mark.parametrize("runonce", [False, True])
def test_correlation_does_not_snap_small_or_near_bound_values(runonce):
    near_zero_left = [-1.0, 1.0, 0.0]
    near_zero_right = [1.0, 1.0 + 4.440892098500626e-16, 0.0]
    near_one_left = [-1.0, 0.0, 1.0]
    near_one_right = [-1.0, 5e-8, 1.0]

    _, near_zero = _evaluate(near_zero_left, near_zero_right, runonce=runonce)
    _, near_one = _evaluate(near_one_left, near_one_right, runonce=runonce)
    expected_zero = _exact_correlation(near_zero_left, near_zero_right)
    expected_one = _exact_correlation(near_one_left, near_one_right)

    assert expected_zero != 0.0
    assert near_zero == (expected_zero, OperatorReason.READY)
    assert expected_one != 1.0
    assert near_one[0] != 1.0
    assert near_one[1] == OperatorReason.READY
    assert math.isclose(near_one[0], expected_one, rel_tol=0.0, abs_tol=3e-16)
