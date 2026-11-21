#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
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

    def _valid(self, *values):
        for value in values:
            if not math.isfinite(value):
                _reject_factor_infinity(self.lines.value, value)
                self.lines.value[0] = float("nan")
                return False
        return True

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
            if not self._valid(high0, high1, low0, low1, close1):
                return
            up_move = high0 - high1
            down_move = low1 - low0
            ranges = (high0 - low0, high0 - close1, low0 - close1)
            if not self._valid(up_move, down_move, *ranges):
                return
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            tr = max(ranges[0], abs(ranges[1]), abs(ranges[2]))
            pdm_vals.append(pdm)
            mdm_vals.append(mdm)
            tr_vals.append(tr)
        tr_sum = sum(tr_vals)
        pdm_sum = sum(pdm_vals)
        mdm_sum = sum(mdm_vals)
        if not self._valid(tr_sum, pdm_sum, mdm_sum):
            return
        if tr_sum <= 1e-12:
            self.lines.value[0] = 0.5
            return
        pdi_numerator = 100.0 * pdm_sum
        mdi_numerator = 100.0 * mdm_sum
        if not self._valid(pdi_numerator, mdi_numerator):
            return
        pdi = pdi_numerator / tr_sum
        mdi = mdi_numerator / tr_sum
        denom = pdi + mdi
        if not self._valid(pdi, mdi, denom):
            return
        ratio = 0.5 if denom <= 1e-12 else pdi / denom
        if not self._valid(ratio):
            return
        self.lines.value[0] = max(0.0, min(1.0, ratio))
