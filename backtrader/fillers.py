#!/usr/bin/env python
"""Fillers Module - Order execution size calculation.

This module provides filler classes that determine how much of an order
can be executed based on available volume, price constraints, and
user-defined parameters.

Classes:
    FixedSize: Execute with fixed maximum size.
    FixedBarPerc: Execute using percentage of bar volume.
    BarPointPerc: Execute distributing volume across price range.

Example:
    >>> cerebro.broker.set_filler(backtrader.fillers.FixedBarPerc(perc=50.0))
"""
from .parameters import ParameterizedBase
from .utils.py3 import MAXINT


# Fixed size filtering, when order executes can only trade current volume, need minimum of order quantity and size, if size is None, ignore size
class FixedSize(ParameterizedBase):
    """Returns the execution size for a given order using a *percentage* of the
    volume in a bar.

    This percentage is set with the parameter ``perc``

    Params:

      - ``size`` (default: ``None``) maximum size to be executed.
      The actual
        volume of the bar at execution time is also a limit if smaller than the
        size

        If the value of this parameter evaluates to False, the entire volume
        of the bar will be used to match the order
    """

    params = (("size", None),)

    def __call__(self, order, price, ago):
        """Calculate the execution size for an order.

        Args:
            order: The order being executed.
            price: Execution price.
            ago: Number of bars back (0 for current, -1 for previous).

        Returns:
            float: The maximum size that can be executed, limited by
                bar volume, remaining order size, and configured size.
        """
        size = self.p.size or MAXINT
        return min((order.data.volume[ago], abs(order.executed.remsize), size))


# Fixed percentage, use a certain percentage of current volume and compare with order quantity, choose minimum for trading
class FixedBarPerc(ParameterizedBase):
    """Returns the execution size for a given order using a *percentage* of the
    volume in a bar.

    This percentage is set with the parameter ``perc``

    Params:

      - ``perc`` (default: ``100.0``) (valied values: ``0.0-100.0``)

        Percentage of the volume bar to use to execute an order
    """

    params = (("perc", 100.0),)

    def __call__(self, order, price, ago):
        """Calculate the execution size using percentage of bar volume.

        Args:
            order: The order being executed.
            price: Execution price.
            ago: Number of bars back (0 for current, -1 for previous).

        Returns:
            float: The maximum size that can be executed based on
                percentage of bar volume and remaining order size.
        """
        # Get the volume and scale it to the requested perc
        maxsize = (order.data.volume[ago] * self.p.perc) // 100
        # Return the maximum possible executed volume
        return min(maxsize, abs(order.executed.remsize))


# Distribute according to bar's fluctuation range by percentage
class BarPointPerc(ParameterizedBase):
    """Returns the execution size for a given order. The volume will be
    distributed uniformly in the range *high*-*low* using ``minmov`` to
    partition.

    From the allocated volume for the given price, the `perc` percentage will
    be used

    Params:

      - ``minmov`` (default: ``0.01``)

        Minimum price movement. Used to partition the range *high*-*low* to
        proportionally distribute the volume amongst possible prices

      - ``perc`` (default: ``100.0``) (valied values: ``0.0-100.0``)

        Percentage of the volume allocated to the order execution price to use
        for matching
        # minmov defaults to 0.01, based on distance between high and low prices, see how many parts can be divided
        # perc defaults to 100, trading limit is order can only be placed for each part's perc
    """

    # Specific parameters
    params = (
        ("minmov", None),
        ("perc", 100.0),
    )

    def __call__(self, order, price, ago):
        """Calculate the execution size distributing volume across price range.

        Args:
            order: The order being executed.
            price: Execution price.
            ago: Number of bars back (0 for current, -1 for previous).

        Returns:
            float: The maximum size that can be executed based on
                proportional distribution across the price range.
        """
        # Data
        data = order.data
        # Minimum price movement
        minmov = self.p.minmov
        # Calculate how many parts can be divided
        parts = 1
        if minmov:
            # high - low + minmov to account for open-ended minus op
            parts = (data.high[ago] - data.low[ago] + minmov) // minmov
        # Calculate how much each part can trade
        alloc_vol = ((data.volume[ago] / parts) * self.p.perc) // 100.0
        # return max possible executable volume
        # Return maximum possible executable order quantity
        return min(alloc_vol, abs(order.executed.remsize))
