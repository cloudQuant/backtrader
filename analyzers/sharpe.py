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

from backtrader.utils.py3 import itervalues

from backtrader import Analyzer, TimeFrame
from backtrader.mathsupport import average, standarddev
from backtrader.analyzers import TimeReturn, AnnualReturn


class SharpeRatio(Analyzer):
  # 相对来说，backtrader计算夏普率的方式其实蛮复杂的，考虑了很多的参数
    '''This analyzer calculates the SharpeRatio of a strategy using a risk free
    asset which is simply an interest rate

    See also:

      - https://en.wikipedia.org/wiki/Sharpe_ratio

    Params:

      - ``timeframe``: (default: ``TimeFrame.Years``)  # 交易周期

      - ``compression`` (default: ``1``)               # 具体的交易周期

        Only used for sub-day timeframes to for example work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

      - ``riskfreerate`` (default: 0.01 -> 1%)  # 计算夏普率使用的无风险收益率

        Expressed in annual terms (see ``convertrate`` below)

      - ``convertrate`` (default: ``True``)     # 是否把无风险收益率从年转化成月、周、日，不支持转化成日内

        Convert the ``riskfreerate`` from annual to monthly, weekly or daily
        rate. Sub-day conversions are not supported

      - ``factor`` (default: ``None``)          # factor如果没有指定，将会按照指定的日期去转化，1年等于12个月等于52周等于252个交易日

        If ``None``, the conversion factor for the riskfree rate from *annual*
        to the chosen timeframe will be chosen from a predefined table

          Days: 252, Weeks: 52, Months: 12, Years: 1

        Else the specified value will be used

      - ``annualize`` (default: ``False``)      # 如果参数设置成True的话，将会转化成年化的收益率

        If ``convertrate`` is ``True``, the *SharpeRatio* will be delivered in
        the ``timeframe`` of choice.

        In most occasions the SharpeRatio is delivered in annualized form.
        Convert the ``riskfreerate`` from annual to monthly, weekly or daily
        rate. Sub-day conversions are not supported

      - ``stddev_sample`` (default: ``False``)  # 计算标准差的时候是否减去1

        If this is set to ``True`` the *standard deviation* will be calculated
        decreasing the denominator in the mean by ``1``. This is used when
        calculating the *standard deviation* if it's considered that not all
        samples are used for the calculation. This is known as the *Bessels'
        correction*

      - ``daysfactor`` (default: ``None``)   # 旧的代码遗留

        Old naming for ``factor``. If set to anything else than ``None`` and
        the ``timeframe`` is ``TimeFrame.Days`` it will be assumed this is old
        code and the value will be used

      - ``legacyannual`` (default: ``False``) # 仅仅作用于年，使用年化收益率的分析器

        Use the ``AnnualReturn`` return analyzer, which as the name implies
        only works on years

      - ``fund`` (default: ``None``)   # 是净资产模式还是fund模式，默认情况下，将会自己判断

        If ``None`` the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - get_analysis

        Returns a dictionary with key "sharperatio" holding the ratio

    '''
    # 默认的参数
    params = (
        ('timeframe', TimeFrame.Years),
        ('compression', 1),
        ('riskfreerate', 0.01),
        ('factor', None),
        ('convertrate', True),
        ('annualize', False),
        ('stddev_sample', False),

        # old behavior
        ('daysfactor', None),
        ('legacyannual', False),
        ('fund', None),
    )
    # 默认的日期转化
    RATEFACTORS = {
        TimeFrame.Days: 252,
        TimeFrame.Weeks: 52,
        TimeFrame.Months: 12,
        TimeFrame.Years: 1,
    }

    def __init__(self):
        # 如果按照年的话，获取年化收益率，否则就获取每日的收益率
        if self.p.legacyannual:
            self.anret = AnnualReturn()
        else:
            self.timereturn = TimeReturn(
                timeframe=self.p.timeframe,
                compression=self.p.compression,
                fund=self.p.fund)

    def stop(self):
        super(SharpeRatio, self).stop()
        # 以年为单位计算收益率和夏普率
        if self.p.legacyannual:
            rate = self.p.riskfreerate
            retavg = average([r - rate for r in self.anret.rets])
            retdev = standarddev(self.anret.rets)
            self.ratio = retavg / retdev
        # 如果不是以年为单位计算收益率和夏普率
        else:
            # Get the returns from the subanalyzer
            # 获取每日的收益率
            returns = list(itervalues(self.timereturn.get_analysis()))
            # 无风险收益率
            rate = self.p.riskfreerate  #
            # 日期先默认为None
            factor = None

            # Hack to identify old code
            # 获取具体的factor日期，如果是日周期并且daysfactor不是None的话，另factor = daysfactor
            if self.p.timeframe == TimeFrame.Days and \
               self.p.daysfactor is not None:

                factor = self.p.daysfactor
            # 否则，如果factor这个参数不是None的话，就等于factor这个参数的值，否则根据交易周期从定义的factors里面找
            # 默认情况下，factor应该是252
            else:
                if self.p.factor is not None:
                    factor = self.p.factor  # user specified factor
                elif self.p.timeframe in self.RATEFACTORS:
                    # Get the conversion factor from the default table
                    factor = self.RATEFACTORS[self.p.timeframe]
            # 如果factor不是None的话，默认情况需要把年化无风险收益率转化转化成日的无风险收益率，如果以日作为周期的话
            if factor is not None:
                # A factor was found

                if self.p.convertrate:
                    # Standard: downgrade annual returns to timeframe factor
                    rate = pow(1.0 + rate, 1.0 / factor) - 1.0
                else:
                    # Else upgrade returns to yearly returns
                    returns = [pow(1.0 + x, factor) - 1.0 for x in returns]
            # 多少个交易日
            lrets = len(returns) - self.p.stddev_sample
            # Check if the ratio can be calculated
            if lrets:
                # Get the excess returns - arithmetic mean - original sharpe
                # 计算得到每日的超额收益率
                ret_free = [r - rate for r in returns]
                # 计算得到每日的超额收益率的平均值
                ret_free_avg = average(ret_free)
                # 计算得到每日超额收益率的波动率
                retdev = standarddev(ret_free, avgx=ret_free_avg,bessel=self.p.stddev_sample)
                # ret_avg = average(returns)
                # retdev = standarddev(returns, avgx=ret_avg,bessel=self.p.stddev_sample)

                try:
                    # 计算得到夏普率
                    ratio = ret_free_avg / retdev
                    # 如果factor不是None,并且把年无风险收益率转化成日了，并且需要计算年化的夏普率
                    if factor is not None and \
                       self.p.convertrate and self.p.annualize:
                        # 把夏普率从日转化成年
                        ratio = math.sqrt(factor) * ratio
                except (ValueError, TypeError, ZeroDivisionError):
                    ratio = None
            else:
                # no returns or stddev_sample was active and 1 return
                ratio = None

            self.ratio = ratio
        # 保存夏普率
        self.rets['sharperatio'] = self.ratio


class SharpeRatio_A(SharpeRatio):
    '''Extension of the SharpeRatio which returns the Sharpe Ratio directly in
    annualized form

    The following param has been changed from ``SharpeRatio``

      - ``annualize`` (default: ``True``)

    '''
    # 计算年化的夏普率
    params = (
        ('annualize', True),
    )
