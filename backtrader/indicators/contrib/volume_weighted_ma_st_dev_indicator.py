#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "VolumeWeightedMAStDevIndicator",
]


def _applied_price(data, price_type, ago=0):
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    low_price = float(data.low[-ago])
    c = float(data.close[-ago])
    if price_type == 0:
        return c
    if price_type == 1:
        return o
    if price_type == 2:
        return h
    if price_type == 3:
        return low_price
    if price_type == 4:
        return (h + low_price) / 2.0
    if price_type == 5:
        return (h + low_price + c) / 3.0
    if price_type == 6:
        return (h + low_price + c + c) / 4.0
    return c


class VolumeWeightedMAStDevIndicator(Indicator):
    """Volume-weighted MA with standard-deviation graded signal lines.

    Computes a volume-weighted moving average (``vwma``) and measures the
    standard deviation of its change. When the latest change exceeds the
    ``dk1``/``dk2`` standard-deviation bands it sets the corresponding
    ``bulls1``/``bulls2`` or ``bears1``/``bears2`` signal lines.
    """

    lines = ("vwma", "bears1", "bulls1", "bears2", "bulls2")
    params = (
        ("length", 12),
        ("ipc", 0),
        ("use_tick_volume", True),
        ("dk1", 1.5),
        ("dk2", 2.5),
        ("std_period", 9),
    )

    def __init__(self):
        """Reserve the warm-up window for the VWMA and std-dev calculations."""
        self.addminperiod(int(self.p.length) + int(self.p.std_period) + 3)

    def _vwma_at(self, ago):
        length = int(self.p.length)
        weights = []
        total = 0.0
        for i in range(length):
            idx = ago + i
            vol = (
                float(self.data.volume[-idx])
                if self.p.use_tick_volume
                else float(self.data.openinterest[-idx])
            )
            if vol < 0:
                vol = 0.0
            weights.append(vol)
            total += vol
        if total == 0.0:
            return _applied_price(self.data, int(self.p.ipc), ago)
        value = 0.0
        for i in range(length):
            value += _applied_price(self.data, int(self.p.ipc), ago + i) * (weights[i] / total)
        return value

    def next(self):
        """Update the VWMA and set graded bull/bear signal lines."""
        self.lines.bears1[0] = float("nan")
        self.lines.bulls1[0] = float("nan")
        self.lines.bears2[0] = float("nan")
        self.lines.bulls2[0] = float("nan")
        vwma_now = self._vwma_at(0)
        self.lines.vwma[0] = vwma_now
        std_period = int(self.p.std_period)
        dvwma = []
        for i in range(std_period):
            v0 = self._vwma_at(i)
            v1 = self._vwma_at(i + 1)
            dvwma.append(v0 - v1)
        mean = sum(dvwma) / std_period
        variance = sum((x - mean) ** 2 for x in dvwma) / std_period
        stdev = math.sqrt(variance)
        dstd = dvwma[0]
        filter1 = float(self.p.dk1) * stdev
        filter2 = float(self.p.dk2) * stdev
        if dstd < -filter1 and dstd >= -filter2:
            self.lines.bears1[0] = vwma_now
        if dstd < -filter2:
            self.lines.bears2[0] = vwma_now
        if dstd > filter1 and dstd <= filter2:
            self.lines.bulls1[0] = vwma_now
        if dstd > filter2:
            self.lines.bulls2[0] = vwma_now
