#!/usr/bin/env python
"""TimeReturn Observer Module - Time-based returns tracking.

This module provides the TimeReturn observer for tracking strategy
returns over different time periods.

Classes:
    TimeReturn: Observer that tracks returns over time periods.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.TimeReturn, timeframe=bt.TimeFrame.Days)
"""

from ..analyzers.timereturn import TimeReturn as TimeReturnAnalyzer
from ..dataseries import TimeFrame
from ..observer import Observer


# Time return class
class TimeReturn(Observer):
    """This observer stores the *returns* of the strategy.

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
    # Set lines
    lines = ("timereturn",)
    # Plot info
    plotinfo = dict(plot=True, subplot=True)
    # Set plotlines
    plotlines = dict(timereturn=dict(_name="Return"))
    # Parameters
    params = (
        ("timeframe", None),
        ("compression", None),
        ("fund", None),
    )

    # Plot labels
    def _plotlabel(self):
        return [
            # Use the final tf/comp values calculated by the return analyzer
            TimeFrame.getname(self.treturn.timeframe, self.treturn.compression),
            str(self.treturn.compression),
        ]

    def __init__(self):
        """Initialize the TimeReturn observer.

        Adds TimeReturn analyzer to track returns over time.
        """
        self.treturn = self._owner._addanalyzer_slave(TimeReturnAnalyzer, **self.p._getkwargs())

    def next(self):
        """Update the time return value for the current period.

        Gets the return value from the analyzer for the current time key.
        """
        self.lines.timereturn[0] = self.treturn.rets.get(self.treturn.dtkey, float("NaN"))
