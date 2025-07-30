#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)


from datetime import datetime

import backtrader as bt
from backtrader.utils.py3 import range

# 创建一个chainer的元类
class MetaChainer(bt.DataBase.__class__):
    def __init__(cls, name, bases, dct):
        """Class has already been created ... register"""
        # Initialize the class
        super(MetaChainer, cls).__init__(name, bases, dct)

    def donew(cls, *args, **kwargs):
        """Intercept const. to copy timeframe/compression from 1st data"""
        # Create the object and set the params in place
        _obj, args, kwargs = super(MetaChainer, cls).donew(*args, **kwargs)

        if args:
            _obj.p.timeframe = args[0]._timeframe
            _obj.p.compression = args[0]._compression

        return _obj, args, kwargs

#
class Chainer(bt.with_metaclass(MetaChainer, bt.DataBase)):
    """Class that chains datas"""
    # 当数据是实时数据的时候 ，会避免preloading 和 runonce行为
    def islive(self):
        """Returns ``True`` to notify ``Cerebro`` that preloading and runonce
        should be deactivated"""
        return True
    # 初始化
    def __init__(self, *args):
        self._args = args

    # 开始
    def start(self):
        super(Chainer, self).start()
        for d in self._args:
            d.setenvironment(self._env)
            d._start()

        # put the references in a separate list to have pops
        self._ds = list(self._args)
        self._d = self._ds.pop(0) if self._ds else None
        self._lastdt = datetime.min

    # 停止
    def stop(self):
        super(Chainer, self).stop()
        for d in self._args:
            d.stop()

    # 通知
    def get_notifications(self):
        return [] if self._d is None else self._d.get_notifications()

    # 获取时区
    def _gettz(self):
        """To be overridden by subclasses which may auto-calculate the
        timezone"""
        if self._args:
            return self._args[0]._gettz()
        return bt.utils.date.Localizer(self.p.tz)
    # load数据，这个处理看起挺巧妙的，后续准备对期货数据的换月做一个处理或者数据到期之后就剔除这个数据
    def _load(self):
        while self._d is not None:
            if not self._d.next():  # no values from current data source
                self._d = self._ds.pop(0) if self._ds else None
                continue

            # Cannot deliver a date equal or less than an already delivered
            dt = self._d.datetime.datetime()
            if dt <= self._lastdt:
                continue

            self._lastdt = dt

            for i in range(self._d.size()):
                self.lines[i][0] = self._d.lines[i][0]

            return True

        # Out of the loop -> self._d is None, no data feed to return from
        return False
