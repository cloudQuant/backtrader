#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"\n=== In TestStrategy.__init__ ===")
        cross = btind.CrossOver(self.data.close, btind.SMA(self.data, period=15))
        
        # Check if lines is instance or class
        print(f"cross.lines type: {type(cross.lines)}")
        print(f"cross.lines is CrossOver.lines: {cross.lines is btind.CrossOver.lines}")
        print(f"cross.lines._owner: {type(cross.lines._owner).__name__ if hasattr(cross.lines, '_owner') and cross.lines._owner else 'None'}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    cerebro.run()
