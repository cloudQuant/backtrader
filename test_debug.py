#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"TestStrategy.__init__ called")
        print(f"  self.datas = {self.datas}")
        print(f"  self.data = {self.data}")
        print(f"  hasattr(self, '_lineiterators') = {hasattr(self, '_lineiterators')}")
        if hasattr(self, '_lineiterators'):
            print(f"  len(self._lineiterators[bt.LineIterator.IndType]) = {len(self._lineiterators[bt.LineIterator.IndType])}")
        
        print(f"Creating SMA indicator...")
        self.sma = btind.SMA(self.data, period=15)
        print(f"  SMA created: {self.sma}")
        print(f"  SMA._owner = {getattr(self.sma, '_owner', 'NOT SET')}")
        print(f"  SMA._clock = {getattr(self.sma, '_clock', 'NOT SET')}")
        print(f"  SMA._minperiod = {getattr(self.sma, '_minperiod', 'NOT SET')}")
        
        if hasattr(self, '_lineiterators'):
            print(f"  len(self._lineiterators[bt.LineIterator.IndType]) after SMA = {len(self._lineiterators[bt.LineIterator.IndType])}")
    
    def next(self):
        print(f"next() called: len={len(self)}, sma={self.sma[0]}")

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
