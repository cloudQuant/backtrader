#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch _notify
original_notify_method = bt.Strategy._notify
def debug_notify(self, qorders=[], qtrades=[]):
    if len(self._orderspending) > 0 or len(qorders) > 0:
        print(f"  Strategy._notify called: _orderspending={len(self._orderspending)}, qorders={len(qorders)}, quicknotify={self.cerebro.p.quicknotify}")
    result = original_notify_method(self, qorders=qorders, qtrades=qtrades)
    return result

bt.Strategy._notify = debug_notify

# Patch notify_order
original_notify_order = bt.Strategy.notify_order
def debug_notify_order(self, order):
    print(f">>>>>> STRATEGY.notify_order: status={order.Status[order.status]} <<<<<<")
    result = original_notify_order(self, order)
    return result

bt.Strategy.notify_order = debug_notify_order

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n=== Creating BUY order at len={len(self)} ===\n")
            self.orderid = self.buy()

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
print(f"quicknotify={cerebro.p.quicknotify}\n")
cerebro.run()
