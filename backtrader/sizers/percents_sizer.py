#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
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

__all__ = ['PercentSizer', 'AllInSizer', 'PercentSizerInt', 'AllInSizerInt']


# 百分比手数，根据可以利用的现金的百分比下单
class PercentSizer(bt.Sizer):
    '''This sizer return percents of available cash

    Params:
      - ``percents`` (default: ``20``)
    '''

    # 参数
    params = (
        ('percents', 20),
        ('retint', False),  # return an int size or rather the float value
    )

    def __init__(self):
        pass

    # 如果当前没有持仓，根据现金的百分比计算可以下单的数目
    # 如果当前有持仓，根据，直接使用持仓的大小作为下单的手数
    # 如果需要转化成整数，那么就转化为整数
    def _getsizing(self, comminfo, cash, data, isbuy):
        position = self.broker.getposition(data)
        if not position:
            size = cash / data.close[0] * (self.params.percents / 100)
        else:
            size = position.size

        if self.p.retint:
            size = int(size)

        return size

# 利用所有的现金进行下单
class AllInSizer(PercentSizer):
    '''This sizer return all available cash of broker

     Params:
       - ``percents`` (default: ``100``)
     '''
    params = (
        ('percents', 100),
    )

# 按照百分比进行计算下单的手数，然后要取整
class PercentSizerInt(PercentSizer):
    '''This sizer return percents of available cash in form of size truncated
    to an int

    Params:
      - ``percents`` (default: ``20``)
    '''

    params = (
        ('retint', True),  # return an int size or rather the float value
    )

# 根据所有的现金进行下单，手数要取整
class AllInSizerInt(PercentSizerInt):
    '''This sizer return all available cash of broker with the
    size truncated to an int

     Params:
       - ``percents`` (default: ``100``)
     '''
    params = (
        ('percents', 100),
    )
