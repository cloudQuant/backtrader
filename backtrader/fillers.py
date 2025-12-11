#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .parameters import ParameterizedBase
from .utils.py3 import MAXINT


# 固定大小过滤，订单执行的时候只能成交当前成交量，需要下单量和size中最小的一个，如果size是None的话，忽略size
class FixedSize(ParameterizedBase):
    """Returns the execution size for a given order using a *percentage* of the
    volume in a bar.

    This percentage is set with the parameter ``perc``

    Params:

      - ``size`` (default: ``None``) maximum size to be executed.
      The actual
        volume of the bar at execution time is also a limit if smaller than the
        size

        If the value of this parameter evaluates to False, the entire volume
        of the bar will be used to match the order
    """

    params = (("size", None),)

    def __call__(self, order, price, ago):
        size = self.p.size or MAXINT
        return min((order.data.volume[ago], abs(order.executed.remsize), size))


# 固定百分比，用当前成交量的一定的百分比和需要下单的量对比，选择最小的进行交易
class FixedBarPerc(ParameterizedBase):
    """Returns the execution size for a given order using a *percentage* of the
    volume in a bar.

    This percentage is set with the parameter ``perc``

    Params:

      - ``perc`` (default: ``100.0``) (valied values: ``0.0-100.0``)

        Percentage of the volume bar to use to execute an order
    """

    params = (("perc", 100.0),)

    def __call__(self, order, price, ago):
        # Get the volume and scale it to the requested perc
        maxsize = (order.data.volume[ago] * self.p.perc) // 100
        # Return the maximum possible executed volume
        return min(maxsize, abs(order.executed.remsize))


# 根据bar的波动幅度按照百分比分配
class BarPointPerc(ParameterizedBase):
    """Returns the execution size for a given order. The volume will be
    distributed uniformly in the range *high*-*low* using ``minmov`` to
    partition.

    From the allocated volume for the given price, the `perc` percentage will
    be used

    Params:

      - ``minmov`` (default: ``0.01``)

        Minimum price movement. Used to partition the range *high*-*low* to
        proportionally distribute the volume amongst possible prices

      - ``perc`` (default: ``100.0``) (valied values: ``0.0-100.0``)

        Percentage of the volume allocated to the order execution price to use
        for matching
        # minmov默认是0.01，根据最高价和最低价之间的距离，看一下可以分成多少份
        # perc默认是100，交易限制是下单只能下每一份的perc
    """

    # 具体的参数
    params = (
        ("minmov", None),
        ("perc", 100.0),
    )

    def __call__(self, order, price, ago):
        # 数据
        data = order.data
        # 最小价格移动
        minmov = self.p.minmov
        # 计算可以分成的份数
        parts = 1
        if minmov:
            # high - low + minmov to account for open-ended minus op
            parts = (data.high[ago] - data.low[ago] + minmov) // minmov
        # 计算每一份可以成交多少
        alloc_vol = ((data.volume[ago] / parts) * self.p.perc) // 100.0
        # return max possible executable volume
        # 返回最大的可执行的订单量
        return min(alloc_vol, abs(order.executed.remsize))
