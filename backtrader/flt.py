#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .metabase import MetaParams


__all__ = ["Filter"]


# Filter元类
class MetaFilter(MetaParams):
    pass


# filter类
class Filter(metaclass=MetaParams):

    _firsttime = True

    def __init__(self, data_):
        pass

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
