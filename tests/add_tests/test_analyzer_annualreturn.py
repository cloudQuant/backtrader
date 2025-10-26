#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader as bt


class RunStrategy(bt.Strategy):
    params = (
        ('period', 15),
        ('printdata', True),
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


chkdatas = 1


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(datas,
                                  RunStrategy,
                                  printdata=main,
                                  plot=main,
                                  analyzer=(bt.analyzers.AnnualReturn, {}))

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print('AnnualReturn Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            # Verify that analysis is a dictionary and contains year keys
            assert isinstance(analysis, dict)
            assert len(analysis) > 0
            # Check that the year 2006 is present
            assert 2006 in analysis
            # Verify the actual return value for 2006 (from actual run)
            assert abs(analysis[2006] - 0.0284) < 0.01


if __name__ == '__main__':
    test_run(main=True)

