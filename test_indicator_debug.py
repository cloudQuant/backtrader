#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class DebugIndicatorStrategy(bt.Strategy):
    def __init__(self):
        print(f"\n=== Strategy Init ===")
        # Create SMA with period=5
        self.sma = btind.SMA(self.data, period=5)
        print(f"SMA created, period={self.sma.p.period}")
        print(f"SMA._minperiod={self.sma._minperiod}")
        print(f"SMA.lines={self.sma.lines}")
        print(f"SMA.lines.sma exists? {hasattr(self.sma.lines, 'sma')}")
        
        # Check if SMA.next is being called
        original_next = self.sma.next
        def debug_next():
            print(f"SMA.next() called at len={len(self.sma)}, data[0]={self.data[0]}")
            result = original_next()
            print(f"  After SMA.next(), sma[0]={self.sma.lines.sma[0]}")
            return result
        self.sma.next = debug_next
        
    def prenext(self):
        if len(self) < 10:
            print(f"prenext {len(self)}: data[0]={self.data[0]:.2f}, len(sma)={len(self.sma)}, sma[0]={self.sma[0]}")
            
    def next(self):
        if len(self) < 10:
            print(f"next {len(self)}: data[0]={self.data[0]:.2f}, sma[0]={self.sma[0]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 10)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugIndicatorStrategy)
    
    print("\n=== Running Cerebro ===")
    cerebro.run()
