#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt
import math
import collections
from . import TimeDrawDown

__all__ = ["Calmar"]


# 计算calmar比例，总体上来看，这个calmar计算的并不算是太成功，或者说analyzer,observer等系列指标，使用效率并不是很高，
# 可以考虑做一个类似pyfolio的分析模块
class Calmar(bt.TimeFrameAnalyzerBase):
    """This analyzer calculates the CalmarRatio
    timeframe which can be different from the one used in the underlying data
    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` the ``timeframe`` of the first data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If compression is None, then the compression of the first data in the system will be
        used
      - *None*

      - ``fund`` (default: ``None``)

        If ``None``, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    See also:

      - https://en.wikipedia.org/wiki/Calmar_ratio

    Methods:
      - ``get_analysis``

        Returns a OrderedDict with a key for the time period and the
        corresponding rolling Calmar ratio

    Attributes:
      - ``calmar`` the latest calculated calmar ratio
    """

    # 使用到的模块
    packages = (
        "collections",
        "math",
    )
    # 参数
    params = (
        ("timeframe", bt.TimeFrame.Months),  # default in calmar
        ("period", 36),
        ("fund", None),
    )

    # 计算最大回撤
    def __init__(self):
        self.calmar = None
        self._fundmode = None
        self._values = None
        self._mdd = None
        self._maxdd = TimeDrawDown(timeframe=self.p.timeframe, compression=self.p.compression)

    # 开始
    def start(self):
        # 最大回撤率
        self._mdd = float("-inf")
        # 双向队列，保存period个值，默认是36个
        self._values = collections.deque([float("Nan")] * self.p.period, maxlen=self.p.period)
        # fundmode
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # 根据fundmode添加不同的值到self._values中
        if not self._fundmode:
            self._values.append(self.strategy.broker.getvalue())
        else:
            self._values.append(self.strategy.broker.fundvalue)

    def on_dt_over(self):
        # 最大回撤率
        self._mdd = max(self._mdd, self._maxdd.maxdd)
        # 添加值到self._values中
        if not self._fundmode:
            self._values.append(self.strategy.broker.getvalue())
        else:
            self._values.append(self.strategy.broker.fundvalue)
        # 默认情况下计算得到平均每个月的收益率
        rann = math.log(self._values[-1] / self._values[0]) / len(self._values)
        # 计算calmar指标
        self.calmar = calmar = rann / (self._mdd or float("Inf"))
        # 保存结果
        self.rets[self.dtkey] = calmar

    def stop(self):
        self.on_dt_over()  # update last values
