#!/usr/bin/env python
"""Calmar Ratio Analyzer Module - Calmar ratio calculation.

This module provides the Calmar analyzer for calculating the Calmar
ratio (annual return divided by maximum drawdown).

Classes:
    Calmar: Analyzer that calculates Calmar ratio.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.Calmar, _name='calmar')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.calmar.get_analysis())
"""

import collections
import math

from ..analyzer import TimeFrameAnalyzerBase
from ..dataseries import TimeFrame
from ..metabase import OwnerContext
from .drawdown import TimeDrawDown

__all__ = ["Calmar"]


# Calculate Calmar ratio. Overall, this Calmar calculation is not very successful, or the analyzer/observer series indicators are not very efficient in usage
# Consider creating an analysis module similar to pyfolio
class Calmar(TimeFrameAnalyzerBase):
    """This analyzer calculates the CalmarRatio
    timeframe which can be different from the one used in the underlying data
    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` the ``timeframe`` of the first data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If compression is None, then the compression of the first data in the system will be
        used
      - *None*

      - ``fund`` (default: ``None``)

        If ``None``, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    See also:

      - https://en.wikipedia.org/wiki/Calmar_ratio

    Methods:
      - ``get_analysis``

        Returns a OrderedDict with a key for the time period and the
        corresponding rolling Calmar ratio

    Attributes:
      - ``calmar`` the latest calculated calmar ratio
    """

    # Modules used
    packages = (
        "collections",
        "math",
    )
    # Parameters
    params = (
        ("timeframe", TimeFrame.Months),  # default in calmar
        ("period", 36),
        ("fund", None),
    )

    # Calculate max drawdown
    def __init__(self, *args, **kwargs):
        """Initialize the Calmar analyzer.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # Call parent class __init__ method to support timeframe and compression parameters
        super().__init__(*args, **kwargs)

        self.calmar = None
        self._fundmode = None
        self._values = None
        self._mdd = None
        # Use OwnerContext so child analyzer can find this as its parent
        with OwnerContext.set_owner(self):
            self._maxdd = TimeDrawDown(timeframe=self.p.timeframe, compression=self.p.compression)

    # Start
    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Sets up the maximum drawdown tracking, value history queue,
        and fund mode.
        """
        # Max drawdown rate
        self._mdd = float("-inf")
        # Double-ended queue, saves period values, default is 36
        self._values = collections.deque([float("Nan")] * self.p.period, maxlen=self.p.period)
        # fundmode
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # Add different values to self._values based on fundmode
        if not self._fundmode:
            self._values.append(self.strategy.broker.getvalue())
        else:
            self._values.append(self.strategy.broker.fundvalue)

    def on_dt_over(self):
        """Calculate Calmar ratio when timeframe period ends.

        Updates maximum drawdown and calculates Calmar ratio as
        annualized return divided by maximum drawdown.
        """
        # Max drawdown rate
        self._mdd = max(self._mdd, self._maxdd.maxdd)
        # Add value to self._values
        if not self._fundmode:
            self._values.append(self.strategy.broker.getvalue())
        else:
            self._values.append(self.strategy.broker.fundvalue)
        # Calculate average monthly return by default
        rann = math.log(self._values[-1] / self._values[0]) / len(self._values)
        # Calculate Calmar indicator
        self.calmar = calmar = rann / (self._mdd or float("Inf"))
        # Save result
        self.rets[self.dtkey] = calmar

    def stop(self):
        """Finalize the analysis when backtest ends.

        Triggers one final Calmar ratio calculation.
        """
        self.on_dt_over()  # update last values
