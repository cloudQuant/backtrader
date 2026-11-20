"""Cerebro execution-mode coverage for the IAMMA recursive seed (R71-033)."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _reference_iamma(closes, ma_period, price_shift, point):
    """Calculate the minperiod seed and subsequent recurrence independently."""
    values = [float("nan")] * len(closes)
    if len(closes) < 2:
        return values

    period = max(int(ma_period), 1)
    offset = float(point) * float(price_shift)
    previous = float(closes[1])
    values[1] = previous
    for index in range(2, len(closes)):
        price = float(closes[index])
        amma = (((period - 1) * (previous - offset)) + price) / period
        previous = amma + offset
        values[index] = previous

    return values


def _run_iamma(closes, *, runonce, ma_period=3, price_shift=0, point=0.01):
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    result = {"next_lengths": []}

    class IAMMAProbe(bt.Strategy):
        def __init__(self):
            self.iamma = bt.indicators.IAMMAIndicator(
                self.data,
                ma_period=ma_period,
                price_shift=price_shift,
                point=point,
            )

        def next(self):
            result["next_lengths"].append(len(self.data))

        def stop(self):
            result["minperiod"] = self.iamma._minperiod
            result["values"] = [float(value) for value in self.iamma.value.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(IAMMAProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_nan_aware_series(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
@pytest.mark.parametrize(
    "closes, expected_next_lengths",
    [
        ([10.0], []),
        ([10.0, 11.0], [2]),
        ([10.0, 11.0, 12.0], [2, 3]),
    ],
    ids=("shorter-than-minperiod", "at-minperiod", "after-minperiod"),
)
def test_iamma_seeds_at_first_real_next_and_keeps_minperiod(
    closes, expected_next_lengths, runonce
):
    expected = _reference_iamma(closes, ma_period=3, price_shift=0, point=0.01)
    result = _run_iamma(closes, runonce=runonce)

    assert result["minperiod"] == 2
    assert result["next_lengths"] == expected_next_lengths
    _assert_nan_aware_series(result["values"], expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
@pytest.mark.parametrize(
    "closes, price_shift, point",
    [
        ([100.0, 103.0, 106.0, 101.0, 108.0, 110.0], 0, 0.01),
        ([100.0, 103.0, 106.0, 101.0, 108.0, 110.0], 7, 0.25),
        ([100.0, 103.0, float("nan"), 101.0, 108.0, 110.0], 7, 0.25),
        ([100.0, float("nan"), 106.0, 101.0, 108.0, 110.0], 7, 0.25),
    ],
    ids=("unshifted", "shifted-seed-is-close", "missing-after-seed", "missing-seed"),
)
def test_iamma_full_sequence_matches_nan_aware_reference(
    closes, price_shift, point, runonce
):
    expected = _reference_iamma(
        closes, ma_period=3, price_shift=price_shift, point=point
    )
    result = _run_iamma(
        closes,
        runonce=runonce,
        ma_period=3,
        price_shift=price_shift,
        point=point,
    )

    assert result["minperiod"] == 2
    _assert_nan_aware_series(result["values"], expected)

    if price_shift and not math.isnan(float(closes[1])):
        assert result["values"][1] == pytest.approx(float(closes[1]))
