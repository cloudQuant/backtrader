import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch SMA to add debug
original_sma_next = bt.indicators.SMA.next
call_count = [0]
def debug_next(self):
    call_count[0] += 1
    if call_count[0] <= 5:
        print(f"  SMA.next() called: len={len(self)}, value will be {self.lines.sma[0] if hasattr(self, 'lines') else 'N/A'}")
    original_sma_next(self)
bt.indicators.SMA.next = debug_next

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        print("Strategy.__init__: Creating SMA")
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        print(f"  SMA created: {self.sma}")
        print("Strategy.__init__: Creating CrossOver")
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        print(f"  CrossOver created: {self.cross}")
        self.bar_num = 0
    
    def prenext(self):
        self.bar_num += 1
        if self.bar_num <= 5:
            print(f"Strategy.prenext() bar {self.bar_num}")
    
    def next(self):
        self.bar_num += 1
        if self.bar_num <= 20:
            print(f"Strategy.next() bar {self.bar_num}: sma={self.sma[0]:.2f}, cross={self.cross[0]:.1f}")

# Test runonce=False
cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("=== Testing runonce=False ===\n")
cerebro.run()
