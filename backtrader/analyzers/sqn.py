#!/usr/bin/env python
"""SQN Analyzer Module - System Quality Number calculation.

This module provides the SQN (System Quality Number) analyzer, defined
by Van K. Tharp to categorize trading systems.

Classes:
    SQN: Analyzer that calculates System Quality Number.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.sqn.get_analysis())
"""

import math

from ..analyzer import Analyzer
from ..mathsupport import average, standarddev
from ..utils import AutoOrderedDict

__all__ = ["SQN"]

_PNL_EPSILON = 1e-10


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
        """Initialize the analyzer at the start of the backtest.

        Initializes lists to store trade P&L values for SQN calculation.
        """
        super().start()
        self.pnl = list()
        self.count = 0

    # Trade notification, if trade is closed, add profit/loss
    def notify_trade(self, trade):
        """Collect P&L from closed trades.

        Args:
            trade: The trade object that was closed.
        """
        if trade.status == trade.Closed:
            self.pnl.append(trade.pnlcomm)
            self.count += 1

    # Stop, calculate SQN indicator, if trade count > 0, SQN equals average trade profit * sqrt(trade count) / standard deviation of trade profit
    def stop(self):
        """Calculate the System Quality Number when backtest ends.

        SQN = sqrt(N) * average(P&L) / std(P&L)

        The result is stored in self.rets.sqn along with the number of
        trades in self.rets.trades.
        """
        if self.count > 1:
            try:
                pnl_values = [0.0 if abs(value) <= _PNL_EPSILON else value for value in self.pnl]
                pnl_av = average(pnl_values)
                pnl_stddev = standarddev(pnl_values)
            except (TypeError, ValueError, ZeroDivisionError):
                sqn = None
            else:
                if not math.isfinite(pnl_av) or not math.isfinite(pnl_stddev):
                    sqn = None
                elif pnl_stddev == 0.0:
                    sqn = None
                else:
                    sqn = math.sqrt(len(self.pnl)) * pnl_av / pnl_stddev
                    if not math.isfinite(sqn):
                        sqn = None
        else:
            sqn = 0
        # Set SQN value and trades value
        self.rets.sqn = sqn
        self.rets.trades = self.count
