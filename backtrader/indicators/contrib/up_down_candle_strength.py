#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "UpDownCandleStrength",
]


class UpDownCandleStrength(Indicator):
    """Up Down Candle Strength Indicator.

    This indicator calculates the strength of price movement by measuring
    the ratio of up candles to down candles over a specified period.

    The strength value ranges from 0.0 (all down candles) to 1.0 (all up candles),
    with 0.5 indicating an equal number of up and down candles.

    Attributes:
        lines.strength: The calculated strength ratio (0.0 to 1.0).
        params.period: The number of periods to analyze for candle strength.

    Note:
        A strength value of 0.5 is returned when there are no clear up or down
        candles (i.e., all candles have equal open and close prices).
    """

    lines = ("strength",)
    params = (("period", 20),)

    def __init__(self):
        """Initialize the UpDownCandleStrength indicator.

        Sets the minimum period required for calculation based on the
        configured period parameter.
        """
        self.addminperiod(self.p.period)

    def next(self):
        """Calculate the candle strength ratio for the current bar.

        Counts the number of up candles (close > open) and down candles
        (close < open) over the specified period and calculates the ratio.

        The strength value is calculated as:
            strength = up_count / (up_count + down_count)

        If no candles have clear directional movement (all open == close),
        the strength is set to 0.5 (neutral).
        """
        up_count = 0
        down_count = 0
        for i in range(self.p.period):
            if self.data.close[-i] > self.data.open[-i]:
                up_count += 1
            elif self.data.close[-i] < self.data.open[-i]:
                down_count += 1

        total = up_count + down_count
        if total == 0:
            self.lines.strength[0] = 0.5
        else:
            self.lines.strength[0] = up_count / total
