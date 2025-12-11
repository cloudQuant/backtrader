#!/usr/bin/env python

from ..analyzers.timereturn import TimeReturn as TimeReturnAnalyzer
from ..dataseries import TimeFrame
from ..observer import Observer


# 时间收益率的类
class TimeReturn(Observer):
    """This observer stores the *returns* of the strategy.

    Params:

      - ``timeframe`` (default: ``None``)
        If ``None`` then the complete return over the entire backtested period
        will be reported

        Pass ``TimeFrame.NoTimeFrame`` to consider the entire dataset with no
        time constraints

      - ``compression`` (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

      - ``fund`` (default: ``None``)

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Remember that at any moment of a `run` the current values can be checked
    by looking at the *lines* by name at index ``0``.

    """

    _stclock = True
    # 设置line
    lines = ("timereturn",)
    # plotinfo信息
    plotinfo = dict(plot=True, subplot=True)
    # 设置line
    plotlines = dict(timereturn=dict(_name="Return"))
    # 参数
    params = (
        ("timeframe", None),
        ("compression", None),
        ("fund", None),
    )

    # 画图时候的标签
    def _plotlabel(self):
        return [
            # Use the final tf/comp values calculated by the return analyzer
            TimeFrame.getname(self.treturn.timeframe, self.treturn.compression),
            str(self.treturn.compression),
        ]

    # 初始化，增加analyzers中的TimeReturn
    def __init__(self):
        self.treturn = self._owner._addanalyzer_slave(TimeReturnAnalyzer, **self.p._getkwargs())

    # 每个next设置当前的收益率
    def next(self):
        self.lines.timereturn[0] = self.treturn.rets.get(self.treturn.dtkey, float("NaN"))
