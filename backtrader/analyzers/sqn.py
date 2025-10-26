#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import math
from backtrader import Analyzer
from backtrader.mathsupport import average, standarddev
from backtrader.utils import AutoOrderedDict


__all__ = ['SQN']


# 获取SQN指标
class SQN(Analyzer):
    """SQN or SystemQualityNumber. Defined by Van K. Tharp to categorize trading
    systems.

      - 1.6 - 1.9 Below average
      - 2.0 - 2.4 Average
      - 2.5 - 2.9 Good
      - 3.0 - 5.0 Excellent
      - 5.1 - 6.9 Superb
      - 7.0 -     Holy Grail?

    The formula:

      - SquareRoot(NumberTrades) * Average(TradesProfit) / StdDev(TradesProfit)

    The sqn value should be deemed reliable when the number of trades >= 30

    Methods:

      - get_analysis

        Returns a dictionary with keys "sqn" and "trades" (number of
        considered trades)

    """
    # 系统质量数
    alias = ('SystemQualityNumber',)

    # 创建分析
    def create_analysis(self):
        """Replace default implementation to instantiate an AutoOrderedDict
        rather than an OrderedDict"""
        self.rets = AutoOrderedDict()

    # 开始，初始化pnl和count
    def start(self):
        super(SQN, self).start()
        self.pnl = list()
        self.count = 0

    # 交易通知，如果trade是关闭的，添加盈亏
    def notify_trade(self, trade):
        if trade.status == trade.Closed:
            self.pnl.append(trade.pnlcomm)
            self.count += 1

    # 停止，计算sqn指标，如果交易次数大于0，sqn等于交易盈利的平均值*交易次数的平方根/交易盈利的标准差
    def stop(self):
        if self.count > 1:
            pnl_av = average(self.pnl)
            pnl_stddev = standarddev(self.pnl)
            try:
                sqn = math.sqrt(len(self.pnl)) * pnl_av / pnl_stddev
            except ZeroDivisionError:
                sqn = None
        else:
            sqn = 0
        # 设置sqn的值和trades的值
        self.rets.sqn = sqn
        self.rets.trades = self.count
