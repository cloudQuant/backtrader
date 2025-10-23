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
                                  analyzer=(bt.analyzers.TradeAnalyzer, {}))

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            print('TradeAnalyzer Analysis:')
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            assert 'total' in analysis
            # Verify total trades from actual run
            assert hasattr(analysis.total, 'total')
            expected_total = 12  # From actual run
            assert analysis.total.total == expected_total
            # Verify closed trades
            assert hasattr(analysis.total, 'closed')
            assert analysis.total.closed == 11  # From actual run
            # Verify won/lost statistics
            assert 'won' in analysis
            assert 'lost' in analysis
            assert analysis.won.total == 5  # From actual run
            assert analysis.lost.total == 6  # From actual run


if __name__ == '__main__':
    test_run(main=True)

