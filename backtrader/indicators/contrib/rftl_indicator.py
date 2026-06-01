#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "RFTLIndicator",
]


RFTL_WEIGHTS = [
    -0.0025097319,
    0.0513007762,
    0.1142800493,
    0.1699342860,
    0.2025269304,
    0.2025269304,
    0.1699342860,
    0.1142800493,
    0.0513007762,
    -0.0025097319,
]


class RFTLIndicator(Indicator):
    """Indicator that computes a weighted RFTL value from weighted close history."""

    lines = ("rftl",)
    params = (("weights", tuple(RFTL_WEIGHTS)),)

    def __init__(self):
        """Build the RFTL weighted sum and enforce warmup period."""
        total = 0.0
        for idx, weight in enumerate(self.p.weights):
            total += float(weight) * self.data.close(-idx)
        self.lines.rftl = total
        self.addminperiod(len(self.p.weights) + 1)
