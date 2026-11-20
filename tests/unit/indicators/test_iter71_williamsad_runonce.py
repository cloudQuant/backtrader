"""Regression coverage for WilliamsAD runonce accumulation (R71-151)."""

from datetime import datetime
import math

import backtrader as bt
import pandas as pd
import pytest


_BARS = (
    # date, open, high, low, close
    (datetime(2024, 1, 1), 10.0, 11.0, 9.0, 10.0),
    (datetime(2024, 1, 2), 10.0, 12.0, 10.0, 11.0),
    (datetime(2024, 1, 3), 11.0, 12.0, 10.0, 10.0),
    (datetime(2024, 1, 4), 10.0, 13.0, 10.0, 12.0),
    (datetime(2024, 1, 5), 12.0, 13.0, 11.0, 11.0),
    (datetime(2024, 1, 6), 11.0, 13.0, 11.0, 12.0),
)
_EXPECTED = (float("nan"), 1.0, -1.0, 1.0, -1.0, 0.0)


class _CaptureWilliamsAD(bt.Strategy):
    def __init__(self):
        self.williams_ad = bt.indicators.WilliamsAD(self.data)

    def start(self):
        self.values = []

    def next(self):
        self.values.append((len(self.data), float(self.williams_ad[0])))


def _run_williamsad(runonce):
    frame = pd.DataFrame(
        {
            "open": [bar[1] for bar in _BARS],
            "high": [bar[2] for bar in _BARS],
            "low": [bar[3] for bar in _BARS],
            "close": [bar[4] for bar in _BARS],
            "volume": [100.0] * len(_BARS),
            "openinterest": [0.0] * len(_BARS),
        },
        index=pd.DatetimeIndex([bar[0] for bar in _BARS]),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_CaptureWilliamsAD)
    return cerebro.run(runonce=runonce, preload=True)[0]


@pytest.mark.parametrize("runonce", (False, True))
def test_williamsad_full_sequence_and_warmup(runonce):
    strategy = _run_williamsad(runonce)
    values = list(strategy.williams_ad.lines.ad.array)

    assert strategy.williams_ad._minperiod == 2
    assert [length for length, _ in strategy.values] == [2, 3, 4, 5, 6]
    assert math.isnan(values[0])
    assert values[1:] == pytest.approx(_EXPECTED[1:])
