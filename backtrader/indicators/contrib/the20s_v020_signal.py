#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    Indicator,
)

__all__ = [
    "The20sV020Signal",
]


class The20sV020Signal(Indicator):
    """Reversal signal from prior-bar 20% zones with an ATR-offset entry."""

    lines = ("sell", "buy")
    params = (
        ("alg", "MODE_1"),
        ("level", 100),
        ("ratio", 0.2),
        ("direct", False),
        ("atr_period", 15),
        ("point", 0.01),
    )

    def __init__(self):
        """Build the ATR sub-indicator and set the warm-up minimum period."""
        self.atr = ATR(self.data, period=max(int(self.p.atr_period), 1))
        self.addminperiod(max(int(self.p.atr_period), 5) + 6)

    def next(self):
        """Emit buy/sell signal levels from the prior-bar 20% zone logic.

        Resets both lines to zero, and once enough bars exist computes the
        prior-bar range, its upper/lower 20% zones, and the ATR. Under MODE_1 it
        flags a reversal when the previous bar spans the band and the current bar
        breaks beyond it by the level threshold; under MODE_2 it uses a three-bar
        expansion-then-inside pattern. The ``direct`` flag optionally swaps the
        buy and sell outputs.
        """
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0

        if len(self.data) < 6:
            return

        dlevel = float(self.p.level) * float(self.p.point)
        last_range = float(self.data.high[-1]) - float(self.data.low[-1])
        top20 = float(self.data.high[-1]) - last_range * float(self.p.ratio)
        bottom20 = float(self.data.low[-1]) + last_range * float(self.p.ratio)
        atr = float(self.atr[0])

        raw_buy = 0.0
        raw_sell = 0.0

        if str(self.p.alg) == "MODE_1":
            if (
                float(self.data.open[-1]) >= top20
                and float(self.data.close[-1]) <= bottom20
                and float(self.data.low[0]) <= float(self.data.low[-1]) - dlevel
            ):
                raw_buy = float(self.data.low[0]) - atr * 3.0 / 8.0
            elif (
                float(self.data.open[-1]) <= bottom20
                and float(self.data.close[-1]) >= top20
                and float(self.data.high[0]) >= float(self.data.high[-1]) + dlevel
            ):
                raw_sell = float(self.data.high[0]) + atr * 3.0 / 8.0
        else:
            cond = (
                (float(self.data.high[-4]) - float(self.data.low[-4]) > last_range)
                and (float(self.data.high[-3]) - float(self.data.low[-3]) > last_range)
                and (float(self.data.high[-2]) - float(self.data.low[-2]) > last_range)
                and float(self.data.high[-2]) > float(self.data.high[-1])
                and float(self.data.low[-2]) < float(self.data.low[-1])
            )
            if cond:
                if float(self.data.open[0]) <= bottom20:
                    raw_buy = float(self.data.low[0]) - atr * 3.0 / 8.0
                if float(self.data.open[0]) >= top20:
                    raw_sell = float(self.data.high[0]) + atr * 3.0 / 8.0

        if bool(self.p.direct):
            self.lines.buy[0] = raw_buy
            self.lines.sell[0] = raw_sell
        else:
            self.lines.buy[0] = raw_sell
            self.lines.sell[0] = raw_buy
