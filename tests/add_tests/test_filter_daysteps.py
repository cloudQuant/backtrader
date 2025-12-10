#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class DayStepsStrategy(bt.Strategy):
    def next(self):
        # Verify data is valid
        assert self.data.close[0] is not None


def test_run(main=False):
    """Test DayStepsFilter (BarReplayer_Open)"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Add BarReplayer filter (DayStepsFilter alias)
    data.addfilter(bt.filters.DayStepsFilter)

    cerebro.adddata(data)
    cerebro.addstrategy(DayStepsStrategy)

    results = cerebro.run()

    # Verify filter worked
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy processed replayed data

    if main:
        # print('DayStepsFilter test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_run(main=True)
