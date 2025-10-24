#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind

class DebugSMA(btind.SMA):
    def next(self):
        print(f"  DebugSMA.next() called: len={len(self)}, data[0]={self.data[0]}")
        super(DebugSMA, self).next()
        print(f"    Result: sma={self.lines.sma[0]}")

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"TestStrategy.__init__ called")
        self.sma = DebugSMA(self.data, period=15)
        print(f"  SMA created: _minperiod={self.sma._minperiod}")
    
    def next(self):
        print(f"Strategy.next() called: len={len(self)}, sma={self.sma[0]}")

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
