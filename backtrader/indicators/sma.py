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

        # CRITICAL FIX: Don't use cache in runonce mode as it breaks with index changes
        # Check cache first only if we're not in runonce mode
        cache_key = f"sma_{period}_{len(self.data)}"
        if not hasattr(self, '_idx') and cache_key in self._result_cache:
            return self._result_cache[cache_key]

        # Phase 2: Use vectorized calculation when enough data is available
        # CRITICAL FIX: In runonce mode, use manual calculation which handles indices correctly
        if self._vectorized_enabled and len(self.data) >= period and not hasattr(self, '_idx'):
            try:
                # Extract recent prices for vectorized calculation
                recent_prices = [float(self.data[i]) for i in range(-period, 0)]
                if len(recent_prices) == period:
                    # Vectorized mean calculation
                    result = np.mean(recent_prices) if np else sum(recent_prices) / period

                    # Cache result if within size limit
                    if len(self._result_cache) < self._cache_size_limit:
                        self._result_cache[cache_key] = result

                    return result
            except (IndexError, ValueError, TypeError):
                pass

        # Fallback to manual calculation (works correctly in both modes)
        return self._calculate_sma_manual(period)

    def _calculate_sma_manual(self, period):
        """Manual SMA calculation with rolling window optimization"""
        try:
            # CRITICAL FIX: Access data correctly regardless of mode
            # Try multiple methods to get the current price
            current_price = None
            
            # Method 1: Direct array access with absolute index
            if hasattr(self.data, 'array') and hasattr(self, '_idx'):
                try:
                    if 0 <= self._idx < len(self.data.array):
                        current_price = float(self.data.array[self._idx])
                except (IndexError, TypeError, AttributeError):
                    pass
            
            # Method 2: Standard relative access
            if current_price is None:
                try:
                    current_price = float(self.data[0])
                except (IndexError, TypeError, AttributeError):
                    pass
            
            # Method 3: Try close line directly
            if current_price is None and hasattr(self.data, 'close'):
                try:
                    if hasattr(self.data.close, 'array') and hasattr(self, '_idx'):
                        if 0 <= self._idx < len(self.data.close.array):
                            current_price = float(self.data.close.array[self._idx])
                    else:
                        current_price = float(self.data.close[0])
                except (IndexError, TypeError, AttributeError):
                    pass
            
            if current_price is None:
                return float('nan')

            # CRITICAL FIX: In runonce mode, don't rely on _price_window state
            # Instead, calculate from the data array directly using absolute indices
            if hasattr(self, '_idx') and hasattr(self.data, 'array'):
                # Runonce mode: use absolute indices
                start_idx = max(0, self._idx - period + 1)
                end_idx = self._idx + 1
                
                if end_idx > start_idx:
                    prices = []
                    for i in range(start_idx, end_idx):
                        if i < len(self.data.array):
                            prices.append(float(self.data.array[i]))
                    
                    if prices:
                        return sum(prices) / len(prices)
                    else:
                        return float('nan')
            else:
                # Normal mode: use rolling window optimization
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
            
            # CRITICAL FIX: If value is NaN and we have sufficient data, try manual calculation
            if (sma_value is None or (isinstance(sma_value, float) and (sma_value != sma_value or sma_value == float('nan')))):
                # Try one more time with direct manual calculation
                sma_value = self._calculate_sma_manual(period)

            # Set the SMA line value
            # CRITICAL FIX: In runonce mode, write directly to array using absolute index
            if hasattr(self, '_idx') and hasattr(self, 'lines') and hasattr(self.lines, 'sma'):
                # Runonce mode: write to absolute position in array
                if hasattr(self.lines.sma, 'array'):
                    # Ensure array is large enough
                    while len(self.lines.sma.array) <= self._idx:
                        self.lines.sma.array.append(float('nan'))
                    self.lines.sma.array[self._idx] = sma_value
                else:
                    self.lines.sma[0] = sma_value
            elif hasattr(self, 'lines') and hasattr(self.lines, 'sma'):
                self.lines.sma[0] = sma_value
            elif hasattr(self, 'lines') and len(self.lines.lines) > 0:
                # Fallback to first line
                if hasattr(self, '_idx') and hasattr(self.lines.lines[0], 'array'):
                    while len(self.lines.lines[0].array) <= self._idx:
                        self.lines.lines[0].array.append(float('nan'))
                    self.lines.lines[0].array[self._idx] = sma_value
                else:
                    self.lines.lines[0][0] = sma_value

        except Exception:
            # Fallback to safe default
            if hasattr(self, 'lines') and hasattr(self.lines, 'sma'):
                self.lines.sma[0] = float('nan')
            elif hasattr(self, 'lines') and len(self.lines.lines) > 0:
                self.lines.lines[0][0] = float('nan')

    # Don't override once() - let the framework use once_via_next() automatically
    # This is simpler and more reliable than a custom once() implementation


SMA = MovingAverageSimple
