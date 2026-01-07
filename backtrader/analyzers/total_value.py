"""TotalValue Analyzer Module - Portfolio value tracking.

This module provides the TotalValue analyzer for tracking the total
portfolio value over time.

Classes:
    TotalValue: Analyzer that records portfolio value at each step.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.TotalValue, _name='val')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.val.get_analysis())
"""
from collections import OrderedDict

from ..analyzer import Analyzer


class TotalValue(Analyzer):
    """This analyzer will get total value from every next.

    Params:
    Methods:

      - Get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    params = ()
    rets = None

    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Creates the ordered dictionary to store value history.
        """
        super().start()
        self.rets = OrderedDict()

    def next(self):
        """Record the total portfolio value for the current bar.

        Gets the current portfolio value from the broker and stores it
        keyed by datetime.
        """
        # Calculate the return
        super().next()
        self.rets[self.datas[0].datetime.datetime()] = self.strategy.broker.getvalue()

    def get_analysis(self):
        """Return the total value analysis results.

        Returns:
            OrderedDict: Dictionary mapping datetimes to portfolio values.
        """
        return self.rets
