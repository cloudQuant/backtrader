import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 15), ('mode_name', ''))
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.bar_num = 0
        self.signals = []
    
    def next(self):
        self.bar_num += 1
        cross_val = self.cross[0]
        if cross_val != 0:
            self.signals.append((self.bar_num, cross_val, self.data.close[0]))
    
    def stop(self):
        print(f"\n{self.p.mode_name}:")
        print(f"  Total signals: {len(self.signals)}")
        for i, (bar, val, price) in enumerate(self.signals[:15]):
            sign = "UP" if val > 0 else "DN"
            print(f"    {i+1}. Bar {bar}: {sign} @ {price:.2f}")

# Test once mode
print("="*60)
cerebro1 = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro1.addstrategy(TestStrategy, mode_name="ONCE MODE (runonce=True)")
data1 = testcommon.getdata(0)
cerebro1.adddata(data1)
cerebro1.run()

# Test next mode  
print("\n" + "="*60)
cerebro2 = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro2.addstrategy(TestStrategy, mode_name="NEXT MODE (runonce=False)")
data2 = testcommon.getdata(0)
cerebro2.adddata(data2)
cerebro2.run()

print("\n" + "="*60)
