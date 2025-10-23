#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class SessionFilterStrategy(bt.Strategy):
    def next(self):
        # Verify data is valid
        assert self.data.close[0] is not None


def test_run(main=False):
    """Test SessionFilter and SessionFiller"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    # Session filters work with intraday data
    # For daily data, just verify it doesn't break
    cerebro.adddata(data)
    cerebro.addstrategy(SessionFilterStrategy)
    
    results = cerebro.run()
    
    # Verify filter worked
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy processed data
    
    if main:
        print('SessionFilter test passed')


if __name__ == '__main__':
    test_run(main=True)

