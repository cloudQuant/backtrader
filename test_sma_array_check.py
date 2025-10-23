#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
检查SMA的array是否被正确填充
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        
    def next(self):
        pass
        
    def stop(self):
        print("\n=== SMA Array Debug ===")
        print(f"SMA type: {type(self.sma)}")
        print(f"Has array: {hasattr(self.sma, 'array')}")
        if hasattr(self.sma, 'array'):
            print(f"Array length: {len(self.sma.array)}")
            print(f"First 20 values: {list(self.sma.array[:20])}")
        
        if hasattr(self.sma, 'lines'):
            print(f"Has lines: True")
            if hasattr(self.sma.lines, 'sma'):
                print(f"Has lines.sma: True")
                if hasattr(self.sma.lines.sma, 'array'):
                    print(f"lines.sma.array length: {len(self.sma.lines.sma.array)}")
                    print(f"lines.sma.array first 20: {list(self.sma.lines.sma.array[:20])}")
                    
        print(f"\nSMA._idx: {getattr(self.sma, '_idx', 'N/A')}")
        if hasattr(self.sma.lines, 'sma'):
            print(f"lines.sma._idx: {getattr(self.sma.lines.sma, '_idx', 'N/A')}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
