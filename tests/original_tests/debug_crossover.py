import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class DebugStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.bar_num = 0
        
    def next(self):
        self.bar_num += 1
        cross_val = self.cross[0]
        if cross_val != 0.0:
            print(f"Bar {self.bar_num}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}, cross={cross_val}")

cerebro = bt.Cerebro()
cerebro.addstrategy(DebugStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.run(runonce=True, preload=True)
