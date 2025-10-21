#!/usr/bin/env python
import backtrader as bt
import datetime

class SimpleStrategy(bt.Strategy):
    def __init__(self):
        print(f"SimpleStrategy.__init__: datas={self.datas}")
        
    def next(self):
        pass

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 10)
    )
    cerebro.adddata(data)
    print(f"\nAdded data to cerebro: {data}")
    print(f"cerebro.datas = {cerebro.datas}")
    
    cerebro.addstrategy(SimpleStrategy)
    print(f"\nStarting cerebro.run()...")
    cerebro.run()
