#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TraceStrategy(bt.Strategy):
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
    
    def next(self):
        cross_val = self.cross[0]
        
        # Print on signal bars
        if abs(cross_val) > 0:
            has_order = self.orderid is not None
            print(f"len={len(self):3d}: cross={cross_val:+.1f}, pos={int(self.position.size)}, order={'Y' if has_order else 'N'}")
        
        if self.orderid:
            return
        
        if not self.position.size:
            if cross_val > 0:
                self.orderid = self.buy()
                print(f"  → Created BUY order")
        elif cross_val < 0:
            self.orderid = self.close()
            print(f"  → Created SELL order")
    
    def stop(self):
        print(f"\nFinal: {self.buy_count} buys, {self.sell_count} sells")

print("Testing runonce=False (uses _runnext mode):")
print("=" * 70)
cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TraceStrategy)
cerebro.run()
