"""RsiomaV2 signal seeding agrees across Cerebro execution modes."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _run(runonce, *, count=350, **params):
    close = [
        100.0 + i * 0.13 + (i * 7 % 13) * 0.47 + math.sin(i * 0.3) * 2.2
        for i in range(count)
    ]
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
            self.indicator = bt.indicators.RsiomaV2(self.data, **params)
            self.downstream = bt.indicators.SMA(self.indicator.signal, period=3)

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.rsioma.array),
                list(self.indicator.signal.array),
                list(self.downstream.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _assert_equal(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(
    ("params", "minperiod"),
    [({}, 48), ({"rsioma_period": 5, "ma_rsioma_period": 4}, 13),
     ({"rsioma_period": 5, "ma_rsioma_period": 4, "mom_period": 3}, 16)],
)
def test_signal_matches_independent_ema_and_next(params, minperiod):
    runnext = _run(False, **params)
    runonce = _run(True, **params)
    assert runnext[0] == runonce[0] == minperiod
    for actual, expected in zip(runonce[1:], runnext[1:]):
        _assert_equal(actual, expected)

    # The signal is a conventional EMA of the already computed RSI: its
    # first value is the mean of the first complete RSI window.
    rsioma, signal = runnext[1:3]
    period = params.get("ma_rsioma_period", 21)
    first = minperiod - 1
    assert all(math.isnan(value) for value in signal[:first])
    previous = math.fsum(rsioma[first - period + 1 : first + 1]) / period
    expected = [math.nan] * first + [previous]
    alpha = 2.0 / (period + 1.0)
    for value in rsioma[first + 1 :]:
        previous = previous * (1.0 - alpha) + value * alpha
        expected.append(previous)
    _assert_equal(signal, expected)


@pytest.mark.parametrize("runonce", [False, True])
def test_short_history_does_not_publish_a_signal(runonce):
    minperiod, _rsioma, signal, downstream = _run(runonce, count=30)
    assert minperiod == 48
    assert all(math.isnan(value) for value in signal)
    assert all(math.isnan(value) for value in downstream)
