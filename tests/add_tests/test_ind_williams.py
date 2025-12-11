#!/usr/bin/env python



import backtrader as bt

import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["-16.458733", "-68.298609", "-28.602854"],
]

chkmin = 14
chkind = btind.WilliamsR


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
