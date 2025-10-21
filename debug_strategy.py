#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind
import datetime

class DebugStrategy(bt.Strategy):
    params = (
        ('period', 15),
    )

    def __init__(self):
        print(f"DebugStrategy.__init__: Starting")
        print(f"DebugStrategy.__init__: self.datas = {self.datas}")
        print(f"DebugStrategy.__init__: self.data = {self.data}")
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=True)
        print(f"DebugStrategy.__init__: Created SMA and CrossOver")
        
    def start(self):
        print(f"DebugStrategy.start: Starting")
        self.order = None
        
    def next(self):
        print(f"DebugStrategy.next: Called at bar {len(self)}")
        print(f"DebugStrategy.next: self.cross = {self.cross[0]}")
        print(f"DebugStrategy.next: self.position.size = {self.position.size}")
        
        if self.order:
            return
            
        if not self.position.size:
            if self.cross > 0.0:
                print(f"DebugStrategy.next: BUY SIGNAL!")
                self.order = self.buy()
                print(f"DebugStrategy.next: buy() returned {self.order}")
        elif self.cross < 0.0:
            print(f"DebugStrategy.next: SELL SIGNAL!")
            self.order = self.close()
            
    def stop(self):
        print(f"DebugStrategy.stop: Final portfolio value: {self.broker.getvalue()}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)
    
    # Add strategy
    cerebro.addstrategy(DebugStrategy)
    
    # Set broker
    cerebro.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
    
    print(f"Starting Portfolio Value: {cerebro.broker.getvalue():.2f}")
    cerebro.run()
    print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}")
