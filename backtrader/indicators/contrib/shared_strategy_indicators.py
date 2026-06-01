#!/usr/bin/env python
"""Repeated functional-test indicators migrated to contrib.

These indicators are re-exported by ``backtrader.indicators`` and are
therefore available as ``Xxx``. Some historical same-name test
classes had incompatible line contracts; those variants use explicit names.
"""

import math
from collections import deque

from .. import (
    EMA,
    AverageDirectionalMovementIndex,
    AverageTrueRange,
    ExponentialMovingAverage,
    Highest,
    If,
    Indicator,
    Lowest,
    MinusDirectionalIndicator,
    ParabolicSAR,
    PlusDirectionalIndicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    StandardDeviation,
    StochasticFull,
    WeightedMovingAverage,
)

__all__ = [
    "SkyscraperFixIndicator",
    "SkyscraperFixDuplexIndicator",
    "SkyscraperFixColorAMLIndicator",
    "AppliedPriceCCI",
    "ColorAMLIndicator",
    "ColorAMLMeanReversionIndicator",
    "X2MACandleApprox",
    "XPeriodCandleColor",
    "XPeriodCandleSystemColor",
    "AcceleratorOscillator",
    "AIAcceleratorOscillator",
    "AdaptiveMarketLevel",
    "AmlIndicator",
    "FunctionalAwesomeOscillator",
    "AIAwesomeOscillator",
    "BlauErgodicMDI",
    "BlauErgodicMDIClassic",
    "BrakeExpIndicator",
    "FlatTrendIndicator",
    "FlatTrendDistanceIndicator",
    "IinMASignalIndicator",
    "KDJ",
    "LaguerreIndicator",
    "LaguerreColorIndicator",
    "RelativeVigorIndex",
    "SmoothedRelativeVigorIndex",
    "SafeCCI",
    "SafeCCIWithFactor",
    "SilverTrendSignalProxy",
    "SilverTrendDirectionSignalProxy",
]


def _price_series(data, mode):
    key = str(mode).lower()
    if key in ("1", "close", "price_close"):
        return data.close
    if key in ("2", "open", "price_open"):
        return data.open
    if key in ("3", "high", "price_high"):
        return data.high
    if key in ("4", "low", "price_low"):
        return data.low
    if key in ("5", "median", "price_median"):
        return (data.high + data.low) / 2.0
    if key in ("6", "typical", "price_typical"):
        return (data.high + data.low + data.close) / 3.0
    if key in ("7", "weighted", "price_weighted"):
        return (data.high + data.low + data.close + data.close) / 4.0
    if key in ("8", "simple", "price_simpl"):
        return (data.open + data.close) / 2.0
    if key in ("9", "quarter", "price_quarter"):
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


def resolve_ma_class(name):
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


