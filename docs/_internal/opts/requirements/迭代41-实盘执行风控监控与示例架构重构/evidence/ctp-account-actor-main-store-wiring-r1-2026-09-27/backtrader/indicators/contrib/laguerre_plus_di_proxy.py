#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "LaguerrePlusDiProxy",
]


class LaguerrePlusDiProxy(Indicator):
    """Laguerre-style +DI proxy normalized to the 0..1 range.

    Approximates the directional-movement balance used by the original EA by
    computing positive/negative directional movement and true range over the
    lookback period and emitting the normalized +DI share.
    """

    lines = ("value",)
    params = (("period", 14),)

    def __init__(self):
        """Set the minimum period required before emitting values."""
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Compute the normalized +DI ratio for the current bar."""
        pdm_vals = []
        mdm_vals = []
        tr_vals = []
        for idx in range(self.p.period):
            high0 = float(self.data.high[-idx])
            high1 = float(self.data.high[-idx - 1])
            low0 = float(self.data.low[-idx])
            low1 = float(self.data.low[-idx - 1])
            close1 = float(self.data.close[-idx - 1])
            up_move = high0 - high1
            down_move = low1 - low0
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            tr = max(high0 - low0, abs(high0 - close1), abs(low0 - close1))
            pdm_vals.append(pdm)
            mdm_vals.append(mdm)
            tr_vals.append(tr)
        tr_sum = sum(tr_vals)
        if tr_sum <= 1e-12:
            self.lines.value[0] = 0.5
            return
        pdi = 100.0 * sum(pdm_vals) / tr_sum
        mdi = 100.0 * sum(mdm_vals) / tr_sum
        denom = pdi + mdi
        ratio = 0.5 if denom <= 1e-12 else pdi / denom
        self.lines.value[0] = max(0.0, min(1.0, ratio))
