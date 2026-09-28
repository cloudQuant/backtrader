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
    "IStochKomposterIndicator",
]


class IStochKomposterIndicator(Indicator):
    """Stochastic-and-ATR composite that prints offset buy/sell markers.

    Emits a buy line below the bar low (and a sell line above the bar high),
    offset by 3/8 of ATR, whenever the slowed %K stochastic crosses up through
    the lower level or down through the upper level respectively.
    """

    lines = ("sell", "buy", "sto", "atr")
    params = (
        ("atr_period", 14),
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
        ("up_level", 70),
        ("dn_level", 30),
    )

    def __init__(self):
        """Build the ATR sub-indicator and set the warm-up minimum period."""
        self._atr = ATR(self.data, period=int(self.p.atr_period))
        self.addminperiod(
            max(
                int(self.p.atr_period),
                int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + 1,
            )
            + 2
        )

    def _raw_k(self, ago):
        period = int(self.p.k_period)
        highs = [float(self.data.high[-(ago + i)]) for i in range(period)]
        lows = [float(self.data.low[-(ago + i)]) for i in range(period)]
        hh = max(highs)
        ll = min(lows)
        cp = float(self.data.close[-ago])
        if hh == ll:
            return 50.0
        return 100.0 * (cp - ll) / (hh - ll)

    def _main_stochastic(self):
        slowing = int(self.p.slowing)
        vals = [self._raw_k(i) for i in range(slowing)]
        return sum(vals) / len(vals)

    def next(self):
        """Compute the slowed stochastic and emit ATR-offset cross markers."""
        self.lines.sell[0] = float("nan")
        self.lines.buy[0] = float("nan")
        sto_now = self._main_stochastic()
        self.lines.sto[0] = sto_now
        self.lines.atr[0] = float(self._atr[0])
        if len(self) < 2:
            return
        sto_prev = float(self.lines.sto[-1])
        atr_now = float(self._atr[0])
        if sto_now > float(self.p.dn_level) and sto_prev <= float(self.p.dn_level):
            self.lines.buy[0] = float(self.data.low[0]) - atr_now * 3.0 / 8.0
        if sto_now < float(self.p.up_level) and sto_prev >= float(self.p.up_level):
            self.lines.sell[0] = float(self.data.high[0]) + atr_now * 3.0 / 8.0
