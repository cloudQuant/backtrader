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

# import datetime

from .utils.py3 import with_metaclass
from .metabase import MetaParams


# 佣金类
class CommInfoBase(with_metaclass(MetaParams)):
    """Base Class for the Commission Schemes.

    Params:

      - ``commission`` (def: ``0.0``): base commission value in percentage or
        monetary units

        # 基础佣金，以百分比形式或者货币单位形式

      - ``mult`` (def ``1.0``): multiplier applied to the asset for
        value/profit

        # 乘数，用于资产上计算市值或者利润

      - ``margin`` (def: ``None``): amount of monetary units needed to
        open/hold an operation. It only applies if the final ``_stocklike``
        attribute in the class is set to ``False``

        # 保证金，如果_stocklike是False的时候，在开仓或者持有一个操作的时候需要的保证金

      - ``automargin`` (def: ``False``): Used by the method ``get_margin``
        to automatically calculate the margin/guarantees needed with the
        following policy

          - Use param ``margin`` if param ``automargin`` evaluates to ``False``

          - Use param ``mult`` * ``price`` if ``automargin < 0``

          - Use param ``automargin`` * ``price`` if ``automargin > 0``

        # automargin默认是False,在get_margin的时候，根据下面的方法自动计算保证金：
        # 如果automargin是False，直接使用margin
        # 如果automargin<0,直接使用乘数乘以价格
        # 如果automargin>0,直接使用automargin*automargin

      - ``commtype`` (def: ``None``): Supported values are
        ``CommInfoBase.COMM_PERC`` (commission to be understood as %) and
        ``CommInfoBase.COMM_FIXED`` (commission to be understood as monetary
        units)

        The default value of ``None`` is a supported value to retain
        compatibility with the legacy ``CommissionInfo`` object. If
        ``commtype`` is set to None, then the following applies:

          - ``margin`` is ``None``: Internal ``_commtype`` is set to
            ``COMM_PERC`` and ``_stocklike`` is set to ``True`` (Operating
            %-wise with Stocks)

          - ``margin`` is not ``None``: ``_commtype`` set to ``COMM_FIXED`` and
            ``_stocklike`` set to ``False`` (Operating with fixed round-trip
            commission with Futures)

        If this param is set to something else than ``None``, then it will be
        passed to the internal ``_commtype`` attribute and the same will be
        done with the param ``stocklike`` and the internal attribute
        ``_stocklike``

        # commtype 佣金类型，默认是None,有两种佣金类型，一种是CommInfoBase.COMM_PERC，佣金将会当成百分比形式
        # 一种是CommInfoBase.COMM_FIXED，佣金将会被当成货币单位。
        # 如果commtype是None的话，如果margin是None,内部的佣金类型将会使用百分比形式，并且_stocklike将会被设置成True
        # 如果commtype是None的话，如果margin不是None,内部的佣金类型将会按照固定形式，并且_stocklike被设置成False

      - ``stocklike`` (def: ``False``): Indicates if the instrument is
        Stock-like or Futures-like (see the ``commtype`` discussion above)

        # stocklike设置成True的时候，将会按照股票的形式来；如果设置成False的时候，将会按照期货的形式来

      - ``percabs`` (def: ``False``): when ``commtype`` is set to COMM_PERC,
        whether the parameter ``commission`` has to be understood as XX% or
        0.XX

        If this param is ``True``: 0.XX
        If this param is ``False``: XX%

        # percabs被设置成False
        # 如果commtype被设置成百分比形式了，如果pecabs是True的话，commission被理解为其本身的值
        # 如果commtype被设置成百分比形式了，如果pecabs是False的话，commission被理解为是一个百分比形式的值，真实值需要除以100

      - ``interest`` (def: ``0.0``)

        If this is non-zero, this is the yearly interest charged for holding a
        short selling position. This is mostly meant for stock short-selling

        The formula: ``days * price * abs(size) * (interest / 365)``

        It must be specified in absolute terms: 0.05 -> 5%

        .. note:: the behavior can be changed by overriding the method:
                 ``_get_credit_interest``
        # interest 默认是0 代表利息费用，如果是非0的话，通常代表卖空股票的时候，每年被收取的利息费用
        # 可以使用公式：days * price * abs(size) * (interest / 365)计算持有仓位需要缴纳的利息费用
        # interest必须是绝对值形式
        # 计算方法可以通过重写_get_credit_interest改变

      - ``interest_long`` (def: ``False``)

        Some products like ETFs get charged on interest for short and long
        positions. If ths is ``True`` and ``interest`` is non-zero the interest
        will be charged on both directions

        # 如果interest_long被设置成True的话，多空两个方向都是需要收取费用的

      - ``leverage`` (def: ``1.0``)

        Amount of leverage for the asset with regard to the needed cash

        # 杠杆水平，用于计算一个资产需要的现金

    Attributes:

      - ``_stocklike``: Final value to use for Stock-like/Futures-like behavior
      - ``_commtype``: Final value to use for PERC vs FIXED commissions

      These two are used internally instead of the declared params to enable the
      compatibility check described above for the legacy ``CommissionInfo`` object

    """

    # 百分比佣金，固定佣金
    COMM_PERC, COMM_FIXED = range(2)
    # 参数
    params = (
        ('commission', 0.0), ('mult', 1.0), ('margin', None),
        ('commtype', None),
        ('stocklike', False),
        ('percabs', False),
        ('interest', 0.0),
        ('interest_long', False),
        ('leverage', 1.0),
        ('automargin', False),
    )

    # 初始化
    def __init__(self):
        super(CommInfoBase, self).__init__()

        self._stocklike = self.p.stocklike
        self._commtype = self.p.commtype

        # The initial block checks for the behavior of the original
        # CommissionInfo in which the commission scheme (perc/fixed) was
        # determined by parameter "margin" evaluating to False/True
        # If the parameter "commtype" is None, this behavior is emulated
        # else, the parameter values are used

        if self._commtype is None:  # original CommissionInfo behavior applies
            if self.p.margin:
                self._stocklike = False
                self._commtype = self.COMM_FIXED
            else:
                self._stocklike = True
                self._commtype = self.COMM_PERC

        if not self._stocklike and not self.p.margin:
            self.p.margin = 1.0  # avoid having None/0

        if self._commtype == self.COMM_PERC and not self.p.percabs:
            self.p.commission /= 100.0

        self._creditrate = self.p.interest / 365.0

    @property
    def margin(self):
        return self.p.margin

    @property
    def stocklike(self):
        return self._stocklike

    # 获取margin todo 这个算法个人不太确定对不对，感觉有点不符合逻辑，后续回来检查
    def get_margin(self, price):
        """Returns the actual margin/guarantees needed for a single item of the
        asset at the given price. The default implementation has this policy:

          - Use param ``margin`` if param ``automargin`` evaluates to ``False``

          - Use param ``mult`` * ``price`` if ``automargin < 0``

          - Use param ``automargin`` * ``price`` if ``automargin > 0``
        """
        # print("运行的是backtrader的get_margin")
        if not self.p.automargin:
            return self.p.margin

        elif self.p.automargin < 0:
            return price * self.p.mult

        return price * self.p.automargin  # int/float expected

    # 获取杠杆
    def get_leverage(self):

        # Returns the level of leverage allowed for this comission scheme
        return self.p.leverage

    # 根据cash和size计算手数
    def getsize(self, price, cash):
        # Returns the needed size to meet a cash operation at a given price
        # todo 此处原版代码做了取整，在实际使用中，可能并不是很符合场景，这里去除取整
        # if not self._stocklike:
        #     return int(self.p.leverage * (cash // self.get_margin(price)))
        #
        # return int(self.p.leverage * (cash // price))
        if not self._stocklike:
            return self.p.leverage * (cash // self.get_margin(price))

        return self.p.leverage * (cash // price)

    # 获取操作成本
    def getoperationcost(self, size, price):
        # Returns the needed amount of cash an operation would cost
        # print(f"当前运行的是{'getoperationcost'}")
        if not self._stocklike:
            return abs(size) * self.get_margin(price)

        return abs(size) * price

    # 获取size的市值
    def getvaluesize(self, size, price):
        # Returns the value of size for given a price. For future-like
        # objects it is fixed at size * margin
        # print(f"当前运行的是{'getvaluesize'}")
        # print(size, self.get_margin(price))
        if not self._stocklike:
            return abs(size) * self.get_margin(price)

        return size * price

    # 获取持仓的市值
    def getvalue(self, position, price):
        # Returns the value of a position given a price. For future-like
        # objects it is fixed at size * margin
        if not self._stocklike:
            return abs(position.size) * self.get_margin(price)

        size = position.size
        if size >= 0:
            return size * price

        # With stocks, a short position is worth more as the price goes down
        value = position.price * size  # original value
        value += (position.price - price) * size  # increased value
        return value

    # 获取佣金
    def _getcommission(self, size, price, pseudoexec):
        """Calculates the commission of an operation at a given price

        pseudoexec: if True the operation has not yet been executed
        """
        if self._commtype == self.COMM_PERC:
            return abs(size) * self.p.commission * price

        return abs(size) * self.p.commission

    # 获取佣金的接口
    def getcommission(self, size, price):
        # Calculates the commission of an operation at a given price
        return self._getcommission(size, price, pseudoexec=True)

    # 确认交易执行
    def confirmexec(self, size, price):
        return self._getcommission(size, price, pseudoexec=False)

    # 计算pnl
    def profitandloss(self, size, price, newprice):
        # Return actual profit and loss a position has
        return size * (newprice - price) * self.p.mult

    # 调整现金
    def cashadjust(self, size, price, newprice):
        # Calculates cash adjustment for a given price difference
        if not self._stocklike:
            return size * (newprice - price) * self.p.mult

        return 0.0

    # 计算利息费用
    def get_credit_interest(self, data, pos, dt):
        # Calculates the credit due for short selling or product specific
        size, price = pos.size, pos.price

        if size > 0 and not self.p.interest_long:
            return 0.0  # long positions not charged

        dt0 = dt.date()
        dt1 = pos.datetime.date()

        if dt0 <= dt1:
            return 0.0

        return self._get_credit_interest(data, size, price,
                                         (dt0 - dt1).days, dt0, dt1)

    # 计算利息的方法，可以重写
    def _get_credit_interest(self, data, size, price, days, dt0, dt1):
        """
        This method returns  the cost in terms of credit interest charged by
        the broker.

        In the case of ``size > 0`` this method will only be called if the
        parameter to the class ``interest_long`` is ``True``

        The formula for the calculation of the credit interest rate is:

          The formula: ``days * price * abs(size) * (interest / 365)``


        Params:
          - ``data``: data feed for which interest is charged

          - ``size``: current position size. > 0 for long positions and < 0 for
            short positions (this parameter will not be ``0``)

          - ``price``: current position price

          - ``days``: number of days elapsed since last credit calculation
            (this is (dt0 - dt1).days)

          - ``dt0``: (datetime.datetime) current datetime

          - ``dt1``: (datetime.datetime) datetime of previous calculation

        ``dt0`` and ``dt1`` are not used in the default implementation and are
        provided as extra input for overridden methods
        """
        return days * self._creditrate * abs(size) * price


# 佣金类，commission大小使用其本身
class CommissionInfo(CommInfoBase):
    """Base Class for the actual Commission Schemes.

    CommInfoBase was created to keep support for the original, incomplete,
    support provided by *backtrader*. New commission schemes derive from this
    class which subclasses ``CommInfoBase``.

    The default value of ``percabs`` is also changed to ``True``

    Params:

      - ``percabs`` (def: True): when ``commtype`` is set to COMM_PERC, whether
        the parameter ``commission`` has to be understood as XX% or 0.XX

        If this param is True: 0.XX
        If this param is False: XX%

    """
    params = (
        ('percabs', True),  # Original CommissionInfo took 0.xx for percentages
    )


class ComminfoDC(CommInfoBase):
    # 实现一个数字货币的佣金类
    params = (
        ('stocklike', False),
        ('commtype', CommInfoBase.COMM_PERC),
        ('percabs', True),
        ("interest", 3),
    )

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * price * self.p.mult * self.p.commission

    def get_margin(self, price):
        return price * self.p.mult * self.p.margin

    # 计算利息费用,这里面涉及到一些简化
    def get_credit_interest(self, data, pos, dt):
        """例如我持有100U，要买300U的BTC，杠杆为三倍，这时候我只需要借入2*100U的钱就可以了，
       所以利息应该是200U * interest，同理，对于n倍开多，需要付（n-1）*base的利息
        如果我要开空，我只有100U，我必须借入BTC先卖掉，就算是一倍开空，也得借入100U的BTC，
        所以对于n倍开空，需要付n*base的利息"""
        # 仓位及价格
        size, price = pos.size, pos.price
        # 持仓时间
        dt0 = dt
        dt1 = pos.datetime
        gap_seconds = (dt0 - dt1).seconds
        days = gap_seconds / (24 * 60 * 60)
        # 计算当前的持仓价值
        position_value = size * price * self.p.mult
        # 如果当前的持仓是多头，并且持仓价值大于1倍杠杆，超过1倍杠杆的部分将会收取利息费用
        total_value = self.broker.getvalue()
        if size > 0 and position_value > total_value:
            return days * self._creditrate * (position_value - total_value)
        # 如果持仓是多头，但是在一倍杠杆之内
        if size > 0 and position_value <= total_value:
            return 0
        # 如果当前是做空的交易，计算利息
        if size < 0:
            return days * self._creditrate * position_value


class ComminfoFuturesPercent(CommInfoBase):
    # write by myself,using in the future backtest,it means we should give a percent comminfo to broker
    params = (
        ('commission', 0.0), ('mult', 1.0), ('margin', None),
        ('stocklike', False),
        ('commtype', CommInfoBase.COMM_PERC),
        ('percabs', True)
    )

    # print("运行的是ComminfoFuturesPercent的get_margin")
    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * price * self.p.mult * self.p.commission

    def get_margin(self, price):
        return price * self.p.mult * self.p.margin


# comm_rb = CommInfoFutures(commission=1e-4, margin=0.09, mult=10.0)
# cerebro = bt.Cerebro()
# cerebro.broker.addcommissioninfo(comm_rb, name='RB')

class ComminfoFuturesFixed(CommInfoBase):
    # write by myself,using in the future backtest,it means we should give a fixed comminfo evey lot to broker
    params = (
        ('commission', 0.0), ('mult', 1.0), ('margin', None),
        ('stocklike', False),
        ('commtype', CommInfoBase.COMM_FIXED),
        ('percabs', True)
    )

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * self.p.commission

    def get_margin(self, price):
        return price * self.p.mult * self.p.margin
