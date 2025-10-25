import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 15), ('mode_name', ''))
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.values = []
    
    def prenext(self):
        # 在prenext阶段也记录
        self.values.append((len(self.data), self.cross[0], self.data.close[0], self.sma[0]))
    
    def next(self):
        self.values.append((len(self.data), self.cross[0], self.data.close[0], self.sma[0]))
    
    def stop(self):
        print(f"\n{self.p.mode_name}:")
        # 显示前50个bar的CrossOver值
        for i, (bar, cross, close, sma) in enumerate(self.values[:60]):
            if cross != 0 or (bar >= 15 and bar <= 25):
                sign = "=" if cross == 0 else ("+" if cross > 0 else "-")
                print(f"  Bar {bar:3d}: cross={sign}{abs(cross):.1f}, close={close:7.2f}, sma={sma:7.2f}")

# Test once mode
print("="*70)
cerebro1 = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro1.addstrategy(TestStrategy, mode_name="ONCE MODE")
data1 = testcommon.getdata(0)
cerebro1.adddata(data1)
cerebro1.run()

# Test next mode
print("\n" + "="*70)
cerebro2 = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro2.addstrategy(TestStrategy, mode_name="NEXT MODE")
data2 = testcommon.getdata(0)
cerebro2.adddata(data2)
cerebro2.run()
