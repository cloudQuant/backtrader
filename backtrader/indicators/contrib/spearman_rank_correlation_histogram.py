#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "SpearmanRankCorrelationHistogram",
]


class SpearmanRankCorrelationHistogram(Indicator):
    """Compute a Spearman-rank-style correlation histogram and regime color."""

    lines = ("value", "color")
    params = (
        ("range_n", 14),
        ("direction", True),
        ("in_high_level", 0.5),
        ("in_low_level", -0.5),
    )

    def __init__(self):
        """Set the indicator minimum period."""
        self.addminperiod(int(self.p.range_n) + 2)

    def _ranks(self, values):
        indexed = list(enumerate(values))
        sorted_values = sorted(indexed, key=lambda item: item[1], reverse=bool(self.p.direction))
        ranks = [0.0] * len(values)
        i = 0
        while i < len(sorted_values):
            j = i + 1
            while j < len(sorted_values) and sorted_values[j][1] == sorted_values[i][1]:
                j += 1
            avg_rank = (i + 1 + j) / 2.0
            for k in range(i, j):
                ranks[sorted_values[k][0]] = avg_rank
            i = j
        return ranks

    def next(self):
        """Compute one step of correlation value and color code."""
        n = int(self.p.range_n)
        values = []
        missing = False
        for i in range(n):
            price = float(self.data.close[-i])
            if math.isnan(price):
                missing = True
            else:
                values.append(int(round(price * 100.0)))
        if missing:
            self.lines.value[0] = float("nan")
            self.lines.color[0] = float("nan")
            return
        ranks = self._ranks(values)
        z2 = 0.0
        for i, rank in enumerate(ranks):
            z2 += (rank - (i + 1)) ** 2
        res = 1.0 - 6.0 * z2 / (n**3 - n)
        self.lines.value[0] = res
        clr = 2
        if res > 0:
            threshold = float(self.p.in_high_level)
            if math.isinf(threshold):
                _reject_factor_infinity(self.lines.value, threshold)
            clr = 4 if res > threshold else 3
        elif res < 0:
            threshold = float(self.p.in_low_level)
            if math.isinf(threshold):
                _reject_factor_infinity(self.lines.value, threshold)
            clr = 0 if res < threshold else 1
        self.lines.color[0] = clr
