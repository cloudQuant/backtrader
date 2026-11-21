"""Long-window DigitalMacd handling of internally generated infinities."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_SIGNAL_PERIOD = 128
_POINT = 0.01
_BAR_COUNT = 760
_FIRST_IMPULSE = 120
_SECOND_IMPULSE = 430


def _closes():
    values = [
        100.0 + index * 0.13 + math.sin(index * 0.17) * 3.0
        for index in range(_BAR_COUNT)
    ]
    values[_FIRST_IMPULSE] = 1.0e308
    values[_SECOND_IMPULSE] = -1.0e308
    return tuple(values)


def _frame(values):
    start = datetime(2025, 1, 1)
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.DatetimeIndex(
            [start + timedelta(minutes=index) for index in range(len(values))]
        ),
    )


def _reference(closes, indicator):
    """Recompute each FIR point and finite-only rolling signal independently."""
    fast_coeffs = indicator._fast_coeffs
    slow_coeffs = indicator._slow_coeffs
    lookback = indicator._max_lookback
    signal_period = indicator._signal_period

    macd = [float("nan")] * len(closes)
    signal = [float("nan")] * len(closes)
    raw_macd = [float("nan")] * len(closes)
    history = []
    for end in range(len(closes)):
        if end + 1 < lookback:
            value = float("nan")
        else:
            window = tuple(closes[end - offset] for offset in range(lookback))
            fast = 0.0
            for index, coefficient in enumerate(fast_coeffs):
                fast += coefficient * window[index]
            slow = 0.0
            for index, coefficient in enumerate(slow_coeffs):
                slow += coefficient * window[index]
            value = (fast - slow) / indicator._point
            raw_macd[end] = value
            if not math.isfinite(value):
                value = float("nan")

        macd[end] = value
        if end + 1 < lookback:
            raw_macd[end] = value
        history.append(raw_macd[end])
        if len(history) > signal_period:
            history.pop(0)
        if len(history) == signal_period and all(
            math.isfinite(item) for item in history
        ):
            value = sum(history) / signal_period
            if math.isfinite(value):
                signal[end] = value

    return macd, signal, raw_macd


def _assert_exact(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == expected_value


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
def test_long_signal_history_counts_internal_signed_infinity_and_recovers(runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.data,
                signal_period=_SIGNAL_PERIOD,
                point=_POINT,
            )

        def stop(self):
            self.actual_macd = list(self.indicator.macd.array)
            self.actual_signal = list(self.indicator.signal.array)

    values = _closes()
    # The feed contains only finite values; overflow arises inside the FIR.
    assert all(math.isfinite(value) for value in values)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    expected_macd, expected_signal, raw_macd = _reference(
        list(strategy.data.close.array), strategy.indicator
    )
    positive_infinities = [
        index
        for index, value in enumerate(raw_macd)
        if math.isinf(value) and value > 0
    ]
    negative_infinities = [
        index
        for index, value in enumerate(raw_macd)
        if math.isinf(value) and value < 0
    ]
    assert positive_infinities
    assert negative_infinities
    _assert_exact(strategy.actual_macd, expected_macd)
    _assert_exact(strategy.actual_signal, expected_signal)

    first_impulse_end = max(
        index
        for index, value in enumerate(raw_macd)
        if _FIRST_IMPULSE <= index < _SECOND_IMPULSE
        and not math.isfinite(value)
    )
    second_impulse_start = min(
        index
        for index, value in enumerate(raw_macd)
        if index >= _SECOND_IMPULSE and not math.isfinite(value)
    )
    first_clear_window = first_impulse_end + _SIGNAL_PERIOD
    assert all(
        math.isfinite(value)
        for value in raw_macd[
            first_clear_window - _SIGNAL_PERIOD + 1 : first_clear_window + 1
        ]
    )
    # The previous window still contains the last non-finite value.
    assert math.isnan(strategy.actual_signal[first_clear_window - 1])
    # Once the first impulse has fully rolled out, a finite signal returns
    # before the second impulse starts. Finite extreme values can keep the
    # SMA sum overflowing for additional bars, so recovery is checked within
    # the interval rather than assumed to occur at the first all-finite window.
    assert any(
        math.isfinite(strategy.actual_signal[index])
        for index in range(first_clear_window, second_impulse_start)
    )

    second_impulse_end = max(
        index
        for index, value in enumerate(raw_macd)
        if index >= _SECOND_IMPULSE and not math.isfinite(value)
    )
    second_clear_window = second_impulse_end + _SIGNAL_PERIOD
    assert all(
        math.isfinite(value)
        for value in raw_macd[
            second_clear_window - _SIGNAL_PERIOD + 1 : second_clear_window + 1
        ]
    )
    assert math.isnan(strategy.actual_signal[second_clear_window - 1])
    assert any(
        math.isfinite(value)
        for value in strategy.actual_signal[second_clear_window:]
    )
