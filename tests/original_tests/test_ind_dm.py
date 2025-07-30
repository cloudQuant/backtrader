#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ['15.302485', '31.674648', '15.961767'],
    ['18.839142', '26.946536', '18.161738'],
    ['28.809535', '30.460124', '31.386311'],
    ['24.638772', '18.914537', '21.564611'],
]

chkmin = 42
chkind = btind.DM


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
