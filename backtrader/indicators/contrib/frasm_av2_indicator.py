#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FRASMAv2Indicator",
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


class FRASMAv2Indicator(Indicator):
    """Fractal-adaptive moving average exposing the ``frasma`` line and slope ``color``."""

    lines = ("frasma", "color")
    params = (
        ("e_period", 30),
        ("normal_speed", 20),
        ("ipc", 0),
    )

    def __init__(self):
        """Set the minimum warmup period from the estimation and speed windows."""
        self.addminperiod(max(int(self.p.e_period), int(self.p.normal_speed)) + 3)

    def next(self):
        """Compute the fractal dimension, adapt the averaging speed, and set color.

        Estimates the fractal dimension of the recent price window, derives an
        adaptive averaging length, writes the resulting value to ``frasma``, and
        encodes its slope into ``color`` (0 rising, 1 flat, 2 falling).
        """
        self.lines.color[0] = 1.0
        need = max(int(self.p.e_period), int(self.p.normal_speed))
        prices = [
            _applied_price(self.data, int(self.p.ipc), i) for i in range(min(need, len(self.data)))
        ]
        e_period = int(self.p.e_period)
        normal_speed = int(self.p.normal_speed)
        g_period_minus_1 = e_period - 1
        if len(prices) < e_period:
            self.lines.frasma[0] = prices[0]
            return
        sample = prices[:e_period]
        price_max = max(sample)
        price_min = min(sample)
        price_range = price_max - price_min
        length = 0.0
        prior_diff = 0.0
        for k in range(g_period_minus_1 + 1):
            if price_range > 0.0:
                diff = (sample[k] - price_min) / price_range
                if k > 0:
                    length += math.sqrt((diff - prior_diff) ** 2 + (1.0 / (e_period**2)))
                prior_diff = diff
        if length > 0.0 and g_period_minus_1 > 0:
            fdi = 1.0 + (math.log(length) + math.log(2.0)) / math.log(2.0 * g_period_minus_1)
        else:
            fdi = 0.0
        res = 2.0 - fdi
        if res == 0.0:
            res = 2.0
        trail_dim = 1.0 / res
        alpha = trail_dim / 2.0
        speed = int(min(max(round(normal_speed * alpha), 1), 10000))
        speed = min(speed, len(prices))
        value = sum(prices[:speed]) / float(speed)
        self.lines.frasma[0] = value
        if len(self) < 2:
            return
        prev = float(self.lines.frasma[-1])
        color = 1.0
        if prev < value:
            color = 0.0
        if prev > value:
            color = 2.0
        self.lines.color[0] = color
