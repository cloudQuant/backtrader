#!/usr/bin/env python
"""ATR Indicator Module - Average True Range.

This module provides the ATR (Average True Range) indicator developed by
J. Welles Wilder, Jr. for measuring market volatility.

Classes:
    TrueHigh: Records the true high for ATR calculation.
    TrueLow: Records the true low for ATR calculation.
    TrueRange: Calculates the True Range.
    AverageTrueRange: Calculates the Average True Range (alias: ATR).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.ATR, period=14)
"""
import math
from . import Indicator, MovAv
class TrueHigh(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the ATR

    Records the "true high" which is the maximum of today's high and
    yesterday's close

    Formula:
      - truehigh = max (high, close_prev)

    See:
      - http://en.wikipedia.org/wiki/Average_true_range
    """

    lines = ("truehigh",)

    def __init__(self):
        """Initialize the TrueHigh indicator.

        Adds a minimum period of 2 to access previous close.
        """
        super().__init__()
        self.addminperiod(2)

    def next(self):
        """Calculate true high: max(high, previous_close)."""
        self.lines.truehigh[0] = max(self.data.high[0], self.data.close[-1])

    def once(self, start, end):
        """Calculate true high in runonce mode."""
        high_array = self.data.high.array
        close_array = self.data.close.array
        larray = self.lines.truehigh.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        if len(high_array) > 0 and len(larray) > 0:
            larray[0] = high_array[0] if len(high_array) > 0 else 0.0
        
        for i in range(1, min(end, len(high_array), len(close_array))):
            high_val = high_array[i] if i < len(high_array) else 0.0
            prev_close = close_array[i - 1] if i > 0 and i - 1 < len(close_array) else 0.0
            if i < len(larray):
                larray[i] = max(high_val, prev_close)


class TrueLow(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the ATR

    Records the "true low" which is the minimum of today's low and
    yesterday's close

    Formula:
      - truelow = min (low, close_prev)

    See:
      - http://en.wikipedia.org/wiki/Average_true_range
    """

    lines = ("truelow",)

    def __init__(self):
        """Initialize the TrueLow indicator.

        Adds a minimum period of 2 to access previous close.
        """
        super().__init__()
        self.addminperiod(2)

    def next(self):
        """Calculate true low: min(low, previous_close)."""
        self.lines.truelow[0] = min(self.data.low[0], self.data.close[-1])

    def once(self, start, end):
        """Calculate true low in runonce mode."""
        low_array = self.data.low.array
        close_array = self.data.close.array
        larray = self.lines.truelow.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        if len(low_array) > 0 and len(larray) > 0:
            larray[0] = low_array[0] if len(low_array) > 0 else 0.0
        
        for i in range(1, min(end, len(low_array), len(close_array))):
            low_val = low_array[i] if i < len(low_array) else 0.0
            prev_close = close_array[i - 1] if i > 0 and i - 1 < len(close_array) else 0.0
            if i < len(larray):
                larray[i] = min(low_val, prev_close)


class TrueRange(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book New Concepts in
    Technical Trading Systems.

    Formula:
      - max(high - low, abs (high - prev_close), abs(prev_close - low)

      Which can be simplified to

      - Max(high, prev_close) - min(low, prev_close)

    See:
      - http://en.wikipedia.org/wiki/Average_true_range

    The idea is to take the previous close into account to calculate the range
    if it yields a larger range than the daily range (High - Low)
    """

    alias = ("TR",)

    lines = ("tr",)

    def __init__(self):
        """Initialize the TrueRange indicator.

        Adds a minimum period of 2 to access previous close.
        """
        super().__init__()
        self.addminperiod(2)

    def next(self):
        """Calculate true range: truehigh - truelow."""
        truehigh = max(self.data.high[0], self.data.close[-1])
        truelow = min(self.data.low[0], self.data.close[-1])
        self.lines.tr[0] = truehigh - truelow

    def once(self, start, end):
        """Calculate true range in runonce mode."""
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        larray = self.lines.tr.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        if len(high_array) > 0 and len(low_array) > 0 and len(larray) > 0:
            larray[0] = high_array[0] - low_array[0] if len(high_array) > 0 and len(low_array) > 0 else 0.0
        
        for i in range(1, min(end, len(high_array), len(low_array), len(close_array))):
            high_val = high_array[i] if i < len(high_array) else 0.0
            low_val = low_array[i] if i < len(low_array) else 0.0
            prev_close = close_array[i - 1] if i > 0 and i - 1 < len(close_array) else 0.0
            
            truehigh = max(high_val, prev_close)
            truelow = min(low_val, prev_close)
            
            if i < len(larray):
                larray[i] = truehigh - truelow


class AverageTrueRange(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    The idea is to take the close into account to calculate the range if it
    yields a larger range than the daily range (High - Low)

    Formula:
      - SmoothedMovingAverage(TrueRange, period)

    See:
      - http://en.wikipedia.org/wiki/Average_true_range
    """

    alias = ("ATR",)

    lines = ("atr",)
    params = (("period", 14), ("movav", MovAv.Smoothed))

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the ATR indicator.

        Sets up Wilder's smoothing factors.
        """
        super().__init__()
        self.addminperiod(self.p.period + 1)
        # SMMA alpha for Wilder's smoothing
        self.alpha = 1.0 / self.p.period
        self.alpha1 = 1.0 - self.alpha

    def _calc_tr(self, high, low, prev_close):
        """Calculate True Range

        Args:
            high: Current high price.
            low: Current low price.
            prev_close: Previous close price.

        Returns:
            float: True range value.
        """
        truehigh = max(high, prev_close)
        truelow = min(low, prev_close)
        return truehigh - truelow

    def nextstart(self):
        """Seed ATR with SMA of first period TR values."""
        # Seed with SMA of first period TR values
        period = self.p.period
        tr_sum = 0.0
        for i in range(period):
            if i == 0:
                tr = self.data.high[-i] - self.data.low[-i]
            else:
                tr = self._calc_tr(self.data.high[-i], self.data.low[-i], self.data.close[-i - 1])
            tr_sum += tr
        self.lines.atr[0] = tr_sum / period

    def next(self):
        """Calculate ATR for the current bar.

        Uses smoothed moving average: ATR = prev_ATR * alpha1 + TR * alpha
        """
        tr = self._calc_tr(self.data.high[0], self.data.low[0], self.data.close[-1])
        self.lines.atr[0] = self.lines.atr[-1] * self.alpha1 + tr * self.alpha

    def once(self, start, end):
        """Calculate ATR in runonce mode."""
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        larray = self.lines.atr.array
        period = self.p.period
        alpha = self.alpha
        alpha1 = self.alpha1
        
        while len(larray) < end:
            larray.append(0.0)
        
        # Pre-fill warmup with NaN (indices 0 to period-1)
        for i in range(min(period, len(high_array))):
            if i < len(larray):
                larray[i] = float("nan")
        
        # CRITICAL FIX: Always seed at index `period` (first valid ATR position)
        # regardless of the `start` parameter. The ATR needs `period` TR values,
        # and TR starts from index 1 (needs close[-1]), so first valid ATR is at index `period`.
        seed_idx = period
        if seed_idx < len(high_array) and seed_idx < len(low_array) and seed_idx < len(close_array):
            tr_sum = 0.0
            for j in range(period):
                # Use TR values from indices 1 to period (inclusive)
                idx = j + 1  # Start from index 1 (first valid TR)
                if idx < len(high_array) and idx < len(low_array) and idx - 1 < len(close_array):
                    truehigh = max(high_array[idx], close_array[idx - 1])
                    truelow = min(low_array[idx], close_array[idx - 1])
                    tr = truehigh - truelow
                    tr_sum += tr
            prev_atr = tr_sum / period
            if seed_idx < len(larray):
                larray[seed_idx] = prev_atr
        else:
            prev_atr = 0.0
        
        # Calculate ATR using SMMA for all subsequent bars
        for i in range(seed_idx + 1, min(end, len(high_array), len(low_array), len(close_array))):
            truehigh = max(high_array[i], close_array[i - 1])
            truelow = min(low_array[i], close_array[i - 1])
            tr = truehigh - truelow
            
            if i > 0 and i - 1 < len(larray):
                prev_val = larray[i - 1]
                if not (isinstance(prev_val, float) and math.isnan(prev_val)):
                    prev_atr = prev_val
            
            prev_atr = prev_atr * alpha1 + tr * alpha
            if i < len(larray):
                larray[i] = prev_atr


TR = TrueRange
ATR = AverageTrueRange
