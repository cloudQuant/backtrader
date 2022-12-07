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

from backtrader.comminfo import CommInfoBase
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass

# from . import fillers as fillers
# from . import fillers as filler


# broker元类，使得get_cash与getcash,get_value与getvalue方法相同
class MetaBroker(MetaParams):
    def __init__(cls, name, bases, dct):
        # Class has already been created ... fill missing methods if needed be
        # Initialize the class
        super(MetaBroker, cls).__init__(name, bases, dct)
        translations = {
            'get_cash': 'getcash',
            'get_value': 'getvalue',
        }

        for attr, trans in translations.items():
            if not hasattr(cls, attr):
                setattr(cls, name, getattr(cls, trans))


# broker基类
class BrokerBase(with_metaclass(MetaBroker, object)):
    # 参数
    params = (
        ('commission', CommInfoBase(percabs=True)),
    )

    # 初始化
    def __init__(self):
        self.comminfo = dict()
        self.init()

    # 这个init用一个None做key,commission做value
    def init(self):
        # called from init and from start
        if None not in self.comminfo:
            self.comminfo = dict({None: self.p.commission})

    # 开始
    def start(self):
        self.init()

    # 结束
    def stop(self):
        pass

    # 增加历史order
    def add_order_history(self, orders, notify=False):
        # Add order history. See cerebro for details
        raise NotImplementedError

    # 设置历史fund
    def set_fund_history(self, fund):
        # Add fund history. See cerebro for details
        raise NotImplementedError

    # 获取佣金信息，如果data._name在佣金信息字典中，获取相应的值，否则用默认的self.p.commission
    def getcommissioninfo(self, data):
        # Retrieves the ``CommissionInfo`` scheme associated with the given ``data``
        # if data._name in self.comminfo:
        #     return self.comminfo[data._name]
        # todo 避免访问被保护的属性._name,在加载数据的时候，已经增加了.name属性，用.name替代_name,避免pycharm弹出警告信息
        if data.name in self.comminfo:
            return self.comminfo[data.name]

        return self.comminfo[None]

    # 设置佣金
    def setcommission(self,
                      commission=0.0, margin=None, mult=1.0,
                      commtype=None, percabs=True, stocklike=False,
                      interest=0.0, interest_long=False, leverage=1.0,
                      automargin=False,
                      name=None):

        """This method sets a `` CommissionInfo`` object for assets managed in
        the broker with the parameters. Consult the reference for
        ``CommInfoBase``

        If name is ``None``, this will be the default for assets for which no
        other ``CommissionInfo`` scheme can be found
        """

        comm = CommInfoBase(commission=commission, margin=margin, mult=mult,
                            commtype=commtype, stocklike=stocklike,
                            percabs=percabs,
                            interest=interest, interest_long=interest_long,
                            leverage=leverage, automargin=automargin)
        self.comminfo[name] = comm

    # 增加佣金信息
    def addcommissioninfo(self, comminfo, name=None):
        # Adds a ``CommissionInfo`` object that will be the default for all assets if ``name`` is ``None``
        self.comminfo[name] = comminfo

    # 获取现金
    def getcash(self):
        raise NotImplementedError

    # 获取市值
    def getvalue(self, datas=None):
        raise NotImplementedError

    # 获取基金份额
    def get_fundshares(self):
        # Returns the current number of shares in the fund-like mode
        return 1.0  # the abstract mode has only 1 share

    fundshares = property(get_fundshares)

    # 获取基金市值
    def get_fundvalue(self):
        return self.getvalue()

    fundvalue = property(get_fundvalue)

    # 设置基金模式
    def set_fundmode(self, fundmode, fundstartval=None):
        """Set the actual fundmode (True or False)

        If the argument fundstartval is not ``None``, it will use
        """
        pass  # do nothing, not all brokers can support this

    # 获取基金模式
    def get_fundmode(self):
        # Returns the actual fundmode (True or False)
        return False

    fundmode = property(get_fundmode, set_fundmode)

    # 获取持仓
    def getposition(self, data):
        raise NotImplementedError

    # 提交
    def submit(self, order):
        raise NotImplementedError

    # 取消
    def cancel(self, order):
        raise NotImplementedError

    # 买入下单
    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            **kwargs):

        raise NotImplementedError

    # 卖出下单
    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             **kwargs):

        raise NotImplementedError

    # 下一个bar
    def next(self):
        pass

# __all__ = ['BrokerBase', 'fillers', 'filler']
