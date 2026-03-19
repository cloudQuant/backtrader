#!/usr/bin/env python
"""MT5-compatible ATR Indicator Module.

This module provides an ATR indicator that exactly matches MetaTrader 5's
iATR() function, using Wilder's smoothing with MT5's seeding convention.

Differences from standard backtrader ATR:
  - Seed at bar index (period - 1) using TR[0..period-1]
  - TR[0] = High[0] - Low[0] (no previous close available)
  - Subsequent: ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period

Classes:
    MT5AverageTrueRange: ATR matching MT5's iATR() (alias: MT5ATR).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.atr = bt.indicators.MT5ATR(self.data, period=14)
"""

import math

from . import Indicator


class MT5AverageTrueRange(Indicator):
    """Average True Range matching MetaTrader 5's iATR() implementation.

    MT5 ATR algorithm:
      - TR[0] = High[0] - Low[0]
      - TR[i] = max(High[i], Close[i-1]) - min(Low[i], Close[i-1])  for i >= 1
      - ATR[period-1] = SMA(TR[0..period-1])   (seed)
      - ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period            for i >= period

    See:
      - https://www.mql5.com/en/docs/indicators/iatr
    """

    alias = ("MT5ATR",)

    lines = ("atr",)
    params = (("period", 14),)

    def _plotlabel(self):
        return [self.p.period]

    def __init__(self):
        super().__init__()
        # MT5 first ATR at bar index period-1, but TR needs prev close from bar 1,
        # and bar 0's TR uses High-Low only. Min period = period bars total.
        self.addminperiod(self.p.period)
        self._period = self.p.period

    @staticmethod
    def _calc_tr(high, low, prev_close):
        """Calculate True Range: max(high, prev_close) - min(low, prev_close)."""
        return max(high, prev_close) - min(low, prev_close)

    def nextstart(self):
        """Seed ATR with SMA of first period TR values (MT5 convention)."""
        period = self._period
        tr_sum = 0.0
        for i in range(period):
            idx = -(period - 1 - i)  # oldest to newest: -(period-1), ..., -1, 0
            if i == 0:
                # First bar: no prev close, use High - Low
                tr = self.data.high[idx] - self.data.low[idx]
            else:
                prev_idx = idx - 1
                tr = self._calc_tr(
                    self.data.high[idx], self.data.low[idx], self.data.close[prev_idx]
                )
            tr_sum += tr
        self.lines.atr[0] = tr_sum / period

    def next(self):
        """ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period."""
        tr = self._calc_tr(self.data.high[0], self.data.low[0], self.data.close[-1])
        self.lines.atr[0] = (self.lines.atr[-1] * (self._period - 1) + tr) / self._period

    def once(self, start, end):
        """Calculate ATR in runonce mode (matches MT5 iATR exactly)."""
        high = self.data.high.array
        low = self.data.low.array
        close = self.data.close.array
        out = self.lines.atr.array
        period = self._period

        # Ensure output array is sized
        while len(out) < end:
            out.append(float("nan"))

        n = min(end, len(high), len(low), len(close))

        # Pre-fill with NaN before seed
        for i in range(min(period - 1, n)):
            out[i] = float("nan")

        if n < period:
            return

        # Seed: SMA of TR[0..period-1]
        seed_idx = period - 1
        tr_sum = high[0] - low[0]  # TR[0] = High - Low (no prev close)
        for i in range(1, period):
            tr_sum += max(high[i], close[i - 1]) - min(low[i], close[i - 1])
        prev_atr = tr_sum / period
        out[seed_idx] = prev_atr

        # Wilder smoothing for remaining bars
        pm1 = period - 1  # period - 1
        for i in range(period, n):
            tr = max(high[i], close[i - 1]) - min(low[i], close[i - 1])
            prev_atr = (prev_atr * pm1 + tr) / period
            out[i] = prev_atr


MT5ATR = MT5AverageTrueRange
