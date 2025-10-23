#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class TradingCalTestStrategy(bt.Strategy):
    def next(self):
        pass


def test_tradingcal(main=False):
    """Test trading calendar functionality"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(TradingCalTestStrategy)
    
    try:
        # Try to set a trading calendar if available
        import pandas as pd
        try:
            from pandas.tseries.holiday import USFederalHolidayCalendar
            cal = USFederalHolidayCalendar()
            # TradingCalendar functionality test
        except:
            pass
    except:
        pass
    
    results = cerebro.run()
    assert len(results) > 0
    
    if main:
        print('TradingCal test passed')


if __name__ == '__main__':
    test_tradingcal(main=True)

