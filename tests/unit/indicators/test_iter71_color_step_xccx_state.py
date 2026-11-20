"""Behavioral checks for ColorStepXCCX startup and streaming state."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.color_step_xccx_indicator import (
    ColorStepXCCXIndicator,
)


_PARAMS = {
    "dsmooth_method": "sma",
    "dperiod": 2,
    "msmooth_method": "sma",
    "mperiod": 2,
    "step_size_fast": 5,
    "step_size_slow": 30,
}


class _SegmentedColorStepXCCX(ColorStepXCCXIndicator):
    """Exercise contiguous, short once() ranges inside Cerebro runonce."""

    def once(self, start, end):
        for chunk_start in range(start, end, 3):
            ColorStepXCCXIndicator.once(self, chunk_start, min(chunk_start + 3, end))


def _run(prices, runonce, indicator_cls=ColorStepXCCXIndicator):
    frame = pd.DataFrame(
        {"close": prices},
        index=pd.date_range("2021-01-01", periods=len(prices), freq="D"),
    )

    class Capture(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_cls(self.data, **_PARAMS)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Capture)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    return strategy.indicator


def _channel_reference(up_values, dn_values, first_index, fast_step, slow_step):
    """Compute channels from oscillator inputs without sentinel state."""
    outputs = ([float("nan")] * len(up_values), [float("nan")] * len(up_values))
    seeded = False
    fmin1 = fmax1 = smin1 = smax1 = None
    ftrend = strend = 0

    for index in range(len(up_values)):
        up = float(up_values[index])
        down = float(dn_values[index])
        if not math.isfinite(up) or not math.isfinite(down) or down <= 0.0:
            continue

        xccx = 100.0 * up / down
        if not math.isfinite(xccx):
            continue

        fmax0 = xccx + 2.0 * fast_step
        fmin0 = xccx - 2.0 * fast_step
        smax0 = xccx + 2.0 * slow_step
        smin0 = xccx - 2.0 * slow_step

        if not seeded:
            fmin1, fmax1 = fmin0, fmax0
            smin1, smax1 = smin0, smax0
            seeded = True
            continue

        if xccx > fmax1:
            ftrend = 1
        if xccx < fmin1:
            ftrend = -1
        if ftrend > 0 and fmin0 < fmin1:
            fmin0 = fmin1
        if ftrend < 0 and fmax0 > fmax1:
            fmax0 = fmax1

        if xccx > smax1:
            strend = 1
        if xccx < smin1:
            strend = -1
        if strend > 0 and smin0 < smin1:
            smin0 = smin1
        if strend < 0 and smax0 > smax1:
            smax0 = smax1

        if index >= first_index:
            if ftrend > 0:
                outputs[0][index] = fmin0 + fast_step
            elif ftrend < 0:
                outputs[0][index] = fmax0 - fast_step

            if strend > 0:
                outputs[1][index] = smin0 + slow_step
            elif strend < 0:
                outputs[1][index] = smax0 - slow_step

        fmin1, fmax1 = fmin0, fmax0
        smin1, smax1 = smin0, smax0

    return outputs


def _assert_matches(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        got = float(got)
        if math.isnan(want):
            assert math.isnan(got), f"index {index}: expected NaN, got {got}"
        else:
            assert got == pytest.approx(want), f"index {index}"


def _assert_matches_reference(indicator):
    expected_fast, expected_slow = _channel_reference(
        indicator._up.array,
        indicator._dn.array,
        indicator._minperiod - 1,
        _PARAMS["step_size_fast"],
        _PARAMS["step_size_slow"],
    )
    _assert_matches(indicator.mplus.array, expected_fast)
    _assert_matches(indicator.mminus.array, expected_slow)
    assert all(
        float(value) not in (-1000004.0, -1000029.0)
        for line in (indicator.mplus.array, indicator.mminus.array)
        for value in line
        if math.isfinite(float(value))
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_unknown_direction_is_nan_until_a_real_channel_forms(runonce):
    # A steady oscillator has a real seed, but it never crosses the seeded
    # bounds and therefore has no basis for claiming either trend direction.
    prices = list(range(10, 50))
    indicator = _run(prices, runonce)

    assert indicator._minperiod == _PARAMS["dperiod"] + _PARAMS["mperiod"] + 5
    first_eligible = indicator._minperiod - 1
    assert math.isnan(float(indicator.mplus.array[first_eligible]))
    assert math.isnan(float(indicator.mminus.array[first_eligible]))
    assert all(math.isnan(float(value)) for value in indicator.mplus.array)
    assert all(math.isnan(float(value)) for value in indicator.mminus.array)
    _assert_matches_reference(indicator)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_channel_values_follow_independent_state_reference(runonce):
    prices = list(range(10, 21)) + list(range(19, 9, -1)) + list(range(11, 21))
    indicator = _run(prices, runonce)

    _assert_matches_reference(indicator)
    finite_fast = [
        float(value)
        for value in indicator.mplus.array
        if math.isfinite(float(value))
    ]
    assert any(value < 0 for value in finite_fast)
    assert any(value > 0 for value in finite_fast)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_warmup_advances_real_state_without_publishing_lines(runonce):
    # The oscillator turns down before the channel's public minperiod. The
    # first published bar should use that real warm-up state, while earlier
    # channel outputs remain unavailable.
    prices = [10, 11, 12, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 2, 3, 4, 5]
    indicator = _run(prices, runonce)

    first_eligible = indicator._minperiod - 1
    assert all(
        math.isnan(float(value))
        for line in (indicator.mplus.array, indicator.mminus.array)
        for value in line[:first_eligible]
    )
    assert float(indicator.mplus.array[first_eligible]) == pytest.approx(-95.0)
    _assert_matches_reference(indicator)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_zero_deviation_is_missing_not_a_neutral_oscillator(runonce):
    indicator = _run([10.0] * 24, runonce)

    assert all(math.isnan(float(value)) for value in indicator.mplus.array)
    assert all(math.isnan(float(value)) for value in indicator.mminus.array)
    _assert_matches_reference(indicator)


def test_once_keeps_state_across_contiguous_segments_and_missing_prices():
    prices = (
        list(range(10, 21))
        + list(range(19, 14, -1))
        + [float("nan")]
        + [17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41]
    )
    expected = _run(prices, runonce=False)
    segmented = _run(prices, runonce=True, indicator_cls=_SegmentedColorStepXCCX)

    _assert_matches_reference(expected)
    _assert_matches_reference(segmented)
    _assert_matches(segmented.mplus.array, expected.mplus.array)
    _assert_matches(segmented.mminus.array, expected.mminus.array)

    # NaN in the source close is genuine missing input. It must leave the
    # channel state untouched, and no output may claim a value on invalid bars.
    missing_input_indexes = [
        index for index, price in enumerate(prices) if math.isnan(price)
    ]
    assert missing_input_indexes == [16]
    assert math.isnan(float(segmented.mplus.array[16]))
    assert math.isnan(float(segmented.mminus.array[16]))
    assert math.isfinite(float(segmented.mplus.array[-1]))
    assert float(segmented.mplus.array[-1]) == pytest.approx(95.0)
