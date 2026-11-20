"""Regression coverage for XRVI recursive once state (R71-037)."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.xrvi_indicator import XRVIIndicator


DEFAULTS = {
    "rvi_method": "jurx",
    "rvi_period": 10,
    "rvi_phase": 15,
    "sign_method": "jurx",
    "sign_period": 5,
    "sign_phase": 15,
}


def _bars(length, nan_index=None):
    bars = []
    bodies = (0.4, -0.7, 1.1, -0.3, 0.8, -1.0, 0.2)
    for index in range(length):
        open_ = 100.0 + index * 0.31 + (index % 3) * 0.09
        close = open_ + bodies[index % len(bodies)]
        if index == nan_index:
            close = float("nan")
        high = max(open_, close) + 1.1 + (index % 4) * 0.13
        low = min(open_, close) - 0.9 - (index % 2) * 0.17
        bars.append((open_, high, low, close))
    return bars


def _run_xrvi(length, runonce, params=None, nan_index=None):
    params = dict(DEFAULTS if params is None else params)
    bars = _bars(length, nan_index=nan_index)
    frame = pd.DataFrame(
        {
            "open": [bar[0] for bar in bars],
            "high": [bar[1] for bar in bars],
            "low": [bar[2] for bar in bars],
            "close": [bar[3] for bar in bars],
            "volume": [1.0] * length,
            "openinterest": [0.0] * length,
        },
        index=pd.date_range("2024-01-01", periods=length, freq="D"),
    )
    result = {}

    class XRVIProbeStrategy(bt.Strategy):
        def __init__(self):
            self.xrvi = XRVIIndicator(self.data, **params)

        def stop(self):
            result["minperiod"] = self.xrvi._minperiod
            result["xrvi"] = [float(value) for value in self.xrvi.lines.xrvi.array]
            result["signal"] = [
                float(value) for value in self.xrvi.lines.signal.array
            ]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(XRVIProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    result["bars"] = bars
    return result


def _moving_average(values, method, period, previous):
    if not values:
        return float("nan")

    mode = str(method).lower()
    value = float(values[-1])
    if mode in {"ema", "mode_ema"}:
        if previous is None or math.isnan(previous):
            return value
        alpha = 2.0 / (period + 1.0)
        return previous + alpha * (value - previous)
    if mode in {"smma", "mode_smma"}:
        if previous is None or math.isnan(previous):
            return value
        return ((period - 1.0) * previous + value) / period
    if mode in {"sma", "mode_sma"}:
        return sum(values) / len(values)
    weights = range(1, len(values) + 1)
    return sum(item * weight for item, weight in zip(values, weights)) / sum(weights)


def _reference_xrvi(bars, params=None):
    params = dict(DEFAULTS if params is None else params)
    length = len(bars)
    rvi_period = max(1, int(params["rvi_period"]))
    sign_period = max(1, int(params["sign_period"]))
    first_valid = rvi_period + sign_period + 2
    raw = []
    for open_, high, low, close in bars:
        denom = high - low
        raw.append((close - open_) / denom if denom else 0.0)

    xrvi = [float("nan")] * length
    signal = [float("nan")] * length
    for index in range(first_valid, length):
        raw_start = max(0, index - rvi_period + 1)
        previous_xrvi = xrvi[index - 1] if index else None
        current_xrvi = _moving_average(
            raw[raw_start : index + 1],
            params["rvi_method"],
            rvi_period,
            previous_xrvi,
        )
        xrvi[index] = current_xrvi

        signal_start = max(0, index - sign_period + 1)
        signal_values = [
            value
            for value in xrvi[signal_start:index]
            if not math.isnan(value)
        ]
        signal_values.append(current_xrvi)
        previous_signal = signal[index - 1] if index else None
        signal[index] = _moving_average(
            signal_values,
            params["sign_method"],
            sign_period,
            previous_signal,
        )

    return {
        "minperiod": rvi_period + sign_period + 3,
        "xrvi": xrvi,
        "signal": signal,
    }


def _assert_line_matches(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if not math.isnan(expected_value):
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


class _Line:
    def __init__(self, values):
        self.array = list(values)


class _OnceProbe:
    _raw_rvi_at = XRVIIndicator._raw_rvi_at
    _window_ma = XRVIIndicator._window_ma

    def __init__(self, bars, params):
        length = len(bars)
        self.data = SimpleNamespace(
            open=_Line([bar[0] for bar in bars]),
            high=_Line([bar[1] for bar in bars]),
            low=_Line([bar[2] for bar in bars]),
            close=_Line([bar[3] for bar in bars]),
        )
        self.p = SimpleNamespace(**params)
        self.lines = SimpleNamespace(
            xrvi=_Line([float("nan")] * length),
            signal=_Line([float("nan")] * length),
        )


@pytest.mark.parametrize(
    "params",
    [
        DEFAULTS,
        {**DEFAULTS, "rvi_method": "ema", "sign_method": "ema"},
        {**DEFAULTS, "rvi_method": "sma", "sign_method": "smma"},
    ],
)
def test_xrvi_real_cerebro_matches_independent_reference(params):
    bars = _bars(40)
    expected = _reference_xrvi(bars, params)
    runnext = _run_xrvi(len(bars), runonce=False, params=params)
    runonce = _run_xrvi(len(bars), runonce=True, params=params)
    first_valid = expected["minperiod"] - 1

    for result in (runnext, runonce):
        assert result["minperiod"] == expected["minperiod"]
        assert all(math.isnan(value) for value in result["xrvi"][:first_valid])
        assert all(math.isnan(value) for value in result["signal"][:first_valid])
        for line_name in ("xrvi", "signal"):
            _assert_line_matches(result[line_name], expected[line_name])


def test_xrvi_default_first_valid_bar_uses_only_published_warmup_state():
    bars = _bars(19)
    expected = _reference_xrvi(bars)
    runnext = _run_xrvi(len(bars), runonce=False)
    runonce = _run_xrvi(len(bars), runonce=True)
    first_valid = 17

    assert runnext["minperiod"] == runonce["minperiod"] == 18
    assert first_valid == runnext["minperiod"] - 1
    assert math.isnan(expected["xrvi"][first_valid - 1])
    assert math.isnan(expected["signal"][first_valid - 1])
    assert runnext["xrvi"][first_valid] == pytest.approx(
        runonce["xrvi"][first_valid]
    )
    assert runnext["signal"][first_valid] == pytest.approx(
        expected["signal"][first_valid]
    )
    assert runonce["signal"][first_valid] == pytest.approx(
        expected["signal"][first_valid]
    )


def test_xrvi_short_history_stays_in_warmup():
    result = _run_xrvi(17, runonce=True)
    assert result["minperiod"] == 18
    for line_name in ("xrvi", "signal"):
        assert all(math.isnan(value) for value in result[line_name])


def test_xrvi_once_consecutive_ranges_match_next_and_reference():
    params = {**DEFAULTS, "rvi_method": "ema", "sign_method": "smma"}
    bars = _bars(40)
    first_valid = params["rvi_period"] + params["sign_period"] + 2
    expected = _reference_xrvi(bars, params)
    next_values = _run_xrvi(len(bars), runonce=False, params=params)
    full = _OnceProbe(bars, params)
    chunked = _OnceProbe(bars, params)

    XRVIIndicator.once(full, first_valid, len(bars))
    boundaries = (first_valid, first_valid + 1, first_valid + 6, len(bars))
    for start, end in zip(boundaries, boundaries[1:]):
        XRVIIndicator.once(chunked, start, end)

    for line_name in ("xrvi", "signal"):
        values = getattr(chunked.lines, line_name).array
        _assert_line_matches(values, expected[line_name])
        _assert_line_matches(values, getattr(full.lines, line_name).array)
        _assert_line_matches(values, next_values[line_name])


def test_xrvi_nan_gap_matches_next_once_and_independent_reference():
    params = {**DEFAULTS, "rvi_method": "ema", "sign_method": "jurx"}
    bars = _bars(44, nan_index=25)
    expected = _reference_xrvi(bars, params)
    runnext = _run_xrvi(len(bars), runonce=False, params=params, nan_index=25)
    runonce = _run_xrvi(len(bars), runonce=True, params=params, nan_index=25)

    for result in (runnext, runonce):
        for line_name in ("xrvi", "signal"):
            _assert_line_matches(result[line_name], expected[line_name])
