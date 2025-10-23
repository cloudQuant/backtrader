#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind


def test_run(main=False):
    """Test that PivotPoint indicator can be created and run"""
    import backtrader as bt
    
    class TestInd(bt.Strategy):
        def __init__(self):
            self.ind = btind.PivotPoint(self.data)
        
        def next(self):
            # Verify indicator produces values for all lines
            if len(self) >= 1:
                assert self.ind.lines.p[0] is not None
                assert self.ind.lines.s1[0] is not None
                assert self.ind.lines.s2[0] is not None
                assert self.ind.lines.r1[0] is not None
                assert self.ind.lines.r2[0] is not None
    
    datas = [testcommon.getdata(0)]
    cerebro = bt.Cerebro()
    for data in datas:
        cerebro.adddata(data)
    cerebro.addstrategy(TestInd)
    cerebro.run()
    
    if main:
        print('PivotPoint test passed')


if __name__ == '__main__':
    test_run(main=True)
