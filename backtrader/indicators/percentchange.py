#!/usr/bin/env python
from . import Indicator

__all__ = ["PercentChange", "PctChange"]


# Percentage change
class PercentChange(Indicator):
    """
    Measures the percentage change of the current value with respect to that
    of period bars ago
    """

    alias = ("PctChange",)
    lines = ("pctchange",)

    # Fancy plotting name
    plotlines = dict(pctchange=dict(_name="%change"))

    # update value to the standard for Moving Averages
    params = (("period", 30),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        prev_val = self.data[-self.p.period]
        if prev_val != 0:
            self.lines.pctchange[0] = self.data[0] / prev_val - 1.0
        else:
            self.lines.pctchange[0] = 0.0

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.pctchange.array
        period = self.p.period
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(period, min(end, len(darray))):
            prev_val = darray[i - period]
            if prev_val != 0:
                larray[i] = darray[i] / prev_val - 1.0
            else:
                larray[i] = 0.0


PctChange = PercentChange
