#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch _addnotification
original_addnotification = bt.Strategy._addnotification
def debug_addnotification(self, order, quicknotify=False):
    print(f"  Strategy._addnotification: order ref={order.ref}, status={order.Status[order.status]}, "
          f"quicknotify={quicknotify}, executed.size={order.executed.size}")
    result = original_addnotification(self, order, quicknotify=quicknotify)
    print(f"    → Done")
    return result

bt.Strategy._addnotification = debug_addnotification

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def notify_order(self, order):
        print(f">>>>>> STRATEGY.notify_order: status={order.Status[order.status]} <<<<<<")
        if order.status == order.Completed:
            self.orderid = None
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n=== Creating BUY order at len={len(self)} ===\n")
            self.orderid = self.buy()

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
print(f"quicknotify={cerebro.p.quicknotify}\n")
cerebro.run()
