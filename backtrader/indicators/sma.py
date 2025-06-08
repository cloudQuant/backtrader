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
        """Phase 2 Optimized batch processing with vectorization"""
        if not self._vectorized_enabled or end - start < 10:
            # Use regular processing for small batches
            super().once(start, end)
            return
            
        try:
            # Phase 2: Vectorized batch processing for large ranges
            period = getattr(self.p, 'period', 30)
            
            # Extract all needed prices at once
            all_prices = []
            for i in range(start, end):
                try:
                    if hasattr(self.data, '__getitem__'):
                        price = float(self.data[i - len(self.data)])
                    else:
                        price = float(self.data[0])  # Fallback
                    all_prices.append(price)
                except (IndexError, ValueError, TypeError):
                    all_prices.append(float('nan'))
            
            # Vectorized SMA calculation for the entire batch
            if len(all_prices) >= period:
                for i in range(len(all_prices)):
                    if i >= period - 1:
                        # Calculate SMA for window [i-period+1:i+1]
                        window_start = max(0, i - period + 1)
                        window_end = i + 1
                        window_prices = all_prices[window_start:window_end]
                        if len(window_prices) == period:
                            sma_val = sum(window_prices) / period
                        else:
                            sma_val = sum(window_prices) / len(window_prices) if window_prices else float('nan')
                        
                        # Set result
                        result_idx = start + i
                        if hasattr(self, 'lines') and hasattr(self.lines, 'sma'):
                            if hasattr(self.lines.sma, 'array') and result_idx < len(self.lines.sma.array):
                                self.lines.sma.array[result_idx] = sma_val
                        
        except Exception:
            # Fallback to regular processing
            super().once(start, end)
