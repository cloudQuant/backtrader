#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    MeanDev,
    MovAv,
)

__all__ = [
    "CloseLineCCI",
]


class CloseLineCCI(Indicator):
    """Custom CCI indicator designed to evaluate simple single close lines instead of HLC.

    Lines:
        cci (Line): Output Commodity Channel Index line.
    """

    lines = ("cci",)
    params = (
        ("period", 20),
        ("factor", 0.015),
        ("movav", MovAv.Simple),
    )

    def __init__(self):
        """Initialize and calculate close-based CCI indicator components."""
        tp = self.data
        tpmean = self.p.movav(tp, period=self.p.period)
        meandev = MeanDev(tp, tpmean, period=self.p.period)
        self.lines.cci = (tp - tpmean) / (self.p.factor * meandev)
