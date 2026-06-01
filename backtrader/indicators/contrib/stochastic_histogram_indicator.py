#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "StochasticHistogramIndicator",
]


class StochasticHistogramIndicator(Indicator):
    """Stochastic-based indicator with a smoothed main line, signal line, and color state.

    The indicator outputs:
    - ``main``: smoothed %K values.
    - ``signal``: smoothed trigger line derived from main.
    - ``hist_base``: fixed base reference line (50.0).
    - ``color_state``: 0 for overbought, 1 for neutral, 2 for oversold.
    """

    lines = ("main", "signal", "hist_base", "color_state")
    params = (
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
        ("ma_method", "sma"),
        ("high_level", 60),
        ("low_level", 40),
    )

    def __init__(self):
        """Set the minimum required bars from K, slowing, and D periods."""
        self.addminperiod(int(self.p.k_period) + int(self.p.slowing) + int(self.p.d_period) + 2)

    def _fast_k_at(self, i, high_array, low_array, close_array):
        period = max(1, int(self.p.k_period))
        if i - period + 1 < 0:
            return float("nan")
        lowest = min(float(low_array[idx]) for idx in range(i - period + 1, i + 1))
        highest = max(float(high_array[idx]) for idx in range(i - period + 1, i + 1))
        denom = highest - lowest
        return 100.0 * (float(close_array[i]) - lowest) / denom if denom else 50.0

    def _ma_value(self, values, period, previous=None):
        if not values:
            return float("nan")
        mode = str(self.p.ma_method).strip().lower()
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
        if mode in {"lwma", "wma", "mode_lwma"}:
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        return sum(values) / len(values)

    def next(self):
        """Compute indicator values for one new bar in Backtrader streaming mode."""
        k_period = max(1, int(self.p.k_period))
        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))
        fast_values = []
        for ago in range(slowing - 1, -1, -1):
            if len(self.data) <= ago + k_period - 1:
                return
            low_values = [float(self.data.low[-ago - shift]) for shift in range(k_period)]
            high_values = [float(self.data.high[-ago - shift]) for shift in range(k_period)]
            lowest = min(low_values)
            highest = max(high_values)
            denom = highest - lowest
            fast_values.append(
                100.0 * (float(self.data.close[-ago]) - lowest) / denom if denom else 50.0
            )
        prev_main = float(self.lines.main[-1]) if len(self) > 1 else None
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else None
        main = self._ma_value(fast_values, slowing, prev_main)
        self.lines.main[0] = main
        signal_values = [
            float(self.lines.main[-ago]) for ago in range(min(len(self), d_period) - 1, 0, -1)
        ]
        signal_values.append(main)
        self.lines.signal[0] = self._ma_value(signal_values, d_period, prev_signal)
        color = 1.0
        if main > float(self.p.high_level):
            color = 0.0
        elif main < float(self.p.low_level):
            color = 2.0
        self.lines.color_state[0] = color
        self.lines.hist_base[0] = 50.0

    def once(self, start, end):
        """Compute indicator arrays for run-once mode from ``start`` to ``end`` indices."""
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        main_line = self.lines.main.array
        signal_line = self.lines.signal.array
        hist_base_line = self.lines.hist_base.array
        color_state_line = self.lines.color_state.array
        for line in (main_line, signal_line, hist_base_line, color_state_line):
            while len(line) < end:
                line.append(float("nan"))

        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))
        actual_end = min(end, len(high_array), len(low_array), len(close_array))
        fast_values = [
            self._fast_k_at(i, high_array, low_array, close_array) for i in range(actual_end)
        ]
        main_values = []
        signal_values_all = []
        prev_main = None
        prev_signal = None
        for i in range(actual_end):
            main_start = max(0, i - slowing + 1)
            main = self._ma_value(fast_values[main_start : i + 1], slowing, prev_main)
            main_values.append(main)
            prev_main = main
            signal_start = max(0, i - d_period + 1)
            signal = self._ma_value(main_values[signal_start : i + 1], d_period, prev_signal)
            signal_values_all.append(signal)
            prev_signal = signal
            if i < start:
                continue
            main_line[i] = main
            signal_line[i] = signal_values_all[i]
            color = 1.0
            if main > float(self.p.high_level):
                color = 0.0
            elif main < float(self.p.low_level):
                color = 2.0
            color_state_line[i] = color
            hist_base_line[i] = 50.0
