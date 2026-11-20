"""Regression contracts for stable near-zero rolling correlation and covariance."""

import math
import sys
from decimal import Decimal, localcontext
from fractions import Fraction

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.alpha101.alpha015 import Alpha015Native
from backtrader.research.operators import (
    CrossSectionalRank,
    OperatorReason,
    RollingCorrelation,
    RollingCovariance,
)


_ZERO_COVARIANCE_PAIRS = (
    (
        [2.6666666666666665, 0.3333333333333333, 0.0],
        [1.6666666666666667, 0.6666666666666666, 2.3333333333333335],
    ),
    (
        [0.0, 3.3333333333333335, 1.3333333333333333],
        [3.3333333333333335, 3.0, 0.6666666666666666],
    ),
    ([0.0, 1.0, 2.0], [0.0, 1.0, 0.0]),
)


def _frame_with_initial_nan(close, open_):
    close = [float("nan")] + list(close)
    open_ = [float("nan")] + list(open_)
    index = pd.date_range("2024-01-01", periods=len(close), freq="D")
    return pd.DataFrame(
        {
            "open": open_,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1.0] * len(close),
            "openinterest": [0.0] * len(close),
        },
        index=index,
    )


def _run(strategy, frames, *, runonce):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for name, frame in frames:
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=name)
    cerebro.addstrategy(strategy)
    return cerebro.run()[0]


def _exact_population_covariance(left, right):
    left_exact = [Fraction.from_float(value) for value in left]
    right_exact = [Fraction.from_float(value) for value in right]
    count = len(left_exact)
    numerator = count * sum(
        (x * y for x, y in zip(left_exact, right_exact)), Fraction(0)
    ) - sum(left_exact) * sum(right_exact)
    return numerator / (count * count)


def _exact_correlation(left, right):
    x = [Fraction.from_float(value) for value in left]
    y = [Fraction.from_float(value) for value in right]
    mean_x = sum(x, Fraction(0)) / len(x)
    mean_y = sum(y, Fraction(0)) / len(y)
    centered_x = [value - mean_x for value in x]
    centered_y = [value - mean_y for value in y]
    covariance = sum((a * b for a, b in zip(centered_x, centered_y)), Fraction(0))
    variance_x = sum((value * value for value in centered_x), Fraction(0))
    variance_y = sum((value * value for value in centered_y), Fraction(0))
    with localcontext() as context:
        context.prec = 100
        numerator = Decimal(covariance.numerator) / Decimal(covariance.denominator)
        denominator = (
            Decimal(variance_x.numerator)
            / Decimal(variance_x.denominator)
            * Decimal(variance_y.numerator)
            / Decimal(variance_y.denominator)
        ).sqrt()
        return float(numerator / denominator)


