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

import itertools

from .utils import AutoOrderedDict
from .utils.date import num2date
from .utils.py3 import range


# 交易历史
class TradeHistory(AutoOrderedDict):
    '''Represents the status and update event for each update a Trade has

    This object is a dictionary which allows '.' notation
    # 这个类保存每个交易的状态和事件更新
    Attributes:
      - ``status`` (``dict`` with '.' notation): Holds the resulting status of
        an update event and has the following sub-attributes
        # 状态，字典格式，可以通过.访问，用于保存一个更新事件的状态，并且具有下面的次级属性
        - ``status`` (``int``): Trade status
            # 交易状态，整数格式
        - ``dt`` (``float``): float coded datetime
            # 时间，字符串格式
        - ``barlen`` (``int``): number of bars the trade has been active
            # 交易产生的时候bar的数量
        - ``size`` (``int``): current size of the Trade
            # 交易的当前大小，这里面是整数形式 todo 实际交易中可能用到非整数形式的交易手数
        - ``price`` (``float``): current price of the Trade
            # 交易的当前价格
        - ``value`` (``float``): current monetary value of the Trade
            # 交易的当前货币价值
        - ``pnl`` (``float``): current profit and loss of the Trade
            # 交易的当前的盈亏
        - ``pnlcomm`` (``float``): current profit and loss minus commission
            # 交易的当前的净盈亏
      - ``event`` (``dict`` with '.' notation): Holds the event update
        - parameters
        # 事件属性，保存事件更新的参数
        - ``order`` (``object``): the order which initiated the``update``
            # 产生交易的订单
        - ``size`` (``int``): size of the update
            # 更新的大小
        - ``price`` (``float``):price of the update
            # 更新的价格
        - ``commission`` (``float``): price of the update
            # 更新的佣金
    '''
    # 初始化
    def __init__(self,
                 status, dt, barlen, size, price, value, pnl, pnlcomm, tz, event=None):
        '''Initializes the object to the current status of the Trade'''
        super(TradeHistory, self).__init__()
        self.status.status = status
        self.status.dt = dt
        self.status.barlen = barlen
        self.status.size = size
        self.status.price = price
        self.status.value = value
        self.status.pnl = pnl
        self.status.pnlcomm = pnlcomm
        self.status.tz = tz
        if event is not None:
            self.event = event

    def __reduce__(self):
        return (self.__class__, (self.status.status, self.status.dt, self.status.barlen, self.status.size,
                                 self.status.price, self.status.value, self.status.pnl, self.status.pnlcomm,
                                 self.status.tz, self.event, ))
    # 做事件的更新
    def doupdate(self, order, size, price, commission):
        '''Used to fill the ``update`` part of the history entry'''
        self.event.order = order
        self.event.size = size
        self.event.price = price
        self.event.commission = commission

        # Do not allow updates (avoids typing errors)
        self._close()

    def datetime(self, tz=None, naive=True):
        '''Returns a datetime for the time the update event happened'''
        return num2date(self.status.dt, tz or self.status.tz, naive)

