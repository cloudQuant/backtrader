#!/usr/bin/env python

import pandas as pd

import backtrader as bt


class ResampleCloneStrategy(bt.Strategy):
    def __init__(self):
        self.minute_bars_seen = 0
        self.hour_bars_seen = 0

    def next(self):
        self.minute_bars_seen = len(self.datas[0])
        self.hour_bars_seen = len(self.datas[1])

    def stop(self):
        self.minute_bars_seen = len(self.datas[0])
        self.hour_bars_seen = len(self.datas[1])


def test_resampledata_existing_data_feed_clones_successfully():
    bars = 180
    base = [100.0 + i * 0.1 for i in range(bars)]
    index = pd.date_range("2024-01-01 09:30", periods=bars, freq="min")
    df = pd.DataFrame(
        {
            "open": base,
            "high": [value + 1.0 for value in base],
            "low": [value - 1.0 for value in base],
            "close": [value + 0.5 for value in base],
            "volume": [1000.0 + i for i in range(bars)],
            "openinterest": [0.0] * bars,
        },
        index=index,
    )

    cerebro = bt.Cerebro()
    data = bt.feeds.PandasData(
        dataname=df,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data)

    data_hour = cerebro.resampledata(
        dataname=data,
        name="hour",
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
        bar2edge=True,
    )

    assert data_hour is not data
    assert data_hour._name == "hour"

    cerebro.addstrategy(ResampleCloneStrategy)
    results = cerebro.run()

    assert len(results) == 1
    assert results[0].minute_bars_seen == bars
    assert results[0].hour_bars_seen > 0
