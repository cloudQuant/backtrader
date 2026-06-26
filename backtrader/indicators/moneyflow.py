#!/usr/bin/env python
"""Money flow indicators migrated from functional strategy tests."""

from . import Indicator
from .atr import ATR

__all__ = [
    "DeltaMFI",
    "MFI",
    "MFIHistogramIndicator",
    "MFISlowdown",
    "MoneyFlowIndex",
]


class MoneyFlowIndex(Indicator):
    """Money Flow Index using a current-inclusive lookback window."""

    lines = ("mfi",)
    params = (("period", 14),)

    def __init__(self):
        """Register the rolling window size needed for the MFI calculation."""
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Compute the Money Flow Index for the current bar.

        Walks the most recent ``period`` bars (current inclusive), sums
        the positive raw money flow (typical price rising) and the
        negative raw money flow (typical price falling) where the raw
        flow is ``typical_price * volume``. The MFI is then written as
        ``100 - 100 / (1 + positive/negative)``; when no negative flow
        is observed, the indicator is saturated at ``100.0``.
        """
        positive_flow = 0.0
        negative_flow = 0.0
        for i in range(self.p.period):
            curr_tp = (
                float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i])
            ) / 3.0
            prev_tp = (
                float(self.data.high[-i - 1])
                + float(self.data.low[-i - 1])
                + float(self.data.close[-i - 1])
            ) / 3.0
            raw_flow = curr_tp * float(self.data.volume[-i])
            if curr_tp > prev_tp:
                positive_flow += raw_flow
            elif curr_tp < prev_tp:
                negative_flow += raw_flow

        if negative_flow == 0.0:
            self.lines.mfi[0] = 100.0
        else:
            money_ratio = positive_flow / negative_flow
            self.lines.mfi[0] = 100.0 - (100.0 / (1.0 + money_ratio))


class MFI(Indicator):
    """Money Flow Index variant using the previous completed window.

    Some functional strategies historically calculated MFI over
    ``range(-period, 0)`` instead of including bar 0. This class preserves
    that behavior and is intentionally not an alias of ``MoneyFlowIndex``.
    """

    lines = ("mfi",)
    params = (("period", 14),)

    def __init__(self):
        """Register the rolling window size needed for the MFI calculation."""
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Compute MFI over the previous ``period`` bars (not the current bar).

        Unlike :class:`MoneyFlowIndex`, the loop indexes
        ``range(-period, 0)`` so the current bar is excluded from the
        window. The positive/negative flow split and saturation rule
        are otherwise identical. This preserves the historical
        functional-strategy behavior.
        """
        period = self.p.period
        pos_flow = 0.0
        neg_flow = 0.0
        for i in range(-period, 0):
            tp_cur = (
                float(self.data.high[i]) + float(self.data.low[i]) + float(self.data.close[i])
            ) / 3.0
            tp_prev = (
                float(self.data.high[i - 1])
                + float(self.data.low[i - 1])
                + float(self.data.close[i - 1])
            ) / 3.0
            mf = tp_cur * float(self.data.volume[i])
            if tp_cur > tp_prev:
                pos_flow += mf
            elif tp_cur < tp_prev:
                neg_flow += mf

        if neg_flow == 0:
            self.lines.mfi[0] = 100.0
        else:
            ratio = pos_flow / neg_flow
            self.lines.mfi[0] = 100.0 - 100.0 / (1.0 + ratio)


class DeltaMFI(Indicator):
    """Difference between two current-inclusive MFI periods plus color state."""

    lines = ("color", "delta")
    params = {"mfi_period1": 14, "mfi_period2": 50, "level": 50}

    def __init__(self):
        """Set up the two MFI sub-indicators and the regime thresholds."""
        self.addminperiod(max(int(self.p.mfi_period1), int(self.p.mfi_period2)) + 3)
        self.mfi1 = MoneyFlowIndex(self.data, period=int(self.p.mfi_period1))
        self.mfi2 = MoneyFlowIndex(self.data, period=int(self.p.mfi_period2))
        lvl = int(self.p.level)
        self.max_level = 100 - (100 - lvl)
        self.min_level = 100 - lvl

    def next(self):
        """Compute the MFI delta and assign a regime color.

        Writes ``mfi_fast - mfi_slow`` to ``self.lines.delta`` and
        colors ``0.0`` when the slow MFI is above the upper threshold
        and the fast MFI is climbing, ``2.0`` when the slow MFI is
        below the lower threshold and the fast MFI is falling, and
        ``1.0`` (neutral) otherwise.
        """
        m1 = float(self.mfi1[0])
        m2 = float(self.mfi2[0])
        self.lines.delta[0] = m1 - m2
        color = 1.0
        if m2 > self.max_level and m1 > m2:
            color = 0.0
        if m2 < self.min_level and m1 < m2:
            color = 2.0
        self.lines.color[0] = color


