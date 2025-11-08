#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class SignalTestStrategy(bt.SignalStrategy):
    def __init__(self):
        # CRITICAL FIX: Call super().__init__() to initialize _signals
        super(SignalTestStrategy, self).__init__()
        sma1 = bt.indicators.SMA(self.data, period=10)
        sma2 = bt.indicators.SMA(self.data, period=30)
        self.signal_add(bt.SIGNAL_LONG, bt.ind.CrossOver(sma1, sma2))


def test_signal(main=False):
    """Test signal-based strategy"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(SignalTestStrategy)
    
    results = cerebro.run()
    assert len(results) > 0
    assert results[0].broker.getvalue() > 0
    
    if main:
        # print('Signal test passed')  # Removed for performance
        pass


if __name__ == '__main__':
    test_signal(main=True)

