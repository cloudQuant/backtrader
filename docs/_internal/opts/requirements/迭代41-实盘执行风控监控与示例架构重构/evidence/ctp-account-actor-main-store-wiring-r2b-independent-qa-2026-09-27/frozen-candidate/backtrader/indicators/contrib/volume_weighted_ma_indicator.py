#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "VolumeWeightedMAIndicator",
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


class VolumeWeightedMAIndicator(Indicator):
    """Volume-weighted moving average of an applied price.

    Averages the applied price (selected by ``ipc``) over ``length`` bars,
    weighting each bar by its tick volume (or open interest when
    ``use_tick_volume`` is False); falls back to the plain applied price when
    the total weight is zero.
    """

    lines = ("vwma",)
    params = (
        ("length", 12),
        ("ipc", 0),
        ("use_tick_volume", True),
    )

    def __init__(self):
        """Set the minimum period to cover the averaging window."""
        self.addminperiod(int(self.p.length) + 2)

    def next(self):
        """Compute the volume-weighted average price for the current bar."""
        length = int(self.p.length)
        weights = []
        total = 0.0
        for i in range(length):
            vol = (
                float(self.data.volume[-i])
                if self.p.use_tick_volume
                else float(self.data.openinterest[-i])
            )
            if vol < 0:
                vol = 0.0
            weights.append(vol)
            total += vol
        if total == 0.0:
            self.lines.vwma[0] = _applied_price(self.data, int(self.p.ipc), 0)
            return
        value = 0.0
        for i in range(length):
            value += _applied_price(self.data, int(self.p.ipc), i) * (weights[i] / total)
        self.lines.vwma[0] = value
