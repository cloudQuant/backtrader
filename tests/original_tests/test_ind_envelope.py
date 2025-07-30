#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ['4063.463000', '3644.444667', '3554.693333'],
    ['4165.049575', '3735.555783', '3643.560667'],
    ['3961.876425', '3553.333550', '3465.826000']
]

chkmin = 30
chkind = btind.Envelope


class TS2(testcommon.TestStrategy):
    def __init__(self):
        ind = btind.MovAv.SMA(self.data)
        self.p.inddata = [ind]
        super(TS2, self).__init__()


def test_run(main=True):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(datas,
                       TS2,
                       main=main,
                       plot=False,
                       chkind=chkind,
                       chkmin=chkmin,
                       chkvals=chkvals)


if __name__ == '__main__':
    test_run(main=True)
