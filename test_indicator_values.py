#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        self.bar_count = 0
        
    def next(self):
        self.bar_count += 1
        if self.bar_count <= 20:  # Print first 20 bars
            sma_val = self.sma[0] if hasattr(self.sma, '__getitem__') else float('nan')
            cross_val = self.cross[0] if hasattr(self.cross, '__getitem__') else float('nan')
            print(f"Bar {self.bar_count}: Close={self.data.close[0]:.2f}, SMA={sma_val:.2f}, Cross={cross_val:.2f}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    # Run
    cerebro.run()
    print("Done!")
