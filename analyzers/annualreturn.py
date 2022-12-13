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

from collections import OrderedDict

from backtrader.utils.py3 import range
from backtrader.utils.date import num2date
from backtrader import Analyzer


# 计算每年的收益率，感觉算法实现有些复杂，后面写了一个用pandas实现的版本MyAnnualReturn，逻辑上简单了很多
class AnnualReturn(Analyzer):
    """
    This analyzer calculates the AnnualReturns by looking at the beginning
    and end of the year

    Params:

      - (None)

    Member Attributes:

      - ``rets``: list of calculated annual returns

      - ``ret``: dictionary (key: year) of annual returns

    **get_analysis**:

      - Returns a dictionary of annual returns (key: year)
    """

    def stop(self):
        # Must have stats.broker
        # 当前年份
        cur_year = -1
        # 开始value
        value_start = 0.0
        # todo 这个值没有使用到，注释掉
        # value_cur = 0.0   # 当前value
        # 结束value
        value_end = 0.0
        # 保存收益率数据
        # todo 直接设置在pycharm中会警告，提示在__init__外面设置属性值, 使用hasattr和setattr设置具体的属性值
        # self.rets = list()  #
        # self.ret = OrderedDict()
        if not hasattr(self, 'rets'):
            setattr(self, "rets", list())
        if not hasattr(self, 'ret'):
            setattr(self, "ret", OrderedDict())
        # 从开始到现在，循环数据
        for i in range(len(self.data) - 1, -1, -1):
            # 获取i的时候的时间和当前价值
            dt = self.data.datetime.date(-i)
            value_cur = self.strategy.stats.broker.value[-i]
            # if i == 0:
            #   print(dt)
            #   print(value_cur)
            # 如果i的时候的年份大于当前年份，如果当前年份大于0，计算收益率，并保存到self.ret中，并且开始价值等于结束价值
            # 当年份不等的时候，表明当前i是新的一年
            if dt.year > cur_year:
                if cur_year >= 0:
                    annualret = (value_end / value_start) - 1.0
                    self.rets.append(annualret)
                    self.ret[cur_year] = annualret

                    # changing between real years, use last value as new start
                    value_start = value_end
                else:
                    # No value set whatsoever, use the currently loaded value
                    value_start = value_cur

                cur_year = dt.year

            # No matter what, the last value is always the last loaded value
            value_end = value_cur
        # 如果当前年份还没有结束，收益率还没有计算，在最后即使不满足一年的条件下，也进行计算下
        if cur_year not in self.ret:
            # finish calculating pending data
            annualret = (value_end / value_start) - 1.0
            self.rets.append(annualret)
            self.ret[cur_year] = annualret

    def get_analysis(self):
        return self.ret


class MyAnnualReturn(Analyzer):
    """
    This analyzer calculates the AnnualReturns by looking at the beginning
    and end of the year

    Params:

      - (None)

    Member Attributes:

      - ``rets``: list of calculated annual returns

      - ``ret``: dictionary (key: year) of annual returns

    **get_analysis**:

      - Returns a dictionary of annual returns (key: year)
    """

    def stop(self):
        # 保存数据的容器---字典
        if not hasattr(self, 'ret'):
            setattr(self, "ret", OrderedDict())
        # 获取数据的时间，并转化为date
        dt_list = self.data.datetime.get(0, size=len(self.data))
        dt_list = [num2date(i) for i in dt_list]
        # 获取账户的资产
        value_list = self.strategy.stats.broker.value.get(0, size=len(self.data))
        # 转化为pandas格式
        import pandas as pd
        df = pd.DataFrame([dt_list, value_list]).T
        df.columns = ['datetime', 'value']
        df['pre_value'] = df['value'].shift(1)
        # 计算每年的持有获得的简单收益率
        df['year'] = [i.year for i in df['datetime']]
        for year, data in df.groupby("year"):
            begin_value = list(data['pre_value'])[0]
            end_value = list(data['value'])[-1]
            annual_return = (end_value / begin_value) - 1
            self.ret[year] = annual_return

    def get_analysis(self):
        return self.ret
