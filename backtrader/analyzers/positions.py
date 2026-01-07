#!/usr/bin/env python
"""Positions Analyzer Module - Position value tracking.

This module provides the PositionsValue analyzer for tracking the
value of positions across all data feeds.

Classes:
    PositionsValue: Analyzer that reports position values over time.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.PositionsValue, _name='posval')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.posval.get_analysis())
"""
from ..analyzer import Analyzer
from ..dataseries import TimeFrame


# Position value
class PositionsValue(Analyzer):
    """This analyzer reports the value of the positions of the current set of
    datas

    Params:

      - timeframe (default: ``None``)
        If ``None`` then the timeframe of the first data of the system will be
        used

      - compression (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - headers (default: ``False``)

        Add an initial key to the dictionary holding the results with the names
        of the data 'Datetime' as a key

      - cash (default: ``False``)

        Include the actual cash as an extra position (for the header 'cash'
        will be used as name)

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    # Parameters
    params = (
        ("headers", False),
        ("cash", False),
    )

    # Start
    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        self._usedate = None

    def start(self):
        # If headers parameter is True, use each data's name as header
        if self.p.headers:
            headers = [d._name or "Data%d" % i for i, d in enumerate(self.datas)]
            # If cash is True, also save cash
            self.rets["Datetime"] = headers + ["cash"] * self.p.cash
        # Time period
        tf = min(d._timeframe for d in self.datas)
        # If time period >= Days, set usedate parameter to True
        self._usedate = tf >= TimeFrame.Days

    # Called once per bar
    def next(self):
        # Get value for each data
        pvals = [self.strategy.broker.get_value([d]) for d in self.datas]
        # If cash is True, save cash
        if self.p.cash:
            pvals.append(self.strategy.broker.get_cash())
        # If usedate is True, use date as key, otherwise use datetime as key
        if self._usedate:
            self.rets[self.strategy.datetime.date()] = pvals
        else:
            self.rets[self.strategy.datetime.datetime()] = pvals
