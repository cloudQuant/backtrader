#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class FeedStrategy(bt.Strategy):
    def next(self):
        # Verify data is loaded
        assert self.data.close[0] > 0


def test_btcsv(main=False):
    """Test BacktraderCSVData feed"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(FeedStrategy)
    results = cerebro.run()

    # Verify feed loaded successfully
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # print('BacktraderCSVData feed test passed')  # Removed for performance
        pass


def test_generic_csv(main=False):
    """Test GenericCSVData feed"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.GenericCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
    )

    cerebro.adddata(data)
    cerebro.addstrategy(FeedStrategy)
    results = cerebro.run()

    # Verify feed loaded successfully
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # print('GenericCSVData feed test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_btcsv(main=True)
    test_generic_csv(main=True)
