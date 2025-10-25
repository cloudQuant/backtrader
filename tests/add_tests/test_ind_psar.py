#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    # Allow multiple length results due to lencount variations
    [('4079.700000', '4147.380000'), ('3578.730000', '3623.990200', '3977.986404', '4142.010000'), ('3420.471369', '3462.955533', '3439.867259')],
]

chkmin = 2
chkind = btind.ParabolicSAR


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

