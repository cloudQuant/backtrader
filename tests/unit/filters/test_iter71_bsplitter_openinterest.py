"""DaySplitterClose preserves close-only open-interest timing."""

import datetime as dt

import backtrader as bt
import pandas as pd


class _CaptureSplitBars(bt.Strategy):
    def __init__(self):
        self.rows = []

    def next(self):
        names = ("open", "high", "low", "close", "volume", "openinterest")
        self.rows.append(
            tuple(float(getattr(self.data.lines, name)[0]) for name in names)
        )


def test_day_splitter_open_tick_hides_close_openinterest_until_close():
    frame = pd.DataFrame(
        {
            "open": [100.0, 110.0],
            "high": [110.0, 120.0],
            "low": [90.0, 100.0],
            "close": [105.0, 115.0],
            "volume": [1000.0, 2000.0],
            "openinterest": [777.0, 888.0],
        },
        index=pd.DatetimeIndex(
            [dt.datetime(2026, 1, 2), dt.datetime(2026, 1, 3)]
        ),
    )
    data = bt.feeds.PandasData(dataname=frame)
    data.addfilter(bt.filters.DaySplitterClose)

    cerebro = bt.Cerebro()
    cerebro.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=1)
    cerebro.addstrategy(_CaptureSplitBars)
    strategy, = cerebro.run(runonce=False, preload=False)

    assert strategy.rows == [
        (100.0, 110.0, 90.0, 100.0, 500.0, 0.0),
        (105.0, 105.0, 105.0, 105.0, 500.0, 777.0),
        (110.0, 120.0, 100.0, 110.0, 1000.0, 0.0),
        (115.0, 115.0, 115.0, 115.0, 1000.0, 888.0),
    ]
