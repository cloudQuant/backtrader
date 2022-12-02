#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
#  Copyright (C) 2015, 2016, 2017 Daniel Rodriguez
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys

# 这个类按照字面意思来看，应该是输出的时候刷新，让输出立即显示，但是看这个类的使用，好像并没有起到这个作用
# 只有在btrun文件中import这个文件，import backtrader.utils.flushfile，import的时候会直接判断这个系统
# 是不是win32,如果是win32就用flushfile创建两个实例，初始化的时候使用sys.stdout，sys.stderr这两个方法
# 实际上看起来，并没有起到什么作用。就跟py3的文件一样，可能是为了起到兼容的作用，但是现在谁还用python2呀，几乎很少了
# 所以整个框架看起来冗余了不少的函数和类
class flushfile(object):

    def __init__(self, f):
        self.f = f

    def write(self, x):
        self.f.write(x)
        self.f.flush()

    def flush(self):
        self.f.flush()

if sys.platform == 'win32':
    sys.stdout = flushfile(sys.stdout)
    sys.stderr = flushfile(sys.stderr)

# 没有用到的类，看类型的话，应该是输出的
class StdOutDevNull(object):

    def __init__(self):
        self.stdout = sys.stdout
        sys.stdout = self

    def write(self, x):
        pass

    def flush(self):
        pass

    def stop(self):
        sys.stdout = self.stdout
