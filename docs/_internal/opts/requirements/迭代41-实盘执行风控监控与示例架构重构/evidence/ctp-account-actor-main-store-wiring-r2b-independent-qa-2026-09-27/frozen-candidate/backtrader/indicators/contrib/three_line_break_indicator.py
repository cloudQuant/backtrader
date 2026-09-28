#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ThreeLineBreakIndicator",
]


class ThreeLineBreakIndicator(Indicator):
    """Three Line Break indicator used as a higher-timeframe trend signal source.

    The indicator tracks a directional swing state based on the last
    ``lines_break`` bars. A bearish-to-bullish and bullish-to-bearish shift
    is confirmed by breakouts above the recent highs or below the recent lows.

    Output lines:
    - ``trend``: ``1.0`` for bullish trend, ``0.0`` for bearish trend.
    - ``line_high``: current bar high value.
    - ``line_low``: current bar low value.
    """

    lines = ("trend", "line_high", "line_low")
    params = (("lines_break", 3),)

    def __init__(self):
        """Initialize internal swing state and minimum period.

        Args:
            lines_break: Number of bars used for the breakout envelope.
        """
        self._swing = True
        self._initialized = False
        self.addminperiod(int(self.p.lines_break) + 2)

    def next(self):
        """Advance the Three Line Break trend and output the current trend lines.

        Returns:
            None.
        """
        lines_break = int(self.p.lines_break)
        if len(self.data) <= lines_break:
            self.lines.trend[0] = 0.0 if self._swing else 1.0
            self.lines.line_high[0] = float(self.data.high[0])
            self.lines.line_low[0] = float(self.data.low[0])
            return

        hh = max(float(self.data.high[-i]) for i in range(1, lines_break + 1))
        ll = min(float(self.data.low[-i]) for i in range(1, lines_break + 1))

        if self._swing and float(self.data.low[0]) < ll:
            self._swing = False
        if (not self._swing) and float(self.data.high[0]) > hh:
            self._swing = True

        self.lines.line_high[0] = float(self.data.high[0])
        self.lines.line_low[0] = float(self.data.low[0])
        self.lines.trend[0] = 0.0 if self._swing else 1.0
