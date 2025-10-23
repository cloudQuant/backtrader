#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

class TestStrategy(bt.Strategy):
    def __init__(self):
        btind.SMA()  # Default period is 30
        self.count_prenext = 0
        self.count_nextstart = 0
        self.count_next = 0
        
    def prenext(self):
        self.count_prenext += 1
        
    def nextstart(self):
        self.count_nextstart += 1
        
    def next(self):
        self.count_next += 1

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(
        dataname='/home/yun/Documents/backtrader/tests/datas/2006-day-001.txt'
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    # Run with runonce=True
    result = cerebro.run()
    strat = result[0]
    
    print(f"prenext called: {strat.count_prenext} times")
    print(f"nextstart called: {strat.count_nextstart} times")
    print(f"next called: {strat.count_next} times")
    print(f"Total: {strat.count_prenext + strat.count_nextstart + strat.count_next}")
    print(f"Expected: 256")
