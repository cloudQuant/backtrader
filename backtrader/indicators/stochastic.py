#!/usr/bin/env python
import math
from . import DivByZero, Highest, Indicator, Lowest, MovAv


# kdj随机指标
class _StochasticBase(Indicator):
    lines = (
        "percK",
        "percD",
    )
    params = (
        ("period", 14),
        ("period_dfast", 3),
        ("movav", MovAv.Simple),
        ("upperband", 80.0),
        ("lowerband", 20.0),
        ("safediv", False),
        ("safezero", 0.0),
    )

    plotlines = dict(percD=dict(_name="%D", ls="--"), percK=dict(_name="%K"))

    def _plotlabel(self):
        plabels = [self.p.period, self.p.period_dfast]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines = [self.p.upperband, self.p.lowerband]

    def __init__(self):
        super().__init__()
        self.highesthigh = Highest(self.data.high, period=self.p.period)
        self.lowestlow = Lowest(self.data.low, period=self.p.period)

    def _calc_k(self):
        """Calculate %K value"""
        hh = self.highesthigh[0]
        ll = self.lowestlow[0]
        close = self.data.close[0]
        knum = close - ll
        kden = hh - ll
        if self.p.safediv and kden == 0:
            return self.p.safezero
        if kden == 0:
            return 0.0
        return 100.0 * (knum / kden)


