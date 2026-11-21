#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

_NAN_SIGNATURE_VALUE = object()

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
        self._last_calculation_signature = None
        self._last_calculation_bar_len = None
        self._calculation_bar_start_swing = True
        self.addminperiod(int(self.p.lines_break) + 2)

    def prenext(self):
        """Seed partial values once per changed source window during warmup."""
        if self._uses_builtin_next():
            self.next()

    def preonce(self, start, end):
        """Mirror ``prenext`` over the warmup range in runonce mode."""
        if not self._uses_builtin_next():
            return
        for _ in range(start, end):
            self.forward()
            self.next()

    def _uses_builtin_next(self):
        """Avoid invoking user overrides before their established lifecycle."""
        if getattr(type(self), "next", None) is not ThreeLineBreakIndicator.next:
            return False

        try:
            instance_next = object.__getattribute__(self, "__dict__").get("next")
        except AttributeError:
            instance_next = None
        return instance_next is None

    @staticmethod
    def _signature_value(value):
        """Normalize NaN so an unchanged missing sample has a stable key."""
        return _NAN_SIGNATURE_VALUE if value != value else value

    def _calculation_inputs(self, period):
        """Read the current bar and its extrema in one lookback pass."""
        length = len(self.data)
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        hh = ll = None
        if length > period:
            if period <= 0:
                # Preserve the pre-existing empty-window ValueError.
                max(float(self.data.high[-i]) for i in range(1, period + 1))
            for ago in range(1, period + 1):
                previous_high = float(self.data.high[-ago])
                previous_low = float(self.data.low[-ago])
                if ago == 1:
                    hh = previous_high
                    ll = previous_low
                else:
                    if previous_high > hh:
                        hh = previous_high
                    if previous_low < ll:
                        ll = previous_low

        # The rolling extrema are the only historical inputs to this bar's
        # decision. Including them detects replay corrections without storing
        # or rescanning the full lookback in a second signature pass.
        signature = (
            length,
            period,
            self._signature_value(high),
            self._signature_value(low),
            self._signature_value(hh),
            self._signature_value(ll),
        )
        return signature, length, high, low, hh, ll

    def next(self):
        """Advance the Three Line Break trend and output the current trend lines.

        Returns:
            None.
        """
        lines_break = int(self.p.lines_break)
        signature, length, high, low, hh, ll = self._calculation_inputs(lines_break)
        if signature == self._last_calculation_signature:
            return

        new_bar = length != self._last_calculation_bar_len
        base_swing = self._swing if new_bar else self._calculation_bar_start_swing
        swing = base_swing

        if length > lines_break:
            if swing and low < ll:
                swing = False
            if (not swing) and high > hh:
                swing = True

        output_lines = (
            self.lines.line_high,
            self.lines.line_low,
            self.lines.trend,
        )
        previous_outputs = tuple(line[0] for line in output_lines)
        output_values = (high, low, 0.0 if swing else 1.0)
        try:
            for line, value in zip(output_lines, output_values):
                line[0] = value
        except BaseException:
            # A later line assignment may fail after an earlier output was
            # already written. Invalidate the cache so a retry cannot mistake
            # that partial output for the last successful calculation.
            self._last_calculation_signature = None
            for line, value in zip(output_lines, previous_outputs):
                try:
                    line[0] = value
                except BaseException:
                    # Keep the calculation failure authoritative. A later
                    # retry will still run because the signature was cleared.
                    pass
            raise

        # Commit state only after every output write succeeded. On replay, a
        # changed version of the same bar is recalculated from its prior state.
        if new_bar:
            self._calculation_bar_start_swing = base_swing
            self._last_calculation_bar_len = length
        self._swing = swing
        self._last_calculation_signature = signature
