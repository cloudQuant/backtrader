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
        cross_val = self.cross[0]
        if self.bar_num <= 30 or cross_val != 0:
            print(f"Bar {self.bar_num}: cross_val={cross_val}, cross>0={self.cross > 0}, cross<0={self.cross < 0}")

# Test first configuration: preload=True, runonce=True, exactbars=False
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("\n=== Running ===")
cerebro.run()
