#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "XRVIIndicator",
]


class XRVIIndicator(Indicator):
    """Compute a custom XRVI oscillator and its smoothed signal line.

    The indicator relies on candle body delta normalized by range and applies
    configurable moving-average methods to build both XRVI and signal streams.
    """

    lines = (
        "xrvi",
        "signal",
    )
    params = (
        ("rvi_method", "jurx"),
        ("rvi_period", 10),
        ("rvi_phase", 15),
        ("sign_method", "jurx"),
        ("sign_period", 5),
        ("sign_phase", 15),
    )

    def __init__(self):
        """Initialize XRVI indicator with a minimal required lookback length."""
        self.addminperiod(self.p.rvi_period + self.p.sign_period + 3)

    def _raw_rvi_at(self, i, open_array, high_array, low_array, close_array):
        denom = float(high_array[i]) - float(low_array[i])
        return (float(close_array[i]) - float(open_array[i])) / denom if denom else 0.0

    def _window_ma(self, values, method, period, previous=None):
        if not values:
            return float("nan")
        mode = str(method).lower()
        value = float(values[-1])
        if mode in {"ema", "mode_ema"}:
            if previous is None or previous != previous:
                return value
            alpha = 2.0 / (period + 1.0)
            return previous + alpha * (value - previous)
        if mode in {"smma", "mode_smma"}:
            if previous is None or previous != previous:
                return value
            return ((period - 1.0) * previous + value) / period
        if mode in {"sma", "mode_sma"}:
            return sum(values) / len(values)
        weights = list(range(1, len(values) + 1))
        return sum(v * w for v, w in zip(values, weights)) / sum(weights)

    def _raw_rvi_ago(self, ago):
        denom = float(self.data.high[-ago]) - float(self.data.low[-ago])
        return (
            (float(self.data.close[-ago]) - float(self.data.open[-ago])) / denom if denom else 0.0
        )

    def next(self):
        """Advance XRVI and signal values for the current bar."""
        rvi_period = max(1, int(self.p.rvi_period))
        sign_period = max(1, int(self.p.sign_period))
        raw_window = [
            self._raw_rvi_ago(ago) for ago in range(min(len(self), rvi_period) - 1, -1, -1)
        ]
        prev_xrvi = float(self.lines.xrvi[-1]) if len(self) > 1 else None
        xrvi = self._window_ma(raw_window, self.p.rvi_method, rvi_period, prev_xrvi)
        self.lines.xrvi[0] = xrvi
        signal_values = []
        for ago in range(min(len(self), sign_period) - 1, 0, -1):
            value = float(self.lines.xrvi[-ago])
            if value == value:
                signal_values.append(value)
        signal_values.append(xrvi)
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else None
        self.lines.signal[0] = self._window_ma(
            signal_values, self.p.sign_method, sign_period, prev_signal
        )

    def once(self, start, end):
        """Vectorized XRVI and signal computation used by Backtrader runonce mode.

        Args:
            start: First bar index to fill into line arrays.
            end: Exclusive bar index end bound for computed slices.
        """
        open_array = self.data.open.array
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        xrvi_line = self.lines.xrvi.array
        signal_line = self.lines.signal.array
        for line in (xrvi_line, signal_line):
            while len(line) < end:
                line.append(float("nan"))

        rvi_period = max(1, int(self.p.rvi_period))
        sign_period = max(1, int(self.p.sign_period))
        prev_xrvi = None
        prev_signal = None
        actual_end = min(end, len(open_array), len(high_array), len(low_array), len(close_array))
        raw_values = [
            self._raw_rvi_at(i, open_array, high_array, low_array, close_array)
            for i in range(actual_end)
        ]
        xrvi_values = []
        for i in range(actual_end):
            raw_start = max(0, i - rvi_period + 1)
            xrvi = self._window_ma(
                raw_values[raw_start : i + 1], self.p.rvi_method, rvi_period, prev_xrvi
            )
            xrvi_values.append(xrvi)
            if i >= start:
                xrvi_line[i] = xrvi
            prev_xrvi = xrvi
            signal_start = max(0, i - sign_period + 1)
            signal_values = xrvi_values[signal_start : i + 1]
            signal = self._window_ma(signal_values, self.p.sign_method, sign_period, prev_signal)
            if i >= start:
                signal_line[i] = signal
            prev_signal = signal
