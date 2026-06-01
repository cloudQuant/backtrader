#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "BezierStDevIndicator",
]


def _factorial(n):
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r


def _price_series(ipc, data, ago=0):
    """Replicate MQ5 PriceSeries with Applied_price_ enum."""
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    low_price = float(data.low[-ago])
    c = float(data.close[-ago])
    if ipc == 0:
        return c  # PRICE_CLOSE_
    if ipc == 1:
        return o  # PRICE_OPEN_
    if ipc == 2:
        return h  # PRICE_HIGH_
    if ipc == 3:
        return low_price  # PRICE_LOW_
    if ipc == 4:
        return (h + low_price) / 2.0  # PRICE_MEDIAN_
    if ipc == 5:
        return (h + low_price + c) / 3.0  # PRICE_TYPICAL_
    if ipc == 6:
        return (h + low_price + c + c) / 4.0  # PRICE_WEIGHTED_
    return c


class BezierStDevIndicator(Indicator):
    """Reconstructs Bezier_StDev indicator.

    Bezier curve interpolation of price over BPeriod, then StDev filter
    on the first derivative to generate Bulls/Bears signals.
    Buffers: 0=BezierLine, 1=ColorIndex, 2=BearsBuffer(sell), 3=BullsBuffer(buy).
    """

    lines = ("bezier", "color", "bears", "bulls")
    params = (
        ("bperiod", 8),
        ("t_param", 0.5),
        ("ipc", 6),
        ("dk", 2.0),
        ("std_period", 9),
    )

    def __init__(self):
        """Cache parameters and precompute coefficients for Bezier interpolation."""
        self._bp = int(self.p.bperiod)
        self._t = float(self.p.t_param)
        self._ipc = int(self.p.ipc)
        self._dk = float(self.p.dk)
        self._sp = int(self.p.std_period)
        # Precompute binomial coefficients
        n = self._bp
        self._binom = [_factorial(n) / (_factorial(i) * _factorial(n - i)) for i in range(n + 1)]
        self.addminperiod(self._bp + self._sp + 3)

    def next(self):
        """Compute Bezier line, color, and bullish/bearish derivative filters."""
        bp = self._bp
        t = self._t
        ipc = self._ipc
        dk = self._dk
        sp = self._sp

        # Compute Bezier for current and previous sp+1 bars
        bezier_vals = []
        needed = sp + 2
        for k in range(needed):
            r = 0.0
            for i in range(bp + 1):
                ago = k + i
                if ago >= len(self.data):
                    break
                price = _price_series(ipc, self.data, ago)
                r += price * self._binom[i] * (t**i) * ((1 - t) ** (bp - i))
            bezier_vals.append(r)

        bz_cur = bezier_vals[0]
        self.lines.bezier[0] = bz_cur

        # Color
        if len(bezier_vals) > 1:
            bz_prev = bezier_vals[1]
            if bz_cur > bz_prev:
                self.lines.color[0] = 1.0
            elif bz_cur < bz_prev:
                self.lines.color[0] = 2.0
            else:
                self.lines.color[0] = 0.0
        else:
            self.lines.color[0] = 0.0

        # StDev filter on derivatives
        d_bezier = []
        for i in range(sp):
            if i + 1 < len(bezier_vals):
                d_bezier.append(bezier_vals[i] - bezier_vals[i + 1])
            else:
                d_bezier.append(0.0)

        mean_d = sum(d_bezier) / sp if sp > 0 else 0
        var_sum = sum((d - mean_d) ** 2 for d in d_bezier)
        std_dev = math.sqrt(var_sum / sp) if sp > 0 else 0

        dstd = d_bezier[0] if d_bezier else 0
        filt = dk * std_dev

        bulls = 0.0
        bears = 0.0
        if dstd > filt:
            bulls = bz_cur
        if dstd < -filt:
            bears = bz_cur

        self.lines.bulls[0] = bulls
        self.lines.bears[0] = bears
