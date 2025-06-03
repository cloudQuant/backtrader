#!/usr/bin/env python

import sys
import os
sys.path.insert(0, '../..')

import backtrader as bt

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"TestStrategy.__init__: hasattr(self, 'data') = {hasattr(self, 'data')}")
        print(f"TestStrategy.__init__: hasattr(self, 'datas') = {hasattr(self, 'datas')}")
        if hasattr(self, 'datas'):
            print(f"TestStrategy.__init__: self.datas = {self.datas}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Create a dummy data feed
    data = bt.feeds.YahooFinanceCSVData(dataname='../datas/2006-day-001.txt')
    cerebro.adddata(data)
    
    cerebro.addstrategy(TestStrategy)
    cerebro.run() 