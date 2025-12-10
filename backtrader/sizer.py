#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .parameters import ParameterizedBase


# Sizer类 - 重构为使用新的参数系统
class Sizer(ParameterizedBase):
    """
    This is the base class for *Sizers*. Any *sizer* should subclass this
    and override the ``_getsizing`` method.

    This class has been refactored from MetaParams to the new ParameterizedBase
    system for Day 36-38 of the metaprogramming removal project.

    Member Attribs:

      - ``strategy``: will be set by the strategy in which the sizer is working

        Gives access to the entire api of the strategy, for example, if the
        actual data position is needed in ``_getsizing``:

           Position = self.strategy.getposition(data)

      - ``broker``: will be set by the strategy in which the sizer is working

        Gives access to information some complex sizers may need like portfolio
        value.

      # strategy 代表在使用sizer的strategy策略，可以通过strategy调用所有的strategy的api
      # broker 代表使用strategy所在的broker，可以用于获取信息进行计算复杂的手数
    """

    strategy = None
    broker = None

    def __init__(self, **kwargs):
        """Initialize the Sizer with any provided parameters."""
        super(Sizer, self).__init__(**kwargs)

    # 获取下单使用的具体的手数
    def getsizing(self, data, isbuy):
        comminfo = self.broker.getcommissioninfo(data)
        return self._getsizing(comminfo, self.broker.getcash(), data, isbuy)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """This method has to be overriden by subclasses of Sizer to provide
        the sizing functionality

        Params:
          - ``comminfo``: The CommissionInfo instance that contains
            information about the commission for the data and allows
            calculation of position value, operation cost, commission for the
            operation

          - ``cash``: current available cash in the *broker*

          - ``data``: target of the operation

          - ``isbuy``: will be ``True`` for *buy* operations and ``False``
            for *sell* operations

        The method has to return the actual size (an int) to be executed. If
         `0` is returned, nothing will be executed.

        The absolute value of the returned value will be used
        # 这个方法在使用的 时候需要被重写，传入四个参数：
        # comminfo 代表佣金的实例，可以用于获取佣金等信息
        # cash 代表当前可以使用的现金
        # data 代表在那个数据上进行交易
        # isbuy 代表在buy操作的时候是True，sell的时候代表是False

        """
        raise NotImplementedError

    # 设置策略和broker
    def set(self, strategy, broker):
        self.strategy = strategy
        self.broker = broker


# SizerBase类
SizerBase = Sizer
