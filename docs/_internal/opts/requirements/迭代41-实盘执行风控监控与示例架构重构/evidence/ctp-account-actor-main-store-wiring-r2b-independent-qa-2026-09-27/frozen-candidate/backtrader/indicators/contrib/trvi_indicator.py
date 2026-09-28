#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from collections import deque

from .. import (
    EMA,
    RSI,
    SMA,
    Indicator,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "TRVIIndicator",
    "ColorRMACDIndicator",
]


def resolve_ma_class(name):
    """Return a Backtrader moving-average class by symbolic name.

    Args:
        name: Indicator name alias like ``sma``, ``ema``, or ``smma``.

    Returns:
        class: A Backtrader indicator class object.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class RollingWeightedAverage:
    """Weighted moving-average helper with recency-biased linear weights."""

    def __init__(self, period):
        """Create deque state for the rolling weighted average window.

        Args:
            period: Number of bars included in each weighted average.
        """
        self.period = max(1, int(period))
        self.values = deque(maxlen=self.period)

    def update(self, value):
        """Push a value and return the weighted mean of the window.

        Args:
            value: Incoming numeric sample.

        Returns:
            float: Linear recency-weighted average of buffered values.
        """
        self.values.append(float(value))
        weights = list(range(len(self.values), 0, -1))
        return sum(v * w for v, w in zip(self.values, weights)) / sum(weights)


class TRVIIndicator(Indicator):
    """TRVI indicator combining price-range velocity with volume-weighted smoothing."""

    lines = (
        "trvi",
        "signal",
    )
    params = (
        ("period", 26),
        ("volume_type", "tick"),
    )

    def __init__(self):
        """Create helper averages and internal signal buffer."""
        self._num_avg = RollingWeightedAverage(self.p.period)
        self._den_avg = RollingWeightedAverage(self.p.period)
        self._signal_window = deque(maxlen=4)
        self.addminperiod(self.p.period + 8)

    def _volume(self):
        if str(self.p.volume_type).lower() == "real":
            return (
                float(self.data.openinterest[0])
                if len(self.data.openinterest)
                else float(self.data.volume[0])
            )
        return float(self.data.volume[0])

    def _count_val(
        self,
        a_now,
        b_now,
        a_prev1,
        b_prev1,
        a_prev2,
        b_prev2,
        a_prev3,
        b_prev3,
        vol_now,
        vol_prev1,
        vol_prev2,
        vol_prev3,
    ):
        return (
            vol_now * (a_now - b_now)
            + 8.0 * vol_prev1 * (a_prev1 - b_prev1)
            + 8.0 * vol_prev2 * (a_prev2 - b_prev2)
            + vol_prev3 * (a_prev3 - b_prev3)
        )

    def next(self):
        """Compute TRVI and smoothed signal for the current bar."""
        volume_now = self._volume()
        volume_prev1 = float(self.data.volume[-1])
        volume_prev2 = float(self.data.volume[-2])
        volume_prev3 = float(self.data.volume[-3])
        num_value = self._count_val(
            float(self.data.close[0]),
            float(self.data.open[0]),
            float(self.data.close[-1]),
            float(self.data.open[-1]),
            float(self.data.close[-2]),
            float(self.data.open[-2]),
            float(self.data.close[-3]),
            float(self.data.open[-3]),
            volume_now,
            volume_prev1,
            volume_prev2,
            volume_prev3,
        )
        den_value = self._count_val(
            float(self.data.high[0]),
            float(self.data.low[0]),
            float(self.data.high[-1]),
            float(self.data.low[-1]),
            float(self.data.high[-2]),
            float(self.data.low[-2]),
            float(self.data.high[-3]),
            float(self.data.low[-3]),
            volume_now,
            volume_prev1,
            volume_prev2,
            volume_prev3,
        )
        smooth_num = self._num_avg.update(num_value)
        smooth_den = self._den_avg.update(den_value)
        trvi_value = smooth_num / smooth_den if smooth_den else 0.0
        self.lines.trvi[0] = trvi_value
        self._signal_window.appendleft(trvi_value)
        if len(self._signal_window) == 4:
            self.lines.signal[0] = (
                4.0 * self._signal_window[0]
                + 3.0 * self._signal_window[1]
                + 2.0 * self._signal_window[2]
                + self._signal_window[3]
            ) / 10.0
        else:
            self.lines.signal[0] = trvi_value


class ColorRMACDIndicator(Indicator):
    """Custom RMACD composite indicator with configurable signal MA."""

    lines = (
        "rmacd",
        "signal",
    )
    params = (
        ("fast_rvi", 12),
        ("slow_trvi", 26),
        ("volume_type", "tick"),
        ("signal_method", "sma"),
        ("signal_xma", 9),
    )

    def __init__(self):
        """Build RMACD components and required minimum period."""
        ma_cls = resolve_ma_class(self.p.signal_method)
        self.rvi = RSI(self.data.close, period=self.p.fast_rvi, safediv=True)
        self.trvi = TRVIIndicator(
            self.data, period=self.p.slow_trvi, volume_type=self.p.volume_type
        )
        self.lines.rmacd = self.rvi - self.trvi.signal
        self.lines.signal = ma_cls(self.lines.rmacd, period=self.p.signal_xma)
        self.addminperiod(max(self.p.fast_rvi, self.p.slow_trvi + 8, self.p.signal_xma) + 5)
