#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt
from .awesomeoscillator import AwesomeOscillator
from .sma import SMA

__all__ = ["AccelerationDecelerationOscillator", "AccDeOsc"]


class AccelerationDecelerationOscillator(bt.Indicator):
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
        ao = AwesomeOscillator()
        self.l.accde = ao - self.p.movav(ao, period=self.p.period)
        super(AccelerationDecelerationOscillator, self).__init__()


AccDeOsc = AccelerationDecelerationOscillator
