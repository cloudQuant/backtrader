"""Cerebro coverage for BlauErgodicMDI's five color-index states (R71-041)."""

import math

import backtrader as bt
import pandas as pd
import pytest


# Color meanings and palette order follow the public MQL5 CodeBase source:
# https://www.mql5.com/en/code/1958
_COLOR_STATES = frozenset((0.0, 1.0, 2.0, 3.0, 4.0))
_INDICATOR_PARAMS = {
    "xlength": 3,
    "xlength1": 2,
    "xlength2": 2,
    "xlength3": 2,
}


def _close_sequence():
    """Create price steps that exercise all five histogram color states."""
    return (
        [100.0] * 18
        + [110.0] * 12
        + [90.0] * 15
        + [100.0] * 12
        + [90.0] * 12
        + [110.0] * 15
        + [100.0] * 18
    )


def _run_indicator(closes, runonce):
    close_values = list(closes)
    frame = pd.DataFrame(
        {
            "open": close_values,
            "high": [value + 0.5 for value in close_values],
            "low": [value - 0.5 for value in close_values],
            "close": close_values,
            "volume": [1.0] * len(close_values),
            "openinterest": [0.0] * len(close_values),
        },
        index=pd.date_range("2024-01-01", periods=len(close_values), freq="D"),
    )
    result = {}

    class ColorProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.BlauErgodicMDI(
                self.data, **_INDICATOR_PARAMS
            )

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["hist"] = [float(value) for value in self.indicator.hist.array]
            result["color_idx"] = [
                float(value) for value in self.indicator.color_idx.array
            ]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ColorProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _expected_color_indices(hist, first_calc_index):
    """Apply the MQL5 color-index mapping only when both bars are finite."""
    result = [float("nan")] * len(hist)
    for index in range(max(1, first_calc_index), len(hist)):
        current = hist[index]
        previous = hist[index - 1]
        if not math.isfinite(current) or not math.isfinite(previous):
            continue

        color = 2.0
        if current > 0.0:
            if current > previous:
                color = 4.0
            elif current < previous:
                color = 3.0
        elif current < 0.0:
            if current < previous:
                color = 0.0
            elif current > previous:
                color = 1.0
        result[index] = color
    return result


def _assert_same_values(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if math.isfinite(expected_value):
            assert actual_value == pytest.approx(expected_value)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_blau_ergodic_mdi_color_idx_matches_all_five_mql5_states(runonce):
    result = _run_indicator(_close_sequence(), runonce=runonce)
    expected = _expected_color_indices(
        result["hist"], result["minperiod"] - 1
    )
    color_idx = result["color_idx"]
    first_hist = next(
        index for index, value in enumerate(result["hist"]) if math.isfinite(value)
    )

    assert math.isnan(color_idx[first_hist])
    assert all(math.isnan(value) for value in color_idx[: result["minperiod"] - 1])
    assert set(value for value in expected if math.isfinite(value)) == _COLOR_STATES
    _assert_same_values(color_idx, expected)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_blau_ergodic_mdi_color_idx_boundary_needs_a_finite_previous_hist(runonce):
    long_result = _run_indicator(_close_sequence(), runonce=runonce)
    minperiod = long_result["minperiod"]

    short_result = _run_indicator(_close_sequence()[: minperiod - 1], runonce=runonce)
    boundary_result = _run_indicator(_close_sequence()[:minperiod], runonce=runonce)

    assert all(math.isnan(value) for value in short_result["color_idx"])
    assert math.isfinite(boundary_result["hist"][-2])
    assert math.isfinite(boundary_result["hist"][-1])
    assert boundary_result["color_idx"][-1] == 2.0


@pytest.mark.parametrize(
    "current, previous, expected",
    (
        (1.0, 2.0, 3.0),
        (1.0, 0.5, 4.0),
        (0.0, 1.0, 2.0),
        (-1.0, -2.0, 1.0),
        (-2.0, -1.0, 0.0),
        (-1.0, -1.0, 2.0),
        (1.0, 1.0, 2.0),
    ),
)
def test_blau_ergodic_mdi_color_idx_uses_upstream_five_state_mapping(
    current, previous, expected
):
    color = bt.indicators.BlauErgodicMDI._color_idx_from_hist(current, previous)
    assert color == expected


@pytest.mark.parametrize(
    "current, previous",
    (
        (float("nan"), 1.0),
        (1.0, float("nan")),
        (float("inf"), 1.0),
        (1.0, float("-inf")),
    ),
)
def test_blau_ergodic_mdi_color_idx_requires_both_hist_values(
    current, previous
):
    color = bt.indicators.BlauErgodicMDI._color_idx_from_hist(current, previous)
    assert math.isnan(color)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_blau_ergodic_mdi_missing_hist_or_previous_hist_keeps_color_nan(runonce):
    closes = _close_sequence()
    missing_index = 72
    closes[missing_index] = float("nan")
    result = _run_indicator(closes, runonce=runonce)
    expected = _expected_color_indices(
        result["hist"], result["minperiod"] - 1
    )

    _assert_same_values(result["color_idx"], expected)
    assert math.isfinite(result["hist"][missing_index - 1])
    assert math.isfinite(result["color_idx"][missing_index - 1])
    assert math.isnan(result["hist"][missing_index])
    assert math.isnan(result["color_idx"][missing_index])

    # These recursive EMAs keep a NaN after the missing close, so this input
    # cannot recover later in the same run; don't synthesize a color meanwhile.
    assert all(not math.isfinite(value) for value in result["hist"][missing_index:])
    assert all(math.isnan(value) for value in result["color_idx"][missing_index:])
