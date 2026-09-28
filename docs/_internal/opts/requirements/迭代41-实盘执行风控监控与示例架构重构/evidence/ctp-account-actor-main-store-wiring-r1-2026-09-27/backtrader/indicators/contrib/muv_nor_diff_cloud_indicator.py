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

__all__ = [
    "MUVNorDiffCloudIndicator",
]


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
        sma_cur = sma_vals[0]
        ema_cur = ema_vals[0]
        sma_max = max(sma_vals)
        sma_min = min(sma_vals)
        ema_max = max(ema_vals)
        ema_min = min(ema_vals)
        sma_range = sma_max - sma_min
        ema_range = ema_max - ema_min
        sma_res = 100.0 - 200.0 * (sma_max - sma_cur) / sma_range if sma_range > 0 else 100.0
        ema_res = 100.0 - 200.0 * (ema_max - ema_cur) / ema_range if ema_range > 0 else 100.0
        self.lines.sma_res[0] = sma_res
        self.lines.ema_res[0] = ema_res
        self.lines.buy[0] = 100.0 if sma_res == 100.0 or ema_res == 100.0 else 0.0
        self.lines.sell[0] = -100.0 if sma_res == -100.0 or ema_res == -100.0 else 0.0

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
                    continue
                sma_delta = float(sma[idx]) - float(sma[prev])
                ema_delta = float(ema[idx]) - float(ema[prev])
                if math.isfinite(sma_delta):
                    sma_vals.append(sma_delta)
                if math.isfinite(ema_delta):
                    ema_vals.append(ema_delta)
            if not sma_vals or not ema_vals:
                sma_res = ema_res = 0.0
            else:
                sma_cur = sma_vals[0]
                ema_cur = ema_vals[0]
                sma_max = max(sma_vals)
                sma_min = min(sma_vals)
                ema_max = max(ema_vals)
                ema_min = min(ema_vals)
                sma_range = sma_max - sma_min
                ema_range = ema_max - ema_min
                sma_res = (
                    100.0 - 200.0 * (sma_max - sma_cur) / sma_range if sma_range > 0 else 100.0
                )
                ema_res = (
                    100.0 - 200.0 * (ema_max - ema_cur) / ema_range if ema_range > 0 else 100.0
                )
            sma_res_line[i] = sma_res
            ema_res_line[i] = ema_res
            buy[i] = 100.0 if sma_res == 100.0 or ema_res == 100.0 else 0.0
            sell[i] = -100.0 if sma_res == -100.0 or ema_res == -100.0 else 0.0
