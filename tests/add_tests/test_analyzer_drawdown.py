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
    # Test both DrawDown and TimeDrawDown
    for analyzer_class in [bt.analyzers.DrawDown, bt.analyzers.TimeDrawDown]:
        cerebros = testcommon.runtest(datas,
                                      RunStrategy,
                                      printdata=main,
                                      plot=main,
                                      analyzer=(analyzer_class, {}))

        for cerebro in cerebros:
            strat = cerebro.runstrats[0][0]  # no optimization, only 1
            analyzer = strat.analyzers[0]  # only 1
            analysis = analyzer.get_analysis()
            if main:
                # print(f'{analyzer_class.__name__} Analysis:')  # Removed for performance
                pass
                print(analysis)
            else:
                # Verify that analysis is a dictionary
                assert isinstance(analysis, dict)
                # Verify expected keys exist
                if analyzer_class == bt.analyzers.DrawDown:
                    assert 'len' in analysis
                    assert 'max' in analysis
                    # Verify specific values from actual run
                    assert hasattr(analysis.max, 'drawdown')
                    assert hasattr(analysis.max, 'len')
                    # Verify max drawdown and length (from actual run)
                    assert analysis.max.drawdown > 0  # Should have some drawdown
                    assert analysis.max.len > 0  # Should have length > 0
                    assert analysis.max.len == 157  # Specific value from run
                else:  # TimeDrawDown
                    assert 'maxdrawdown' in analysis
                    assert analysis['maxdrawdown'] >= 0


if __name__ == '__main__':
    test_run(main=True)

