import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch SMA.nextstart to debug
original_nextstart = bt.indicators.SMA.nextstart
def debug_nextstart(self):
    period = self.p.period
    print(f"\nSMA.nextstart() called: len(self.data)={len(self.data)}, period={period}")
    
    # Show what data we're accessing
    prices = []
    for i in range(-period, 0):
        price = self.data[i]
        prices.append(price)
    print(f"  Prices from range(-{period}, 0): {[f'{p:.2f}' for p in prices[:5]]} ... {[f'{p:.2f}' for p in prices[-3:]]}")
    print(f"  Average: {sum(prices)/len(prices):.2f}")
    
    original_nextstart(self)
    
    print(f"  Result sma[0]: {self.lines.sma[0]:.2f}")
    print(f"  _price_window len: {len(self._price_window)}, _sum: {self._sum:.2f}")

bt.indicators.SMA.nextstart = debug_nextstart

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
    
    def next(self):
        if len(self) <= 18:
            print(f"  Strategy.next() len={len(self)}: sma={self.sma[0]:.2f}")

cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.run()
