#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "AIAccelerationDecelerationOscillator",
]


class AIAccelerationDecelerationOscillator(Indicator):
    """Indicator computing acceleration/deceleration oscillator from SMA spread."""

    lines = ("ac",)
    params = (
        ("fast", 5),
        ("slow", 34),
        ("signal", 5),
    )

    def __init__(self):
        """Initialize AC line based on fast/slow/signal SMAs."""
        median = (self.data.high + self.data.low) / 2.0
        ao = SimpleMovingAverage(median, period=self.p.fast) - SimpleMovingAverage(
            median, period=self.p.slow
        )
        self.lines.ac = ao - SimpleMovingAverage(ao, period=self.p.signal)
