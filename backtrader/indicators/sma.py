#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .mabase import MovingAverageBase
import numpy as np
from collections import deque


# 移动平均线指标
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
        # Phase 2 optimization: Add result cache and vectorized calculation support
        self._result_cache = {}
        self._cache_size_limit = 1000  # Limit cache size to prevent memory bloat
        self._vectorized_enabled = True  # Enable vectorized calculations when possible

        # Phase 2 optimization: Use deque for efficient rolling window
        self._price_window = deque(maxlen=self.p.period)
        self._sum = 0.0  # Running sum for O(1) SMA updates

        # Before super to ensure mixins (right-hand side in subclassing)
        # can see the assignment operation and operate on the line
        super(MovingAverageSimple, self).__init__()

    def _calculate_sma_optimized(self, period):
        """Phase 2 Optimization: Optimized SMA calculation with caching and vectorization"""

        # Check cache first
        cache_key = f"sma_{period}_{len(self.data)}"
        if cache_key in self._result_cache:
            return self._result_cache[cache_key]

        # Phase 2: Use vectorized calculation when enough data is available
        if self._vectorized_enabled and len(self.data) >= period:
            try:
                # Extract recent prices for vectorized calculation
                # Use correct data access pattern: data[-i] for ago indexing
                recent_prices = []
                for i in range(period):
                    # data[0] is current, data[-1] is previous, etc.
                    recent_prices.append(float(self.data[-i]))
                
                if len(recent_prices) == period:
                    # Vectorized mean calculation
                    result = np.mean(recent_prices) if np else sum(recent_prices) / period

                    # Cache result if within size limit
                    if len(self._result_cache) < self._cache_size_limit:
                        self._result_cache[cache_key] = result

                    return result
            except (IndexError, ValueError, TypeError):
                pass

        # Fallback to manual calculation
        return self._calculate_sma_manual(period)

    def _calculate_sma_manual(self, period):
        """Manual SMA calculation with rolling window optimization"""
        try:
            current_price = float(self.data[0])

            # Phase 2: Use efficient rolling window with deque
            if len(self._price_window) == period:
                # Remove oldest price from sum
                oldest_price = self._price_window[0]
                self._sum -= oldest_price

            # Add current price
            self._price_window.append(current_price)
            self._sum += current_price

            # Calculate SMA using running sum (O(1) operation)
            if len(self._price_window) >= period:
                return self._sum / period
            else:
                # Not enough data yet
                return sum(self._price_window) / len(self._price_window)

        except (IndexError, ValueError, TypeError):
            return float('nan')

    def next(self):
        """Phase 2 Optimized next() method with vectorized calculations"""
        try:
            if hasattr(self, 'p') and hasattr(self.p, 'period'):
                period = self.p.period
            else:
                period = 30  # Default period

            # Phase 2: Use optimized calculation method
            sma_value = self._calculate_sma_optimized(period)

            # Set the SMA line value
            if hasattr(self, 'lines') and hasattr(self.lines, 'sma'):
                self.lines.sma[0] = sma_value
            elif hasattr(self, 'lines') and len(self.lines.lines) > 0:
                self.lines.lines[0][0] = sma_value

        except Exception:
            # Fallback to safe default
            if hasattr(self, 'lines') and hasattr(self.lines, 'sma'):
                self.lines.sma[0] = float('nan')
            elif hasattr(self, 'lines') and len(self.lines.lines) > 0:
                self.lines.lines[0][0] = float('nan')

    def once(self, start, end):
        """CRITICAL FIX: Simplified once() that actually works"""
        period = getattr(self.p, 'period', 30)
        
        # Get the line array for direct manipulation
        # CRITICAL: Don't use truthiness on arrays because empty arrays are False in Python
        sma_array = self.lines.sma.array if hasattr(self.lines.sma, 'array') else None
        # For SMA, we need the close line of the data
        if hasattr(self.data, 'lines') and hasattr(self.data.lines, 'close'):
            data_array = self.data.lines.close.array if hasattr(self.data.lines.close, 'array') else None
        else:
            data_array = self.data.array if hasattr(self.data, 'array') else None

        # Guard: if arrays are not available, bail out
        if sma_array is None or data_array is None:
            return

        # Ensure sma_array has enough space for [0, end)
        missing = end - len(sma_array)
        if missing > 0:
            sma_array.extend([float('nan')] * missing)

        n = len(data_array)
        if n == 0 or period <= 0:
            # Nothing to compute
            return

        # Fill leading region with NaN up to period-1 within [start, end)
        nan_end = min(end, period - 1)
        for i in range(start, nan_end):
            sma_array[i] = float('nan')

        # Start index where a full window exists
        i0 = max(start, period - 1)
        last = min(end, n)
        if i0 >= last:
            # Not enough data within [start, end) to compute any SMA
            return

        # Initial window sum for window ending at i0
        base = i0 - period + 1
        wsum = 0.0
        for j in range(base, i0 + 1):
            wsum += data_array[j]
        sma_array[i0] = wsum / period

        # Slide window forward in O(N)
        for i in range(i0 + 1, last):
            wsum += data_array[i] - data_array[i - period]
            sma_array[i] = wsum / period


SMA = MovingAverageSimple
