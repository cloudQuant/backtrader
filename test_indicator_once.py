#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=5)
        print(f"SMA created, period={self.sma.p.period}")
        print(f"SMA._clock = {self.sma._clock if hasattr(self.sma, '_clock') else 'NOT SET'}")
        
    def next(self):
        if len(self) < 3:
            print(f"next {len(self)}: close={self.data.close[0]:.2f}, sma={self.sma[0]}")

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
    print("Done")
