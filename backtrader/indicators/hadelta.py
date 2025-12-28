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
        from . import HeikinAshi
        super().__init__()

        self._autoheikin = self.p.autoheikin
        if self.p.autoheikin:
            self._ha = HeikinAshi(self.data)
        else:
            self._ha = None
        
        self._ma = self.p.movav(period=self.p.period)

    def next(self):
        if self._autoheikin:
            hd = self._ha.lines.ha_close[0] - self._ha.lines.ha_open[0]
        else:
            hd = self.data.close[0] - self.data.open[0]
        
        self.lines.haDelta[0] = hd
        
        # Calculate SMA of haDelta
        period = self.p.period
        hd_sum = hd
        for i in range(1, period):
            hd_sum += self.lines.haDelta[-i]
        self.lines.smoothed[0] = hd_sum / period

    def once(self, start, end):
        if self._autoheikin:
            ha_close_array = self._ha.lines.ha_close.array
            ha_open_array = self._ha.lines.ha_open.array
        else:
            ha_close_array = self.data.close.array
            ha_open_array = self.data.open.array
        
        hd_array = self.lines.haDelta.array
        sm_array = self.lines.smoothed.array
        period = self.p.period
        
        for arr in [hd_array, sm_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        # Calculate haDelta
        for i in range(start, min(end, len(ha_close_array), len(ha_open_array))):
            hd_array[i] = ha_close_array[i] - ha_open_array[i]
        
        # Calculate smoothed (SMA of haDelta)
        for i in range(start, min(end, len(hd_array))):
            if i < period - 1:
                sm_array[i] = float("nan")
            else:
                hd_sum = 0.0
                for j in range(period):
                    hd_sum += hd_array[i - j]
                sm_array[i] = hd_sum / period


haD = HaDelta
haDelta = HaDelta  # Alias for tests
