#!/usr/bin/env python
import math
from . import MovingAverageBase


# 指数移动平均线
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
        super().__init__()
        self.alpha = 2.0 / (1.0 + self.p.period)
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):
        # Seed value: SMA of first period values
        period = self.p.period
        data_sum = 0.0
        for i in range(period):
            data_sum += self.data[-i]
        self.lines[0][0] = data_sum / period

    def next(self):
        # EMA formula: prev * alpha1 + current * alpha
        self.lines[0][0] = self.lines[0][-1] * self.alpha1 + self.data[0] * self.alpha

    def once(self, start, end):
        """Calculate EMA in runonce mode"""
        # CRITICAL FIX: If data source is a LinesOperation (or similar),
        # ensure its once() is called first to populate its array
        if hasattr(self.data, 'once') and len(self.data.array) > 0:
            # Check if data array has valid values (not all zeros or empty)
            if all(v == 0.0 for v in self.data.array[:min(10, len(self.data.array))]):
                try:
                    self.data.once(start, end)
                except Exception:
                    pass
        
        darray = self.data.array
        larray = self.lines[0].array
        alpha = self.alpha
        alpha1 = self.alpha1
        period = self.p.period

        # Ensure output array is properly sized
        while len(larray) < end:
            larray.append(0.0)

        # Check if we have valid data
        if len(darray) == 0:
            return

        # Pre-fill warmup period with NaN
        for i in range(min(period - 1, len(darray))):
            larray[i] = float("nan")

        # Find first valid (non-NaN) index for seed calculation
        first_valid = 0
        for i in range(len(darray)):
            val = darray[i]
            if not (isinstance(val, float) and math.isnan(val)):
                first_valid = i
                break

        # Calculate seed value (SMA of first period values starting from first valid)
        seed_idx = first_valid + period - 1
        if seed_idx < len(darray):
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
        for i in range(seed_idx + 1, min(end, len(darray))):
            current_val = darray[i]
            if isinstance(current_val, float) and math.isnan(current_val):
                larray[i] = float("nan")
                continue
            prev = prev * alpha1 + float(current_val) * alpha
            larray[i] = prev


EMA = ExponentialMovingAverage
