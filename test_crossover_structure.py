#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        
        print("\n=== CrossOver Structure ===")
        print(f"CrossOver type: {type(self.cross)}")
        print(f"Has _lineiterators: {hasattr(self.cross, '_lineiterators')}")
        if hasattr(self.cross, '_lineiterators'):
            from backtrader.lineiterator import LineIterator
            ind_list = self.cross._lineiterators.get(LineIterator.IndType, [])
            print(f"Number of sub-indicators: {len(ind_list)}")
            for i, ind in enumerate(ind_list):
                print(f"  Sub-indicator {i}: {type(ind).__name__}")
        
        print(f"\nHas lines.crossover: {hasattr(self.cross.lines, 'crossover')}")
        if hasattr(self.cross.lines, 'crossover'):
            co_line = self.cross.lines.crossover
            print(f"lines.crossover type: {type(co_line)}")
            print(f"lines.crossover has bindings: {hasattr(co_line, 'bindings')}")
            if hasattr(co_line, 'bindings'):
                print(f"Number of bindings: {len(co_line.bindings)}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
