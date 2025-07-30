#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import testcommon

import backtrader as bt
import backtrader.indicators as btind


chkdatas = 1


class RunStrategy(bt.Strategy):
    params = dict(main=False)

    def __init__(self):
        btind.SMA()


def test_run(main=False):
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(datas,
                                  RunStrategy,
                                  main=main,
                                  plot=main,
                                  writer=(bt.WriterStringIO, dict(csv=True)))

    for cerebro in cerebros:
        writer = cerebro.runwriters[0]
        if main:
            # writer.out.seek(0)
            for l in writer.out:
                print(l.rstrip('\r\n'))

        else:
            lines = iter(writer.out)
            l = next(lines).rstrip('\r\n')
            assert l == '=' * 79

            count = 0
            while True:
                l = next(lines).rstrip('\r\n')
                if l[0] == '=':
                    break
                count += 1

            assert count == 256  # header + 256 lines data


if __name__ == '__main__':
    test_run(main=True)
