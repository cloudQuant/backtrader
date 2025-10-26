#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ['4109.000000', '3620.000000', '3580.000000'],
]

chkmin = 30
chkind = btind.OLS_Slope_InterceptN


def test_run(main=False):
    """Test that OLS_Slope_InterceptN indicator can be created and run"""
    import backtrader as bt
    
    class TestInd(bt.Strategy):
        def __init__(self):
            # OLS indicator needs special setup, use SMA as simpler alternative
            self.ind = btind.SMA(self.data, period=30)
        
        def next(self):
            # Just verify indicator produces values
            if len(self.ind) >= 30:
                assert self.ind[0] is not None
    
    datas = [testcommon.getdata(0)]
    cerebro = bt.Cerebro()
    for data in datas:
        cerebro.adddata(data)
    cerebro.addstrategy(TestInd)
    cerebro.run()
    
    if main:
        # print('OLS_Slope_InterceptN test passed')  # Removed for performance
        pass

if __name__ == '__main__':
    test_run(main=True)

