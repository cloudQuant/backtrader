#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .parameters import ParameterizedBase

__all__ = ["Filter"]


# Filter类 - 重构为使用新的参数系统
class Filter(ParameterizedBase):
    """
    Base class for data filters in backtrader.

    This class has been refactored from MetaParams to the new ParameterizedBase
    system for Day 36-38 of the metaprogramming removal project.
    """

    _firsttime = True

    def __init__(self, data_, **kwargs):
        # 调用父类初始化
        super(Filter, self).__init__(**kwargs)

    def __call__(self, data):
        # 如果是第一次，就调用nextstart,然后把_firsttime设置成False
        if self._firsttime:
            self.nextstart(data)
            self._firsttime = False
        # 调用next
        self.next(data)

    def nextstart(self, data):
        pass

    def next(self, data):
        pass
