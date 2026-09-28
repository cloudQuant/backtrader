#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    Indicator,
    SmoothedMovingAverage,
)

__all__ = [
    "BWWiseMan1Signal",
]


class BWWiseMan1Signal(Indicator):
    """Generate long/short trigger values based on Alligator-like MAs and ATR.

    The indicator outputs two value lines (`buy`, `sell`) that represent candidate
    entry levels for short and long flips under the configured market regime.
    """

    lines = ("sell", "buy")
    params = (
        ("retrogradely", True),
        ("back", 2),
        ("jaw_period", 13),
        ("jaw_shift", 8),
        ("teeth_period", 8),
        ("teeth_shift", 5),
        ("lips_period", 5),
        ("lips_shift", 3),
        ("atr_period", 15),
    )

    def __init__(self):
        """Initialize moving average and ATR lines and minimum period requirements."""
        median_price = (self.data.high + self.data.low) / 2.0
        self.jaw = SmoothedMovingAverage(median_price, period=max(int(self.p.jaw_period), 1))
        self.teeth = SmoothedMovingAverage(median_price, period=max(int(self.p.teeth_period), 1))
        self.lips = SmoothedMovingAverage(median_price, period=max(int(self.p.lips_period), 1))
        self.atr = ATR(self.data, period=max(int(self.p.atr_period), 1))
        self.addminperiod(
            max(
                int(self.p.jaw_period) + int(self.p.jaw_shift),
                int(self.p.teeth_period) + int(self.p.teeth_shift),
                int(self.p.lips_period) + int(self.p.lips_shift),
                int(self.p.atr_period),
            )
            + int(self.p.back)
            + 2
        )

    def next(self):
        """Compute current `buy`/`sell` trigger values from MA and ATR relationships."""
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0

        if len(self.data) <= max(
            int(self.p.jaw_shift), int(self.p.teeth_shift), int(self.p.lips_shift), int(self.p.back)
        ):
            return

        jaw = float(self.jaw[-int(self.p.jaw_shift)])
        teeth = float(self.teeth[-int(self.p.teeth_shift)])
        lips = float(self.lips[-int(self.p.lips_shift)])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        mid = (high + low) / 2.0
        atr = float(self.atr[0])

        raw_sell = 0.0
        raw_buy = 0.0

        if low > lips and low > teeth and low > jaw and close < mid:
            contup = True
            for i in range(1, int(self.p.back) + 1):
                if high <= float(self.data.high[-i]):
                    contup = False
                    break
            if contup:
                raw_sell = high + atr * 3.0 / 8.0

        if high < lips and high < teeth and high < jaw and close > mid:
            contup = True
            for i in range(1, int(self.p.back) + 1):
                if low >= float(self.data.low[-i]):
                    contup = False
                    break
            if contup:
                raw_buy = low - atr * 3.0 / 8.0

        if bool(self.p.retrogradely):
            self.lines.buy[0] = raw_sell
            self.lines.sell[0] = raw_buy
        else:
            self.lines.buy[0] = raw_buy
            self.lines.sell[0] = raw_sell
