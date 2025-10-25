#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt
from backtrader.indicators.crossover import CrossUp

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.crossup = CrossUp(self.data.close, self.sma)
        
        print(f"\n=== Checking CrossUp ===")
        print(f"CrossUp has lines: {hasattr(self.crossup, 'lines')}")
        print(f"CrossUp.lines has cross: {hasattr(self.crossup.lines, 'cross')}")
        print(f"CrossUp.lines.cross type: {type(self.crossup.lines.cross)}")
        print(f"CrossUp.lines.cross is LineBuffer: {type(self.crossup.lines.cross).__name__}")
    
    def next(self):
        if len(self) == 19:
            print(f"\nBar 19:")
            print(f"  close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")
            print(f"  crossup[0]={self.crossup[0]:.2f}")
            print(f"  crossup.lines.cross[0]={self.crossup.lines.cross[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
