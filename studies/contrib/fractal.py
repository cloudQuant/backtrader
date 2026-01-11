#!/usr/bin/env python

###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
# (based on backtrader from Daniel Rodriguez)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

"""Fractal Indicator for Backtrader.

This module implements the Fractal indicator, which identifies potential
reversal points in price action. Fractals are patterns that consist of
five consecutive bars, where the middle bar represents either a local
high (bearish fractal) or a local low (bullish fractal).

The indicator is based on the concept developed by Bill Williams and
provides visual signals on price charts to help traders identify
potential turning points in the market.

Reference:
    http://www.investopedia.com/articles/trading/06/fractals.asp
"""

import backtrader as bt

__all__ = ["Fractal"]


class Fractal(bt.ind.PeriodN):
    """Fractal Indicator for identifying potential market reversals.

    The Fractal indicator identifies potential reversal points by looking
    for specific patterns in price action. A bearish fractal occurs when
    there is a pattern with the highest high in the middle and two lower
    highs on each side. A bullish fractal occurs when there is a pattern
    with the lowest low in the middle and two higher lows on each side.

    Attributes:
        lines.fractal_bearish: Line containing bearish fractal values.
            Values are plotted above the high price at fractal points.
        lines.fractal_bullish: Line containing bullish fractal values.
            Values are plotted below the low price at fractal points.
        plotinfo: Dictionary controlling plotting behavior.
            - subplot: False (plots on main price chart)
            - plotlinelabels: False (no line labels)
            - plot: True (enable plotting)
        plotlines: Dictionary controlling line appearance.
            - fractal_bearish: Triangle marker (^), light blue, size 4.0
            - fractal_bullish: Inverted triangle marker (v), light blue, size 4.0
        params:
            period (int): Number of bars to analyze for fractal patterns.
                Default is 5, which looks for standard fractal patterns.
            bardist (float): Distance percentage to offset fractal markers
                from the high/low price. Default is 0.015 (1.5%).
                Positive values place bearish fractals above highs and
                bullish fractals below lows.
            shift_to_potential_fractal (int): Index offset within the period
                where the fractal point should be located. Default is 2,
                which places the fractal at the center of a 5-bar pattern.

    Example:
        ::

            import backtrader as bt

            class MyStrategy(bt.Strategy):
                def __init__(self):
                    self.fractal = bt.indicators.Fractal(self.data)

                def next(self):
                    if self.fractal.fractal_bearish[0] > 0:
                        # Bearish fractal detected - potential reversal downward
                        self.sell()

                    if self.fractal.fractal_bullish[0] > 0:
                        # Bullish fractal detected - potential reversal upward
                        self.buy()
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
        ("bardist", 0.015),  # Distance to max/min in absolute percentage
        ("shift_to_potential_fractal", 2),
    )

    def next(self):
        """Calculate fractal patterns for the current bar.

        This method analyzes the last 'period' bars to identify fractal patterns.
        A bearish fractal is detected when the middle bar has the highest high
        in the pattern. A bullish fractal is detected when the middle bar has
        the lowest low in the pattern.

        The fractal values are written to position [-2] (two bars back) because
        fractals can only be confirmed after the full pattern is complete,
        and we want to mark the center bar of the pattern.

        The method operates by:
        1. Extracting the last 'period' high prices
        2. Finding the maximum value and its index
        3. If the maximum is at the expected position, marking a bearish fractal
        4. Repeating the process for low prices to find bullish fractals

        Side Effects:
            - Writes fractal values to self.lines.fractal_bearish[-2] or
              self.lines.fractal_bullish[-2] when patterns are detected
            - Values are offset by the bardist parameter for visual clarity
        """
        # A bearish turning point occurs when there is a pattern with the
        # highest high in the middle and two lower highs on each side.
        # Reference: http://www.investopedia.com/articles/trading/06/fractals.asp

        last_five_highs = self.data.high.get(size=self.p.period)
        max_val = max(last_five_highs)
        max_idx = last_five_highs.index(max_val)

        if max_idx == self.p.shift_to_potential_fractal:
            self.lines.fractal_bearish[-2] = max_val * (1 + self.p.bardist)

        # A bullish turning point occurs when there is a pattern with the
        # lowest low in the middle and two higher lows on each side.
        # Reference: http://www.investopedia.com/articles/trading/06/fractals.asp
        last_five_lows = self.data.low.get(size=self.p.period)
        min_val = min(last_five_lows)
        min_idx = last_five_lows.index(min_val)

        if min_idx == self.p.shift_to_potential_fractal:
            self.l.fractal_bullish[-2] = min_val * (1 - self.p.bardist)
