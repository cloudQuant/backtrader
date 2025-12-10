#!/usr/bin/env python
from . import Analyzer
from backtrader.dataseries import TimeFrame


# 持仓价值
class PositionsValue(Analyzer):
    """This analyzer reports the value of the positions of the current set of
    datas

    Params:

      - timeframe (default: ``None``)
        If ``None`` then the timeframe of the first data of the system will be
        used

      - compression (default: ``None``)

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If `None`, then the compression of the first data in the system will be
        used

      - headers (default: ``False``)

        Add an initial key to the dictionary holding the results with the names
        of the data 'Datetime' as a key

      - cash (default: ``False``)

        Include the actual cash as an extra position (for the header 'cash'
        will be used as name)

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    # 参数
    params = (
        ("headers", False),
        ("cash", False),
    )

    # 开始
    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        self._usedate = None

    def start(self):
        # 如果headers参数是True,每个data的命字作为header
        if self.p.headers:
            headers = [d._name or "Data%d" % i for i, d in enumerate(self.datas)]
            # 如果cash是True的话，也会保存cash
            self.rets["Datetime"] = headers + ["cash"] * self.p.cash
        # 时间周期
        tf = min(d._timeframe for d in self.datas)
        # 如果时间周期大于等于日，usedate参数设置成True
        self._usedate = tf >= TimeFrame.Days

    # 每个bar调用一次
    def next(self):
        # 获取每个数据的value
        pvals = [self.strategy.broker.get_value([d]) for d in self.datas]
        # 如果cash是True的话，保存cash
        if self.p.cash:
            pvals.append(self.strategy.broker.get_cash())
        # 如果usedate是True,使用date作为key,否则使用datetime作为key
        if self._usedate:
            self.rets[self.strategy.datetime.date()] = pvals
        else:
            self.rets[self.strategy.datetime.datetime()] = pvals
