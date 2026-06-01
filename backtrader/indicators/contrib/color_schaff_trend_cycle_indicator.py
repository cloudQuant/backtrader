#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "ColorSchaffTrendCycleIndicator",
]


def resolve_ma_class(name):
    """Resolve a moving-average selector into a Backtrader indicator class.

    Args:
        name: MA mode string.

    Returns:
        class: Backtrader MA indicator class.
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
    """Resolve a price series selection for indicator calculations.

    Args:
        data: Backtrader data feed.
        mode: Applied price mode string.

    Returns:
        backtrader line: Selected price series.
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
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class ColorSchaffTrendCycleIndicator(Indicator):
    """Custom indicator producing Schaff Trend Cycle value and color states."""

    lines = ("value", "color")
    params = (
        ("xma_method", "ema"),
        ("fast_xma", 23),
        ("slow_xma", 50),
        ("xphase", 15),
        ("applied_price", "price_close"),
        ("cycle", 10),
        ("high_level", 60),
        ("low_level", -60),
    )

    def __init__(self):
        """Initialize fast/slow MA dependencies and required history."""
        price_line = resolve_price_line(self.data, self.p.applied_price)
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._fast = ma_cls(price_line, period=max(1, int(self.p.fast_xma)))
        self._slow = ma_cls(price_line, period=max(1, int(self.p.slow_xma)))
        self.addminperiod(
            max(int(self.p.fast_xma), int(self.p.slow_xma)) + int(self.p.cycle) * 2 + 5
        )

    def next(self):
        """Advance indicator by one bar and compute `value`/`color` for that bar."""
        cycle = max(2, int(self.p.cycle))
        macd_vals = [float(self._fast[-i]) - float(self._slow[-i]) for i in range(cycle)]
        llv1 = min(macd_vals)
        hhv1 = max(macd_vals)
        prev_st = float(self.lines.value[-1]) if len(self) > 0 else 0.0
        if prev_st != prev_st:
            prev_st = 0.0
        cur_macd = macd_vals[0]
        st = ((cur_macd - llv1) / (hhv1 - llv1) * 100.0) if (hhv1 - llv1) != 0 else prev_st
        st = 0.5 * (st - prev_st) + prev_st if len(self) > 0 else st
        st_vals = [st]
        for i in range(1, cycle):
            value = float(self.lines.value[-i])
            if value == value:
                st_vals.append(value)
        llv2 = min(st_vals)
        hhv2 = max(st_vals)
        prev_stc = float(self.lines.value[-1]) if len(self) > 0 else 0.0
        if prev_stc != prev_stc:
            prev_stc = 0.0
        stc = ((st - llv2) / (hhv2 - llv2) * 200.0 - 100.0) if (hhv2 - llv2) != 0 else prev_stc
        stc = 0.5 * (stc - prev_stc) + prev_stc if len(self) > 0 else stc
        self.lines.value[0] = stc
        delta = stc - prev_stc if len(self) > 0 else 0.0
        color = 4
        if stc > 0:
            if stc > float(self.p.high_level):
                color = 7 if delta >= 0 else 6
            else:
                color = 5 if delta >= 0 else 4
        if stc < 0:
            if stc < float(self.p.low_level):
                color = 0 if delta < 0 else 1
            else:
                color = 2 if delta < 0 else 3
        self.lines.color[0] = color

    def once(self, start, end):
        """Compute indicator output in vectorized mode for backtest startup."""
        fast_array = self._fast.array
        slow_array = self._slow.array
        value_line = self.lines.value.array
        color_line = self.lines.color.array
        for line in (value_line, color_line):
            while len(line) < end:
                line.append(float("nan"))

        cycle = max(2, int(self.p.cycle))
        prev_value = None
        actual_end = min(end, len(fast_array), len(slow_array))
        for i in range(start, actual_end):
            macd_vals = [
                float(fast_array[i - j]) - float(slow_array[i - j])
                for j in range(cycle)
                if i - j >= 0
            ]
            llv1 = min(macd_vals)
            hhv1 = max(macd_vals)
            prev_st = 0.0 if prev_value is None else prev_value
            cur_macd = macd_vals[0]
            st = ((cur_macd - llv1) / (hhv1 - llv1) * 100.0) if (hhv1 - llv1) != 0 else prev_st
            if prev_value is not None:
                st = 0.5 * (st - prev_st) + prev_st

            st_vals = [st]
            for j in range(1, cycle):
                idx = i - j
                if idx < start:
                    break
                st_vals.append(float(value_line[idx]))
            llv2 = min(st_vals)
            hhv2 = max(st_vals)
            prev_stc = 0.0 if prev_value is None else prev_value
            stc = ((st - llv2) / (hhv2 - llv2) * 200.0 - 100.0) if (hhv2 - llv2) != 0 else prev_stc
            if prev_value is not None:
                stc = 0.5 * (stc - prev_stc) + prev_stc

            delta = stc - prev_stc if prev_value is not None else 0.0
            color = 4
            if stc > 0:
                if stc > float(self.p.high_level):
                    color = 7 if delta >= 0 else 6
                else:
                    color = 5 if delta >= 0 else 4
            if stc < 0:
                if stc < float(self.p.low_level):
                    color = 0 if delta < 0 else 1
                else:
                    color = 2 if delta < 0 else 3
            value_line[i] = stc
            color_line[i] = color
            prev_value = stc
