#!/usr/bin/env python
"""Leverage Analyzer Module - Gross leverage calculation.

This module provides the GrossLeverage analyzer for calculating the
gross leverage (ratio of used capital to portfolio value).

Classes:
    GrossLeverage: Analyzer that calculates gross leverage.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.GrossLeverage, _name='lev')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.lev.get_analysis())
"""
from ..analyzer import Analyzer


# Ratio of used capital
class GrossLeverage(Analyzer):
    """This analyzer calculates the Gross Leverage of the current strategy
    on a timeframe basis

    Params:

      - ``fund`` (default: ``None``)

        If None, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - Get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    # Parameters
    params = (("fund", None),)

    # Start
    def __init__(self, *args, **kwargs):
        """Initialize the GrossLeverage analyzer.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        self._value = None
        self._cash = None
        self._fundmode = None

    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Sets the fund mode based on parameters or broker settings.
        """
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund

    # Fund notification
    def notify_fund(self, cash, value, fundvalue, shares):
        """Update cash and value from fund notification.

        Args:
            cash: Current cash amount.
            value: Current portfolio value.
            fundvalue: Current fund value.
            shares: Number of fund shares.
        """
        self._cash = cash
        if not self._fundmode:
            self._value = value
        else:
            self._value = fundvalue

    # Run once per bar, get ratio of used capital
    def next(self):
        """Calculate and record the gross leverage for the current bar.

        Gross leverage is calculated as (value - cash) / value.
        Returns 0.0 if 100% in cash, 1.0 if fully invested without shorting.
        """
        # Updates the leverage for "dtkey" (see base class) for each cycle
        # 0.0 if 100% in cash, 1.0 if no short selling and fully invested
        lev = (self._value - self._cash) / self._value
        self.rets[self.data0.datetime.datetime()] = lev
