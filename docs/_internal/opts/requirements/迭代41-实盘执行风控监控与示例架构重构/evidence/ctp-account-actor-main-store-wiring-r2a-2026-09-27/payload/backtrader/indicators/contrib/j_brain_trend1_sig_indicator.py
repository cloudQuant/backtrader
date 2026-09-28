#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from collections import deque

from .. import (
    ATR,
    EMA,
    RSI,
    SMA,
    Highest,
    Indicator,
    Lowest,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "JBrainTrend1SigIndicator",
    "UltraRSIIndicator",
]


def resolve_ma_class(name):
    """Resolve a moving-average style name to a Backtrader indicator class.

    Args:
        name: Requested moving-average mode, e.g., ``sma`` or ``ema``.

    Returns:
        Corresponding Backtrader moving-average indicator class.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    if mode in {"lwma", "mode_lwma"}:
        return WeightedMovingAverage
    return EMA


class CountSmoother:
    """Track a rolling series of values and return a smoothed aggregate.

    Supports EMA-like, SMA, LWMA, and SMMA update rules used by the RSI module.
    """

    def __init__(self, method, period):
        """Initialize the smoother.

        Args:
            method: Smoothing method name.
            period: Window size used by SMA/LWMA/SMMA/EMA-style calculations.
        """
        self.method = str(method).lower()
        self.period = max(1, int(period))
        self.state = None
        self.values = deque(maxlen=self.period)

    def update(self, value):
        """Update the smoother with a new sample and return the current value.

        Args:
            value: New numeric sample.

        Returns:
            Smoothed value after applying the configured method.
        """
        value = float(value)
        if self.method in {"sma", "mode_sma"}:
            self.values.append(value)
            return sum(self.values) / len(self.values)
        if self.method in {"lwma", "mode_lwma"}:
            self.values.append(value)
            weights = list(range(1, len(self.values) + 1))
            return sum(v * w for v, w in zip(self.values, weights)) / sum(weights)
        if self.method in {"smma", "mode_smma"}:
            if self.state is None:
                self.state = value
            else:
                self.state = ((self.period - 1) * self.state + value) / self.period
            return self.state
        alpha = 2.0 / (self.period + 1.0)
        if self.state is None:
            self.state = value
        else:
            self.state = self.state + alpha * (value - self.state)
        return self.state


class JBrainTrend1SigIndicator(Indicator):
    """Generate directional trend-signal levels from ATR, stochastic, and MAs.

    The indicator emits ``buy_signal`` and ``sell_signal`` pulses used by the
    main strategy.
    """

    lines = (
        "sell_signal",
        "buy_signal",
    )
    params = (
        ("atr_period", 7),
        ("sto_period", 9),
        ("ma_method", "sma"),
        ("xlength", 7),
    )

    def __init__(self):
        """Build ATR, highest/lowest price extremes, and smoothing primitives."""
        ma_cls = resolve_ma_class(self.p.ma_method)
        self.atr = ATR(self.data, period=self.p.atr_period)
        self.highest = Highest(self.data.high, period=self.p.sto_period)
        self.lowest = Lowest(self.data.low, period=self.p.sto_period)
        self.jh = ma_cls(self.data.high, period=self.p.xlength)
        self.jl = ma_cls(self.data.low, period=self.p.xlength)
        self.jc = ma_cls(self.data.close, period=self.p.xlength)
        self._d = 2.3
        self._s = 1.5
        self._x1 = 53.0
        self._x2 = 47.0
        self._p_state = 0
        self._old_trend = 0
        self.addminperiod(max(self.p.atr_period, self.p.sto_period, self.p.xlength) + 3)

    def next(self):
        """Evaluate one bar and update ``buy_signal``/``sell_signal`` outputs."""
        self.lines.sell_signal[0] = 0.0
        self.lines.buy_signal[0] = 0.0
        highest = float(self.highest[0])
        lowest = float(self.lowest[0])
        close = float(self.data.close[0])
        denom = highest - lowest
        stochastic = 50.0 if denom == 0 else 100.0 * (close - lowest) / denom
        atr_value = float(self.atr[0])
        range_value = atr_value / self._d
        range_shift = atr_value * self._s / 4.0
        val3 = abs(float(self.jc[0]) - float(self.jc[-2]))

        if stochastic < self._x2 and val3 > range_value:
            self._p_state = 1
        if stochastic > self._x1 and val3 > range_value:
            self._p_state = 2
        if val3 <= range_value:
            return

        if stochastic < self._x2 and self._p_state in (0, 1):
            if self._old_trend > 0:
                self.lines.sell_signal[0] = float(self.jh[0]) + range_shift
            if len(self.data) > 1:
                self._old_trend = -1
        if stochastic > self._x1 and self._p_state in (0, 2):
            if self._old_trend < 0:
                self.lines.buy_signal[0] = float(self.jl[0]) - range_shift
            if len(self.data) > 1:
                self._old_trend = 1


class UltraRSIIndicator(Indicator):
    """Smooth RSI slope-count indicator with configurable averaging stages.

    Counts bullish versus bearish RSI directional changes across multiple moving
    average steps and smooths both counters for a stable signal.
    """

    lines = (
        "bulls",
        "bears",
    )
    params = (
        ("rsi_period", 13),
        ("applied_price", "close"),
        ("w_method", "jjma"),
        ("start_length", 3),
        ("nstep", 5),
        ("nsteps_total", 10),
        ("smooth_method", "jjma"),
        ("smooth_length", 3),
    )

    def __init__(self):
        """Initialize RSI series and helper smoothing state."""
        price_line = self._price_line()
        ma_cls = resolve_ma_class(self.p.w_method)
        self.rsi = RSI(price_line, period=self.p.rsi_period, safediv=True)
        self._series = [
            ma_cls(self.rsi, period=max(1, int(self.p.start_length + step * self.p.nstep)))
            for step in range(int(self.p.nsteps_total) + 1)
        ]
        self._bull_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self._bear_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self.addminperiod(
            self.p.rsi_period
            + self.p.start_length
            + self.p.nstep * self.p.nsteps_total
            + self.p.smooth_length
            + 5
        )

    def _price_line(self):
        mode = str(self.p.applied_price).lower()
        if mode == "open":
            return self.data.open
        if mode == "high":
            return self.data.high
        if mode == "low":
            return self.data.low
        if mode == "median":
            return (self.data.high + self.data.low) / 2.0
        if mode == "typical":
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if mode == "weighted":
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def next(self):
        """Update bullish and bearish counters and write smoothed values."""
        up_count = 0
        down_count = 0
        for series in self._series:
            current = float(series[0])
            previous = float(series[-1])
            if current > previous:
                up_count += 1
            elif current < previous:
                down_count += 1
        self.lines.bulls[0] = self._bull_smoother.update(up_count)
        self.lines.bears[0] = self._bear_smoother.update(down_count)
