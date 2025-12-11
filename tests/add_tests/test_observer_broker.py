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
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('Broker observer test completed')  # Removed for performance
            pass
            print(f"Final value: {strat.broker.getvalue()}")
        # Verify the strategy ran successfully
        assert len(strat) > 0
        assert strat.broker.getvalue() > 0


if __name__ == "__main__":
    test_run(main=True)
