#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "RVIHistogramIndicator",
]


class _RollingWeightedAverage4:
    """Symmetric 4-bar weighted average (weights 1-2-2-1) over a rolling window."""

    def __init__(self):
        """Initialize the rolling value buffer."""
        self.values = []

    def update(self, value):
        """Add a value and return the 4-bar weighted average.

        Args:
            value: The new value to incorporate.

        Returns:
            The weighted average once four values are buffered, else 0.0.
        """
        self.values.append(float(value))
        if len(self.values) > 4:
            self.values.pop(0)
        if len(self.values) < 4:
            return 0.0
        return (self.values[3] + 2.0 * self.values[2] + 2.0 * self.values[1] + self.values[0]) / 6.0


class _RollingSimpleAverage:
    """Simple moving average over a fixed-length rolling window."""

    def __init__(self, period):
        """Initialize the rolling buffer.

        Args:
            period: Window length (clamped to at least 1).
        """
        self.period = max(int(period), 1)
        self.values = []

    def update(self, value):
        """Add a value and return the current simple moving average.

        Args:
            value: The new value to incorporate.

        Returns:
            The simple moving average of the buffered values.
        """
        self.values.append(float(value))
        if len(self.values) > self.period:
            self.values.pop(0)
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)


class RVIHistogramIndicator(Indicator):
    """Relative Vigor Index with a smoothed signal line and color state."""

    lines = ("main", "signal", "hist_base", "color_state")
    params = (
        ("rvi_period", 14),
        ("high_level", 0.3),
        ("low_level", -0.3),
    )

    def __init__(self):
        """Build the weighted/simple averagers used by the RVI computation."""
        self._co_avg4 = _RollingWeightedAverage4()
        self._hl_avg4 = _RollingWeightedAverage4()
        self._num_sma = _RollingSimpleAverage(self.p.rvi_period)
        self._den_sma = _RollingSimpleAverage(self.p.rvi_period)
        self._main_avg4 = _RollingWeightedAverage4()
        self._rolling_averages = (
            self._co_avg4, self._hl_avg4, self._num_sma, self._den_sma, self._main_avg4
        )
        self._sample_length = None
        self._sample_before = None
        self.addminperiod(int(self.p.rvi_period) + 6)

    def _sample(self, publish):
        # A replay can revise OHLC without advancing the input bar; another
        # feed's clock can also cause repeated calls for the same input bar.
        length = len(self.data)
        if length == self._sample_length:
            before = self._sample_before
            for average, values in zip(self._rolling_averages, before):
                average.values[:] = values
        else:
            before = tuple(tuple(average.values) for average in self._rolling_averages)

        try:
            co = float(self.data.close[0]) - float(self.data.open[0])
            hl = float(self.data.high[0]) - float(self.data.low[0])
            weighted_co = self._co_avg4.update(co)
            weighted_hl = self._hl_avg4.update(hl)
            num = self._num_sma.update(weighted_co)
            den = self._den_sma.update(weighted_hl)
            main = num / den if abs(den) > 1e-12 else 0.0
            signal = self._main_avg4.update(main)

            if publish:
                color = 1.0
                if main > float(self.p.high_level):
                    color = 0.0
                elif main < float(self.p.low_level):
                    color = 2.0

                self.lines.main[0] = main
                self.lines.signal[0] = signal
                self.lines.hist_base[0] = 0.0
                self.lines.color_state[0] = color
        except BaseException:
            for average, values in zip(self._rolling_averages, before):
                average.values[:] = values
            raise

        self._sample_length = length
        self._sample_before = before

    def prenext(self):
        """Warm the rolling windows without publishing premature values."""
        self._sample(publish=False)

    def next(self):
        """Compute the RVI main/signal lines and the level-based color state."""
        self._sample(publish=True)
