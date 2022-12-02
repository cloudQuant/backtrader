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

from ..utils.py3 import with_metaclass

from . import Indicator

# 移动平均类，用于设置指标的名字
class MovingAverage(object):
    '''MovingAverage (alias MovAv)

    A placeholder to gather all Moving Average Types in a single place.

    Instantiating a SimpleMovingAverage can be achieved as follows::

      sma = MovingAverage.Simple(self.data, period)

    Or using the shorter aliases::

      sma = MovAv.SMA(self.data, period)

    or with the full (forwards and backwards) names:

      sma = MovAv.SimpleMovingAverage(self.data, period)

      sma = MovAv.MovingAverageSimple(self.data, period)

    '''
    # 移动平均类的保存
    _movavs = []

    @classmethod
    def register(cls, regcls):
        # 如果指标中没有_notregister或者_notregister的值是False，就继续运行，进行注册，否则直接返回
        if getattr(regcls, '_notregister', False):
            return
        # 把需要计算的指标类添加进去
        cls._movavs.append(regcls)
        # 类的名称，并且把类名称设置成cls的属性，属性值为具体的类
        clsname = regcls.__name__
        setattr(cls, clsname, regcls)

        # 具体指标的别名，如果指标开头是MovingAverage,那么，用后面的值作为别名，如果结尾是MovingAverage，用前面的值作为别名
        # 如果取得的别名不是空字符串，那么就把别名也设置成属性，该属性的值为这个类
        clsalias = ''
        if clsname.endswith('MovingAverage'):
            clsalias = clsname.split('MovingAverage')[0]
        elif clsname.startswith('MovingAverage'):
            clsalias = clsname.split('MovingAverage')[1]

        if clsalias:
            setattr(cls, clsalias, regcls)

# 移动平均的别名
class MovAv(MovingAverage):
    pass  # alias


# 移动平均的基类
class MetaMovAvBase(Indicator.__class__):
    # Register any MovingAverage with the placeholder to allow the automatic
    # creation of envelopes and oscillators
    # 创建移动平均值的类
    def __new__(meta, name, bases, dct):
        # Create the class
        cls = super(MetaMovAvBase, meta).__new__(meta, name, bases, dct)

        MovingAverage.register(cls)

        # return the class
        return cls

# 移动平均的基类，增加参数和画图的设置
class MovingAverageBase(with_metaclass(MetaMovAvBase, Indicator)):
    # 参数
    params = (('period', 30),)
    # 默认画到主图上
    plotinfo = dict(subplot=False)
