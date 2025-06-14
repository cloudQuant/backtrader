#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from backtrader import TimeFrameAnalyzerBase


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
        # 计算第一个period的收益率的时候，是否使用第一个开盘价计算，如果参数是False, 就会使用第一个收盘价

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

    # 参数
    params = (
        ("data", None),
        ("firstopen", True),
        ("fund", None),
    )

    # 开始
    def __init__(self, *args, **kwargs):
        super(TimeReturn, self).__init__(*args, **kwargs)
        
        self._value_start = None
        self._value_end = None
        self._fundmode = None

    def start(self):
        super(TimeReturn, self).start()
        
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund

        # Initialize starting value
        if self.p.data is None:
            if not self._fundmode:
                self._value_start = self.strategy.broker.getvalue()
            else:
                self._value_start = self.strategy.broker.fundvalue
        else:
            # Track specific data
            if len(self.p.data) > 0:
                if self.p.firstopen:
                    self._value_start = self.p.data.open[0]
                else:
                    self._value_start = self.p.data[0]
            else:
                self._value_start = 1.0  # Default fallback

    def notify_fund(self, cash, value, fundvalue, shares):
        # Update current value for tracking
        if not self._fundmode:
            self._value_end = value if self.p.data is None else self.p.data[0]
        else:
            self._value_end = fundvalue if self.p.data is None else self.p.data[0]

    def stop(self):
        # Final calculation at end of backtest
        if self.p.data is None:
            if not self._fundmode:
                self._value_end = self.strategy.broker.getvalue()
            else:
                self._value_end = self.strategy.broker.fundvalue
        else:
            if len(self.p.data) > 0:
                self._value_end = self.p.data[0]

        # Calculate final return for the entire period
        if self._value_start and self._value_start != 0:
            final_return = (self._value_end / self._value_start) - 1.0
            self.rets[self.dtkey] = final_return

    def on_dt_over(self):
        """Called when a timeframe period is over - store the return for this period"""
        # Get end value for this period
        if self.p.data is None:
            if not self._fundmode:
                value_end = self.strategy.broker.getvalue()
            else:
                value_end = self.strategy.broker.fundvalue
        else:
            if len(self.p.data) > 0:
                value_end = self.p.data[0]
            else:
                value_end = self._value_start  # No change if no data

        # Calculate return for this period
        if self._value_start and self._value_start != 0:
            period_return = (value_end / self._value_start) - 1.0
            # Store the return with the period's datetime key
            self.rets[self.dtkey] = period_return
            
        # Update start value for next period  
        self._value_start = value_end

    def next(self):
        super(TimeReturn, self).next()
        
        # Get current portfolio value
        if self.p.data is None:
            if not self._fundmode:
                self._value_end = self.strategy.broker.getvalue()
            else:
                self._value_end = self.strategy.broker.fundvalue
        else:
            self._value_end = self.p.data[0]
        
        # Set initial start value on first call
        if self._value_start is None:
            if self.p.data is None:
                self._value_start = self._value_end
            else:
                if self.p.firstopen:
                    self._value_start = self.p.data.open[0]
                else:
                    self._value_start = self.p.data[0]
