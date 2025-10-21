#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind

class DebugStrategy(bt.Strategy):
    def __init__(self):
        print(f"\n=== Creating SMA with period=5 ===")
        self.sma = btind.SMA(self.data, period=5)
        print(f"After creation:")
        print(f"  SMA.p = {self.sma.p}")
        print(f"  SMA.p.period = {self.sma.p.period}")
        print(f"  SMA._minperiod = {self.sma._minperiod}")
        
if __name__ == '__main__':
    import datetime
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 31)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugStrategy)
    cerebro.run()
