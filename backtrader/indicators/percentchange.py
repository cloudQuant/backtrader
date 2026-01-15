#!/usr/bin/env python
"""Percent Change Indicator Module - Percentage change calculation.

This module provides the Percent Change indicator for measuring the
percentage change in price over a given period.

Classes:
    PercentChange: Percentage change indicator (alias: PctChange).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.PctChange, period=30)
"""
from . import Indicator

__all__ = ["PercentChange", "PctChange"]


class PercentChange(Indicator):
    """
    Measures the percentage change of the current value with respect to that
    of period bars ago
    """

    alias = ("PctChange",)
    lines = ("pctchange",)

    # Fancy plotting name
    plotlines = dict(pctchange=dict(_name="%change"))

    # update value to the standard for Moving Averages
    params = (("period", 30),)

    def __init__(self):
        """Initialize the Percent Change indicator.

        Sets minimum period to period + 1 for comparison calculation.
        """
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Calculate percent change for the current bar.

        Formula: pctchange = (current_value / value_period_ago) - 1.0
        Returns 0.0 if the previous value is 0 to avoid division by zero.
        """
        prev_val = self.data[-self.p.period]
        if prev_val != 0:
            self.lines.pctchange[0] = self.data[0] / prev_val - 1.0
        else:
            self.lines.pctchange[0] = 0.0

    def once(self, start, end):
        """Calculate percent change in runonce mode.

        Computes percentage change for each bar relative to the value
        'period' bars ago.
        """
        darray = self.data.array
        larray = self.lines.pctchange.array
        period = self.p.period

        while len(larray) < end:
            larray.append(0.0)

        for i in range(period, min(end, len(darray))):
            prev_val = darray[i - period]
            if prev_val != 0:
                larray[i] = darray[i] / prev_val - 1.0
            else:
                larray[i] = 0.0


PctChange = PercentChange
