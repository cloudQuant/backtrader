"""Regression contracts for exact-zero rolling covariance candidates."""

import math
import sys
from fractions import Fraction

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.operators import (
    CrossSectionalRank,
    OperatorReason,
    RollingCovariance,
)


_EXACT_ZERO_PAIRS = (
    (
        [2.6666666666666665, 0.3333333333333333, 0.0],
        [1.6666666666666667, 0.6666666666666666, 2.3333333333333335],
    ),
    (
        [0.0, 3.3333333333333335, 1.3333333333333333],
        [3.3333333333333335, 3.0, 0.6666666666666666],
    ),
)


def _exact_population_covariance(left, right):
    left_exact = tuple(Fraction.from_float(value) for value in left)
    right_exact = tuple(Fraction.from_float(value) for value in right)
    count = len(left_exact)
    numerator = count * sum((x * y for x, y in zip(left_exact, right_exact)), Fraction(0)) - sum(
        left_exact
    ) * sum(right_exact)
    return numerator / (count * count)


def _frame(left, right):
    index = pd.date_range("2024-01-01", periods=len(left), freq="D")
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


def _run(strategy, frames, *, runonce):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for name, frame in frames:
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=name)
    cerebro.addstrategy(strategy)
    return cerebro.run()[0]


@pytest.mark.parametrize("runonce", [False, True])
def test_exact_zero_covariance_candidates_tie_without_snapping_nonzero_values(runonce):
    epsilon = sys.float_info.epsilon
    first_left, first_right = _EXACT_ZERO_PAIRS[0]
    second_left, second_right = _EXACT_ZERO_PAIRS[1]
    pairs = [
        (
            tuple(math.ldexp(value, 400) for value in first_left),
            tuple(math.ldexp(value, -400) for value in first_right),
        ),
        (
            tuple(math.ldexp(value, -400) for value in second_left),
            tuple(math.ldexp(value, 400) for value in second_right),
        ),
        (
            tuple(math.ldexp(value, 400) for value in (-1.0, 0.0, 1.0)),
            (1.0, -2.0, 1.0 + epsilon),
        ),
        (
            tuple(math.ldexp(value, -400) for value in (-1.0, 0.0, 1.0)),
            (1.0, -2.0, 1.0 - epsilon),
        ),
    ]
    exact_values = tuple(_exact_population_covariance(left, right) for left, right in pairs)
    assert exact_values[:2] == (0, 0)
    assert exact_values[2] > 0
    assert exact_values[3] < 0

    class CovarianceRankProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.covariances = tuple(
                RollingCovariance(data.close, data.open, period=3) for data in feeds
            )
            self.rank = CrossSectionalRank.bind(
                *feeds, values=tuple(node.value for node in self.covariances)
            )
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    tuple(node.value[0] for node in self.covariances),
                    tuple(int(node.reason[0]) for node in self.covariances),
                    tuple(self.rank.outputs[data].value[0] for data in self.datas),
                    tuple(int(self.rank.outputs[data].reason[0]) for data in self.datas),
                )
            )

    result = _run(
        CovarianceRankProbe,
        [(f"asset-{index}", _frame(left, right)) for index, (left, right) in enumerate(pairs)],
        runonce=runonce,
    )
    covariances, reasons, ranks, rank_reasons = result.rows[-1]

    assert covariances[:2] == (0.0, 0.0)
    assert covariances[2] > 0.0 and math.isfinite(covariances[2])
    assert covariances[3] < 0.0 and math.isfinite(covariances[3])
    assert reasons == (OperatorReason.READY,) * 4
    assert ranks == pytest.approx((0.625, 0.625, 1.0, 0.25))
    assert rank_reasons == (OperatorReason.READY,) * 4


@pytest.mark.parametrize("runonce", [False, True])
def test_period_five_covariance_keeps_finite_signed_extreme_scale(runonce):
    left = tuple(value * 1e200 for value in (1.0, 2.0, 3.0, 4.0, 5.0))
    positive_right = tuple(value * 1e-200 for value in (1.0, 2.0, 3.0, 4.0, 5.0))
    negative_right = tuple(value * 1e-200 for value in (5.0, 4.0, 3.0, 2.0, 1.0))

    class ExtremeCovarianceProbe(bt.Strategy):
        def __init__(self):
            self.nodes = tuple(
                RollingCovariance(data.close, data.open, period=5) for data in self.datas
            )
            self.rows = []

        def next(self):
            self.rows.append(tuple((node.value[0], int(node.reason[0])) for node in self.nodes))

    result = _run(
        ExtremeCovarianceProbe,
        [
            ("positive", _frame(left, positive_right)),
            ("negative", _frame(left, negative_right)),
        ],
        runonce=runonce,
    )
    positive, negative = result.rows[-1]

    assert positive[1] == negative[1] == OperatorReason.READY
    assert math.isfinite(positive[0]) and positive[0] > 0.0
    assert math.isfinite(negative[0]) and negative[0] < 0.0
    assert positive[0] == pytest.approx(2.0, rel=1e-14)
    assert negative[0] == pytest.approx(-2.0, rel=1e-14)
