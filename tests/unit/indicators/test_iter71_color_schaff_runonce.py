"""Regression coverage for Color Schaff Trend Cycle once() state continuity."""

import math
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.color_schaff_trend_cycle_indicator import (
    ColorSchaffTrendCycleIndicator,
)


FAST_XMA = 23
SLOW_XMA = 50
CYCLE = 10
MINPERIOD = 75
FIRST_VALID = MINPERIOD - 1
CLOSE = [100.0 + ((index % 16) - 8) * 2.5 for index in range(76)]


def _run_stc(close, runonce):
    """Return both STC lines and the EMA inputs from a real Cerebro run."""
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1.0] * len(close),
            "openinterest": [0.0] * len(close),
        },
        index=pd.date_range("2020-01-01", periods=len(close), freq="D"),
    )
    result = {}

    class STCProbeStrategy(bt.Strategy):
        def __init__(self):
            self.stc = ColorSchaffTrendCycleIndicator(self.data)

        def stop(self):
            result["minperiod"] = self.stc._minperiod
            result["value"] = [float(value) for value in self.stc.lines.value.array]
            result["color"] = [float(value) for value in self.stc.lines.color.array]
            result["fast"] = [float(value) for value in self.stc._fast.array]
            result["slow"] = [float(value) for value in self.stc._slow.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(STCProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _reference_stc(fast, slow):
    """Calculate STC from EMA arrays with the event-mode recursive formulas."""
    values = [float("nan")] * len(fast)
    colors = [float("nan")] * len(fast)

    for index in range(FIRST_VALID, min(len(fast), len(slow))):
        macd_values = [
            fast[index - offset] - slow[index - offset]
            for offset in range(CYCLE)
            if index - offset >= 0
        ]
        low_macd = min(macd_values)
        high_macd = max(macd_values)
        previous = values[index - 1] if index else 0.0
        if previous != previous:
            previous = 0.0

        current_macd = macd_values[0]
        st = (
            (current_macd - low_macd) / (high_macd - low_macd) * 100.0
            if high_macd != low_macd
            else previous
        )
        if index > 0:
            st = 0.5 * (st - previous) + previous

        st_values = [st]
        for offset in range(1, CYCLE):
            prior_index = index - offset
            if prior_index < 0:
                break
            prior_value = values[prior_index]
            if prior_value == prior_value:
                st_values.append(prior_value)
        low_st = min(st_values)
        high_st = max(st_values)
        previous_stc = values[index - 1] if index else 0.0
        if previous_stc != previous_stc:
            previous_stc = 0.0
        stc = (
            (st - low_st) / (high_st - low_st) * 200.0 - 100.0
            if high_st != low_st
            else previous_stc
        )
        if index > 0:
            stc = 0.5 * (stc - previous_stc) + previous_stc

        delta = stc - previous_stc if index > 0 else 0.0
        color = 4
        if stc > 0:
            if stc > 60.0:
                color = 7 if delta >= 0 else 6
            else:
                color = 5 if delta >= 0 else 4
        if stc < 0:
            if stc < -60.0:
                color = 0 if delta < 0 else 1
            else:
                color = 2 if delta < 0 else 3

        values[index] = stc
        colors[index] = color

    return values, colors


def _assert_lines_match(actual, expected, *, exact=False):
    assert len(actual) == len(expected)
    for index, (value, expected_value) in enumerate(zip(actual, expected)):
        assert math.isnan(value) == math.isnan(expected_value), f"NaN mismatch at {index}"
        if math.isnan(expected_value):
            continue
        if exact:
            assert value == expected_value, f"value mismatch at {index}"
        else:
            assert value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            ), f"value mismatch at {index}"


def _run_stc_once_chunks(fast, slow, chunks):
    """Call once() over adjacent slices and guard all out-of-slice cells."""
    sentinel = -999999.0
    values = [float("nan")] * FIRST_VALID + [
        sentinel - index for index in range(FIRST_VALID, len(fast))
    ]
    colors = [float("nan")] * FIRST_VALID + [
        sentinel - index for index in range(FIRST_VALID, len(fast))
    ]
    indicator = SimpleNamespace(
        _fast=SimpleNamespace(array=fast),
        _slow=SimpleNamespace(array=slow),
        lines=SimpleNamespace(
            value=SimpleNamespace(array=values),
            color=SimpleNamespace(array=colors),
        ),
        p=SimpleNamespace(cycle=CYCLE, high_level=60.0, low_level=-60.0),
    )

    for start, end in chunks:
        prior_values = values[:]
        prior_colors = colors[:]
        ColorSchaffTrendCycleIndicator.once(indicator, start, end)
        for index in range(len(values)):
            if not start <= index < end:
                assert values[index] == prior_values[index] or (
                    math.isnan(values[index]) and math.isnan(prior_values[index])
                )
                assert colors[index] == prior_colors[index] or (
                    math.isnan(colors[index]) and math.isnan(prior_colors[index])
                )

    return values, colors


def test_color_schaff_runonce_matches_runnext_and_independent_reference():
    """At minperiod 75, all 76 value/color outputs match event mode."""
    runnext = _run_stc(CLOSE, runonce=False)
    runonce = _run_stc(CLOSE, runonce=True)
    expected_value, expected_color = _reference_stc(runnext["fast"], runnext["slow"])

    assert runnext["minperiod"] == runonce["minperiod"] == MINPERIOD
    assert expected_value[75] == pytest.approx(50.0)
    assert expected_color[75] == 5.0
    assert all(math.isnan(value) for value in runnext["value"][:FIRST_VALID])
    assert all(math.isnan(value) for value in runnext["color"][:FIRST_VALID])
    _assert_lines_match(runnext["value"], expected_value)
    _assert_lines_match(runnext["color"], expected_color, exact=True)
    _assert_lines_match(runonce["value"], expected_value)
    _assert_lines_match(runonce["color"], expected_color, exact=True)


def test_color_schaff_once_contiguous_chunks_match_whole_range():
    """A cycle window crossing the [74, 75)/[75, 76) boundary stays intact."""
    runnext = _run_stc(CLOSE, runonce=False)
    whole_values, whole_colors = _run_stc_once_chunks(
        runnext["fast"], runnext["slow"], [(FIRST_VALID, len(CLOSE))]
    )
    chunked_values, chunked_colors = _run_stc_once_chunks(
        runnext["fast"], runnext["slow"], [(FIRST_VALID, 75), (75, 76)]
    )
    expected_value, expected_color = _reference_stc(runnext["fast"], runnext["slow"])

    _assert_lines_match(chunked_values, whole_values)
    _assert_lines_match(chunked_colors, whole_colors, exact=True)
    _assert_lines_match(chunked_values, expected_value)
    _assert_lines_match(chunked_colors, expected_color, exact=True)


def test_color_schaff_nan_input_matches_runnext_and_runonce():
    """A NaN source value at the last bar retains event-mode NaN behavior."""
    close = CLOSE[:-1] + [float("nan")]
    runnext = _run_stc(close, runonce=False)
    runonce = _run_stc(close, runonce=True)
    expected_value, expected_color = _reference_stc(runnext["fast"], runnext["slow"])

    assert math.isnan(expected_value[75])
    _assert_lines_match(runnext["value"], expected_value)
    _assert_lines_match(runnext["color"], expected_color, exact=True)
    _assert_lines_match(runonce["value"], expected_value)
    _assert_lines_match(runonce["color"], expected_color, exact=True)
