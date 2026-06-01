#!/usr/bin/env python
"""SuperTrend indicator variants migrated from functional tests."""

from . import Indicator
from .atr import ATR
from .ema import EMA

__all__ = [
    "AdaptiveSuperTrendIndicator",
    "SuperTrendBandIndicator",
    "SuperTrendBandsIndicator",
    "SuperTrendCCIIndicator",
    "SuperTrendIndicator",
    "SupertrendIndicator",
]


class SuperTrendIndicator(Indicator):
    """Classic SuperTrend with ``supertrend`` and ``direction`` lines."""

    lines = ("supertrend", "direction")
    params = {"period": 10, "multiplier": 3.0}

    def __init__(self):
        self.atr = ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0

    def next(self):
        if len(self) < self.p.period + 1:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            return

        atr = self.atr[0]
        hl2 = self.hl2[0]
        upper_band = hl2 + self.p.multiplier * atr
        lower_band = hl2 - self.p.multiplier * atr
        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]

        if prev_direction == 1:
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        else:
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


class SuperTrendBandIndicator(Indicator):
    """ATR SuperTrend variant with persistent upper/lower bands."""

    lines = ("supertrend", "direction")
    params = (("atr_period", 10), ("multiplier", 3.0))

    def __init__(self):
        self.atr = ATR(self.data, period=self.p.atr_period)
        self._upper = None
        self._lower = None
        self._dir = 1

    def next(self):
        hl2 = (float(self.data.high[0]) + float(self.data.low[0])) / 2.0
        atr_val = float(self.atr[0])
        up = hl2 + self.p.multiplier * atr_val
        dn = hl2 - self.p.multiplier * atr_val

        if self._upper is not None:
            up = min(up, self._upper) if float(self.data.close[-1]) > self._upper else up
            dn = max(dn, self._lower) if float(self.data.close[-1]) < self._lower else dn

        close = float(self.data.close[0])
        if self._dir == 1:
            if close < dn:
                self._dir = -1
        else:
            if close > up:
                self._dir = 1

        self._upper = up
        self._lower = dn
        self.lines.supertrend[0] = dn if self._dir == 1 else up
        self.lines.direction[0] = float(self._dir)


class SuperTrendBandsIndicator(Indicator):
    """SuperTrend variant exposing final bands and trend state."""

    lines = ("st", "final_up", "final_dn", "trend")
    params = {"period": 20, "multiplier": 3.0}

    def __init__(self):
        self.atr = ATR(self.data, period=self.p.period)
        hl2 = (self.data.high + self.data.low) / 2.0
        self.basic_up = hl2 + self.p.multiplier * self.atr
        self.basic_dn = hl2 - self.p.multiplier * self.atr
        self.addminperiod(self.p.period + 1)

    def next(self):
        if len(self) == self.p.period + 1:
            self.final_up[0] = self.basic_up[0]
            self.final_dn[0] = self.basic_dn[0]
            self.trend[0] = 1
            self.st[0] = self.basic_dn[0]
            return

        prev_fu = self.final_up[-1]
        prev_fd = self.final_dn[-1]

        if self.basic_up[0] < prev_fu or self.data.close[-1] > prev_fu:
            self.final_up[0] = self.basic_up[0]
        else:
            self.final_up[0] = prev_fu

        if self.basic_dn[0] > prev_fd or self.data.close[-1] < prev_fd:
            self.final_dn[0] = self.basic_dn[0]
        else:
            self.final_dn[0] = prev_fd

        if self.data.close[0] > self.final_up[-1]:
            self.trend[0] = 1
        elif self.data.close[0] < self.final_dn[-1]:
            self.trend[0] = -1
        else:
            self.trend[0] = self.trend[-1]

        self.st[0] = self.final_dn[0] if self.trend[0] > 0 else self.final_up[0]


class SupertrendIndicator(Indicator):
    """SuperTrend variant exposing ``final_up`` and ``final_down`` lines."""

    lines = ("supertrend", "final_up", "final_down")
    params = {"atr_period": 14, "atr_multiplier": 3}
    plotinfo = {"subplot": False}

    def __init__(self):
        self.atr = ATR(self.data, period=self.p.atr_period)
        self.avg = (self.data.high + self.data.low) / 2
        self.basic_up = self.avg - self.p.atr_multiplier * self.atr
        self.basic_down = self.avg + self.p.atr_multiplier * self.atr

    def prenext(self):
        self.l.final_up[0] = 0
        self.l.final_down[0] = 0
        self.l.supertrend[0] = 0

    def next(self):
        if self.data.close[-1] > self.l.final_up[-1]:
            self.l.final_up[0] = max(self.basic_up[0], self.l.final_up[-1])
        else:
            self.l.final_up[0] = self.basic_up[0]

        if self.data.close[-1] < self.l.final_down[-1]:
            self.l.final_down[0] = min(self.basic_down[0], self.l.final_down[-1])
        else:
            self.l.final_down[0] = self.basic_down[0]

        if self.data.close[0] > self.l.final_down[-1]:
            self.l.supertrend[0] = self.l.final_up[0]
        elif self.data.close[0] < self.l.final_up[-1]:
            self.l.supertrend[0] = self.l.final_down[0]
        else:
            self.l.supertrend[0] = self.l.supertrend[-1]


