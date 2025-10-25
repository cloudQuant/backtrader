import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class DebugStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        print("Strategy initialized")
        
    def prenext(self):
        pass
        
    def next(self):
        print(f"Bar: close={self.data.close[0]:.2f}, cross={self.cross[0]}")

cerebro = bt.Cerebro()
cerebro.addstrategy(DebugStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("Running...")
cerebro.run(runonce=True, preload=True)
print("Done")
