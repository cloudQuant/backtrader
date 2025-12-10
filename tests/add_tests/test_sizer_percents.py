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

    # Test PercentSizer
    class PercentStrategy(RunStrategy):
        def __init__(self):
            super().__init__()
            self.sizer = bt.sizers.PercentSizer(percents=20)

    cerebros = testcommon.runtest(datas, PercentStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('PercentSizer test completed')  # Removed for performance
            pass
            print(f"Final value: {strat.broker.getvalue()}")
        assert len(strat) > 0


def test_allin(main=False):
    datas = [testcommon.getdata(0)]

    # Test AllInSizer
    class AllInStrategy(RunStrategy):
        def __init__(self):
            super().__init__()
            self.sizer = bt.sizers.AllInSizer()

    cerebros = testcommon.runtest(datas, AllInStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('AllInSizer test completed')  # Removed for performance
            pass
        assert len(strat) > 0


def test_percentint(main=False):
    datas = [testcommon.getdata(0)]

    # Test PercentSizerInt
    class PercentIntStrategy(RunStrategy):
        def __init__(self):
            super().__init__()
            self.sizer = bt.sizers.PercentSizerInt(percents=20)

    cerebros = testcommon.runtest(datas, PercentIntStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('PercentSizerInt test completed')  # Removed for performance
            pass
        assert len(strat) > 0


def test_allinint(main=False):
    datas = [testcommon.getdata(0)]

    # Test AllInSizerInt
    class AllInIntStrategy(RunStrategy):
        def __init__(self):
            super().__init__()
            self.sizer = bt.sizers.AllInSizerInt()

    cerebros = testcommon.runtest(datas, AllInIntStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('AllInSizerInt test completed')  # Removed for performance
            pass
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
    test_allin(main=True)
    test_percentint(main=True)
    test_allinint(main=True)
