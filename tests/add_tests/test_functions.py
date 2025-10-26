#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backtrader as bt
import backtrader.functions as btfunc


def test_functions_and_or(main=False):
    """Test And and Or functions"""
    
    class FuncStrategy(bt.Strategy):
        def __init__(self):
            sma1 = bt.indicators.SMA(self.data, period=10)
            sma2 = bt.indicators.SMA(self.data, period=20)
            
            # Test And
            self.and_signal = btfunc.And(self.data.close > sma1, sma1 > sma2)
            
            # Test Or  
            self.or_signal = btfunc.Or(self.data.close > sma1, self.data.close > sma2)
        
        def next(self):
            # Verify signals produce values
            assert self.and_signal[0] is not None
            assert self.or_signal[0] is not None
    
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    import datetime
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(FuncStrategy)
    cerebro.run()
    
    if main:
        # print('And/Or functions test passed')  # Removed for performance
        pass


def test_functions_if(main=False):
    """Test If function"""
    
    class IfStrategy(bt.Strategy):
        def __init__(self):
            sma = bt.indicators.SMA(self.data, period=10)
            
            # Test If function
            self.if_result = btfunc.If(self.data.close > sma, 1, -1)
        
        def next(self):
            # Verify If produces values
            if len(self) >= 10:
                assert self.if_result[0] is not None
                assert self.if_result[0] in [1, -1]
    
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    import datetime
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(IfStrategy)
    cerebro.run()
    
    if main:
        # print('If function test passed')  # Removed for performance
        pass


def test_functions_max_min(main=False):
    """Test Max and Min functions"""
    
    class MaxMinStrategy(bt.Strategy):
        def __init__(self):
            sma1 = bt.indicators.SMA(self.data, period=10)
            sma2 = bt.indicators.SMA(self.data, period=20)
            
            # Test Max and Min
            self.max_val = btfunc.Max(sma1, sma2)
            self.min_val = btfunc.Min(sma1, sma2)
        
        def next(self):
            if len(self) >= 20:
                assert self.max_val[0] is not None
                assert self.min_val[0] is not None
                assert self.max_val[0] >= self.min_val[0]
    
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    import datetime
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(MaxMinStrategy)
    cerebro.run()
    
    if main:
        # print('Max/Min functions test passed')  # Removed for performance
        pass


if __name__ == '__main__':
    test_functions_and_or(main=True)
    test_functions_if(main=True)
    test_functions_max_min(main=True)

