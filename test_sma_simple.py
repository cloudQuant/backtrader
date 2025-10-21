#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class SimpleTestStrategy(bt.Strategy):
    def __init__(self):
        # Create SMA with period=5
        self.sma5 = btind.SMA(self.data, period=5)
        print(f"SMA5 created with period parameter: {self.sma5.p.period}")
        print(f"SMA5._minperiod: {self.sma5._minperiod}")
        
        # Create default SMA (should be period=30)
        self.sma30 = btind.SMA(self.data)
        print(f"SMA30 created with default period: {self.sma30.p.period}")
        print(f"SMA30._minperiod: {self.sma30._minperiod}")
        
    def next(self):
        bar = len(self)
        if bar % 5 == 0 or bar < 10:
            # Print first 10 bars and then every 5th bar
            print(f"Bar {bar}: close={self.data.close[0]:.2f}, sma5={self.sma5[0]}, sma30={self.sma30[0]}")
            
            # Check if the SMA should have a valid value by now
            if bar >= 4:  # Should have 5 bars for SMA5
                last_5_closes = [self.data.close[-i] for i in range(5)]
                manual_avg = sum(last_5_closes) / 5
                print(f"  Manual calculation of 5-bar average: {manual_avg:.2f}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 31)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleTestStrategy)
    cerebro.run()
