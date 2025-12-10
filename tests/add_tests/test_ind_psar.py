#!/usr/bin/env python


import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["4079.700000", "3578.730000", "3420.471369"],
]

chkmin = 2
chkind = btind.ParabolicSAR


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkvals=chkvals,
    )


if __name__ == "__main__":
    test_run(main=True)
