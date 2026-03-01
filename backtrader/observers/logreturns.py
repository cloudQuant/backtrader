#!/usr/bin/env python
"""LogReturns Observer Module - Log returns tracking.

This module provides observers for tracking log returns of the strategy
or a data feed.

Classes:
    LogReturns: Observer that tracks log returns.
    LogReturns2: Alternative log returns observer.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.LogReturns)
"""

from ..analyzers import LogReturnsRolling
from ..dataseries import TimeFrame
from ..observer import Observer

__all__ = ["LogReturns", "LogReturns2"]


# Get log returns
class LogReturns(Observer):
    """This observer stores the *log returns* of the strategy or a

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` then the complete return over the entire backtested period
        will be reported

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Remember that at any moment of a `run` the current values can be checked
    by looking at the *lines* by name at index ``0``.

    """

    _stclock = True

    lines = ("logret1",)
    plotinfo = dict(plot=True, subplot=True)

    params = (
        ("timeframe", None),
        ("compression", None),
        ("fund", None),
    )

    # Plot labels
    def _plotlabel(self):
        return [
            TimeFrame.getname(self.p.timeframe, self.p.compression),
            str(self.p.compression or 1),
        ]

    def __init__(self):
        """Initialize the LogReturns observer.

        Adds LogReturnsRolling analyzer to track log returns.
        """
        self.logret1 = self._owner._addanalyzer_slave(
            LogReturnsRolling, data=self.data0, **self.p._getkwargs()
        )

    def next(self):
        """Update log return value for the current period.

        Gets the log return from the analyzer.
        """
        self.lines.logret1[0] = self.logret1.rets[self.logret1.dtkey]


# Show log returns for the second instrument
class LogReturns2(LogReturns):
    """Extends the observer LogReturns to show two instruments"""

    lines = ("logret2",)

    def __init__(self):
        """Initialize the LogReturns2 observer.

        Adds analyzer for second data feed's log returns.
        """
        super().__init__()

        self.logret2 = self._owner._addanalyzer_slave(
            LogReturnsRolling, data=self.data1, **self.p._getkwargs()
        )

    def next(self):
        """Update log return values for both data feeds.

        Updates logret1 from parent and logret2 for second feed.
        """
        super().next()
        self.lines.logret2[0] = self.logret2.rets[self.logret2.dtkey]
