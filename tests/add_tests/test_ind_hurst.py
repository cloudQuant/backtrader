#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    # Allow both 254 and 255 length results
    ['0.209985', ('0.299843', '0.315214'), ('0.432428', '0.409012')],
]

chkmin = 100
chkind = btind.HurstExponent


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(datas,
                       testcommon.TestStrategy,
                       main=main,
                       plot=main,
                       chkind=chkind,
                       chkmin=chkmin,
                       chkargs={'period': 100},
                       chkvals=chkvals)

if __name__ == '__main__':
    test_run(main=True)

