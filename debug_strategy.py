#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')

import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    params = (('period', 15),)

    def __init__(self):
        self.orderid = None
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=False)

    def next(self):
        if len(self) <= 20:  # First 20 bars
            try:
                print(f"Bar {len(self)}: close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}, cross={self.cross[0]:.2f}")
            except Exception as e:
                print(f"Bar {len(self)}: Error reading values: {e}")
        
        if not self.position.size and self.cross[0] > 0.0:
            print(f"BUY SIGNAL at bar {len(self)}: cross={self.cross[0]}")
            self.buy()
        elif self.position.size and self.cross[0] < 0.0:
            print(f"SELL SIGNAL at bar {len(self)}: cross={self.cross[0]}")
            self.close()

cerebro = bt.Cerebro()
data = bt.feeds.BacktraderCSVData(
    dataname='/home/yun/Documents/backtrader/tests/original_tests/../datas/2006-day-001.txt'
)
cerebro.adddata(data)
cerebro.addstrategy(DebugStrategy)
cerebro.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)

results = cerebro.run()
print(f"\nFinal value: {cerebro.broker.getvalue():.2f}")
