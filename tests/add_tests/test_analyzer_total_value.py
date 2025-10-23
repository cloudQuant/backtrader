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
                                  analyzer=(bt.analyzers.TotalValue, {}))

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            print('TotalValue Analysis:')
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # TotalValue should record portfolio value over time
            assert len(analysis) > 0  # Should have value recordings
            # All values should be positive
            for dt, value in analysis.items():
                assert value > 0, f"Portfolio value {value} should be positive"


if __name__ == '__main__':
    test_run(main=True)

