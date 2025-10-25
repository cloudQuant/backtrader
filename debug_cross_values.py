#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt

class TestStrat(bt.Strategy):
    def __init__(self):
        from backtrader.indicators.crossover import CrossUp, CrossDown
        
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.upcross = CrossUp(self.data.close, self.sma)
        self.downcross = CrossDown(self.data.close, self.sma)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if len(self) in [15, 18, 19, 20]:
            print(f"Bar {len(self)}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
            print(f"  upcross={self.upcross[0]:.2f}, downcross={self.downcross[0]:.2f}, cross={self.cross[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
