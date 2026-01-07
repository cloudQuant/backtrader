#!/usr/bin/env python
"""PSAR Indicator Module - Parabolic SAR.

This module provides the Parabolic SAR (Stop and Reverse) indicator
developed by J. Welles Wilder, Jr. for trend following and reversal signals.

Classes:
    ParabolicSAR: Parabolic SAR indicator (alias: PSAR).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.PSAR)
"""
from . import PeriodN

__all__ = ["ParabolicSAR", "PSAR"]


class _SarStatus:
    sar = None
    tr = None
    af = 0.0
    ep = 0.0

    def __str__(self):
        txt = []
        txt.append(f"sar: {self.sar}")
        txt.append(f"tr: {self.tr}")
        txt.append(f"af: {self.af}")
        txt.append(f"ep: {self.ep}")
        return "\n".join(txt)


class ParabolicSAR(PeriodN):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the RSI

    SAR stands for *Stop and Reverse*, and the indicator was meant as a signal
    for entry (and reverse)

    How to select the first signal is left unspecified in the book and the
    increase/decrease of bars

    See:
      - https://en.wikipedia.org/wiki/Parabolic_SAR
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:parabolic_sar
    """

    alias = ("PSAR",)
    lines = ("psar",)
    params = (
        ("period", 2),  # when to start showing values
        ("af", 0.02),
        ("afmax", 0.20),
    )

    plotinfo = dict(subplot=False)
    plotlines = dict(
        psar=dict(marker=".", markersize=4.0, color="black", fillstyle="full", ls=""),
    )

    def prenext(self):
        """Handle calculations before minimum period is reached.

        Initializes status tracking and calculates initial PSAR values.
        """
        if len(self) == 1:
            self._status = []  # empty status
            return  # not enough data to do anything

        elif len(self) == 2:
            self.nextstart()  # kickstart calculation
        else:
            self.next()  # regular calc

        self.lines.psar[0] = float("NaN")  # no return yet still prenext

    def nextstart(self):
        """Initialize PSAR calculation on first valid bar.

        Determines initial trend direction and sets up status tracking.
        """
        if self._status:  # some states have been calculated
            self.next()  # delegate
            return

        # Prepare a status holding array, for current and previous lengths
        self._status = [_SarStatus(), _SarStatus()]

        # Start by looking if price has gone up/down (close) in the 2nd day to
        # get an *entry* signal and configure the values as they would have
        # been in the previous trend, including a sar value which is
        # immediately invalidated in next, which reverses and sets the trend to
        # the actual up/down value calculated with the close
        # Put the 4 status variables in a Status holder
        plenidx = (len(self) - 1) % 2  # previous length index (0 or 1)
        status = self._status[plenidx]

        # Calculate the status for previous length
        status.sar = (self.data.high[0] + self.data.low[0]) / 2.0

        status.af = self.p.af
        if self.data.close[0] >= self.data.close[-1]:  # uptrend
            status.tr = not True  # uptrend when reversed
            status.ep = self.data.low[-1]  # ep from prev trend
        else:
            status.tr = not False  # downtrend when reversed
            status.ep = self.data.high[-1]  # ep from prev trend

        # With the fake prev trend in place and a sar which will be invalidated
        # go to next to get the calculation done
        self.next()

    def next(self):
        """Calculate PSAR for the current bar.

        Updates the stop-and-reverse point based on trend direction,
        extreme price, and acceleration factor.
        """


PSAR = ParabolicSAR
