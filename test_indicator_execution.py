#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class DebugStrategy(bt.Strategy):
    params = (('period', 5),)
    
    def __init__(self):
        print(f"\n=== Strategy.__init__ ===")
        self.sma = btind.SMA(self.data, period=self.p.period)
        print(f"SMA created: {self.sma}")
        print(f"SMA.p.period = {self.sma.p.period}")
        print(f"SMA._minperiod = {self.sma._minperiod}")
        print(f"SMA has next method: {hasattr(self.sma, 'next')}")
        print(f"SMA has once method: {hasattr(self.sma, 'once')}")
        
    def prenext(self):
        if len(self) < 10:
            print(f"prenext {len(self)}: data[0]={self.data[0]:.2f}, checking SMA...")
            # Try to manually call SMA.next() to see if it works
            try:
                self.sma.next()
                print(f"  After manual next(): sma[0]={self.sma[0]}")
            except Exception as e:
                print(f"  Error calling sma.next(): {e}")
                
    def next(self):
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
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
