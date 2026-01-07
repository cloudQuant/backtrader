#!/usr/bin/env python
"""EMA Indicator Module - Exponential Moving Average.

This module provides the EMA (Exponential Moving Average) indicator
which applies weighting factors that decrease exponentially.

Classes:
    ExponentialMovingAverage: EMA indicator (alias: EMA).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.EMA, period=20)
"""
import math
from . import MovingAverageBase
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
        larray = self.lines[0].array
        alpha = self.alpha
        alpha1 = self.alpha1
        period = self.p.period

        # Ensure output array is properly sized
        while len(larray) < end:
            larray.append(0.0)

        # CRITICAL FIX: For LinesOperation data sources, call their once() to populate array
        if hasattr(self.data, 'once') and hasattr(self.data, 'operation'):
            try:
                self.data.once(start, end)
            except Exception:
                pass
        
        darray = self.data.array
        data_len = len(darray)
        if data_len == 0:
            return

        # Find first valid (non-NaN) index for seed calculation
        first_valid = 0
        for i in range(data_len):
            val = darray[i]
            if not (isinstance(val, float) and math.isnan(val)):
                first_valid = i
                break

        # Calculate seed index
        seed_idx = first_valid + period - 1
        
        # CRITICAL FIX: Pre-fill warmup period with NaN up to seed_idx
        # This ensures indices before the seed are NaN, not 0.0
        for i in range(min(seed_idx, data_len)):
            larray[i] = float("nan")

        if seed_idx < data_len:
            seed_sum = 0.0
            valid_count = 0
            for i in range(first_valid, seed_idx + 1):
                val = darray[i]
                if not (isinstance(val, float) and math.isnan(val)):
                    seed_sum += val
                    valid_count += 1
            if valid_count > 0:
                prev = seed_sum / valid_count
                larray[seed_idx] = prev
            else:
                return  # No valid data
        else:
            return  # Not enough data

        # EMA is recursive - must calculate ALL values from seed onwards
        for i in range(seed_idx + 1, min(end, data_len)):
            current_val = darray[i]
            if isinstance(current_val, float) and math.isnan(current_val):
                larray[i] = float("nan")
                continue
            prev = prev * alpha1 + float(current_val) * alpha
            larray[i] = prev


EMA = ExponentialMovingAverage