class StochasticFast(_StochasticBase):
    """
    By Dr. George Lane in the 50s. It compares a closing price to the price
    range and tries to show convergence if the closing prices are close to the
    extremes

      - It will go up if closing prices are close to the highs
      - It will roughly go down if closing prices are close to the lows

    It shows divergence if the extremes keep on growing, but closing prices
    do not in the same manner (distance to the extremes grows)

    Formula:
      - hh = highest(data.high, period)
      - ll = lowest(data.low, period)
      - knum = data.close - ll
      - kden = hh - ll
      - k = 100 * (knum / kden)
      - d = MovingAverage(k, period_dfast)

    See:
      - http://en.wikipedia.org/wiki/Stochastic_oscillator
    """

    def __init__(self):
        super().__init__()

    def next(self):
        k_val = self._calc_k()
        self.lines.percK[0] = k_val
        # Calculate %D as SMA of %K
        period_d = self.p.period_dfast
        k_sum = k_val
        for i in range(1, period_d):
            k_sum += self.lines.percK[-i]
        self.lines.percD[0] = k_sum / period_d

    def once(self, start, end):
        hh_array = self.highesthigh.lines[0].array
        ll_array = self.lowestlow.lines[0].array
        close_array = self.data.close.array
        percK_array = self.lines.percK.array
        percD_array = self.lines.percD.array
        period = self.p.period
        period_d = self.p.period_dfast
        safediv = self.p.safediv
        safezero = self.p.safezero
        
        for arr in [percK_array, percD_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        # Calculate %K
        for i in range(start, min(end, len(hh_array), len(ll_array), len(close_array))):
            hh = hh_array[i] if i < len(hh_array) else 0.0
            ll = ll_array[i] if i < len(ll_array) else 0.0
            close = close_array[i] if i < len(close_array) else 0.0
            
            if isinstance(hh, float) and math.isnan(hh):
                percK_array[i] = float("nan")
                continue
            if isinstance(ll, float) and math.isnan(ll):
                percK_array[i] = float("nan")
                continue
            
            knum = close - ll
            kden = hh - ll
            if safediv and kden == 0:
                percK_array[i] = safezero
            elif kden == 0:
                percK_array[i] = 0.0
            else:
                percK_array[i] = 100.0 * (knum / kden)
        
        # Calculate %D (SMA of %K)
        for i in range(start, min(end, len(percK_array))):
            if i < period_d - 1:
                percD_array[i] = float("nan")
            else:
                k_sum = 0.0
                valid = True
                for j in range(period_d):
                    idx = i - j
                    if idx >= 0 and idx < len(percK_array):
                        val = percK_array[idx]
                        if isinstance(val, float) and math.isnan(val):
                            valid = False
                            break
                        k_sum += val
                if valid:
                    percD_array[i] = k_sum / period_d
                else:
                    percD_array[i] = float("nan")


class Stochastic(_StochasticBase):
    """
    The regular (or slow version) adds an additional moving average layer and
    thus:

      - The percD line of the StochasticFast becomes the percK line
      - percD becomes a moving average of period_dslow of the original percD

    Formula:
      - k = k
      - d = d
      - d = MovingAverage(d, period_dslow)

    See:
      - http://en.wikipedia.org/wiki/Stochastic_oscillator
    """

    alias = ("StochasticSlow",)
    params = (("period_dslow", 3),)

    def _plotlabel(self):
        plabels = [self.p.period, self.p.period_dfast, self.p.period_dslow]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        super().__init__()
        self._fast_d_vals = []

    def next(self):
        k_val = self._calc_k()
        # Fast %D becomes slow %K
        period_d = self.p.period_dfast
        self._fast_d_vals.append(k_val)
        if len(self._fast_d_vals) > period_d:
            self._fast_d_vals.pop(0)
        
        if len(self._fast_d_vals) >= period_d:
            fast_d = sum(self._fast_d_vals[-period_d:]) / period_d
        else:
            fast_d = sum(self._fast_d_vals) / len(self._fast_d_vals)
        
        self.lines.percK[0] = fast_d
        
        # Slow %D is SMA of slow %K
        period_dslow = self.p.period_dslow
        d_sum = fast_d
        for i in range(1, period_dslow):
            d_sum += self.lines.percK[-i]
        self.lines.percD[0] = d_sum / period_dslow

    def once(self, start, end):
        hh_array = self.highesthigh.lines[0].array
        ll_array = self.lowestlow.lines[0].array
        close_array = self.data.close.array
        percK_array = self.lines.percK.array
        percD_array = self.lines.percD.array
        period = self.p.period
        period_d = self.p.period_dfast
        period_dslow = self.p.period_dslow
        safediv = self.p.safediv
        safezero = self.p.safezero
        
        for arr in [percK_array, percD_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        # Calculate raw %K first
        raw_k = []
        for i in range(min(end, len(hh_array), len(ll_array), len(close_array))):
            hh = hh_array[i] if i < len(hh_array) else 0.0
            ll = ll_array[i] if i < len(ll_array) else 0.0
            close = close_array[i] if i < len(close_array) else 0.0
            
            if isinstance(hh, float) and math.isnan(hh):
                raw_k.append(float("nan"))
                continue
            if isinstance(ll, float) and math.isnan(ll):
                raw_k.append(float("nan"))
                continue
            
            knum = close - ll
            kden = hh - ll
            if safediv and kden == 0:
                raw_k.append(safezero)
            elif kden == 0:
                raw_k.append(0.0)
            else:
                raw_k.append(100.0 * (knum / kden))
        
        # Calculate fast %D (which becomes slow %K)
        for i in range(start, min(end, len(raw_k))):
            if i < period_d - 1:
                percK_array[i] = float("nan")
            else:
                k_sum = 0.0
                valid = True
                for j in range(period_d):
                    idx = i - j
                    if idx >= 0 and idx < len(raw_k):
                        val = raw_k[idx]
                        if isinstance(val, float) and math.isnan(val):
                            valid = False
                            break
                        k_sum += val
                if valid:
                    percK_array[i] = k_sum / period_d
                else:
                    percK_array[i] = float("nan")
        
        # Calculate slow %D (SMA of slow %K)
        for i in range(start, min(end, len(percK_array))):
            if i < period_d + period_dslow - 2:
                percD_array[i] = float("nan")
            else:
                d_sum = 0.0
                valid = True
                for j in range(period_dslow):
                    idx = i - j
                    if idx >= 0 and idx < len(percK_array):
                        val = percK_array[idx]
                        if isinstance(val, float) and math.isnan(val):
                            valid = False
                            break
                        d_sum += val
                if valid:
                    percD_array[i] = d_sum / period_dslow
                else:
                    percD_array[i] = float("nan")


class StochasticFull(_StochasticBase):
    """
    This version displays the 3 possible lines:

      - percK
      - percD
      - percSlow

    Formula:
      - k = d
      - d = MovingAverage(k, period_dslow)
      - dslow =

    See:
      - http://en.wikipedia.org/wiki/Stochastic_oscillator
    """

    lines = ("percDSlow",)
    params = (("period_dslow", 3),)

    plotlines = dict(percDSlow=dict(_name="%DSlow"))

    def _plotlabel(self):
        plabels = [self.p.period, self.p.period_dfast, self.p.period_dslow]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        super().__init__()

    def next(self):
        k_val = self._calc_k()
        self.lines.percK[0] = k_val
        
        # %D is SMA of %K
        period_d = self.p.period_dfast
        k_sum = k_val
        for i in range(1, period_d):
            k_sum += self.lines.percK[-i]
        d_val = k_sum / period_d
        self.lines.percD[0] = d_val
        
        # %DSlow is SMA of %D
        period_dslow = self.p.period_dslow
        d_sum = d_val
        for i in range(1, period_dslow):
            d_sum += self.lines.percD[-i]
        self.lines.percDSlow[0] = d_sum / period_dslow

    def once(self, start, end):
        hh_array = self.highesthigh.lines[0].array
        ll_array = self.lowestlow.lines[0].array
        close_array = self.data.close.array
        percK_array = self.lines.percK.array
        percD_array = self.lines.percD.array
        percDSlow_array = self.lines.percDSlow.array
        period = self.p.period
        period_d = self.p.period_dfast
        period_dslow = self.p.period_dslow
        safediv = self.p.safediv
        safezero = self.p.safezero
        
        for arr in [percK_array, percD_array, percDSlow_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        # Calculate %K
        for i in range(start, min(end, len(hh_array), len(ll_array), len(close_array))):
            hh = hh_array[i] if i < len(hh_array) else 0.0
            ll = ll_array[i] if i < len(ll_array) else 0.0
            close = close_array[i] if i < len(close_array) else 0.0
            
            if isinstance(hh, float) and math.isnan(hh):
                percK_array[i] = float("nan")
                continue
            if isinstance(ll, float) and math.isnan(ll):
                percK_array[i] = float("nan")
                continue
            
            knum = close - ll
            kden = hh - ll
            if safediv and kden == 0:
                percK_array[i] = safezero
            elif kden == 0:
                percK_array[i] = 0.0
            else:
                percK_array[i] = 100.0 * (knum / kden)
        
        # Calculate %D
        for i in range(start, min(end, len(percK_array))):
            if i < period_d - 1:
                percD_array[i] = float("nan")
            else:
                k_sum = 0.0
                valid = True
                for j in range(period_d):
                    idx = i - j
                    if idx >= 0 and idx < len(percK_array):
                        val = percK_array[idx]
                        if isinstance(val, float) and math.isnan(val):
                            valid = False
                            break
                        k_sum += val
                if valid:
                    percD_array[i] = k_sum / period_d
                else:
                    percD_array[i] = float("nan")
        
        # Calculate %DSlow
        for i in range(start, min(end, len(percD_array))):
            if i < period_d + period_dslow - 2:
                percDSlow_array[i] = float("nan")
            else:
                d_sum = 0.0
                valid = True
                for j in range(period_dslow):
                    idx = i - j
                    if idx >= 0 and idx < len(percD_array):
                        val = percD_array[idx]
                        if isinstance(val, float) and math.isnan(val):
                            valid = False
                            break
                        d_sum += val
                if valid:
                    percDSlow_array[i] = d_sum / period_dslow
                else:
                    percDSlow_array[i] = float("nan")
