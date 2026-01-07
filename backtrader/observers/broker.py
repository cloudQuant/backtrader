#!/usr/bin/env python
"""Broker Observer Module - Cash and value tracking.

This module provides observers for tracking broker cash and portfolio value.

Classes:
    Cash: Observer that tracks current cash level.
    Value: Observer that tracks portfolio value.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.Broker)
"""
from ..observer import Observer


# Get cash
class Cash(Observer):
    """This observer keeps track the current amount of cash in the broker

    Params: None
    """

    _stclock = True

    lines = ("cash",)

    plotinfo = dict(plot=True, subplot=True)

    def next(self):
        """Update the cash value for the current period.

        Gets current cash amount from the broker.
        """
        self.lines[0][0] = self._owner.broker.getcash()


# Get value
class Value(Observer):
    """This observer keeps track of the current portfolio value in the broker
    including the cash

    Params:

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    """

    _stclock = True

    params = (("fund", None),)

    lines = ("value",)

    plotinfo = dict(plot=True, subplot=True)

    def __init__(self):
        """Initialize the Value observer.

        Sets up fund mode tracking variable.
        """
        self._fundmode = None

    def start(self):
        """Start the Value observer and determine fund mode.

        Detects or sets fund mode for value calculation.
        """
        if self.p.fund is None:
            self._fundmode = self._owner.broker.fundmode
        else:
            self._fundmode = self.p.fund

    def next(self):
        """Update the portfolio value for the current period.

        Gets value from broker based on fund mode setting.
        """
        if not self._fundmode:
            self.lines[0][0] = self._owner.broker.getvalue()
        else:
            self.lines[0][0] = self._owner.broker.fundvalue


# Get both cash and value
class Broker(Observer):
    """This observer keeps track of the current cash amount and portfolio value in
    the broker (including the cash)

    Params: None
    """

    _stclock = True

    params = (("fund", None),)

    alias = ("CashValue",)
    lines = ("cash", "value")

    plotinfo = dict(plot=True, subplot=True)

    def __init__(self):
        """Initialize the Broker observer.

        Sets up fund mode tracking variable.
        """
        self._fundmode = None

    def start(self):
        """Start the Broker observer and configure plotting.

        Determines fund mode and configures plot settings.
        """
        if self.p.fund is None:
            self._fundmode = self._owner.broker.fundmode
        else:
            self._fundmode = self.p.fund

        if self._fundmode:
            self.plotlines.cash._plotskip = True
            self.plotlines.value._name = "FundValue"

    def next(self):
        """Update cash and value for the current period.

        Gets current cash and portfolio value from the broker.
        """
        if not self._fundmode:
            self.lines.value[0] = self._owner.broker.getvalue()
            self.lines.cash[0] = self._owner.broker.getcash()
        else:
            self.lines.value[0] = self._owner.broker.fundvalue


# fundvalue
class FundValue(Observer):
    """This observer keeps track of the current fund-like value

    Params: None
    """

    _stclock = True

    alias = ("FundShareValue", "FundVal")
    lines = ("fundval",)

    plotinfo = dict(plot=True, subplot=True)

    def next(self):
        """Update the fund value for the current period.

        Gets current fund value from the broker.
        """
        self.lines.fundval[0] = self._owner.broker.fundvalue


# Fund shares
class FundShares(Observer):
    """This observer keeps track of the current fund-like shares

    Params: None
    """

    _stclock = True

    lines = ("fundshares",)

    plotinfo = dict(plot=True, subplot=True)

    def next(self):
        """Update the fund shares for the current period.

        Gets current fund shares from the broker.
        """
        self.lines.fundshares[0] = self._owner.broker.fundshares
