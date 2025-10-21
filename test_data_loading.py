#!/usr/bin/env python
import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"Strategy init: data length = {len(self.data)}")
        
    def prenext(self):
        print(f"prenext: bar {len(self)}, data length={len(self.data)}")
        
    def next(self):
        print(f"next: bar {len(self)}, data length={len(self.data)}, close={self.data.close[0]:.2f}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 5)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    print("Running cerebro...")
    cerebro.run()
    print("Done")
