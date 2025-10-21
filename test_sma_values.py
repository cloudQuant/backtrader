#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class TestSMAStrategy(bt.Strategy):
    def __init__(self):
        self.sma5 = btind.SMA(self.data, period=5)
        self.sma15 = btind.SMA(self.data, period=15)
        
    def next(self):
        bar = len(self)
        if bar < 20 or bar % 10 == 0:
            print(f"Bar {bar}: close={self.data.close[0]:.2f}, sma5={self.sma5[0]:.2f}, sma15={self.sma15[0]:.2f}")
            
            # Manually calculate SMA5 to verify
            if bar >= 4:
                manual_sma5 = sum(self.data.close[-i] for i in range(5)) / 5
                print(f"  Manual SMA5 = {manual_sma5:.2f}, Indicator SMA5 = {self.sma5[0]:.2f}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 2, 1)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestSMAStrategy)
    cerebro.run()
    print(f"\nFinal value: {cerebro.broker.getvalue():.2f}")
