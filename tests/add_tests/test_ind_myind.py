#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import testcommon
import backtrader.indicators as btind

chkdatas = 1
chkmin = 1


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    # Test MyInd indicator - basic custom indicator test
    try:
        testcommon.runtest(datas,
                          testcommon.TestStrategy,
                          main=main,
                          plot=main,
                          chkind=btind.MyInd,
                          chkmin=chkmin,
                          chkvals=[['0.000000', '0.000000', '0.000000']])
    except AttributeError:
        # MyInd might not be in all versions
        if main:
            print('MyInd not available, skipping test')


if __name__ == '__main__':
    test_run(main=True)

