#!/usr/bin/env python
"""MACD Indicator Module - Moving Average Convergence Divergence.

This module provides the MACD (Moving Average Convergence Divergence)
indicator developed by Gerald Appel in the 1970s for trend following.

Classes:
    MACD: MACD indicator with signal line.
    MACDHisto: MACD with histogram (alias: MACDHistogram).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.MACD)
"""
import math
from . import Indicator, MovAv
class MACD(Indicator):
    """
    Moving Average Convergence Divergence. Defined by Gerald Appel in the 70s.

    It measures the distance of a short and a long term moving average to
    try to identify the trend.

    A second lagging moving average over the convergence-divergence should
    provide a "signal" upon being crossed by the macd

    Formula:
      - macd = ema(data, me1_period) - ema(data, me2_period)
      - signal = ema(macd, signal_period)

    See:
      - http://en.wikipedia.org/wiki/MACD
    """

    lines = (
        "macd",
        "signal",
    )
    params = (
        ("period_me1", 12),
        ("period_me2", 26),
        ("period_signal", 9),
        ("movav", MovAv.Exponential),
    )

    plotinfo = dict(plothlines=[0.0])
    plotlines = dict(signal=dict(ls="--"))

    def _plotlabel(self):
        plabels = super()._plotlabel()
        if self.p.isdefault("movav"):
            plabels.remove(self.p.movav)
        return plabels

    def __init__(self):
        """Initialize the MACD indicator.

        Creates moving averages and sets up signal line calculation.
        """
        super().__init__()
        # Store the EMAs as sub-indicators
        self.me1 = self.p.movav(self.data, period=self.p.period_me1)
        self.me2 = self.p.movav(self.data, period=self.p.period_me2)
        
        # Calculate minperiod
        self.macd_minperiod = max(self.p.period_me1, self.p.period_me2)
        signal_minperiod = self.macd_minperiod + self.p.period_signal - 1
        self._minperiod = max(self._minperiod, signal_minperiod)
        
        # CRITICAL FIX: Propagate minperiod to lines so that other indicators
        # using these lines as data sources will inherit the correct minperiod
        for line in self.lines:
            line.updateminperiod(self._minperiod)
        
        # Signal line alpha for EMA calculation
        self.signal_alpha = 2.0 / (1.0 + self.p.period_signal)
        self.signal_alpha1 = 1.0 - self.signal_alpha

    def prenext(self):
        """Calculate MACD during warmup period.

        Ensures MACD values are available for signal line seeding.
        """
        # Calculate MACD during warmup period so values are available for signal seeding
        idx = self.lines[0].idx
        me1_val = self.me1.lines[0].array[idx]
        me2_val = self.me2.lines[0].array[idx]
        self.lines.macd[0] = me1_val - me2_val

    def nextstart(self):
        """Calculate MACD and seed signal line on first valid bar.

        Computes MACD and seeds signal with SMA of MACD values.
        """
        # Calculate MACD = me1 - me2
        # Use direct array access to avoid dependency on indicator processing order
        idx = self.lines[0].idx
        me1_val = self.me1.lines[0].array[idx]
        me2_val = self.me2.lines[0].array[idx]
        macd_val = me1_val - me2_val
        self.lines.macd[0] = macd_val
        # # Seed signal with MACD value
        # self.lines.signal[0] = macd_val
        signal_period = self.p.period_signal
        macd_sum = 0.0
        for i in range(signal_period):
            macd_sum += self.lines.macd[-i]
        self.lines.signal[0] = macd_sum / signal_period

    def next(self):
        """Calculate MACD and signal line for the current bar.

        MACD = me1 - me2
        Signal = EMA(MACD)
        """
        # Calculate MACD = me1 - me2
        # Use direct array access to avoid dependency on indicator processing order
        idx = self.lines[0].idx
        me1_val = self.me1.lines[0].array[idx]
        me2_val = self.me2.lines[0].array[idx]
        macd_val = me1_val - me2_val
        self.lines.macd[0] = macd_val
        # Calculate signal = EMA of MACD
        self.lines.signal[0] = self.lines.signal[-1] * self.signal_alpha1 + macd_val * self.signal_alpha

    def once(self, start, end):
        """Calculate MACD in runonce mode"""
        me1_array = self.me1.lines[0].array
        me2_array = self.me2.lines[0].array
        macd_array = self.lines.macd.array
        signal_array = self.lines.signal.array
        
        signal_alpha = self.signal_alpha
        signal_alpha1 = self.signal_alpha1
        macd_minperiod = self.macd_minperiod
        signal_period = self.p.period_signal
        
        # Ensure arrays are properly sized
        while len(macd_array) < end:
            macd_array.append(0.0)
        while len(signal_array) < end:
            signal_array.append(0.0)
        
        # Pre-fill warmup period with NaN
        for i in range(min(macd_minperiod - 1, len(me1_array))):
            macd_array[i] = float("nan")
            signal_array[i] = float("nan")
        
        # Calculate MACD values for all data points from macd_minperiod onwards
        for i in range(macd_minperiod - 1, min(end, len(me1_array), len(me2_array))):
            me1_val = me1_array[i]
            me2_val = me2_array[i]
            
            # Handle NaN values
            if isinstance(me1_val, float) and math.isnan(me1_val):
                macd_array[i] = float("nan")
                continue
            if isinstance(me2_val, float) and math.isnan(me2_val):
                macd_array[i] = float("nan")
                continue
            
            macd_array[i] = me1_val - me2_val
        
        # Calculate signal line (EMA of MACD)
        signal_start = macd_minperiod + signal_period - 2
        
        # Pre-fill signal warmup with NaN
        for i in range(macd_minperiod - 1, min(signal_start, len(signal_array))):
            signal_array[i] = float("nan")
        
        # Seed signal with SMA of first signal_period MACD values
        if signal_start < len(macd_array) and signal_start >= 0:
            seed_sum = 0.0
            seed_count = 0
            for j in range(macd_minperiod - 1, signal_start + 1):
                if j < len(macd_array):
                    val = macd_array[j]
                    if not (isinstance(val, float) and math.isnan(val)):
                        seed_sum += val
                        seed_count += 1
            prev_signal = seed_sum / seed_count if seed_count > 0 else 0.0
            signal_array[signal_start] = prev_signal
        else:
            prev_signal = 0.0
        
        # Calculate signal EMA for all subsequent data points
        for i in range(signal_start + 1, min(end, len(macd_array))):
            macd_val = macd_array[i]
            if isinstance(macd_val, float) and math.isnan(macd_val):
                signal_array[i] = float("nan")
                continue
            
            prev_signal = prev_signal * signal_alpha1 + macd_val * signal_alpha
            signal_array[i] = prev_signal


