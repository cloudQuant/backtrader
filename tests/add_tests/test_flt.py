#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class FltTestStrategy(bt.Strategy):
    def next(self):
        pass


def test_flt(main=False):
    """Test flt (filter) module basic functionality"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(FltTestStrategy)
    
    results = cerebro.run()
    assert len(results) > 0
    
    if main:
        print('Flt test passed')


if __name__ == '__main__':
    test_flt(main=True)

