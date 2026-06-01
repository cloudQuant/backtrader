#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from backtrader.utils.dateintern import num2date

from .. import Indicator

__all__ = [
    "DigitalFT01Indicator",
]


DIGITAL_WEIGHTS = [
    0.24470985659780,
    0.23139774006970,
    0.20613796947320,
    0.17166230340640,
    0.13146907903600,
    0.08950387549560,
    0.04960091651250,
    0.01502270569607,
    -0.01188033734430,
    -0.02989873856137,
    -0.03898967104900,
    -0.04014113626390,
    -0.03511968085800,
    -0.02611613850342,
    -0.01539056955666,
    -0.00495353651394,
    0.00368588764825,
    0.00963614049782,
    0.01265138888314,
    0.01307496106868,
    0.01169702291063,
    0.00974841844086,
    0.00898900012545,
    -0.00649745721156,
]


class DigitalFT01Indicator(Indicator):
    """Fixed-weight digital filter with a channel trigger for crossover signals."""

    lines = ("digital", "trigger")
    params = (
        ("halfchannel", 25),
        ("applied_price_code", 1),
        ("point", 0.01),
        ("signal_period_minutes", 180),
    )

    def __init__(self):
        """Set the minimum period to cover the digital-filter kernel length."""
        self.addminperiod(len(DIGITAL_WEIGHTS) + 10)

    def _price_value(self, shift):
        o = float(self.data.open[-shift] if shift else self.data.open[0])
        h = float(self.data.high[-shift] if shift else self.data.high[0])
        low_price = float(self.data.low[-shift] if shift else self.data.low[0])
        c = float(self.data.close[-shift] if shift else self.data.close[0])
        code = int(self.p.applied_price_code)
        if code == 1:
            return c
        if code == 2:
            return o
        if code == 3:
            return h
        if code == 4:
            return low_price
        if code == 5:
            return (h + low_price) / 2.0
        if code == 6:
            return (h + low_price + c) / 3.0
        if code == 7:
            return (h + low_price + c + c) / 4.0
        if code == 8:
            return (o + h + low_price + c) / 4.0
        if code == 12:
            base = h + low_price + c
            if c < o:
                return (base + low_price) / 4.0
            if c > o:
                return (base + h) / 4.0
            return (base + c) / 4.0
        return c

    def next(self):
        """Compute the digital-filter value and channel trigger for this bar.

        Convolves the fixed DIGITAL_WEIGHTS kernel with the applied price, then
        sets the trigger to a reference close plus/minus the half-channel
        depending on whether the filtered value is above or below that close.
        """
        if len(self.data) < len(DIGITAL_WEIGHTS):
            return
        digital = 0.0
        for shift, weight in enumerate(DIGITAL_WEIGHTS):
            digital += weight * self._price_value(shift)
        dt = num2date(self.data.datetime[0])
        period_minutes = max(int(self.p.signal_period_minutes), 1)
        bars_from_day_start = int(round((dt.hour * 60 + dt.minute) / float(period_minutes)) + 1)
        if len(self.data) <= bars_from_day_start:
            return
        ref_close = float(self.data.close[-bars_from_day_start])
        halfchannel = float(self.p.halfchannel) * float(self.p.point)
        trigger = ref_close + halfchannel if digital >= ref_close else ref_close - halfchannel
        self.lines.digital[0] = digital
        self.lines.trigger[0] = trigger
