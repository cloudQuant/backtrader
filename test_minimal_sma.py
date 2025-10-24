#!/usr/bin/env python
import backtrader as bt

class DebugSMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 5),)
    
    def __init__(self):
        self.addminperiod(self.p.period)
        print(f"DebugSMA __init__: period={self.p.period}, _minperiod={self._minperiod}")
        
    def next(self):
        print(f"DebugSMA.next() called: len={len(self)}, data[0]={self.data[0]}")
        # Simple average of last 'period' bars
        total = sum([self.data[-i] for i in range(self.p.period)])
        avg = total / self.p.period
        self.lines.sma[0] = avg
        print(f"  Calculated SMA: {avg}")

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = DebugSMA(self.data, period=5)
        print(f"Strategy __init__: SMA created, in _lineiterators: {self.sma in self._lineiterators.get(bt.LineIterator.IndType, [])}")
        
    def next(self):
        if len(self) <= 10:
            print(f"Strategy.next(): len={len(self)}, close={self.data.close[0]:.2f}, sma={self.sma[0]:.2f}")

cerebro = bt.Cerebro(runonce=False, preload=True)
cerebro.addstrategy(TestStrategy)
data = bt.feeds.BacktraderCSVData(dataname='/home/yun/Documents/backtrader/tests/datas/2005-2006-day-001.txt')
cerebro.adddata(data)
print("Running...")
cerebro.run()
