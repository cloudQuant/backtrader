#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "PriceChannelStopIndicator",
]


class PriceChannelStopIndicator(Indicator):
    """Reconstructs PriceChannel_Stop from its MQ5 source.

    6 output buffers mapped to lines:
      0=DownTrendSignal, 1=DownTrendBuffer, 2=DownTrendLine
      3=UpTrendSignal,   4=UpTrendBuffer,   5=UpTrendLine
    """

    lines = ("down_signal", "down_buffer", "down_line", "up_signal", "up_buffer", "up_line")
    params = (
        ("channel_period", 5),
        ("risk", 0.1),
    )

    def __init__(self):
        """Initialize oscillator state and force initial warm-up period."""
        self._cp = int(self.p.channel_period)
        self._risk = float(self.p.risk)
        self._trend = 0
        self._prev_bsmax = 0.0
        self._prev_bsmin = 0.0
        self.addminperiod(self._cp + 2)

    def next(self):
        """Update indicator lines from current and rolling high/low windows."""
        cp = self._cp
        risk = self._risk

        # Highest high and lowest low over [bar, bar+ChannelPeriod)
        hi = max(float(self.data.high[-i]) for i in range(cp))
        lo = min(float(self.data.low[-i]) for i in range(cp))

        d_price = (hi - lo) * risk
        bsmax = hi - d_price
        bsmin = lo + d_price

        cur_close = float(self.data.close[0])

        if cur_close > self._prev_bsmax:
            self._trend = 1
        if cur_close < self._prev_bsmin:
            self._trend = -1

        # Ratchet
        if self._trend > 0 and bsmin < self._prev_bsmin:
            bsmin = self._prev_bsmin
        if self._trend < 0 and bsmax > self._prev_bsmax:
            bsmax = self._prev_bsmax

        # Reset all
        self.lines.down_signal[0] = 0.0
        self.lines.down_buffer[0] = 0.0
        self.lines.down_line[0] = 0.0
        self.lines.up_signal[0] = 0.0
        self.lines.up_buffer[0] = 0.0
        self.lines.up_line[0] = 0.0

        prev_down_buffer = (
            float(self.lines.down_buffer[-1])
            if len(self) > 1 and not math.isnan(float(self.lines.down_buffer[-1]))
            else 0.0
        )
        prev_up_buffer = (
            float(self.lines.up_buffer[-1])
            if len(self) > 1 and not math.isnan(float(self.lines.up_buffer[-1]))
            else 0.0
        )

        if self._trend > 0:
            price = bsmin
            if prev_down_buffer > 0:
                self.lines.up_signal[0] = price
                self.lines.up_line[0] = price
            else:
                self.lines.up_buffer[0] = price
                self.lines.up_line[0] = price

        if self._trend < 0:
            price = bsmax
            if prev_up_buffer > 0:
                self.lines.down_signal[0] = price
                self.lines.down_line[0] = price
            else:
                self.lines.down_buffer[0] = price
                self.lines.down_line[0] = price

        self._prev_bsmax = bsmax
        self._prev_bsmin = bsmin
