#!/usr/bin/env python
"""DrawDown Analyzer Module - Drawdown statistics calculation.

This module provides analyzers for calculating drawdown statistics including
current drawdown, maximum drawdown, and drawdown duration.

Classes:
    DrawDown: Analyzer that calculates drawdown statistics.
    TimeDrawDown: Time-frame based drawdown analyzer.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.dd.get_analysis())
"""
from ..analyzer import Analyzer, TimeFrameAnalyzerBase
from ..utils import AutoOrderedDict

__all__ = ["DrawDown", "TimeDrawDown"]


# Analyze drawdown situation
class DrawDown(Analyzer):
    """This analyzer calculates trading system drawdowns stats such as drawdown
    values in %s and in dollars, max drawdown in %s and in dollars, drawdown
    length and drawdown max length

    Params:

      - ``fund`` (default: ``None``)

        If ``None``, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - ``get_analysis``

        Returns a dictionary (with . notation support and subdctionaries) with
        drawdown stats as values, the following keys/attributes are available:

        - ``drawdown`` - drawdown value in 0.xx %
        - ``moneydown`` - drawdown value in monetary units
        - ``len`` - drawdown length

        - ``max.drawdown`` - max drawdown value in 0.xx %
        - ``max.moneydown`` - max drawdown value in monetary units
        - ``max.len`` - max drawdown length
    """

    params = (("fund", None),)

    # Start, get fundmode
    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Sets the fund mode based on parameters or broker settings.
        """
        super().start()
        if self.p.fund is None:
            # self._fundmode = self.strategy.broker.fundmode
            setattr(self, "_fundmode", self.strategy.broker.fundmode)
        else:
            # self._fundmode = self.p.fund
            setattr(self, "_fundmode", self.p.fund)

    # Create indicator values to analyze
    def create_analysis(self):
        """Create the analysis result data structure.

        Initializes the results dictionary with all drawdown metrics set to zero.
        """
        self.rets = AutoOrderedDict()  # dict with. notation

        self.rets.len = 0
        self.rets.drawdown = 0.0
        self.rets.moneydown = 0.0

        self.rets.max.len = 0.0
        self.rets.max.drawdown = 0.0
        self.rets.max.moneydown = 0.0

        self._maxvalue = float("-inf")  # any value will outdo it

    # Stop
    def stop(self):
        """Finalize the analysis when backtest ends.

        Closes the results dictionary to prevent further modifications.
        """
        self.rets._close()  # . notation cannot create more keys

    # Notify fund situation
    def notify_fund(self, cash, value, fundvalue, shares):
        """Update drawdown calculation with current fund values.

        Args:
            cash: Current cash amount.
            value: Current portfolio value.
            fundvalue: Current fund value.
            shares: Number of fund shares.
        """
        if not self._fundmode:
            self._value = value  # record current value
            self._maxvalue = max(self._maxvalue, value)  # update peak value
        else:
            self._value = fundvalue  # record current value
            self._maxvalue = max(self._maxvalue, fundvalue)  # update peak

    def next(self):
        """Calculate drawdown for the current period.

        Updates current and maximum drawdown values and lengths.
        """
        r = self.rets

        # calculate current drawdown values
        r.moneydown = moneydown = self._maxvalue - self._value
        r.drawdown = drawdown = 100.0 * moneydown / self._maxvalue

        # maxximum drawdown values
        r.max.moneydown = max(r.max.moneydown, moneydown)
        r.max.drawdown = max(r.max.drawdown, drawdown)

        r.len = r.len + 1 if drawdown else 0
        r.max.len = max(r.max.len, r.len)


# Analyze time drawdown situation (max drawdown)
class TimeDrawDown(TimeFrameAnalyzerBase):
    """This analyzer calculates trading system drawdowns on the chosen
    timeframe which can be different from the one used in the underlying data
    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` the ``timeframe`` of the 1st data in the system will be
        used

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If None, then the compression of the 1st data of the system will be
        used
      - *None*

      - ``fund`` (default: ``None``)

        If ``None``, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - ``get_analysis``

        Returns a dictionary (with . notation support and subdctionaries) with
        drawdown stats as values, the following keys/attributes are available:

        - ``drawdown`` - drawdown value in 0.xx %
        - ``maxdrawdown`` - drawdown value in monetary units
        - ``maxdrawdownperiod`` - drawdown length

      - Those are available during runs as attributes
        - ``dd``
        - ``maxdd``
        - ``maxddlen``
    """

    params = (("fund", None),)

    def __init__(self, *args, **kwargs):
        """Initialize the TimeDrawDown analyzer.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # Call parent class __init__ method to support timeframe and compression parameters
        super().__init__(*args, **kwargs)

        self.ddlen = None
        self.peak = None
        self.maxddlen = None
        self.maxdd = None
        self.dd = None
        self._fundmode = None

    def start(self):
        """Initialize the analyzer at the start of the backtest.

        Sets the fund mode and initializes drawdown tracking variables.
        """
        super().start()
        # fundmode
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # Initialize parameters
        self.dd = 0.0
        self.maxdd = 0.0
        self.maxddlen = 0
        self.peak = float("-inf")
        self.ddlen = 0

    # Calculate max drawdown and max drawdown length
    def on_dt_over(self):
        """Called when a datetime period is over.

        Updates drawdown calculations for the timeframe period.
        """
        if not self._fundmode:
            value = self.strategy.broker.getvalue()
        else:
            value = self.strategy.broker.fundvalue

        # update the maximum seen peak
        if value > self.peak:
            self.peak = value
            self.ddlen = 0  # start of streak

        # calculate the current drawdown
        self.dd = dd = 100.0 * (self.peak - value) / self.peak
        self.ddlen += bool(dd)  # if peak == value -> dd = 0

        # update the maxdrawdown if needed
        self.maxdd = max(self.maxdd, dd)
        self.maxddlen = max(self.maxddlen, self.ddlen)

    # When stopping, add max drawdown and max drawdown length to dictionary
    def stop(self):
        """Finalize the analysis when backtest ends.

        Stores the maximum drawdown and maximum drawdown period.
        """
        self.rets["maxdrawdown"] = self.maxdd
        self.rets["maxdrawdownperiod"] = self.maxddlen
