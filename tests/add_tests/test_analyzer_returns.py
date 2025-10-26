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

    def next(self):
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main,
                                  analyzer=(bt.analyzers.Returns, {}))

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('Returns Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # Check for expected keys
            assert 'rtot' in analysis
            assert 'ravg' in analysis
            assert 'rnorm' in analysis
            # Verify actual values from run
            expected_rtot = 0.028013920205183424
            assert abs(analysis['rtot'] - expected_rtot) < 0.01
            # Verify rnorm100 is percentage form
            assert 'rnorm100' in analysis
            assert abs(analysis['rnorm100'] - 2.807111707414246) < 0.1


if __name__ == '__main__':
    test_run(main=True)

