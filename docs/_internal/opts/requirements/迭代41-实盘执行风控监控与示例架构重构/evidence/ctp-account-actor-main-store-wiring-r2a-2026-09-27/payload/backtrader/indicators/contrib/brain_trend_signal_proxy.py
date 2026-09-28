#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    AverageTrueRange,
    Indicator,
    Stochastic,
)

__all__ = [
    "BrainTrendSignalProxy",
]


class BrainTrendSignalProxy(Indicator):
    """Signal proxy that combines ATR and stochastic cross conditions."""

    lines = ("buy_signal", "sell_signal")
    params = (
        ("atr_period", 14),
        ("sto_period", 12),
    )

    def __init__(self):
        """Initialize indicators and required warm-up bars."""
        self.atr = AverageTrueRange(self.data, period=self.p.atr_period)
        self.stoch = Stochastic(self.data, period=self.p.sto_period)
        self.addminperiod(max(self.p.atr_period, self.p.sto_period) + 3)

    def next(self):
        """Emit buy and sell trigger levels for the latest bar."""
        buy_signal = 0.0
        sell_signal = 0.0
        close0 = float(self.data.close[0])
        atr0 = float(self.atr[0])
        k0 = float(self.stoch.percK[0])
        k1 = float(self.stoch.percK[-1])
        if k1 <= 20.0 and k0 > 20.0 and close0 > float(self.data.close[-1]) + atr0 * 0.1:
            buy_signal = close0
        elif k1 >= 80.0 and k0 < 80.0 and close0 < float(self.data.close[-1]) - atr0 * 0.1:
            sell_signal = close0
        self.lines.buy_signal[0] = buy_signal
        self.lines.sell_signal[0] = sell_signal