class SkyscraperFixIndicator(Indicator):
    """Channel-like adaptive indicator emitting buy/sell buffers and color state."""

    lines = ("up_buffer", "dn_buffer", "buy_buffer", "sell_buffer", "color_state")
    params = (
        ("length", 10),
        ("kv", 0.9),
        ("percentage", 0.0),
        ("use_high_low", True),
        ("atr_period", 15),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Initialize internal ATR state and channel persistence variables."""
        self.addminperiod(max(self.p.length, self.p.atr_period) + 3)
        self.atr = AverageTrueRange(self.data, period=self.p.atr_period)
        self.atr_high = Highest(self.atr, period=self.p.length)
        self.atr_low = Lowest(self.atr, period=self.p.length)
        self._prev_smin = None
        self._prev_smax = None
        self._prev_trend = 0

    @staticmethod
    def _nan():
        return float("nan")

    @staticmethod
    def _valid(value):
        return value is not None and math.isfinite(value)

    def next(self):
        """Calculate up/down channel levels, pending buffers, and current color."""
        up = self._nan()
        dn = self._nan()
        buy = self._nan()
        sell = self._nan()
        color = (
            self.lines.color_state[-1]
            if len(self) > 1 and math.isfinite(self.lines.color_state[-1])
            else 1.0
        )
        if self._prev_smin is None:
            close = float(self.data.close[0])
            self._prev_smin = close
            self._prev_smax = close
            self._prev_trend = 0
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            self.lines.color_state[0] = color
            return
        atrmax = float(self.atr_high[0])
        atrmin = float(self.atr_low[0])
        if not math.isfinite(atrmax) or not math.isfinite(atrmin):
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            self.lines.color_state[0] = color
            return
        step = int(0.5 * self.p.kv * (atrmax + atrmin) / self.p.point_size)
        xstep = step * self.p.point_size
        x2step = 2.0 * xstep
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.p.use_high_low:
            smax0 = low + x2step
            smin0 = high - x2step
        else:
            smax0 = close + x2step
            smin0 = close - x2step
        trend0 = self._prev_trend
        if close > self._prev_smax:
            trend0 = 1
        if close < self._prev_smin:
            trend0 = -1
        if trend0 > 0:
            smin0 = max(smin0, self._prev_smin)
            up = smin0
            color = 0.0
        else:
            smax0 = min(smax0, self._prev_smax)
            dn = smax0
            color = 1.0
        prev_up = self.lines.up_buffer[-1] if len(self) > 1 else self._nan()
        prev_dn = self.lines.dn_buffer[-1] if len(self) > 1 else self._nan()
        if self._valid(prev_dn) and self._valid(up):
            buy = up
        if self._valid(prev_up) and self._valid(dn):
            sell = dn
        self.lines.up_buffer[0] = up
        self.lines.dn_buffer[0] = dn
        self.lines.buy_buffer[0] = buy
        self.lines.sell_buffer[0] = sell
        self.lines.color_state[0] = color
        self._prev_smin = smin0
        self._prev_smax = smax0
        self._prev_trend = trend0


class SkyscraperFixDuplexIndicator(Indicator):
    """Indicator for directional buffer-based skyline reversals."""

    lines = ("up_buffer", "dn_buffer", "buy_buffer", "sell_buffer")
    params = (
        ("length", 10),
        ("kv", 0.9),
        ("percentage", 0.0),
        ("use_high_low", True),
        ("atr_period", 15),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Build ATR state and initialize rolling trend context."""
        self.addminperiod(max(self.p.length, self.p.atr_period) + 2)
        self.atr = AverageTrueRange(self.data, period=self.p.atr_period)
        self.atr_high = Highest(self.atr, period=self.p.length)
        self.atr_low = Lowest(self.atr, period=self.p.length)
        self._prev_smin = None
        self._prev_smax = None
        self._prev_trend = 0

    @staticmethod
    def _nan():
        return float("nan")

    @staticmethod
    def _valid(value):
        return value is not None and math.isfinite(value)

    def next(self):
        """Update the skyscraper buffers for the current bar."""
        up = self._nan()
        dn = self._nan()
        buy = self._nan()
        sell = self._nan()

        if self._prev_smin is None:
            self._prev_smin = float(self.data.close[0])
            self._prev_smax = float(self.data.close[0])
            self._prev_trend = 0
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            return

        atrmax = float(self.atr_high[0])
        atrmin = float(self.atr_low[0])
        if not math.isfinite(atrmax) or not math.isfinite(atrmin):
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            return

        step = int(0.5 * self.p.kv * (atrmax + atrmin) / self.p.point_size)
        xstep = step * self.p.point_size
        x2step = 2.0 * xstep

        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.p.use_high_low:
            smax0 = low + x2step
            smin0 = high - x2step
        else:
            smax0 = close + x2step
            smin0 = close - x2step

        trend0 = self._prev_trend
        if close > self._prev_smax:
            trend0 = 1
        if close < self._prev_smin:
            trend0 = -1

        if trend0 > 0:
            smin0 = max(smin0, self._prev_smin)
            up = smin0
        else:
            smax0 = min(smax0, self._prev_smax)
            dn = smax0

        prev_up = self.lines.up_buffer[-1] if len(self) > 1 else self._nan()
        prev_dn = self.lines.dn_buffer[-1] if len(self) > 1 else self._nan()

        if self._valid(prev_dn) and self._valid(up):
            buy = up
        if self._valid(prev_up) and self._valid(dn):
            sell = dn

        self.lines.up_buffer[0] = up
        self.lines.dn_buffer[0] = dn
        self.lines.buy_buffer[0] = buy
        self.lines.sell_buffer[0] = sell

        self._prev_smin = smin0
        self._prev_smax = smax0
        self._prev_trend = trend0


class SkyscraperFixColorAMLIndicator(Indicator):
    """Skyscraper fix channel indicator producing buy/sell buffers and color state."""

    lines = ("up_buffer", "dn_buffer", "buy_buffer", "sell_buffer", "color_state")
    params = (
        ("length", 10),
        ("kv", 0.9),
        ("percentage", 0.0),
        ("use_high_low", True),
        ("atr_period", 15),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Initialize ATR-derived channel state and lookback counters."""
        self.addminperiod(max(self.p.length, self.p.atr_period) + 3)
        self.atr = AverageTrueRange(self.data, period=self.p.atr_period)
        self.atr_high = Highest(self.atr, period=self.p.length)
        self.atr_low = Lowest(self.atr, period=self.p.length)
        self._prev_smin = None
        self._prev_smax = None
        self._prev_trend = 0

    @staticmethod
    def _nan():
        return float("nan")

    @staticmethod
    def _valid(value):
        return value is not None and math.isfinite(value)

    def next(self):
        """Compute current channel extrema and potential reversal buffers."""
        up = self._nan()
        dn = self._nan()
        buy = self._nan()
        sell = self._nan()
        color = (
            self.lines.color_state[-1]
            if len(self) > 1 and math.isfinite(self.lines.color_state[-1])
            else 1.0
        )
        if self._prev_smin is None:
            close = float(self.data.close[0])
            self._prev_smin = close
            self._prev_smax = close
            self._prev_trend = 0
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            self.lines.color_state[0] = color
            return
        atrmax = float(self.atr_high[0])
        atrmin = float(self.atr_low[0])
        if not math.isfinite(atrmax) or not math.isfinite(atrmin):
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            self.lines.color_state[0] = color
            return
        step = int(0.5 * self.p.kv * (atrmax + atrmin) / self.p.point_size)
        x2step = 2.0 * step * self.p.point_size
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.p.use_high_low:
            smax0 = low + x2step
            smin0 = high - x2step
        else:
            smax0 = close + x2step
            smin0 = close - x2step
        trend0 = self._prev_trend
        if close > self._prev_smax:
            trend0 = 1
        if close < self._prev_smin:
            trend0 = -1
        if trend0 > 0:
            smin0 = max(smin0, self._prev_smin)
            up = smin0
            color = 0.0
        else:
            smax0 = min(smax0, self._prev_smax)
            dn = smax0
            color = 1.0
        prev_up = self.lines.up_buffer[-1] if len(self) > 1 else self._nan()
        prev_dn = self.lines.dn_buffer[-1] if len(self) > 1 else self._nan()
        if self._valid(prev_dn) and self._valid(up):
            buy = up
        if self._valid(prev_up) and self._valid(dn):
            sell = dn
        self.lines.up_buffer[0] = up
        self.lines.dn_buffer[0] = dn
        self.lines.buy_buffer[0] = buy
        self.lines.sell_buffer[0] = sell
        self.lines.color_state[0] = color
        self._prev_smin = smin0
        self._prev_smax = smax0
        self._prev_trend = trend0


class AppliedPriceCCI(Indicator):
    """Commodity Channel Index computed on an arbitrary applied-price line."""

    lines = ("cci",)
    params = (
        ("period", 14),
        ("factor", 0.015),
    )

    def __init__(self):
        """Set the warm-up period to one bar beyond the CCI lookback."""
        self.addminperiod(int(self.p.period) + 1)

    def next(self):
        """Emit the CCI value: price deviation from its mean over mean abs deviation."""
        period = int(self.p.period)
        prices = [float(self.data[-i]) for i in range(period)]
        mean_price = sum(prices) / period
        mean_dev = sum(abs(price - mean_price) for price in prices) / period
        denom = float(self.p.factor) * mean_dev
        if denom == 0:
            self.lines.cci[0] = 0.0
            return
        self.lines.cci[0] = (float(self.data[0]) - mean_price) / denom


class ColorAMLIndicator(Indicator):
    """Fractal-driven adaptive moving line with trend color transitions."""

    lines = ("aml", "color_state")
    params = (
        ("fractal", 6),
        ("lag", 7),
        ("shift", 0),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Initialize smoothing buffers and state for AML computation."""
        self.addminperiod(2 * self.p.fractal + self.p.lag + 5)
        self._smooth_history = []
        self._prev_aml = None
        self._prev_color = 1.0

    @staticmethod
    def _window_max(line, start_ago, size):
        values = [float(line[-(start_ago + idx)]) for idx in range(size)]
        return max(values)

    @staticmethod
    def _window_min(line, start_ago, size):
        values = [float(line[-(start_ago + idx)]) for idx in range(size)]
        return min(values)

    def next(self):
        """Update AML line value and color state for the current candle."""
        if len(self.data) < 2 * self.p.fractal + self.p.lag + 2:
            self.lines.aml[0] = float("nan")
            self.lines.color_state[0] = self._prev_color
            return
        r1 = (
            self._window_max(self.data.high, 0, self.p.fractal)
            - self._window_min(self.data.low, 0, self.p.fractal)
        ) / float(self.p.fractal)
        r2 = (
            self._window_max(self.data.high, self.p.fractal, self.p.fractal)
            - self._window_min(self.data.low, self.p.fractal, self.p.fractal)
        ) / float(self.p.fractal)
        r3 = (
            self._window_max(self.data.high, 0, 2 * self.p.fractal)
            - self._window_min(self.data.low, 0, 2 * self.p.fractal)
        ) / float(2 * self.p.fractal)
        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896
        alpha = math.exp(-self.p.lag * (dim - 1.0))
        alpha = min(alpha, 1.0)
        alpha = max(alpha, 0.01)
        price = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.open[0])
            + 2.0 * float(self.data.close[0])
        ) / 6.0
        prev_smooth = self._smooth_history[-1] if self._smooth_history else price
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        self._smooth_history.append(smooth)
        prev_aml = self._prev_aml if self._prev_aml is not None else smooth
        lag_smooth = (
            self._smooth_history[-(self.p.lag + 1)]
            if len(self._smooth_history) > self.p.lag
            else smooth
        )
        if abs(smooth - lag_smooth) >= self.p.lag * self.p.lag * self.p.point_size:
            aml = smooth
        else:
            aml = prev_aml
        color = self._prev_color
        if aml > prev_aml:
            color = 2.0
        if aml < prev_aml:
            color = 0.0
        self.lines.aml[0] = aml
        self.lines.color_state[0] = color
        self._prev_aml = aml
        self._prev_color = color


