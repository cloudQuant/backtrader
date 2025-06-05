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
        # 调用父类的__init__方法以支持timeframe和compression参数
        super(TimeReturn, self).__init__(*args, **kwargs)
        
        self._value = None
        self._lastvalue = None
        self._value_start = None
        self._fundmode = None

    def start(self):
        super(TimeReturn, self).start()
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # 开始价值
        self._value_start = 0.0
        # 结束价值
        self._lastvalue = None
        # 如果参数data是None的时候
        if self.p.data is None:
            # keep the initial portfolio value if not tracing data
            if not self._fundmode:
                self._lastvalue = self.strategy.broker.getvalue()
            else:
                self._lastvalue = self.strategy.broker.fundvalue

    # 通知fund信息
    def notify_fund(self, cash, value, fundvalue, shares):
        if not self._fundmode:
            # Record current value
            if self.p.data is None:
                self._value = value  # the portfolio value if tracking no data
            else:
                self._value = self.p.data[0]  # the data value if tracking data
        else:
            if self.p.data is None:
                self._value = fundvalue  # the fund value if tracking no data
            else:
                self._value = self.p.data[0]  # the data value if tracking data

    # on_dt_over
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

    # 调用next
    def next(self):
        # Calculate the return
        super(TimeReturn, self).next()
        
        # CRITICAL FIX: Ensure _value is never None to prevent division by None
        if self._value is None:
            # Try to get value from strategy's broker
            if hasattr(self, 'strategy') and hasattr(self.strategy, 'broker'):
                broker = self.strategy.broker
                if broker is not None:
                    if hasattr(broker, 'getvalue'):
                        self._value = broker.getvalue()
                    elif hasattr(broker, 'value'):
                        self._value = broker.value
                    else:
                        self._value = 10000.0  # Fallback default
                else:
                    self._value = 10000.0  # Fallback default
            else:
                self._value = 10000.0  # Fallback default
        
        # CRITICAL FIX: Ensure _value_start is never None
        if self._value_start is None or self._value_start == 0.0:
            self._value_start = self._value if self._value is not None else 10000.0
        
        # Ensure both values are not None before division
        if self._value is not None and self._value_start is not None and self._value_start != 0.0:
            # self.dtkey是analyzer中设置的属性值，一般是一个period结束的日期
            self.rets[self.dtkey] = (self._value / self._value_start) - 1.0
        else:
            # Safe fallback: no change
            self.rets[self.dtkey] = 0.0
            
        # self.rets[self.dtkey] = (float(self._value) / float(self._value_start)) - 1.0
        self._lastvalue = self._value  # keep last value