# Trade类
class Trade(object):
    '''Keeps track of the life of an trade: size, price,
    commission (and value?)

    An trade starts at 0 can be increased and reduced and can
    be considered closed if it goes back to 0.

    The trade can be long (positive size) or short (negative size)

    An trade is not meant to be reversed (no support in the logic for it)
    # 对一个trade的生命保持追踪，大小，价格，佣金（和市值)
    # 一个交易在0的时候开始，可以增加，也可以减少，并且在会到0的时候认为这个trade会关闭
    # 一个trade可以是多(正的大小)，也可以是空(负的大小)
    # 一个trade不可以从多转为空或者从空转为多，不支持这样的逻辑

    Member Attributes:

      - ``ref``: unique trade identifier
        # trade的标识符
      - ``status`` (``int``): one of Created, Open, Closed
        # trade的状态
      - ``tradeid``: grouping tradeid passed to orders during creation
        The default in orders is 0
        # 在交易创建的时候传输到order中的tradeid,order中默认的值是0
      - ``size`` (``int``): current size of the trade
        # trade的当前大小
      - ``price`` (``float``): current price of the trade
        # trade的当前价格
      - ``value`` (``float``): current value of the trade
        # trade的当前市值
      - ``commission`` (``float``): current accumulated commission
        # 当前累计的佣金
      - ``pnl`` (``float``): current profit and loss of the trade (gross pnl)
        # 当前的盈亏
      - ``pnlcomm`` (``float``): current profit and loss of the trade minus
        commission (net pnl)
        # 当前扣除手续费之后的净盈亏
      - ``isclosed`` (``bool``): records if the last update closed (set size to
        null the trade
        # 判断最近的一次更新事件是否关闭了这个交易，如果是关闭了，就把size设置为空值
      - ``isopen`` (``bool``): records if any update has opened the trade
        # 判断交易是否已经开仓
      - ``justopened`` (``bool``): if the trade was just opened
        # 判断交易是否刚开仓
      - ``baropen`` (``int``): bar in which this trade was opened
        # 记录是哪一个bar开仓的
      - ``dtopen`` (``float``): float coded datetime in which the trade was
        opened
        # 记录是在什么时间开仓的，可以使用open_datetime或者num2date获取python格式的时间
        - Use method ``open_datetime`` to get a Python datetime.datetime
          or use the platform provided ``num2date`` method
      - ``barclose`` (``int``): bar in which this trade was closed
        # trade是在那一根bar结束的
      - ``dtclose`` (``float``): float coded datetime in which the trade was
        closed
        - Use method ``close_datetime`` to get a Python datetime.datetime
          or use the platform provided ``num2date`` method
        # 记录trade是在什么时间关闭的，可以使用close_datetime或者num2date获取python格式的时间
      - ``barlen`` (``int``): number of bars this trade was open
        # trade开仓的时候bar的数量
      - ``historyon`` (``bool``): whether history has to be recorded
        # 是否记录历史的trade更新事件
      - ``history`` (``list``): holds a list updated with each "update" event
        containing the resulting status and parameters used in the update
        The first entry in the history is the Opening Event
        The last entry in the history is the Closing Event
        # 用一个列表保存过去每个trade的事件及状态，第一个是开仓事件，最后一个是平仓事件

    '''
    # trade的计数器
    refbasis = itertools.count(1)
    # trade的状态名字
    status_names = ['Created', 'Open', 'Closed']
    Created, Open, Closed = range(3)
    # 打印trade相关的信息
    def __str__(self):
        toprint = (
            'ref', 'data', 'tradeid',
            'size', 'price', 'value', 'commission', 'pnl', 'pnlcomm',
            'justopened', 'isopen', 'isclosed',
            'baropen', 'dtopen', 'barclose', 'dtclose', 'barlen',
            'historyon', 'history',
            'status')

        return '\n'.join(
            (':'.join((x, str(getattr(self, x)))) for x in toprint)
        )
    # 初始化
    def __init__(self, data=None, tradeid=0, historyon=False,
                 size=0, price=0.0, value=0.0, commission=0.0):

        self.ref = next(self.refbasis)
        self.data = data
        self.tradeid = tradeid
        self.size = size
        self.price = price
        self.value = value
        self.commission = commission

        self.pnl = 0.0
        self.pnlcomm = 0.0

        self.justopened = False
        self.isopen = False
        self.isclosed = False

        self.baropen = 0
        self.dtopen = 0.0
        self.barclose = 0
        self.dtclose = 0.0
        self.barlen = 0

        self.historyon = historyon
        self.history = list()

        self.status = self.Created
    # 返回交易的绝对大小,todo 感觉这个用法稍微有一些奇怪
    def __len__(self):
        '''Absolute size of the trade'''
        return abs(self.size)
    # 判断交易是否为0,trade的size是0的时候，代表trade是close的，如果不为0，代表trade是开着的
    def __bool__(self):
        '''Trade size is not 0'''
        return self.size != 0

    __nonzero__ = __bool__

    # 返回数据的名称
    def getdataname(self):
        '''Shortcut to retrieve the name of the data this trade references'''
        return self.data._name
    # 返回开仓时间
    def open_datetime(self, tz=None, naive=True):
        '''Returns a datetime.datetime object with the datetime in which
        the trade was opened
        '''
        # data中存在这个num2date的方法
        return self.data.num2date(self.dtopen, tz=tz, naive=naive)

    # 返回平仓的时间
    def close_datetime(self, tz=None, naive=True):
        '''Returns a datetime.datetime object with the datetime in which
        the trade was closed
        '''
        return self.data.num2date(self.dtclose, tz=tz, naive=naive)

    # 更新trade的事件
    def update(self, order, size, price, value, commission, pnl,
               comminfo):
        '''
        Updates the current trade. The logic does not check if the
        trade is reversed, which is not conceptually supported by the
        object.

        If an update sets the size attribute to 0, "closed" will be
        set to true

        Updates may be received twice for each order, once for the existing
        size which has been closed (sell undoing a buy) and a second time for
        the the opening part (sell reversing a buy)
        # 更新当前的trade.逻辑上并没有检查trade是否反转，这个是从概念上就不支持
        Args:
            order: the order object which has (completely or partially)
                generated this updatede
            # 导致trade更新的order
            size (int): amount to update the order
                if size has the same sign as the current trade a
                position increase will happen
                if size has the opposite sign as current op size a
                reduction/close will happen
            # 更新trade的size，如果size的符号和当前trade的一致，仓位会增加；如果和当前trade不一致，会导致仓位减少或者平仓
            price (float): always be positive to ensure consistency
            # 价格，总是正的以确保连续性 todo 不知道是负数的时候会产生什么样的结果
            value (float): (unused) cost incurred in new size/price op
                           Not used because the value is calculated for the
                           trade
            # 市值，并没有使用，因为value是通过trade计算出来的
            commission (float): incurred commission in the new size/price op
            # 新的交易产生的佣金
            pnl (float): (unused) generated by the executed part
                         Not used because the trade has an independent pnl
            # 执行部分产生的盈亏，没有是用，因为trade有独立的盈亏
        '''
        # 如果更新的size是0的话，直接返回
        if not size:
            return  # empty update, skip all other calculations

        # Commission can only increase
        # 佣金不断增加
        self.commission += commission

        # Update size and keep a reference for logic an calculations
        # 更新trade的大小
        oldsize = self.size
        self.size += size  # size will carry the opposite sign if reducing

        # Check if it has been currently opened
        # 如果原先仓位是0,但是当前仓位不是0,这代表仓位刚开
        self.justopened = bool(not oldsize and size)
        # 如果是仓位刚开，那么就更新baropen,dtopen和long
        if self.justopened:
            self.baropen = len(self.data)
            self.dtopen = 0.0 if order.p.simulated else self.data.datetime[0]
            self.long = self.size > 0

        # Any size means the trade was opened
        # 判断当前trade是否是open的
        self.isopen = bool(self.size)

        # Update current trade length
        # 更新当前trade的持仓bar数目
        self.barlen = len(self.data) - self.baropen

        # record if the position was closed (set to null)
        # 如果原先仓位不为0,但是当前仓位是0,代表trade已经平仓
        self.isclosed = bool(oldsize and not self.size)

        # record last bar for the trade
        # 如果已经平仓，更新isopen,barclose,dtclose,status属性
        if self.isclosed:
            self.isopen = False
            self.barclose = len(self.data)
            self.dtclose = self.data.datetime[0]

            self.status = self.Closed
        # 如果当前是开仓，更新status
        elif self.isopen:
            self.status = self.Open
        # 如果是加仓
        if abs(self.size) > abs(oldsize):
            # position increased (be it positive or negative)
            # update the average price
            self.price = (oldsize * self.price + size * price) / self.size
            pnl = 0.0
        # 如果是平仓一部分
        else:  # abs(self.size) < abs(oldsize)
            # position reduced/closed
            # 计算盈亏
            pnl = comminfo.profitandloss(-size, self.price, price)
        # trade的盈亏
        self.pnl += pnl
        # trade的净盈亏
        self.pnlcomm = self.pnl - self.commission
        # 更新trade的value
        self.value = comminfo.getvaluesize(self.size, self.price)

        # Update the history if needed
        # 如果需要，就增加trade的历史状态，保存到self.history中
        if self.historyon:
            dt0 = self.data.datetime[0] if not order.p.simulated else 0.0
            histentry = TradeHistory(
                self.status, dt0, self.barlen,
                self.size, self.price, self.value,
                self.pnl, self.pnlcomm, self.data._tz)
            histentry.doupdate(order, size, price, commission)
            self.history.append(histentry)
