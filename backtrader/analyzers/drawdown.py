#!/usr/bin/env python
from . import Analyzer
from backtrader import TimeFrameAnalyzerBase
from backtrader.utils import AutoOrderedDict

__all__ = ["DrawDown", "TimeDrawDown"]


# 分析回撤的情况
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

    # 开始，获取fundmode
    def start(self):
        super().start()
        if self.p.fund is None:
            # self._fundmode = self.strategy.broker.fundmode
            setattr(self, "_fundmode", self.strategy.broker.fundmode)
        else:
            # self._fundmode = self.p.fund
            setattr(self, "_fundmode", self.p.fund)

    # 创建需要分析的指标值
    def create_analysis(self):
        self.rets = AutoOrderedDict()  # dict with. notation

        self.rets.len = 0
        self.rets.drawdown = 0.0
        self.rets.moneydown = 0.0

        self.rets.max.len = 0.0
        self.rets.max.drawdown = 0.0
        self.rets.max.moneydown = 0.0

        self._maxvalue = float("-inf")  # any value will outdo it

    # 停止
    def stop(self):
        self.rets._close()  # . notation cannot create more keys

    # 通知fund的情况
    def notify_fund(self, cash, value, fundvalue, shares):
        if not self._fundmode:
            self._value = value  # record current value
            self._maxvalue = max(self._maxvalue, value)  # update peak value
        else:
            self._value = fundvalue  # record current value
            self._maxvalue = max(self._maxvalue, fundvalue)  # update peak

    def next(self):
        r = self.rets

        # calculate current drawdown values
        r.moneydown = moneydown = self._maxvalue - self._value
        r.drawdown = drawdown = 100.0 * moneydown / self._maxvalue

        # maxximum drawdown values
        r.max.moneydown = max(r.max.moneydown, moneydown)
        r.max.drawdown = max(r.max.drawdown, drawdown)

        r.len = r.len + 1 if drawdown else 0
        r.max.len = max(r.max.len, r.len)


# 分析时间回撤情况(最大回撤)
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
        # 调用父类的__init__方法以支持timeframe和compression参数
        super().__init__(*args, **kwargs)

        self.ddlen = None
        self.peak = None
        self.maxddlen = None
        self.maxdd = None
        self.dd = None
        self._fundmode = None

    def start(self):
        super().start()
        # fundmode
        if self.p.fund is None:
            self._fundmode = self.strategy.broker.fundmode
        else:
            self._fundmode = self.p.fund
        # 初始化参数
        self.dd = 0.0
        self.maxdd = 0.0
        self.maxddlen = 0
        self.peak = float("-inf")
        self.ddlen = 0

    # 统计最大回撤以及最大回撤的长度
    def on_dt_over(self):
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

    # 停止的时候，把最大回撤和最大回撤长度添加到字典中
    def stop(self):
        self.rets["maxdrawdown"] = self.maxdd
        self.rets["maxdrawdownperiod"] = self.maxddlen
