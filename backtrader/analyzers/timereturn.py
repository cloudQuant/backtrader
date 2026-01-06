#!/usr/bin/env python
from ..analyzer import TimeFrameAnalyzerBase


class TimeReturn(TimeFrameAnalyzerBase):
    """This analyzer calculates the Returns by looking at the beginning
    and end of the timeframe

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

        - Note:: this data must have been added to a ``cerebro`` instance with
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
        # When calculating returns for the first period, whether to use the first opening price. If parameter is False, the first closing price will be used

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

    # __init__ method to support parameter initialization after metaclass removal
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # Start
    def start(self):
        super().start()
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # Start value
        self._value_start = 0.0
        # End value
        self._lastvalue = None
        # If parameter data is None
        if self.p.data is None:
            # keep the initial portfolio value if not tracing a data
            if not self._fundmode:
                self._lastvalue = self.strategy.broker.getvalue()
            else:
                self._lastvalue = self.strategy.broker.fundvalue

    # Notify fund information
    def notify_fund(self, cash, value, fundvalue, shares):
        if not self._fundmode:
            # Record current value
            if self.p.data is None:
                self._value = value  # the portofolio value if tracking no data
            else:
                self._value = self.p.data[0]  # the data value if tracking data
        else:
            if self.p.data is None:
                self._value = fundvalue  # the fund value if tracking no data
            else:
                self._value = self.p.data[0]  # the data value if tracking data

    # On datetime over
    def on_dt_over(self):
        # next is called in a new timeframe period
        # if self.p.data is None or len(self.p.data) > 1:
        if self.p.data is None or self._lastvalue is not None:
            self._value_start = self._lastvalue  # update value_start to last

        else:
            # The 1st tick has no previous reference, use the opening price
            if self.p.firstopen:
                self._value_start = self.p.data.open[0]
            else:
                self._value_start = self.p.data[0]

    # Call next
    def next(self):
        # Calculate the return
        super().next()
        # self.dtkey is an attribute set in analyzer, usually the end date of a period
        self.rets[self.dtkey] = (self._value / self._value_start) - 1.0
        # self.rets[self.dtkey] = (float(self._value) / float(self._value_start)) - 1.0
        self._lastvalue = self._value  # keep last value
