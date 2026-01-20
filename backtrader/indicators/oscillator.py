#!/usr/bin/env python
"""Oscillator Indicator Module - Oscillating indicators.

This module provides oscillator indicators that show the deviation
of one data series from another, typically price from a moving average.

Classes:
    OscillatorMixIn: MixIn class to create oscillating indicators.
    Oscillator: Oscillation of data around another data.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            # Oscillate price around SMA
            self.osc = bt.indicators.Oscillator(self.data, bt.indicators.SMA(self.data, period=20))

        def next(self):
            # When oscillator is positive, price is above SMA
            if self.osc[0] > 0:
                self.buy()
            elif self.osc[0] < 0:
                self.sell()
"""

import sys

from . import Indicator, MovingAverage


class OscillatorMixIn(Indicator):
    """
    MixIn class to create a subclass with another indicator. The main line of
    that indicator will be substracted from the other base class main line
    creating an oscillator

    The usage is:

      - Class XXXOscillator(XXX, OscillatorMixIn)

    Formula:
      - XXX calculates lines[0]
      - osc = self.data - XXX.lines[0]
    """

    plotlines = dict(_0=dict(_name="osc"))

    def _plotinit(self):
        try:
            lname = self.lines._getlinealias(0)
            self.plotlines._0._name = lname + "_osc"
        except AttributeError:
            pass

    def __init__(self):
        """Initialize the oscillator by subtracting the base line from data."""
        self.lines[0] = self.data - self.lines[0]
        super().__init__()


class Oscillator(Indicator):
    """
    Oscillation of given data around another data

    Datas:
      This indicator can accept one or two data for the calculation.

      - If one data is provided, it must be a complex "Lines" object (indicator)
        which also has "data".Example: A moving average

        The calculated oscillation will be that of the Moving Average (in the
        example) around the data that was used for the average calculation

      - If two data are provided, the calculated oscillation will be that of the
        second data around the first data

    Formula:
      - 1 data -> osc = data.data - data
      - 2 datas -> osc = data0 - data1
    """

    lines = ("osc",)

    # Have a default value which can be later modified if needed
    plotlines = dict(_0=dict(_name="osc"))

    def _plotinit(self):
        try:
            lname = self.dataosc._getlinealias(0)
            self.plotlines._0._name = lname + "_osc"
        except AttributeError:
            pass

    def __init__(self):
        """Initialize the oscillator with data source and oscillator data.

        Calculates the oscillation between two data series or between
        a data series and its underlying data.
        """
        super().__init__()

        if len(self.datas) > 1:
            datasrc = self.data
            self.dataosc = self.data1
        else:
            datasrc = self.data.data
            self.dataosc = self.data

        self.lines[0] = datasrc - self.dataosc


# Automatic creation of Oscillating Lines

for movav in MovingAverage._movavs[0:]:
    _newclsdoc = """
    Oscillation of a %s around its data
    """
    # Skip aliases - they will be created automatically
    if getattr(movav, "aliased", ""):
        continue

    movname = movav.__name__
    # Handle both tuple lines and Lines objects after refactoring
    if hasattr(movav.lines, "_getlinealias"):
        # It's a Lines object
        linename = movav.lines._getlinealias(0)
    elif isinstance(movav.lines, (tuple, list)) and movav.lines:
        # It's a tuple/list of line names
        linename = movav.lines[0]
    else:
        # Fallback to first line name or class name
        linename = (
            getattr(movav.lines, "_getlinealias", lambda x: movav.__name__.lower())(0)
            if hasattr(movav.lines, "_getlinealias")
            else movav.__name__.lower()
        )

    newclsname = movname + "Oscillator"

    newaliases = [movname + "Osc"]
    for alias in getattr(movav, "alias", []):
        for suffix in ["Oscillator", "Osc"]:
            newaliases.append(alias + suffix)

    newclsdoc = _newclsdoc % movname
    newclsdct = {
        "__doc__": newclsdoc,
        "__module__": OscillatorMixIn.__module__,
        "_notregister": True,
        "alias": newaliases,
    }

    newcls = type(str(newclsname), (movav, OscillatorMixIn), newclsdct)
    module = sys.modules[OscillatorMixIn.__module__]
    setattr(module, newclsname, newcls)
