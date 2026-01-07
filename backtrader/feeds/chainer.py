#!/usr/bin/env python
"""Chainer Data Feed Module - Chain multiple data feeds.

This module provides the Chainer feed for chaining multiple data
feeds together seamlessly during backtesting.

Classes:
    Chainer: Chains multiple data feeds together.

Example:
    >>> data1 = bt.feeds.BacktraderCSVData(dataname='part1.csv')
    >>> data2 = bt.feeds.BacktraderCSVData(dataname='part2.csv')
    >>> data = bt.feeds.Chainer(data1, data2)
    >>> cerebro.adddata(data)
"""

from datetime import datetime

from backtrader.utils.py3 import range

from ..feed import DataBase
from ..utils import date


class Chainer(DataBase):
    """Class that chains datas"""

    # When data is live data, will avoid preloading and runonce behavior
    def islive(self):
        """Returns ``True`` to notify ``Cerebro`` that preloading and runonce
        should be deactivated"""
        return True

    # Initialize
    def __init__(self, *args, **kwargs):
        # Handle timeframe and compression parameters, originally handled by metaclass
        if args:
            # Copy timeframe and compression from first data source
            kwargs.setdefault("timeframe", getattr(args[0], "_timeframe", None))
            kwargs.setdefault("compression", getattr(args[0], "_compression", None))

        super().__init__(**kwargs)

        self._lastdt = None
        self._d = None
        self._ds = None
        self._args = args

    # Start
    def start(self):
        super().start()
        for d in self._args:
            d.setenvironment(self._env)
            d._start()

        # put the references in a separate list to have pops
        self._ds = list(self._args)
        self._d = self._ds.pop(0) if self._ds else None
        self._lastdt = datetime.min

    # Stop
    def stop(self):
        super().stop()
        for d in self._args:
            d.stop()

    # Notifications
    def get_notifications(self):
        return [] if self._d is None else self._d.get_notifications()

    # Get timezone
    def _gettz(self):
        """To be overriden by subclasses which may auto-calculate the
        timezone"""
        if self._args:
            return self._args[0]._gettz()
        return date.Localizer(self.p.tz)

    # Load data, this processing looks quite clever, planning to handle futures contract rollover or remove data when it expires later
    def _load(self):
        while self._d is not None:
            if not self._d.next():  # no values from current data source
                self._d = self._ds.pop(0) if self._ds else None
                continue

            # Cannot deliver a date equal or less than an already delivered
            dt = self._d.datetime.datetime()
            if dt <= self._lastdt:
                continue

            self._lastdt = dt

            for i in range(self._d.size()):
                self.lines[i][0] = self._d.lines[i][0]

            return True

        # Out of the loop -> self._d is None, no data feed to return from
        return False
