#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        
        print(f"\n=== Checking _ltype ===")
        print(f"SMA _ltype: {getattr(self.sma, '_ltype', 'NOT SET')}")
        print(f"Cross _ltype: {getattr(self.cross, '_ltype', 'NOT SET')}")
        print(f"IndType constant: {bt.LineIterator.IndType}")
        
        print(f"\n=== Checking _lineiterators content ===")
        if hasattr(self, '_lineiterators'):
            for key, val in self._lineiterators.items():
                print(f"  Key {key}: {val}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
