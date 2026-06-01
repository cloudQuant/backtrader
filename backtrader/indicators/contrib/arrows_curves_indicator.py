#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ArrowsCurvesIndicator",
]


class ArrowsCurvesIndicator(Indicator):
    """Custom Arrows and Curves technical indicator.

    Calculates channel boundaries (smax, smin, smax2, smin2) based on highest high and lowest low windows
    and returns trade entry signals (buy, sell, buy_stop, sell_stop).
    """

    lines = ("sell", "buy", "sell_stop", "buy_stop", "smax", "smin", "smax2", "smin2")
    params = (
        ("ssp", 20),
        ("channel", 0),
        ("ch_stop", 30),
        ("relay", 10),
    )

    def __init__(self):
        """Initializes trends, state flags, and sets indicator minimum period requirement."""
        self.addminperiod(self.p.ssp + self.p.relay + 2)
        self._uptrend = False
        self._old = False
        self._uptrend2 = False
        self._old2 = False

    def next(self):
        """Calculates channel lines and signals for each bar.

        Generates buy/sell and buy_stop/sell_stop triggers based on price crossovers
        and trend state switches.
        """
        if len(self.data) <= self.p.ssp + self.p.relay:
            for line in self.lines:
                line[0] = 0.0
            return

        high_window = [
            float(self.data.high[-shift])
            for shift in range(self.p.relay, self.p.relay + self.p.ssp)
        ]
        low_window = [
            float(self.data.low[-shift]) for shift in range(self.p.relay, self.p.relay + self.p.ssp)
        ]
        close0 = float(self.data.close[0])
        high_val = max(high_window)
        low_val = min(low_window)
        smax = high_val - (low_val - high_val) * self.p.channel / 100.0
        smin = low_val + (high_val - low_val) * self.p.channel / 100.0
        smax2 = high_val - (high_val - low_val) * (self.p.channel + self.p.ch_stop) / 100.0
        smin2 = low_val + (high_val - low_val) * (self.p.channel + self.p.ch_stop) / 100.0

        sell_signal = 0.0
        buy_signal = 0.0
        sell_stop = 0.0
        buy_stop = 0.0

        uptrend = self._uptrend
        uptrend2 = self._uptrend2
        old = self._old
        old2 = self._old2

        if close0 < smin and close0 < smax and uptrend2 is True:
            uptrend = False
        if close0 > smax and close0 > smin and uptrend2 is False:
            uptrend = True
        if (close0 > smax2 or close0 > smin2) and uptrend is False:
            uptrend2 = False
        if (close0 < smin2 or close0 < smax2) and uptrend is True:
            uptrend2 = True

        if close0 < smin and close0 < smax and uptrend2 is False:
            sell_signal = low_val
            uptrend2 = True
        if close0 > smax and close0 > smin and uptrend2 is True:
            buy_signal = high_val
            uptrend2 = False

        if uptrend != old and uptrend is False:
            sell_signal = low_val
        if uptrend != old and uptrend is True:
            buy_signal = high_val

        if uptrend2 != old2 and uptrend2 is True:
            buy_stop = smax2
        if uptrend2 != old2 and uptrend2 is False:
            sell_stop = smin2

        self.lines.sell[0] = sell_signal
        self.lines.buy[0] = buy_signal
        self.lines.sell_stop[0] = sell_stop
        self.lines.buy_stop[0] = buy_stop
        self.lines.smax[0] = smax
        self.lines.smin[0] = smin
        self.lines.smax2[0] = smax2
        self.lines.smin2[0] = smin2

        self._old = uptrend
        self._old2 = uptrend2
        self._uptrend = uptrend
        self._uptrend2 = uptrend2
