#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt

# Patch CrossUp.once to add debugging
original_once = bt.indicators.crossover.CrossUp.once

def debug_once(self, start, end):
    print(f"\n=== CrossUp.once called: start={start}, end={end} ===")
    
    # Call original
    result = original_once(self, start, end)
    
    # Check results at key points
    cross_array = self.lines.cross.array
    for i in [15, 18, 19, 20]:
        if start <= i < end:
            print(f"  cross_array[{i}] = {cross_array[i]:.2f}")
    
    return result

bt.indicators.crossover.CrossUp.once = debug_once

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()

print(f"\nFinal value: {cerebro.broker.getvalue():.2f}")
