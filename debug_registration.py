import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class DebugStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        
        print(f"\n=== Strategy Indicators ===")
        print(f"Total indicators: {len(self._lineiterators[bt.LineIterator.IndType])}")
        for i, ind in enumerate(self._lineiterators[bt.LineIterator.IndType]):
            print(f"  {i}: {ind.__class__.__name__} - minperiod={ind._minperiod}")
            if hasattr(ind, 'nzd'):
                print(f"       has nzd: {ind.nzd.__class__.__name__}")

cerebro = bt.Cerebro()
cerebro.addstrategy(DebugStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.run(runonce=True, preload=True)
