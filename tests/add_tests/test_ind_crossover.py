#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind


def test_run(main=False):
    """Test CrossOver indicator"""
    import backtrader as bt
    
    # Test CrossOver functionality
    class TestCrossStrategy(bt.Strategy):
        def __init__(self):
            sma1 = btind.SMA(self.data, period=15)
            sma2 = btind.SMA(self.data, period=30)
            self.crossover = btind.CrossOver(sma1, sma2)
        
        def next(self):
            # Verify crossover produces values
            if len(self) >= 30:
                # CrossOver returns 1, -1, or 0
                assert self.crossover[0] in [-1, 0, 1]
    
    datas = [testcommon.getdata(0)]
    cerebro = bt.Cerebro()
    for data in datas:
        cerebro.adddata(data)
    cerebro.addstrategy(TestCrossStrategy)
    results = cerebro.run()
    
    # Verify test ran
    assert len(results) > 0
    assert len(results[0]) > 0
    
    if main:
        print('CrossOver test passed')


if __name__ == '__main__':
    test_run(main=True)
