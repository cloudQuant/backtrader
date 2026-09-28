#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "BSIIndicator",
]


class BSIIndicator(Indicator):
    """Balance of power-style indicator returning BSI value and trend color."""

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
        sumpos = 0.0
        sumneg = 0.0
        sumhigh = 0.0
        for k in range(int(self.p.slowing)):
            idx = ago + k
            highs = [float(self.data.high[-(idx + j)]) for j in range(int(self.p.range_period))]
            lows = [float(self.data.low[-(idx + j)]) for j in range(int(self.p.range_period))]
            hh = max(highs)
            ll = min(lows)
            rng = max(hh - ll, 1e-12)
            bark_close = float(self.data.close[-idx])
            bark_prev_close = float(self.data.close[-(idx + 1)])
            bark_high = float(self.data.high[-idx])
            bark_low = float(self.data.low[-idx])
            sp = bark_high - bark_low
            if self.p.volume_mode == "NONE":
                vol = 1.0
            elif self.p.volume_mode == "VOLUME":
                vmax = max(
                    float(self.data.openinterest[-(idx + j)])
                    for j in range(int(self.p.range_period))
                )
                vol = float(self.data.openinterest[-idx]) / vmax if vmax else 0.0
            else:
                vmax = max(
                    float(self.data.volume[-(idx + j)]) for j in range(int(self.p.range_period))
                )
                vol = float(self.data.volume[-idx]) / vmax if vmax else 0.0
            ratio = 0.0
            if not (bark_prev_close - sp * 0.2 > bark_close):
                ratio = 1.0 if bark_low == ll else (hh - bark_low) / rng
                sumpos += (bark_close - bark_low) * ratio * vol
            if not (bark_prev_close + sp * 0.2 < bark_close):
                ratio = 1.0 if bark_high == hh else (bark_high - ll) / rng
                sumneg += (bark_high - bark_close) * ratio * vol * -1.0
            sumhigh += rng
        if not sumhigh:
            return 0.0
        return (sumpos / sumhigh * 100.0) + (sumneg / sumhigh * 100.0)

    def next(self):
        """Compute BSI and derive color from directional BSI movement."""
        vals = [self._component(i) for i in range(int(self.p.avg_period))]
        bsi = sum(vals) / float(int(self.p.avg_period))
        self.lines.bsi[0] = bsi
        if len(self) < 2:
            self.lines.color[0] = 1.0
            return
        prev = float(self.lines.bsi[-1])
        color = 1.0
        if prev > bsi:
            color = 0.0
        if prev < bsi:
            color = 2.0
        self.lines.color[0] = color
