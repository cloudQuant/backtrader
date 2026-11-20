"""Regression tests for Renko brick OHLC values through Cerebro."""

import pandas as pd

import backtrader as bt


class _CaptureBars(bt.Strategy):
    def __init__(self):
        self.bars = []

    def next(self):
        data = self.data
        self.bars.append((data.open[0], data.high[0], data.low[0], data.close[0]))


def _run_renko(closes):
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="D")
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [close + 2.0 for close in closes],
            "low": [close - 2.0 for close in closes],
            "close": closes,
            "volume": [10.0] * len(closes),
            "openinterest": [1.0] * len(closes),
        },
        index=dates,
    )

    cerebro = bt.Cerebro()
    data = bt.feeds.PandasData(dataname=frame)
    data.addfilter(bt.filters.Renko, size=10.0)
    cerebro.adddata(data)
    cerebro.addstrategy(_CaptureBars)
    return cerebro.run()[0].bars


def test_renko_up_brick_has_ordered_ohlc():
    assert _run_renko([100.0, 120.0]) == [(110.0, 120.0, 110.0, 120.0)]


def test_renko_down_brick_has_ordered_ohlc():
    assert _run_renko([100.0, 90.0]) == [(90.0, 90.0, 80.0, 80.0)]


def test_renko_reversal_bricks_keep_ohlc_order():
    assert _run_renko([100.0, 120.0, 80.0, 120.0]) == [
        (110.0, 120.0, 110.0, 120.0),
        (110.0, 110.0, 100.0, 100.0),
        (110.0, 120.0, 110.0, 120.0),
    ]


def test_renko_emits_multiple_bricks_with_valid_ohlc():
    bars = _run_renko([100.0, 150.0, 150.0, 150.0, 150.0])

    assert bars == [
        (110.0, 120.0, 110.0, 120.0),
        (120.0, 130.0, 120.0, 130.0),
        (130.0, 140.0, 130.0, 140.0),
        (140.0, 150.0, 140.0, 150.0),
    ]
    assert all(high >= low for _, high, low, _ in bars)
