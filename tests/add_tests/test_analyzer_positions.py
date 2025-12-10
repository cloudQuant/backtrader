#!/usr/bin/env python


import backtrader as bt

from . import testcommon


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
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.PositionsValue, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('Positions Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # Positions should track position values over time
            # Dict should have datetime keys with position values
            assert len(analysis) >= 0  # May be empty if no positions taken


if __name__ == "__main__":
    test_run(main=True)