def _average_rank(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        rank = ((start + 1) + end) / 2.0 / len(values)
        for offset in range(start, end):
            result[order[offset]] = rank
        start = end
    return result


@pytest.mark.parametrize("runonce", [False, True])
def test_exact_zero_correlation_snaps_before_cross_sectional_rank(runonce):
    for left, right in _ZERO_COVARIANCE_PAIRS:
        assert _exact_population_covariance(left, right) == 0

    class NearZeroPanelProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            pairs = tuple(
                (
                    RollingCorrelation(data.close, data.open, period=3),
                    RollingCovariance(data.close, data.open, period=3),
                )
                for data in feeds
            )
            self.correlations = tuple(pair[0] for pair in pairs)
            self.covariances = tuple(pair[1] for pair in pairs)
            self.ranks = CrossSectionalRank.bind(
                *feeds, values=tuple(node.value for node in self.correlations)
            )
            self.rows = []

        def _capture(self):
            self.rows.append(
                (
                    tuple(node.value[0] for node in self.correlations),
                    tuple(int(node.reason[0]) for node in self.correlations),
                    tuple(node.value[0] for node in self.covariances),
                    tuple(int(node.reason[0]) for node in self.covariances),
                    tuple(self.ranks.outputs[data].value[0] for data in self.datas),
                )
            )

        def prenext(self):
            self._capture()

        def nextstart(self):
            self._capture()

        def next(self):
            self._capture()

    frames = [
        (f"asset-{index}", _frame_with_initial_nan(left, right))
        for index, (left, right) in enumerate(_ZERO_COVARIANCE_PAIRS)
    ]
    result = _run(NearZeroPanelProbe, frames, runonce=runonce)

    correlations, correlation_reasons, covariances, covariance_reasons, ranks = result.rows[-1]
    assert correlations == (0.0, 0.0, 0.0)
    assert correlation_reasons == (OperatorReason.READY,) * 3
    assert covariance_reasons == (OperatorReason.READY,) * 3
    # Covariance has physical scale. Keep its existing float64 approximation
    # contract instead of applying a dimensionless absolute epsilon threshold.
    assert all(abs(value) <= 1.3e-16 for value in covariances)
    assert ranks == pytest.approx((2.0 / 3.0,) * 3)


@pytest.mark.parametrize("runonce", [False, True])
def test_alpha015_preserves_nonzero_binary64_correlations_near_zero(runonce):
    # These are actual average-tie rank projections for five assets. Their first
    # two correlations are near zero by decimal intent, but exact binary64 input
    # math is nonzero; keep their distinct rank order instead of snapping blindly.
    high_pattern = (
        (0.7, 0.3, 0.3, 1.0, 0.7),
        (0.8, 0.5, 0.5, 1.0, 0.2),
        (0.3, 0.3, 0.9, 0.9, 0.6),
    )
    volume_pattern = (
        (0.5, 0.5, 0.5, 0.5, 1.0),
        (0.8, 0.4, 0.8, 0.2, 0.8),
        (0.7, 0.3, 0.3, 1.0, 0.7),
    )
    high_rows = [high_pattern[index % 3] for index in range(5)]
    volume_rows = [volume_pattern[index % 3] for index in range(5)]

    # Reassemble the per-asset time series as PandasData feeds.
    asset_frames = []
    for asset in range(5):
        asset_frames.append(
            (
                f"asset-{asset}",
                pd.DataFrame(
                    {
                        "open": [high_rows[bar][asset] for bar in range(5)],
                        "high": [high_rows[bar][asset] for bar in range(5)],
                        "low": [high_rows[bar][asset] for bar in range(5)],
                        "close": [high_rows[bar][asset] for bar in range(5)],
                        "volume": [volume_rows[bar][asset] for bar in range(5)],
                        "openinterest": [0.0] * 5,
                    },
                    index=pd.date_range("2024-02-01", periods=5, freq="D"),
                ),
            )
        )

    class Alpha015Probe(bt.Strategy):
        def __init__(self):
            self.factor = Alpha015Native.bind(*self.datas)
            self.rows = []

        def next(self):
            self.rows.append(
                tuple(self.factor.outputs[data].factor[0] for data in self.datas)
            )

    result = _run(Alpha015Probe, asset_frames, runonce=runonce)
    actual = result.rows[-1]

    ranked_correlations = []
    for end in range(2, 5):
        correlations = []
        for asset in range(5):
            left = [high_rows[bar][asset] for bar in range(end - 2, end + 1)]
            right = [volume_rows[bar][asset] for bar in range(end - 2, end + 1)]
            correlations.append(_exact_correlation(left, right))
        assert 0.0 < abs(correlations[0]) <= 8.0 * sys.float_info.epsilon
        assert 0.0 < abs(correlations[1]) <= 8.0 * sys.float_info.epsilon
        ranked_correlations.append(_average_rank(correlations))
    expected = tuple(
        -sum(ranked_correlations[time][asset] for time in range(3))
        for asset in range(5)
    )
    assert actual == pytest.approx(expected)
    assert actual[0] != actual[1]


@pytest.mark.parametrize("runonce", [False, True])
def test_near_constant_finite_variance_and_nan_windows_keep_their_reasons(runonce):
    one_ulp = math.nextafter(1.0, math.inf)
    two_ulps = math.nextafter(one_ulp, math.inf)
    near_constant = [1.0, one_ulp, two_ulps]
    frames = [
        ("near", _frame_with_initial_nan(near_constant, near_constant)),
        ("constant", _frame_with_initial_nan([2.0, 2.0, 2.0], [1.0, 2.0, 3.0])),
        ("missing", _frame_with_initial_nan([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])),
        (
            "above-snap",
            _frame_with_initial_nan(
                [-1.0, 0.0, 1.0],
                [1.0, -2.0, 1.0 + 32.0 * sys.float_info.epsilon],
            ),
        ),
        (
            "nonzero-below-snap",
            _frame_with_initial_nan(
                [-1.0, 0.0, 1.0],
                [1.0, -2.0, 1.0 + sys.float_info.epsilon],
            ),
        ),
    ]

    class VarianceProbe(bt.Strategy):
        def __init__(self):
            self.nodes = tuple(
                RollingCorrelation(data.close, data.open, period=3) for data in self.datas
            )
            self.rows = []

        def _capture(self):
            self.rows.append(
                tuple((node.value[0], int(node.reason[0])) for node in self.nodes)
            )

        prenext = _capture
        nextstart = _capture
        next = _capture

    result = _run(VarianceProbe, frames, runonce=runonce)
    assert math.isnan(result.rows[2][2][0])
    assert result.rows[2][2][1] == OperatorReason.INCOMPLETE_WINDOW

    near_value, near_reason = result.rows[-1][0]
    assert near_reason == OperatorReason.READY
    assert near_value == pytest.approx(1.0, abs=5e-16)
    constant_value, constant_reason = result.rows[-1][1]
    assert math.isnan(constant_value)
    assert constant_reason == OperatorReason.DOMAIN_ERROR
    missing_value, missing_reason = result.rows[-1][2]
    assert missing_value == pytest.approx(1.0, abs=5e-16)
    assert missing_reason == OperatorReason.READY
    above_value, above_reason = result.rows[-1][3]
    assert above_value > 8.0 * sys.float_info.epsilon
    assert above_reason == OperatorReason.READY
    small_value, small_reason = result.rows[-1][4]
    assert 0.0 < small_value <= 8.0 * sys.float_info.epsilon
    assert (
        _exact_population_covariance(
            [-1.0, 0.0, 1.0], [1.0, -2.0, 1.0 + sys.float_info.epsilon]
        )
        != 0.0
    )
    assert small_reason == OperatorReason.READY
