#!/usr/bin/env python

import math

from ..analyzer import Analyzer
from ..mathsupport import average, standarddev
from ..utils import AutoOrderedDict

__all__ = ["SQN"]


# Get SQN indicator
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

    # System quality number
    alias = ("SystemQualityNumber",)

    # Create analysis
    def create_analysis(self):
        """Replace default implementation to instantiate an AutoOrderedDict
        rather than an OrderedDict"""
        self.rets = AutoOrderedDict()

    # Start, initialize pnl and count
    def start(self):
        super().start()
        self.pnl = list()
        self.count = 0

    # Trade notification, if trade is closed, add profit/loss
    def notify_trade(self, trade):
        if trade.status == trade.Closed:
            self.pnl.append(trade.pnlcomm)
            self.count += 1

    # Stop, calculate SQN indicator, if trade count > 0, SQN equals average trade profit * sqrt(trade count) / standard deviation of trade profit
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
        # Set SQN value and trades value
        self.rets.sqn = sqn
        self.rets.trades = self.count
