#!/usr/bin/env python
"""ZLEMA Indicator Module - Zero Lag Exponential Moving Average.

This module provides the ZLEMA (Zero Lag Exponential Moving Average)
indicator which aims to reduce lag in the standard EMA.

Classes:
    ZeroLagExponentialMovingAverage: ZLEMA indicator (aliases: ZLEMA, ZeroLagEma).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.zlema = bt.indicators.ZLEMA(self.data.close, period=20)

        def next(self):
            # Price above ZLEMA indicates uptrend
            if self.data.close[0] > self.zlema[0]:
                self.buy()
            # Price below ZLEMA indicates downtrend
            elif self.data.close[0] < self.zlema[0]:
                self.sell()
"""

from . import MovingAverageBase
from .ema import EMA


class ZeroLagExponentialMovingAverage(MovingAverageBase):
    """
    The zero-lag exponential moving average (ZLEMA) is a variation of the EMA
    which adds a momentum term aiming to reduce lag in the average to
    track current prices more closely.

    Formula:
      - lag = (period - 1) / 2
      - zlema = ema(2 * data - data(-lag))

    See also:
      - http://user42.tuxfamily.org/chart/manual/Zero_002dLag-Exponential-Moving-Average.html

    """

    alias = (
        "ZLEMA",
        "ZeroLagEma",
    )
    lines = ("zlema",)
    params = (("_movav", EMA),)

    def __init__(self):
        """Initialize the ZLEMA indicator.

        Calculates lag and alpha values for zero-lag EMA.
        """
        super().__init__()
        self.lag = (self.p.period - 1) // 2
        self.alpha = 2.0 / (1.0 + self.p.period)
        self.alpha1 = 1.0 - self.alpha
        # MovingAverageBase has already added the EMA period.  ZLEMA needs
        # only the additional lagged input history beyond that window.
        self.addminperiod(self.lag + 1)

    def nextstart(self):
        """Seed ZLEMA calculation with SMA on first valid bar.

        Uses SMA of lag-adjusted data for initial seed value.
        """
        # Seed with SMA of adjusted data
        period = self.p.period
        lag = self.lag
        data_sum = 0.0
        for i in range(period):
            adjusted = 2.0 * self.data[-i] - self.data[-i - lag]
            data_sum += adjusted
        self.lines.zlema[0] = data_sum / period

    def next(self):
        """Calculate ZLEMA for the current bar.

        Applies EMA to lag-adjusted data: 2 * data - data(-lag).
        """
        lag = self.lag
        adjusted = 2.0 * self.data[0] - self.data[-lag]
        self.lines.zlema[0] = self.lines.zlema[-1] * self.alpha1 + adjusted * self.alpha

    def once(self, start, end):
        """Calculate ZLEMA in runonce mode.

        Applies EMA to lag-adjusted data across all bars.
        """
        if start >= end:
            return

        darray = self.data.array
        larray = self.lines.zlema.array
        period = self.p.period
        lag = self.lag
        alpha = self.alpha
        alpha1 = self.alpha1

        while len(larray) < end:
            larray.append(float("nan"))

        source_start = max(0, getattr(self.data, "_minperiod", 1) - 1)
        seed_idx = source_start + lag + period - 1
        data_end = min(end, len(darray))

        # Warmup values belong to this call's range only.  In particular, a
        # segmented ``once`` must not clear earlier values or preseed the next
        # segment's seed slot.
        for i in range(start, min(end, seed_idx)):
            larray[i] = float("nan")

        # Match the source buffer's available extent without touching any
        # output outside [start, end).
        for i in range(max(start, len(darray)), end):
            larray[i] = float("nan")

        if seed_idx >= len(darray) or end <= seed_idx:
            return

        if start <= seed_idx:
            # The requested range contains the first complete adjusted window.
            seed_sum = 0.0
            for j in range(period):
                idx = seed_idx - j
                adjusted = 2.0 * darray[idx] - darray[idx - lag]
                seed_sum += adjusted
            prev = seed_sum / period
            larray[seed_idx] = prev
            calc_start = seed_idx + 1
        else:
            # Later ranges continue the recursive state written by the prior
            # range.  NaN is a valid state and must propagate as in next().
            prev = larray[start - 1]
            calc_start = start

        for i in range(calc_start, data_end):
            adjusted = 2.0 * darray[i] - darray[i - lag]
            prev = prev * alpha1 + adjusted * alpha
            larray[i] = prev
