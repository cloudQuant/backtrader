#!/usr/bin/env python


import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["0.209985", "0.299843", "0.432428"],
]

chkmin = 100
chkind = btind.HurstExponent


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 100},
        chkvals=chkvals,
    )


if __name__ == "__main__":
    test_run(main=True)
