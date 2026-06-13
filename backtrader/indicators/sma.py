#!/usr/bin/env python
"""SMA Indicator Module - Simple Moving Average.

This module provides the SMA (Simple Moving Average) indicator for
calculating the non-weighted average of the last n periods.

Classes:
    MovingAverageSimple: SMA indicator (alias: SMA).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=20)

        def next(self):
            if self.data.close[0] > self.sma[0]:
                self.buy()
            elif self.data.close[0] < self.sma[0]:
                self.sell()
"""

import math

from ..utils.log_message import get_logger
from .mabase import MovingAverageBase

logger = get_logger(__name__)


# Moving average indicator
class MovingAverageSimple(MovingAverageBase):
    """
    Non-weighted average of the last n periods

    Formula:
      - movav = Sum(data, period) / period

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Simple_moving_average
    """

    alias = (
        "SMA",
        "SimpleMovingAverage",
    )
    lines = ("sma",)

    def __init__(self):
        """Initialize the SMA indicator."""
        # Before super to ensure mixins (right-hand side in subclassing)
        # can see the assignment operation and operate on the line
        super().__init__()
        self._period = self.p.period
        self._next_offsets = tuple(range(1 - self._period, 1))
        data = getattr(self, "data", None)
        self._data_getitem = data.__getitem__ if data is not None else None
        self._sma_line = self.lines.sma
        self._fsum = math.fsum

    def nextstart(self):
        """Initialize on first call after minperiod is met."""
        # Delegate to next() — at this point we have exactly enough data
        self.next()

    def next(self):
        """Calculate SMA for the current bar.

        Recalculates from scratch each bar using sum of the last 'period'
        values to avoid floating-point drift from incremental updates.
        """
        try:
            data_getitem = self._data_getitem
            if data_getitem is None:
                data_getitem = self.data.__getitem__
                self._data_getitem = data_getitem
            prices = [float(data_getitem(i)) for i in self._next_offsets]
            self._sma_line[0] = self._fsum(prices) / self._period
        except (AttributeError, ValueError, TypeError, IndexError):
            logger.debug("SMA next() failed", exc_info=True)
            self._sma_line[0] = float("nan")

    def once(self, start, end):
        """Batch calculation for runonce mode."""
        try:
            # If data source is a LinesOperation, ensure its once() is called first
            if hasattr(self.data, "once") and hasattr(self.data, "operation"):
                try:
                    self.data.once(start, end)
                except Exception as e:
                    logger.debug("data.once() failed in SMA: %s", e)

            dst = self.lines[0].array
            src = self.data.array
            period = self.p.period
            actual_end = min(end, len(src))

            # Ensure destination array is large enough, pre-fill with NaN
            while len(dst) < end:
                dst.append(float("nan"))

            # Pre-fill warmup period with NaN
            for i in range(min(period - 1, len(src))):
                dst[i] = float("nan")

            calc_start = max(period - 1, start)
            fsum = math.fsum  # Cache function reference
            nan_val = float("nan")

            for i in range(calc_start, actual_end):
                start_idx = i - period + 1
                end_idx = i + 1
                if end_idx <= len(src):
                    window = src[start_idx:end_idx]
                    # NaN check: only NaN != NaN (faster than isinstance + isnan)
                    has_nan = False
                    for v in window:
                        if v != v:
                            has_nan = True
                            break
                    if has_nan:
                        dst[i] = nan_val
                    else:
                        dst[i] = fsum(window) / period
                else:
                    dst[i] = nan_val
        except Exception:
            logger.debug("SMA once() failed, falling back to once_via_next", exc_info=True)
            super().once_via_next(start, end)


SMA = MovingAverageSimple
