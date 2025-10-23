#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import backtrader as bt


class SimpleStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            self.close()


def test_cerebro_basic(main=False):
    """Test basic cerebro functionality"""
    cerebro = bt.Cerebro()
    
    # Create a data feed
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    cerebro.broker.setcash(10000.0)
    
    if main:
        print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    
    cerebro.run()
    
    if main:
        print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    
    # Verify cerebro ran
    assert cerebro.broker.getvalue() > 0


def test_cerebro_analyzer(main=False):
    """Test cerebro with analyzers"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    results = cerebro.run()
    strat = results[0]
    
    if main:
        print('Sharpe Ratio:', strat.analyzers.sharpe.get_analysis())
        print('Returns:', strat.analyzers.returns.get_analysis())
    
    # Verify analyzers worked
    assert hasattr(strat.analyzers, 'sharpe')
    assert hasattr(strat.analyzers, 'returns')


def test_cerebro_observer(main=False):
    """Test cerebro with observers"""
    cerebro = bt.Cerebro()
    
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, '../datas/2006-day-001.txt')
    
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31))
    
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    cerebro.addobserver(bt.observers.DrawDown)
    
    results = cerebro.run()
    
    # Verify observer was added
    assert len(results) > 0
    assert len(results[0].observers) > 0
    
    if main:
        print('Cerebro with observers test passed')


if __name__ == '__main__':
    test_cerebro_basic(main=True)
    test_cerebro_analyzer(main=True)
    test_cerebro_observer(main=True)

