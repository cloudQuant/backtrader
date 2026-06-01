#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    AverageTrueRange,
    ExponentialMovingAverage,
    Indicator,
    MinusDirectionalIndicator,
    PlusDirectionalIndicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "ADXCrossHullStyleIndicator",
    "UltraXMAIndicator",
]


def resolve_ma_class(name):
    """Map an MT5 moving-average method name to a backtrader indicator class.

    Args:
        name: MT5 MA method name (e.g. ``'sma'``, ``'ema'``, ``'jjma'``).

    Returns:
        The backtrader moving-average indicator class for the method, defaulting
        to WeightedMovingAverage for unrecognized names.
    """
    mode = str(name).lower()
    if mode in {"mode_sma", "sma"}:
        return SimpleMovingAverage
    if mode in {
        "mode_ema",
        "ema",
        "mode_jjma",
        "jjma",
        "mode_jurx",
        "jurx",
        "mode_parma",
        "parma",
        "mode_t3",
        "t3",
        "mode_vidya",
        "vidya",
        "mode_ama",
        "ama",
    }:
        return ExponentialMovingAverage
    if mode in {"mode_smma", "smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Build an applied-price line from a data feed per MT5 price modes.

    Args:
        data: The backtrader data feed providing OHLC lines.
        mode: MT5 applied-price mode (e.g. ``'price_close'``, ``'price_typical'``).

    Returns:
        A backtrader line expression for the selected applied price, defaulting
        to the close line.
    """
    price_mode = str(mode).lower()
    if price_mode in {"price_open", "open"}:
        return data.open
    if price_mode in {"price_high", "high"}:
        return data.high
    if price_mode in {"price_low", "low"}:
        return data.low
    if price_mode in {"price_median", "median"}:
        return (data.high + data.low) / 2.0
    if price_mode in {"price_typical", "typical"}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {"price_weighted", "weighted"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {"price_simple", "simple"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class ADXCrossHullStyleIndicator(Indicator):
    """Hull-style ADX cross indicator emitting up/down directional signal levels.

    Builds smoothed +DI/-DI values from a full and a half-length directional
    index and marks an ``up`` level on a bullish DI cross or a ``down`` level on a
    bearish DI cross, each offset from price by a fraction of ATR.
    """

    lines = ("up", "down")
    params = (("adx_period", 14),)

    def __init__(self):
        """Construct the directional-index and ATR components and set min period."""
        period = max(2, int(self.p.adx_period))
        self._plus1 = PlusDirectionalIndicator(self.data, period=period)
        self._plus2 = PlusDirectionalIndicator(self.data, period=max(2, period // 2))
        self._minus1 = MinusDirectionalIndicator(self.data, period=period)
        self._minus2 = MinusDirectionalIndicator(self.data, period=max(2, period // 2))
        self._atr = AverageTrueRange(self.data, period=10)
        self.addminperiod(period + 12)

    def next(self):
        """Compute the per-bar up/down signal levels from smoothed DI crosses."""
        b4plusdi = 2.0 * float(self._plus2[-1]) - float(self._plus1[-1])
        nowplusdi = 2.0 * float(self._plus2[0]) - float(self._plus1[0])
        b4minusdi = 2.0 * float(self._minus2[-1]) - float(self._minus1[-1])
        nowminusdi = 2.0 * float(self._minus2[0]) - float(self._minus1[0])
        self.lines.up[0] = 0.0
        self.lines.down[0] = 0.0
        if b4plusdi < b4minusdi and nowplusdi > nowminusdi:
            self.lines.up[0] = float(self.data.low[0]) - 0.25 * float(self._atr[0])
        if b4plusdi > b4minusdi and nowplusdi < nowminusdi:
            self.lines.down[0] = float(self.data.high[0]) + 0.25 * float(self._atr[0])

    def once(self, start, end):
        """Vectorized batch computation of up/down signal levels over a range.

        Args:
            start: First index in the array range to compute.
            end: One past the last index in the array range to compute.
        """
        plus1 = self._plus1.array
        plus2 = self._plus2.array
        minus1 = self._minus1.array
        minus2 = self._minus2.array
        atr = self._atr.array
        low = self.data.low.array
        high = self.data.high.array
        up_line = self.lines.up.array
        down_line = self.lines.down.array
        for line in (up_line, down_line):
            while len(line) < end:
                line.append(float("nan"))

        actual_end = min(
            end, len(plus1), len(plus2), len(minus1), len(minus2), len(atr), len(low), len(high)
        )
        for i in range(start, actual_end):
            up_line[i] = 0.0
            down_line[i] = 0.0
            if i <= 0:
                continue
            b4plusdi = 2.0 * float(plus2[i - 1]) - float(plus1[i - 1])
            nowplusdi = 2.0 * float(plus2[i]) - float(plus1[i])
            b4minusdi = 2.0 * float(minus2[i - 1]) - float(minus1[i - 1])
            nowminusdi = 2.0 * float(minus2[i]) - float(minus1[i])
            if b4plusdi < b4minusdi and nowplusdi > nowminusdi:
                up_line[i] = float(low[i]) - 0.25 * float(atr[i])
            if b4plusdi > b4minusdi and nowplusdi < nowminusdi:
                down_line[i] = float(high[i]) + 0.25 * float(atr[i])


class UltraXMAIndicator(Indicator):
    """UltraXMA breadth indicator counting rising vs falling fanned moving averages.

    Computes a fan of moving averages over increasing periods, counts how many
    are rising (bulls) versus falling (bears) each bar, and smooths those counts
    with an exponential factor to produce trend-strength breadth lines.
    """

    lines = ("bulls", "bears")
    params = (
        ("w_method", "jjma"),
        ("start_length", 3),
        ("wphase", 100),
        ("step", 5),
        ("steps_total", 10),
        ("smooth_method", "jjma"),
        ("smooth_length", 3),
        ("smooth_phase", 100),
        ("ipc", "price_close"),
    )

    def __init__(self):
        """Build the fan of moving averages and breadth smoothing, set min period."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        ma_cls = resolve_ma_class(self.p.w_method)
        smooth_cls = resolve_ma_class(self.p.smooth_method)
        self._periods = [
            int(self.p.start_length + i * self.p.step) for i in range(int(self.p.steps_total) + 1)
        ]
        self._ma_lines = [ma_cls(price_line, period=max(1, p)) for p in self._periods]
        self._bull_smooth = smooth_cls(self.lines.bulls, period=max(1, int(self.p.smooth_length)))
        self._bear_smooth = smooth_cls(self.lines.bears, period=max(1, int(self.p.smooth_length)))
        self.addminperiod(max(self._periods) + int(self.p.smooth_length) + 5)

    def next(self):
        """Compute and smooth the per-bar bullish/bearish moving-average counts."""
        upsch = 0.0
        dnsch = 0.0
        for ma_line in self._ma_lines:
            if float(ma_line[0]) > float(ma_line[-1]):
                upsch += 1.0
            else:
                dnsch += 1.0
        period = max(1, int(self.p.smooth_length))
        alpha = 2.0 / (period + 1.0)
        prev_bulls = float(self.lines.bulls[-1]) if len(self) > 0 else upsch
        prev_bears = float(self.lines.bears[-1]) if len(self) > 0 else dnsch
        if prev_bulls != prev_bulls:
            prev_bulls = upsch
        if prev_bears != prev_bears:
            prev_bears = dnsch
        self.lines.bulls[0] = alpha * upsch + (1.0 - alpha) * prev_bulls if len(self) > 0 else upsch
        self.lines.bears[0] = alpha * dnsch + (1.0 - alpha) * prev_bears if len(self) > 0 else dnsch

    def once(self, start, end):
        """Vectorized batch computation of smoothed breadth counts over a range.

        Args:
            start: First index in the array range to compute.
            end: One past the last index in the array range to compute.
        """
        ma_arrays = [ma_line.array for ma_line in self._ma_lines]
        bulls_line = self.lines.bulls.array
        bears_line = self.lines.bears.array
        for line in (bulls_line, bears_line):
            while len(line) < end:
                line.append(float("nan"))

        period = max(1, int(self.p.smooth_length))
        alpha = 2.0 / (period + 1.0)
        prev_bulls = None
        prev_bears = None
        actual_end = min([end] + [len(array) for array in ma_arrays])
        for i in range(start, actual_end):
            upsch = 0.0
            dnsch = 0.0
            for ma_array in ma_arrays:
                if i > 0 and float(ma_array[i]) > float(ma_array[i - 1]):
                    upsch += 1.0
                else:
                    dnsch += 1.0
            bulls = upsch if prev_bulls is None else alpha * upsch + (1.0 - alpha) * prev_bulls
            bears = dnsch if prev_bears is None else alpha * dnsch + (1.0 - alpha) * prev_bears
            bulls_line[i] = bulls
            bears_line[i] = bears
            prev_bulls = bulls
            prev_bears = bears
