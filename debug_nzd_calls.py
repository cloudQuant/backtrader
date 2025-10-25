#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt

# Patch NZD.next to track calls
from backtrader.indicators.crossover import NonZeroDifference
original_next = NonZeroDifference.next

call_count = [0]

def tracked_next(self):
    call_count[0] += 1
    if call_count[0] <= 5 or 18 <= len(self) <= 20:
        print(f"NZD.next() called! Count={call_count[0]}, len={len(self)}")
    return original_next(self)

NonZeroDifference.next = tracked_next

class TestStrat(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.nzd = NonZeroDifference(self.data.close, self.sma)

    def next(self):
        if len(self) == 19:
            print(f"Strategy.next() bar 19: NZD value = {self.nzd[0]:.2f}")

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(TestStrat)
cerebro.run()

print(f"\nTotal NZD.next() calls: {call_count[0]}")
