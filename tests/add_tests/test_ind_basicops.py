#!/usr/bin/env python



import backtrader as bt

import backtrader.indicators as btind

from . import testcommon

chkdatas = 1


def test_highest(main=False):
    """Test Highest indicator"""
    chkvals = [
        ["4140.660000", "3685.480000", "3670.750000"],  # From actual run
    ]
    chkmin = 20
    chkind = btind.Highest

    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 20},
        chkvals=chkvals,
    )


def test_lowest(main=False):
    """Test Lowest indicator"""
    chkvals = [
        ["3932.090000", "3532.680000", "3490.240000"],  # From actual run
    ]
    chkmin = 20
    chkind = btind.Lowest

    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 20},
        chkvals=chkvals,
    )


def test_run(main=False):
    """Test basic operations indicators"""
    # Note: testcommon.TestStrategy.stop() contains assertions for chkvals
    test_highest(main)
    test_lowest(main)


if __name__ == "__main__":
    test_run(main=True)
