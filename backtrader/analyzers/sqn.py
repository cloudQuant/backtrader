#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import math
from backtrader import Analyzer
from backtrader.mathsupport import average, standarddev
from backtrader.utils import AutoOrderedDict


# 获取SQN指标
class SQN(Analyzer):
    """SQN or SystemQualityNumber. Defined by Van K. Tharp to categorize trading
    systems.

      - 1.6 - 1.9 Below average
      - 2.0 - 2.4 Average
      - 2.5 - 2.9 Good
      - 3.0 - 5.0 Excellent
      - 5.1 - 6.9 Superb
      - 7.0 - Holy Grail?

    The formula:

      - SquareRoot(NumberTrades) * Average(TradesProfit) / StdDev(TradesProfit)

    The sqn value should be deemed reliable when the number of trades >= 30

    Methods:

      - Get_analysis

        Returns a dictionary with keys "sqn" and "trades" (number of
        considered trades)

    """

    # 系统质量数
    alias = ("SystemQualityNumber",)

    # 创建分析
    def create_analysis(self):
        """Replace default implementation to instantiate an AutoOrderedDict
        rather than an OrderedDict"""
        self.rets = AutoOrderedDict()
        self.rets.sqn = 0.0
        self.rets.trades = 0

    # 开始，初始化pnl和count
    def start(self):
        super(SQN, self).start()
        self._trades = []

    # 交易通知，如果trade是关闭的，添加盈亏
    def notify_trade(self, trade):
        if trade.isclosed:
            # Get profit/loss for this trade
            pnl = trade.pnl
            
            # Create trades list if not exists
            if not hasattr(self, '_trades'):
                self._trades = []
            
            # Add trade pnl to list
            self._trades.append(pnl)
            
            # Update trade count
            self.rets.trades = len(self._trades)
            
            # Calculate SQN if we have enough trades
            if len(self._trades) > 1:
                avg_pnl = average(self._trades)
                std_pnl = standarddev(self._trades)
                
                if std_pnl > 0.0:
                    sqn = math.sqrt(len(self._trades)) * avg_pnl / std_pnl
                    self.rets.sqn = sqn
                else:
                    self.rets.sqn = 0.0
            else:
                self.rets.sqn = 0.0

    # 停止，计算sqn指标，如果交易次数大于0，sqn等于交易盈利的平均值*交易次数的平方根/交易盈利的标准差
    def stop(self):
        # Final calculation in case needed
        if hasattr(self, '_trades') and len(self._trades) > 1:
            avg_pnl = average(self._trades)
            std_pnl = standarddev(self._trades)
            
            if std_pnl > 0.0:
                sqn = math.sqrt(len(self._trades)) * avg_pnl / std_pnl
                self.rets.sqn = sqn
            else:
                self.rets.sqn = 0.0
