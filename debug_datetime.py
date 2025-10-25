#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt

class TestStrat(bt.Strategy):
    def next(self):
        if len(self) == 19:
            print(f"\nBar {len(self)}:")
            print(f"  self.data.datetime[0] = {self.data.datetime[0]}")
            print(f"  self.data.datetime has _idx: {hasattr(self.data.datetime, '_idx')}")
            if hasattr(self.data.datetime, '_idx'):
                print(f"  self.data.datetime._idx = {self.data.datetime._idx}")
            print(f"  self.data.datetime.array length: {len(self.data.datetime.array) if hasattr(self.data.datetime, 'array') else 'no array'}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()