class ColorAMLMeanReversionIndicator(Indicator):
    """Adaptive moving-lowpass indicator for color-state trend capture."""

    lines = ("aml", "color_state")
    params = (
        ("fractal", 6),
        ("lag", 7),
        ("shift", 0),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Prepare smoothing buffers and history for AML color-state generation."""
        self.addminperiod(2 * self.p.fractal + self.p.lag + 5)
        self._smooth_history = []
        self._prev_aml = None
        self._prev_color = 1.0

    @staticmethod
    def _window_max(line, start_ago, size):
        values = [float(line[-(start_ago + idx)]) for idx in range(size)]
        return max(values)

    @staticmethod
    def _window_min(line, start_ago, size):
        values = [float(line[-(start_ago + idx)]) for idx in range(size)]
        return min(values)

    def next(self):
        """Update smooth and color values for the active bar."""
        if len(self.data) < 2 * self.p.fractal + self.p.lag + 2:
            self.lines.aml[0] = float("nan")
            self.lines.color_state[0] = self._prev_color
            return
        r1 = (
            self._window_max(self.data.high, 0, self.p.fractal)
            - self._window_min(self.data.low, 0, self.p.fractal)
        ) / float(self.p.fractal)
        r2 = (
            self._window_max(self.data.high, self.p.fractal, self.p.fractal)
            - self._window_min(self.data.low, self.p.fractal, self.p.fractal)
        ) / float(self.p.fractal)
        r3 = (
            self._window_max(self.data.high, 0, 2 * self.p.fractal)
            - self._window_min(self.data.low, 0, 2 * self.p.fractal)
        ) / float(2 * self.p.fractal)
        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896
        alpha = math.exp(-self.p.lag * (dim - 1.0))
        alpha = min(alpha, 1.0)
        alpha = max(alpha, 0.01)
        price = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.open[0])
            + 2.0 * float(self.data.close[0])
        ) / 6.0
        prev_smooth = self._smooth_history[-1] if self._smooth_history else price
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        self._smooth_history.append(smooth)
        prev_aml = self._prev_aml if self._prev_aml is not None else smooth
        lag_smooth = (
            self._smooth_history[-(self.p.lag + 1)]
            if len(self._smooth_history) > self.p.lag
            else smooth
        )
        aml = (
            smooth
            if abs(smooth - lag_smooth) >= self.p.lag * self.p.lag * self.p.point_size
            else prev_aml
        )
        color = self._prev_color
        if aml > prev_aml:
            color = 2.0
        if aml < prev_aml:
            color = 0.0
        self.lines.aml[0] = aml
        self.lines.color_state[0] = color
        self._prev_aml = aml
        self._prev_color = color


class X2MACandleApprox(Indicator):
    """Two-stage moving approximation of candle structure and color."""

    lines = ("open_value", "high_value", "low_value", "close_value", "color_state")
    params = (
        ("length1", 12),
        ("phase1", 15),
        ("length2", 5),
        ("phase2", 15),
        ("gap", 10.0),
    )

    def __init__(self):
        """Initialize rolling queues and two-stage smoothing states."""
        self._length1 = max(1, int(self.p.length1))
        self._length2 = max(2, int(self.p.length2))
        self._phase2 = max(-100, min(100, int(self.p.phase2)))
        base_alpha = 2.0 / (self._length2 + 1.0)
        self._alpha = max(0.01, min(0.95, base_alpha * (1.0 + self._phase2 / 200.0)))
        self._phase_gain = self._phase2 / 200.0
        self._queues = {
            "open": deque(maxlen=self._length1),
            "high": deque(maxlen=self._length1),
            "low": deque(maxlen=self._length1),
            "close": deque(maxlen=self._length1),
        }
        self._states = {
            "open": {"ema1": None, "ema2": None},
            "high": {"ema1": None, "ema2": None},
            "low": {"ema1": None, "ema2": None},
            "close": {"ema1": None, "ema2": None},
        }
        self.addminperiod(self._length1 + self._length2)

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _sma(self, key, value):
        queue = self._queues[key]
        queue.append(float(value))
        if len(queue) < self._length1:
            return None
        return sum(queue) / len(queue)

    def _smooth(self, key, value):
        state = self._states[key]
        if state["ema1"] is None:
            state["ema1"] = value
            state["ema2"] = value
        else:
            state["ema1"] = state["ema1"] + self._alpha * (value - state["ema1"])
            state["ema2"] = state["ema2"] + self._alpha * (state["ema1"] - state["ema2"])
        return state["ema1"] + self._phase_gain * (state["ema1"] - state["ema2"])

    def _stage_value(self, key, line):
        sma_value = self._sma(key, line[0])
        if sma_value is None:
            return None
        return self._smooth(key, sma_value)

    def next(self):
        """Update approximated open/high/low/close and color from historical window."""
        open_value = self._stage_value("open", self.data.open)
        high_value = self._stage_value("high", self.data.high)
        low_value = self._stage_value("low", self.data.low)
        close_value = self._stage_value("close", self.data.close)
        if not all(self._finite(v) for v in (open_value, high_value, low_value, close_value)):
            self.lines.open_value[0] = float("nan")
            self.lines.high_value[0] = float("nan")
            self.lines.low_value[0] = float("nan")
            self.lines.close_value[0] = float("nan")
            self.lines.color_state[0] = float("nan")
            return
        max_value = max(open_value, close_value, high_value, low_value)
        min_value = min(open_value, close_value, high_value, low_value)
        adjusted_open = open_value
        if len(self) > 1 and abs(float(self.data.open[0]) - float(self.data.close[0])) <= float(
            self.p.gap
        ):
            prev_close = float(self.lines.close_value[-1])
            if self._finite(prev_close):
                adjusted_open = prev_close
        color_state = (
            2.0 if adjusted_open < close_value else 0.0 if adjusted_open > close_value else 1.0
        )
        self.lines.open_value[0] = adjusted_open
        self.lines.high_value[0] = max_value
        self.lines.low_value[0] = min_value
        self.lines.close_value[0] = close_value
        self.lines.color_state[0] = color_state


class XPeriodCandleColor(Indicator):
    """Smoothing-based period-candle indicator producing color index."""

    lines = ("color_idx", "xopen", "xclose", "xhigh", "xlow")
    params = (
        ("cperiod", 5),
        ("ma_length", 3),
    )

    def __init__(self):
        """Build smoothed OHLC components and set minimum bars."""
        self.smooth_open = SimpleMovingAverage(self.data.open, period=self.p.ma_length)
        self.smooth_high = SimpleMovingAverage(self.data.high, period=self.p.ma_length)
        self.smooth_low = SimpleMovingAverage(self.data.low, period=self.p.ma_length)
        self.smooth_close = SimpleMovingAverage(self.data.close, period=self.p.ma_length)
        self.addminperiod(self.p.ma_length + self.p.cperiod)

    def next(self):
        """Compute synthetic candle and color value for the current bar."""
        lookback = max(1, int(self.p.cperiod))
        start = -(lookback - 1)
        xopen = float(self.smooth_open[start])
        xclose = float(self.smooth_close[0])
        highs = [float(self.smooth_high[-i]) for i in range(lookback)]
        lows = [float(self.smooth_low[-i]) for i in range(lookback)]
        self.lines.xopen[0] = xopen
        self.lines.xclose[0] = xclose
        self.lines.xhigh[0] = max(highs)
        self.lines.xlow[0] = min(lows)
        self.lines.color_idx[0] = 0.0 if xopen <= xclose else 2.0


class XPeriodCandleSystemColor(Indicator):
    """SMA-smoothed candle color indicator with Bollinger Band breakout detection."""

    lines = ("color_idx", "upper", "lower", "xopen", "xclose")
    params = (
        ("period", 5),
        ("bb_length", 20),
        ("bands_deviation", 1.001),
    )

    def __init__(self):
        """Initialize SMA smoothing of OHLC and Bollinger Band components."""
        self.smooth_open = SimpleMovingAverage(self.data.open, period=self.p.period)
        self.smooth_high = SimpleMovingAverage(self.data.high, period=self.p.period)
        self.smooth_low = SimpleMovingAverage(self.data.low, period=self.p.period)
        self.smooth_close = SimpleMovingAverage(self.data.close, period=self.p.period)
        self.mid = SimpleMovingAverage(self.smooth_close, period=self.p.bb_length)
        self.std = StandardDeviation(self.smooth_close, period=self.p.bb_length)

    def next(self):
        """Assign color index based on smoothed candle direction and Bollinger Band position."""
        xopen = float(self.smooth_open[0])
        xclose = float(self.smooth_close[0])
        upper = float(self.mid[0] + self.std[0] * self.p.bands_deviation)
        lower = float(self.mid[0] - self.std[0] * self.p.bands_deviation)
        color = 2.0
        if xopen <= xclose:
            color = 1.0
        elif xopen > xclose:
            color = 3.0
        if xopen <= xclose and xclose > upper:
            color = 0.0
        if xopen > xclose and xclose < lower:
            color = 4.0
        self.lines.xopen[0] = xopen
        self.lines.xclose[0] = xclose
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        self.lines.color_idx[0] = color


class AcceleratorOscillator(Indicator):
    """Compute accelerator oscillator using short and long SMA of median price."""

    lines = ("ac",)
    params = ()

    def __init__(self):
        """Build the oscillator line from medians and SMA smoothing."""
        median = (self.data.high + self.data.low) / 2.0
        ao = SimpleMovingAverage(median, period=5) - SimpleMovingAverage(median, period=34)
        self.lines.ac = ao - SimpleMovingAverage(ao, period=5)


class AIAcceleratorOscillator(Indicator):
    """Accelerator Oscillator indicator computed from Awesome Oscillator."""

    lines = ("ac",)

    def __init__(self):
        """Create an AO smoothed by a 5-period SMA."""
        ao = AIAwesomeOscillator(self.data)
        ao_sma = SimpleMovingAverage(ao.ao, period=5)
        self.lines.ac = ao.ao - ao_sma


class AdaptiveMarketLevel(Indicator):
    """Adaptive Market Level indicator using fractal dimension and adaptive smoothing.

    The AML line adapts its smoothing alpha based on the measured fractal
    dimension of the price range, providing faster response in trending markets
    and slower response in mean-reverting regimes.
    """

    lines = ("aml",)
    params = (
        ("fractal", 70),
        ("lag", 18),
        ("shift", 0),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize history deques and minimum period for the indicator."""
        self._smooth_history = []
        self._aml_history = []
        self._min_period = max(int(self.p.fractal) * 2 + int(self.p.lag), 1)

    def _range(self, count, start):
        highs = []
        lows = []
        for idx in range(start, start + count):
            ago = -idx if idx else 0
            highs.append(float(self.data.high[ago]))
            lows.append(float(self.data.low[ago]))
        return max(highs) - min(lows)

    def next(self):
        """Compute AML value using fractal-range adaptive smoothing."""
        fractal = int(self.p.fractal)
        lag = int(self.p.lag)
        if len(self.data) < self._min_period:
            self.lines.aml[0] = float(self.data.close[0])
            return
        r1 = self._range(fractal, 0) / fractal
        r2 = self._range(fractal, fractal) / fractal
        r3 = self._range(fractal * 2, 0) / (fractal * 2)
        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896
        alpha = math.exp(-lag * (dim - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        price = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.open[0])
            + 2.0 * float(self.data.close[0])
        ) / 6.0
        prev_smooth = self._smooth_history[-1] if self._smooth_history else 0.0
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        lagged_smooth = self._smooth_history[-lag] if len(self._smooth_history) >= lag else 0.0
        prev_aml = self._aml_history[-1] if self._aml_history else smooth
        threshold = lag * lag * float(self.p.point)
        aml = smooth if abs(smooth - lagged_smooth) >= threshold else prev_aml
        self._smooth_history.append(smooth)
        self._aml_history.append(aml)
        self.lines.aml[0] = aml


class AmlIndicator(Indicator):
    """Adaptive Market Level indicator for backtrader (on-chart version).

    Uses the same fractal-range adaptive smoothing logic as AdaptiveMarketLevel
    but implemented as a Backtrader indicator with minperiod management.
    """

    lines = ("aml",)
    params = (
        ("fractal", 70),
        ("lag", 18),
        ("shift", 0),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize smoothing deque and minperiod based on fractal and lag."""
        lag = max(1, int(self.p.lag))
        fractal = max(1, int(self.p.fractal))
        self._smooth = deque(maxlen=lag + 1)
        self.addminperiod(max(fractal * 2 + 2, lag + 2))

    def _range(self, start, count):
        highs = [float(self.data.high[-(start + i)]) for i in range(count)]
        lows = [float(self.data.low[-(start + i)]) for i in range(count)]
        return max(highs) - min(lows)

    def next(self):
        """Compute AML value using fractal-range adaptive smoothing."""
        fractal = max(1, int(self.p.fractal))
        lag = max(1, int(self.p.lag))
        price = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.open[0])
            + 2.0 * float(self.data.close[0])
        ) / 6.0

        if len(self.data) < fractal * 2 + 1:
            self._smooth.append(price)
            self.lines.aml[0] = float(self.lines.aml[-1]) if len(self) > 1 else price
            return

        r1 = self._range(0, fractal) / fractal
        r2 = self._range(fractal, fractal) / fractal
        r3 = self._range(0, fractal * 2) / (fractal * 2)

        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) / math.log(2.0)

        alpha = math.exp(-lag * (dim - 1.0))
        alpha = min(1.0, max(0.01, alpha))

        prev_smooth = self._smooth[-1] if self._smooth else 0.0
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        lagged_smooth = self._smooth[0] if len(self._smooth) == self._smooth.maxlen else 0.0
        self._smooth.append(smooth)

        if abs(smooth - lagged_smooth) >= lag * lag * float(self.p.point):
            self.lines.aml[0] = smooth
        else:
            self.lines.aml[0] = float(self.lines.aml[-1]) if len(self) > 1 else smooth


class FunctionalAwesomeOscillator(Indicator):
    """Awesome Oscillator: fast minus slow SMA of the median price."""

    lines = ("ao",)
    params = (
        ("fast", 5),
        ("slow", 34),
    )

    def __init__(self):
        """Build the fast and slow median-price moving averages."""
        median_price = (self.data.high + self.data.low) / 2.0
        self._fast = SimpleMovingAverage(median_price, period=self.p.fast)
        self._slow = SimpleMovingAverage(median_price, period=self.p.slow)

    def next(self):
        """Emit the fast/slow SMA difference for the current bar."""
        self.lines.ao[0] = float(self._fast[0]) - float(self._slow[0])


class AIAwesomeOscillator(Indicator):
    """Awesome Oscillator indicator using two SMAs on the price midpoint."""

    lines = ("ao",)
    params = (
        ("fast", 5),
        ("slow", 34),
    )

    def __init__(self):
        """Create fast and slow moving averages of the midpoint."""
        median = (self.data.high + self.data.low) / 2.0
        fast_ma = SimpleMovingAverage(median, period=self.p.fast)
        slow_ma = SimpleMovingAverage(median, period=self.p.slow)
        self.lines.ao = fast_ma - slow_ma


class BlauErgodicMDI(Indicator):
    """Calculate layered EMA histograms used as the Blau Ergodic MDI signal."""

    lines = ("up", "dn", "hist", "color_idx")
    params = (
        ("xlength", 20),
        ("xlength1", 5),
        ("xlength2", 5),
        ("xlength3", 5),
    )

    def __init__(self):
        """Initialize recursive EMA stages and expose indicator lines."""
        price = ExponentialMovingAverage(self.data.close, period=max(2, self.p.xlength))
        xprice = ExponentialMovingAverage(price, period=max(2, self.p.xlength1))
        dif = price - xprice
        xdif = ExponentialMovingAverage(dif, period=max(2, self.p.xlength1))
        xxdif = ExponentialMovingAverage(xdif, period=max(2, self.p.xlength2))
        xxxdif = ExponentialMovingAverage(xxdif, period=max(2, self.p.xlength3))
        self.lines.hist = xxdif
        self.lines.up = xxdif
        self.lines.dn = xxxdif
        self.addminperiod(self.p.xlength + self.p.xlength1 + self.p.xlength2 + self.p.xlength3 + 2)


class BlauErgodicMDIClassic(Indicator):
    """Ergodic MDI indicator with up/down/histogram smoothing channels."""

    lines = ("up", "down", "hist")
    params = (
        ("xlength", 20),
        ("xlength1", 5),
        ("xlength2", 3),
        ("xlength3", 8),
        ("ipc", "close"),
    )

    def __init__(self):
        """Build normalized price deviation and EMA-smoothed up/down/histogram lines."""
        price = _price_series(self.data, self.p.ipc)
        xprice = EMA(price, period=int(self.p.xlength))
        dif = (price - xprice) / 0.01
        xdif = EMA(dif, period=int(self.p.xlength1))
        xxdif = EMA(xdif, period=int(self.p.xlength2))
        xxxdif = EMA(xxdif, period=int(self.p.xlength3))
        self.l.hist = xxdif
        self.l.up = xxdif
        self.l.down = xxxdif


class BrakeExpIndicator(Indicator):
    """Exponential trailing-stop indicator with trend and flip lines.

    Maintains an exponential-curve stop that rises while long (and falls while
    short) from a begin price; when price breaks the stop the direction flips.
    Exposes the active stop on ``up_trend``/``down_trend`` lines and
    direction-flip cues on ``buy_signal``/``sell_signal`` lines.
    """

    lines = ("up_trend", "down_trend", "buy_signal", "sell_signal")
    params = (
        ("a", 3.0),
        ("b", 1.0),
    )

    def __init__(self):
        """Set the minimum period and initialize the exponential-stop state."""
        self.addminperiod(5)
        self._is_long = True
        self._max_price = float("-inf")
        self._min_price = float("inf")
        self._begin_bar = 0
        self._begin_price = None

    def next(self):
        """Advance the exponential stop and emit trend and flip lines.

        Extends the stop along the exponential curve, flips direction (resetting
        the begin price and extremes) when price breaks the stop, and sets the
        ``up_trend``/``down_trend`` lines plus ``buy_signal``/``sell_signal`` flip
        cues for the bar.
        """
        if self._begin_price is None:
            self._begin_price = float(self.data.low[0])
        self._max_price = max(self._max_price, float(self.data.high[0]))
        self._min_price = min(self._min_price, float(self.data.low[0]))
        bars_since_begin = max(0, len(self.data) - 1 - self._begin_bar)
        a = float(self.p.a) * 0.1
        b = float(self.p.b) * 0.00001
        exp_val = (math.exp(bars_since_begin * a) - 1.0) * b
        value = self._begin_price + exp_val if self._is_long else self._begin_price - exp_val
        if self._is_long and value > float(self.data.low[0]):
            self._is_long = False
            self._begin_price = self._max_price
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float("-inf")
            self._min_price = float("inf")
        elif (not self._is_long) and value < float(self.data.high[0]):
            self._is_long = True
            self._begin_price = self._min_price
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float("-inf")
            self._min_price = float("inf")
        prev_up = float(self.lines.up_trend[-1]) if len(self) > 0 else 0.0
        prev_dn = float(self.lines.down_trend[-1]) if len(self) > 0 else 0.0
        if self._is_long:
            self.lines.up_trend[0] = value
            self.lines.down_trend[0] = 0.0
        else:
            self.lines.up_trend[0] = 0.0
            self.lines.down_trend[0] = value
        self.lines.buy_signal[0] = (
            self.lines.down_trend[0]
            if prev_up > 0.0 and float(self.lines.down_trend[0]) > 0.0
            else 0.0
        )
        self.lines.sell_signal[0] = (
            self.lines.up_trend[0] if prev_dn > 0.0 and float(self.lines.up_trend[0]) > 0.0 else 0.0
        )


class FlatTrendIndicator(Indicator):
    """Flat-trend regime indicator combining ADX/DI and Parabolic SAR.

    Emits four binary lines (``buy``, ``sell``, ``end_buy``, ``end_sell``) that
    classify each bar's trend state from the SAR position relative to price and
    the dominance of the positive over the negative directional indicator.
    """

    lines = ("sell", "buy", "end_sell", "end_buy")

    def __init__(self):
        """Build the ADX, +DI, -DI and Parabolic SAR sub-indicators.

        Also sets the minimum period to 20 bars so the directional and SAR
        components have enough history before producing signals.
        """
        self.adx = AverageDirectionalMovementIndex(self.data)
        self.di_plus = PlusDirectionalIndicator(self.data)
        self.di_minus = MinusDirectionalIndicator(self.data)
        self.sar = ParabolicSAR(self.data)
        self.addminperiod(20)

    def next(self):
        """Classify the current bar into a buy/sell/end-of-trend state.

        Sets exactly one of the four output lines to 1.0 based on whether the
        SAR sits below price (uptrend context) and whether +DI exceeds -DI.
        """
        sell = buy = end_sell = end_buy = 0.0
        if self.sar[0] < self.data.close[0]:
            if self.di_plus[0] > self.di_minus[0]:
                buy = 1.0
            else:
                end_buy = 1.0
        else:
            if self.di_plus[0] > self.di_minus[0]:
                end_sell = 1.0
            else:
                sell = 1.0
        self.lines.sell[0] = sell
        self.lines.buy[0] = buy
        self.lines.end_sell[0] = end_sell
        self.lines.end_buy[0] = end_buy


class FlatTrendDistanceIndicator(Indicator):
    """Volatility-regime classifier from smoothed ATR and standard-deviation slopes.

    Compares the slopes of smoothed ATR and smoothed standard deviation to emit a
    ``state`` line flagging rising, falling, or flat volatility.
    """

    lines = ("state",)
    params = (
        ("stdev_period", 20),
        ("stdev_method", "lwma"),
        ("stdev_length", 5),
        ("stdev_phase", 15),
        ("atr_period", 20),
        ("atr_method", "lwma"),
        ("atr_length", 5),
        ("atr_phase", 15),
    )

    def __init__(self):
        """Construct smoothed ATR and standard-deviation components, set min period."""
        self._atr = AverageTrueRange(self.data, period=max(1, int(self.p.atr_period)))
        self._std = StandardDeviation(self.data.close, period=max(1, int(self.p.stdev_period)))
        atr_ma = resolve_ma_class(self.p.atr_method)
        std_ma = resolve_ma_class(self.p.stdev_method)
        self._xatr = atr_ma(self._atr, period=max(1, int(self.p.atr_length)))
        self._xstd = std_ma(self._std, period=max(1, int(self.p.stdev_length)))
        self.addminperiod(
            max(
                int(self.p.atr_period) + int(self.p.atr_length),
                int(self.p.stdev_period) + int(self.p.stdev_length),
            )
            + 3
        )

    def next(self):
        """Classify the current volatility regime from ATR/stdev slope direction."""
        prev_xatr = float(self._xatr[-1])
        prev_xstd = float(self._xstd[-1])
        xatr = float(self._xatr[0])
        xstd = float(self._xstd[0])
        res = 0
        if prev_xatr > xatr and prev_xstd > xstd:
            res = 1
        if prev_xatr < xatr and prev_xstd < xstd:
            res = 2
        self.lines.state[0] = res + 1


class IinMASignalIndicator(Indicator):
    """Cross-period MA signal indicator producing buy/sell trigger levels."""

    lines = ("buy_signal", "sell_signal")
    params = (
        ("fast_period", 10),
        ("fast_ma", "EMA"),
        ("slow_period", 22),
        ("slow_ma", "SMA"),
        ("atr_period", 10),
    )

    def __init__(self):
        """Initialize fast/slow MAs and internal trend state."""
        ma_map = {
            "SMA": SimpleMovingAverage,
            "EMA": ExponentialMovingAverage,
            "SMMA": SmoothedMovingAverage,
            "WMA": WeightedMovingAverage,
        }
        fast_cls = ma_map.get(str(self.p.fast_ma).upper(), ExponentialMovingAverage)
        slow_cls = ma_map.get(str(self.p.slow_ma).upper(), SimpleMovingAverage)
        self.fast_ma = fast_cls(self.data.close, period=self.p.fast_period)
        self.slow_ma = slow_cls(self.data.close, period=self.p.slow_period)
        self._trend = 0
        self.addminperiod(max(self.p.fast_period, self.p.slow_period) + self.p.atr_period + 3)

    def next(self):
        """Detect MA transitions and write conditional trigger levels."""
        buy_signal = 0.0
        sell_signal = 0.0
        fast_now = float(self.fast_ma[0])
        fast_prev = float(self.fast_ma[-1])
        slow_now = float(self.slow_ma[0])
        slow_prev = float(self.slow_ma[-1])
        avg_range = 0.0
        for idx in range(self.p.atr_period):
            avg_range += abs(float(self.data.high[-idx]) - float(self.data.low[-idx]))
        avg_range /= float(self.p.atr_period)
        if self._trend <= 0 and fast_now > slow_now and fast_prev < slow_prev:
            buy_signal = float(self.data.low[0]) - avg_range * 0.5
            self._trend = 1
        if self._trend >= 0 and fast_now < slow_now and fast_prev > slow_prev:
            sell_signal = float(self.data.high[0]) + avg_range * 0.5
            self._trend = -1
        self.lines.buy_signal[0] = buy_signal
        self.lines.sell_signal[0] = sell_signal


class KDJ(Indicator):
    """KDJ (Stochastic) Technical Indicator.

    The KDJ indicator is a momentum oscillator that compares a specific closing
    price of a security to a range of its prices over a certain period of time.
    It consists of three lines: K, D, and J, where K and D are similar to the
    Stochastic oscillator, and J is a derivative line.

    The indicator is calculated using the StochasticFull indicator as the base,
    with J calculated as: J = 3*K - 2*D.

    Refactoring Note:
        Uses the next() method instead of line binding (self.l.K = self.kd.percD)
        because line binding has idx synchronization issues in the current
        architecture.

    Attributes:
        lines: Tuple containing ('K', 'D', 'J') - the three output lines.
        params: Tuple containing configuration parameters:
            - period (int): Lookback period for Stochastic calculation (default: 9).
            - period_dfast (int): Fast %D smoothing period (default: 3).
            - period_dslow (int): Slow %D smoothing period (default: 3).
        kd (StochasticFull): Internal StochasticFull indicator instance.
    """

    lines = ("K", "D", "J")

    params = (
        ("period", 9),
        ("period_dfast", 3),
        ("period_dslow", 3),
    )

    def __init__(self):
        """Initialize the KDJ indicator with a StochasticFull base.

        Creates a StochasticFull indicator with the configured parameters
        to serve as the foundation for K, D, and J line calculations.
        """
        self.kd = StochasticFull(
            self.data,
            period=self.p.period,
            period_dfast=self.p.period_dfast,
            period_dslow=self.p.period_dslow,
        )

    def next(self):
        """Calculate KDJ values for the current bar.

        Updates the K, D, and J lines based on the underlying StochasticFull
        indicator values. The J line is derived from K and D using the
        formula: J = 3*K - 2*D.
        """
        self.l.K[0] = self.kd.percD[0]
        self.l.D[0] = self.kd.percDSlow[0]
        self.l.J[0] = self.l.K[0] * 3 - self.l.D[0] * 2


class LaguerreIndicator(Indicator):
    """Laguerre RSI-style oscillator over a four-stage Laguerre filter."""

    lines = ("laguerre",)
    params = (("gamma", 0.7),)

    def __init__(self):
        """Set the minimum period and initialize Laguerre filter state."""
        self.addminperiod(2)
        self._l0 = None
        self._l1 = None
        self._l2 = None
        self._l3 = None

    def next(self):
        """Advance the Laguerre filter and emit the oscillator value."""
        price = float(self.data.close[0])
        gamma = self.p.gamma
        if self._l0 is None:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price

        l0_prev = self._l0
        l1_prev = self._l1
        l2_prev = self._l2
        l3_prev = self._l3

        l0 = (1.0 - gamma) * price + gamma * l0_prev
        l1 = -gamma * l0 + l0_prev + gamma * l1_prev
        l2 = -gamma * l1 + l1_prev + gamma * l2_prev
        l3 = -gamma * l2 + l2_prev + gamma * l3_prev

        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2

        self.lines.laguerre[0] = cu / (cu + cd) if (cu + cd) else 0.0
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3


class LaguerreColorIndicator(Indicator):
    """Ehlers Laguerre RSI oscillator with high/low colour-state transitions."""

    lines = ("value", "color_state")
    params = (
        ("gamma", 0.7),
        ("high_level", 85),
        ("middle_level", 50),
        ("low_level", 15),
    )

    def __init__(self):
        """Initialize the Laguerre filter stages and minimum period."""
        self._l0 = 0.0
        self._l1 = 0.0
        self._l2 = 0.0
        self._l3 = 0.0
        self._initialized = False
        self.addminperiod(3)

    def _zone(self, value):
        if value > float(self.p.high_level):
            return "high"
        if value > float(self.p.middle_level):
            return "high_mid"
        if value < float(self.p.low_level):
            return "low"
        return "low_mid"

    def _color_from_state(self, curr_zone, prev_zone, prev_color):
        if curr_zone == "high":
            return 1.0
        if curr_zone == "high_mid":
            if prev_zone == "high":
                return 2.0
            if prev_zone == "high_mid":
                return prev_color
            return 1.0
        if curr_zone == "low_mid":
            if prev_zone in ("high", "high_mid"):
                return 2.0
            if prev_zone == "low_mid":
                return prev_color
            return 1.0
        if curr_zone == "low":
            return 2.0
        return prev_color

    def next(self):
        """Advance the Laguerre filter and update the value/colour lines."""
        price = float(self.data.close[0])
        gamma = float(self.p.gamma)
        prev_l0, prev_l1, prev_l2, prev_l3 = self._l0, self._l1, self._l2, self._l3

        if not self._initialized:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price
            self._initialized = True
        else:
            self._l0 = (1.0 - gamma) * price + gamma * prev_l0
            self._l1 = -gamma * self._l0 + prev_l0 + gamma * prev_l1
            self._l2 = -gamma * self._l1 + prev_l1 + gamma * prev_l2
            self._l3 = -gamma * self._l2 + prev_l2 + gamma * prev_l3

        cu = 0.0
        cd = 0.0
        pairs = ((self._l0, self._l1), (self._l1, self._l2), (self._l2, self._l3))
        for a, b in pairs:
            if a >= b:
                cu += a - b
            else:
                cd += b - a
        value = 0.0
        if (cu + cd) > 1e-12:
            value = 100.0 * cu / (cu + cd)

        prev_value = float(self.lines.value[-1]) if len(self) > 1 else value
        prev_color = float(self.lines.color_state[-1]) if len(self) > 1 else 1.0
        curr_zone = self._zone(value)
        prev_zone = self._zone(prev_value)
        color = self._color_from_state(curr_zone, prev_zone, prev_color)

        self.lines.value[0] = value
        self.lines.color_state[0] = color


class RelativeVigorIndex(Indicator):
    """Relative Vigor Index (RVI) with its 4-point symmetric signal line."""

    lines = ("rvi", "signal")
    params = (("period", 44),)

    def __init__(self):
        """Reserve enough warm-up bars for the period plus the 4-bar weighting."""
        self.addminperiod(self.p.period + 6)

    def next(self):
        """Compute the RVI ratio and its weighted signal value for the current bar."""
        numerator_sum = 0.0
        denominator_sum = 0.0
        for shift in range(self.p.period):
            close0 = float(self.data.close[-shift])
            open0 = float(self.data.open[-shift])
            close1 = float(self.data.close[-shift - 1])
            open1 = float(self.data.open[-shift - 1])
            close2 = float(self.data.close[-shift - 2])
            open2 = float(self.data.open[-shift - 2])
            close3 = float(self.data.close[-shift - 3])
            open3 = float(self.data.open[-shift - 3])
            high0 = float(self.data.high[-shift])
            low0 = float(self.data.low[-shift])
            high1 = float(self.data.high[-shift - 1])
            low1 = float(self.data.low[-shift - 1])
            high2 = float(self.data.high[-shift - 2])
            low2 = float(self.data.low[-shift - 2])
            high3 = float(self.data.high[-shift - 3])
            low3 = float(self.data.low[-shift - 3])
            numerator_sum += (
                (close0 - open0)
                + 2.0 * (close1 - open1)
                + 2.0 * (close2 - open2)
                + (close3 - open3)
            ) / 6.0
            denominator_sum += (
                (high0 - low0) + 2.0 * (high1 - low1) + 2.0 * (high2 - low2) + (high3 - low3)
            ) / 6.0
        rvi_value = numerator_sum / denominator_sum if denominator_sum else 0.0
        self.lines.rvi[0] = rvi_value
        if len(self) >= 4:
            values = [
                float(self.lines.rvi[0]),
                float(self.lines.rvi[-1]),
                float(self.lines.rvi[-2]),
                float(self.lines.rvi[-3]),
            ]
            if all(math.isfinite(value) for value in values):
                self.lines.signal[0] = (
                    values[0] + 2.0 * values[1] + 2.0 * values[2] + values[3]
                ) / 6.0
            else:
                self.lines.signal[0] = rvi_value
        else:
            self.lines.signal[0] = rvi_value


class SmoothedRelativeVigorIndex(Indicator):
    """Relative Vigor Index indicator with smoothed signal line."""

    lines = ("rvi", "signal")
    params = (("period", 13),)

    def __init__(self):
        """Compute weighted numerator/denominator and moving-average filtered lines."""
        weighted_num = (
            (self.data.close - self.data.open)
            + 2.0 * (self.data.close(-1) - self.data.open(-1))
            + 2.0 * (self.data.close(-2) - self.data.open(-2))
            + (self.data.close(-3) - self.data.open(-3))
        ) / 6.0
        weighted_den = (
            (self.data.high - self.data.low)
            + 2.0 * (self.data.high(-1) - self.data.low(-1))
            + 2.0 * (self.data.high(-2) - self.data.low(-2))
            + (self.data.high(-3) - self.data.low(-3))
        ) / 6.0
        num_ma = SimpleMovingAverage(weighted_num, period=self.p.period)
        den_ma = SimpleMovingAverage(weighted_den, period=self.p.period)
        self.lines.rvi = If(den_ma != 0, num_ma / den_ma, 0.0)
        self.lines.signal = (
            self.lines.rvi
            + 2.0 * self.lines.rvi(-1)
            + 2.0 * self.lines.rvi(-2)
            + self.lines.rvi(-3)
        ) / 6.0


class SafeCCI(Indicator):
    """Safe Commodity Channel Index indicator with guarded zero-variance handling."""

    lines = ("cci",)
    params = (("period", 14),)

    def __init__(self):
        """Initialize CCI period warm-up requirement."""
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Compute CCI value for the current bar with mean deviation protection."""
        typical_prices = []
        for idx in range(self.p.period):
            typical_prices.append(
                (
                    float(self.data.high[-idx])
                    + float(self.data.low[-idx])
                    + float(self.data.close[-idx])
                )
                / 3.0
            )
        tp_now = typical_prices[0]
        tp_sma = sum(typical_prices) / float(len(typical_prices))
        mean_dev = sum(abs(tp - tp_sma) for tp in typical_prices) / float(len(typical_prices))
        if mean_dev <= 1e-12:
            self.lines.cci[0] = 0.0
            return
        self.lines.cci[0] = (tp_now - tp_sma) / (0.015 * mean_dev)


class SafeCCIWithFactor(Indicator):
    """CCI indicator with mean deviation, returning 0.0 when denominator is zero."""

    lines = ("cci",)
    params = (
        ("period", 27),
        ("factor", 0.015),
    )

    def __init__(self):
        """Initialise SafeCCI and set minimum period to `period`."""
        self.addminperiod(self.p.period)

    def next(self):
        """Compute CCI from rolling typical-price SMA and mean deviation."""
        period = self.p.period
        typical_prices = [
            (float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i]))
            / 3.0
            for i in range(period)
        ]
        sma = sum(typical_prices) / period
        mean_dev = sum(abs(tp - sma) for tp in typical_prices) / period
        current_tp = typical_prices[0]
        denominator = self.p.factor * mean_dev
        self.lines.cci[0] = 0.0 if denominator == 0.0 else (current_tp - sma) / denominator


