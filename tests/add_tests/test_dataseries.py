#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class DataSeriesStrategy(bt.Strategy):
    def __init__(self):
        # Test dataseries access
        self.data_close = self.data.close
        self.data_open = self.data.open
        self.data_high = self.data.high
        self.data_low = self.data.low
        self.data_volume = self.data.volume

    def next(self):
        # Access dataseries values
        if len(self) > 0:
            close = self.data.close[0]
            open_price = self.data.open[0]
            high = self.data.high[0]
            low = self.data.low[0]
            volume = self.data.volume[0]
            
            # Verify values are valid
            assert close > 0
            assert open_price > 0
            assert high >= low
            assert volume >= 0


def test_dataseries(main=False):
    """Test dataseries functionality"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(DataSeriesStrategy)
    
    cerebro.run()
    
    if main:
        # print('DataSeries test passed')  # Removed for performance
        pass


if __name__ == '__main__':
    test_dataseries(main=True)

