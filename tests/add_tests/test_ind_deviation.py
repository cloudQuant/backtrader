#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ['58.042315', '50.824827', '73.944160'],
]

chkmin = 30
chkind = btind.StandardDeviation


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(datas,
                       testcommon.TestStrategy,
                       main=main,
                       plot=main,
                       chkind=chkind,
                       chkmin=chkmin,
                       chkargs={'period': 30},
                       chkvals=chkvals)

if __name__ == '__main__':
    test_run(main=True)

