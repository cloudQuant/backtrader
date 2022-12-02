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

import math

# 看了一下，这几个函数主要用于计算一些指标使用，在主体中没有用到，注释一下，稍后回来看是否需要用cython改进，暂时没有改进的必要。
# 但是这几个函数其实可以考虑使用numpy改进一下，numpy提供了具体的函数用于计算均值，计算标准差

# 这个计算的是平均值，带了一个参数bessel，用于确定计算平均值的时候分母的值是否减去一。分子使用math.fsum用于计算和
def average(x, bessel=False):
    '''
    Args:
      x: iterable with len

      oneless: (default ``False``) reduces the length of the array for the
                division.

    Returns:
      A float with the average of the elements of x
    '''
    return math.fsum(x) / (len(x) - bessel)

# 用于计算方差，很明显，这种函数直接改成cython或者numpy，会有很大的效率提升。但是这函数属于边缘函数，暂时忽略改进。
# 这个函数先判断了avgx是否是None,如果是None然后计算一个可迭代对象的平均值，然后计算方差。
def variance(x, avgx=None):
    '''
    Args:
      x: iterable with len

    Returns:
      A list with the variance for each element of x
    '''
    if avgx is None:
        avgx = average(x)
    return [pow(y - avgx, 2.0) for y in x]

# 这个函数用于计算一个可迭代对象x的标准差。
def standarddev(x, avgx=None, bessel=False):
    '''
    Args:
      x: iterable with len

      bessel: (default ``False``) to be passed to the average to divide by
      ``N - 1`` (Bessel's correction)

    Returns:
      A float with the standard deviation of the elements of x
    '''
    return math.sqrt(average(variance(x, avgx), bessel=bessel))
