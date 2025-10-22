#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from ..sizer import Sizer
from ..parameters import ParameterDescriptor, Int


# 固定手数类，如果下单的时候没有指定size,将会默认调用一个sizer
class FixedSize(Sizer):
    """
    This sizer simply returns a fixed size for any operation.
    Size can be controlled by the number of tranches that a system
    wishes to use to scale into trades by specifying the ``tranches``
    parameter.

    This class has been refactored from legacy params tuple to the new 
    ParameterDescriptor system for Day 36-38 of the metaprogramming removal project.

    Params:
      - ``stake`` (default: ``1``)
      - ``tranches`` (default: ``1``)
    """

    # 使用新的参数描述符系统定义参数
    stake = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Fixed stake size for operations"
    )
    tranches = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Number of tranches to divide stake into"
    )

    def __init__(self, **kwargs):
        super(FixedSize, self).__init__(**kwargs)

    # 返回具体的手数，如果tranches大于1，会把手数分成tranches份，否则直接返回手数
    def _getsizing(self, comminfo, cash, data, isbuy):
        if self.get_param('tranches') > 1:
            return abs(int(self.get_param('stake') / self.get_param('tranches')))
        else:
            return self.get_param('stake')

    # 设置手数
    def setsizing(self, stake):
        if self.get_param('tranches') > 1:
            self.set_param('stake', abs(int(stake / self.get_param('tranches'))))
        else:
            self.set_param('stake', stake)  # OLD METHOD FOR SAMPLE COMPATIBILITY


# FixedSize的另一个名称
SizerFix = FixedSize


# 如果是开仓，使用stake手，如果是反手，使用两倍的stake手
class FixedReverser(Sizer):
    """This sizer returns the needes fixed size to reverse an open position or
    the fixed size to open one

      - To open a position: return the param ``stake``

      - To reverse a position: return 2 * `stake`

    Params:
      - ``stake`` (default: ``1``)
    """

    stake = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Fixed stake size for operations"
    )

    def __init__(self, **kwargs):
        super(FixedReverser, self).__init__(**kwargs)

    def _getsizing(self, comminfo, cash, data, isbuy):
        position = self.strategy.getposition(data)
        size = self.get_param('stake') * (1 + (position.size != 0))
        return size


# 固定目标手数，如果tranches大于1的话，会先把stake分成tranches份，然后计算当前持仓和每份持仓与stake的大小，选择比较小的作为下单的手数
# 如果tranches不大于1，直接使用stake手数
class FixedSizeTarget(Sizer):
    """
    This sizer simply returns a fixed target size, useful when coupled
    with Target Orders and specifically ``cerebro.target_order_size()``.
    Size can be controlled by the number of tranches that a system
    wishes to use to scale into trades by specifying the ``tranches``
    parameter.

    Params:
      - ``stake`` (default: ``1``)
      - ``tranches`` (default: ``1``)
    """

    stake = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Fixed target stake size"
    )
    tranches = ParameterDescriptor(
        default=1,
        type_=int,
        validator=Int(min_val=1),
        doc="Number of tranches to divide stake into"
    )

    def __init__(self, **kwargs):
        super(FixedSizeTarget, self).__init__(**kwargs)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if self.get_param('tranches') > 1:
            size = abs(int(self.get_param('stake') / self.get_param('tranches')))
            return min((self.strategy.position.size + size), self.get_param('stake'))
        else:
            return self.get_param('stake')

    def setsizing(self, stake):
        if self.get_param('tranches') > 1:
            size = abs(int(stake / self.get_param('tranches')))
            self.set_param('stake', min((self.strategy.position.size + size), stake))
        else:
            self.set_param('stake', stake)  # OLD METHOD FOR SAMPLE COMPATIBILITY
