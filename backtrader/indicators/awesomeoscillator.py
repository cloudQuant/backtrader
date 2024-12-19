#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Ssoftware Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from . import MovAv


__all__ = ['AwesomeOscillator', 'AwesomeOsc', 'AO']


# AwesomeOscillator指标
class AwesomeOscillator(bt.Indicator):
    '''
    Awesome Oscillator (AO) is a momentum indicator reflecting the precise
    changes in the market driving force which helps to identify the trend’s
    strength up to the points of formation and reversal.


    Formula:
     - median price = (high + low) / 2
     - AO = SMA(median price, 5)- SMA(median price, 34)

    See:
      - https://www.metatrader5.com/en/terminal/help/indicators/bw_indicators/awesome
      - https://www.ifcmarkets.com/en/ntx-indicators/awesome-oscillator

    '''
    # 别名
    alias = ('AwesomeOsc', 'AO')
    # 要生成的line
    lines = ('ao',)
    # 参数
    params = (
        ('fast', 5),
        ('slow', 34),
        ('movav', MovAv.SMA),
    )
    # 画图的参数
    plotlines = dict(ao=dict(_method='bar', alpha=0.50, width=1.0))

    # 初始化的时候，创建指标
    def __init__(self):
        # 最高价和最低价的平均值
        median_price = (self.data.high + self.data.low) / 2.0
        # 计算平均值的fast个周期的平均值
        sma1 = self.p.movav(median_price, period=self.p.fast)
        # 计算平均值的slow个周期的平均值
        sma2 = self.p.movav(median_price, period=self.p.slow)
        # 计算两者的差
        self.l.ao = sma1 - sma2
        # super
        super(AwesomeOscillator, self).__init__()
