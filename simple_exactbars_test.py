#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.buy_count = 0
        self.sell_count = 0
    
    def notify_order(self, order):
        if order.status == order.Completed:
            if isinstance(order, bt.BuyOrder):
                self.buy_count += 1
                print(f"  BUY COMPLETED at len={len(self)}, price={order.executed.price:.2f}")
            else:
                self.sell_count += 1
                print(f"  SELL COMPLETED at len={len(self)}, price={order.executed.price:.2f}")
            self.orderid = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"  ORDER {order.Status[order.status]} at len={len(self)}")
            self.orderid = None
    
    def next(self):
        cross_val = self.cross[0]
        
        if self.orderid:
            return
        
        if not self.position.size:
            if cross_val > 0:
                print(f"BUY signal at len={len(self)}, cross={cross_val}")
                self.orderid = self.buy()
        elif cross_val < 0:
            print(f"SELL signal at len={len(self)}, cross={cross_val}")
            self.orderid = self.close()
    
    def stop(self):
        print(f"\nFinal: {self.buy_count} buys, {self.sell_count} sells, value={self.broker.getvalue():.2f}")

print("Testing exactbars=False (SHOULD WORK):")
print("=" * 70)
cerebro1 = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro1.adddata(testcommon.getdata(0))
cerebro1.addstrategy(TestStrategy)
cerebro1.run()

print("\n\nTesting exactbars=-2 (BROKEN):")
print("=" * 70)
cerebro2 = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro2.adddata(testcommon.getdata(0))
cerebro2.addstrategy(TestStrategy)
cerebro2.run()
