#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

from backtrader.brokers.bbroker import BackBroker

original_check_submitted = BackBroker.check_submitted
def debug_check_submitted(self):
    print(f"\ncheck_submitted: submitted queue size={len(self.submitted)}")
    original_check_submitted(self)
    print(f"  → After: submitted={len(self.submitted)}, pending={len(self.pending)}")

BackBroker.check_submitted = debug_check_submitted

original_execute = BackBroker._execute
def debug_execute(self, order, cash, position):
    print(f"  _execute: order ref={order.ref}, cash_before={cash:.2f}")
    result_cash = original_execute(self, order, cash=cash, position=position)
    print(f"    → cash_after={result_cash:.2f}, {'OK' if result_cash >= 0 else 'MARGIN CALL!'}")
    return result_cash

BackBroker._execute = debug_execute

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def notify_order(self, order):
        print(f"  NOTIFY: status={order.Status[order.status]}")
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n*** Strategy len={len(self)}: Creating BUY order ***")
            self.orderid = self.buy()

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
print("Testing exactbars=-2:\n")
cerebro.run()