class SuperTrendCCIIndicator(Indicator):
    """CCI/ATR SuperTrend variant exposing trend and signal buffers."""

    lines = ("trend_up", "trend_down", "sign_up", "sign_down")
    params = {"cci_period": 50, "atr_period": 5, "level": 0}

    def __init__(self):
        self._cci_period = int(self.p.cci_period)
        self._atr_period = int(self.p.atr_period)
        self._level = int(self.p.level)
        self._prev_tu = 0.0
        self._prev_td = 0.0
        self._prev_cci = 0.0
        self.addminperiod(max(self._cci_period, self._atr_period) + 2)

    def _calc_cci(self):
        period = self._cci_period
        tp_vals = []
        for i in range(period):
            h = float(self.data.high[-i])
            low_price = float(self.data.low[-i])
            c = float(self.data.close[-i])
            tp_vals.append((h + low_price + c) / 3.0)
        mean_tp = sum(tp_vals) / period
        mean_dev = sum(abs(v - mean_tp) for v in tp_vals) / period
        if mean_dev == 0:
            return 0.0
        return (tp_vals[0] - mean_tp) / (0.015 * mean_dev)

    def _calc_atr(self):
        period = self._atr_period
        total = 0.0
        for i in range(period):
            h = float(self.data.high[-i])
            low_price = float(self.data.low[-i])
            if i + 1 < len(self.data):
                pc = float(self.data.close[-(i + 1)])
                tr = max(h - low_price, abs(h - pc), abs(low_price - pc))
            else:
                tr = h - low_price
            total += tr
        return total / period

    def next(self):
        cci = self._calc_cci()
        atr = self._calc_atr()
        level = self._level
        tu = 0.0
        td = 0.0
        su = 0.0
        sd = 0.0
        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        if cci >= level and self._prev_cci < level:
            tu = self._prev_td
        if cci <= level and self._prev_cci > level:
            td = self._prev_tu
        if cci > level:
            tu = cur_low - atr
            if tu < self._prev_tu and self._prev_cci >= level:
                tu = self._prev_tu
        if cci < level:
            td = cur_high + atr
            if td > self._prev_td and self._prev_cci <= level:
                td = self._prev_td
        if self._prev_td != 0.0 and tu != 0.0:
            su = tu
        if self._prev_tu != 0.0 and td != 0.0:
            sd = td

        self._prev_cci = cci
        self._prev_tu = tu
        self._prev_td = td
        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.sign_up[0] = su
        self.lines.sign_down[0] = sd


class AdaptiveSuperTrendIndicator(Indicator):
    """Adaptive SuperTrend that dynamically adjusts multiplier from ATR."""

    lines = ("st",)
    params = {
        "period": 20,
        "vol_lookback": 20,
        "a_coef": 0.5,
        "b_coef": 2.0,
        "min_mult": 0.5,
        "max_mult": 3.0,
    }

    def __init__(self):
        self.atr = ATR(self.data, period=self.p.period)
        self.avg_atr = EMA(self.atr, period=self.p.vol_lookback)
        self.hl2 = (self.data.high + self.data.low) / 2.0
        self.updateminperiod(self.avg_atr._minperiod)

    def _calc_bands(self):
        atr_val = float(self.atr[0])
        avg_atr_val = float(self.avg_atr[0])
        if atr_val <= 0:
            atr_val = 0.0001
        base_mult = self.p.a_coef + self.p.b_coef * avg_atr_val
        base_mult = max(self.p.min_mult, min(self.p.max_mult, base_mult))
        dyn_mult = base_mult * (avg_atr_val / atr_val) if atr_val > 0 else base_mult
        dyn_mult = max(self.p.min_mult, min(self.p.max_mult, dyn_mult))
        hl2 = float(self.hl2[0])
        return hl2 + dyn_mult * atr_val, hl2 - dyn_mult * atr_val

    def nextstart(self):
        upper, _lower = self._calc_bands()
        self.l.st[0] = upper

    def next(self):
        upper, lower = self._calc_bands()
        prev_st = self.l.st[-1]
        if self.data.close[0] > prev_st:
            self.l.st[0] = max(lower, prev_st)
        else:
            self.l.st[0] = min(upper, prev_st)

    def preonce(self, start, end):
        pass

    def oncestart(self, start, end):
        pass

    def once(self, start, end):
        atr_array = self.atr.lines[0].array
        avg_atr_array = self.avg_atr.lines[0].array
        hl2_array = self.hl2.array
        close_array = self.data.close.array
        st_array = self.lines.st.array
        minperiod = self.avg_atr._minperiod
        actual_end = min(end, len(atr_array), len(avg_atr_array), len(hl2_array), len(close_array))
        while len(st_array) < actual_end:
            st_array.append(0.0)
        for i in range(minperiod - 1, actual_end):
            atr_val = float(atr_array[i])
            avg_atr_val = float(avg_atr_array[i])
            if atr_val <= 0:
                atr_val = 0.0001
            base_mult = self.p.a_coef + self.p.b_coef * avg_atr_val
            base_mult = max(self.p.min_mult, min(self.p.max_mult, base_mult))
            dyn_mult = base_mult * (avg_atr_val / atr_val) if atr_val > 0 else base_mult
            dyn_mult = max(self.p.min_mult, min(self.p.max_mult, dyn_mult))
            hl2 = float(hl2_array[i])
            upper = hl2 + dyn_mult * atr_val
            lower = hl2 - dyn_mult * atr_val
            if i == minperiod - 1:
                st_array[i] = upper
            else:
                prev_st = st_array[i - 1]
                close_val = float(close_array[i])
                if close_val > prev_st:
                    st_array[i] = max(lower, prev_st)
                else:
                    st_array[i] = min(upper, prev_st)
