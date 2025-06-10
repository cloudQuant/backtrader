#!/usr/bin/env python
import sys
sys.path.insert(0, '..')
import backtrader as bt
import tests.original_tests.testcommon as testcommon

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        
    def next(self):
        print("self.data.close[0]:", bt.num2date(self.data.datetime[0]), self.data.close[0],self.sma[0])
        if len(self) == 15:  # First valid SMA point
            print(f'Day {len(self)}: price={self.data.close[0]:.2f}, sma={self.sma[0]}')
        elif len(self) == 20:  # A few days later
            print(f'Day {len(self)}: price={self.data.close[0]:.2f}, sma={self.sma[0]}')
            
# Create a simple test
data = testcommon.getdata(0)
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run() 