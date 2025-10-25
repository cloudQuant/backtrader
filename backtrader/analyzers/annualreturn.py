#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import datetime
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
    
    def __init__(self):
        super(AnnualReturn, self).__init__()
        # 缓存数据
        self._dt_cache = []
        self._value_cache = []
    
    def next(self):
        # 每次next被调用时，缓存当前的日期和账户价值
        dt_val = self.data.datetime[0]
        value_val = self.strategy.broker.getvalue()
        self._dt_cache.append(dt_val)
        self._value_cache.append(value_val)

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
        setattr(self, "rets", list())
        setattr(self, "ret", OrderedDict())
        
        # 使用缓存的数据进行计算
        for i in range(len(self._dt_cache)):
            dt_val = self._dt_cache[i]
            value_cur = self._value_cache[i]
            
            # 转换日期
            try:
                dt = num2date(dt_val)
            except:
                continue
            
            # 如果i的时候的年份大于当前年份，如果当前年份大于0，计算收益率，并保存到self.ret中，并且开始价值等于结束价值
            # 当年份不等的时候，表明当前i是新的一年
            if dt.year > cur_year:
                if cur_year >= 0:
                    if value_start != 0:
                        annual_ret = (value_end / value_start) - 1.0
                    else:
                        annual_ret = 0.0
                    self.rets.append(annual_ret)
                    self.ret[cur_year] = annual_ret

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
            if value_start != 0:
                annual_ret = (value_end / value_start) - 1.0
            else:
                annual_ret = 0.0
            self.rets.append(annual_ret)
            self.ret[cur_year] = annual_ret

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
        if not hasattr(self, "ret"):
            setattr(self, "ret", OrderedDict())
        # 获取数据的时间，并转化为date
        dt_list = self.data.datetime.get(0, size=len(self.data))
        dt_list = [num2date(i) for i in dt_list]
        # 获取账户的资产
        value_list = self.strategy.stats.broker.value.get(0, size=len(self.data))
        # 转化为pandas格式
        import pandas as pd

        df = pd.DataFrame([dt_list, value_list]).T
        df.columns = ["datetime", "value"]
        df["pre_value"] = df["value"].shift(1)
        # 计算每年的持有获得的简单收益率
        df["year"] = [i.year for i in df["datetime"]]
        for year, data in df.groupby("year"):
            begin_value = list(data["pre_value"])[0]
            end_value = list(data["value"])[-1]
            annual_return = (end_value / begin_value) - 1
            self.ret[year] = annual_return

    def get_analysis(self):
        return self.ret
