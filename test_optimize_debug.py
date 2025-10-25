#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if self.orderid:
            return
        if not self.position.size:
            if self.cross > 0.0:
                self.orderid = self.buy()
        elif self.cross < 0.0:
            self.orderid = self.close()
    
    def stop(self):
        value = self.broker.getvalue()
        print(f"Period {self.p.period}: value={value:.2f}")

# Run optimization for periods 15-20
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=False, optreturn=False, maxcpus=1)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
cerebro.optstrategy(TestStrategy, period=range(15, 21))
print("Testing optimization periods 15-20:")
cerebro.run()
