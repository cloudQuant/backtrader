#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Position Sizer Module - Position size calculation.

This module provides the base class for position sizers, which determine
the size of orders to place based on available cash, risk parameters,
and other factors.

Classes:
    Sizer: Base class for position sizers.
    FixedSize: Sizer that uses a fixed size.
    FixedReverser: Sizer that reverses positions with fixed size.
    PercentSizer: Sizer that uses a percentage of available cash.
    AllInSizer: Sizer that uses all available cash.
    RiskReturnSizer: Sizer that sizes based on risk/reward ratio.

Example:
    Creating a custom sizer:
    >>> class MySizer(bt.Sizer):
    ...     params = (('perc', 0.1),)
    ...
    ...     def _getsizing(self, comminfo, cash, data, isbuy):
    ...         return int(cash * self.p.perc / data.close[0])
"""
from .parameters import ParameterizedBase


# Sizer class - Refactored to use new parameter system
class Sizer(ParameterizedBase):
    """Base class for position sizers.

    This is the base class for sizers. Any sizer should subclass this
    and override the ``_getsizing`` method to provide custom position
    sizing logic.

    Attributes:
        strategy: The strategy using this sizer.
        broker: The broker instance for portfolio information.

    Methods:
        getsizing(data, isbuy): Get the position size for an order.
        _getsizing(comminfo, cash, data, isbuy): Override to implement sizing logic.
        set(strategy, broker): Set the strategy and broker references.

    Example:
        >>> cerebro.addsizer(bt.sizers.FixedSize, stake=100)
    """

    strategy = None
    broker = None

    def __init__(self, **kwargs):
        """Initialize the Sizer with any provided parameters."""
        super(Sizer, self).__init__(**kwargs)

    # Get the specific position size for order placement
    def getsizing(self, data, isbuy):
        comminfo = self.broker.getcommissioninfo(data)
        return self._getsizing(comminfo, self.broker.getcash(), data, isbuy)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """This method has to be overriden by subclasses of Sizer to provide
        the sizing functionality

        Params:
          - ``comminfo``: The CommissionInfo instance that contains
            information about the commission for the data and allows
            calculation of position value, operation cost, commission for the
            operation

          - ``cash``: current available cash in the *broker*

          - ``data``: target of the operation

          - ``isbuy``: will be ``True`` for *buy* operations and ``False``
            for *sell* operations

        The method has to return the actual size (an int) to be executed. If
         `0` is returned, nothing will be executed.

        The absolute value of the returned value will be used
        # This method needs to be overridden when in use, takes four parameters:
        # comminfo represents the commission instance, can be used to get commission etc.
        # cash represents currently available cash
        # data represents which data to trade on
        # isbuy represents True for buy operations, False for sell operations

        """
        raise NotImplementedError

    # Set strategy and broker
    def set(self, strategy, broker):
        self.strategy = strategy
        self.broker = broker


# SizerBase class
SizerBase = Sizer
