#!/usr/bin/env python

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    params = (
        ("period", 15),
        ("printdata", True),
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
    cerebros = testcommon.runtest(
        datas, RunStrategy, printdata=main, plot=main, analyzer=(bt.analyzers.Calmar, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print('Calmar Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            # Verify that analysis is a dictionary
            assert isinstance(analysis, dict)
            # Verify calmar attribute exists
            assert hasattr(analyzer, "calmar")


if __name__ == "__main__":
    test_run(main=True)
