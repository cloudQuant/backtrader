import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if self.cross > 0:
            print(f"BUY SIGNAL: close={self.data.close[0]:.2f}, cross={self.cross[0]}")
        elif self.cross < 0:
            print(f"SELL SIGNAL: close={self.data.close[0]:.2f}, cross={self.cross[0]}")

# Test first configuration: preload=True, runonce=True, exactbars=False
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("\n=== Running: runonce=True, preload=True, exactbars=False ===")
cerebro.run()
print(f"Final value: {cerebro.broker.getvalue():.2f}")
