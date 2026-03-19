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

import math

from ..analyzer import Analyzer, TimeFrameAnalyzerBase
from ..utils import AutoOrderedDict

__all__ = ["DrawDown", "TimeDrawDown"]


def _is_finite_real(value):
    try:
        return not isinstance(value, complex) and math.isfinite(value)
    except TypeError:
        return False


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
        current_value = value if not self._fundmode else fundvalue
        self._value = current_value
        if _is_finite_real(current_value):
            if not _is_finite_real(self._maxvalue):
                self._maxvalue = current_value
            else:
                self._maxvalue = max(self._maxvalue, current_value)
        elif not _is_finite_real(self._maxvalue):
            self._maxvalue = 0.0

    def next(self):
        """Calculate drawdown for the current period.

        Updates current and maximum drawdown values and lengths.
        """
        # PERFORMANCE OPTIMIZATION: Cache attribute access to reduce lookups
        # Called 688K+ times, attribute caching helps
        r = self.rets
        maxvalue = self._maxvalue
        value = self._value
        r_max = r.max

        # calculate current drawdown values
        if not (_is_finite_real(maxvalue) and _is_finite_real(value)):
            moneydown = 0.0
            drawdown = 0.0
        else:
            moneydown = maxvalue - value
            drawdown = 100.0 * moneydown / maxvalue if maxvalue else 0.0
            if isinstance(moneydown, complex) or not math.isfinite(moneydown):
                moneydown = 0.0
            if isinstance(drawdown, complex) or not math.isfinite(drawdown):
                drawdown = 0.0

        r.moneydown = moneydown
        r.drawdown = drawdown

        # maximum drawdown values
        if moneydown > r_max.moneydown:
            r_max.moneydown = moneydown
        if drawdown > r_max.drawdown:
            r_max.drawdown = drawdown

        r.len = r.len + 1 if drawdown else 0
        if r.len > r_max.len:
            r_max.len = r.len


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
        value_valid = _is_finite_real(value)
        if not _is_finite_real(self.peak):
            self.peak = 0.0

        # update the maximum seen peak
        if value_valid and value > self.peak:
            self.peak = value
            self.ddlen = 0  # start of streak

        # calculate the current drawdown
        try:
            if value_valid and self.peak:
                self.dd = dd = 100.0 * (self.peak - value) / self.peak
                if isinstance(dd, complex) or not math.isfinite(dd):
                    self.dd = dd = 0.0
            else:
                self.dd = dd = 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            self.dd = dd = 0.0
        self.ddlen += bool(dd)  # if peak == value -> dd = 0

        # update the maxdrawdown if needed
        self.maxdd = max(self.maxdd if _is_finite_real(self.maxdd) else 0.0, dd)
        self.maxddlen = max(self.maxddlen, self.ddlen)

    # When stopping, add max drawdown and max drawdown length to dictionary
    def stop(self):
        """Finalize the analysis when backtest ends.

        Stores the maximum drawdown and maximum drawdown period.
        """
        self.rets["maxdrawdown"] = self.maxdd
        self.rets["maxdrawdownperiod"] = self.maxddlen
