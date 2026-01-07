#!/usr/bin/env python
"""Bollinger Bands Indicator Module - Volatility bands.

This module provides the Bollinger Bands indicator developed by
John Bollinger in the 1980s for measuring market volatility.

Classes:
    BollingerBands: Bollinger Bands indicator (alias: BBands).
    BollingerBandsPct: Bollinger Bands with %B line.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.BBands, period=20, devfactor=2.0)
"""
import math
from . import Indicator, MovAv
class BollingerBands(Indicator):
    """
    Defined by John Bollinger in the 80s. It measures volatility by defining
    upper and lower bands at distance x standard deviations

    Formula:
      - midband = SimpleMovingAverage(close, period)
      - topband = midband + devfactor * StandardDeviation(data, period)
      - botband = midband - devfactor * StandardDeviation(data, period)

    See:
      - http://en.wikipedia.org/wiki/Bollinger_Bands
    """

    alias = ("BBands",)

    lines = (
        "mid",
        "top",
        "bot",
    )
    params = (
        ("period", 20),
        ("devfactor", 2.0),
        ("movav", MovAv.Simple),
    )

    plotinfo = dict(subplot=False)
    plotlines = dict(
        mid=dict(ls="--"),
        top=dict(_samecolor=True),
        bot=dict(_samecolor=True),
    )

    def _plotlabel(self):
        plabels = [self.p.period, self.p.devfactor]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the Bollinger Bands indicator.

        Sets minimum period to the configured period.
        """
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):
        """Calculate Bollinger Bands for the current bar.

        Calculates mid (SMA), top (mid + devfactor*stddev), and
        bot (mid - devfactor*stddev) bands.
        """
        period = self.p.period
        devfactor = self.p.devfactor

        # Calculate SMA (mid)
        data_sum = 0.0
        data_sq_sum = 0.0
        for i in range(period):
            val = self.data[-i]
            data_sum += val
            data_sq_sum += val * val

        mid = data_sum / period

        # Calculate StdDev
        meansq = data_sq_sum / period
        sqmean = mid * mid
        diff = abs(meansq - sqmean)
        stddev = math.sqrt(max(0, diff))

        # Set lines
        self.lines.mid[0] = mid
        self.lines.top[0] = mid + devfactor * stddev
        self.lines.bot[0] = mid - devfactor * stddev

    def once(self, start, end):
        """Calculate Bollinger Bands in runonce mode."""
        darray = self.data.array
        mid_array = self.lines.mid.array
        top_array = self.lines.top.array
        bot_array = self.lines.bot.array
        period = self.p.period
        devfactor = self.p.devfactor
        
        # Ensure arrays are sized
        for arr in [mid_array, top_array, bot_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        # Pre-fill warmup with NaN
        for i in range(min(period - 1, len(darray))):
            for arr in [mid_array, top_array, bot_array]:
                if i < len(arr):
                    arr[i] = float("nan")
        
        for i in range(period - 1, min(end, len(darray))):
            data_sum = 0.0
            data_sq_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0 and idx < len(darray):
                    val = darray[idx]
                    if not (isinstance(val, float) and math.isnan(val)):
                        data_sum += val
                        data_sq_sum += val * val
            
            mid = data_sum / period
            meansq = data_sq_sum / period
            sqmean = mid * mid
            diff = abs(meansq - sqmean)
            stddev = math.sqrt(max(0, diff))
            
            if i < len(mid_array):
                mid_array[i] = mid
            if i < len(top_array):
                top_array[i] = mid + devfactor * stddev
            if i < len(bot_array):
                bot_array[i] = mid - devfactor * stddev


# Bollinger Bands Percentage indicator
class BollingerBandsPct(BollingerBands):
    """
    Extends the Bollinger Bands with a Percentage line
    """

    lines = ("pctb",)
    plotlines = dict(pctb=dict(_name="%B"))  # display the line as %B on chart

    def __init__(self):
        """Initialize the Bollinger Bands %B indicator.

        Extends Bollinger Bands with percentage calculation.
        """
        super().__init__()

    def next(self):
        """Calculate %B line for the current bar.

        Formula: %B = (price - bot) / (top - bot)
        """
        super().next()
        top = self.lines.top[0]
        bot = self.lines.bot[0]
        diff = top - bot
        if diff != 0:
            self.lines.pctb[0] = (self.data[0] - bot) / diff
        else:
            self.lines.pctb[0] = 0.0

    def once(self, start, end):
        """Calculate %B line in runonce mode."""
        super().once(start, end)
        darray = self.data.array
        top_array = self.lines.top.array
        bot_array = self.lines.bot.array
        pctb_array = self.lines.pctb.array
        
        while len(pctb_array) < end:
            pctb_array.append(0.0)
        
        for i in range(start, min(end, len(darray), len(top_array), len(bot_array))):
            top = top_array[i] if i < len(top_array) else 0.0
            bot = bot_array[i] if i < len(bot_array) else 0.0
            data_val = darray[i] if i < len(darray) else 0.0
            
            if isinstance(top, float) and math.isnan(top):
                pctb_array[i] = float("nan")
            elif isinstance(bot, float) and math.isnan(bot):
                pctb_array[i] = float("nan")
            else:
                diff = top - bot
                if diff != 0:
                    pctb_array[i] = (data_val - bot) / diff
                else:
                    pctb_array[i] = 0.0
