#!/usr/bin/env python
"""Price Oscillator Module - Price oscillators.

This module provides Price Oscillator indicators that measure the
difference between two moving averages.

Classes:
    _PriceOscBase: Base class for price oscillators.
    PriceOscillator: Price difference (aliases: PriceOsc, APO, AbsPriceOsc).
    PercentagePriceOscillator: Percentage price oscillator (aliases: PPO, PercPriceOsc).
    PercentagePriceOscillatorShort: PPO with short denominator (aliases: PPOShort).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.PPO, period1=12, period2=26)
"""
import math
from . import Indicator, MovAv
class _PriceOscBase(Indicator):
    params = (
        ("period1", 12),
        ("period2", 26),
        ("_movav", MovAv.Exponential),
    )

    plotinfo = dict(plothlines=[0.0])

    def __init__(self):
        super().__init__()
        self.ma1 = self.p._movav(self.data, period=self.p.period1)
        self.ma2 = self.p._movav(self.data, period=self.p.period2)

    def next(self):
        self.lines[0][0] = self.ma1[0] - self.ma2[0]

    def once(self, start, end):
        ma1_array = self.ma1.lines[0].array
        ma2_array = self.ma2.lines[0].array
        larray = self.lines[0].array
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(start, min(end, len(ma1_array), len(ma2_array))):
            ma1_val = ma1_array[i] if i < len(ma1_array) else 0.0
            ma2_val = ma2_array[i] if i < len(ma2_array) else 0.0
            
            if isinstance(ma1_val, float) and math.isnan(ma1_val):
                larray[i] = float("nan")
            elif isinstance(ma2_val, float) and math.isnan(ma2_val):
                larray[i] = float("nan")
            else:
                larray[i] = ma1_val - ma2_val


# Moving average difference
class PriceOscillator(_PriceOscBase):
    """
    Shows the difference between a short and long exponential moving
    averages expressed in points.

    Formula:
      - po = ema(short) - ema(long)

    See:
      - http://www.metastock.com/Customer/Resources/TAAZ/?c=3&p=94
    """

    alias = (
        "PriceOsc",
        "AbsolutePriceOscillator",
        "APO",
        "AbsPriceOsc",
    )
    lines = ("po",)


# Similar to MACD indicator, expressed in percentage
class PercentagePriceOscillator(_PriceOscBase):
    """
    Shows the difference between a short and long exponential moving
    averages expressed in percentage. The MACD does the same but expressed in
    absolute points.

    Expressing the difference in percentage allows to compare the indicator at
    different points in time when the underlying value has significatnly
    different values.

    Formula:
      - po = 100 * (ema(short) - ema(long)) / ema(long)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:price_oscillators_ppo
    """

    _long = True

    alias = (
        "PPO",
        "PercPriceOsc",
    )

    lines = ("ppo", "signal", "histo")
    params = (("period_signal", 9),)

    plotlines = dict(histo=dict(_method="bar", alpha=0.50, width=1.0))

    def __init__(self):
        super().__init__()
        self.signal_alpha = 2.0 / (1.0 + self.p.period_signal)
        self.signal_alpha1 = 1.0 - self.signal_alpha

    def next(self):
        # Calculate base PO
        po_val = self.ma1[0] - self.ma2[0]
        self.lines.po[0] = po_val
        
        # Calculate PPO
        den = self.ma2[0] if self._long else self.ma1[0]
        if den != 0:
            ppo_val = 100.0 * po_val / den
        else:
            ppo_val = 0.0
        self.lines.ppo[0] = ppo_val
        
        # Calculate signal (EMA of PPO)
        self.lines.signal[0] = self.lines.signal[-1] * self.signal_alpha1 + ppo_val * self.signal_alpha
        
        # Calculate histogram
        self.lines.histo[0] = self.lines.ppo[0] - self.lines.signal[0]

    def nextstart(self):
        # Calculate base PO
        po_val = self.ma1[0] - self.ma2[0]
        self.lines.po[0] = po_val
        
        # Calculate PPO
        den = self.ma2[0] if self._long else self.ma1[0]
        if den != 0:
            ppo_val = 100.0 * po_val / den
        else:
            ppo_val = 0.0
        self.lines.ppo[0] = ppo_val
        
        # Seed signal with PPO
        self.lines.signal[0] = ppo_val
        
        # Calculate histogram
        self.lines.histo[0] = 0.0

    def once(self, start, end):
        ma1_array = self.ma1.lines[0].array
        ma2_array = self.ma2.lines[0].array
        po_array = self.lines.po.array
        ppo_array = self.lines.ppo.array
        signal_array = self.lines.signal.array
        histo_array = self.lines.histo.array
        signal_alpha = self.signal_alpha
        signal_alpha1 = self.signal_alpha1
        use_long = self._long
        
        for arr in [po_array, ppo_array, signal_array, histo_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        prev_signal = 0.0
        for i in range(start, min(end, len(ma1_array), len(ma2_array))):
            ma1_val = ma1_array[i] if i < len(ma1_array) else 0.0
            ma2_val = ma2_array[i] if i < len(ma2_array) else 0.0
            
            if isinstance(ma1_val, float) and math.isnan(ma1_val):
                po_array[i] = float("nan")
                ppo_array[i] = float("nan")
                signal_array[i] = float("nan")
                histo_array[i] = float("nan")
                continue
            if isinstance(ma2_val, float) and math.isnan(ma2_val):
                po_array[i] = float("nan")
                ppo_array[i] = float("nan")
                signal_array[i] = float("nan")
                histo_array[i] = float("nan")
                continue
            
            po_val = ma1_val - ma2_val
            po_array[i] = po_val
            
            den = ma2_val if use_long else ma1_val
            if den != 0:
                ppo_val = 100.0 * po_val / den
            else:
                ppo_val = 0.0
            ppo_array[i] = ppo_val
            
            # Update signal
            if i > 0 and i - 1 < len(signal_array):
                prev_val = signal_array[i - 1]
                if not (isinstance(prev_val, float) and math.isnan(prev_val)):
                    prev_signal = prev_val
            
            prev_signal = prev_signal * signal_alpha1 + ppo_val * signal_alpha
            signal_array[i] = prev_signal
            
            histo_array[i] = ppo_val - prev_signal


class PercentagePriceOscillatorShort(PercentagePriceOscillator):
    """
    Shows the difference between a short and long exponential moving
    averages expressed in percentage. The MACD does the same but expressed in
    absolute points.

    Expressing the difference in percentage allows to compare the indicator at
    different points in time when the underlying value has significatnly
    different values.

    Most on-line literature shows the percentage calculation having the long
    exponential moving average as the denominator. Some sources like MetaStock
    use the short one.

    Formula:
      - po = 100 * (ema(short) - ema(long)) / ema(short)

    See:
      - http://www.metastock.com/Customer/Resources/TAAZ/?c=3&p=94
    """

    _long = False
    alias = (
        "PPOShort",
        "PercPriceOscShort",
    )
