"""R71-042 coverage for the ZPF mirror line binding."""

import math

import backtrader as bt
import pandas as pd
import pytest


_PERIOD = 4


def _synthetic_inputs():
    closes = [100.0 + ((index * 7) % 11) * 0.4 + index * 0.01 for index in range(40)]
    volumes = [1.0 + index % 4 for index in range(len(closes))]
    closes[14] = float("nan")
    volumes[29] = float("nan")
    return closes, volumes


def _sma(values, period):
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        if not any(value != value for value in window):
            result[index] = math.fsum(window) / period
    return result


def _reference_zpf(closes, volumes, period):
    """Calculate the documented volume-weighted SMA spread independently."""
    short_average = _sma(closes, period)
    long_average = _sma(closes, 2 * period)
    average_volume = _sma(volumes, period)
    expected = []

    for short_value, long_value, volume_value in zip(
        short_average, long_average, average_volume
    ):
        if any(value != value for value in (short_value, long_value, volume_value)):
            expected.append(float("nan"))
        else:
            expected.append(volume_value * (short_value - long_value) / 2.0)

    return expected


def _run_zpf(closes, volumes, *, runonce):
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    result = {}

    class ZPFProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.ZPFIndicator(
                self.data, xlength=_PERIOD
            )

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            data_length = len(closes)
            result["line1"] = [
                float(value) for value in self.indicator.line1.array[:data_length]
            ]
            result["line2"] = [
                float(value) for value in self.indicator.line2.array[:data_length]
            ]
            result["zpf"] = [
                float(value) for value in self.indicator.zpf.array[:data_length]
            ]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ZPFProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_series_matches(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), f"index {index}: {actual_value!r}"
        else:
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            ), f"index {index}"


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
def test_zpf_and_line1_match_independent_reference_with_missing_inputs(runonce):
    closes, volumes = _synthetic_inputs()
    expected_zpf = _reference_zpf(closes, volumes, _PERIOD)
    result = _run_zpf(closes, volumes, runonce=runonce)
    expected_line1 = [
        -value if math.isfinite(value) else float("nan")
        for value in expected_zpf
    ]

    assert result["minperiod"] == 4 * _PERIOD + 1
    assert any(math.isfinite(value) for value in expected_zpf)
    _assert_series_matches(result["zpf"], expected_zpf)
    _assert_series_matches(result["line1"], expected_line1)
    _assert_series_matches(result["line2"], expected_zpf)

    for zpf, line1 in zip(result["zpf"], result["line1"]):
        if math.isfinite(zpf):
            assert line1 == pytest.approx(-zpf, rel=1e-12, abs=1e-12)
        else:
            assert math.isnan(line1)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
def test_zpf_short_history_keeps_unavailable_lines_nan(runonce):
    closes = [100.0 + index * 0.25 for index in range(2 * _PERIOD - 1)]
    volumes = [1.0 + index for index in range(len(closes))]

    result = _run_zpf(closes, volumes, runonce=runonce)

    assert result["minperiod"] == 4 * _PERIOD + 1
    assert all(math.isnan(value) for value in result["zpf"])
    assert all(math.isnan(value) for value in result["line1"])
    assert all(math.isnan(value) for value in result["line2"])
