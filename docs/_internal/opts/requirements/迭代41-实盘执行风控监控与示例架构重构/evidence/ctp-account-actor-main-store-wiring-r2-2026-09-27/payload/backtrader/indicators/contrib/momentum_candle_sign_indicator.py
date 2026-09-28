#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    Indicator,
    Momentum,
)

__all__ = [
    "MomentumCandleSignIndicator",
]


class MomentumCandleSignIndicator(Indicator):
    """Emit ATR-offset buy/sell dots on open/close momentum crossovers."""

    lines = ("sell_signal", "buy_signal", "momentum_open", "momentum_close")
    params = (
        ("period", 12),
        ("atr_period", 15),
    )

    def __init__(self):
        """Build open/close momentum and ATR sub-indicators and set min period."""
        self.addminperiod(max(int(self.p.period), int(self.p.atr_period)) + 3)
        self.momentum_open = Momentum(self.data.open, period=int(self.p.period))
        self.momentum_close = Momentum(self.data.close, period=int(self.p.period))
        self.atr = ATR(self.data, period=int(self.p.atr_period))

    def next(self):
        """Detect momentum crossovers and place ATR-offset signal dots."""
        self.lines.sell_signal[0] = 0.0
        self.lines.buy_signal[0] = 0.0
        self.lines.momentum_open[0] = float(self.momentum_open[0])
        self.lines.momentum_close[0] = float(self.momentum_close[0])
        if len(self.data) < 2:
            return
        prev_open = float(self.momentum_open[-1])
        prev_close = float(self.momentum_close[-1])
        curr_open = float(self.momentum_open[0])
        curr_close = float(self.momentum_close[0])
        atr = float(self.atr[0])
        if prev_open >= prev_close and curr_open < curr_close:
            self.lines.buy_signal[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if prev_open <= prev_close and curr_open > curr_close:
            self.lines.sell_signal[0] = float(self.data.high[0]) + atr * 3.0 / 8.0
