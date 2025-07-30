#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import testcommon

import backtrader as bt

chkdatas = 1
chkvals = [
    ['4119.466107', '3591.732500', '3578.625259'],
    ['4142.010000', '3638.420000', '3662.920000'],
    ['4119.466107', '3591.732500', '3578.625259'],
    ['4128.002500', '3614.670000', '3653.455000']
]

chkmin = 2
chkind = bt.ind.HeikinAshi


def test_run(main=False):
    if False:
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
