#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        
        print("\n=== Before CrossOver creation ===")
        
        # Create CrossOver manually to debug
        cross = btind.CrossOver(self.data.close, self.sma)
        
        print("\n=== After CrossOver creation ===")
        print(f"CrossOver.lines type: {type(cross.lines)}")
        print(f"CrossOver.lines.__class__: {cross.lines.__class__}")
        
        # Check if crossover attribute is a descriptor
        print(f"\nChecking 'crossover' attribute in Lines class:")
        lines_class = cross.lines.__class__
        if hasattr(lines_class, 'crossover'):
            attr = getattr(lines_class, 'crossover')
            print(f"  crossover attribute type: {type(attr)}")
            print(f"  Is LineAlias: {type(attr).__name__}")
        else:
            print("  'crossover' not found as class attribute")
        
        # Check instance attribute
        print(f"\nChecking instance attribute:")
        if hasattr(cross.lines, 'crossover'):
            print(f"  cross.lines.crossover exists: {type(cross.lines.crossover)}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
