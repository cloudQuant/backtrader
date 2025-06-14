#!/usr/bin/env python
import sys
sys.path.insert(0, '..')
import backtrader as bt

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=5)
        self.count = 0
        
    def next(self):
        self.count += 1
        if self.count <= 10:  # Print first 10 values
            print(f'Day {self.count}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.6f}')

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Load data
    data = bt.feeds.YahooFinanceCSVData(
        dataname='datas/2006-day-001.txt',
        fromdate=bt.datetime.datetime(2006, 1, 1),
        todate=bt.datetime.datetime(2006, 1, 31)
    )
    
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrat)
    cerebro.run() 