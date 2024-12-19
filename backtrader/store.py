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

from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass


class MetaSingleton(MetaParams):
    '''Metaclass to make a metaclassed class a singleton'''
    def __init__(cls, name, bases, dct):
        super(MetaSingleton, cls).__init__(name, bases, dct)
        cls._singleton = None

    def __call__(cls, *args, **kwargs):
        if cls._singleton is None:
            cls._singleton = (
                super(MetaSingleton, cls).__call__(*args, **kwargs))

        return cls._singleton

# 创建一个store类
class Store(with_metaclass(MetaSingleton, object)):
    '''Base class for all Stores'''
    # 开始，默认是False
    _started = False
    # 参数
    params = ()
    # 获取数据
    def getdata(self, *args, **kwargs):
        '''Returns ``DataCls`` with args, kwargs'''
        data = self.DataCls(*args, **kwargs)
        data._store = self
        return data

    # 获取broker
    @classmethod
    def getbroker(cls, *args, **kwargs):
        '''Returns broker with *args, **kwargs from registered ``BrokerCls``'''
        broker = cls.BrokerCls(*args, **kwargs)
        broker._store = cls
        return broker

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    # 开始
    def start(self, data=None, broker=None):
        # 如果还没有开始，就初始化
        if not self._started:
            self._started = True
            self.notifs = collections.deque()
            self.datas = list()
            self.broker = None
        # 如果数据不是None
        if data is not None:
            self._cerebro = self._env = data._env
            self.datas.append(data)
            # 如果self.broker不是None的话
            if self.broker is not None:
                if hasattr(self.broker, 'data_started'):
                    self.broker.data_started(data)
        # 如果broker不是None的话
        elif broker is not None:
            self.broker = broker

    # 结束
    def stop(self):
        pass

    # 把信息添加到通知
    def put_notification(self, msg, *args, **kwargs):
        self.notifs.append((msg, args, kwargs))

    # 获取通知的信息
    def get_notifications(self):
        '''Return the pending "store" notifications'''
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]
