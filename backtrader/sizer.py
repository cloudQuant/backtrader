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

from .utils.py3 import with_metaclass

from .metabase import MetaParams

# Sizer类,其他的sizer需要继承这个类并且重写_getsizing类
class Sizer(with_metaclass(MetaParams, object)):
    '''This is the base class for *Sizers*. Any *sizer* should subclass this
    and override the ``_getsizing`` method

    Member Attribs:

      - ``strategy``: will be set by the strategy in which the sizer is working

        Gives access to the entire api of the strategy, for example if the
        actual data position would be needed in ``_getsizing``::

           position = self.strategy.getposition(data)

      - ``broker``: will be set by the strategy in which the sizer is working

        Gives access to information some complex sizers may need like portfolio
        value, ..

      # strategy 代表在使用sizer的strategy策略，可以通过strategy调用所有的strategy的api
      # broker 代表使用strategy所在的broker，可以用于获取信息进行计算复杂的手数
    '''
    strategy = None
    broker = None

    # 获取下单使用的具体的手数
    def getsizing(self, data, isbuy):
        comminfo = self.broker.getcommissioninfo(data)
        return self._getsizing(comminfo, self.broker.getcash(), data, isbuy)

    def _getsizing(self, comminfo, cash, data, isbuy):
        '''This method has to be overriden by subclasses of Sizer to provide
        the sizing functionality

        Params:
          - ``comminfo``: The CommissionInfo instance that contains
            information about the commission for the data and allows
            calculation of position value, operation cost, commision for the
            operation

          - ``cash``: current available cash in the *broker*

          - ``data``: target of the operation

          - ``isbuy``: will be ``True`` for *buy* operations and ``False``
            for *sell* operations

        The method has to return the actual size (an int) to be executed. If
        ``0`` is returned nothing will be executed.

        The absolute value of the returned value will be used
        # 这个方法在使用的 时候需要被重写，传入四个参数：
        # comminfo  代表佣金的实例，可以用于获取佣金等信息
        # cash      代表当前可以使用的现金
        # data      代表在那个数据上进行交易
        # isbuy     代表在buy操作的时候是True，sell的时候代表是False

        '''
        raise NotImplementedError

    # 设置策略和broker
    def set(self, strategy, broker):
        self.strategy = strategy
        self.broker = broker

# SizerBase类
SizerBase = Sizer  # alias for old naming
