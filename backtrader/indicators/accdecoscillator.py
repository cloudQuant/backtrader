#!/usr/bin/env python
"""Acceleration/Deceleration Oscillator Module - AC indicator.

This module provides the Acceleration/Deceleration Oscillator (AC)
developed by Bill Williams to measure the acceleration of driving force.

Classes:
    AccelerationDecelerationOscillator: AC indicator (alias: AccDeOsc).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.ac = bt.indicators.AccDeOsc(self.data)

        def next(self):
            if self.ac.accde[0] > 0 and self.ac.accde[-1] < 0:
                self.buy()
"""

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
     - AcdDecOsc = AwesomeOscillator - movav(AwesomeOscillator, period)

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

    plotlines = {"accde": {"_method": "bar", "alpha": 0.50, "width": 1.0}}

    def __init__(self):
        """Initialize the AC indicator.

        Create the Awesome Oscillator and its configured smoothing average.
        """
        super().__init__()
        self.ao = AwesomeOscillator(self.data)
        self.ao_average = self.p.movav(self.ao, period=self.p.period)
        self.lines.accde = self.ao - self.ao_average


AccDeOsc = AccelerationDecelerationOscillator
