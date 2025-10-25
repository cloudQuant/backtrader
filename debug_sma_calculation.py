import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch SMA to add debug
original_sma_next = bt.indicators.SMA.next
def debug_next(self):
    before_val = self.lines.sma[0] if len(self) > 0 else 0.0
    original_sma_next(self)
    after_val = self.lines.sma[0]
    if len(self) <= 20:
        data_vals = [self.data[i] for i in range(-min(len(self)-1, 4), 1)]
        print(f"  SMA.next() len={len(self)}: before={before_val:.2f}, after={after_val:.2f}, last_data={data_vals}")
bt.indicators.SMA.next = debug_next

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
    
    def next(self):
        pass

cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("=== Testing SMA calculation in next() mode ===\n")
cerebro.run()
