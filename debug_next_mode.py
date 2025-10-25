import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.bar_num = 0
    
    def next(self):
        self.bar_num += 1
        if self.bar_num <= 40 or self.cross[0] != 0:
            print(f"Bar {self.bar_num}: cross={self.cross[0]:.1f}, close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")

# Test runonce=False (next mode)
cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("=== Testing runonce=False (next mode) ===")
cerebro.run()
