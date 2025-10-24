#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import backtrader.indicators as btind
import datetime
import os

class TestStrategy(bt.Strategy):
    params = (
        ('period', 30),
    )
    
    def __init__(self):
        self.sma = btind.SMA(self.data, period=self.p.period)
    
    def stop(self):
        l = len(self.sma)
        mp = self.p.period
        
        # Check points: first valid value, middle, last
        chkpts = [0, -l + mp, (-l + mp) // 2]
        
        print(f"Total length: {l}")
        print(f"len(self): {len(self)}")
        print(f"Min period: {mp}")
        print(f"Check points: {chkpts}")
        print(f"self.data._idx: {getattr(self.data, '_idx', 'NOT SET')}")
        print(f"self.data.lines.datetime._idx: {getattr(self.data.lines.datetime, '_idx', 'NOT SET')}")
        print(f"self.sma._idx: {getattr(self.sma, '_idx', 'NOT SET')}")
        print(f"datetime.array length: {len(self.data.lines.datetime.array)}")
        print(f"datetime.array[-5:]: {self.data.lines.datetime.array[-5:]}")
        print(f"close.array length: {len(self.data.lines.close.array)}")
        print(f"close.array[-5:]: {self.data.lines.close.array[-5:]}")
        print(f"sma.array length: {len(self.sma.lines.sma.array)}")
        print(f"sma.array[-5:]: {self.sma.lines.sma.array[-5:]}")
        
        for chkpt in chkpts:
            dt_value = self.data.lines.datetime[chkpt]
            print(f"  datetime[{chkpt}] raw value: {dt_value}")
            dtstr = self.data.datetime.date(chkpt).strftime('%Y-%m-%d')
            sma_val = self.sma[chkpt]
            print(f"  chkpt {chkpt} ({dtstr}): SMA = {sma_val:.6f} (formatted: '{sma_val:f}')")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = os.path.join(os.path.dirname(__file__), 'tests/datas/2006-day-001.txt')
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    cerebro.adddata(data)
    
    cerebro.addstrategy(TestStrategy, period=30)
    
    print("Running test...")
    cerebro.run()
    print("\nExpected values:")
    print("  ['4063.463000', '3644.444667', '3554.693333']")
