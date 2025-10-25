#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch to trace execution flow
from backtrader.brokers.bbroker import BackBroker

original_next = BackBroker.next
call_stack = []
def debug_next(self):
    import traceback
    stack = [line.strip() for line in traceback.format_stack()[-6:-1]]
    call_stack.append(('next', len(self.pending), stack))
    
    pending_before = len(self.pending)
    original_next(self)
    pending_after = len(self.pending)
    
    if pending_before > 0 or pending_after > 0:
        print(f"Broker.next: pending {pending_before}→{pending_after}")
        for line in stack[-2:]:
            print(f"  {line}")

BackBroker.next = debug_next

original_submit_accept = BackBroker.submit_accept
def debug_submit_accept(self, order):
    import traceback
    print(f"\nBroker.submit_accept: order ref={order.ref}, pending={len(self.pending)}")
    stack = [line.strip() for line in traceback.format_stack()[-5:-1]]
    for line in stack[-3:]:
        print(f"  {line}")
    
    original_submit_accept(self, order)
    print(f"  → After: pending={len(self.pending)}\n")

BackBroker.submit_accept = debug_submit_accept

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n*** Strategy.next len={len(self)}: Creating BUY order ***")
            self.orderid = self.buy()
            print(f"*** Order created: ref={self.orderid.ref} ***\n")

print("Testing exactbars=-2:")
print("=" * 70)
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
cerebro.run()
