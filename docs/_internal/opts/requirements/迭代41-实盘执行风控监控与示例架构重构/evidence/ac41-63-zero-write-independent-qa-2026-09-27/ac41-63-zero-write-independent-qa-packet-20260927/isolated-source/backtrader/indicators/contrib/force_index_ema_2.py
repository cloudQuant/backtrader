#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "ForceIndexEma",
]


class ForceIndexEma(Indicator):
    """Force Index (price change times volume) smoothed by an EMA."""

    lines = ("value",)
    params = (("period", 24),)

    def __init__(self):
        """Build the raw Force Index and apply the EMA smoothing of length ``period``."""
        raw = (self.data.close - self.data.close(-1)) * self.data.volume
        self.lines.value = ExponentialMovingAverage(raw, period=self.p.period)
