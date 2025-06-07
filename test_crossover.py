#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    def __init__(self):
        # Create a CrossOver indicator
        self.sma1 = bt.indicators.SimpleMovingAverage(self.data, period=10)
        self.sma2 = bt.indicators.SimpleMovingAverage(self.data, period=30)
        self.crossover = bt.indicators.CrossOver(self.sma1, self.sma2)
        
        # Print attributes to debug
        print(f"SMA1 has _idx: {hasattr(self.sma1, '_idx')}")
        print(f"SMA2 has _idx: {hasattr(self.sma2, '_idx')}")
        print(f"CrossOver has _idx: {hasattr(self.crossover, '_idx')}")
        
        print(f"SMA1 has _clock: {hasattr(self.sma1, '_clock')}")
        print(f"SMA2 has _clock: {hasattr(self.sma2, '_clock')}")
        print(f"CrossOver has _clock: {hasattr(self.crossover, '_clock')}")
        
    def next(self):
        if len(self) < 35:  # Only print for the first few bars
            return
            
        print(f"Date: {self.data.datetime.date(0)}, CrossOver: {self.crossover[0]}")

def main():
    # Create a cerebro entity
    cerebro = bt.Cerebro()
    
    # Add a data feed
    # Use the base CSVDataBase directly, which has no issues with parameter naming
    data = bt.feeds.BacktraderCSVData(
        dataname='/Users/yunjinqi/Documents/backtrader/tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)
    
    # Add a strategy
    cerebro.addstrategy(TestStrategy)
    
    # Run over everything
    cerebro.run()

if __name__ == "__main__":
    main()
