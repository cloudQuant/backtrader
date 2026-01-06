#!/usr/bin/env python
from . import Indicator, Max, Min

__all__ = ["HeikinAshi"]


# HeikinAshi forms alternative candlesticks
class HeikinAshi(Indicator):
    """
    Heikin Ashi candlesticks in the forms of lines

    Formula:
        ha_open = (ha_open(-1) + ha_close(-1)) / 2
        ha_high = max (hi, ha_open, ha_close)
        ha_low = min (lo, ha_open, ha_close)
        ha_close = (open + high + low + close) / 4

    See also:
        https://en.wikipedia.org/wiki/Candlestick_chart#Heikin_Ashi_candlesticks
        http://stockcharts.com/school/doku.php?id=chart_school:chart_analysis:heikin_ashi
    """

    lines = (
        "ha_open",
        "ha_high",
        "ha_low",
        "ha_close",
    )

    linealias = (
        (
            "ha_open",
            "open",
        ),
        (
            "ha_high",
            "high",
        ),
        (
            "ha_low",
            "low",
        ),
        (
            "ha_close",
            "close",
        ),
    )

    plotinfo = dict(subplot=False)

    _nextforce = True

    def __init__(self):
        # CRITICAL FIX: Call super().__init__() FIRST to ensure proper initialization
        super().__init__()
        # Use next()/once() methods for calculation to avoid recursive line operation issues
        # that cause strategy's next() to never be called

    def next(self):
        # ha_close = (open + high + low + close) / 4
        ha_close = (self.data.open[0] + self.data.high[0] + self.data.low[0] + self.data.close[0]) / 4.0
        self.lines.ha_close[0] = ha_close
        
        # ha_open = (ha_open[-1] + ha_close[-1]) / 2
        # Uses PREVIOUS bar's ha_open and PREVIOUS bar's ha_close
        if len(self) > 1:
            ha_open = (self.lines.ha_open[-1] + self.lines.ha_close[-1]) / 2.0
        else:
            # First bar: seed with average of open and close
            ha_open = (self.data.open[0] + self.data.close[0]) / 2.0
        self.lines.ha_open[0] = ha_open
        
        # ha_high = max(high, ha_open, ha_close)
        self.lines.ha_high[0] = max(self.data.high[0], ha_open, ha_close)
        
        # ha_low = min(low, ha_open, ha_close)
        self.lines.ha_low[0] = min(self.data.low[0], ha_open, ha_close)

    def prenext(self):
        # Same calculation as next() for prenext period
        self.next()

    def once(self, start, end):
        """Batch calculation for runonce mode - matches next() logic exactly"""
        o_array = self.data.open.array
        h_array = self.data.high.array
        l_array = self.data.low.array
        c_array = self.data.close.array
        
        ha_open_array = self.lines.ha_open.array
        ha_high_array = self.lines.ha_high.array
        ha_low_array = self.lines.ha_low.array
        ha_close_array = self.lines.ha_close.array
        
        # Ensure arrays are properly sized
        for arr in [ha_open_array, ha_high_array, ha_low_array, ha_close_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        data_len = min(end, len(o_array), len(h_array), len(l_array), len(c_array))
        for i in range(start, data_len):
            # ha_close = (open + high + low + close) / 4
            ha_close = (o_array[i] + h_array[i] + l_array[i] + c_array[i]) / 4.0
            ha_close_array[i] = ha_close
            
            # ha_open = (ha_open[-1] + ha_close[-1]) / 2
            # Uses PREVIOUS bar's ha_open and PREVIOUS bar's ha_close
            if i > 0:
                ha_open = (ha_open_array[i-1] + ha_close_array[i-1]) / 2.0
            else:
                ha_open = (o_array[i] + c_array[i]) / 2.0
            ha_open_array[i] = ha_open
            
            # ha_high and ha_low
            ha_high_array[i] = max(h_array[i], ha_open, ha_close)
            ha_low_array[i] = min(l_array[i], ha_open, ha_close)
