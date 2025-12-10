#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class ResampleTestStrategy(bt.Strategy):
    def next(self):
        pass


def test_resample(main=False):
    """Test data resampling"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Resample to weekly
    cerebro.resampledata(data, timeframe=bt.TimeFrame.Weeks)
    cerebro.addstrategy(ResampleTestStrategy)

    results = cerebro.run()
    assert len(results) > 0

    if main:
        # print('Resample test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_resample(main=True)
