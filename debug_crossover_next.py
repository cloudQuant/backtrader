import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch CrossOver.next to add debug
original_cross_next = bt.indicators.CrossOver.next
def debug_next(self):
    before_last_nzd = self._last_nzd if hasattr(self, '_last_nzd') else None
    original_cross_next(self)
    after_last_nzd = self._last_nzd if hasattr(self, '_last_nzd') else None
    result = self.lines.crossover[0]
    if len(self) <= 25 or result != 0:
        diff = self.data0[0] - self.data1[0]
        print(f"  CrossOver.next() len={len(self)}: diff={diff:.2f}, before_nzd={before_last_nzd:.2f if before_last_nzd else None}, after_nzd={after_last_nzd:.2f if after_last_nzd else None}, result={result}")
bt.indicators.CrossOver.next = debug_next

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        pass

cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("=== Testing CrossOver.next() ===\n")
cerebro.run()
