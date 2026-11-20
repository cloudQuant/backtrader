"""Actual Cerebro regression coverage for DigitalMacd signal warm-up (R71-040)."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_SIGNAL_PERIOD = 5
_BAR_COUNT = 210
_CLOSES = tuple(
    100.0 + index * 0.37 + math.sin(index * 0.33) * 4.0 + math.cos(index * 0.117) * 1.7
    for index in range(_BAR_COUNT)
)


class _DigitalMacdProbe(bt.Strategy):
    params = (("signal_period", _SIGNAL_PERIOD),)

    def __init__(self):
        self.indicator = bt.indicators.DigitalMacd(
            self.data, signal_period=self.p.signal_period
        )

    def start(self):
        self.strategy_phases = []

    def prenext(self):
        self.strategy_phases.append(("prenext", len(self.data)))

    def nextstart(self):
        self.strategy_phases.append(("nextstart", len(self.data)))

    def next(self):
        self.strategy_phases.append(("next", len(self.data)))


def _frame_for_closes(closes):
    start = datetime(2025, 1, 1)
    return pd.DataFrame(
        {
            "open": [close - 0.1 for close in closes],
            "high": [close + 1.0 for close in closes],
            "low": [close - 1.0 for close in closes],
            "close": closes,
            "volume": [100.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.DatetimeIndex(
            [start + timedelta(days=index) for index in range(len(closes))]
        ),
    )


def _run_digital_macd(runonce, closes=_CLOSES, signal_period=_SIGNAL_PERIOD):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(closes)))
    cerebro.addstrategy(_DigitalMacdProbe, signal_period=signal_period)
    return cerebro.run(runonce=runonce, preload=True)[0]


def _reference_sequences(closes, signal_period, point=0.01):
    """Independently convolve source closes, then apply a rolling SMA to MACD."""
    indicator_type = bt.indicators.DigitalMacd
    fast_coeffs = tuple(float(value) for value in indicator_type.FAST_COEFFS)
    slow_coeffs = tuple(float(value) for value in indicator_type.SLOW_COEFFS)
    lookback = max(len(fast_coeffs), len(slow_coeffs))

    macd = [float("nan")] * len(closes)
    for end in range(lookback - 1, len(closes)):
        fast_values = [closes[end - offset] for offset in range(len(fast_coeffs))]
        slow_values = [closes[end - offset] for offset in range(len(slow_coeffs))]
        if not all(math.isfinite(value) for value in fast_values + slow_values):
            continue
        fast = sum(coeff * value for coeff, value in zip(fast_coeffs, fast_values))
        slow = sum(coeff * value for coeff, value in zip(slow_coeffs, slow_values))
        macd[end] = (fast - slow) / point

    signal = [float("nan")] * len(closes)
    for end in range(signal_period - 1, len(closes)):
        window = macd[end - signal_period + 1 : end + 1]
        if all(math.isfinite(value) for value in window):
            signal[end] = sum(window) / signal_period
    return macd, signal, lookback


def _assert_matches(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(expected_value, rel=1e-11, abs=1e-11)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_digital_macd_signal_uses_fir_history_and_signal_sma(runonce):
    """The signal is the SMA of the actual FIR MACD sequence in both engine modes."""
    strategy = _run_digital_macd(runonce)
    indicator = strategy.indicator
    macd = list(indicator.lines.macd.array)
    signal = list(indicator.lines.signal.array)
    expected_macd, expected_signal, lookback = _reference_sequences(
        _CLOSES, _SIGNAL_PERIOD
    )
    macd_first_valid = lookback - 1
    signal_first_valid = macd_first_valid + _SIGNAL_PERIOD - 1

    assert indicator._minperiod == signal_first_valid + 1
    assert len(macd) == len(signal) == len(_CLOSES)
    _assert_matches(macd, expected_macd)
    _assert_matches(signal, expected_signal)
    assert next(index for index, value in enumerate(macd) if math.isfinite(value)) == macd_first_valid
    assert next(index for index, value in enumerate(signal) if math.isfinite(value)) == signal_first_valid
    assert strategy.strategy_phases[signal_first_valid - 1][0] == "prenext"
    assert strategy.strategy_phases[signal_first_valid][0] == "nextstart"


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_digital_macd_short_feed_preserves_macd_but_not_incomplete_signal(runonce):
    """Short history computes available FIR values without fabricating a signal."""
    expected_macd, expected_signal, lookback = _reference_sequences(
        _CLOSES, _SIGNAL_PERIOD
    )
    signal_first_valid = lookback + _SIGNAL_PERIOD - 2
    closes = _CLOSES[:signal_first_valid]
    strategy = _run_digital_macd(runonce, closes=closes)
    macd = list(strategy.indicator.lines.macd.array)
    signal = list(strategy.indicator.lines.signal.array)
    short_expected_macd, short_expected_signal, _ = _reference_sequences(
        closes, _SIGNAL_PERIOD
    )

    assert len(closes) == signal_first_valid
    assert len(macd) == len(signal) == len(closes)
    assert strategy.indicator._minperiod == signal_first_valid + 1
    _assert_matches(macd, short_expected_macd)
    _assert_matches(signal, short_expected_signal)
    assert sum(math.isfinite(value) for value in macd) == len(closes) - lookback + 1
    assert all(math.isnan(value) for value in signal)
    assert all(phase == "prenext" for phase, _ in strategy.strategy_phases)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_digital_macd_signal_waits_for_finite_history_after_nan_gap(runonce):
    """A missing close poisons only windows containing it and does not create signal values."""
    gap_index = 84
    closes = list(_CLOSES)
    closes[gap_index] = float("nan")
    expected_macd, expected_signal, lookback = _reference_sequences(
        closes, _SIGNAL_PERIOD
    )
    strategy = _run_digital_macd(runonce, closes=closes)
    macd = list(strategy.indicator.lines.macd.array)
    signal = list(strategy.indicator.lines.signal.array)

    _assert_matches(macd, expected_macd)
    _assert_matches(signal, expected_signal)
    assert all(math.isnan(value) for value in macd[gap_index : gap_index + lookback])
    assert all(
        math.isnan(value)
        for value in signal[gap_index : gap_index + lookback + _SIGNAL_PERIOD - 1]
    )
    assert math.isfinite(macd[gap_index + lookback])
    assert math.isfinite(signal[gap_index + lookback + _SIGNAL_PERIOD - 1])
