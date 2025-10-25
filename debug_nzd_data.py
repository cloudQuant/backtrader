#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt
from backtrader.indicators.crossover import NonZeroDifference

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.nzd = NonZeroDifference(self.data.close, self.sma)

        print(f"\n=== NonZeroDifference data check ===")
        print(f"NZD.data0 type: {type(self.nzd.data0)}")
        print(f"NZD.data1 type: {type(self.nzd.data1)}")
        print(f"Expected data0: {type(self.data.close)} (close)")
        print(f"Expected data1: {type(self.sma)} (SMA)")

    def next(self):
        if len(self) == 19:
            print(f"\nBar 19:")
            print(f"  Strategy sees: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
            print(f"  NZD sees: data0={self.nzd.data0[0]:.2f}, data1={self.nzd.data1[0]:.2f}")
            print(f"  NZD calculates: {self.nzd.data0[0] - self.nzd.data1[0]:.2f}")
            print(f"  NZD returns: {self.nzd[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
