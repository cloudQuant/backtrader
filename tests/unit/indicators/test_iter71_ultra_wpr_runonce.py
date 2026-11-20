"""Regression coverage for UltraWPR batch-state continuity (R71-037)."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.ultra_wpr_indicator import UltraWPRIndicator


_WPR_PERIOD = 13
_MINPERIOD = 74
_FIRST_OUTPUT = _MINPERIOD - 1
_PARAMS = {
    "wpr_period": _WPR_PERIOD,
    "w_method": "jjma",
    "start_length": 3,
    "xstep": 5,
    "xsteps_total": 10,
    "smooth_method": "jjma",
    "smooth_length": 3,
}
_SMOOTHER_METHODS = (
    ("jjma", "jjma"),
    ("sma", "smma"),
    ("smma", "ema"),
    ("ema", "sma"),
)


def _bars(length, missing_close=None):
    """Build fixed OHLC bars with a falling WPR transition at index 74."""
    close = [100.0 - 5.0 * math.sin(index * 0.1) for index in range(length)]
    if missing_close is not None:
        close[missing_close] = float("nan")
    return {
        "open": close,
        "high": [110.0] * length,
        "low": [90.0] * length,
        "close": close,
        "volume": [1.0] * length,
        "openinterest": [0.0] * length,
    }


def _run_cerebro(length, runonce, params=None, missing_close=None):
    """Capture complete UltraWPR lines from a real Cerebro execution."""
    bars = _bars(length, missing_close=missing_close)
    frame = pd.DataFrame(
        bars,
        index=pd.date_range("2024-01-01", periods=length, freq="D"),
    )
    captured = {}
    indicator_params = dict(_PARAMS)
    if params:
        indicator_params.update(params)

    class UltraWPRProbe(bt.Strategy):
        def __init__(self):
            self.indicator = UltraWPRIndicator(self.data, **indicator_params)

        def stop(self):
            captured["minperiod"] = self.indicator._minperiod
            captured["bulls"] = list(self.indicator.bulls.array)
            captured["bears"] = list(self.indicator.bears.array)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(UltraWPRProbe)
    cerebro.run(runonce=runonce, preload=True)
    return captured


class _ReferenceSmoother:
    """Small independent implementation of the public smoother semantics."""

    def __init__(self, method, period):
        self.method = str(method).lower()
        self.period = max(1, int(period))
        self.values = []
        self.state = None

    def update(self, value):
        value = float(value)
        if self.method in {"sma", "mode_sma"}:
            self.values.append(value)
            self.values = self.values[-self.period :]
            return sum(self.values) / len(self.values)
        if self.method in {"lwma", "mode_lwma", "jjma", "mode_jjma"}:
            self.values.append(value)
            self.values = self.values[-self.period :]
            weights = range(1, len(self.values) + 1)
            return sum(item * weight for item, weight in zip(self.values, weights)) / sum(
                weights
            )
        if self.method in {"smma", "mode_smma"}:
            if self.state is None:
                self.state = value
            else:
                self.state = (
                    (self.period - 1) * self.state + value
                ) / self.period
            return self.state
        alpha = 2.0 / (self.period + 1.0)
        if self.state is None:
            self.state = value
        else:
            self.state += alpha * (value - self.state)
        return self.state


def _reference_from_wpr(base_wpr, params=None):
    """Compute the full output from raw WPR values without production helpers."""
    options = dict(_PARAMS)
    if params:
        options.update(params)
    periods = [
        int(options["start_length"] + options["xstep"] * offset)
        for offset in range(int(options["xsteps_total"]) + 1)
    ]
    fan = [
        _ReferenceSmoother(options["w_method"], period) for period in periods
    ]
    output_bulls = _ReferenceSmoother(
        options["smooth_method"], options["smooth_length"]
    )
    output_bears = _ReferenceSmoother(
        options["smooth_method"], options["smooth_length"]
    )
    previous = [None] * len(periods)
    bulls = [float("nan")] * len(base_wpr)
    bears = [float("nan")] * len(base_wpr)

    for index in range(_FIRST_OUTPUT, len(base_wpr)):
        value = float(base_wpr[index])
        if math.isnan(value):
            continue

        current = [smoother.update(value) for smoother in fan]
        rising = sum(
            old is not None and new > old
            for old, new in zip(previous, current)
        )
        falling = sum(
            old is not None and not new > old
            for old, new in zip(previous, current)
        )
        bulls[index] = output_bulls.update(float(rising))
        bears[index] = output_bears.update(float(falling))
        previous = current

    return {"bulls": bulls, "bears": bears}


def _reference_for_bars(length, params=None, missing_close=None):
    """Independently calculate Williams %R, then the UltraWPR fan."""
    bars = _bars(length, missing_close=missing_close)
    period = int((params or {}).get("wpr_period", _WPR_PERIOD))
    base_wpr = [float("nan")] * length
    for index in range(period - 1, length):
        close = bars["close"][index]
        if math.isnan(close):
            continue
        highest = max(bars["high"][index - period + 1 : index + 1])
        lowest = min(bars["low"][index - period + 1 : index + 1])
        denominator = highest - lowest
        base_wpr[index] = (
            -100.0 * (highest - close) / denominator if denominator else 0.0
        )
    return _reference_from_wpr(base_wpr, params=params)


def _assert_line_matches(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if not math.isnan(expected_value):
            assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("length", (75, 900))
def test_ultra_wpr_cerebro_modes_match_reference_and_exact_warmup(length):
    expected = _reference_for_bars(length)
    runnext = _run_cerebro(length, runonce=False)
    runonce = _run_cerebro(length, runonce=True)

    assert runnext["minperiod"] == runonce["minperiod"] == _MINPERIOD
    assert all(math.isnan(value) for value in expected["bulls"][:_FIRST_OUTPUT])
    assert all(math.isnan(value) for value in expected["bears"][:_FIRST_OUTPUT])
    assert expected["bulls"][_FIRST_OUTPUT] == pytest.approx(0.0)
    assert expected["bears"][_FIRST_OUTPUT + 1] == pytest.approx(22.0 / 3.0)
    for line_name in ("bulls", "bears"):
        _assert_line_matches(runnext[line_name], expected[line_name])
        _assert_line_matches(runonce[line_name], expected[line_name])


def test_ultra_wpr_nan_close_is_missing_output_and_preserves_smoother_state():
    length = 120
    missing_index = 88
    expected = _reference_for_bars(length, missing_close=missing_index)
    runnext = _run_cerebro(
        length, runonce=False, missing_close=missing_index
    )
    runonce = _run_cerebro(
        length, runonce=True, missing_close=missing_index
    )

    assert runnext["minperiod"] == runonce["minperiod"] == _MINPERIOD
    for line_name in ("bulls", "bears"):
        _assert_line_matches(runnext[line_name], expected[line_name])
        _assert_line_matches(runonce[line_name], expected[line_name])
        assert math.isnan(runnext[line_name][missing_index])
        assert math.isnan(runonce[line_name][missing_index])
        assert math.isfinite(runnext[line_name][missing_index + 1])
        assert math.isfinite(runonce[line_name][missing_index + 1])


def _new_once_probe(base_wpr, params):
    """Create only the state and line-array surface consumed by ``once``."""
    options = dict(_PARAMS)
    options.update(params)
    periods = [
        int(options["start_length"] + options["xstep"] * offset)
        for offset in range(int(options["xsteps_total"]) + 1)
    ]
    size = len(base_wpr)
    return SimpleNamespace(
        p=SimpleNamespace(**options),
        _minperiod=_MINPERIOD,
        _periods=periods,
        _wpr_indicators=[
            SimpleNamespace(
                lines=[SimpleNamespace(array=list(base_wpr))]
            )
        ],
        lines=SimpleNamespace(
            bulls=SimpleNamespace(array=[float("nan")] * size),
            bears=SimpleNamespace(array=[float("nan")] * size),
        ),
    )


@pytest.mark.parametrize("w_method,smooth_method", _SMOOTHER_METHODS)
def test_ultra_wpr_once_replays_hidden_state_across_multiple_chunks(
    w_method, smooth_method
):
    length = 137
    base_wpr = [
        -48.0 + 34.0 * math.sin(index * 0.21) + 7.0 * math.cos(index * 0.053)
        for index in range(length)
    ]
    base_wpr[91] = float("nan")
    base_wpr[116] = float("nan")
    params = {"w_method": w_method, "smooth_method": smooth_method}
    expected = _reference_from_wpr(base_wpr, params=params)

    full = _new_once_probe(base_wpr, params)
    UltraWPRIndicator.once(full, _FIRST_OUTPUT, length)

    chunked = _new_once_probe(base_wpr, params)
    boundaries = (_FIRST_OUTPUT, 74, 78, 91, 92, 99, 116, 117, 125, length)
    for start, end in zip(boundaries, boundaries[1:]):
        UltraWPRIndicator.once(chunked, start, end)

    for line_name in ("bulls", "bears"):
        _assert_line_matches(getattr(full.lines, line_name).array, expected[line_name])
        _assert_line_matches(
            getattr(chunked.lines, line_name).array, expected[line_name]
        )
        _assert_line_matches(
            getattr(chunked.lines, line_name).array,
            getattr(full.lines, line_name).array,
        )
