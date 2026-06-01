#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "RenkoLevel",
]


class RenkoLevel(Indicator):
    """Fixed-brick Renko level tracker emitting upper/lower levels and color."""

    lines = ("upper", "lower", "color_idx")
    params = (
        ("size_of_block", 30),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Precompute the brick price step and epsilon, set minimum period."""
        self.step_price = self.p.size_of_block * self.p.point_size
        self.eps = self.p.point_size * 0.1
        self.addminperiod(1)

    def _levels(self, price):
        """Round a price to its enclosing Renko brick levels.

        Args:
            price: The price to snap to the brick grid.

        Returns:
            A tuple ``(price_ceil, price_round, price_floor)`` of brick levels.
        """
        step = self.step_price
        price_round = round(price / step) * step
        price_ceil = math.ceil((price_round + step / 2.0) / step) * step
        price_floor = math.floor((price_round - step / 2.0) / step) * step
        return price_ceil, price_round, price_floor

    def next(self):
        """Advance the Renko brick levels for the current bar's close."""
        close_price = float(self.data.close[0])
        if (
            len(self) == 1
            or not math.isfinite(float(self.lines.upper[-1]))
            or not math.isfinite(float(self.lines.lower[-1]))
        ):
            price_ceil, price_round, price_floor = self._levels(close_price)
            self.lines.upper[0] = price_round
            self.lines.lower[0] = price_floor
            self.lines.color_idx[0] = 0.0
            return
        prev_up = float(self.lines.upper[-1])
        prev_down = float(self.lines.lower[-1])
        prev_color = (
            float(self.lines.color_idx[-1])
            if math.isfinite(float(self.lines.color_idx[-1]))
            else 0.0
        )
        price_ceil, price_round, price_floor = self._levels(close_price)
        upper = prev_up
        lower = prev_down
        color = prev_color
        if prev_down <= close_price <= prev_up:
            pass
        elif close_price < prev_down:
            if abs(price_round - prev_down) > self.eps:
                upper = price_ceil
                lower = price_round
                color = 1.0
        elif close_price > prev_up:
            if abs(price_round - prev_up) > self.eps:
                lower = price_floor
                upper = price_round
                color = 0.0
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        self.lines.color_idx[0] = color
