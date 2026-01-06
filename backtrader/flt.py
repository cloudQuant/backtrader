#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .parameters import ParameterizedBase

__all__ = ["Filter"]


# Filter class - refactored to use new parameter system
class Filter(ParameterizedBase):
    """
    Base class for data filters in backtrader.

    This class has been refactored from MetaParams to the new ParameterizedBase
    system for Day 36-38 of the metaprogramming removal project.
    """

    _firsttime = True

    def __init__(self, data_, **kwargs):
        # Call parent class initialization
        super(Filter, self).__init__(**kwargs)

    def __call__(self, data):
        # If first time, call nextstart, then set _firsttime to False
        if self._firsttime:
            self.nextstart(data)
            self._firsttime = False
        # Call next
        self.next(data)

    def nextstart(self, data):
        pass

    def next(self, data):
        pass
