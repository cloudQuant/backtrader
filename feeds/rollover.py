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


from datetime import datetime

import backtrader as bt


# rollover元类
class MetaRollOver(bt.DataBase.__class__):
    def __init__(cls, name, bases, dct):
        '''Class has already been created ... register'''
        # Initialize the class
        super(MetaRollOver, cls).__init__(name, bases, dct)

    def donew(cls, *args, **kwargs):
        '''Intercept const. to copy timeframe/compression from 1st data'''
        # Create the object and set the params in place
        _obj, args, kwargs = super(MetaRollOver, cls).donew(*args, **kwargs)

        if args:
            _obj.p.timeframe = args[0]._timeframe
            _obj.p.compression = args[0]._compression

        return _obj, args, kwargs


class RollOver(bt.with_metaclass(MetaRollOver, bt.DataBase)):
    # 当条件满足之后，移动到下一个合约上
    '''Class that rolls over to the next future when a condition is met

    Params:

        - ``checkdate`` (default: ``None``)

          This must be a *callable* with the following signature::

            checkdate(dt, d):

          Where:

            - ``dt`` is a ``datetime.datetime`` object
            - ``d`` is the current data feed for the active future

          Expected Return Values:

            - ``True``: as long as the callable returns this, a switchover can
              happen to the next future

        If a commodity expires on the 3rd Friday of March, ``checkdate`` could
        return ``True`` for the entire week in which the expiration takes
        place.

            - ``False``: the expiration cannot take place

        # 这个参数是一个可调用对象checkdate(dt,d),其中dt是一个时间对象，d是当前活跃数据，
        # 如果返回的值是True，就会转移到下一个合约上；如果是False，就不会转移到下个合约上

        - ``checkcondition`` (default: ``None``)

          **Note**: This will only be called if ``checkdate`` has returned
          ``True``

          If ``None`` this will evaluate to ``True`` (execute roll over)
          internally

          Else this must be a *callable* with this signature::

            checkcondition(d0, d1)

          Where:

            - ``d0`` is the current data feed for the active future
            - ``d1`` is the data feed for the next expiration

          Expected Return Values:

            - ``True``: roll-over to the next future

        Following with the example from ``checkdate``, this could say that the
        roll-over can only happend if the *volume* from ``d0`` is already less
        than the volume from ``d1``

            - ``False``: the expiration cannot take place
        # 在checkdate返回是True的时候，将会调用这个功能，这个必须要是一个可调用对象，checkcondition(d0,d1)
        # 其中d0是当前激活的期货合约，d1是下一个到期的合约，如果是True的话，将会从d0转移到d1上，如果不是，将不会发生转移。
    '''

    params = (
        # ('rolls', []),  # array of futures to roll over
        ('checkdate', None),  # callable
        ('checkcondition', None),  # callable
    )

    def islive(self):
        # 让数据是live形式，将会避免preloading和runonce
        '''Returns ``True`` to notify ``Cerebro`` that preloading and runonce
        should be deactivated'''
        return True

    def __init__(self, *args):
        # 准备用于换月的期货合约
        self._rolls = args

    def start(self):
        super(RollOver, self).start()
        # 循环所有的数据，准备开始
        for d in self._rolls:
            d.setenvironment(self._env)
            d._start()

        # put the references in a separate list to have pops
        # todo 此处从新使用list好像用处不大，应为self._rolls本身就是list格式
        self._ds = list(self._rolls)
        # 第一个数据
        self._d = self._ds.pop(0) if self._ds else None
        # 到期数据
        self._dexp = None
        # 此处默认了一个最小的时间，当和任何时间对比的时候，都会进行移动
        self._dts = [datetime.min for xx in self._ds]

    def stop(self):
        # 结束数据
        super(RollOver, self).stop()
        for d in self._rolls:
            d.stop()

    def _gettz(self):
        # 获取具体的时区
        '''To be overriden by subclasses which may auto-calculate the
        timezone'''
        if self._rolls:
            return self._rolls[0]._gettz()
        return bt.utils.date.Localizer(self.p.tz)

    def _checkdate(self, dt, d):
        # 计算当前是否满足换月条件
        if self.p.checkdate is not None:
            return self.p.checkdate(dt, d)

        return False

    def _checkcondition(self, d0, d1):
        # 准备开始换月
        if self.p.checkcondition is not None:
            return self.p.checkcondition(d0, d1)

        return True

    def _load(self):
        # 加载数据的方法
        while self._d is not None:
            # 当self._d不是None的时候，调用next
            _next = self._d.next()
            # 如果_next值是None的话，继续调用next
            if _next is None:  # no values yet, more will come
                continue
            # 如果_next值是False的话，当前数据就换到下个数据上，
            if _next is False:  # no values from current data src
                if self._ds:
                    self._d = self._ds.pop(0)
                    self._dts.pop(0)
                else:
                    self._d = None
                continue
            # 当前数据的当前时间
            dt0 = self._d.datetime.datetime()  # current dt for active data

            # Synchronize other datas using dt0
            # 根据当前时间同步其他的数据
            for i, d_dt in enumerate(zip(self._ds, self._dts)):
                d, dt = d_dt
                # 如果其他数据的时间小于当前时间，就把其他数据向后移动，时间增加，并把时间保存到self._dts中
                while dt < dt0:
                    if d.next() is None:
                        continue
                    self._dts[i] = dt = d.datetime.datetime()

            # Move expired future as much as needed
            # 移动到期的数据
            while self._dexp is not None:
                if not self._dexp.next():
                    self._dexp = None
                    break

                if self._dexp.datetime.datetime() < dt0:
                    continue

            if self._dexp is None and self._checkdate(dt0, self._d):
                # rule has been met ... check other factors only if 2 datas
                # still there
                if self._ds and self._checkcondition(self._d, self._ds[0]):
                    # Time to switch to next data
                    self._dexp = self._d
                    self._d = self._ds.pop(0)
                    self._dts.pop(0)

            # Fill the line and tell we die
            self.lines.datetime[0] = self._d.lines.datetime[0]
            self.lines.open[0] = self._d.lines.open[0]
            self.lines.high[0] = self._d.lines.high[0]
            self.lines.low[0] = self._d.lines.low[0]
            self.lines.close[0] = self._d.lines.close[0]
            self.lines.volume[0] = self._d.lines.volume[0]
            self.lines.openinterest[0] = self._d.lines.openinterest[0]
            return True

        # Out of the loop -> self._d is None, no data feed to return from
        return False
