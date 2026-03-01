#!/usr/bin/env python
"""Period Statistics Analyzer Module - Basic statistics by period.

This module provides the PeriodStats analyzer for calculating basic
statistics (average, standard deviation, etc.) for a given timeframe.

Classes:
    PeriodStats: Analyzer that calculates period statistics.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='stats')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.stats.get_analysis())
"""

from ..analyzer import Analyzer
from ..dataseries import TimeFrame
from ..mathsupport import average, standarddev
from ..metabase import OwnerContext
from ..utils.py3 import itervalues
from .timereturn import TimeReturn

__all__ = ["PeriodStats"]


# Period statistics
class PeriodStats(Analyzer):
    """Calculates basic statistics for given timeframe

    Params:

      - ``timeframe`` (default: ``Years``)
        If ``None`` the ``timeframe`` of the first data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``1``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior


    ``get_analysis`` returns a dictionary containing the keys:

      - ``average``
      - ``stddev``
      - ``positive``
      - ``negative``
      - ``nochange``
      - ``best``
      - ``worst``

    If the parameter ``zeroispos`` is set to ``True``, periods with no change
    will be counted as positive
    """

    # Parameters
    params = (
        ("timeframe", TimeFrame.Years),
        ("compression", 1),
        ("zeroispos", False),
        ("fund", None),
    )

    # Initialize, call TimeReturn
    def __init__(self, *args, **kwargs):
        """Initialize the PeriodStats analyzer.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        # Use OwnerContext so child analyzer can find this as its parent
        with OwnerContext.set_owner(self):
            self._tr = TimeReturn(
                timeframe=self.p.timeframe, compression=self.p.compression, fund=self.p.fund
            )

    # Stop
    def stop(self):
        """Calculate period statistics when backtest ends.

        Computes average, standard deviation, and count of positive/negative/
        zero returns for the specified timeframe period.
        """
        # Get returns, default is annual
        trets = self._tr.get_analysis()  # dict key = date, value = ret
        # Count years with positive, negative, and zero returns
        pos = nul = neg = 0
        trets = list(itervalues(trets))
        for tret in trets:
            if tret > 0.0:
                pos += 1
            elif tret < 0.0:
                neg += 1
            else:
                # Whether 0 is considered positive return
                if self.p.zeroispos:
                    pos += tret == 0.0
                else:
                    nul += tret == 0.0
        # Average return
        self.rets["average"] = avg = average(trets)
        # Return standard deviation
        self.rets["stddev"] = standarddev(trets, avg)
        # Number of positive years
        self.rets["positive"] = pos
        # Number of negative years
        self.rets["negative"] = neg
        # Number of unchanged years
        self.rets["nochange"] = nul
        # Best year return
        self.rets["best"] = max(trets)
        # Worst year return
        self.rets["worst"] = min(trets)
