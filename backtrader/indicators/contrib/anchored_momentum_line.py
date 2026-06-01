#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "AnchoredMomentumLine",
    "AnchoredMomentumCandleIndicator",
]


class AnchoredMomentumLine(Indicator):
    """Anchored Momentum line: EMA-vs-SMA percentage plus a zone classifier."""

    lines = ("momentum", "zone")
    params = (
        ("mom_period", 8),
        ("smooth_period", 6),
        ("up_level", 0.025),
        ("dn_level", -0.025),
    )

    def __init__(self):
        """Create the SMA/EMA sub-indicators and set the minimum period."""
        self.sma = SimpleMovingAverage(self.data, period=int(self.p.mom_period))
        self.ema = ExponentialMovingAverage(self.data, period=int(self.p.mom_period))
        self.addminperiod(int(self.p.mom_period) + 2)

    def next(self):
        """Compute the percentage momentum and assign its up/neutral/down zone."""
        sma = float(self.sma[0])
        if sma == 0:
            momentum = 0.0
        else:
            momentum = 100.0 * (float(self.ema[0]) / sma - 1.0)
        self.lines.momentum[0] = momentum
        if momentum > float(self.p.up_level):
            zone = 2
        elif momentum < float(self.p.dn_level):
            zone = 0
        else:
            zone = 1
        self.lines.zone[0] = zone


class AnchoredMomentumCandleIndicator(Indicator):
    """Synthetic candle from Anchored Momentum on each OHLC price plus colour."""

    lines = ("a_open", "a_high", "a_low", "a_close", "color")
    params = (
        ("mom_period", 8),
        ("smooth_period", 6),
        ("up_level", 0.025),
        ("dn_level", -0.025),
    )

    def __init__(self):
        """Create the four per-price Anchored Momentum lines and set min period."""
        self.mom_open = AnchoredMomentumLine(
            self.data.open,
            mom_period=self.p.mom_period,
            smooth_period=self.p.smooth_period,
            up_level=self.p.up_level,
            dn_level=self.p.dn_level,
        )
        self.mom_high = AnchoredMomentumLine(
            self.data.high,
            mom_period=self.p.mom_period,
            smooth_period=self.p.smooth_period,
            up_level=self.p.up_level,
            dn_level=self.p.dn_level,
        )
        self.mom_low = AnchoredMomentumLine(
            self.data.low,
            mom_period=self.p.mom_period,
            smooth_period=self.p.smooth_period,
            up_level=self.p.up_level,
            dn_level=self.p.dn_level,
        )
        self.mom_close = AnchoredMomentumLine(
            self.data.close,
            mom_period=self.p.mom_period,
            smooth_period=self.p.smooth_period,
            up_level=self.p.up_level,
            dn_level=self.p.dn_level,
        )
        self.addminperiod(int(self.p.mom_period) + 2)

    def next(self):
        """Assemble the momentum candle OHLC and colour for the current bar."""
        o = float(self.mom_open.momentum[0])
        h = max(float(self.mom_high.momentum[0]), o)
        low_price = min(float(self.mom_low.momentum[0]), o)
        c = float(self.mom_close.momentum[0])
        h = max(h, c)
        low_price = min(low_price, c)
        self.lines.a_open[0] = o
        self.lines.a_high[0] = h
        self.lines.a_low[0] = low_price
        self.lines.a_close[0] = c
        if o < c:
            color = 2
        elif o > c:
            color = 0
        else:
            color = 1
        self.lines.color[0] = color
