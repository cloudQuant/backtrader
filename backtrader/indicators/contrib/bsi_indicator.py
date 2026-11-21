#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "BSIIndicator",
]


class BSIIndicator(Indicator):
    """Return BSI and trend color, preserving missing inputs as NaN.

    The color remains NaN until the current and previous computed BSI are valid.
    """

    lines = ("bsi", "color")
    params = (
        ("range_period", 20),
        ("slowing", 3),
        ("avg_period", 3),
        ("volume_mode", "TICK"),
    )

    def __init__(self):
        """Set minimum period and initialize smoothing configuration."""
        self.addminperiod(
            int(self.p.range_period) + int(self.p.slowing) + int(self.p.avg_period) + 3
        )

    def _component(self, ago):
        missing = False

        def read(value):
            nonlocal missing
            value = float(value)
            missing |= math.isnan(value)
            return value

        sumpos = 0.0
        sumneg = 0.0
        sumhigh = 0.0
        for k in range(int(self.p.slowing)):
            idx = ago + k
            highs = [read(self.data.high[-(idx + j)]) for j in range(int(self.p.range_period))]
            lows = [read(self.data.low[-(idx + j)]) for j in range(int(self.p.range_period))]
            hh = max(highs)
            ll = min(lows)
            rng = max(hh - ll, 1e-12)
            bark_close = read(self.data.close[-idx])
            bark_prev_close = read(self.data.close[-(idx + 1)])
            bark_high = read(self.data.high[-idx])
            bark_low = read(self.data.low[-idx])
            sp = bark_high - bark_low
            if self.p.volume_mode == "NONE":
                vol = 1.0
            elif self.p.volume_mode == "VOLUME":
                vmax = max(
                    read(self.data.openinterest[-(idx + j)])
                    for j in range(int(self.p.range_period))
                )
                vol = read(self.data.openinterest[-idx]) / vmax if vmax else 0.0
            else:
                vmax = max(
                    read(self.data.volume[-(idx + j)]) for j in range(int(self.p.range_period))
                )
                vol = read(self.data.volume[-idx]) / vmax if vmax else 0.0
            ratio = 0.0
            if not (bark_prev_close - sp * 0.2 > bark_close):
                ratio = 1.0 if bark_low == ll else (hh - bark_low) / rng
                sumpos += (bark_close - bark_low) * ratio * vol
            if not (bark_prev_close + sp * 0.2 < bark_close):
                ratio = 1.0 if bark_high == hh else (bark_high - ll) / rng
                sumneg += (bark_high - bark_close) * ratio * vol * -1.0
            sumhigh += rng
        if missing:
            return math.nan
        if not sumhigh:
            return 0.0
        return (sumpos / sumhigh * 100.0) + (sumneg / sumhigh * 100.0)

    def next(self):
        """Compute BSI and derive color from directional BSI movement."""
        vals = [self._component(i) for i in range(int(self.p.avg_period))]
        bsi = sum(vals) / float(int(self.p.avg_period))
        self.lines.bsi[0] = bsi
        if len(self) < 2:
            self.lines.color[0] = math.nan if math.isnan(bsi) else 1.0
            return
        prev = float(self.lines.bsi[-1])
        if math.isnan(bsi) or (len(self) > self._minperiod and math.isnan(prev)):
            self.lines.color[0] = math.nan
            return
        color = 1.0
        if prev > bsi:
            color = 0.0
        if prev < bsi:
            color = 2.0
        self.lines.color[0] = color
