#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import testcommon

import backtrader as bt

chkdatas = 1
chkvals = [
    ['4110.000000', '3821.030000', '3748.785000'],
    ['4030.920000', '3821.030000', '3676.860000'],
    ['4057.485000', '3753.502500', '3546.152500'],
    ['3913.300000', '3677.815000', '3637.130000'],
    [('nan', '3682.320000'), '3590.910000', '3899.410000']
]

chkmin = 78
chkind = bt.ind.Ichimoku


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(datas,
                       testcommon.TestStrategy,
                       main=main,
                       plot=main,
                       chkind=chkind,
                       chkmin=chkmin,
                       chkvals=chkvals)


if __name__ == '__main__':
    test_run(main=True)
