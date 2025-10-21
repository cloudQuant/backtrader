#!/usr/bin/env python
import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"Strategy.__init__: data has {len(self.data)} bars at init")
        if hasattr(self.data, 'buflen'):
            print(f"  data.buflen() = {self.data.buflen()}")
        
    def start(self):
        print(f"Strategy.start: data has {len(self.data)} bars")
        if hasattr(self.data, 'buflen'):
            print(f"  data.buflen() = {self.data.buflen()}")
        
    def prenext(self):
        if len(self) < 3:
            print(f"prenext {len(self)}: close={self.data.close[0]:.2f}")
        
    def next(self):
        if len(self) < 3:
            print(f"next {len(self)}: close={self.data.close[0]:.2f}")

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