class MACDHisto(MACD):
    """
    Subclass of MACD which adds a "histogram" of the difference between the
    macd and signal lines

    Formula:
      - histo = macd - signal

    See:
      - http://en.wikipedia.org/wiki/MACD
    """

    alias = ("MACDHistogram",)

    lines = ("histo",)
    plotlines = dict(histo=dict(_method="bar", alpha=0.50, width=1.0))

    def __init__(self):
        """Initialize the MACD Histogram indicator.

        Extends MACD with histogram line.
        """
        super().__init__()

    def nextstart(self):
        """Calculate MACD Histogram on first valid bar.

        Histogram = MACD - Signal.
        """
        super().nextstart()
        self.lines.histo[0] = self.lines.macd[0] - self.lines.signal[0]

    def next(self):
        """Calculate MACD Histogram for the current bar.

        Histogram = MACD - Signal.
        """
        super().next()
        self.lines.histo[0] = self.lines.macd[0] - self.lines.signal[0]

    def once(self, start, end):
        """Calculate MACD Histogram in runonce mode.

        Computes histogram as MACD minus signal across all bars.
        """
        super().once(start, end)
        macd_array = self.lines.macd.array
        signal_array = self.lines.signal.array
        histo_array = self.lines.histo.array
        
        # Ensure histo array is sized
        while len(histo_array) < end:
            histo_array.append(0.0)
        
        # Calculate histogram
        for i in range(start, min(end, len(macd_array), len(signal_array))):
            macd_val = macd_array[i] if i < len(macd_array) else 0.0
            signal_val = signal_array[i] if i < len(signal_array) else 0.0
            
            if isinstance(macd_val, float) and math.isnan(macd_val):
                histo_array[i] = float("nan")
            elif isinstance(signal_val, float) and math.isnan(signal_val):
                histo_array[i] = float("nan")
            else:
                histo_array[i] = macd_val - signal_val
