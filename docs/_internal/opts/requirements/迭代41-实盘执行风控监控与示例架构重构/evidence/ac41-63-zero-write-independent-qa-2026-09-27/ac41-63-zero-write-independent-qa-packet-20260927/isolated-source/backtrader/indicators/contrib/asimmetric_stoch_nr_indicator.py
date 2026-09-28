#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "AsimmetricStochNRIndicator",
]


class AsimmetricStochNRIndicator(Indicator):
    """Asymmetric stochastic oscillator indicator with dynamic MA smoothing."""

    lines = (
        "stoch",
        "signal",
    )
    params = (
        ("kperiod_short", 5),
        ("kperiod_long", 12),
        ("dmethod", "sma"),
        ("dperiod", 7),
        ("dphase", 15),
        ("slowing", 3),
        ("price_field", "lowhigh"),
        ("sens", 7),
        ("overbought", 80),
        ("oversold", 20),
    )

    def __init__(self):
        """Initialize period state and minimum bar requirements."""
        self._kperiod0 = int(self.p.kperiod_short)
        self._kperiod1 = int(self.p.kperiod_short)
        self.addminperiod(
            max(self.p.kperiod_short, self.p.kperiod_long) + self.p.slowing + self.p.dperiod + 5
        )

    def _stoch_value(self, bar=0):
        max_value = 0.0
        min_value = 0.0
        c_value = 0.0
        for j in range(bar, bar + int(self.p.slowing)):
            if str(self.p.price_field).lower() == "closeclose":
                window_max = max(
                    float(self.data.close[-idx]) for idx in range(j, j + self._kperiod0)
                )
                window_min = min(
                    float(self.data.close[-idx]) for idx in range(j, j + self._kperiod1)
                )
            else:
                window_max = max(
                    float(self.data.high[-idx]) for idx in range(j, j + self._kperiod0)
                )
                window_min = min(float(self.data.low[-idx]) for idx in range(j, j + self._kperiod1))
            max_value += window_max
            min_value += window_min
            c_value += float(self.data.close[-j])
        sens_total = float(self.p.sens) * int(self.p.slowing)
        delta = max_value - min_value
        diff = sens_total - delta
        if diff > 0:
            delta = sens_total
            min_value -= diff / 2.0
        if delta:
            return 100.0 * (c_value - min_value) / delta
        return -2.0

    def next(self):
        """Compute current `stoch` and `signal` values using the active periods."""
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else float("nan")
        self.lines.stoch[0] = self._stoch_value(0)
        values = [
            float(self.lines.stoch[-idx])
            for idx in range(min(len(self), int(self.p.dperiod)) - 1, -1, -1)
        ]
        self.lines.signal[0] = self._ma_window_value(values, str(self.p.dmethod), prev_signal)
        if prev_signal > float(self.p.overbought):
            self._kperiod0 = int(self.p.kperiod_short)
            self._kperiod1 = int(self.p.kperiod_long)
        if prev_signal < float(self.p.oversold):
            self._kperiod0 = int(self.p.kperiod_long)
            self._kperiod1 = int(self.p.kperiod_short)

    def _ma_window_value(self, values, method, previous=None):
        if not values:
            return float("nan")
        period = max(1, int(self.p.dperiod))
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
        if mode in {"lwma", "wma", "mode_lwma", "jjma", "mode_jjma"}:
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        return sum(values) / len(values)

    def _stoch_value_at(self, i, high_array, low_array, close_array, kperiod0, kperiod1):
        max_value = 0.0
        min_value = 0.0
        c_value = 0.0
        slowing = int(self.p.slowing)
        if i - slowing + 1 < 0:
            return float("nan")
        closeclose = str(self.p.price_field).lower() == "closeclose"
        for j in range(slowing):
            bar = i - j
            if bar - max(kperiod0, kperiod1) + 1 < 0:
                return float("nan")
            if closeclose:
                window_max = max(
                    float(close_array[idx]) for idx in range(bar - kperiod0 + 1, bar + 1)
                )
                window_min = min(
                    float(close_array[idx]) for idx in range(bar - kperiod1 + 1, bar + 1)
                )
            else:
                window_max = max(
                    float(high_array[idx]) for idx in range(bar - kperiod0 + 1, bar + 1)
                )
                window_min = min(
                    float(low_array[idx]) for idx in range(bar - kperiod1 + 1, bar + 1)
                )
            max_value += window_max
            min_value += window_min
            c_value += float(close_array[bar])
        sens_total = float(self.p.sens) * slowing
        delta = max_value - min_value
        diff = sens_total - delta
        if diff > 0:
            delta = sens_total
            min_value -= diff / 2.0
        if delta:
            return 100.0 * (c_value - min_value) / delta
        return -2.0

    def _ma_value_at(self, values, i, previous):
        period = max(1, int(self.p.dperiod))
        mode = str(self.p.dmethod).lower()
        float(values[i])
        start = max(0, i - period + 1)
        window = [float(values[idx]) for idx in range(start, i + 1)]
        return self._ma_window_value(window, mode, previous)

    def once(self, start, end):
        """Batch compute indicator lines for historical range in one pass."""
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        stoch_line = self.lines.stoch.array
        signal_line = self.lines.signal.array
        for line in (stoch_line, signal_line):
            while len(line) < end:
                line.append(float("nan"))

        kperiod0 = int(self.p.kperiod_short)
        kperiod1 = int(self.p.kperiod_short)
        previous_signal = None
        actual_end = min(end, len(high_array), len(low_array), len(close_array))
        for i in range(start, actual_end):
            prev_signal_for_state = previous_signal
            stoch = self._stoch_value_at(i, high_array, low_array, close_array, kperiod0, kperiod1)
            stoch_line[i] = stoch
            signal = self._ma_value_at(stoch_line, i, previous_signal)
            signal_line[i] = signal
            previous_signal = signal
            if prev_signal_for_state is not None and prev_signal_for_state > float(
                self.p.overbought
            ):
                kperiod0 = int(self.p.kperiod_short)
                kperiod1 = int(self.p.kperiod_long)
            if prev_signal_for_state is not None and prev_signal_for_state < float(self.p.oversold):
                kperiod0 = int(self.p.kperiod_long)
                kperiod1 = int(self.p.kperiod_short)
        self._kperiod0 = kperiod0
        self._kperiod1 = kperiod1
