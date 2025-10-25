#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt
from backtrader.indicators.crossover import NonZeroDifference

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.nzd = NonZeroDifference(self.data.close, self.sma)

    def next(self):
        if len(self) in [15, 16, 17, 18, 19, 20]:
            diff_calc = self.data.close[0] - self.sma[0]
            print(f"Bar {len(self)}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
            print(f"  Calculated diff: {diff_calc:.2f}")
            print(f"  NZD value: {self.nzd[0]:.2f}")
            if len(self) > 15:
                print(f"  NZD[-1]: {self.nzd[-1]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
