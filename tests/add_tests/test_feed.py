#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class FeedTestStrategy(bt.Strategy):
    def next(self):
        # Just verify data is loaded
        if len(self) == 1:
            assert self.data.close[0] > 0


def test_feed(main=False):
    """Test data feed loading"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(FeedTestStrategy)
    
    results = cerebro.run()
    
    # Verify feed loaded data correctly
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy ran through data
    
    if main:
        # print('Feed test passed')  # Removed for performance
        pass


if __name__ == '__main__':
    test_feed(main=True)

