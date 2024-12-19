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

# 固定手数类，如果下单的时候没有指定size,将会默认调用一个sizer
class FixedSize(bt.Sizer):
    '''
    This sizer simply returns a fixed size for any operation.
    Size can be controlled by number of tranches that a system
    wishes to use to scale into trades by specifying the ``tranches``
    parameter.


    Params:
      - ``stake`` (default: ``1``)
      - ``tranches`` (default: ``1``)
    '''

    # 参数
    params = (('stake', 1),
              ('tranches', 1))

    # 返回具体的手数，如果tranches大于1，会把手数分成tranches份，否则直接返回手数
    def _getsizing(self, comminfo, cash, data, isbuy):
        if self.p.tranches > 1:
            return abs(int(self.p.stake / self.p.tranches))
        else:
            return self.p.stake
    # 设置手数
    def setsizing(self, stake):
        if self.p.tranches > 1:
            self.p.stake = abs(int(self.p.stake / self.p.tranches))
        else:
            self.p.stake = stake  # OLD METHOD FOR SAMPLE COMPATIBILITY

# FixedSize的另一个名称
SizerFix = FixedSize


# 如果是开仓，使用stake手，如果是反手，使用两倍的stake手
class FixedReverser(bt.Sizer):
    '''This sizer returns the needes fixed size to reverse an open position or
    the fixed size to open one

      - To open a position: return the param ``stake``

      - To reverse a position: return 2 * ``stake``

    Params:
      - ``stake`` (default: ``1``)
    '''
    params = (('stake', 1),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        position = self.strategy.getposition(data)
        size = self.p.stake * (1 + (position.size != 0))
        return size


# 固定目标手数，如果tranches大于1的话，会先把stake分成tranches份，然后计算当前持仓和每份持仓与stake的大小，选择比较小的作为下单的手数
# 如果tranches不大于1，直接使用stake手数
class FixedSizeTarget(bt.Sizer):
    '''
    This sizer simply returns a fixed target size, useful when coupled
    with Target Orders and specifically ``cerebro.target_order_size()``.
    Size can be controlled by number of tranches that a system
    wishes to use to scale into trades by specifying the ``tranches``
    parameter.


    Params:
      - ``stake`` (default: ``1``)
      - ``tranches`` (default: ``1``)
    '''

    params = (('stake', 1),
              ('tranches', 1))

    def _getsizing(self, comminfo, cash, data, isbuy):
        if self.p.tranches > 1:
            size = abs(int(self.p.stake / self.p.tranches))
            return min((self.strategy.position.size + size), self.p.stake)
        else:
            return self.p.stake

    def setsizing(self, stake):
        if self.p.tranches > 1:
            size = abs(int(self.p.stake / self.p.tranches))
            self.p.stake = min((self.strategy.position.size + size),
                               self.p.stake)
        else:
            self.p.stake = stake  # OLD METHOD FOR SAMPLE COMPATIBILITY
