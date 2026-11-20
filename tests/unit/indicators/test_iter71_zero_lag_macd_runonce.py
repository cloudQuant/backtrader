"""ZeroLagMacd signal matches its EMA reference in both Cerebro modes."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _prices(count):
    return [
        100.0 + i * 0.13 + (i * 7 % 13) * 0.47 + math.sin(i * 0.3) * 2.2
        for i in range(count)
    ]


def _run(runonce, *, count=350, **params):
    close = _prices(count)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1000.0] * count,
        },
        index=pd.date_range("2020-01-01", periods=count),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.ZeroLagMacd(self.data.close, **params)
            self.downstream = bt.indicators.SMA(self.indicator.signal, period=3)

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.macd.array),
                list(self.indicator.signal.array),
                list(self.downstream.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _ema(values, period, source_start):
    """Calculate EMA from a known first valid input, using an SMA seed."""
    output = [math.nan] * len(values)
    seed = source_start + period - 1
    if seed >= len(values):
        return output
    previous = math.fsum(values[source_start : seed + 1]) / period
    output[seed] = previous
    alpha = 2.0 / (period + 1.0)
    for index in range(seed + 1, len(values)):
        previous = previous * (1.0 - alpha) + values[index] * alpha
        output[index] = previous
    return output


def _assert_equal(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("fast,slow", [(12, 26), (3, 5), (8, 3), (1, 4)])
def test_formula_and_signal_seed_match_next_and_once(fast, slow):
    runnext = _run(False, fast=fast, slow=slow)
    runonce = _run(True, fast=fast, slow=slow)
    first_macd = 2 * max(fast, slow) - 2
    first_signal = first_macd + 8
    assert runnext[0] == runonce[0] == first_signal + 1
    for actual, expected in zip(runonce[1:], runnext[1:]):
        _assert_equal(actual, expected)

    prices = _prices(350)
    fast_one = _ema(prices, fast, 0)
    fast_two = _ema(fast_one, fast, fast - 1)
    slow_one = _ema(prices, slow, 0)
    slow_two = _ema(slow_one, slow, slow - 1)
    expected_macd = [math.nan] * first_macd + [
        (2.0 * fast_one[i] - fast_two[i]) - (2.0 * slow_one[i] - slow_two[i])
        for i in range(first_macd, len(prices))
    ]
    expected_signal = _ema(expected_macd, 9, first_macd)
    _assert_equal(runnext[1], expected_macd)
    _assert_equal(runnext[2], expected_signal)


@pytest.mark.parametrize("runonce", [False, True])
def test_short_history_keeps_signal_unavailable(runonce):
    minperiod, _macd, signal, downstream = _run(runonce, count=55)
    assert minperiod == 59
    assert all(math.isnan(value) for value in signal)
    assert all(math.isnan(value) for value in downstream)
