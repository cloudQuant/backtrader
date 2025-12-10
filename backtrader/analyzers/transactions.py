#!/usr/bin/env python
import collections
from backtrader import Order, Position
from . import Analyzer


# 交易
class Transactions(Analyzer):
    """This analyzer reports the transactions occurred with each every data in
    the system

    It looks at the order execution bits to create a `Position` starting from
    0 during each `next` cycle.

    The result is used during next to record the transactions

    Params:

      - Headers (default: ``True``)

        Add an initial key to the dictionary holding the results with the names
        of the datas

        This analyzer was modeled to facilitate the integration with
        ``pyfolio``, and the header names are taken from the samples used for
        it::

          'Date', 'amount', 'price', 'sid', 'symbol', 'value'

    Methods:

      - Get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    # 参数
    params = (
        ("headers", False),
        ("_pfheaders", ("date", "amount", "price", "sid", "symbol", "value")),
    )

    # 开始
    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        self._idnames = None
        self._positions = None

    def start(self):
        super().start()
        # 如果headers等于True的话，初始化rets
        if self.p.headers:
            self.rets[self.p._pfheaders[0]] = [list(self.p._pfheaders[1:])]
        # 持仓
        self._positions = collections.defaultdict(Position)
        # index和数据名字
        self._idnames = list(enumerate(self.strategy.getdatanames()))

    # 订单信息处理
    def notify_order(self, order):
        # An order could have several partial executions per cycle (unlikely
        # but possible) and therefore: collect each new execution notification
        # and let the work for the next

        # We use a fresh Position object for each round to get a summary of what
        # the execution bits have done in that round
        # 如果订单没有成交，忽略
        if order.status not in [Order.Partial, Order.Completed]:
            return  # It's not an execution
        # 获取产生订单的数据的持仓
        pos = self._positions[order.data._name]
        # 循环
        for exbit in order.executed.iterpending():
            # 如果执行信息是None的话，跳出
            if exbit is None:
                break  # end of pending reached
            # 更新仓位信息
            pos.update(exbit.size, exbit.price)

    # 每个bar调用一次
    def next(self):
        # super(Transactions, self).next()  # let dtkey update
        # 入场
        entries = []
        # 对于index和数据名称
        for i, dname in self._idnames:
            # 获取数据的持仓
            pos = self._positions.get(dname, None)
            # 如果持仓不是None的话，如果持仓并且不是0，就保存持仓相关的数据
            if pos is not None:
                size, price = pos.size, pos.price
                if size:
                    entries.append([size, price, i, dname, -size * price])
        # 如果持仓不是0的话，更新当前bar的持仓数据
        if entries:
            self.rets[self.strategy.datetime.datetime()] = entries
        # 清空self._positions
        self._positions.clear()
