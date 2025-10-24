#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind

class DebugSMA(btind.SMA):
    def next(self):
        print(f"\n=== DebugSMA.next() called ===")
        print(f"  Before calculation:")
        print(f"    self._idx = {getattr(self, '_idx', 'NOT SET')}")
        print(f"    self.lines.sma._idx = {getattr(self.lines.sma, '_idx', 'NOT SET')}")
        print(f"    self.data.lines.close._idx = {getattr(self.data.lines.close, '_idx', 'NOT SET')}")
        
        # Call parent next() to calculate
        super(DebugSMA, self).next()
        
        print(f"  After calculation:")
        print(f"    self._idx = {getattr(self, '_idx', 'NOT SET')}")
        print(f"    self.lines.sma._idx = {getattr(self.lines.sma, '_idx', 'NOT SET')}")
        print(f"    self.lines.sma.array[{self._idx}] = {self.lines.sma.array[self._idx] if hasattr(self.lines.sma, 'array') and self._idx < len(self.lines.sma.array) else 'N/A'}")
        print(f"    self.lines.sma[0] = {self.lines.sma[0]}")
        print(f"    self[0] = {self[0]}")

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = DebugSMA(self.data, period=15)
    
    def next(self):
        if len(self) <= 17:
            print(f"\n>>> Strategy.next(): len={len(self)}, close={self.data.close[0]}, sma={self.sma[0]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    import datetime
    import os
    datapath = os.path.join(os.path.dirname(__file__), 'tests/datas/2006-day-001.txt')
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    print("Running cerebro...")
    cerebro.run()
    print("\nDone")
