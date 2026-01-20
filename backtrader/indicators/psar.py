#!/usr/bin/env python
"""PSAR Indicator Module - Parabolic SAR.

This module provides the Parabolic SAR (Stop and Reverse) indicator
developed by J. Welles Wilder, Jr. for trend following and reversal signals.

Classes:
    ParabolicSAR: Parabolic SAR indicator (alias: PSAR).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.psar = bt.indicators.PSAR(self.data)

        def next(self):
            # PSAR dots below price indicate uptrend
            if self.psar.psar[0] < self.data.low[0]:
                self.buy()
            # PSAR dots above price indicate downtrend
            elif self.psar.psar[0] > self.data.high[0]:
                self.sell()
"""

from . import PeriodN

__all__ = ["ParabolicSAR", "PSAR"]


class _SarStatus:
    """Internal status holder for Parabolic SAR calculations.

    Attributes:
        sar: Stop and Reverse value for the current period.
        tr: Trend direction (True for long/up, False for short/down).
        af: Acceleration factor, controlling how quickly SAR responds.
        ep: Extreme point - highest high in uptrend or lowest low in downtrend.
    """

    sar = None
    tr = None
    af = 0.0
    ep = 0.0

    def __str__(self):
        """Return a string representation of the SAR status.

        Returns:
            str: Multi-line string containing sar, tr, af, and ep values.
        """
        txt = []
        txt.append(f"sar: {self.sar}")
        txt.append(f"tr: {self.tr}")
        txt.append(f"af: {self.af}")
        txt.append(f"ep: {self.ep}")
        return "\n".join(txt)


class ParabolicSAR(PeriodN):
    """Parabolic SAR (Stop and Reverse) indicator.

    Defined by J. Welles Wilder, Jr. in 1978 in his book *New Concepts in
    Technical Trading Systems*. SAR stands for Stop and Reverse, and the
    indicator is meant as a signal for entry (and reverse).

    The indicator places dots above or below price bars to indicate the
    current trend direction. When the dots flip from above to below (or
    vice versa), it signals a potential trend reversal.

    The initial trend direction is determined by comparing the close price
    of the second bar to the first bar. The SAR value accelerates toward
    the price as the trend extends, using the acceleration factor.

    See:
        https://en.wikipedia.org/wiki/Parabolic_SAR
        http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:parabolic_sar

    Attributes:
        psar: Line containing the calculated Parabolic SAR values.

    Args:
        period: Bar number from which to start showing values (default: 2).
        af: Acceleration factor (default: 0.02).
        afmax: Maximum acceleration factor (default: 0.20).
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
        hi = self.data.high[0]
        lo = self.data.low[0]

        plenidx = (len(self) - 1) % 2  # previous length index (0 or 1)
        status = self._status[plenidx]  # use prev status for calculations

        tr = status.tr
        sar = status.sar

        # Check if the sar penetrated the price to switch the trend
        if (tr and sar >= lo) or (not tr and sar <= hi):
            tr = not tr  # reverse the trend
            sar = status.ep  # new sar is prev SIP (Significant price)
            ep = hi if tr else lo  # select new SIP / Extreme Price
            af = self.p.af  # reset acceleration factor

        else:  # use the precalculated values
            ep = status.ep
            af = status.af

        # Update sar value for today
        self.lines.psar[0] = sar

        # Update ep and af if needed
        if tr:  # long trade
            if hi > ep:
                ep = hi
                af = min(af + self.p.af, self.p.afmax)

        else:  # downtrend
            if lo < ep:
                ep = lo
                af = min(af + self.p.af, self.p.afmax)

        sar = sar + af * (ep - sar)  # calculate the sar for tomorrow

        # make sure sar doesn't go into hi/lows
        if tr:  # long trade
            lo1 = self.data.low[-1]
            if sar > lo or sar > lo1:
                sar = min(lo, lo1)  # sar not above last 2 lows -> lower
        else:
            hi1 = self.data.high[-1]
            if sar < hi or sar < hi1:
                sar = max(hi, hi1)  # sar not below last 2 highs -> highest

        # new status has been calculated, keep it in current length
        # will be used when length moves forward
        newstatus = self._status[not plenidx]
        newstatus.tr = tr
        newstatus.sar = sar
        newstatus.ep = ep
        newstatus.af = af


PSAR = ParabolicSAR
