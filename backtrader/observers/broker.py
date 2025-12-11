#!/usr/bin/env python
from ..observer import Observer


# 获取cash
class Cash(Observer):
    """This observer keeps track the current amount of cash in the broker

    Params: None
    """

    _stclock = True

    lines = ("cash",)

    plotinfo = dict(plot=True, subplot=True)

    def next(self):
        self.lines[0][0] = self._owner.broker.getcash()


# 获取value
class Value(Observer):
    """This observer keeps track of the current portfolio value in the broker
    including the cash

    Params:

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    """

    _stclock = True

    params = (("fund", None),)

    lines = ("value",)

    plotinfo = dict(plot=True, subplot=True)

    def __init__(self):
        self._fundmode = None

    def start(self):
        if self.p.fund is None:
            self._fundmode = self._owner.broker.fundmode
        else:
            self._fundmode = self.p.fund

    def next(self):
        if not self._fundmode:
            self.lines[0][0] = self._owner.broker.getvalue()
        else:
            self.lines[0][0] = self._owner.broker.fundvalue


# 同时获取cash和value
class Broker(Observer):
    """This observer keeps track of the current cash amount and portfolio value in
    the broker (including the cash)

    Params: None
    """

    _stclock = True

    params = (("fund", None),)

    alias = ("CashValue",)
    lines = ("cash", "value")

    plotinfo = dict(plot=True, subplot=True)

    def __init__(self):
        self._fundmode = None

    def start(self):
        if self.p.fund is None:
            self._fundmode = self._owner.broker.fundmode
        else:
            self._fundmode = self.p.fund

        if self._fundmode:
            self.plotlines.cash._plotskip = True
            self.plotlines.value._name = "FundValue"

    def next(self):
        if not self._fundmode:
            self.lines.value[0] = self._owner.broker.getvalue()
            self.lines.cash[0] = self._owner.broker.getcash()
        else:
            self.lines.value[0] = self._owner.broker.fundvalue


# fundvalue
class FundValue(Observer):
    """This observer keeps track of the current fund-like value

    Params: None
    """

    _stclock = True

    alias = ("FundShareValue", "FundVal")
    lines = ("fundval",)

    plotinfo = dict(plot=True, subplot=True)

    def next(self):
        self.lines.fundval[0] = self._owner.broker.fundvalue


# 基金份额
class FundShares(Observer):
    """This observer keeps track of the current fund-like shares

    Params: None
    """

    _stclock = True

    lines = ("fundshares",)

    plotinfo = dict(plot=True, subplot=True)

    def next(self):
        self.lines.fundshares[0] = self._owner.broker.fundshares
