#!/usr/bin/env python
"""LogReturnsRolling Analyzer Module - Rolling log returns calculation.

This module provides the LogReturnsRolling analyzer for calculating
rolling log returns over a specified timeframe.

Classes:
    LogReturnsRolling: Analyzer that calculates rolling log returns.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.LogReturnsRolling)
"""
import collections
import math

from ..analyzer import TimeFrameAnalyzerBase

__all__ = ["LogReturnsRolling"]


class LogReturnsRolling(TimeFrameAnalyzerBase):
    """This analyzer calculates rolling returns for a given timeframe and
    compression

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` the ``timeframe`` of the first data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - ``data`` (default: ``None``)

        Reference asset to track instead of the portfolio value.

        .note: this data must have been added to a ``cerebro`` instance with
                  ``addata``, ``resampledata`` or ``replaydata``

      - ``firstopen`` (default: ``True``)

        When tracking the returns of `data` the following is done when
        crossing a timeframe boundary, for example, ``Years``:

          - Last ``close`` the previous year is used as the reference price to
            see the return in the current year

        The problem is the first calculation, because the data has** no
        previous** closing price.As such, and when this parameter is `True`,
        the *opening* price will be used for the first calculation.

        This requires the data feed to have an ``open`` price (for ``close``
        the standard [0] notations will be used without a reference to a field
        price)

        Else the initial close will be used.

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
    """

    # Parameters
    params = (
        ("data", None),
        ("firstopen", True),
        ("fund", None),
    )

    # Start
    def __init__(self, *args, **kwargs):
        """Initialize the LogReturnsRolling analyzer.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # Call parent class __init__ method to support timeframe and compression parameters
        super().__init__(*args, **kwargs)

        self._value = None
        self._lastvalue = None
        self._values = None
        self._fundmode = None

    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Sets the fund mode and initializes the rolling value queue
        with size controlled by compression parameter.
        """
        super().start()
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # The special part is that self._values is set as a queue, where self.compression parameter controls how many elements the queue saves
        # Note: use self.compression (set in _start from data) not self.p.compression (which may be None)
        self._values = collections.deque(
            [float("Nan")] * self.compression, maxlen=self.compression
        )

        if self.p.data is None:
            # keep the initial portfolio value if not tracing data
            if not self._fundmode:
                self._lastvalue = self.strategy.broker.getvalue()
            else:
                self._lastvalue = self.strategy.broker.fundvalue

    def notify_fund(self, cash, value, fundvalue, shares):
        """Update current value from fund notification.

        Args:
            cash: Current cash amount.
            value: Current portfolio value.
            fundvalue: Current fund value.
            shares: Number of fund shares.
        """
        if not self._fundmode:
            self._value = value if self.p.data is None else self.p.data[0]
        else:
            self._value = fundvalue if self.p.data is None else self.p.data[0]

    # Called once in a new timeframe
    def on_dt_over(self):
        """Handle timeframe boundary crossing.

        Updates the rolling value queue when entering a new period.
        """
        # next is called in a new timeframe period
        if self.p.data is None or len(self.p.data) > 1:
            # Not tracking a data feed or data feed has data already
            vst = self._lastvalue  # update value_start to last
        else:
            # The 1st tick has no previous reference, use the opening price
            vst = self.p.data.open[0] if self.p.firstopen else self.p.data[0]

        self._values.append(vst)  # push values backwards (and out)

    def next(self):
        """Calculate and store the rolling log return for the current period.

        Calculates log(current_value / oldest_value) from the rolling window.
        """
        # Calculate the return
        super().next()
        # print(self._value,self._values[0])
        # When the strategy is running, if there are too many losses, self._value / self._values[0] might be 0, avoid this situation
        try:
            self.rets[self.dtkey] = math.log(self._value / self._values[0])
        except Exception:
            # print(e)  # Removed for performance
            self.rets[self.dtkey] = 0
            # print("When calculating log returns, the corresponding value is less than 0")
        self._lastvalue = self._value  # keep last value