class MFISlowdown(Indicator):
    """MFI extreme signal generator with optional slowdown detection."""

    lines = ("sell", "buy")
    params = {"mfi_period": 2, "level_max": 90.0, "level_min": 10.0, "seek_slowdown": True}

    def __init__(self):
        """Set up the MFI and ATR sub-indicators and the minimum period."""
        self.addminperiod(max(int(self.p.mfi_period) + 2, 18))
        self.mfi = MoneyFlowIndex(self.data, period=int(self.p.mfi_period))
        self.atr = ATR(self.data, period=15)

    def next(self):
        """Emit ATR-buffered stop levels when MFI touches an extreme.

        When ``seek_slowdown`` is enabled, a signal is only produced if
        the MFI's previous bar value differs from the current value by
        less than ``1.0`` (i.e. the MFI is stalling at the extreme).
        The buy line is placed ``atr * 3/8`` below the low, and the
        sell line ``atr * 3/8`` above the high. Lines are ``NaN`` when
        no signal is produced.
        """
        self.lines.buy[0] = float("nan")
        self.lines.sell[0] = float("nan")
        m0 = float(self.mfi[0])
        m1 = float(self.mfi[-1])
        atr = float(self.atr[0])
        if m0 >= float(self.p.level_max):
            if (not self.p.seek_slowdown) or abs(m1 - m0) < 1.0:
                self.lines.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if m0 <= float(self.p.level_min):
            if (not self.p.seek_slowdown) or abs(m1 - m0) < 1.0:
                self.lines.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0


class MFIHistogramIndicator(Indicator):
    """MFI value, midpoint and color-state histogram."""

    lines = ("value", "midline", "color_state")
    params = {"mfi_period": 14, "high_level": 60, "low_level": 40}

    def __init__(self):
        """Register the minimum period needed for the MFI lookback."""
        self.addminperiod(self.p.mfi_period + 1)

    def next(self):
        """Write the MFI value, the 50 midline and the regime color.

        For the first ``mfi_period`` bars the output is the neutral
        ``(50.0, 50.0, 1.0)`` triple. After the buffer is warm, the
        MFI is computed from typical prices and volume, falling back to
        ``50.0`` when there is no flow information. The color is
        ``0.0`` above ``high_level``, ``2.0`` below ``low_level``, and
        ``1.0`` (neutral) in between.
        """
        if len(self.data) <= self.p.mfi_period:
            self.lines.value[0] = 50.0
            self.lines.midline[0] = 50.0
            self.lines.color_state[0] = 1.0
            return

        positive_flow = 0.0
        negative_flow = 0.0
        for ago in range(self.p.mfi_period):
            high = float(self.data.high[-ago])
            low = float(self.data.low[-ago])
            close = float(self.data.close[-ago])
            prev_high = float(self.data.high[-ago - 1])
            prev_low = float(self.data.low[-ago - 1])
            prev_close = float(self.data.close[-ago - 1])
            volume = float(self.data.volume[-ago])
            typical = (high + low + close) / 3.0
            prev_typical = (prev_high + prev_low + prev_close) / 3.0
            raw_money_flow = typical * volume
            if typical > prev_typical:
                positive_flow += raw_money_flow
            elif typical < prev_typical:
                negative_flow += raw_money_flow

        if negative_flow <= 1e-12:
            mfi_value = 100.0 if positive_flow > 0 else 50.0
        else:
            money_ratio = positive_flow / negative_flow
            mfi_value = 100.0 - (100.0 / (1.0 + money_ratio))

        color = 1.0
        if mfi_value > float(self.p.high_level):
            color = 0.0
        elif mfi_value < float(self.p.low_level):
            color = 2.0

        self.lines.value[0] = mfi_value
        self.lines.midline[0] = 50.0
        self.lines.color_state[0] = color
