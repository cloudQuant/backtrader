#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
    
    def next(self):
        if len(self) <= 20:  # Only print first few
            print(f"Strategy.next(): len={len(self)}, close={self.data.close[0]}, sma={self.sma[0]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro(runonce=False)  # Disable runonce mode
    
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
    print("Running cerebro with runonce=False...")
    cerebro.run()
    print("Done")
