#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch notify_order to see if it's called
original_notify_order = bt.Strategy.notify_order
call_count = 0
def debug_notify_order(self, order):
    global call_count
    call_count += 1
    print(f"  notify_order #{call_count}: status={order.Status[order.status]}, len={len(self)}")
    return original_notify_order(self, order)
bt.Strategy.notify_order = debug_notify_order

class TraceStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\nlen={len(self)}: Creating BUY order")
            self.orderid = self.buy()
            print(f"  Order created: {self.orderid}\n")

cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TraceStrategy)
print("Testing runonce=False:\n")
cerebro.run()
print(f"\nTotal notify_order calls: {call_count}")
