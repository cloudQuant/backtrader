#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon

# Patch CrossOver to debug
original_next = bt.indicators.CrossOver.next
call_count = 0
def debug_next(self):
    global call_count
    call_count += 1
    
    # Try to get values
    try:
        d0_val = self.data0[0]
        d1_val = self.data1[0]
        diff = d0_val - d1_val
        
        if call_count <= 25 or (hasattr(self, 'lines') and abs(self.lines.crossover[0]) > 0):
            print(f"  CrossOver.next #{call_count}: d0={d0_val:.2f}, d1={d1_val:.2f}, diff={diff:.2f}, _last_nzd={getattr(self, '_last_nzd', None):.2f if getattr(self, '_last_nzd', None) else None}")
    except Exception as e:
        print(f"  CrossOver.next #{call_count}: ERROR accessing data - {e}")
    
    original_next(self)
    
    try:
        result = self.lines.crossover[0]
        if call_count <= 25 or abs(result) > 0:
            print(f"    → result={result:.1f}")
    except Exception as e:
        print(f"    → ERROR getting result - {e}")

bt.indicators.CrossOver.next = debug_next

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        pass

print("Testing exactbars=-2:")
print("=" * 60)
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.addstrategy(TestStrategy)
cerebro.run()
