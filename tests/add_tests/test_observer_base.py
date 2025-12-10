#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class ObserverTestStrategy(bt.Strategy):
    def __init__(self):
        # Observers are added by default, just verify strategy works
        pass

    def next(self):
        if not self.position:
            if self.data.close[0] > self.data.open[0]:
                self.buy()
        elif len(self) > 50:
            self.close()


def test_observer(main=False):
    """Test base observer functionality"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(ObserverTestStrategy)

    results = cerebro.run()
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # print('Observer base test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_observer(main=True)
