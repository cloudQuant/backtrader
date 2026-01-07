#!/usr/bin/env python
"""DEMA/TEMA Indicator Module - Double/Triple Exponential Moving Average.

This module provides DEMA and TEMA indicators introduced by Patrick G. Mulloy
in 1994 to reduce the lag associated with traditional moving averages.

Classes:
    DoubleExponentialMovingAverage: DEMA indicator (alias: DEMA).
    TripleExponentialMovingAverage: TEMA indicator (alias: TEMA).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.DEMA, period=20)
"""
import math
from . import MovingAverageBase
from .ema import EMA
class DoubleExponentialMovingAverage(MovingAverageBase):
    """
    DEMA was first time introduced in 1994, in the article "Smoothing Data with
    Faster-Moving Averages" by Patrick G. Mulloy in "Technical Analysis of
    Stocks & Commodities" magazine.

    It attempts to reduce the inherent lag associated with Moving Averages

    Formula:
      - dema = (2.0 - ema(data, period) - ema(ema(data, period), period)

    See:
      (None)
    """

    alias = (
        "DEMA",
        "MovingAverageDoubleExponential",
    )

    lines = ("dema",)
    params = (("_movav", EMA),)

    def __init__(self):
        """Initialize the DEMA indicator.

        Creates two EMAs for the DEMA calculation.
        """
        super().__init__()
        self.ema1 = self.p._movav(self.data, period=self.p.period)
        self.ema2 = self.p._movav(self.ema1, period=self.p.period)
        # minperiod = 2 * period - 1 for DEMA
        self._minperiod = max(self._minperiod, 2 * self.p.period - 1)

    def next(self):
        """Calculate DEMA for the current bar.

        Formula: DEMA = 2 * EMA1 - EMA(EMA1)
        """
        self.lines.dema[0] = 2.0 * self.ema1[0] - self.ema2[0]

    def once(self, start, end):
        """Calculate DEMA in runonce mode."""
        ema1_array = self.ema1.lines[0].array
        ema2_array = self.ema2.lines[0].array
        larray = self.lines.dema.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        minperiod = 2 * self.p.period - 1
        for i in range(min(minperiod - 1, len(ema1_array))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(minperiod - 1, min(end, len(ema1_array), len(ema2_array))):
            ema1_val = ema1_array[i] if i < len(ema1_array) else 0.0
            ema2_val = ema2_array[i] if i < len(ema2_array) else 0.0
            
            if isinstance(ema1_val, float) and math.isnan(ema1_val):
                larray[i] = float("nan")
            elif isinstance(ema2_val, float) and math.isnan(ema2_val):
                larray[i] = float("nan")
            else:
                larray[i] = 2.0 * ema1_val - ema2_val


# Triple Exponential Moving Average
class TripleExponentialMovingAverage(MovingAverageBase):
    """
    TEMA was first time introduced in 1994, in the article "Smoothing Data with
    Faster-Moving Averages" by Patrick G. Mulloy in "Technical Analysis of
    Stocks & Commodities" magazine.

    It attempts to reduce the inherent lag associated with Moving Averages

    Formula:
      - ema1 = ema(data, period)
      - ema2 = ema(ema1, period)
      - ema3 = ema(ema2, period)
      - tema = 3 * ema1 - 3 * ema2 + ema3

    See:
      (None)
    """

    alias = (
        "TEMA",
        "MovingAverageTripleExponential",
    )

    lines = ("tema",)
    params = (("_movav", EMA),)

    def __init__(self):
        """Initialize the TEMA indicator.

        Creates three EMAs for the TEMA calculation.
        """
        super().__init__()
        self.ema1 = self.p._movav(self.data, period=self.p.period)
        self.ema2 = self.p._movav(self.ema1, period=self.p.period)
        self.ema3 = self.p._movav(self.ema2, period=self.p.period)
        # minperiod = 3 * period - 2 for TEMA
        self._minperiod = max(self._minperiod, 3 * self.p.period - 2)

    def next(self):
        """Calculate TEMA for the current bar.

        Formula: TEMA = 3 * EMA1 - 3 * EMA2 + EMA3
        """
        self.lines.tema[0] = 3.0 * self.ema1[0] - 3.0 * self.ema2[0] + self.ema3[0]

    def once(self, start, end):
        """Calculate TEMA in runonce mode."""
        ema1_array = self.ema1.lines[0].array
        ema2_array = self.ema2.lines[0].array
        ema3_array = self.ema3.lines[0].array
        larray = self.lines.tema.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        minperiod = 3 * self.p.period - 2
        for i in range(min(minperiod - 1, len(ema1_array))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(minperiod - 1, min(end, len(ema1_array), len(ema2_array), len(ema3_array))):
            ema1_val = ema1_array[i] if i < len(ema1_array) else 0.0
            ema2_val = ema2_array[i] if i < len(ema2_array) else 0.0
            ema3_val = ema3_array[i] if i < len(ema3_array) else 0.0
            
            if isinstance(ema1_val, float) and math.isnan(ema1_val):
                larray[i] = float("nan")
            elif isinstance(ema2_val, float) and math.isnan(ema2_val):
                larray[i] = float("nan")
            elif isinstance(ema3_val, float) and math.isnan(ema3_val):
                larray[i] = float("nan")
            else:
                larray[i] = 3.0 * ema1_val - 3.0 * ema2_val + ema3_val
