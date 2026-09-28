#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "NonLagDotIndicator",
]


PI = math.pi


class NonLagDotIndicator(Indicator):
    """Reconstructs NonLagDot from its MQ5 source.

    Applies a weighted cosine kernel over SMA values to produce a non-lag MA,
    then assigns color: 0=gray, 1=magenta(down), 2=green(up).
    """

    lines = ("nlm", "color")
    params = (
        ("length", 10),
        ("filter_pts", 0),
        ("deviation", 0.0),
        ("point", 0.0001),
    )

    def __init__(self):
        """Pre-compute kernel parameters and allocate indicator state."""
        self._length = int(self.p.length)
        coeff = 3 * PI
        phase = self._length - 1
        cycle = 4
        self._len_total = int(self._length * cycle + phase)
        self._dT1 = (2 * cycle - 1) / (cycle * self._length - 1)
        self._dT2 = 1.0 / (phase - 1) if phase > 1 else 1.0
        self._kd = 1.0 + self.p.deviation / 100.0
        self._fi = int(self.p.filter_pts) * float(self.p.point)
        self._coeff = coeff
        self._phase = phase
        self._cycle = cycle
        self._trend = 0
        self.addminperiod(self._length + self._len_total + 2)

    def _calc_sma(self, ago):
        length = self._length
        total = 0.0
        for i in range(length):
            total += float(self.data.close[-(ago + i)])
        return total / length

    def next(self):
        """Compute smoothed value and trend color for current bar.

        The method calculates weighted SMA contributions, applies optional filtering,
        and updates `nlm` and `color` lines.
        """
        len_total = self._len_total
        coeff = self._coeff
        phase = self._phase
        fi = self._fi

        # Build weighted sum using cosine kernel over SMA values
        total_sum = 0.0
        total_weight = 0.0
        t = 0.0

        for i in range(int(len_total)):
            # SMA at offset i (0 = current bar)
            sma_val = self._calc_sma(i)
            if i <= phase - 1:
                alfa = 1.0
            else:
                alfa = 1.0 / (1.0 + math.exp((i - phase + 0.5) * coeff / len_total))

            beta = math.cos(PI * t)
            g = 1.0 / (coeff * t + 1.0)
            if t <= 0.5:
                g = 1.0

            total_sum += sma_val * beta * g * alfa
            total_weight += beta * g * alfa

            if t < 0.5:
                t += self._dT2
            elif t < len_total - 1:
                t += self._dT1

        nlm_val = self._kd * total_sum / total_weight if total_weight > 0 else 0.0

        # Filter: if change < fi, hold previous value
        prev_nlm = (
            float(self.lines.nlm[-1])
            if len(self.lines.nlm) > 1 and not math.isnan(float(self.lines.nlm[-1]))
            else nlm_val
        )
        if fi > 0 and abs(nlm_val - prev_nlm) < fi:
            nlm_val = prev_nlm

        self.lines.nlm[0] = nlm_val

        # Trend detection
        trend = self._trend
        if nlm_val - prev_nlm > fi:
            trend = 1  # up
        if prev_nlm - nlm_val > fi:
            trend = -1  # down

        # Color: 0=gray, 1=magenta(down), 2=green(up)
        color = 0.0
        if trend > 0:
            color = 2.0
        if trend < 0:
            color = 1.0

        self.lines.color[0] = color
        self._trend = trend
