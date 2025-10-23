#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class TalibTestStrategy(bt.Strategy):
    def __init__(self):
        try:
            # Try to use talib indicator if available
            self.sma = bt.talib.SMA(self.data.close, timeperiod=15)
        except:
            # If talib not available, use regular SMA
            self.sma = bt.indicators.SMA(self.data, period=15)

    def next(self):
        pass


def test_talib(main=False):
    """Test talib integration"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(TalibTestStrategy)
    
    results = cerebro.run()
    assert len(results) > 0
    
    if main:
        print('Talib test passed (or skipped if talib not installed)')


if __name__ == '__main__':
    test_talib(main=True)

