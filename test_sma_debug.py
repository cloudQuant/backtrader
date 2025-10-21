#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class DebugSMAStrategy(bt.Strategy):
    params = (('period', 5),)

    def __init__(self):
        print(f"\n=== DebugSMAStrategy.__init__ ===")
        print(f"self.data = {self.data}")
        print(f"self.datas = {self.datas}")
        
        # Create SMA indicator
        self.sma = btind.SMA(self.data, period=self.p.period)
        print(f"Created SMA: {self.sma}")
        print(f"SMA.lines = {self.sma.lines}")
        print(f"SMA has 'sma' line: {hasattr(self.sma.lines, 'sma')}")
        print(f"SMA._minperiod = {getattr(self.sma, '_minperiod', 'NOT SET')}")
        
    def start(self):
        print(f"\n=== Strategy.start() ===")
        print(f"self._minperiods = {getattr(self, '_minperiods', 'NOT SET')}")
        print(f"self._minperiod = {getattr(self, '_minperiod', 'NOT SET')}")
        print(f"SMA._minperiod = {getattr(self.sma, '_minperiod', 'NOT SET')}")
        print(f"self._lineiterators = {getattr(self, '_lineiterators', 'NOT SET')}")
        
    def prenext(self):
        bar = len(self)
        if bar < 10:
            print(f"prenext Bar {bar}: close={self.data.close[0]:.2f}, sma=<calculating>")
        
    def next(self):
        bar = len(self)
        close = self.data.close[0]
        
        # Try to get SMA value
        try:
            sma_val = self.sma[0]
            print(f"next Bar {bar}: close={close:.2f}, sma={sma_val}")
        except Exception as e:
            print(f"next Bar {bar}: close={close:.2f}, sma=ERROR: {e}")
        
        if bar >= 20:
            return  # Stop printing after 20 bars

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 2, 28)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(DebugSMAStrategy)
    
    print(f"\nStarting backtest...")
    cerebro.run()
    print(f"\nBacktest complete")
