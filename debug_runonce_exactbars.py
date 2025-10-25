#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon

# Patch CrossOver.once to debug
original_once = bt.indicators.CrossOver.once
def debug_once(self, start, end):
    print(f"\nCrossOver.once called: start={start}, end={end}")
    print(f"  d0array size: {len(self.data0.array)}, d1array size: {len(self.data1.array)}")
    print(f"  crossarray size before: {len(self.line.array)}")
    
    original_once(self, start, end)
    
    print(f"  crossarray size after: {len(self.line.array)}")
    
    # Count non-zero crossovers
    crosses = [v for v in self.line.array[start:end] if abs(v) > 0]
    print(f"  Non-zero crosses: {len(crosses)}")
    if len(crosses) <= 15:
        print(f"  Cross values: {[f'{v:.1f}' for v in crosses]}")

bt.indicators.CrossOver.once = debug_once

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        print(f"Strategy.__init__: cross indicator created")
    
    def next(self):
        if abs(self.cross[0]) > 0:
            print(f"  Strategy.next len={len(self)}: cross={self.cross[0]:.1f}")

print("Testing runonce=True, exactbars=False (SHOULD PASS):")
print("=" * 70)
cerebro1 = bt.Cerebro(runonce=True, preload=True, exactbars=False)
data1 = testcommon.getdata(0)
cerebro1.adddata(data1)
cerebro1.addstrategy(TestStrategy)
cerebro1.run()

print("\n\nTesting runonce=True, exactbars=-2 (FAILS):")
print("=" * 70)
cerebro2 = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
data2 = testcommon.getdata(0)
cerebro2.adddata(data2)
cerebro2.addstrategy(TestStrategy)
cerebro2.run()
