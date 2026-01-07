#!/usr/bin/env python
"""Returns Analyzer Module - Return statistics calculation.

This module provides the Returns analyzer for calculating total, average,
compound, and annualized returns using a logarithmic approach.

Classes:
    Returns: Analyzer that calculates return statistics.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.Returns, _name='ret')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.ret.get_analysis())
"""
import math

from ..analyzer import TimeFrameAnalyzerBase
from ..dataseries import TimeFrame


# Calculate total, average, compound and annualized returns using logarithmic method
class Returns(TimeFrameAnalyzerBase):
    """
    Total, Average, Compound and Annualized Returns calculated using a
    logarithmic approach

    See:

      - https://www.crystalbull.com/sharpe-ratio-better-with-log-returns/

    Params:

      - ``timeframe`` (default: ``None``)

        If ``None`` the `timeframe` of the first data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - ``tann`` (default: ``None``)

        Number of periods to use for the annualization (normalization)

        namely:

          - ``days: 252``
          - ``weeks: 52``
          - ``months: 12``
          - ``years: 1``

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys

        The returned dict the following keys:

          - ``rtot``: Total compound return
          - ``ravg``: Average return for the entire period (timeframe specific)
          - ``rnorm``: Annualized/Normalized return
          - ``rnorm100``: Annualized/Normalized return expressed in 100%

    """

    # Parameters
    params = (
        ("tann", None),
        ("fund", None),
    )
    # Days etc. for calculating annualization
    _TANN = {
        TimeFrame.Days: 252.0,
        TimeFrame.Weeks: 52.0,
        TimeFrame.Months: 12.0,
        TimeFrame.Years: 1.0,
    }

    # Start
    def __init__(self, *args, **kwargs):
        # Call parent class __init__ method to support timeframe and compression parameters
        super().__init__(*args, **kwargs)

        self._value_end = None
        self._tcount = None
        self._value_start = None
        self._fundmode = None

    def start(self):
        super().start()
        # If fund is None, _fundmode is broker's fundmode, otherwise equals fund
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # If fundmode is False, get value, otherwise get fundvalue
        if not self._fundmode:
            self._value_start = self.strategy.broker.getvalue()
        else:
            self._value_start = self.strategy.broker.fundvalue
        # Count subperiods
        self._tcount = 0

    # When stopping
    def stop(self):
        super().stop()
        # If fundmode is False, get value, otherwise get fundvalue
        if not self._fundmode:
            self._value_end = self.strategy.broker.getvalue()
        else:
            self._value_end = self.strategy.broker.fundvalue

        # Compound return
        # rtot calculates total log returns
        try:
            nlrtot = self._value_end / self._value_start
        except ZeroDivisionError:
            rtot = float("-inf")
        else:
            if nlrtot < 0.0:
                rtot = float("-inf")
            else:
                rtot = math.log(nlrtot)

        self.rets["rtot"] = rtot

        # Average return
        # Calculate average return, first calculate log returns, then calculate average log returns
        if self._tcount > 0:
            self.rets["ravg"] = ravg = rtot / self._tcount
        else:
            self.rets["ravg"] = ravg = 0.0

        # Annualized normalized return
        # Calculate annualized return
        tann = self.p.tann or self._TANN.get(self.timeframe, None)
        if tann is None:
            tann = self._TANN.get(self.data._timeframe, 1.0)  # assign default

        if ravg > float("-inf"):
            self.rets["rnorm"] = rnorm = math.expm1(ravg * tann)
        else:
            self.rets["rnorm"] = rnorm = ravg
        # Annualized return in percentage form
        self.rets["rnorm100"] = rnorm * 100.0  # human-readable %

    def on_dt_over(self):
        self._tcount += 1  # count the subperiod
