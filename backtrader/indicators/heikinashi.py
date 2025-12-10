#!/usr/bin/env python
from . import Indicator, Max, Min


__all__ = ["HeikinAshi"]


# HeikinAshi 形成另类的K线
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
        o = self.data.open
        h = self.data.high
        l = self.data.low
        c = self.data.close

        self.l.ha_close = ha_close = (o + h + l + c) / 4.0
        self.l.ha_open = ha_open = (self.l.ha_open(-1) + ha_close(-1)) / 2.0
        self.l.ha_high = Max(h, ha_open, ha_close)
        self.l.ha_low = Min(l, ha_open, ha_close)

        super().__init__()

    def prenext(self):
        # seed recursive value
        self.lines.ha_open[0] = (self.data.open[0] + self.data.close[0]) / 2.0
