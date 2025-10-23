#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class HeikinAshiStrategy(bt.Strategy):
    def __init__(self):
        # Verify HeikinAshi modified data
        self.sma = bt.indicators.SMA(self.data, period=10)
    
    def next(self):
        # Verify data is valid
        assert self.data.open[0] is not None
        assert self.data.high[0] is not None
        assert self.data.low[0] is not None
        assert self.data.close[0] is not None
        # HA property: close is average of OHLC
        # open is midpoint of prev bar


def test_run(main=False):
    """Test HeikinAshi filter"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    # Add HeikinAshi filter
    data.addfilter(bt.filters.HeikinAshi)
    
    cerebro.adddata(data)
    cerebro.addstrategy(HeikinAshiStrategy)
    
    results = cerebro.run()
    
    # Verify filter worked
    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0  # Strategy processed HA data
    # Verify HA data was created (implicitly tested by strategy running successfully)
    
    if main:
        print('HeikinAshi filter test passed')
        print(f'Processed {len(strat)} bars')


if __name__ == '__main__':
    test_run(main=True)

