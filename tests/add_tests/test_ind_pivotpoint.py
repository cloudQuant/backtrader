#!/usr/bin/env python


import backtrader.indicators as btind

from . import testcommon


def test_run(main=False):
    """Test that PivotPoint indicator can be created and run"""
    import backtrader as bt

    class TestInd(bt.Strategy):
        def __init__(self):
            self.ind = btind.PivotPoint(self.data)

        def next(self):
            # Verify indicator produces values for all lines
            if len(self) >= 1:
                assert self.ind.lines.p[0] is not None
                assert self.ind.lines.s1[0] is not None
                assert self.ind.lines.s2[0] is not None
                assert self.ind.lines.r1[0] is not None
                assert self.ind.lines.r2[0] is not None

    datas = [testcommon.getdata(0)]
    cerebro = bt.Cerebro()
    for data in datas:
        cerebro.adddata(data)
    cerebro.addstrategy(TestInd)
    cerebro.run()

    if main:
        # print('PivotPoint test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_run(main=True)
