import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class DebugCrossOver(bt.indicators.CrossOver):
    def nextstart(self):
        diff = self.data0[0] - self.data1[0]
        self._last_nzd = diff
        self.lines.crossover[0] = 0.0
        print(f"nextstart: diff={diff:.2f}, _last_nzd={self._last_nzd:.2f}, result=0.0")
    
    def next(self):
        diff = self.data0[0] - self.data1[0]
        prev_nzd = self._last_nzd if self._last_nzd is not None else diff
        self._last_nzd = diff if diff != 0.0 else prev_nzd
        up_cross = 1.0 if (prev_nzd < 0.0 and self.data0[0] > self.data1[0]) else 0.0
        down_cross = 1.0 if (prev_nzd > 0.0 and self.data0[0] < self.data1[0]) else 0.0
        result = up_cross - down_cross
        self.lines.crossover[0] = result
        
        if len(self) <= 25 or result != 0:
            print(f"next len={len(self)}: diff={diff:.2f}, prev_nzd={prev_nzd:.2f}, _last_nzd={self._last_nzd:.2f}, up={up_cross}, down={down_cross}, result={result}")

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = DebugCrossOver(self.data.close, self.sma)
    
    def next(self):
        pass

cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
print("=== Tracing CrossOver in next() mode ===\n")
cerebro.run()
