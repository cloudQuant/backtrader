#!/usr/bin/env python
"""Fractal Indicator Module - Fractal pattern detection.

This module provides the Fractal indicator for identifying fractal
patterns in price data. Fractals are reversal patterns that indicate
potential trend changes.

Classes:
    Fractal: Identifies bullish and bearish fractal patterns.

References:
    http://www.investopedia.com/articles/trading/06/fractals.asp

Example:
    >>> from backtrader.utils import Fractal
    >>> fractal = Fractal()
    >>> cerebro.addindicator(fractal)
"""
from ..indicators import PeriodN

__all__ = ["Fractal"]


class Fractal(PeriodN):
    """Fractal pattern indicator.

    Identifies bullish and bearish fractal patterns which indicate
    potential reversal points in price trends.

    A bearish fractal occurs when there's a pattern with the highest
    high in the middle and two lower highs on each side.

    A bullish fractal occurs when there's a pattern with the lowest
    low in the middle and two higher lows on each side.

    Params:
        period: Number of bars to check (default: 5).
        bardist: Distance to max/min in percentage (default: 0.015).
        shift_to_potential_fractal: Index of potential fractal (default: 2).

    Lines:
        fractal_bearish: Bearish fractal levels.
        fractal_bullish: Bullish fractal levels.
    """

    lines = ("fractal_bearish", "fractal_bullish")

    plotinfo = dict(subplot=False, plotlinelabels=False, plot=True)

    plotlines = dict(
        fractal_bearish=dict(
            marker="^", markersize=4.0, color="lightblue", fillstyle="full", ls=""
        ),
        fractal_bullish=dict(
            marker="v", markersize=4.0, color="lightblue", fillstyle="full", ls=""
        ),
    )
    params = (
        ("period", 5),
        ("bardist", 0.015),  # distance to max/min in absolute perc
        ("shift_to_potential_fractal", 2),
    )

    def next(self):
        # A bearish turning point occurs when there is a pattern with the
        # highest high in the middle and two lower highs on each side. [Ref 1]

        last_five_highs = self.data.high.get(size=self.p.period)
        max_val = max(last_five_highs)
        max_idx = last_five_highs.index(max_val)

        if max_idx == self.p.shift_to_potential_fractal:
            self.lines.fractal_bearish[-2] = max_val * (1 + self.p.bardist)

        # A bullish turning point occurs when there is a pattern with the
        # lowest low in the middle and two higher lowers on each side. [Ref 1]
        last_five_lows = self.data.low.get(size=self.p.period)
        min_val = min(last_five_lows)
        min_idx = last_five_lows.index(min_val)

        if min_idx == self.p.shift_to_potential_fractal:
            self.l.fractal_bullish[-2] = min_val * (1 - self.p.bardist)
