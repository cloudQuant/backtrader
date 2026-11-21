#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
)
from ...linebuffer import _reject_factor_infinity

__all__ = [
    "MUVNorDiffCloudIndicator",
]


def _cloud_values(sma_vals, ema_vals, *, context_line=None):
    """Calculate a cloud only from complete finite current and history windows."""
    if context_line is not None:
        for value in (*sma_vals, *ema_vals):
            _reject_factor_infinity(context_line, value)
    if not all(math.isfinite(value) for value in (*sma_vals, *ema_vals)):
        # The public strategy tests signal lines with ``!= 0``; NaN there would
        # be interpreted as a signal, so keep missing cloud values neutral.
        return 0.0, 0.0, float("nan"), float("nan")

    sma_cur, ema_cur = sma_vals[0], ema_vals[0]
    sma_max, sma_min = max(sma_vals), min(sma_vals)
    ema_max, ema_min = max(ema_vals), min(ema_vals)
    sma_range, ema_range = sma_max - sma_min, ema_max - ema_min
    sma_distance, ema_distance = sma_max - sma_cur, ema_max - ema_cur
    sma_scaled, ema_scaled = 200.0 * sma_distance, 200.0 * ema_distance
    intermediates = (sma_range, ema_range, sma_distance, ema_distance, sma_scaled, ema_scaled)
    if context_line is not None:
        for value in intermediates:
            _reject_factor_infinity(context_line, value)
    if not all(math.isfinite(value) for value in intermediates):
        return 0.0, 0.0, float("nan"), float("nan")
    sma_res = 100.0 - sma_scaled / sma_range if sma_range > 0 else 100.0
    ema_res = 100.0 - ema_scaled / ema_range if ema_range > 0 else 100.0
    if context_line is not None:
        _reject_factor_infinity(context_line, sma_res)
        _reject_factor_infinity(context_line, ema_res)
    if not math.isfinite(sma_res) or not math.isfinite(ema_res):
        return 0.0, 0.0, float("nan"), float("nan")
    buy = 100.0 if sma_res == 100.0 or ema_res == 100.0 else 0.0
    sell = -100.0 if sma_res == -100.0 or ema_res == -100.0 else 0.0
    return buy, sell, sma_res, ema_res


class MUVNorDiffCloudIndicator(Indicator):
    """Calculate normalized DIFF cloud signals used by the strategy."""

    lines = ("buy", "sell", "sma_res", "ema_res")
    params = (
        ("ma_period", 14),
        ("momentum", 1),
        ("kperiod", 14),
    )

    def __init__(self):
        """Initialize SMA/EMA buffers and minimum bars required for reliable signals."""
        price = self.data.close
        self._sma = SimpleMovingAverage(price, period=max(1, int(self.p.ma_period)))
        self._ema = ExponentialMovingAverage(price, period=max(1, int(self.p.ma_period)))
        self.addminperiod(int(self.p.ma_period) + int(self.p.momentum) + int(self.p.kperiod) + 5)

    def next(self):
        """Compute cloud values for the current bar."""
        momentum = max(1, int(self.p.momentum))
        kperiod = max(2, int(self.p.kperiod))
        sma_vals = []
        ema_vals = []
        for i in range(kperiod):
            sma_vals.append(float(self._sma[-i]) - float(self._sma[-i - momentum]))
            ema_vals.append(float(self._ema[-i]) - float(self._ema[-i - momentum]))
        buy, sell, sma_res, ema_res = _cloud_values(
            sma_vals, ema_vals, context_line=self.lines.sma_res
        )
        self.lines.sma_res[0] = sma_res
        self.lines.ema_res[0] = ema_res
        self.lines.buy[0] = buy
        self.lines.sell[0] = sell

    def once(self, start, end):
        """Compute cloud values for a pre-allocated bar range in vectorized mode."""
        momentum = max(1, int(self.p.momentum))
        kperiod = max(2, int(self.p.kperiod))
        sma = self._sma.array
        ema = self._ema.array
        buy = self.lines.buy.array
        sell = self.lines.sell.array
        sma_res_line = self.lines.sma_res.array
        ema_res_line = self.lines.ema_res.array

        for i in range(start, end):
            sma_vals = []
            ema_vals = []
            for j in range(kperiod):
                idx = i - j
                prev = idx - momentum
                if prev < 0:
                    sma_vals.append(float("nan"))
                    ema_vals.append(float("nan"))
                else:
                    sma_vals.append(float(sma[idx]) - float(sma[prev]))
                    ema_vals.append(float(ema[idx]) - float(ema[prev]))
            buy_value, sell_value, sma_res, ema_res = _cloud_values(
                sma_vals, ema_vals, context_line=self.lines.sma_res
            )
            sma_res_line[i] = sma_res
            ema_res_line[i] = ema_res
            buy[i] = buy_value
            sell[i] = sell_value
