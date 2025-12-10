#!/usr/bin/env python


import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["8.536393", "33.289375", "46.992371"],
    ["13.866583", "28.956875", "69.517198"],
]

chkmin = 4
chkind = btind.haDelta


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
