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
                                  analyzer=(bt.analyzers.GrossLeverage, {}))

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            print('GrossLeverage Analysis:')
            print(analysis)
            print(f'Number of leverage readings: {len(analysis)}')
        else:
            # Verify that analysis is a dictionary
            assert isinstance(analysis, dict)
            # Verify we have leverage values
            assert len(analysis) > 0
            # Leverage values should be between 0 (all cash) and 1 (fully invested)
            for dt, lev in analysis.items():
                assert 0 <= lev <= 1, f"Leverage {lev} out of range [0,1]"


if __name__ == '__main__':
    test_run(main=True)

