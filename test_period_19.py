#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 19),)
    
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.trades = []
    
    def notify_order(self, order):
        if order.status == order.Completed:
            self.orderid = None
            trade_type = "BUY" if isinstance(order, bt.BuyOrder) else "SELL"
            self.trades.append((len(self), trade_type, order.executed.price))
    
    def next(self):
        if self.orderid:
            return
        if not self.position.size:
            if self.cross > 0.0:
                self.orderid = self.buy()
        elif self.cross < 0.0:
            self.orderid = self.close()
    
    def stop(self):
        value = self.broker.getvalue()
        print(f"Period 19: Final value={value:.2f}")
        print(f"Total trades: {len(self.trades)}")
        for i, (bar, ttype, price) in enumerate(self.trades[:10]):
            print(f"  {i+1}. Bar {bar}: {ttype} @ {price:.2f}")

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=False)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
cerebro.addstrategy(TestStrategy)
cerebro.run()
