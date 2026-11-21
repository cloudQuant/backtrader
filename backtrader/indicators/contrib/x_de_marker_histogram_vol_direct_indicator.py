#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
from collections import deque

from .. import Indicator

__all__ = [
    "XDeMarkerHistogramVolDirectIndicator",
]


class XDeMarkerHistogramVolDirectIndicator(Indicator):
    """Indicator that calculates DeMarker histogram zone and direct trend color."""

    lines = ("value", "color_zone", "color_direct", "upper2", "upper1", "lower1", "lower2")
    params = (
        ("de_marker_period", 14),
        ("volume_type", "tick"),
        ("high_level2", 20),
        ("high_level1", 15),
        ("low_level1", -15),
        ("low_level2", -20),
        ("ma_method", "MODE_SMA_"),
        ("ma_length", 12),
        ("ma_phase", 15),
    )

    def __init__(self):
        """Initialize de_marker state deques and warm-up period."""
        de_marker_period = max(int(self.p.de_marker_period), 1)
        ma_length = max(int(self.p.ma_length), 1)
        self._demax = deque(maxlen=de_marker_period)
        self._demin = deque(maxlen=de_marker_period)
        self._raw = deque(maxlen=ma_length)
        self._vol = deque(maxlen=ma_length)
        self._sample_length = None
        self._sample_before = None
        self._sample_after = None
        self._last_high = None
        self._last_low = None
        self.addminperiod(de_marker_period + ma_length)

    @staticmethod
    def _nan():
        return float("nan")

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _bar_volume(self):
        volume_type = str(self.p.volume_type).lower()
        if volume_type in {"real", "volume_real", "volume"}:
            raw = float(self.data.openinterest[0])
            if math.isfinite(raw) and raw > 0:
                return raw
        raw = float(self.data.volume[0])
        return raw if math.isfinite(raw) else 0.0

    def _state_snapshot(self):
        """Capture the bounded rolling state before the current data bar."""
        return (
            tuple(
                tuple(values)
                for values in (self._demax, self._demin, self._raw, self._vol)
            ),
            self._last_high,
            self._last_low,
        )

    def _restore_state(self, snapshot):
        """Restore rolling state after a revised bar or a failed calculation."""
        values_snapshot, self._last_high, self._last_low = snapshot
        for values, saved in zip(
            (self._demax, self._demin, self._raw, self._vol), values_snapshot
        ):
            values.clear()
            values.extend(saved)

    def prenext(self):
        """Prime rolling state before the first complete output window."""
        self._sample(publish=False)

    def next(self):
        """Compute the current DeMarker value and replace replay revisions."""
        self._sample(publish=True)

    def _sample(self, publish):
        """Advance one input bar, transactionally replacing same-length updates.

        All derived values are computed before mutating output lines. If an
        exception occurs while computing or writing any output line, rolling
        state is restored to the last committed state and any already-written
        current-bar output slots are rolled back on a best-effort basis. If
        restoring an output slot itself raises, the original exception remains
        authoritative and partial current-bar output may persist until a
        subsequent same-bar revision/retry overwrites it.
        """
        sample_length = len(self.data)
        is_revision = sample_length == self._sample_length
        if is_revision:
            before = self._sample_before
            failure_state = self._sample_after
            self._restore_state(before)
        else:
            before = self._state_snapshot()
            failure_state = before

        output_lines = (
            self.lines.value,
            self.lines.color_zone,
            self.lines.color_direct,
            self.lines.upper2,
            self.lines.upper1,
            self.lines.lower1,
            self.lines.lower2,
        )
        previous_outputs = None
        written = 0
        try:
            outputs = self._compute_sample(publish)
            previous_outputs = tuple(line[0] for line in output_lines)
            for line, new_value in zip(output_lines, outputs):
                written += 1
                line[0] = new_value
        except BaseException:
            # A failed revision must leave the most recent successful version
            # of this bar in place. A failed new bar rolls back to the prior
            # bar, so a retry can safely apply it later.
            self._restore_state(failure_state)
            if previous_outputs is not None and written:
                for line, old_value in zip(
                    output_lines[:written], previous_outputs[:written]
                ):
                    try:
                        line[0] = old_value
                    except BaseException:
                        # Best-effort output rollback: keep the original
                        # failure authoritative if restoring a line slot fails.
                        pass
            raise

        self._sample_length = sample_length
        self._sample_before = before
        self._sample_after = self._state_snapshot()

    def _compute_sample(self, publish):
        """Compute this bar from the bounded history before it."""
        high_now = float(self.data.high[0])
        low_now = float(self.data.low[0])
        if len(self.data) < 2:
            self._last_high = high_now
            self._last_low = low_now
            nan_val = self._nan()
            return (nan_val,) * 7

        high_prev = (
            self._last_high
            if self._last_high is not None
            else float(self.data.high[-1])
        )
        low_prev = (
            self._last_low if self._last_low is not None else float(self.data.low[-1])
        )
        vol_now = self._bar_volume()

        self._demax.append(max(high_now - high_prev, 0.0))
        self._demin.append(max(low_prev - low_now, 0.0))

        value = self._nan()
        color_zone = self._nan()
        color_direct = (
            self.lines.color_direct[-1]
            if len(self) > 1 and self._finite(self.lines.color_direct[-1])
            else self._nan()
        )
        upper2 = self._nan()
        upper1 = self._nan()
        lower1 = self._nan()
        lower2 = self._nan()

        if len(self._demax) >= int(self.p.de_marker_period) and len(self._demin) >= int(
            self.p.de_marker_period
        ):
            sum_max = sum(self._demax)
            sum_min = sum(self._demin)
            denom = sum_max + sum_min
            demarker = (
                self._nan() if math.isnan(denom) else (sum_max / denom if denom > 0 else 0.5)
            )
            raw = ((demarker * 100.0) - 50.0) * vol_now
            self._raw.append(raw)
            self._vol.append(vol_now)

            if len(self._raw) >= int(self.p.ma_length) and len(self._vol) >= int(self.p.ma_length):
                if str(self.p.ma_method).upper() != "MODE_SMA_":
                    raise ValueError(
                        "Current backtrader migration only supports MODE_SMA_ for XDeMarker_Histogram_Vol_Direct"
                    )
                value = sum(self._raw) / len(self._raw)
                avg_vol = sum(self._vol) / len(self._vol)
                upper2 = self.p.high_level2 * avg_vol
                upper1 = self.p.high_level1 * avg_vol
                lower1 = self.p.low_level1 * avg_vol
                lower2 = self.p.low_level2 * avg_vol
                if value > upper2:
                    color_zone = 0.0
                elif value > upper1:
                    color_zone = 1.0
                elif value < lower2:
                    color_zone = 4.0
                elif value < lower1:
                    color_zone = 3.0
                else:
                    color_zone = 2.0

                prev_value = (
                    self.lines.value[-1]
                    if len(self) > 1 and self._finite(self.lines.value[-1])
                    else self._nan()
                )
                prev_direct = (
                    self.lines.color_direct[-1]
                    if len(self) > 1 and self._finite(self.lines.color_direct[-1])
                    else 1.0
                )
                if not self._finite(prev_value):
                    color_direct = prev_direct
                elif value > prev_value:
                    color_direct = 0.0
                elif value < prev_value:
                    color_direct = 1.0
                else:
                    color_direct = prev_direct
                if math.isnan(value):
                    color_zone = self._nan()
                    color_direct = self._nan()

        self._last_high = high_now
        self._last_low = low_now

        if publish:
            return (
                value,
                color_zone,
                color_direct,
                upper2,
                upper1,
                lower1,
                lower2,
            )
        nan_val = self._nan()
        return (nan_val,) * 7
