#!/usr/bin/env python
"""EMA Indicator Module - Exponential Moving Average.

This module provides the EMA (Exponential Moving Average) indicator
which applies weighting factors that decrease exponentially.

Classes:
    ExponentialMovingAverage: EMA indicator (alias: EMA).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.ema = bt.indicators.EMA(self.data.close, period=20)

        def next(self):
            if self.data.close[0] > self.ema[0]:
                self.buy()
"""

from ..utils.log_message import get_logger
from . import MovingAverageBase

logger = get_logger(__name__)


class ExponentialMovingAverage(MovingAverageBase):
    """
    A Moving Average that smoothes data exponentially over time.

    It is a subclass of SmoothingMovingAverage.

      - self.smfactor -> 2 / (1 + period)
      - self.smfactor1 -> `1 - self.smfactor`

    Formula:
      - movav = prev * (1.0 - smoothfactor) + newdata * smoothfactor

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average
    """

    alias = (
        "EMA",
        "MovingAverageExponential",
    )
    lines = ("ema",)

    def __init__(self):
        """Initialize the EMA indicator.

        Calculates alpha and alpha1 smoothing factors:
        - alpha = 2 / (1 + period)
        - alpha1 = 1 - alpha
        """
        super().__init__()
        self.alpha = 2.0 / (1.0 + self.p.period)
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):
        """Seed the EMA with SMA of first period values."""
        # Seed value: SMA of first period values
        period = self.p.period
        data_sum = 0.0
        for i in range(period):
            data_sum += self.data[-i]
        self.lines[0][0] = data_sum / period

    def next(self):
        """Calculate EMA for the current bar.

        Formula: EMA = previous_ema * alpha1 + current_price * alpha
        """
        # EMA formula: prev * alpha1 + current * alpha
        self.lines[0][0] = self.lines[0][-1] * self.alpha1 + self.data[0] * self.alpha

    def once(self, start, end):
        """Calculate EMA in runonce mode"""
        if start >= end:
            return

        larray = self.lines[0].array
        alpha = self.alpha
        alpha1 = self.alpha1
        period = self.p.period

        # Ensure output array is properly sized
        while len(larray) < end:
            larray.append(float("nan"))

        # CRITICAL FIX: For line-operation data sources, calculate the full
        # input history needed to seed the EMA. Using this EMA's ``start``
        # would skip the operation's warmup window and delay the seed.
        if hasattr(self.data, "once") and hasattr(self.data, "operation"):
            try:
                self.data.once(0, end)
            except Exception as e:
                logger.debug("data.once() failed in EMA: %s", e)

        darray = self.data.array
        data_len = len(darray)

        # The input line's minperiod identifies structural warmup NaNs from
        # upstream indicators. Do not scan for the first non-NaN value here:
        # a NaN in a raw input is real missing data and must remain in the
        # first period-sized seed window, just as it does in nextstart().
        source_start = max(0, getattr(self.data, "_minperiod", 1) - 1)
        seed_idx = source_start + period - 1

        # Only write the requested slice. In particular, a seed-before range
        # must not populate warmup or seed slots that belong to later calls.
        write_start = max(0, start)
        write_end = min(end, data_len)
        for i in range(write_start, min(write_end, seed_idx)):
            larray[i] = float("nan")

        # If the requested output extends beyond the available source, those
        # requested positions are missing rather than stale destination data.
        for i in range(max(write_start, data_len), end):
            larray[i] = float("nan")

        if seed_idx >= data_len or end <= seed_idx:
            return  # No complete seed window in this range

        if start <= seed_idx:
            seed_sum = 0.0
            for i in range(source_start, seed_idx + 1):
                seed_sum += darray[i]
            prev = seed_sum / period
            larray[seed_idx] = prev
            calc_start = seed_idx + 1
        else:
            # once may be called over consecutive ranges. Continue from the
            # previous range's output so a NaN poisons the same recursive
            # state as repeated next() calls.
            prev = larray[start - 1]
            calc_start = start

        for i in range(calc_start, min(end, data_len)):
            current_val = darray[i]
            prev = prev * alpha1 + float(current_val) * alpha
            larray[i] = prev


EMA = ExponentialMovingAverage
