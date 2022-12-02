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

import calendar
import datetime

import backtrader as bt
from .. import Observer, TimeFrame

from backtrader.utils.py3 import MAXINT

# 时间收益率的类
class TimeReturn(Observer):
    '''This observer stores the *returns* of the strategy.

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` then the complete return over the entire backtested period
        will be reported

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to for example work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

      - ``fund`` (default: ``None``)

        If ``None`` the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Remember that at any moment of a ``run`` the current values can be checked
    by looking at the *lines* by name at index ``0``.

    '''
    _stclock = True
    # 设置line
    lines = ('timereturn',)
    # plotinfo信息
    plotinfo = dict(plot=True, subplot=True)
    # 设置line
    plotlines = dict(timereturn=dict(_name='Return'))
    # 参数
    params = (
        ('timeframe', None),
        ('compression', None),
        ('fund', None),
    )
    # 画图时候的标签
    def _plotlabel(self):
        return [
            # Use the final tf/comp values calculated by the return analyzer
            TimeFrame.getname(self.treturn.timeframe,
                              self.treturn.compression),
            str(self.treturn.compression)
        ]
    # 初始化，增加analyzers中的TimeReturn
    def __init__(self):
        self.treturn = self._owner._addanalyzer_slave(bt.analyzers.TimeReturn,
                                                      **self.p._getkwargs())
    # 每个next设置当前的收益率
    def next(self):
        self.lines.timereturn[0] = self.treturn.rets.get(self.treturn.dtkey,
                                                         float('NaN'))
