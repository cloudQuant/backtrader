"""Cerebro parity for DigitalMacd's long signal-history tracking."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_SIGNAL_PERIOD = 128
_POINT = 0.01
_BAR_COUNT = 520


def _closes():
    values = [
        100.0 + index * 0.13 + math.sin(index * 0.17) * 3.0
        for index in range(_BAR_COUNT)
    ]
    values[260] = float("nan")
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
    fast_coeffs = indicator._fast_coeffs
    slow_coeffs = indicator._slow_coeffs
    lookback = indicator._max_lookback
    signal_period = indicator._signal_period

    macd = [float("nan")] * len(closes)
    signal = [float("nan")] * len(closes)
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
            if not math.isfinite(value):
                value = float("nan")

        macd[end] = value
        history.append(value)
        if len(history) > signal_period:
            history.pop(0)
        if len(history) == signal_period and all(
            math.isfinite(item) for item in history
        ):
            value = sum(history) / signal_period
            if math.isfinite(value):
                signal[end] = value

    return macd, signal


def _assert_exact(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == expected_value


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
def test_long_signal_history_count_preserves_nan_recovery_and_cached_params(runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.data,
                signal_period=_SIGNAL_PERIOD,
                point=_POINT,
            )

        def start(self):
            # DigitalMacd captures these values when constructed; runtime
            # parameter mutation must not resize either rolling history.
            self.indicator.p.signal_period = 3
            self.indicator.p.point = 0.5

        def stop(self):
            self.actual_macd = list(self.indicator.macd.array)
            self.actual_signal = list(self.indicator.signal.array)

    values = _closes()
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    expected_macd, expected_signal = _reference(
        list(strategy.data.close.array), strategy.indicator
    )
    _assert_exact(strategy.actual_macd, expected_macd)
    _assert_exact(strategy.actual_signal, expected_signal)

    indicator = strategy.indicator
    assert indicator._signal_period == _SIGNAL_PERIOD
    assert indicator._point == _POINT
    assert indicator.p.signal_period == 3
    assert indicator.p.point == 0.5
    assert indicator._minperiod == indicator._max_lookback + _SIGNAL_PERIOD - 1
    assert math.isnan(strategy.actual_signal[260])
    assert math.isfinite(strategy.actual_signal[-1])
