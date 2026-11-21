"""Color3rdGenXMA warmup follows its EMA chain and signal-bar gate."""

import datetime as dt
import math

import backtrader as bt
import pandas as pd
import pytest

from tests.functional.strategies.trend_following.test_0312_1260_color3rdgenxma import (
    Color3rdGenXMAStrategy,
)


def _prices(count):
    return [
        80.0 + index * 0.31 + (index * 7 % 11) * 0.73
        for index in range(count)
    ]


def _ema(values, period, source_start=0):
    output = [math.nan] * len(values)
    seed_index = source_start + period - 1
    if seed_index >= len(values):
        return output

    previous = sum(values[source_start : seed_index + 1]) / period
    output[seed_index] = previous
    alpha = 2.0 / (period + 1.0)
    for index in range(seed_index + 1, len(values)):
        previous = previous * (1.0 - alpha) + values[index] * alpha
        output[index] = previous
    return output


def _reference(prices, xlength, price_shift):
    slength = 2 * xlength
    x1 = _ema(prices, slength)
    first_x1 = slength - 1
    x2 = _ema(x1, xlength, first_x1)
    lam = float(slength) / float(xlength)
    alpha = lam * (slength - 1.0) / (slength - lam)
    value = [math.nan] * len(prices)
    for index, (first, second) in enumerate(zip(x1, x2)):
        if math.isfinite(first) and math.isfinite(second):
            value[index] = (
                (alpha + 1.0) * first
                - alpha * second
                + float(price_shift) * 0.00001
            )

    color = [1.0] * len(prices)
    for index in range(1, len(prices)):
        if math.isfinite(value[index]) and math.isfinite(value[index - 1]):
            if value[index] > value[index - 1]:
                color[index] = 2.0
            elif value[index] < value[index - 1]:
                color[index] = 0.0
    return value, color


def _assert_lines(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), index
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), index


def _frame(count):
    close = _prices(count)
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1000.0] * count,
        },
        index=pd.date_range(dt.datetime(2026, 1, 1), periods=count, freq="D"),
    )


def _run_consumer(runonce, consumer, xlength=4, signal_bar=1):
    count = max(80, 3 * xlength + signal_bar + 20)
    frame = _frame(count)

    class StandaloneProbe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.Color3rdGenXMAIndicator(
                self.data,
                xlength=xlength,
                xma_method="ema",
                ipc="price_close",
                price_shift=2,
            )
            self.callback_lengths = []

        def next(self):
            self.callback_lengths.append(len(self.data))

        def stop(self):
            self.result = {
                "minperiod": self.indicator._minperiod,
                "value": list(self.indicator.value.array),
                "color": list(self.indicator.color.array),
                "callback_lengths": self.callback_lengths,
                "signal_lengths": [],
            }

    class StrategyProbe(Color3rdGenXMAStrategy):
        params = {
            "xlength": xlength,
            "signal_bar": signal_bar,
            "start_hour": 8,
            "start_minute": 0,
            "price_shift": 2,
        }

        def __init__(self):
            super().__init__()
            self.callback_lengths = []
            self.signal_lengths = []

        def next(self):
            self.callback_lengths.append(len(self.data))
            warmup = int(self.p.xlength) * 3 + int(self.p.signal_bar) + 5
            if len(self.data) >= warmup:
                self.signal_lengths.append(len(self.data))
            super().next()

        def stop(self):
            self.result = {
                "minperiod": self.indicator._minperiod,
                "value": list(self.indicator.value.array),
                "color": list(self.indicator.color.array),
                "callback_lengths": self.callback_lengths,
                "signal_lengths": self.signal_lengths,
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    if consumer == "standalone":
        cerebro.addstrategy(StandaloneProbe)
    else:
        cerebro.addstrategy(StrategyProbe)
    return cerebro.run(runonce=runonce, preload=True)[0].result


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("consumer", ["standalone", "strategy"])
@pytest.mark.parametrize("signal_bar", [1, 3])
@pytest.mark.parametrize("xlength", [4, 50])
def test_warmup_matches_ema_chain_and_preserves_strategy_signal_gate(
    runonce, consumer, signal_bar, xlength
):
    expected_minperiod = 3 * xlength + 5
    expected_signal_start = 3 * xlength + signal_bar + 5
    prices = _prices(max(80, 3 * xlength + signal_bar + 20))
    expected_value, expected_color = _reference(prices, xlength, price_shift=2)

    result = _run_consumer(runonce, consumer, xlength, signal_bar)

    assert result["minperiod"] == expected_minperiod
    _assert_lines(result["value"], expected_value)
    _assert_lines(result["color"], expected_color)
    assert result["callback_lengths"][0] == expected_minperiod
    if consumer == "strategy":
        assert result["signal_lengths"][0] == expected_signal_start
        assert result["callback_lengths"][0] < result["signal_lengths"][0]
