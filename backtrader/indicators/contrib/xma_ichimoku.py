#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
from collections import deque
from itertools import islice

from .. import Indicator

__all__ = [
    "XmaIchimoku",
    "TwoXmaIchimokuOscillator",
]

# A rolling sum is exact only when every intermediate addition is exact.
# Integer windows with total absolute magnitude at most 2**53 satisfy that
# condition for binary64. All other windows retain the original sum order.
_ROLLING_SUM_MIN_PERIOD = 128
_EXACT_INTEGER_LIMIT = 1 << 53


class XmaIchimoku(Indicator):
    """Calculate a smoothed midpoint of selected high/low ranges."""

    lines = ("value",)

    params = (
        ("up_period", 6),
        ("dn_period", 6),
        ("up_mode", "HIGH"),
        ("dn_mode", "LOW"),
        ("xma_method", "SMA"),
        ("x_length", 25),
        ("x_phase", 15),
        ("price_shift", 0.0),
    )

    def __init__(self):
        """Initialize Ichimoku-like windows and smoothing helpers."""
        self.addminperiod(
            max(int(self.p.up_period), int(self.p.dn_period)) + int(self.p.x_length) + 5
        )
        self._raw_buf = deque(maxlen=max(1, int(self.p.x_length)))
        self._raw_seen_count = 0
        self._smooth_prev = None
        self._reset_rolling_state()
        self._last_evicted = None
        self._last_had_evicted = False

    def _reset_rolling_state(self):
        """Invalidate cached O(1) rolling SMA sum state."""
        self._rolling_integer_sum = 0
        self._rolling_absolute_sum = 0
        self._rolling_inexact_count = 0
        self._rolling_period = None
        self._rolling_seen_count = -1
        self._rolling_tail_value = None
        self._rolling_tail_count = 0
        self._rolling_uniform_total = None

    def _adjust_rolling_integer(self, value, direction):
        """Track only integers whose value can participate in the exact fast path."""
        if (
            type(value) is float
            and value.is_integer()
            and -_EXACT_INTEGER_LIMIT <= value <= _EXACT_INTEGER_LIMIT
        ):
            integer = int(value)
            self._rolling_integer_sum += direction * integer
            self._rolling_absolute_sum += direction * (
                integer if integer >= 0 else -integer
            )
        else:
            self._rolling_inexact_count += direction

    def _sma_rolling_total(self, raw_value, period):
        """Reuse a proven exact sum or a sum of unchanged ordered inputs."""
        if (self._rolling_period == period
                and self._rolling_seen_count == self._raw_seen_count - 1
                and self._last_had_evicted):
            if (self._rolling_tail_count == period
                    and raw_value == self._rolling_tail_value
                    and self._rolling_uniform_total is not None):
                # The complete ordered input is unchanged, even for floats
                # whose additions are not exact (for example 0.1).
                self._rolling_seen_count = self._raw_seen_count
                return self._rolling_uniform_total
            evicted = self._last_evicted
            if raw_value != evicted or raw_value != raw_value or evicted != evicted:
                self._adjust_rolling_integer(evicted, -1)
                self._adjust_rolling_integer(raw_value, 1)
            if raw_value == self._rolling_tail_value:
                self._rolling_tail_count = min(period, self._rolling_tail_count + 1)
            else:
                self._rolling_tail_value = raw_value
                self._rolling_tail_count = 1 if raw_value == raw_value else 0
            self._rolling_uniform_total = None
        else:
            self._reset_rolling_state()
            for item in self._raw_buf:
                self._adjust_rolling_integer(item, 1)
            self._rolling_tail_value = raw_value
            for item in reversed(self._raw_buf):
                if item != raw_value:
                    break
                self._rolling_tail_count += 1
        self._rolling_period = period
        self._rolling_seen_count = self._raw_seen_count
        if not self._rolling_inexact_count and self._rolling_absolute_sum <= _EXACT_INTEGER_LIMIT:
            total = float(self._rolling_integer_sum)
        else:
            total = sum(self._raw_buf)
        if self._rolling_tail_count == period:
            self._rolling_uniform_total = total
        return total

    def _series_value(self, mode, ago):
        mode = str(mode).upper()
        if mode == "OPEN":
            return float(self.data.open[ago])
        if mode == "LOW":
            return float(self.data.low[ago])
        if mode == "HIGH":
            return float(self.data.high[ago])
        return float(self.data.close[ago])

    def _smooth_value(self, raw_value):
        method = str(self.p.xma_method).upper()
        if method in ("MODE_SMA_", "SMA"):
            period = max(1, int(self.p.x_length))
            raw_buf = self._raw_buf
            buf_maxlen = raw_buf.maxlen
            if period > buf_maxlen:
                raise ValueError(
                    "x_length=%d exceeds retained SMA window capacity %d"
                    % (period, buf_maxlen)
                )
            buf_len = len(raw_buf)
            if buf_len < period:
                return raw_value
            start = buf_len - period
            if (
                start == 0
                and period >= _ROLLING_SUM_MIN_PERIOD
                and period == buf_maxlen
            ):
                return self._sma_rolling_total(raw_value, period) / float(period)
            window = raw_buf if start == 0 else islice(raw_buf, start, None)
            return sum(window) / float(period)

        length = max(1, int(self.p.x_length))
        phase = max(-100, min(100, int(self.p.x_phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if self._smooth_prev is None or not math.isfinite(self._smooth_prev):
            smooth = raw_value
        else:
            smooth = self._smooth_prev + alpha * (raw_value - self._smooth_prev)
        self._smooth_prev = smooth
        return smooth

    def next(self):
        """Compute smoothed range midpoint for each bar."""
        up_period = int(self.p.up_period)
        dn_period = int(self.p.dn_period)
        if len(self.data) < max(up_period, dn_period):
            self.lines.value[0] = 0.0
            return

        highs = [self._series_value(self.p.up_mode, -i) for i in range(up_period)]
        lows = [self._series_value(self.p.dn_mode, -i) for i in range(dn_period)]
        ish_up = max(highs)
        ish_dn = min(lows)
        raw_value = (
            float("nan")
            if any(type(value) is float and value != value for value in highs + lows)
            else (ish_up + ish_dn) / 2.0
        )
        method = str(self.p.xma_method).upper()
        period = max(1, int(self.p.x_length))
        if method in ("MODE_SMA_", "SMA") and period > self._raw_buf.maxlen:
            capacity = self._raw_buf.maxlen
            if self._raw_seen_count > capacity:
                raise ValueError(
                    "x_length=%d exceeds retained SMA window capacity %d after "
                    "older raw values were discarded"
                    % (period, capacity)
                )
            self._raw_buf = deque(self._raw_buf, maxlen=period)
            self._reset_rolling_state()
        if len(self._raw_buf) == self._raw_buf.maxlen:
            self._last_evicted = self._raw_buf[0]
            self._last_had_evicted = True
        else:
            self._last_evicted = None
            self._last_had_evicted = False
        self._raw_buf.append(raw_value)
        self._raw_seen_count += 1
        smooth = self._smooth_value(raw_value) + float(self.p.price_shift)
        self.lines.value[0] = smooth


class TwoXmaIchimokuOscillator(Indicator):
    """Combine two XMA windows into oscillator value and color channels."""

    lines = (
        "line",
        "color",
    )

    params = (
        ("up_period1", 6),
        ("dn_period1", 6),
        ("up_period2", 9),
        ("dn_period2", 9),
        ("up_mode1", "HIGH"),
        ("dn_mode1", "LOW"),
        ("up_mode2", "HIGH"),
        ("dn_mode2", "LOW"),
        ("xma1_method", "SMA"),
        ("xma2_method", "SMA"),
        ("x_length1", 25),
        ("x_length2", 80),
        ("x_phase", 15),
        ("point", 0.01),
    )

    def __init__(self):
        """Create two :class:`XmaIchimoku` instances and reset color state."""
        self.xma1 = XmaIchimoku(
            self.data,
            up_period=self.p.up_period1,
            dn_period=self.p.dn_period1,
            up_mode=self.p.up_mode1,
            dn_mode=self.p.dn_mode1,
            xma_method=self.p.xma1_method,
            x_length=self.p.x_length1,
            x_phase=self.p.x_phase,
        )
        self.xma2 = XmaIchimoku(
            self.data,
            up_period=self.p.up_period2,
            dn_period=self.p.dn_period2,
            up_mode=self.p.up_mode2,
            dn_mode=self.p.dn_mode2,
            xma_method=self.p.xma2_method,
            x_length=self.p.x_length2,
            x_phase=self.p.x_phase,
        )
        self._prev_color = 2.0

    def next(self):
        """Update oscillator value and derived color trend state."""
        point = float(self.p.point) if float(self.p.point) != 0 else 1.0
        line_value = (float(self.xma1[0]) - float(self.xma2[0])) / point
        self.lines.line[0] = line_value

        current_length = len(self)
        if current_length < 2:
            self.lines.color[0] = 2.0
            self._prev_color = 2.0
            return

        prev_line = float(self.lines.line[-1])
        if line_value != line_value or (prev_line != prev_line and current_length > self._minperiod):
            self.lines.color[0] = float("nan")
            return
        color = self._prev_color
        if line_value >= 0:
            if line_value > prev_line:
                color = 0.0
            elif line_value < prev_line:
                color = 1.0
        else:
            if line_value < prev_line:
                color = 4.0
            elif line_value > prev_line:
                color = 3.0
        self.lines.color[0] = color
        self._prev_color = color
