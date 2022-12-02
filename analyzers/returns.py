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

import math

import backtrader as bt
from backtrader import TimeFrameAnalyzerBase

# 使用对数方法计算总的，平均，复合和年化收益率
class Returns(TimeFrameAnalyzerBase):
    '''Total, Average, Compound and Annualized Returns calculated using a
    logarithmic approach

    See:

      - https://www.crystalbull.com/sharpe-ratio-better-with-log-returns/

    Params:

      - ``timeframe`` (default: ``None``)

        If ``None`` the ``timeframe`` of the 1st data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to for example work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If ``None`` then the compression of the 1st data of the system will be
        used

      - ``tann`` (default: ``None``)

        Number of periods to use for the annualization (normalization) of the

        namely:

          - ``days: 252``
          - ``weeks: 52``
          - ``months: 12``
          - ``years: 1``

      - ``fund`` (default: ``None``)

        If ``None`` the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys

        The returned dict the following keys:

          - ``rtot``: Total compound return
          - ``ravg``: Average return for the entire period (timeframe specific)
          - ``rnorm``: Annualized/Normalized return
          - ``rnorm100``: Annualized/Normalized return expressed in 100%

    '''
    # 参数
    params = (
        ('tann', None),
        ('fund', None),
    )
    # 计算年化的时候的天数等
    _TANN = {
        bt.TimeFrame.Days: 252.0,
        bt.TimeFrame.Weeks: 52.0,
        bt.TimeFrame.Months: 12.0,
        bt.TimeFrame.Years: 1.0,
    }
    # 开始
    def start(self):
        super(Returns, self).start()
        # 如果fund是None的话，_fundmode是broker的fundmode，否则就等于fund
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # 如果fundmode是False的话，获取value,如果不是False的话，获取fundvalue
        if not self._fundmode:
            self._value_start = self.strategy.broker.getvalue()
        else:
            self._value_start = self.strategy.broker.fundvalue
        # 统计subperiod
        self._tcount = 0

    # 停止的时候
    def stop(self):
        super(Returns, self).stop()
        # 如果fundmode是False的话，获取value,如果不是False的话，获取fundvalue
        if not self._fundmode:
            self._value_end = self.strategy.broker.getvalue()
        else:
            self._value_end = self.strategy.broker.fundvalue

        # Compound return
        # rtot计算的是总的对数收益率
        try:
            nlrtot = self._value_end / self._value_start
        except ZeroDivisionError:
            rtot = float('-inf')
        else:
            if nlrtot < 0.0:
                rtot = float('-inf')
            else:
                rtot = math.log(nlrtot)

        self.rets['rtot'] = rtot

        # Average return
        # 计算的是平均的收益率,先计算的对数收益率，然后计算的平均的对数收益率
        self.rets['ravg'] = ravg = rtot / self._tcount

        # Annualized normalized return
        # 计算的是年化的收益率
        tann = self.p.tann or self._TANN.get(self.timeframe, None)
        if tann is None:
            tann = self._TANN.get(self.data._timeframe, 1.0)  # assign default

        if ravg > float('-inf'):
            self.rets['rnorm'] = rnorm = math.expm1(ravg * tann)
        else:
            self.rets['rnorm'] = rnorm = ravg
        # 百分比形式的年化收益率
        self.rets['rnorm100'] = rnorm * 100.0  # human readable %

    def _on_dt_over(self):
        self._tcount += 1  # count the subperiod
