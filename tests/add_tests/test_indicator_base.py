#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class IndicatorTestStrategy(bt.Strategy):
    def __init__(self):
        # Test indicator creation
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.ema = bt.indicators.EMA(self.data, period=15)
        
    def next(self):
        # Verify indicators work
        if len(self) >= 15:
            assert self.sma[0] > 0
            assert self.ema[0] > 0


def test_indicator(main=False):
    """Test base indicator functionality"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(IndicatorTestStrategy)
    
    cerebro.run()
    
    if main:
        # print('Indicator base test passed')  # Removed for performance
        pass


if __name__ == '__main__':
    test_indicator(main=True)

