#!/usr/bin/env python
"""Acceleration/Deceleration Oscillator Module - AC indicator.

This module provides the Acceleration/Deceleration Oscillator (AC)
developed by Bill Williams to measure the acceleration of driving force.

Classes:
    AccelerationDecelerationOscillator: AC indicator (alias: AccDeOsc).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.AccDeOsc)
"""
import math
from . import Indicator
from .awesomeoscillator import AwesomeOscillator
from .sma import SMA

__all__ = ["AccelerationDecelerationOscillator", "AccDeOsc"]


class AccelerationDecelerationOscillator(Indicator):
    """
    Acceleration/Deceleration Technical Indicator (AC) measures acceleration
    and deceleration of the current driving force. This indicator will change
    the direction before any changes in the driving force, which, it its turn, will
    change its direction before the price.

    Formula:
     - AcdDecOsc = AwesomeOscillator - SMA(AwesomeOscillator, period)

    See:
      - https://www.metatrader5.com/en/terminal/help/indicators/bw_indicators/ao
      - https://www.ifcmarkets.com/en/ntx-indicators/ntx-indicators-accelerator-decelerator-oscillator

    """

    alias = ("AccDeOsc",)
    lines = ("accde",)

    params = (
        ("period", 5),
        ("movav", SMA),
    )

    plotlines = dict(accde=dict(_method="bar", alpha=0.50, width=1.0))

    def __init__(self):
        """Initialize the AC indicator.

        Creates an Awesome Oscillator sub-indicator for calculation.
        """
        super().__init__()
        self.ao = AwesomeOscillator(self.data)

    def next(self):
        """Calculate AC for the current bar.

        Formula: AC = AO - SMA(AO, period)
        """
        ao_val = self.ao[0]
        period = self.p.period

        # Calculate SMA of AO
        ao_sum = ao_val
        for i in range(1, period):
            ao_sum += self.ao[-i]
        ao_sma = ao_sum / period

        self.lines.accde[0] = ao_val - ao_sma

    def once(self, start, end):
        """Calculate AC in runonce mode.

        Calculates AC = AO - SMA(AO, period) for all bars.
        """
        ao_array = self.ao.lines[0].array
        larray = self.lines.accde.array
        period = self.p.period

        while len(larray) < end:
            larray.append(0.0)

        for i in range(start, min(end, len(ao_array))):
            ao_val = ao_array[i] if i < len(ao_array) else 0.0

            if isinstance(ao_val, float) and math.isnan(ao_val):
                larray[i] = float("nan")
                continue

            if i < period - 1:
                larray[i] = float("nan")
            else:
                ao_sum = 0.0
                for j in range(period):
                    idx = i - j
                    if idx >= 0 and idx < len(ao_array):
                        ao_sum += ao_array[idx]
                ao_sma = ao_sum / period
                larray[i] = ao_val - ao_sma


AccDeOsc = AccelerationDecelerationOscillator
