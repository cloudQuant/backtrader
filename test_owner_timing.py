#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

# Monkey patch to debug
from backtrader.lineseries import LineAlias
original_set = LineAlias.__set__

def debug_set(self, obj, value):
    if type(value).__name__ == 'LinesOperation':
        owner = getattr(obj, '_owner', None)
        print(f"LineAlias.__set__ for LinesOperation:")
        print(f"  obj._owner = {type(owner).__name__ if owner else 'None'}")
        if owner:
            print(f"  owner has _lineiterators: {hasattr(owner, '_lineiterators')}")
            if hasattr(owner, '_lineiterators'):
                from backtrader.lineiterator import LineIterator
                print(f"  owner._lineiterators[IndType] length: {len(owner._lineiterators.get(LineIterator.IndType, []))}")
    return original_set(self, obj, value)

LineAlias.__set__ = debug_set

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.cross = btind.CrossOver(self.data.close, btind.SMA(self.data, period=15))
        
        # Check after creation
        from backtrader.lineiterator import LineIterator
        print(f"\nAfter CrossOver creation:")
        print(f"  CrossOver._lineiterators[IndType] length: {len(self.cross._lineiterators.get(LineIterator.IndType, []))}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    cerebro.run()
