#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch _oncepost
original_oncepost = bt.Strategy._oncepost
call_count = 0
def debug_oncepost(self, dt):
    global call_count
    call_count += 1
    
    pending_count = len(self._orderspending)
    
    if call_count <= 25 or pending_count > 0:
        print(f"_oncepost #{call_count}: _orderspending={pending_count}, len(self)={len(self)}")
    
    result = original_oncepost(self, dt)
    
    pending_after = len(self._orderspending)
    if pending_count != pending_after:
        print(f"  → _orderspending changed: {pending_count} → {pending_after}")
    
    return result

bt.Strategy._oncepost = debug_oncepost

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def notify_order(self, order):
        print(f"  notify_order: {order.Status[order.status]}")
        if order.status == order.Completed:
            self.orderid = None
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n*** Creating BUY order at len={len(self)} ***\n")
            self.orderid = self.buy()

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
cerebro.run()
