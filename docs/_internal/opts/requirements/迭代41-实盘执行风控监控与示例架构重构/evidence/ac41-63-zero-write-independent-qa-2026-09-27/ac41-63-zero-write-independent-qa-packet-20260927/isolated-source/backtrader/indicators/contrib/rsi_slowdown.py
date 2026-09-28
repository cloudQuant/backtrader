#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    RSI,
    Indicator,
)

__all__ = [
    "RSISlowdown",
]


class RSISlowdown(Indicator):
    """RSI Slowdown — detects RSI extreme flattening as reversal signal.

    Fires buy when RSI(2) >= level_max (overbought) and the change between
    consecutive bars is small (slowdown). Fires sell symmetrically at
    level_min (oversold). Signal lines store ATR-scaled price levels.
    """

    lines = ("sell", "buy")
    params = (
        ("rsi_period", 2),
        ("level_max", 90.0),
        ("level_min", 10.0),
        ("seek_slowdown", True),
    )

    def __init__(self):
        """Create RSI and ATR indicators and set minimum required periods."""
        self.addminperiod(max(int(self.p.rsi_period) + 2, 18))
        self.rsi = RSI(self.data, period=int(self.p.rsi_period))
        self.atr = ATR(self.data, period=15)

    def next(self):
        """Compute RSI slowdown signal for the current bar.

        Sets buy/sell lines to ATR-derived price levels when the RSI extreme
        + slowdown condition is met, or NaN otherwise.
        """
        self.lines.buy[0] = float("nan")
        self.lines.sell[0] = float("nan")
        r0 = float(self.rsi[0])
        r1 = float(self.rsi[-1])
        atr = float(self.atr[0])
        if r0 >= float(self.p.level_max):
            if (not self.p.seek_slowdown) or abs(r1 - r0) < 1.0:
                self.lines.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if r0 <= float(self.p.level_min):
            if (not self.p.seek_slowdown) or abs(r1 - r0) < 1.0:
                self.lines.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0
