#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=15)
        self.cross = btind.CrossOver(self.data.close, self.sma)
        print(f"Created CrossOver, has array: {hasattr(self.cross, 'array')}")
        print(f"CrossOver type: {type(self.cross)}")
        print(f"CrossOver.__class__.__mro__: {[c.__name__ for c in type(self.cross).__mro__]}")

cerebro = bt.Cerebro()

# Create a Data Feed
data = bt.feeds.GenericCSVData(
    dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt',
    dtformat='%Y-%m-%d',
    openinterest=-1,
    timeframe=bt.TimeFrame.Days,
)

cerebro.adddata(data)
cerebro.addstrategy(TestStrategy)

print("Running backtest...")
cerebro.run()
print("Done!")
