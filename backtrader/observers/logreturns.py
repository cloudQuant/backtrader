#!/usr/bin/env python

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

    # Calculate log returns via LogReturnsRolling during initialization
    def __init__(self):
        self.logret1 = self._owner._addanalyzer_slave(
            LogReturnsRolling, data=self.data0, **self.p._getkwargs()
        )

    # Assign value to logret1
    def next(self):
        self.lines.logret1[0] = self.logret1.rets[self.logret1.dtkey]


# Show log returns for the second instrument
class LogReturns2(LogReturns):
    """Extends the observer LogReturns to show two instruments"""

    lines = ("logret2",)

    def __init__(self):
        super().__init__()

        self.logret2 = self._owner._addanalyzer_slave(
            LogReturnsRolling, data=self.data1, **self.p._getkwargs()
        )

    def next(self):
        super().next()
        self.lines.logret2[0] = self.logret2.rets[self.logret2.dtkey]