class SilverTrendSignalProxy(Indicator):
    """SilverTrend buy/sell signal proxy based on a moving-average crossover.

    Emits a non-zero ``buy`` (or ``sell``) value when price crosses above (or
    below) a risk-scaled simple moving average, mirroring the EA's signal lines.
    """

    lines = ("buy", "sell")
    params = (("risk", 3),)

    def __init__(self):
        """Build the risk-scaled moving average and set the minimum period."""
        self.period = max(3, int(self.p.risk) * 2 + 1)
        self.ma = SimpleMovingAverage(self.data.close, period=self.period)
        self.addminperiod(self.period + 3)

    def next(self):
        """Set buy/sell signal lines from the price/MA crossover this bar."""
        buy = 0.0
        sell = 0.0
        close0 = float(self.data.close[0])
        close1 = float(self.data.close[-1])
        ma0 = float(self.ma[0])
        ma1 = float(self.ma[-1])
        if close1 <= ma1 and close0 > ma0:
            buy = close0
        elif close1 >= ma1 and close0 < ma0:
            sell = close0
        self.lines.buy[0] = buy
        self.lines.sell[0] = sell


class SilverTrendDirectionSignalProxy(Indicator):
    """Proxy indicator emitting +1/-1 on SMA crossover direction flips."""

    lines = ("signal",)
    params = (("risk", 3),)

    def __init__(self):
        """Set up the SMA and minimum period from the risk parameter."""
        self.period = max(3, int(self.p.risk) * 2 + 1)
        self.ma = SimpleMovingAverage(self.data.close, period=self.period)
        self.addminperiod(self.period + 2)

    def next(self):
        """Carry the prior signal forward, flipping it on a fresh MA crossover."""
        signal = float(self.lines.signal[-1]) if len(self) > 0 else 0.0
        if not math.isfinite(signal):
            signal = 0.0
        close_prev = float(self.data.close[-1])
        close_now = float(self.data.close[0])
        ma_prev = float(self.ma[-1])
        ma_now = float(self.ma[0])
        if close_prev <= ma_prev and close_now > ma_now:
            signal = 1.0
        elif close_prev >= ma_prev and close_now < ma_now:
            signal = -1.0
        self.lines.signal[0] = signal
