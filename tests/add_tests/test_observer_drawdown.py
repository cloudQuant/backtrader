#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader as bt


class RunStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Add DrawDown observer
        bt.observers.DrawDown()

    def next(self):
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)
    
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('DrawDown observer test completed')  # Removed for performance
            pass
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == '__main__':
    test_run(main=True)

