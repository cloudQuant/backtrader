#!/usr/bin/env python
"""On-Balance Volume indicator.

This module provides the On-Balance Volume (OBV) cumulative volume indicator.
OBV adds the current volume when the closing price rises, subtracts it when
it falls, and leaves the cumulative value unchanged when the closing price is
unchanged.

Classes:
    OnBalanceVolume: On-Balance Volume indicator (alias: OBV).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.obv = bt.indicators.OBV(self.data)
"""

from . import Indicator


class OnBalanceVolume(Indicator):
    """Cumulative On-Balance Volume indicator.

    Formula:
      - first value = volume
      - close > previous close: obv = previous obv + volume
      - close < previous close: obv = previous obv - volume
      - close == previous close: obv = previous obv
    """

    alias = ("OBV",)
    lines = ("obv",)

    def __init__(self):
        """Initialize the indicator."""
        super().__init__()

    def nextstart(self):
        """Seed OBV with the first available volume value."""
        self.lines.obv[0] = self.data.volume[0]

    def next(self):
        """Update OBV for the current bar in event-driven mode."""
        previous = self.lines.obv[-1]
        close = self.data.close[0]
        previous_close = self.data.close[-1]
        volume = self.data.volume[0]

        if close > previous_close:
            self.lines.obv[0] = previous + volume
        elif close < previous_close:
            self.lines.obv[0] = previous - volume
        else:
            self.lines.obv[0] = previous

    def oncestart(self, start, end):
        """Seed OBV in batch-processing mode."""
        dst = self.lines.obv.array
        volume = self.data.volume.array

        while len(dst) < end:
            dst.append(float("nan"))

        for i in range(start, min(end, len(volume))):
            dst[i] = volume[i]

    def once(self, start, end):
        """Calculate OBV values in batch-processing mode."""
        dst = self.lines.obv.array
        close = self.data.close.array
        volume = self.data.volume.array
        actual_end = min(end, len(close), len(volume))

        while len(dst) < end:
            dst.append(float("nan"))

        if start >= actual_end:
            return

        if start == 0:
            dst[0] = volume[0]
            start = 1

        previous = dst[start - 1]
        for i in range(start, actual_end):
            if close[i] > close[i - 1]:
                previous += volume[i]
            elif close[i] < close[i - 1]:
                previous -= volume[i]

            dst[i] = previous


OBV = OnBalanceVolume
