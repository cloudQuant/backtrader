#!/usr/bin/env python
from collections import deque

import numpy as np

from .mabase import MovingAverageBase


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
        super().__init__()

    def _calculate_sma_optimized(self, period):
        """Phase 2 Optimization: Optimized SMA calculation with caching and vectorization"""

        # CRITICAL FIX: Don't use cache in runonce mode as it breaks with index changes
        # Check cache first only if we're not in runonce mode
        cache_key = f"sma_{period}_{len(self.data)}"
        if not (hasattr(self, "_idx") and self._idx >= 0) and cache_key in self._result_cache:
            return self._result_cache[cache_key]

        # Phase 2: Use vectorized calculation when enough data is available
        # CRITICAL FIX: In runonce mode, use manual calculation which handles indices correctly
        if (
            self._vectorized_enabled
            and len(self.data) >= period
            and not (hasattr(self, "_idx") and self._idx >= 0)
        ):
            try:
                # Extract recent prices for vectorized calculation
                # Use range(1-period, 1) to get the last 'period' bars including current
                recent_prices = [float(self.data[i]) for i in range(1 - period, 1)]
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
            if hasattr(self.data, "array") and hasattr(self, "_idx") and self._idx >= 0:
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
            if current_price is None and hasattr(self.data, "close"):
                try:
                    if (
                        hasattr(self.data.close, "array")
                        and hasattr(self, "_idx")
                        and self._idx >= 0
                    ):
                        if 0 <= self._idx < len(self.data.close.array):
                            current_price = float(self.data.close.array[self._idx])
                    else:
                        current_price = float(self.data.close[0])
                except (IndexError, TypeError, AttributeError):
                    pass

            if current_price is None:
                return float("nan")

            # CRITICAL FIX: In runonce mode, don't rely on _price_window state
            # Instead, calculate from the data array directly using absolute indices
            if hasattr(self, "_idx") and self._idx >= 0:
                # Runonce mode: use absolute indices
                # Get the data array - try multiple sources
                data_array = None
                if (
                    hasattr(self.data, "lines")
                    and hasattr(self.data.lines, "close")
                    and hasattr(self.data.lines.close, "array")
                ):
                    data_array = self.data.lines.close.array
                elif hasattr(self.data, "array"):
                    data_array = self.data.array

                if data_array is not None:
                    start_idx = max(0, self._idx - period + 1)
                    end_idx = self._idx + 1

                    # DEBUG
                    # print(f"      SMA calc: _idx={self._idx}, period={period}, start_idx={start_idx}, end_idx={end_idx}")

                    if end_idx > start_idx:
                        prices = []
                        for i in range(start_idx, end_idx):
                            if i < len(data_array):
                                prices.append(float(data_array[i]))

                        # DEBUG
                        # if len(prices) > 0:
                        #     print(f"      Prices: {prices[:5]}... (total {len(prices)} prices)")
                        #     print(f"      SMA result: {sum(prices) / len(prices)}")

                        if prices:
                            return sum(prices) / len(prices)
                        else:
                            return float("nan")
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
                    # Not enough data yet - return NaN to prevent premature trading
                    return float("nan")

        except (IndexError, ValueError, TypeError):
            return float("nan")

    def nextstart(self):
        """Initialize on first call after minperiod is met"""
        try:
            period = self.p.period if hasattr(self, "p") else 30

            # Initialize _price_window with historical prices
            # At this point, we have exactly 'period' bars of data
            # Use range(1-period, 1) to get the last 'period' bars including current
            for i in range(1 - period, 1):
                try:
                    price = float(self.data[i])
                    self._price_window.append(price)
                    self._sum += price
                except (IndexError, TypeError, AttributeError):
                    pass

            # Calculate first SMA value
            if len(self._price_window) >= period:
                sma_value = self._sum / period
            else:
                # Not enough data yet - return NaN to prevent premature trading
                sma_value = float("nan")

            # Set the value
            if hasattr(self, "lines") and hasattr(self.lines, "sma"):
                self.lines.sma[0] = sma_value
            elif hasattr(self, "lines") and len(self.lines.lines) > 0:
                self.lines.lines[0][0] = sma_value

        except Exception:
            # Fallback to NaN to prevent premature trading
            if hasattr(self, "lines") and hasattr(self.lines, "sma"):
                self.lines.sma[0] = float("nan")

    def next(self):
        """Phase 2 Optimized next() method with vectorized calculations"""
        try:
            if hasattr(self, "p") and hasattr(self.p, "period"):
                period = self.p.period
            else:
                period = 30  # Default period

            # Phase 2: Use optimized calculation method
            sma_value = self._calculate_sma_optimized(period)

            # CRITICAL FIX: If value is NaN and we have sufficient data, try manual calculation
            if sma_value is None or (
                isinstance(sma_value, float)
                and (sma_value != sma_value or sma_value == float("nan"))
            ):
                # Try one more time with direct manual calculation
                sma_value = self._calculate_sma_manual(period)

            # CRITICAL FIX: Keep NaN when there's insufficient data
            # This is important because strategies may use prenext() to call next()
            # and we don't want to trigger trades when indicators aren't ready
            # NaN comparisons always return False, preventing premature trading
            if sma_value is None:
                sma_value = float("nan")

            # Set the SMA line value
            # CRITICAL FIX: Always use line assignment to ensure lencount is managed correctly
            # Using self.lines.sma[0] = value will automatically call forward() and update lencount
            if hasattr(self, "lines") and hasattr(self.lines, "sma"):
                self.lines.sma[0] = sma_value
            elif hasattr(self, "lines") and len(self.lines.lines) > 0:
                self.lines.lines[0][0] = sma_value

        except Exception:
            # Fallback to NaN to prevent premature trading
            if hasattr(self, "lines") and hasattr(self.lines, "sma"):
                self.lines.sma[0] = float("nan")
            elif hasattr(self, "lines") and len(self.lines.lines) > 0:
                self.lines.lines[0][0] = float("nan")

    def once(self, start, end):
        """Optimized batch calculation for runonce mode"""
        try:
            # CRITICAL FIX: If data source is a LinesOperation, ensure its once() is called first
            # to populate its array before we access it
            if hasattr(self.data, 'once') and hasattr(self.data, 'operation'):
                try:
                    self.data.once(start, end)
                except Exception:
                    pass
            
            # Get arrays for efficient calculation
            dst = self.lines[0].array
            src = self.data.array
            period = self.p.period

            # CRITICAL FIX: Use the actual data source length, not the passed end parameter
            # This is important when multiple data feeds have different lengths
            # The indicator should only calculate up to its own data source's length
            actual_end = min(end, len(src))

            # Ensure destination array is large enough for full end
            # Fill with NaN for positions beyond data source length
            while len(dst) < end:
                dst.append(float("nan"))

            # CRITICAL FIX: Pre-fill only the true warmup period (period-1) with NaN
            # Don't pre-fill based on start parameter as that may skip valid calculation range
            for i in range(0, min(period - 1, len(src))):
                dst[i] = float("nan")

            # Calculate SMA for each index up to actual data length
            # Start from period-1 (first valid SMA) or start, whichever is later
            calc_start = max(period - 1, start)
            for i in range(calc_start, actual_end):
                if i >= period - 1:
                    # Calculate SMA: average of last 'period' values
                    start_idx = i - period + 1
                    end_idx = i + 1
                    if end_idx <= len(src):
                        window = src[start_idx:end_idx]
                        # CRITICAL FIX: Check for NaN values in the window
                        # If any value is NaN (e.g., from misaligned data feeds),
                        # the result should be NaN to match master branch behavior
                        import math
                        if any(math.isnan(v) if isinstance(v, float) else False for v in window):
                            dst[i] = float("nan")
                        else:
                            window_sum = sum(window)
                            dst[i] = window_sum / period
                    else:
                        dst[i] = float("nan")
                else:
                    # Not enough data yet
                    dst[i] = float("nan")
        except Exception:
            # Fallback to once_via_next if once() fails
            super().once_via_next(start, end)


SMA = MovingAverageSimple
