#!/usr/bin/env python
"""Regression coverage for the matplotlib Cerebro plotter path."""

from __future__ import annotations

import datetime
import os

import backtrader as bt


class MatplotlibSmokeStrategy(bt.Strategy):
    """Minimal strategy with an indicator whose label must be plot-safe."""

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=10)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=30)

    def next(self):
        if not self.position and self.sma_fast > self.sma_slow:
            self.buy()
        elif self.position and self.sma_fast < self.sma_slow:
            self.close()


def test_cerebro_plot_matplotlib_handles_non_string_indicator_labels():
    """The explicit matplotlib backend renders an indicator without a label type error."""
    data_path = os.path.join(os.path.dirname(__file__), "..", "datas", "nvda-1999-2014.txt")
    cerebro = bt.Cerebro()
    cerebro.adddata(
        bt.feeds.GenericCSVData(
            dataname=data_path,
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
            fromdate=datetime.datetime(2010, 1, 1),
            todate=datetime.datetime(2010, 6, 30),
        )
    )
    cerebro.addstrategy(MatplotlibSmokeStrategy)
    cerebro.run()

    figures = cerebro.plot(backend="matplotlib", use="Agg", iplot=False)

    assert len(figures) == 1
    assert figures[0]
