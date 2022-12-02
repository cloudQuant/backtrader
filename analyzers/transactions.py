#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)


import collections

import backtrader as bt
from backtrader import Order, Position

# 交易
class Transactions(bt.Analyzer):
    '''This analyzer reports the transactions occurred with each an every data in
    the system

    It looks at the order execution bits to create a ``Position`` starting from
    0 during each ``next`` cycle.

    The result is used during next to record the transactions

    Params:

      - headers (default: ``True``)

        Add an initial key to the dictionary holding the results with the names
        of the datas

        This analyzer was modeled to facilitate the integration with
        ``pyfolio`` and the header names are taken from the samples used for
        it::

          'date', 'amount', 'price', 'sid', 'symbol', 'value'

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    '''
    # 参数
    params = (
        ('headers', False),
        ('_pfheaders', ('date', 'amount', 'price', 'sid', 'symbol', 'value')),
    )
    # 开始
    def start(self):
        super(Transactions, self).start()
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
        # and let the work for next

        # We use a fresh Position object for each round to get summary of what
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
