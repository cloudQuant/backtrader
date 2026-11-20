#!/usr/bin/env python
"""Awesome Oscillator Module - AO momentum indicator.

This module provides the Awesome Oscillator (AO) developed by
Bill Williams to measure market momentum.

Classes:
    AwesomeOscillator: Awesome Oscillator indicator (aliases: AwesomeOsc, AO).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.ao = bt.indicators.AO(self.data)

        def next(self):
            if self.ao.ao[0] > 0 and self.ao.ao[-1] < 0:
                self.buy()
"""

from . import Indicator, MovAv

__all__ = ["AwesomeOscillator", "AwesomeOsc", "AO"]


class AwesomeOscillator(Indicator):
    """
    Awesome Oscillator (AO) is a momentum indicator reflecting the precise
    changes in the market driving force, which helps to identify the trend's
    strength up to the points of formation and reversal.


    Formula:
     - median price = (high + low) / 2
     - AO = MA (median price, fast) - MA (median price, slow)

    See:
      - https://www.metatrader5.com/en/terminal/help/indicators/bw_indicators/awesome
      - https://www.ifcmarkets.com/en/ntx-indicators/awesome-oscillator

    """

    # Alias
    alias = ("AwesomeOsc", "AO")
    # Line to generate
    lines = ("ao",)
    # Parameters
    params = (
        ("fast", 5),
        ("slow", 34),
        ("movav", MovAv.Simple),
    )
    # Plot parameters
    plotlines = {"ao": {"_method": "bar", "alpha": 0.50, "width": 1.0}}

    # Create indicators during initialization
    def __init__(self):
        """Build the fast and slow moving averages of the median price."""
        super().__init__()

        median = (self.data.high + self.data.low) / 2.0
        fast = self.p.movav(median, period=self.p.fast)
        slow = self.p.movav(median, period=self.p.slow)
        self.lines.ao = fast - slow


AwesomeOsc = AO = AwesomeOscillator
