#!/usr/bin/env python
"""Moving Average Base Module - Core moving average infrastructure.

This module provides the base classes and registration system for all
moving average indicators in backtrader.

Classes:
    MovingAverage: Placeholder for all moving average types.
    MovAv: Alias for MovingAverage.
    MovingAverageBase: Base class for moving average indicators.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=20)
            self.ema = bt.indicators.EMA(self.data.close, period=12)
            # Or using MovAv wrapper
            self.wma = bt.indicators.MovAv.WMA(self.data.close, period=15)

        def next(self):
            if self.data.close[0] > self.sma[0]:
                self.buy()
            elif self.data.close[0] < self.sma[0]:
                self.sell()
"""

from . import Indicator


# Moving average class, used to set indicator names
class MovingAverage:
    """MovingAverage (alias MovAv)

    A placeholder to gather all Moving Average Types in a single place.

    Instantiating a SimpleMovingAverage can be achieved as follows::

      sma = MovingAverage.Simple(self.data, period)

    Or using the shorter aliases::

      sma = MovAv.SMA(self.data, period)

    or with the full (forwards and backwards) names:

      sma = MovAv.SimpleMovingAverage(self.data, period)

      sma = MovAv.MovingAverageSimple(self.data, period)

    """

    # Storage for moving average classes
    _movavs = []

    @classmethod
    def register(cls, regcls):
        """Register a moving average class with the placeholder.

        Args:
            regcls: The moving average class to register.

        Sets the class name and aliases as attributes on the placeholder
        for easy access (e.g., MovAv.SMA, MovAv.EMA).
        """
        # If indicator doesn't have _notregister or _notregister value is False, continue to register, otherwise return directly
        if getattr(regcls, "_notregister", False):
            return
        # Add indicator class to be calculated
        cls._movavs.append(regcls)
        # Class name, and set class name as cls attribute, attribute value is the specific class
        clsname = regcls.__name__
        setattr(cls, clsname, regcls)

        # Specific indicator alias, if indicator starts with MovingAverage, use latter value as alias, if ends with MovingAverage, use former value as alias
        # If obtained alias is not empty string, then also set alias as attribute, attribute value is this class
        clsalias = ""
        if clsname.endswith("MovingAverage"):
            clsalias = clsname.split("MovingAverage")[0]
        elif clsname.startswith("MovingAverage"):
            clsalias = clsname.split("MovingAverage")[1]

        if clsalias:
            setattr(cls, clsalias, regcls)

        # CRITICAL FIX: Process the alias attribute if it exists
        # Many indicators define their own aliases like alias = ("SMA", "SimpleMovingAverage")
        if hasattr(regcls, "alias"):
            aliases = regcls.alias
            # Support both tuple and single string
            if isinstance(aliases, str):
                aliases = (aliases,)
            # Register each alias
            for alias_name in aliases:
                if alias_name and isinstance(alias_name, str):
                    setattr(cls, alias_name, regcls)


# Alias for moving average
class MovAv(MovingAverage):
    """Alias for MovingAverage.

    Provides a shorter name for accessing moving average types.
    """

    pass  # alias


# Base class for moving average, add parameters and plot settings - refactored to remove metaclass
class MovingAverageBase(Indicator):
    """Base class for all moving average indicators.

    Provides common initialization with minimum period management and
    automatic registration with the MovingAverage placeholder.

    Attributes:
        params: Default period parameter (30).
        plotinfo: Default to plot on main chart (subplot=False).
    """

    # Parameters
    params = (("period", 30),)
    # Plot on main chart by default
    plotinfo = dict(subplot=False)

    def __init__(self):
        """Initialize moving average and set minimum period"""
        super().__init__()

        # CRITICAL FIX: Inherit minperiod from data source BEFORE adding own period
        # This ensures nested indicators (like EMA applied to MACD line) properly accumulate minperiods
        if hasattr(self, "datas") and self.datas:
            data_minperiods = [getattr(d, "_minperiod", 1) for d in self.datas if d is not None]
            if data_minperiods:
                data_max = max(data_minperiods)
                if data_max > self._minperiod:
                    self._minperiod = data_max

        # CRITICAL FIX: Set the minimum period based on the period parameter
        # This ensures the indicator doesn't start calculating until enough data is available
        self.addminperiod(self.p.period)

    def __init_subclass__(cls, **kwargs):
        """Register moving average classes automatically"""
        super().__init_subclass__(**kwargs)
        # Register any MovingAverage with the placeholder to allow the automatic
        # creation of envelopes and oscillators
        MovingAverage.register(cls)

