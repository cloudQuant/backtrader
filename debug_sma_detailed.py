import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch SMA manual calculation
original_manual = bt.indicators.SMA._calculate_sma_manual
def debug_manual(self, period):
    result = original_manual(self, period)
    if len(self) <= 18:
        has_idx = hasattr(self, '_idx')
        window_len = len(self._price_window) if hasattr(self, '_price_window') else 0
        sum_val = self._sum if hasattr(self, '_sum') else 0
        print(f"  _calculate_sma_manual: len={len(self)}, has_idx={has_idx}, window_len={window_len}, sum={sum_val:.2f}, result={result}")
    return result
bt.indicators.SMA._calculate_sma_manual = debug_manual

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
    
    def next(self):
        if len(self) <= 18:
            print(f"Strategy.next() len={len(self)}: sma={self.sma[0]:.2f}")

cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("=== Testing SMA manual calculation ===\n")
cerebro.run()
