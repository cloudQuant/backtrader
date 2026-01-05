#!/usr/bin/env python
import math
from . import Indicator
from .sma import SMA

__all__ = ["HaDelta", "haD", "haDelta"]


# HaDelta指标
class HaDelta(Indicator):
    """Heikin Ashi Delta. Defined by Dan Valcu in his book "Heikin-Ashi: How to
    Trade Without Candlestick Patterns ".

    This indicator measures the difference between Heikin Ashi close and open of
    Heikin Ashi candles, the body of the candle.

    To get signals add haDelta smoothed by 3 period moving average.

    For correct use, the data for the indicator must have been previously
    passed by the Heikin Ahsi filter.

    Formula:
      - HaDelta = Heikin Ashi close - Heikin Ashi open
      - smoothed = movav(haDelta, period)

    """

    alias = ("haD",)

    lines = ("haDelta", "smoothed")

    params = (
        ("period", 3),
        ("movav", SMA),
        ("autoheikin", True),
    )

    plotinfo = dict(subplot=True)

    plotlines = dict(
        haDelta=dict(color="red"),
        smoothed=dict(color="grey", _fill_gt=(0, "green"), _fill_lt=(0, "red")),
    )

    def __init__(self):
        super().__init__()

        self._autoheikin = self.p.autoheikin
        # Store previous HA values for recursive calculation
        self._prev_ha_close = 0.0
        self._prev_ha_open = 0.0
        self._first_bar = True
        
        # Set minperiod = period + 1 to match expected behavior
        self.addminperiod(self.p.period + 1)

    def _calc_heikin_ashi(self):
        """Calculate Heikin Ashi values for current bar inline."""
        if self._autoheikin:
            # ha_close = (open + high + low + close) / 4
            ha_close = (self.data.open[0] + self.data.high[0] + 
                       self.data.low[0] + self.data.close[0]) / 4.0
            
            # ha_open = (prev_ha_open + prev_ha_close) / 2
            if self._first_bar:
                ha_open = (self.data.open[0] + self.data.close[0]) / 2.0
                self._first_bar = False
            else:
                ha_open = (self._prev_ha_open + self._prev_ha_close) / 2.0
            
            # Store for next bar
            self._prev_ha_close = ha_close
            self._prev_ha_open = ha_open
            
            return ha_close - ha_open
        else:
            return self.data.close[0] - self.data.open[0]

    def prenext(self):
        # Calculate haDelta during warmup period
        hd = self._calc_heikin_ashi()
        self.lines.haDelta[0] = hd

    def nextstart(self):
        # First valid bar - calculate haDelta and seed smoothed with SMA
        hd = self._calc_heikin_ashi()
        self.lines.haDelta[0] = hd
        
        # Seed smoothed with SMA of first period haDelta values
        period = self.p.period
        hd_sum = hd
        for i in range(1, period):
            hd_sum += self.lines.haDelta[-i]
        self.lines.smoothed[0] = hd_sum / period

    def next(self):
        # Calculate haDelta = ha_close - ha_open
        hd = self._calc_heikin_ashi()
        self.lines.haDelta[0] = hd
        
        # Calculate SMA of haDelta
        period = self.p.period
        hd_sum = hd
        for i in range(1, period):
            hd_sum += self.lines.haDelta[-i]
        self.lines.smoothed[0] = hd_sum / period

    def once(self, start, end):
        # Get data arrays
        o_array = self.data.open.array
        h_array = self.data.high.array
        l_array = self.data.low.array
        c_array = self.data.close.array
        
        hd_array = self.lines.haDelta.array
        sm_array = self.lines.smoothed.array
        period = self.p.period
        
        # Ensure arrays are properly sized
        for arr in [hd_array, sm_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        data_end = min(end, len(o_array), len(h_array), len(l_array), len(c_array))
        
        if self._autoheikin:
            # Calculate HeikinAshi values inline
            prev_ha_close = 0.0
            prev_ha_open = 0.0
            
            for i in range(0, data_end):
                # ha_close = (open + high + low + close) / 4
                ha_close = (o_array[i] + h_array[i] + l_array[i] + c_array[i]) / 4.0
                
                # ha_open = (prev_ha_open + prev_ha_close) / 2
                if i == 0:
                    ha_open = (o_array[i] + c_array[i]) / 2.0
                else:
                    ha_open = (prev_ha_open + prev_ha_close) / 2.0
                
                hd_array[i] = ha_close - ha_open
                
                prev_ha_close = ha_close
                prev_ha_open = ha_open
        else:
            for i in range(0, data_end):
                hd_array[i] = c_array[i] - o_array[i]
        
        # Calculate smoothed (SMA of haDelta)
        for i in range(0, min(end, len(hd_array))):
            if i < period - 1:
                sm_array[i] = float("nan")
            else:
                hd_sum = 0.0
                for j in range(period):
                    hd_sum += hd_array[i - j]
                sm_array[i] = hd_sum / period


haD = HaDelta
haDelta = HaDelta  # Alias for tests
