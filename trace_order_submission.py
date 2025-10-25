#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch broker methods to trace order flow
from backtrader.brokers.bbroker import BackBroker

original_submit = BackBroker.submit
def debug_submit(self, order, check=True):
    print(f"Broker.submit called: order ref={order.ref}, check={check}")
    result = original_submit(self, order, check=check)
    print(f"  → submit returned: {result}")
    return result
BackBroker.submit = debug_submit

original_submit_accept = BackBroker.submit_accept
def debug_submit_accept(self, order):
    print(f"Broker.submit_accept called: order ref={order.ref}")
    print(f"  → pending queue size before: {len(self.pending)}")
    original_submit_accept(self, order)
    print(f"  → pending queue size after: {len(self.pending)}")
BackBroker.submit_accept = debug_submit_accept

original_transmit = BackBroker.transmit
def debug_transmit(self, order, check=True):
    print(f"Broker.transmit called: order ref={order.ref}, check={check}")
    print(f"  → checksubmit={self.get_param('checksubmit')}")
    result = original_transmit(self, order, check=check)
    return result
BackBroker.transmit = debug_transmit

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n=== Strategy len={len(self)}: Creating BUY order ===")
            self.orderid = self.buy()
            print(f"=== Order object returned: ref={self.orderid.ref} ===\n")

print("Testing exactbars=-2:")
print("=" * 70)
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
cerebro.run()
