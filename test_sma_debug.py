#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind

class DebugSMA(btind.SMA):
    def next(self):
        print(f"\n  DebugSMA.next() called:")
        print(f"    len(self)={len(self)}")
        print(f"    self._idx={getattr(self, '_idx', 'NOT SET')}")
        print(f"    self.data._idx={getattr(self.data, '_idx', 'NOT SET')}")
        if hasattr(self.data, 'lines') and hasattr(self.data.lines, 'close'):
            print(f"    self.data.lines.close._idx={getattr(self.data.lines.close, '_idx', 'NOT SET')}")
            print(f"    self.data.lines.close[0]={self.data.lines.close[0]}")
        print(f"    self.data[0]={self.data[0]}")
        super(DebugSMA, self).next()
        print(f"    Result: sma={self.lines.sma[0]}")

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = DebugSMA(self.data, period=15)
    
    def next(self):
        if len(self) <= 17:  # Only print first few
            print(f"Strategy.next(): len={len(self)}, close={self.data.close[0]}, sma={self.sma[0]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    import datetime
    import os
    datapath = os.path.join(os.path.dirname(__file__), 'tests/datas/2006-day-001.txt')
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    cerebro.adddata(data)
    
    # Add strategy
    cerebro.addstrategy(TestStrategy)
    
    # Run
    print("Running cerebro...")
    cerebro.run()
    print("Done")
