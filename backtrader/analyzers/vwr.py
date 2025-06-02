#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import math
import backtrader as bt
from backtrader import TimeFrameAnalyzerBase
from . import Returns
from ..mathsupport import standarddev


# 获取VMR指标
class VWR(TimeFrameAnalyzerBase):
    """Variability-Weighted Return: Better SharpeRatio with Log Returns

    Alias:

      - VariabilityWeightedReturn

    See:

      - https://www.crystalbull.com/sharpe-ratio-better-with-log-returns/

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` then the complete return over the entire backtested period
        will be reported

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - ``tann`` (default: ``None``)

        Number of periods to use for the annualization (normalization) of the
        average returns. If ``None``, then standard ``t`` values will be used,
        namely:

          - ``days: 252``
          - ``weeks: 52``
          - ``months: 12``
          - ``years: 1``

      - ``tau`` (default: ``2.0``)

        Factor for the calculation (see the literature)

      - ``sdev_max`` (default: ``0.20``)

        Max standard deviation (see the literature)

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - Get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys

        The returned dict contains the following keys:

          - ``vwr``: Variability-Weighted Return
    """

    # 参数
    params = (
        ("tann", None),
        ("tau", 0.20),
        ("sdev_max", 2.0),
        ("fund", None),
    )

    # 一年对应的交易周期
    _TANN = {
        bt.TimeFrame.Days: 252.0,
        bt.TimeFrame.Weeks: 52.0,
        bt.TimeFrame.Months: 12.0,
        bt.TimeFrame.Years: 1.0,
    }

    # 初始化，获取收益率
    def __init__(self, *args, **kwargs):
        # 调用父类的__init__方法以支持timeframe和compression参数
        super(VWR, self).__init__(*args, **kwargs)
        
        # Children log return analyzer
        self._pns = None
        self._pis = None
        self._fundmode = None
        self._returns = Returns(
            timeframe=self.p.timeframe, compression=self.p.compression, tann=self.p.tann
        )

    # 开始
    def start(self):
        super(VWR, self).start()
        # Add an initial placeholder for [-1] operation
        # 获取fundmode
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # 根据fundmode的值获取初始的值
        if not self._fundmode:
            self._pis = [self.strategy.broker.getvalue()]  # keep initial value
        else:
            self._pis = [self.strategy.broker.fundvalue]  # keep initial value
        # 初始化最终的值为None
        self._pns = [None]  # keep final prices (value)

    # 停止
    def stop(self):
        super(VWR, self).stop()
        # Check if no value has been seen after the last 'dt_over'
        # If so, there is one 'pi' out of place and a None 'pn'. Purge
        # 如果最后一个值是None, 删除最后一个元素
        if self._pns[-1] is None:
            self._pis.pop()
            self._pns.pop()

        # Get results from children
        # 获取收益率
        rs = self._returns.get_analysis()
        ravg = rs["ravg"]
        rnorm100 = rs["rnorm100"]

        # make n 1 based in enumerate (number of periods and not index)
        # skip initial placeholders for synchronization
        # 计算每个period的收益率(通常是每年的, 然后保存到dts中)
        dts = []
        for n, pipn in enumerate(zip(self._pis, self._pns), 1):
            pi, pn = pipn
            # print(n,pi,pn,pipn,ravg,rs)
            dt = pn / (pi * math.exp(ravg * n)) - 1.0
            dts.append(dt)
        # 计算年收益率的标准差
        sdev_p = standarddev(dts, bessel=True)
        # 计算vmr的值
        vwr = rnorm100 * (1.0 - pow(sdev_p / self.p.sdev_max, self.p.tau))
        self.rets["vwr"] = vwr

    # fund通知
    def notify_fund(self, cash, value, fundvalue, shares):
        if not self._fundmode:
            self._pns[-1] = value  # annotate last seen pn for the current period
        else:
            self._pns[-1] = fundvalue  # annotate last pn for current period

    def _on_dt_over(self):
        self._pis.append(self._pns[-1])  # the last pn is pi in the next period
        self._pns.append(None)  # placeholder for [-1] operation


VariabilityWeightedReturn = VWR
