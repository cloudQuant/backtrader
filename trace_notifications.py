#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

from backtrader.brokers.bbroker import BackBroker

original_notify = BackBroker.notify
def debug_notify(self, order):
    print(f"  Broker.notify: order ref={order.ref}, status={order.Status[order.status]}")
    original_notify(self, order)
    print(f"    → Added to notifs queue, size={len(self.notifs)}")

BackBroker.notify = debug_notify

original_get_notification = BackBroker.get_notification
def debug_get_notification(self):
    print(f"  Broker.get_notification called, notifs size={len(self.notifs)}")
    result = original_get_notification(self)
    if result:
        print(f"    → Returning: order ref={result.ref}, status={result.Status[result.status]}")
    else:
        print(f"    → Returning: None")
    return result

BackBroker.get_notification = debug_get_notification

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def notify_order(self, order):
        print(f"STRATEGY.notify_order: status={order.Status[order.status]}")
        if order.status == order.Completed:
            self.orderid = None
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n=== Creating BUY order at len={len(self)} ===\n")
            self.orderid = self.buy()

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
print("Testing exactbars=-2:\n")
cerebro.run()
