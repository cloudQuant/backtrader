#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "VWMACandle",
]


class VWMACandle(Indicator):
    """Volume-weighted candle color indicator.

    Computes volume-weighted moving averages of the open and close over
    ``length`` bars and emits a ``color`` line of 2.0 (bullish), 0.0 (bearish)
    or 1.0 (neutral) depending on their relationship. A window with a
    non-finite open, close, or selected weight yields NaN.
    """

    lines = ("color",)
    params = (
        ("length", 12),
        ("use_tick_volume", True),
    )

    def __init__(self):
        """Reserve the warm-up window needed for the volume-weighted average."""
        self.addminperiod(int(self.p.length) + 3)

    def _window(self):
        length = int(self.p.length)
        values = []
        for i in range(length):
            vol = (
                float(self.data.volume[-i])
                if self.p.use_tick_volume
                else float(self.data.openinterest[-i])
            )
            op = float(self.data.open[-i])
            cl = float(self.data.close[-i])
            for value in (op, cl, vol):
                if math.isinf(value):
                    _reject_factor_infinity(self.lines.color, value)
            values.append((op, cl, vol))
        return values

    def _vwma(self, values, price_index):
        if any(not all(math.isfinite(value) for value in row) for row in values):
            return float("nan")

        total = 0.0
        vals = 0.0
        for row in values:
            price, vol = row[price_index], row[2]
            weight = max(vol, 0.0)
            total += weight
            product = price * weight
            for value in (total, product):
                if math.isinf(value):
                    _reject_factor_infinity(self.lines.color, value)
                    return float("nan")
            vals += product
            if math.isinf(vals):
                _reject_factor_infinity(self.lines.color, vals)
                return float("nan")
        result = values[0][price_index] if total == 0.0 else vals / total
        if math.isinf(result):
            _reject_factor_infinity(self.lines.color, result)
            return float("nan")
        return result

    def next(self):
        """Set the candle color from volume-weighted open vs close."""
        values = self._window()
        op = self._vwma(values, 0)
        cl = self._vwma(values, 1)
        if not math.isfinite(op) or not math.isfinite(cl):
            self.lines.color[0] = float("nan")
            return
        color = 1.0
        if op < cl:
            color = 2.0
        elif op > cl:
            color = 0.0
        self.lines.color[0] = color
