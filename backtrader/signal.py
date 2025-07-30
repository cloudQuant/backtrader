#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

# 创建不同的SIGNAL类型
(

    SIGNAL_NONE,
    SIGNAL_LONGSHORT,
    SIGNAL_LONG,
    SIGNAL_LONG_INV,
    SIGNAL_LONG_ANY,
    SIGNAL_SHORT,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORT_ANY,
    SIGNAL_LONGEXIT,
    SIGNAL_LONGEXIT_INV,
    SIGNAL_LONGEXIT_ANY,
    SIGNAL_SHORTEXIT,
    SIGNAL_SHORTEXIT_INV,
    SIGNAL_SHORTEXIT_ANY,

) = range(14)

# 不同的信号类型
SignalTypes = [
    SIGNAL_NONE,
    SIGNAL_LONGSHORT,
    SIGNAL_LONG, SIGNAL_LONG_INV, SIGNAL_LONG_ANY,
    SIGNAL_SHORT, SIGNAL_SHORT_INV, SIGNAL_SHORT_ANY,
    SIGNAL_LONGEXIT, SIGNAL_LONGEXIT_INV, SIGNAL_LONGEXIT_ANY,
    SIGNAL_SHORTEXIT, SIGNAL_SHORTEXIT_INV, SIGNAL_SHORTEXIT_ANY
]

# 继承指标，创建一个signal指标
class Signal(bt.Indicator):
    # 信号类型
    SignalTypes = SignalTypes
    # 创建了一个signal的line
    lines = ('signal',)
    # 初始化
    def __init__(self):
        self.lines.signal = self.data0.lines[0]
        self.plotinfo.plotmaster = getattr(self.data0, '_clock', self.data0)
