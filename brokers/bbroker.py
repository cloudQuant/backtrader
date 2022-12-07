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
import datetime

import backtrader as bt
# from backtrader.comminfo import CommInfoBase
from backtrader.order import Order, BuyOrder, SellOrder
from backtrader.position import Position
from backtrader.utils.py3 import string_types, integer_types

__all__ = ['BackBroker', 'BrokerBack']


# 这个是回测的时候使用的类
class BackBroker(bt.BrokerBase):
    """Broker Simulator

      The simulation supports different order types, checking a submitted order
      cash requirements against current cash, keeping track of cash and value
      for each iteration of ``cerebro`` and keeping the current position on
      different datas.

      *cash* is adjusted on each iteration for instruments like ``futures`` for
       which a price change implies in real brokers the addition/subtraction of
       cash.
        # 这个回测模拟类支持不同的订单类型，检查现在的现金是否满足提交订单的现金需求，在每个bar的时候
        # 检查cash和value,以及不同的数据上的持仓

      Supported order types:

        - ``Market``: to be executed with the 1st tick of the next bar (namely
          the ``open`` price)

        - ``Close``: meant for intraday in which the order is executed with the
          closing price of the last bar of the session

        - ``Limit``: executes if the given limit price is seen during the
          session

        - ``Stop``: executes a ``Market`` order if the given stop price is seen

        - ``StopLimit``: sets a ``Limit`` order in motion if the given stop
          price is seen

        # 支持的订单类型有上面的五种基本的，实际上还是有其他的订单类型支持的，可以参考以前的教程
        # https://blog.csdn.net/qq_26948675/article/details/122868368

      Because the broker is instantiated by ``Cerebro`` and there should be
      (mostly) no reason to replace the broker, the params are not controlled
      by the user for the instance.  To change this there are two options:

        1. Manually create an instance of this class with the desired params
           and use ``cerebro.broker = instance`` to set the instance as the
           broker for the ``run`` execution

        2. Use the ``set_xxx`` to set the value using
           ``cerebro.broker.set_xxx`` where ```xxx`` stands for the name of the
           parameter to set

        .. note::

           ``cerebro.broker`` is a *property* supported by the ``getbroker``
           and ``setbroker`` methods of ``Cerebro``

        # 通常情况下不需要设置broker的参数，如果需要设置，通常具有下面的两种方法，第一种是创建一个broker的实例，然后cerebro.broker = instance
        # 第二种是使用cerebro.broker.set_xxx来设置不同的参数


      Params:
            # 下面是一些参数的意义

        - ``cash`` (default: ``10000``): starting cash
            # cash就是开始时候的资金有多少，默认是10000

        - ``commission`` (default: ``CommInfoBase(percabs=True)``)
          base commission scheme which applies to all assets
            # 佣金类，对于资产交易怎么收取佣金、保证金等设置，默认是CommInfoBase(percabs=True)

        - ``checksubmit`` (default: ``True``)
          check margin/cash before accepting an order into the system
          # 在把一个订单传递到系统中的时候是否检查保证金和资金是否满足，默认是需要检查

        - ``eosbar`` (default: ``False``):
          With intraday bars consider a bar with the same ``time`` as the end
          of session to be the end of the session. This is not usually the
          case, because some bars (final auction) are produced by many
          exchanges for many products for a couple of minutes after the end of
          the session
            # 交易结束bar,默认是False,在日内bar的时候，考虑一个具有和交易结束时间相同时间的bar作为一天交易的结束。
            # 但是通常情况下不是这样，这是因为很多资产的bar是在当天交易时间结束之后的一些分钟之后在很多交易所通过最终拍卖形成的

        - ``filler`` (default: ``None``)

          A callable with signature: ``callable(order, price, ago)``

            - ``order``: obviously the order in execution. This provides access
              to the *data* (and with it the *ohlc* and *volume* values), the
              *execution type*, remaining size (``order.executed.remsize``) and
              others.

              Please check the ``Order`` documentation and reference for things
              available inside an ``Order`` instance

            - ``price`` the price at which the order is going to be executed in
              the ``ago`` bar

            - ``ago``: index meant to be used with ``order.data`` for the
              extraction of the *ohlc* and *volume* prices. In most cases this
              will be ``0`` but on a corner case for ``Close`` orders, this
              will be ``-1``.

              In order to get the bar volume (for example) do: ``volume =
              order.data.voluume[ago]``

          The callable must return the *executed size* (a value >= 0)

          The callable may of course be an object with ``__call__`` matching
          the aforementioned signature

          With the default ``None`` orders will be completely executed in a
          single shot

          # filler事一个可调用对象，默认是None,在这种情况下，所有的交易量都可以执行；如果filler不是None的话，
          # 会根据order,price,ago具体计算出可以下单的量
          # 参考文章：https://blog.csdn.net/qq_26948675/article/details/124566885?spm=1001.2014.3001.5501
          # https://yunjinqi.blog.csdn.net/article/details/113445040


        - ``slip_perc`` (default: ``0.0``) Percentage in absolute terms (and
          positive) that should be used to slip prices up/down for buy/sell
          orders

          Note:

            - ``0.01`` is ``1%``

            - ``0.001`` is ``0.1%``
            # 百分比滑点形式

        - ``slip_fixed`` (default: ``0.0``) Percentage in units (and positive)
          that should be used to slip prices up/down for buy/sell orders

          Note: if ``slip_perc`` is non zero, it takes precedence over this.

            # 固定滑点形式，如果百分比滑点不是0的话，只考虑百分比滑点

        - ``slip_open`` (default: ``False``) whether to slip prices for order
          execution which would specifically used the *opening* price of the
          next bar. An example would be ``Market`` order which is executed with
          the next available tick, i.e: the opening price of the bar.

          This also applies to some of the other executions, because the logic
          tries to detect if the *opening* price would match the requested
          price/execution type when moving to a new bar.
            # 计算滑点的时候，是否使用下个bar的开盘价

        - ``slip_match`` (default: ``True``)

          If ``True`` the broker will offer a match by capping slippage at
          ``high/low`` prices in case they would be exceeded.

          If ``False`` the broker will not match the order with the current
          prices and will try execution during the next iteration
            # 如果加上滑点的价格超过了最高价和最低价，如果slip_match设置成True的话，成交价将会按照最高价或者最低价计算
            # 如果没有设置成True,将会等待下个bar去尝试成交

        - ``slip_limit`` (default: ``True``)

          ``Limit`` orders, given the exact match price requested, will be
          matched even if ``slip_match`` is ``False``.

          This option controls that behavior.

          If ``True``, then ``Limit`` orders will be matched by capping prices
          to the ``limit`` / ``high/low`` prices

          If ``False`` and slippage exceeds the cap, then there will be no
          match
            # 限价单将会寻求严格的匹配，即使slip_match是False的时候
            # slip_limit设置成True的话，限价单如果在最高价和最低价之间，将会成交
            # 如果设置成False,限价单加上滑点超过了最高价和最低价，将不会成交

        - ``slip_out`` (default: ``False``)

          Provide *slippage* even if the price falls outside the ``high`` -
          ``low`` range.
            # 当slip_out设置成True的时候，即使价格超过了最高价和最低价的范围，也会提供滑点

        - ``coc`` (default: ``False``)

          *Cheat-On-Close* Setting this to ``True`` with ``set_coc`` enables
           matching a ``Market`` order to the closing price of the bar in which
           the order was issued. This is actually *cheating*, because the bar
           is *closed* and any order should first be matched against the prices
           in the next bar
            # coc设置成True的时候，在下市价单的时候，允许在收盘价成交
        - ``coo`` (default: ``False``)

          *Cheat-On-Open* Setting this to ``True`` with ``set_coo`` enables
           matching a ``Market`` order to the opening price, by for example
           using a timer with ``cheat`` set to ``True``, because such a timer
           gets executed before the broker has evaluated
            # coo设置成True的时候，允许市价单按照开盘价成交，类似于tbquant的模式

        - ``int2pnl`` (default: ``True``)

          Assign generated interest (if any) to the profit and loss of
          operation that reduces a position (be it long or short). There may be
          cases in which this is undesired, because different strategies are
          competing and the interest would be assigned on a non-deterministic
          basis to any of them.
          # int2pnl，默认是True. todo 按照字面意思理解是把产生的利息费用转嫁到pnl上

        - ``shortcash`` (default: ``True``)

          If True then cash will be increased when a stocklike asset is shorted
          and the calculated value for the asset will be negative.

          If ``False`` then the cash will be deducted as operation cost and the
          calculated value will be positive to end up with the same amount

          # 对于股票类资产，如果这个参数设置是True的话，那么当卖空的时候，将会导致可用的资金是增加的，但是这个资产的价值将是负的
          # 如果这个参数设置的是False的话，那么在卖空的时候，可用资金是减少的，资产的价值是正的

        - ``fundstartval`` (default: ``100.0``)

          This parameter controls the start value for measuring the performance
          in a fund-like way, i.e.: cash can be added and deducted increasing
          the amount of shares. Performance is not measured using the net
          asset value of the portfolio but using the value of the fund
          # fundstartval，将会按照fund的模式计算绩效

        - ``fundmode`` (default: ``False``)

          If this is set to ``True`` analyzers like ``TimeReturn`` can
          automatically calculate returns based on the fund value and not on
          the total net asset value
          # 如果fundmode设置成True的话，一些analyzers，比如TimeReturn将会使用fund value计算收益

    """
    # 参数
    params = (
        ('cash', 10000.0),
        ('checksubmit', True),
        ('eosbar', False),
        ('filler', None),
        # slippage options
        ('slip_perc', 0.0),
        ('slip_fixed', 0.0),
        ('slip_open', False),
        ('slip_match', True),
        ('slip_limit', True),
        ('slip_out', False),
        ('coc', False),
        ('coo', False),
        ('int2pnl', True),
        ('shortcash', True),
        ('fundstartval', 100.0),
        ('fundmode', False),
    )

    # 创建实例的时候初始化
    def __init__(self):
        super(BackBroker, self).__init__()
        # 用于保存order历史记录
        self._userhist = []
        # 用于保存fund历史记录
        self._fundhist = []
        # share_value, net asset value
        # 用于保存fund的份额和净资产价值
        self._fhistlast = [float('NaN'), float('NaN')]

    # 初始化函数
    def init(self):
        super(BackBroker, self).init()
        # 开始的时候的初始现金
        self.startingcash = self.cash = self.p.cash
        # 未加杠杆的账户价值
        self._value = self.cash
        # 未加杠杆的持仓价值
        self._valuemkt = 0.0  # no open position
        # 加了杠杆的账户价值
        self._valuelever = 0.0  # no open position
        # 加了杠杆的持仓市值
        self._valuemktlever = 0.0  # no open position
        # 杠杆
        self._leverage = 1.0  # initially nothing is open
        # 未实现盈利
        self._unrealized = 0.0  # no open position
        # 订单
        self.orders = list()  # will only be appending
        # 双向队列
        self.pending = collections.deque()  # popleft and append(right)
        self._toactivate = collections.deque()  # to activate in next cycle
        # 持仓
        self.positions = collections.defaultdict(Position)
        # 利息率
        self.d_credit = collections.defaultdict(float)  # credit per data
        # 通知信息的双向队列
        self.notifs = collections.deque()
        # 提交的双向队列
        self.submitted = collections.deque()

        # to keep dependent orders if needed
        # 如果需要保持独立的订单
        self._pchildren = collections.defaultdict(collections.deque)
        # ocos
        self._ocos = dict()
        # ocol
        self._ocol = collections.defaultdict(list)
        # fund value
        self._fundval = self.p.fundstartval
        # fund shares
        self._fundshares = self.p.cash / self._fundval
        # 现金增加
        self._cash_addition = collections.deque()

    # 获取通知信息
    def get_notification(self):
        try:
            return self.notifs.popleft()
        except IndexError:
            pass

        return None

    # 设置fund模式
    def set_fundmode(self, fundmode, fundstartval=None):
        """Set the actual fundmode (True or False)

        If the argument fundstartval is not ``None``, it will use
        """
        self.p.fundmode = fundmode
        if fundstartval is not None:
            self.set_fundstartval(fundstartval)

    # 获取fundmode
    def get_fundmode(self):
        # Returns the actual fundmode (True or False)
        return self.p.fundmode
    # 把fundmode变成属性
    fundmode = property(get_fundmode, set_fundmode)

    # 设置fund的开始价值
    def set_fundstartval(self, fundstartval):
        # Set the starting value of the fund-like performance tracker
        self.p.fundstartval = fundstartval

    # 把利息费用转移到pnl
    def set_int2pnl(self, int2pnl):
        # Configure assignment of interest to profit and loss
        self.p.int2pnl = int2pnl

    # 设置Cheat-On-Close
    def set_coc(self, coc):
        # Configure the Cheat-On-Close method to buy the close on order bar
        self.p.coc = coc

    # 设置Cheat-On-Open
    def set_coo(self, coo):
        # Configure the Cheat-On-Open method to buy the close on order bar
        self.p.coo = coo

    # 设置shortcash参数
    def set_shortcash(self, shortcash):
        # Configure the shortcash parameters
        self.p.shortcash = shortcash

    # 设置百分比滑点相关的信息
    def set_slippage_perc(self, perc,
                          slip_open=True, slip_limit=True,
                          slip_match=True, slip_out=False):
        # Configure slippage to be percentage based
        self.p.slip_perc = perc
        self.p.slip_fixed = 0.0
        self.p.slip_open = slip_open
        self.p.slip_limit = slip_limit
        self.p.slip_match = slip_match
        self.p.slip_out = slip_out

    # 设置固定滑点相关的信息
    def set_slippage_fixed(self, fixed,
                           slip_open=True, slip_limit=True,
                           slip_match=True, slip_out=False):
        # Configure slippage to be fixed points based
        self.p.slip_perc = 0.0
        self.p.slip_fixed = fixed
        self.p.slip_open = slip_open
        self.p.slip_limit = slip_limit
        self.p.slip_match = slip_match
        self.p.slip_out = slip_out

    # 设置根据成交量限制决定订单成交大小的可调用对象
    def set_filler(self, filler):
        # Sets a volume filler for volume filling execution
        self.p.filler = filler

    # 设置checksubmit参数
    def set_checksubmit(self, checksubmit):
        # Sets the checksubmit parameter
        self.p.checksubmit = checksubmit

    # 设置eosbar参数
    def set_eosbar(self, eosbar):
        # Sets the eosbar parameter (alias: ``seteosbar``
        self.p.eosbar = eosbar

    seteosbar = set_eosbar

    # 获取现金
    def get_cash(self):
        # Returns the current cash (alias: ``getcash``)
        return self.cash

    getcash = get_cash

    # 设置现金
    def set_cash(self, cash):
        # Sets the cash parameter (alias: ``setcash``)
        self.startingcash = self.cash = self.p.cash = cash
        self._value = cash

    setcash = set_cash

    # 增加现金
    def add_cash(self, cash):
        # Add/Remove cash to the system (use a negative value to remove)
        self._cash_addition.append(cash)

    # 获取基金份额
    def get_fundshares(self):
        # Returns the current number of shares in the fund-like mode
        return self._fundshares

    fundshares = property(get_fundshares)

    # 获取基金价值
    def get_fundvalue(self):
        # Returns the Fund-like share value
        return self._fundval

    fundvalue = property(get_fundvalue)

    # 取消订单
    def cancel(self, order, bracket=False):
        try:
            self.pending.remove(order)
        except ValueError:
            # If the list didn't have the element we didn't cancel anything
            return False

        order.cancel()
        self.notify(order)
        self._ococheck(order)
        if not bracket:
            self._bracketize(order, cancel=True)
        return True

    # 获取价值，如果没有指定data,就获取的是整个账户的价值
    def get_value(self, datas=None, mkt=False, lever=False):
        """Returns the portfolio value of the given datas (if datas is ``None``, then
        the total portfolio value will be returned (alias: ``getvalue``)
        """
        if datas is None:
            if mkt:
                return self._valuemkt if not lever else self._valuemktlever

            return self._value if not lever else self._valuelever

        return self._get_value(datas=datas, lever=lever)

    getvalue = get_value

    # todo 这个函数只在这里声明了，在其他地方都没有使用，无用函数,注释掉
    # def get_value_lever(self, datas=None, mkt=False):
    #     return self.get_value(datas=datas, mkt=mkt)

    # 获取账户价值
    def _get_value(self, datas=None, lever=False):
        # 持仓价值
        pos_value = 0.0
        # 未加杠杆的持仓价值
        pos_value_unlever = 0.0
        # 未实现的利润
        unrealized = 0.0

        # 如果增加了现金，把现金增加到self.cash中
        while self._cash_addition:
            c = self._cash_addition.popleft()
            self._fundshares += c / self._fundval
            self.cash += c

        # 如果datas是None的话，循环self.positions，如果datas不是None的话，循环datas
        for data in datas or self.positions:
            # 获取佣金相关信息
            comminfo = self.getcommissioninfo(data)
            # 获取data的持仓
            position = self.positions[data]
            # use valuesize:  returns raw value, rather than negative adj val
            # 如果shortcash是False的话，用comminfo.getvalue获取data的value
            # 如果shortcash是True的话，用comminfo.getvaluesize获取data的value
            if not self.p.shortcash:
                dvalue = comminfo.getvalue(position, data.close[0])
            else:
                dvalue = comminfo.getvaluesize(position.size, data.close[0])
            # 获取data未实现的利润
            dunrealized = comminfo.profitandloss(position.size, position.price,
                                                 data.close[0])
            # 如果datas不是None,并且datas是一个列表，里面有一个data
            if datas and len(datas) == 1:
                # 如果lever是True,并且dvalue大于0,计算初始的dvalue值，然后除以杠杆，加上未实现的利润，就是data的value
                if lever and dvalue > 0:
                    dvalue -= dunrealized
                    return (dvalue / comminfo.get_leverage()) + dunrealized
                # 如果lever是False或者因为shortcash导致dvalue<0,返回dvalue
                return dvalue  # raw data value requested, short selling is neg
            # 如果shortcash是False的话
            if not self.p.shortcash:
                dvalue = abs(dvalue)  # short selling adds value in this case
            # 持仓价值等于持仓价值加上数据的价值
            pos_value += dvalue
            # 未实现的利润等于未实现的利润加上数据未实现的利润
            unrealized += dunrealized
            # 如果dvalue大于0的话，计算出未加杠杆的持仓价值
            if dvalue > 0:  # long position - unlever
                dvalue -= dunrealized
                # todo 为什么每次都需要重置pos_value_unlever
                pos_value_unlever += (dvalue / comminfo.get_leverage())
                pos_value_unlever += dunrealized
            else:
                pos_value_unlever += dvalue
        # 如果不是fundhist模式，计算_value，fundval
        if not self._fundhist:
            # todo 注释掉没有使用的v
            # self._value = v = self.cash + pos_value_unlever
            self._value = self.cash + pos_value_unlever
            self._fundval = self._value / self._fundshares  # update fundvalue
        # 如果是fundhist模式
        else:
            # Try to fetch a value
            # 调用函数_process_fund_history()，获取fval,fvalue
            fval, fvalue = self._process_fund_history()
            # _value等于fvalue
            self._value = fvalue
            # cash等于fvalue减去未加杠杆的持仓
            self.cash = fvalue - pos_value_unlever
            # _fundval = fval
            self._fundval = fval
            # _fund的份额
            self._fundshares = fvalue / fval
            # 杠杆的倍数
            lev = pos_value / (pos_value_unlever or 1.0)

            # update the calculated values above to the historical values
            # 未加杠杆的持仓价值
            pos_value_unlever = fvalue
            # 加了杠杆的持仓价值
            pos_value = fvalue * lev
        # 未加杠杆的持仓价值
        self._valuemkt = pos_value_unlever
        # 加了杠杆的账户价值
        self._valuelever = self.cash + pos_value
        # 加了杠杆的持仓价值
        self._valuemktlever = pos_value
        # 杠杆率
        self._leverage = pos_value / (pos_value_unlever or 1.0)
        # 未实现的利润
        self._unrealized = unrealized

        return self._value if not lever else self._valuelever

    # 获取杠杆
    def get_leverage(self):
        return self._leverage

    # 获取未成交的订单
    def get_orders_open(self, safe=False):
        """Returns an iterable with the orders which are still open (either not
        executed or partially executed)

        The orders returned must not be touched.

        If order manipulation is needed, set the parameter ``safe`` to True
        """
        if safe:
            os = [x.clone() for x in self.pending]
        else:
            os = [x for x in self.pending]

        return os

    # 获取data的持仓
    def getposition(self, data):
        """Returns the current position status (a ``Position`` instance) for
        the given ``data``"""
        return self.positions[data]

    # 获取order的状态
    def orderstatus(self, order):
        try:
            o = self.orders.index(order)
        except ValueError:
            o = order

        return o.status

    #
    def _take_children(self, order):
        # order的id
        oref = order.ref
        # 获取order的父订单的id，如果获取不到买,就是自身
        pref = getattr(order.parent, 'ref', oref)  # parent ref or self
        # 如果子订单id和父订单id不相等
        if oref != pref:
            # 如果父订单id也不在_pchildren中，将会拒单，并且返回None
            if pref not in self._pchildren:
                order.reject()  # parent not there - may have been rejected
                self.notify(order)  # reject child, notify
                return None
        # 如果两个相等，将会返回父订单id
        return pref

    # 提交订单
    def submit(self, order, check=True):
        # 获取order的父订单的id或者是自身的id,如果这个id是None,返回order本身
        pref = self._take_children(order)
        if pref is None:  # order has not been taken
            return order
        # pc是一个deque,保存parent和children订单
        pc = self._pchildren[pref]
        pc.append(order)  # store in parent/children queue
        # 如果order是transmit的话，对于pc中的订单，调用transmit函数，并返回最后一个order
        if order.transmit:  # if single order, sent and queue cleared
            # if parent-child, the parent will be sent, the other kept
            rets = [self.transmit(x, check=check) for x in pc]
            return rets[-1]  # last one is the one triggering transmission

        return order

    # transmit函数
    def transmit(self, order, check=True):
        # 如果check是True,并且checksubmit是True的话
        if check and self.p.checksubmit:
            # 订单submit
            order.submit()
            # 把订单追加到submitted中
            self.submitted.append(order)
            # 把订单追加到orders中
            self.orders.append(order)
            # 通知订单
            self.notify(order)
        # 如果check或者checksubmit中有一个是False的话，把order追加到submit_accept中
        else:
            self.submit_accept(order)
        # 返回order
        return order

    # 检查提交
    def check_submitted(self):
        # 当前可用资金
        cash = self.cash
        # 持仓
        positions = dict()
        # 当submitted不是空的话
        while self.submitted:
            # 删除最左边的order并获取到
            order = self.submitted.popleft()
            # 如果调用_take_children(order)的结果是None的话，这个订单会被拒绝，继续到下个订单
            if self._take_children(order) is None:  # children not taken
                continue
            # 获取佣金信息类
            # comminfo = self.getcommissioninfo(order.data)
            # todo 注释掉了没有使用的comminfo
            # 获取持仓
            position = positions.setdefault(
                order.data, self.positions[order.data].clone())
            # pseudo-execute the order to get the remaining cash after exec
            # 假设执行订单之后获取的现金
            cash = self._execute(order, cash=cash, position=position)
            # 如果剩余的现金大于0，调用submit_accept接受订单
            if cash >= 0.0:
                self.submit_accept(order)
                continue
            # 如果cash是小于0的话，保证金不足，通知order的状态，调用_ococheck和_bracketize
            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)

    # 接受这个订单
    def submit_accept(self, order):
        # todo 给order额外设置pannotated属性,暂时不知用处
        order.pannotated = None
        # 订单提交
        order.submit()
        # 订单接受
        order.accept()
        # 把订单添加到待成交订单里
        self.pending.append(order)
        # 通知订单状态
        self.notify(order)

    # 删除订单或者把订单活跃状态变成不活跃
    def _bracketize(self, order, cancel=False):
        # 订单id
        oref = order.ref
        # 父订单id或者自身id
        pref = getattr(order.parent, 'ref', oref)
        # 如果两个id相等，parent就是True
        parent = oref == pref
        # 获取订单的deque
        pc = self._pchildren[pref]  # defdict - guaranteed
        # 如果cancel是True或者parent不是True的话，
        if cancel or not parent:  # cancel left or child exec -> cancel other
            # 如果pc有订单，会一直运行，取消订单
            while pc:
                self.cancel(pc.popleft(), bracket=True)  # idempotent
            # 删除这个key,value
            del self._pchildren[pref]  # defdict guaranteed
        # 如果上面两个条件都不满足，即cancel是false,并且parent是True
        else:  # not cancel -> parent exec'd
            # 清空parent订单，然后把子订单的状态变为不激活
            pc.popleft()  # remove parent
            for o in pc:  # activate children
                self._toactivate.append(o)

    # oco订单的检查
    def _ococheck(self, order):
        # ocoref = self._ocos[order.ref] or order.ref  # a parent or self
        parentref = self._ocos[order.ref]
        ocoref = self._ocos.get(parentref, None)
        ocol = self._ocol.pop(ocoref, None)
        if ocol:
            for i in range(len(self.pending) - 1, -1, -1):
                o = self.pending[i]
                if o is not None and o.ref in ocol:
                    del self.pending[i]
                    o.cancel()
                    self.notify(o)

    # oco订单的操作
    def _ocoize(self, order, oco):
        oref = order.ref
        if oco is None:
            self._ocos[oref] = oref  # current order is parent
            self._ocol[oref].append(oref)  # create ocogroup
        else:
            ocoref = self._ocos[oco.ref]  # ref to group leader
            self._ocos[oref] = ocoref  # ref to group leader
            self._ocol[ocoref].append(oref)  # add to group

    # 增加订单历史
    def add_order_history(self, orders, notify=True):
        oiter = iter(orders)
        o = next(oiter, None)
        self._userhist.append([o, oiter, notify])

    # 设置fund历史信息
    def set_fund_history(self, fund):
        # iterable with the following pro item
        # [datetime, share_value, net asset value]
        fiter = iter(fund)
        f = list(next(fiter))  # must not be empty
        self._fundhist = [f, fiter]
        # self._fhistlast = f[1:]

        self.set_cash(float(f[2]))

    # 买操作
    def buy(self, owner, data,
            size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            parent=None, transmit=True,
            histnotify=False, _checksubmit=True,
            **kwargs):

        order = BuyOrder(owner=owner, data=data,
                         size=size, price=price, pricelimit=plimit,
                         exectype=exectype, valid=valid, tradeid=tradeid,
                         trailamount=trailamount, trailpercent=trailpercent,
                         parent=parent, transmit=transmit,
                         histnotify=histnotify)

        order.addinfo(**kwargs)
        self._ocoize(order, oco)

        return self.submit(order, check=_checksubmit)

    # 卖操作
    def sell(self, owner, data,
             size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             parent=None, transmit=True,
             histnotify=False, _checksubmit=True,
             **kwargs):

        order = SellOrder(owner=owner, data=data,
                          size=size, price=price, pricelimit=plimit,
                          exectype=exectype, valid=valid, tradeid=tradeid,
                          trailamount=trailamount, trailpercent=trailpercent,
                          parent=parent, transmit=transmit,
                          histnotify=histnotify)

        order.addinfo(**kwargs)
        self._ocoize(order, oco)

        return self.submit(order, check=_checksubmit)

    # 执行订单
    def _execute(self, order, ago=None, price=None, cash=None, position=None,
                 dtcoc=None):
        # ago = None is used a flag for pseudo execution
        # print(f"订单的大小:{order.executed.remsize}")
        # 如果ago不是None，并且price是None的话，不操作，返回
        if ago is not None and price is None:
            return  # no psuedo exec no price - no execution

        # 获取要执行的订单量
        if self.p.filler is None or ago is None:
            # Order gets full size or pseudo-execution
            size = order.executed.remsize
        else:
            # Execution depends on volume filler
            size = self.p.filler(order, price, ago)
            if not order.isbuy():
                size = -size

        # Get comminfo object for the data
        # 获取佣金信息类
        comminfo = self.getcommissioninfo(order.data)

        # Check if something has to be compensated
        # 如果data的_compensate不是None的话，就获取_compensate的佣金信息类，否则还用data的
        if order.data._compensate is not None:
            data = order.data._compensate
            cinfocomp = self.getcommissioninfo(data)  # for actual commission
        else:
            data = order.data
            cinfocomp = comminfo

        # Adjust position with operation size
        # 如果ago不是None的话，就获取持仓，持仓平均价格，更新持仓相关信息，以及计算的pnl和cash
        if ago is not None:
            # Real execution with date
            position = self.positions[data]
            pprice_orig = position.price

            psize, pprice, opened, closed = position.pseudoupdate(size, price)

            # if part/all of a position has been closed, then there has been
            # a profitandloss ... record it
            pnl = comminfo.profitandloss(-closed, pprice_orig, price)
            cash = self.cash
        # 如果ago是None的话
        else:
            # pnl = 0
            pnl = 0
            # 如果cheat_on_open=False的话
            if not self.p.coo:
                # 价格
                price = pprice_orig = order.created.price
            # 如果cheat_on_open = True 的话
            else:
                # When doing cheat on open, the price to be considered for a
                # market order is the opening price and not the default closing
                # price with which the order was created
                # 如果是市价单的话，价格等于当天的开盘价，否则就等于创建的价格
                if order.exectype == Order.Market:
                    price = pprice_orig = order.data.open[0]
                else:
                    price = pprice_orig = order.created.price
            # 更新position的size和price
            psize, pprice, opened, closed = position.update(size, price)

        # "Closing" totally or partially is possible. Cash may be re-injected
        # 如果是closed
        if closed:
            # Adjust to returned value for closed items & acquired opened items
            # 如果shortcash是True的话，平仓的价值用comminfo.getvaluesize计算得到，
            # 如果shortcash是False的话，用comminfo.getoperationcost计算得到平仓的价值
            if self.p.shortcash:
                closedvalue = comminfo.getvaluesize(-closed, pprice_orig)
            else:
                closedvalue = comminfo.getoperationcost(closed, pprice_orig)

            # 如果closedvalue>0的话，计算调整杠杆之后的closecash
            closecash = closedvalue
            if closedvalue > 0:  # long position closed
                closecash /= comminfo.get_leverage()  # inc cash with lever
            # 如果是stocklike，cash等于cash加上closecash加上pnl
            # 如果stocklike是False的话，cash等于cash+closecash
            cash += closecash + pnl * comminfo.stocklike
            # Calculate and substract commission
            # 关闭仓位的时候的佣金
            closedcomm = comminfo.getcommission(closed, price)
            # 现金等于现金减去平仓的佣金
            cash -= closedcomm
            # 如果ago不是None的话
            if ago is not None:
                # Cashadjust closed contracts: prev close vs exec price
                # The operation can inject or take cash out
                # 调整现金，并更新
                cash += comminfo.cashadjust(-closed,
                                            position.adjbase,
                                            price)

                # Update system cash
                self.cash = cash
        # 如果不是closed的话
        else:
            closedvalue = closedcomm = 0.0

        # 如果是opened
        popened = opened
        if opened:
            # 计算开仓的价值
            if self.p.shortcash:
                # print(f"opened:{opened},price:{price}")
                openedvalue = comminfo.getvaluesize(opened, price)
            else:
                openedvalue = comminfo.getoperationcost(opened, price)

            # 计算开仓使用的现金
            opencash = openedvalue
            if openedvalue > 0:  # long position being opened
                opencash /= comminfo.get_leverage()  # dec cash with level
            # print(f"openedvalue:{openedvalue},opencash:{opencash},cash:{cash}")
            # 减去开仓后得到的现金
            cash -= opencash  # original behavior
            # 开仓的佣金
            openedcomm = cinfocomp.getcommission(opened, price)
            # 减去开仓佣金后得到的现金
            cash -= openedcomm
            # 如果现金小于0，不可能开仓
            if cash < 0.0:
                # execution is not possible - nullify
                opened = 0
                openedvalue = openedcomm = 0.0

            # 如果ago不是None
            elif ago is not None:  # real execution
                # 如果持仓的绝对值大小大于开仓的绝对值大小
                if abs(psize) > abs(opened):
                    # some futures were opened - adjust the cash of the
                    # previously existing futures to the operation price and
                    # use that as new adjustment base, because it already is
                    # for the new futures At the end of the cycle the
                    # adjustment to the close price will be done for all open
                    # futures from a common base price with regard to the
                    # close price
                    # 需要调整的size
                    adjsize = psize - opened
                    # 调整现金
                    cash += comminfo.cashadjust(adjsize,
                                                position.adjbase, price)

                # record adjust price base for end of bar cash adjustment
                # 更新position的adjbase价格
                position.adjbase = price

                # update system cash - checking if opened is still != 0
                self.cash = cash
        # 如果opened是False的话
        else:
            openedvalue = openedcomm = 0.0

        # 如果ago等于None的话，返回cash
        if ago is None:
            # return cash from pseudo-execution
            return cash
        # 执行订单的大小
        execsize = closed + opened
        # 如果执行订单的大小大于0
        if execsize:
            # Confimrm the operation to the comminfo object
            # todo 确认需要的佣金，这个都没有变量接受返回值,似乎没什么用处
            comminfo.confirmexec(execsize, price)

            # do a real position update if something was executed
            # 更新position
            position.update(execsize, price, data.datetime.datetime())
            # 如果是closed并且把利息转成pnl的话，平仓的时候佣金要加上利息费用
            if closed and self.p.int2pnl:  # Assign accumulated interest data
                closedcomm += self.d_credit.pop(data, 0.0)

            # Execute and notify the order
            # 执行订单并通知订单
            order.execute(dtcoc or data.datetime[ago],
                          execsize, price,
                          closed, closedvalue, closedcomm,
                          opened, openedvalue, openedcomm,
                          comminfo.margin, pnl,
                          psize, pprice)

            order.addcomminfo(comminfo)

            self.notify(order)
            self._ococheck(order)

        # 如果开仓了但是因为现金不够，会提示margin
        if popened and not opened:
            # opened was not executed - not enough cash
            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)

    # 通知订单信息
    def notify(self, order):
        self.notifs.append(order.clone())

    # 尝试执行历史
    def _try_exec_historical(self, order):
        self._execute(order, ago=0, price=order.created.price)

    # 尝试执行市价单
    def _try_exec_market(self, order, popen, phigh, plow):
        # ago = 0
        # todo 注释掉了没有使用的ago
        # 如果cheat_on_close是True，或者order里面cheat_on_open是True的话
        if self.p.coc and order.info.get('coc', True):
            # 订单创建时间
            dtcoc = order.created.dt
            # 执行价格
            exprice = order.created.pclose
        # 如果coc不是True的话
        else:
            # 如果当前不是cheat_on_open，如果数据的时间小于等于创建时间，直接返回，不执行
            if not self.p.coo and order.data.datetime[0] <= order.created.dt:
                return    # can only execute after creation time
            # dtcoc设置成None
            dtcoc = None
            # 执行价格等于popen
            exprice = popen
        # 如果是买单和卖单，分别得到考虑滑点之后的价格
        if order.isbuy():
            p = self._slip_up(phigh, exprice, doslip=self.p.slip_open)
        else:
            p = self._slip_down(plow, exprice, doslip=self.p.slip_open)
        # 执行订单
        self._execute(order, ago=0, price=p, dtcoc=dtcoc)

    # 尝试执行收盘价订单
    def _try_exec_close(self, order, pclose):
        # pannotated allows to keep track of the closing bar if there is no
        # information which lets us know that the current bar is the closing
        # bar (like matching end of session bar)
        # The actual matching will be done one bar afterwards but using the
        # information from the actual closing bar
        # 获取当前的时间
        dt0 = order.data.datetime[0]
        # don't use "len" -> in replay the close can be reached with same len
        # 如果当前时间大于订单创建时间
        if dt0 > order.created.dt:  # can only execute after creation time
            # or (self.p.eosbar and dt0 == order.dteos):
            # 如果当前时间大于等于订单的一天结束的时间
            if dt0 >= order.dteos:
                # past the end of session or right at it and eosbar is True
                # 如果order.pannotated是一个价格，并且dt0大于了一天结束时间，ago设置成-1，执行价格等于前一个收盘价
                if order.pannotated and dt0 > order.dteos:
                    ago = -1
                    execprice = order.pannotated
                # 否则，ago就等于0，执行价格就等于pclose
                else:
                    ago = 0
                    execprice = pclose
                # 执行订单
                self._execute(order, ago=ago, price=execprice)
                return

        # If no execution has taken place ... annotate the closing price
        # 如果dt0小于等于订单创建时间，更新order的pannotated为价格
        order.pannotated = pclose

    # 尝试执行限价单
    def _try_exec_limit(self, order, popen, phigh, plow, plimit):
        # 如果是买订单
        if order.isbuy():
            # 如果plimit大于等于popen
            if plimit >= popen:
                # open smaller/equal than requested - buy cheaper
                # 计算pmax
                pmax = min(phigh, plimit)
                # 计算算上滑点之后的价格
                p = self._slip_up(pmax, popen, doslip=self.p.slip_open, lim=True)
                # 执行订单
                self._execute(order, ago=0, price=p)
            # 如果plimit大于等于plow,执行订单
            elif plimit >= plow:
                # day low below req price ... match limit price
                self._execute(order, ago=0, price=plimit)
        # 如果是卖单
        else:  # Sell
            # plimit小于等于popen
            if plimit <= popen:
                # open greater/equal than requested - sell more expensive
                # 计算pmin
                # todo 注释掉了没有使用的pmin
                # pmin = max(plow, plimit)
                # 计算算上滑点之后的价格
                p = self._slip_down(plimit, popen, doslip=self.p.slip_open,
                                    lim=True)
                # 执行订单
                self._execute(order, ago=0, price=p)
            # plimit小于等于最高价，执行订单
            elif plimit <= phigh:
                # day high above req price ... match limit price
                self._execute(order, ago=0, price=plimit)

    # 尝试执行止损价
    def _try_exec_stop(self, order, popen, phigh, plow, pcreated, pclose):
        # 买单
        if order.isbuy():
            #  popen大于等于pcreated
            if popen >= pcreated:
                # price penetrated with an open gap - use open
                # 计算考虑过滑点的价格
                p = self._slip_up(phigh, popen, doslip=self.p.slip_open)
                # 执行订单
                self._execute(order, ago=0, price=p)
            # 如果phigh小于等于pcreated
            elif phigh >= pcreated:
                # price penetrated during the session - use trigger price
                # 计算考虑过滑点的价格
                p = self._slip_up(phigh, pcreated)
                # 执行订单
                self._execute(order, ago=0, price=p)
        # 卖单
        else:  # Sell
            # 如果popen小于pcreated
            if popen <= pcreated:
                # price penetrated with an open gap - use open
                # 计算考虑过滑点的价格
                p = self._slip_down(plow, popen, doslip=self.p.slip_open)
                # 执行订单
                self._execute(order, ago=0, price=p)
            # 如果plow小于等于pcreated
            elif plow <= pcreated:
                # price penetrated during the session - use trigger price
                # 计算考虑过滑点的价格
                p = self._slip_down(plow, pcreated)
                # 执行订单
                self._execute(order, ago=0, price=p)

        # not (completely) executed and trailing stop
        #  如果订单是活的，并且订单类型是StopTrail,根据pclose调整价格
        if order.alive() and order.exectype == Order.StopTrail:
            order.trailadjust(pclose)

    # 尝试执行止损限价单
    def _try_exec_stoplimit(self, order,
                            popen, phigh, plow, pclose,
                            pcreated, plimit):

        # 和止损单比较类似，只是止损单触发止损的时候下的是市价单，这个下的是限价单
        if order.isbuy():
            if popen >= pcreated:
                order.triggered = True
                self._try_exec_limit(order, popen, phigh, plow, plimit)

            elif phigh >= pcreated:
                # price penetrated upwards during the session
                order.triggered = True
                # can calculate execution for a few cases - datetime is fixed
                if popen > pclose:
                    if plimit >= pcreated:  # limit above stop trigger
                        p = self._slip_up(phigh, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)
                    elif plimit >= pclose:
                        self._execute(order, ago=0, price=plimit)
                else:  # popen < pclose
                    if plimit >= pcreated:
                        p = self._slip_up(phigh, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)
        else:  # Sell
            if popen <= pcreated:
                # price penetrated downwards with an open gap
                order.triggered = True
                self._try_exec_limit(order, popen, phigh, plow, plimit)

            elif plow <= pcreated:
                # price penetrated downwards during the session
                order.triggered = True
                # can calculate execution for a few cases - datetime is fixed
                if popen <= pclose:
                    if plimit <= pcreated:
                        p = self._slip_down(plow, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)
                    elif plimit <= pclose:
                        self._execute(order, ago=0, price=plimit)
                else:
                    # popen > pclose
                    if plimit <= pcreated:
                        p = self._slip_down(plow, pcreated, lim=True)
                        self._execute(order, ago=0, price=p)

        # not (completely) executed and trailing stop
        if order.alive() and order.exectype == Order.StopTrailLimit:
            order.trailadjust(pclose)

    # 向上增加滑点
    def _slip_up(self, pmax, price, doslip=True, lim=False):
        if not doslip:
            return price

        slip_perc = self.p.slip_perc
        slip_fixed = self.p.slip_fixed
        if slip_perc:
            pslip = price * (1 + slip_perc)
        elif slip_fixed:
            pslip = price + slip_fixed
        else:
            return price

        if pslip <= pmax:  # slipping can return price
            return pslip
        elif self.p.slip_match or (lim and self.p.slip_limit):
            if not self.p.slip_out:
                return pmax

            return pslip  # non existent price

        return None  # no price can be returned

    # 向下增加滑点
    def _slip_down(self, pmin, price, doslip=True, lim=False):
        if not doslip:
            return price

        slip_perc = self.p.slip_perc
        slip_fixed = self.p.slip_fixed
        if slip_perc:
            pslip = price * (1 - slip_perc)
        elif slip_fixed:
            pslip = price - slip_fixed
        else:
            return price

        if pslip >= pmin:  # slipping can return price
            return pslip
        elif self.p.slip_match or (lim and self.p.slip_limit):
            if not self.p.slip_out:
                return pmin

            return pslip  # non existent price

        return None  # no price can be returned

    # 尝试执行订单
    def _try_exec(self, order):
        # 产生订单的数据
        data = order.data
        # 分别获取开盘、最高、最低、收盘价，如果有tick数据，使用tick数据
        popen = getattr(data, 'tick_open', None)
        if popen is None:
            popen = data.open[0]
        phigh = getattr(data, 'tick_high', None)
        if phigh is None:
            phigh = data.high[0]
        plow = getattr(data, 'tick_low', None)
        if plow is None:
            plow = data.low[0]
        pclose = getattr(data, 'tick_close', None)
        if pclose is None:
            pclose = data.close[0]

        pcreated = order.created.price
        plimit = order.created.pricelimit

        # 根据不同的订单类型分别执行
        if order.exectype == Order.Market:
            self._try_exec_market(order, popen, phigh, plow)

        elif order.exectype == Order.Close:
            self._try_exec_close(order, pclose)

        elif order.exectype == Order.Limit:
            self._try_exec_limit(order, popen, phigh, plow, pcreated)

        elif (order.triggered and
              order.exectype in [Order.StopLimit, Order.StopTrailLimit]):
            self._try_exec_limit(order, popen, phigh, plow, plimit)

        elif order.exectype in [Order.Stop, Order.StopTrail]:
            self._try_exec_stop(order, popen, phigh, plow, pcreated, pclose)

        elif order.exectype in [Order.StopLimit, Order.StopTrailLimit]:
            self._try_exec_stoplimit(order,
                                     popen, phigh, plow, pclose,
                                     pcreated, plimit)

        elif order.exectype == Order.Historical:
            self._try_exec_historical(order)

    # 处理fund的历史
    def _process_fund_history(self):
        fhist = self._fundhist  # [last element, iterator]
        f, funds = fhist
        if not f:
            return self._fhistlast

        dt = f[0]  # date/datetime instance
        if isinstance(dt, string_types):
            dtfmt = '%Y-%m-%d'
            if 'T' in dt:
                dtfmt += 'T%H:%M:%S'
                if '.' in dt:
                    dtfmt += '.%f'
            dt = datetime.datetime.strptime(dt, dtfmt)
            f[0] = dt  # update value

        elif isinstance(dt, datetime.datetime):
            pass
        elif isinstance(dt, datetime.date):
            dt = datetime.datetime(year=dt.year, month=dt.month, day=dt.day)
            f[0] = dt  # Update the value

        # Synchronization with the strategy is not possible because the broker
        # is called before the strategy advances. The 2 lines below would do it
        # if possible
        # st0 = self.cerebro.runningstrats[0]
        # if dt <= st0.datetime.datetime():
        if dt <= self.cerebro._dtmaster:
            self._fhistlast = f[1:]
            fhist[0] = list(next(funds, []))

        return self._fhistlast

    # 处理order的历史
    def _process_order_history(self):
        for uhist in self._userhist:
            uhorder, uhorders, uhnotify = uhist
            while uhorder is not None:
                uhorder = list(uhorder)  # to support assignment (if tuple)
                try:
                    dataidx = uhorder[3]  # 2nd field
                except IndexError:
                    dataidx = None  # Field not present, use default

                if dataidx is None:
                    d = self.cerebro.datas[0]
                elif isinstance(dataidx, integer_types):
                    d = self.cerebro.datas[dataidx]
                else:  # assume string
                    d = self.cerebro.datasbyname[dataidx]

                if not len(d):
                    break  # may start later than other data feeds

                dt = uhorder[0]  # date/datetime instance
                if isinstance(dt, string_types):
                    dtfmt = '%Y-%m-%d'
                    if 'T' in dt:
                        dtfmt += 'T%H:%M:%S'
                        if '.' in dt:
                            dtfmt += '.%f'
                    dt = datetime.datetime.strptime(dt, dtfmt)
                    uhorder[0] = dt
                elif isinstance(dt, datetime.datetime):
                    pass
                elif isinstance(dt, datetime.date):
                    dt = datetime.datetime(year=dt.year,
                                           month=dt.month,
                                           day=dt.day)
                    uhorder[0] = dt

                if dt > d.datetime.datetime():
                    break  # cannot execute yet 1st in queue, stop processing

                size = uhorder[1]
                price = uhorder[2]
                owner = self.cerebro.runningstrats[0]
                if size > 0:
                    self.buy(owner=owner, data=d, size=size, price=price, exectype=Order.Historical,
                             histnotify=uhnotify, _checksubmit=False)

                elif size < 0:
                    self.sell(owner=owner, data=d, size=abs(size), price=price, exectype=Order.Historical,
                              histnotify=uhnotify, _checksubmit=False)

                # update to next potential order
                uhist[0] = uhorder = next(uhorders, None)

    # next
    def next(self):
        while self._toactivate:
            self._toactivate.popleft().activate()

        if self.p.checksubmit:
            self.check_submitted()

        # Discount any cash for positions hold
        # 利息费用
        credit = 0.0
        for data, pos in self.positions.items():
            if pos:
                comminfo = self.getcommissioninfo(data)
                dt0 = data.datetime.datetime()
                dcredit = comminfo.get_credit_interest(data, pos, dt0)
                self.d_credit[data] += dcredit
                credit += dcredit
                pos.datetime = dt0  # mark last credit operation

        self.cash -= credit
        # 处理order历史
        self._process_order_history()

        # Iterate once over all elements of the pending queue
        # 给待成交的订单增加一个None
        self.pending.append(None)
        # 循环待成交的订单一遍，到None的时候，会break跳出
        while True:
            order = self.pending.popleft()
            if order is None:
                break

            if order.expire():
                self.notify(order)
                self._ococheck(order)
                self._bracketize(order, cancel=True)

            elif not order.active():
                self.pending.append(order)  # cannot yet be processed

            else:
                self._try_exec(order)
                if order.alive():
                    self.pending.append(order)

                elif order.status == Order.Completed:
                    # a bracket parent order may have been executed
                    self._bracketize(order)

        # Operations have been executed ... adjust cash end of bar
        # 在bar结束的时候，根据持仓信息调整cash
        for data, pos in self.positions.items():
            # futures change cash every bar
            if pos:
                comminfo = self.getcommissioninfo(data)
                self.cash += comminfo.cashadjust(pos.size,
                                                 pos.adjbase,
                                                 data.close[0])
                # record the last adjustment price
                pos.adjbase = data.close[0]

        self._get_value()  # update value


# Alias
BrokerBack = BackBroker
