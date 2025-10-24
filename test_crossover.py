#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind
import datetime
import os

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        self.cross_count = 0
    
    def next(self):
        # Debug: print first few and last few values
        if len(self) <= 20 or len(self) >= len(self.data) - 5:
            sma_idx = getattr(self.sma.lines.sma, '_idx', 'NOT SET')
            sma_array_len = len(self.sma.lines.sma.array) if hasattr(self.sma.lines.sma, 'array') else 'NO ARRAY'
            print(f"Day {len(self)}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}, sma._idx={sma_idx}, array_len={sma_array_len}, cross={self.cross[0]}")
        
        if self.cross > 0.0:
            self.cross_count += 1
            print(f"Golden Cross #{self.cross_count} at {self.data.datetime.date(0)}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}, cross={self.cross[0]}")
        elif self.cross < 0.0:
            self.cross_count += 1
            print(f"Death Cross #{self.cross_count} at {self.data.datetime.date(0)}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}, cross={self.cross[0]}")
    
    def stop(self):
        print(f"\nTotal crossovers: {self.cross_count}")
        print(f"CrossOver array length: {len(self.cross.lines.crossover.array)}")
        print(f"CrossOver array sample: {self.cross.lines.crossover.array[30:50]}")
        # Count non-zero values
        non_zero = sum(1 for v in self.cross.lines.crossover.array if v != 0.0)
        print(f"Non-zero crossover values: {non_zero}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = os.path.join(os.path.dirname(__file__), 'tests/datas/2006-day-001.txt')
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy, period=15)
    
    print("Running test...")
    cerebro.run()
    print("\nDone")
