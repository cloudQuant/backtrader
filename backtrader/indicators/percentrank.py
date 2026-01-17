#!/usr/bin/env python
"""Percent Rank Indicator Module - Percentile ranking.

This module provides the Percent Rank indicator for calculating
the percentile rank of current values within a period.

Classes:
    PercentRank: Percent rank indicator (alias: PctRank).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            # Calculate 50-period percent rank
            self.pctrank = bt.indicators.PctRank(self.data.close, period=50)

        def next(self):
            # Buy when price is in top 20% (percent rank > 0.8)
            if self.pctrank[0] > 0.8:
                self.buy()
            # Sell when price is in bottom 20% (percent rank < 0.2)
            elif self.pctrank[0] < 0.2:
                self.sell()
"""
from math import fsum

from . import BaseApplyN

__all__ = ["PercentRank", "PctRank"]


class PercentRank(BaseApplyN):
    """
    Measures the percent rank of the current value with respect to that of
    period bars ago
    """

    alias = ("PctRank",)
    lines = ("pctrank",)
    params = (
        ("period", 50),
        ("func", lambda d: fsum(x < d[-1] for x in d) / len(d)),
    )


PctRank = PercentRank
