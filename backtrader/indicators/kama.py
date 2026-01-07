#!/usr/bin/env python
"""KAMA Indicator Module - Kaufman's Adaptive Moving Average.

This module provides the KAMA (Kaufman's Adaptive Moving Average) indicator
developed by Perry Kaufman to adapt to market volatility and direction.

Classes:
    AdaptiveMovingAverage: KAMA indicator (aliases: KAMA, MovingAverageAdaptive).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.KAMA, period=30)
"""
import math
from . import MovingAverageBase
class AdaptiveMovingAverage(MovingAverageBase):
    """
    Defined by Perry Kaufman in his book `"Smarter Trading"`.

    It is A Moving Average with a continuously scaled smoothing factor by
    taking into account market direction and volatility. The smoothing factor
    is calculated from 2 ExponetialMovingAverage smoothing factors, a fast one
    and slow one.

    If the market trends, the value will tend to the fast ema smoothing
    period. If the market doesn't trend, it will move towards the slow EMA
    smoothing period.

    It is a subclass of SmoothingMovingAverage, overriding once to account for
    the live nature of the smoothing factor

    Formula:
      - direction = close - close_period
      - volatility = sumN(abs (close - close_n), period)
      - effiency_ratio = abs (direction / volatility)
      - fast = 2 / (fast_period + 1)
      - slow = 2 / (slow_period + 1)

      - Smfactor = squared(efficienty_ratio * (fast - slow) + slow)
      - smfactor1 = 1.0 - smfactor

      - The initial seed value is a SimpleMovingAverage

    See also:
      - http://fxcodebase.com/wiki/index.php/Kaufman's_Adaptive_Moving_Average_(KAMA)
      - http://www.metatrader5.com/en/terminal/help/analytics/indicators/trend_indicators/ama
      - http://help.cqg.com/cqgic/default.htm#!Documents/adaptivemovingaverag2.htm
    """

    alias = (
        "KAMA",
        "MovingAverageAdaptive",
    )
    lines = ("kama",)
    params = (("fast", 2), ("slow", 30))

    def __init__(self):
        """Initialize the KAMA indicator.

        Calculates fast and slow smoothing constants for the
        adaptive moving average.
        """
        super().__init__()
        self.fast_sc = 2.0 / (self.p.fast + 1.0)
        self.slow_sc = 2.0 / (self.p.slow + 1.0)

    def _calc_sc(self):
        """Calculate smoothing constant based on efficiency ratio"""
        period = self.p.period
        
        # direction = close - close_period
        direction = self.data[0] - self.data[-period]
        
        # volatility = sum of abs(close - close_prev) over period
        volatility = 0.0
        for i in range(period):
            volatility += abs(self.data[-i] - self.data[-i - 1])
        
        # efficiency ratio
        if volatility != 0:
            er = abs(direction / volatility)
        else:
            er = 0.0
        
        # smoothing constant = (er * (fast - slow) + slow)^2
        sc = pow(er * (self.fast_sc - self.slow_sc) + self.slow_sc, 2)
        return sc

    def nextstart(self):
        """Seed KAMA calculation with SMA on first valid bar.

        Calculates simple moving average for the initial seed value.
        """
        # Seed with SMA
        period = self.p.period
        data_sum = 0.0
        for i in range(period):
            data_sum += self.data[-i]
        self.lines.kama[0] = data_sum / period

    def next(self):
        """Calculate KAMA for the current bar.

        KAMA = prev_KAMA + sc * (price - prev_KAMA)
        where sc is the adaptive smoothing constant.
        """
        sc = self._calc_sc()
        self.lines.kama[0] = self.lines.kama[-1] + sc * (self.data[0] - self.lines.kama[-1])

    def once(self, start, end):
        """Calculate KAMA in runonce mode.

        Seeds with SMA and applies adaptive smoothing for each bar.
        """
        darray = self.data.array
        larray = self.lines.kama.array
        period = self.p.period
        fast_sc = self.fast_sc
        slow_sc = self.slow_sc
        
        while len(larray) < end:
            larray.append(0.0)
        
        # Pre-fill warmup with NaN
        for i in range(min(period, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")
        
        # Calculate seed value (SMA)
        seed_idx = period
        if seed_idx < len(darray):
            seed_sum = sum(darray[seed_idx - period:seed_idx])
            prev_kama = seed_sum / period
            if seed_idx < len(larray):
                larray[seed_idx] = prev_kama
        else:
            prev_kama = 0.0
        
        # Calculate KAMA
        for i in range(seed_idx + 1, min(end, len(darray))):
            # direction
            if i >= period and i - period >= 0:
                direction = darray[i] - darray[i - period]
            else:
                direction = 0.0
            
            # volatility
            volatility = 0.0
            for j in range(period):
                idx = i - j
                if idx > 0 and idx < len(darray) and idx - 1 >= 0:
                    volatility += abs(darray[idx] - darray[idx - 1])
            
            # efficiency ratio
            if volatility != 0:
                er = abs(direction / volatility)
            else:
                er = 0.0
            
            # smoothing constant
            sc = pow(er * (fast_sc - slow_sc) + slow_sc, 2)
            
            # Get previous KAMA
            if i > 0 and i - 1 < len(larray):
                prev_val = larray[i - 1]
                if not (isinstance(prev_val, float) and math.isnan(prev_val)):
                    prev_kama = prev_val
            
            # KAMA formula
            prev_kama = prev_kama + sc * (darray[i] - prev_kama)
            if i < len(larray):
                larray[i] = prev_kama
