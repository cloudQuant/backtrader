#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"\n=== TestStrategy.__init__ ===")
        self.sma = btind.SMA(self.data, period=5)
        print(f"SMA created, period={self.sma.p.period}")
        
        # Patch the sma.next() to see if it's called
        orig_next = self.sma.next
        self.sma_next_called = 0
        def tracked_next():
            self.sma_next_called += 1
            print(f"  SMA.next() called #{self.sma_next_called}")
            return orig_next()
        self.sma.next = tracked_next
        
        # Also patch sma.advance()
        orig_advance = self.sma.advance
        self.sma_advance_called = 0
        def tracked_advance(size=1):
            self.sma_advance_called += 1
            print(f"  SMA.advance() called #{self.sma_advance_called}, size={size}")
            return orig_advance(size)
        self.sma.advance = tracked_advance
        
    def next(self):
        if len(self) < 10:
            print(f"Strategy.next() bar {len(self)}: close={self.data.close[0]:.2f}, sma={self.sma[0]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 10)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    print("\nRunning cerebro...")
    cerebro.run()
    print("\nDone")
