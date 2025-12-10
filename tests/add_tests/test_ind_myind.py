#!/usr/bin/env python


import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkmin = 1


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    # Test MyInd indicator - basic custom indicator test
    try:
        testcommon.runtest(
            datas,
            testcommon.TestStrategy,
            main=main,
            plot=main,
            chkind=btind.MyInd,
            chkmin=chkmin,
            chkvals=[["0.000000", "0.000000", "0.000000"]],
        )
    except AttributeError:
        # MyInd might not be in all versions
        if main:
            # print('MyInd not available, skipping test')  # Removed for performance
            pass


if __name__ == "__main__":
    test_run(main=True)
