#!/usr/bin/env python
"""VWR Analyzer Module - Variability-Weighted Return calculation.

This module provides the VWR (Variability-Weighted Return) analyzer,
an alternative to the Sharpe ratio using log returns.

Classes:
    VWR: Analyzer that calculates VWR metric.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.VWR, _name='vwr')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.vwr.get_analysis())
"""

import math

from ..analyzer import TimeFrameAnalyzerBase
from ..dataseries import TimeFrame
from ..mathsupport import standarddev
from ..metabase import OwnerContext
from .returns import Returns


# Get VWR indicator
class VWR(TimeFrameAnalyzerBase):
    """Variability-Weighted Return: Better SharpeRatio with Log Returns

    Alias:

      - VariabilityWeightedReturn

    See:

      - https://www.crystalbull.com/sharpe-ratio-better-with-log-returns/

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` then the complete return over the entire backtested period
        will be reported

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - ``tann`` (default: ``None``)

        Number of periods to use for the annualization (normalization) of the
        average returns. If ``None``, then standard ``t`` values will be used,
        namely:

          - ``days: 252``
          - ``weeks: 52``
          - ``months: 12``
          - ``years: 1``

      - ``tau`` (default: ``2.0``)

        Factor for the calculation (see the literature)

      - ``sdev_max`` (default: ``0.20``)

        Max standard deviation (see the literature)

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - Get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys

        The returned dict contains the following keys:

          - ``vwr``: Variability-Weighted Return
    """

    # Parameters
    params = (
        ("tann", None),
        ("tau", 0.20),
        ("sdev_max", 2.0),
        ("fund", None),
    )

    # Trading periods per year
    _TANN = {
        TimeFrame.Days: 252.0,
        TimeFrame.Weeks: 52.0,
        TimeFrame.Months: 12.0,
        TimeFrame.Years: 1.0,
    }

    # Initialize, get returns
    def __init__(self, *args, **kwargs):
        """Initialize the VWR analyzer.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # Call parent class __init__ method to support timeframe and compression parameters
        super().__init__(*args, **kwargs)

        # Children log return analyzer
        self._pns = None
        self._pis = None
        self._fundmode = None
        # Use OwnerContext so child analyzer can find this as its parent
        with OwnerContext.set_owner(self):
            self._returns = Returns(
                timeframe=self.p.timeframe, compression=self.p.compression, tann=self.p.tann
            )

    # Start
    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Sets the fund mode and initializes lists to track period
        start and end values.
        """
        super().start()
        # Add an initial placeholder for [-1] operation
        # Get fundmode
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # Get initial value based on fundmode
        if not self._fundmode:
            self._pis = [self.strategy.broker.getvalue()]  # keep initial value
        else:
            self._pis = [self.strategy.broker.fundvalue]  # keep initial value
        # Initialize final value to None
        self._pns = [None]  # keep final prices (value)

    # Stop
    def stop(self):
        """Calculate the VWR metric when backtest ends.

        VWR = rnorm100 * (1 - (sdev_p / sdev_max)^tau)
        where sdev_p is the standard deviation of period returns.
        """
        super().stop()
        # Check if no value has been seen after the last 'dt_over'
        # If so, there is one 'pi' out of place and a None 'pn'. Purge
        # If the last value is None, remove the last element
        if self._pns[-1] is None:
            self._pis.pop()
            self._pns.pop()

        # Get results from children
        # Get returns
        rs = self._returns.get_analysis()
        ravg = rs["ravg"]
        rnorm100 = rs["rnorm100"]

        # make n 1 based in enumerate (number of periods and not index)
        # skip initial placeholders for synchronization
        # Calculate return for each period (usually yearly, then save to dts)
        dts = []
        for n, pipn in enumerate(zip(self._pis, self._pns), 1):
            pi, pn = pipn
            # print(n,pi,pn,pipn,ravg,rs)
            dt = pn / (pi * math.exp(ravg * n)) - 1.0
            dts.append(dt)
        # Calculate standard deviation of annual returns
        sdev_p = standarddev(dts, bessel=True)
        # Calculate VWR value
        vwr = rnorm100 * (1.0 - pow(sdev_p / self.p.sdev_max, self.p.tau))
        self.rets["vwr"] = vwr

    # Fund notification
    def notify_fund(self, cash, value, fundvalue, shares):
        """Update the current period end value from fund notification.

        Args:
            cash: Current cash amount.
            value: Current portfolio value.
            fundvalue: Current fund value.
            shares: Number of fund shares.
        """
        if not self._fundmode:
            self._pns[-1] = value  # annotate last seen pn for the current period
        else:
            self._pns[-1] = fundvalue  # annotate last pn for current period

    def on_dt_over(self):
        """Handle timeframe boundary crossing.

        Moves the current period end value to be the next period's
        start value and creates a new placeholder.
        """
        self._pis.append(self._pns[-1])  # the last pn is pi in the next period
        self._pns.append(None)  # placeholder for [-1] operation


VariabilityWeightedReturn = VWR
