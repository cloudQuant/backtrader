#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon

# Patch broker.next() to trace execution
from backtrader.brokers.bbroker import BackBroker
original_next = BackBroker.next
call_count = 0
def debug_next(self):
    global call_count
    call_count += 1
    
    pending_count = len(self.pending)
    
    if call_count <= 25 or pending_count > 0:
        print(f"Broker.next #{call_count}: pending orders={pending_count}")
    
    # Call original
    original_next(self)
    
    # Check notifications
    notif = self.get_notification()
    if notif:
        print(f"  → Notification available: {notif.Status[notif.status]}")
        # Put it back for the strategy to get
        self.notifs.append(notif)

BackBroker.next = debug_next

# Patch _try_exec to see execution attempts
original_try_exec = BackBroker._try_exec
def debug_try_exec(self, order):
    print(f"    _try_exec called for order ref={order.ref}, status={order.Status[order.status]}")
    try:
        result = original_try_exec(self, order)
        print(f"    → After _try_exec: status={order.Status[order.status]}, alive={order.alive()}")
        return result
    except Exception as e:
        print(f"    → ERROR in _try_exec: {e}")
        raise

BackBroker._try_exec = debug_try_exec

class TestStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def notify_order(self, order):
        print(f"  STRATEGY notify_order: status={order.Status[order.status]}")
        if order.status == order.Completed:
            self.orderid = None
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\nStrategy len={len(self)}: Creating BUY order")
            self.orderid = self.buy()
            print(f"  Order created: ref={self.orderid.ref}\n")

print("Testing exactbars=-2:")
print("=" * 70)
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
cerebro.run()
