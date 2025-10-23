#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

# Monkey patch LineAlias.__set__ to add debug
from backtrader.lineseries import LineAlias
original_set = LineAlias.__set__

def debug_set(self, obj, value):
    print(f"LineAlias.__set__ called: line={self.line}, value type={type(value).__name__}")
    return original_set(self, obj, value)

LineAlias.__set__ = debug_set

class TestStrategy(bt.Strategy):
    def __init__(self):
        print("\n=== Creating CrossOver ===")
        self.cross = btind.CrossOver(self.data.close, btind.SMA(self.data, period=15))
        print("=== Done creating CrossOver ===")
        
        # Check structure
        from backtrader.lineiterator import LineIterator
        print(f"CrossOver has {len(self.cross._lineiterators.get(LineIterator.IndType, []))} sub-indicators")
        for i, ind in enumerate(self.cross._lineiterators.get(LineIterator.IndType, [])):
            print(f"  Sub-indicator {i}: {type(ind).__name__}")
        
        # Check if lines.crossover is bound FROM a LinesOperation
        co_line = self.cross.lines.crossover
        print(f"lines.crossover type: {type(co_line).__name__}")
        
        # The binding is REVERSED: LinesOperation has binding TO lines.crossover
        # So we need to find which object has lines.crossover in its bindings
        print(f"\nSearching for source that binds TO lines.crossover...")
        for ind in self.cross._lineiterators.get(LineIterator.IndType, []):
            if hasattr(ind, 'bindings'):
                if co_line in ind.bindings:
                    print(f"  Found: {type(ind).__name__} binds to lines.crossover")
                    print(f"  It has {len(ind.bindings)} bindings")
        print()

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    cerebro.run()
