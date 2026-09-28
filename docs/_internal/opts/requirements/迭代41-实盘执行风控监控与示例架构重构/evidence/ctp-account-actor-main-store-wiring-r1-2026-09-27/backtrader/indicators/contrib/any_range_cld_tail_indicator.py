#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from backtrader.utils.dateintern import num2date

from .. import Indicator

__all__ = [
    "AnyRangeCldTailIndicator",
]


class AnyRangeCldTailIndicator(Indicator):
    """Compute a session-based daily channel and color-state trend signal."""

    lines = ("color_state", "upper", "lower")
    params = (
        ("time1", "02:00"),
        ("time2", "07:00"),
    )

    def __init__(self):
        """Initialize session boundaries and window tracking state."""
        self._time1 = self._parse_hhmm(self.p.time1)
        self._time2 = self._parse_hhmm(self.p.time2)
        self._window_start = min(self._time1, self._time2)
        self._window_end = max(self._time1, self._time2)
        self._current_day = None
        self._range_high = None
        self._range_low = None
        self._channel_high = None
        self._channel_low = None
        self._window_finalized = False
        self.addminperiod(2)

    @staticmethod
    def _parse_hhmm(value):
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)

    def next(self):
        """Update channel bounds and emit color state for the current bar."""
        dt = num2date(self.data.datetime[0])
        day = dt.date()
        minute = dt.hour * 60 + dt.minute
        if self._current_day != day:
            self._current_day = day
            self._range_high = None
            self._range_low = None
            self._channel_high = None
            self._channel_low = None
            self._window_finalized = False
        in_window = self._window_start < minute <= self._window_end
        if in_window:
            high = float(self.data.high[0])
            low = float(self.data.low[0])
            self._range_high = high if self._range_high is None else max(self._range_high, high)
            self._range_low = low if self._range_low is None else min(self._range_low, low)
        elif (
            minute > self._window_end
            and not self._window_finalized
            and self._range_high is not None
            and self._range_low is not None
        ):
            self._channel_high = self._range_high
            self._channel_low = self._range_low
            self._window_finalized = True
        color = 4.0
        if self._channel_high is not None and self._channel_low is not None and not in_window:
            close = float(self.data.close[0])
            open_ = float(self.data.open[0])
            if close > self._channel_high:
                color = 3.0 if close >= open_ else 2.0
            elif close < self._channel_low:
                color = 0.0 if close <= open_ else 1.0
        self.lines.color_state[0] = color
        self.lines.upper[0] = self._channel_high if self._channel_high is not None else float("nan")
        self.lines.lower[0] = self._channel_low if self._channel_low is not None else float("nan")
