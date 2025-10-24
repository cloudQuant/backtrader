#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import datetime
import os

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"TestStrategy.__init__: len(self)={len(self) if hasattr(self, '__len__') else 'N/A'}")
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.prenext_count = 0
        self.next_count = 0
        print(f"TestStrategy.__init__ done: len(self)={len(self)}")
    
    def prenext(self):
        self.prenext_count += 1
        if self.prenext_count <= 3 or self.prenext_count >= 13:
            print(f"  prenext #{self.prenext_count}, len={len(self)}")
    
    def next(self):
        self.next_count += 1
        if self.next_count == 1:
            print(f"  next #{self.next_count}, len={len(self)}")
            print(f"    len(self.datas[0])={len(self.datas[0])}")
            print(f"    len(self.datas[0].lines.close.array)={len(self.datas[0].lines.close.array)}")
            print(f"    self.datas[0].lines.close.lencount={self.datas[0].lines.close.lencount}")
        elif self.next_count <= 3 or self.next_count >= 242:
            print(f"  next #{self.next_count}, len={len(self)}")
    
    def stop(self):
        print(f"\n=== stop() called ===")
        print(f"Strategy prenext calls: {self.prenext_count}")
        print(f"Strategy next calls: {self.next_count}")
        print(f"Total strategy calls: {self.prenext_count + self.next_count}")
        print(f"Total _oncepost calls: {getattr(self, '_oncepost_count', 'NOT TRACKED')}")
        print(f"len(self): {len(self)}")
        print(f"len(self.data): {len(self.data)}")
        print(f"len(self.sma): {len(self.sma)}")
        print(f"data.lines.close.array length: {len(self.data.lines.close.array)}")
        print(f"data.lines.close.idx: {self.data.lines.close.idx}")
        print(f"data.lines.close.lencount: {self.data.lines.close.lencount}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
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
