#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        # Create a simple SMA first
        sma = btind.SMA(self.data, period=15)
        print(f"\n=== SMA created ===")
        print(f"SMA.lines._owner: {type(sma.lines._owner).__name__ if sma.lines._owner else 'None'}")
        
        # Now create CrossOver
        cross = btind.CrossOver(self.data.close, sma)
        print(f"\n=== CrossOver created ===")
        print(f"CrossOver.lines._owner: {type(cross.lines._owner).__name__ if cross.lines._owner else 'None'}")
        
        # Check if LinesOperation was added
        from backtrader.lineiterator import LineIterator
        print(f"CrossOver._lineiterators[IndType] length: {len(cross._lineiterators.get(LineIterator.IndType, []))}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    cerebro.run()
