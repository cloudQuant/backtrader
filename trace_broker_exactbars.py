#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon

class TraceStrategy(bt.Strategy):
    params = (('period', 15),)
    
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.order_count = 0
        self.notify_count = 0
    
    def notify_order(self, order):
        self.notify_count += 1
        print(f"  notify_order #{self.notify_count}: len={len(self)}, status={order.Status[order.status]}, "
              f"type={'BUY' if isinstance(order, bt.BuyOrder) else 'SELL'}")
        
        if order.status == order.Completed:
            print(f"    → Order COMPLETED at price {order.executed.price:.2f}")
            self.orderid = None
        elif order.status in [order.Submitted, order.Accepted]:
            print(f"    → Order {order.Status[order.status]}")
        else:
            print(f"    → Order {order.Status[order.status]} (not completed!)")
            self.orderid = None  # Clear anyway
    
    def next(self):
        if len(self) == 19 or len(self) == 44:
            cross_val = self.cross[0]
            print(f"\n  Strategy.next len={len(self)}: cross={cross_val:.1f}, orderid={'SET' if self.orderid else 'None'}")
            
            if self.orderid:
                print(f"    → SKIP (order pending)")
                return
            
            if len(self) == 19 and cross_val > 0:
                self.order_count += 1
                self.orderid = self.buy()
                print(f"    → BUY order #{self.order_count} created: {self.orderid}")
            elif len(self) == 44 and cross_val < 0:
                self.order_count += 1
                self.orderid = self.close()
                print(f"    → SELL order #{self.order_count} created: {self.orderid}")
    
    def stop(self):
        print(f"\nFinal: orders created={self.order_count}, notify_order calls={self.notify_count}")

print("Testing exactbars=False:")
print("=" * 70)
cerebro1 = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro1.adddata(testcommon.getdata(0))
cerebro1.addstrategy(TraceStrategy)
cerebro1.run()

print("\n\nTesting exactbars=-2:")
print("=" * 70)
cerebro2 = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro2.adddata(testcommon.getdata(0))
cerebro2.addstrategy(TraceStrategy)
cerebro2.run()
