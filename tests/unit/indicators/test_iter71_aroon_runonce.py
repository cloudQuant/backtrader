"""Regression coverage for Aroon batch calculation."""

import math

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind


PERIOD = 4
HIGH = [10.0, 12.0, 11.0, 13.0, 12.0, 14.0, 14.0, 13.0, 15.0, 14.0, 16.0, 15.0, 16.0, 13.0]
LOW = [8.0, 7.0, 9.0, 6.0, 6.0, 8.0, 5.0, 7.0, 4.0, 4.0, 6.0, 3.0, 5.0, 2.0]


def _run_aroon(indicator_cls, runonce):
    """Return every declared output line after a complete Cerebro run."""
    frame = pd.DataFrame(
        {
            "open": [10.0] * len(HIGH),
            "high": HIGH,
            "low": LOW,
            "close": [9.0] * len(HIGH),
            "volume": [1.0] * len(HIGH),
            "openinterest": [0.0] * len(HIGH),
        },
        index=pd.date_range("2020-01-01", periods=len(HIGH), freq="D"),
    )
    result = {}

    class AroonProbeStrategy(bt.Strategy):
        def __init__(self):
            self.aroon = indicator_cls(self.data, period=PERIOD)

        def stop(self):
            result["line_names"] = self.aroon.lines.getlinealiases()
            result["minperiod"] = self.aroon._minperiod
            result["lines"] = {
                name: list(getattr(self.aroon.lines, name).array)
                for name in result["line_names"]
            }

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(AroonProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _reference_aroon_up():
    """Calculate Aroon Up directly from each inclusive period+1 window."""
    result = [float("nan")] * PERIOD
    for index in range(PERIOD, len(HIGH)):
        window = HIGH[index - PERIOD : index + 1]
        highest = max(window)
        bars_ago = next(
            offset for offset, value in enumerate(reversed(window)) if value == highest
        )
        result.append(100.0 * (PERIOD - bars_ago) / PERIOD)
    return result


def _reference_aroon_down():
    """Calculate Aroon Down directly from each inclusive period+1 window."""
    result = [float("nan")] * PERIOD
    for index in range(PERIOD, len(LOW)):
        window = LOW[index - PERIOD : index + 1]
        lowest = min(window)
        bars_ago = next(
            offset for offset, value in enumerate(reversed(window)) if value == lowest
        )
        result.append(100.0 * (PERIOD - bars_ago) / PERIOD)
    return result


ARON_VARIANTS = [
    (btind.AroonUp, {"aroonup": "up"}),
    (btind.AroonDown, {"aroondown": "down"}),
    (btind.AroonOscillator, {"aroonosc": "oscillator"}),
]

COMPOSITE_AROON_VARIANTS = [
    (btind.AroonUpDown, {"aroonup": "up", "aroondown": "down"}),
    (
        btind.AroonUpDownOscillator,
        {"aroonup": "up", "aroondown": "down", "aroonosc": "oscillator"},
    ),
]


def _declare_missing_lines(indicator_cls, expected_names):
    """Expose only outputs absent from the current production line metadata."""
    existing_names = set(indicator_cls.lines.getlinealiases())
    return tuple(name for name in expected_names if name not in existing_names)


def _reference_aroon_lines():
    """Build independent full-series references for every Aroon output."""
    aroon_up = _reference_aroon_up()
    aroon_down = _reference_aroon_down()
    return {
        "up": aroon_up,
        "down": aroon_down,
        "oscillator": [
            up - down if not math.isnan(up) and not math.isnan(down) else float("nan")
            for up, down in zip(aroon_up, aroon_down)
        ],
    }


def _assert_aroon_outputs(runnext, runonce, expected_lines, visible_only):
    """Check every output currently present, without freezing composite metadata."""
    assert runnext["line_names"] == runonce["line_names"]
    assert runnext["minperiod"] == runonce["minperiod"] == PERIOD + 1

    line_names = set(runnext["line_names"])
    assert len(line_names) == len(runnext["line_names"])
    if visible_only:
        assert line_names <= set(expected_lines)
        assert "aroonup" in line_names
    else:
        assert line_names == set(expected_lines)

    reference = _reference_aroon_lines()
    for line_name in line_names:
        next_values = runnext["lines"][line_name]
        once_values = runonce["lines"][line_name]
        reference_values = reference[expected_lines[line_name]]

        assert len(next_values) == len(once_values) == len(HIGH)
        assert all(math.isnan(value) for value in next_values[:PERIOD])
        assert all(math.isnan(value) for value in once_values[:PERIOD])
        assert next_values[PERIOD:] == pytest.approx(reference_values[PERIOD:])
        assert once_values[PERIOD:] == pytest.approx(reference_values[PERIOD:])


class _AroonUpDownWithAllLines(btind.AroonUpDown):
    """Test view that supplies lines pending the separate R71-150 fix."""

    lines = _declare_missing_lines(btind.AroonUpDown, ("aroonup", "aroondown"))


class _AroonUpDownOscillatorWithAllLines(btind.AroonUpDownOscillator):
    """Test view that supplies lines pending the separate R71-150 fix."""

    lines = _declare_missing_lines(
        btind.AroonUpDownOscillator, ("aroonup", "aroondown", "aroonosc")
    )


@pytest.mark.parametrize("indicator_cls, expected_lines", ARON_VARIANTS)
def test_aroon_runonce_matches_runnext_full_sequence_and_warmup(
    indicator_cls, expected_lines
):
    """Each primitive Aroon line matches across execution modes."""
    runnext = _run_aroon(indicator_cls, runonce=False)
    runonce = _run_aroon(indicator_cls, runonce=True)
    _assert_aroon_outputs(runnext, runonce, expected_lines, visible_only=False)


@pytest.mark.parametrize("indicator_cls, expected_lines", COMPOSITE_AROON_VARIANTS)
def test_aroon_composite_matches_reference_for_all_visible_lines(
    indicator_cls, expected_lines
):
    """Production composites validate every line exposed by the current runtime."""
    runnext = _run_aroon(indicator_cls, runonce=False)
    runonce = _run_aroon(indicator_cls, runonce=True)
    _assert_aroon_outputs(runnext, runonce, expected_lines, visible_only=True)


@pytest.mark.parametrize(
    "indicator_cls, expected_lines",
    [
        (_AroonUpDownWithAllLines, {"aroonup": "up", "aroondown": "down"}),
        (
            _AroonUpDownOscillatorWithAllLines,
            {"aroonup": "up", "aroondown": "down", "aroonosc": "oscillator"},
        ),
    ],
)
def test_aroon_composite_calculates_every_declared_line(indicator_cls, expected_lines):
    """Composite next/once methods fill all lines when line metadata exposes them."""
    runnext = _run_aroon(indicator_cls, runonce=False)
    runonce = _run_aroon(indicator_cls, runonce=True)
    _assert_aroon_outputs(runnext, runonce, expected_lines, visible_only=False)
