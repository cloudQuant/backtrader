#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .parameters import ParameterizedBase


# Sizer class - Refactored to use new parameter system
class Sizer(ParameterizedBase):
    """
    This is the base class for *Sizers*. Any *sizer* should subclass this
    and override the ``_getsizing`` method.

    This class has been refactored from MetaParams to the new ParameterizedBase
    system for Day 36-38 of the metaprogramming removal project.

    Member Attribs:

      - ``strategy``: will be set by the strategy in which the sizer is working

        Gives access to the entire api of the strategy, for example, if the
        actual data position is needed in ``_getsizing``:

           Position = self.strategy.getposition(data)

      - ``broker``: will be set by the strategy in which the sizer is working

        Gives access to information some complex sizers may need like portfolio
        value.

      # strategy represents the strategy using sizer, can call all strategy APIs through strategy
      # broker represents the broker where strategy is used, can be used to get information for calculating complex position sizes
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
