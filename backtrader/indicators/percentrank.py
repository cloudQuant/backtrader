#!/usr/bin/env python
"""Percent Rank Indicator Module - Percentile ranking.

This module provides the Percent Rank indicator for calculating
the percentile rank of current values within a period.

Classes:
    PercentRank: Percent rank indicator (alias: PctRank).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.PctRank, period=50)
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
