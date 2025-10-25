#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    # Allow multiple length results due to lencount variations
    ['4063.463000', ('3644.444667', '3604.330000', '3648.549000'), ('3554.693333', '3559.765667', '3557.698667')],
]

chkmin = 30
chkind = btind.SMA


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

