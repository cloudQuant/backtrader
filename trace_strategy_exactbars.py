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
        self.buycreate = []
        self.sellcreate = []
    
    def notify_order(self, order):
        if order.status == order.Completed:
            self.orderid = None  # Allow new orders
    
    def next(self):
        cross_val = self.cross[0]
        
        # Only print on signal bars or first 5 bars after minperiod
        if abs(cross_val) > 0 or len(self) <= 20:
            has_position = self.position.size != 0
            has_order = self.orderid is not None
            
            action = ""
            if self.orderid:
                action = "SKIP (order pending)"
            elif not self.position.size:
                if cross_val > 0:
                    self.orderid = self.buy()
                    self.buycreate.append(f'{self.data.close[0]:.2f}')
                    action = f"BUY @ {self.data.close[0]:.2f}"
            elif cross_val < 0:
                self.orderid = self.close()
                self.sellcreate.append(f'{self.data.close[0]:.2f}')
                action = f"SELL @ {self.data.close[0]:.2f}"
            
            print(f"  len={len(self):3d}: cross={cross_val:+.1f}, pos={int(self.position.size)}, "
                  f"order={'Y' if has_order else 'N'}, {action}")
    
    def stop(self):
        print(f"\nFinal: buys={len(self.buycreate)}, sells={len(self.sellcreate)}")

print("Testing exactbars=False (SHOULD: 12 buys, 11 sells):")
print("=" * 70)
cerebro1 = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro1.adddata(testcommon.getdata(0))
cerebro1.addstrategy(TraceStrategy)
cerebro1.run()

print("\n\nTesting exactbars=-2 (CURRENTLY: 1 buy, 0 sells):")
print("=" * 70)
cerebro2 = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro2.adddata(testcommon.getdata(0))
cerebro2.addstrategy(TraceStrategy)
cerebro2.run()
