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

import itertools
import sys

PY2 = sys.version_info.major == 2   # 获取当前python的版本，看是否是python2,如果是python2,返回值就是True,否则就是False

# 如果是python2
if PY2:
    # 尝试用于import _winreg模块，如果可以调用，就证明这个系统是windows系统，可以用于windows注册表相关的操作；
    # 如果调用出现了错误，就说明系统不是windows系统，winreg设置成None
    try:
        import _winreg as winreg
    except ImportError:
        winreg = None
    # 系统允许的最大整数
    MAXINT = sys.maxint
    # 系统允许的最小整数
    MININT = -sys.maxint - 1
    # 系统允许的最大浮点数
    MAXFLOAT = sys.float_info.max
    # 系统允许的最小浮点数
    MINFLOAT = sys.float_info.min
    # 字符串类型
    string_types = str, unicode
    # 整数类型
    integer_types = int, long
    # 过滤函数filter
    filter = itertools.ifilter
    # 映射函数map
    map = itertools.imap
    # 创建整数迭代器函数range
    range = xrange
    # 把元素成对打包成元组的函数zip
    zip = itertools.izip
    # 整数
    long = long
    # 对比函数
    cmp = cmp
    # 生成bytes
    bytes = bytes
    bstr = bytes
    # 字符串缓存
    from io import StringIO
    # 爬虫模块
    from urllib2 import urlopen, ProxyHandler, build_opener, install_opener
    from urllib import quote as urlquote
    # 字典迭代
    def iterkeys(d): return d.iterkeys()

    def itervalues(d): return d.itervalues()

    def iteritems(d): return d.iteritems()
    # 字典值
    def keys(d): return d.keys()

    def values(d): return d.values()

    def items(d): return d.items()

    import Queue as queue
    
    
else:
    # python3的注释和上面的注释差不多
    try:
        import winreg
    except ImportError:
        winreg = None
    
    MAXINT = sys.maxsize
    MININT = -sys.maxsize - 1

    MAXFLOAT = sys.float_info.max
    MINFLOAT = sys.float_info.min

    string_types = str,
    integer_types = int,

    filter = filter
    map = map
    range = range
    zip = zip
    long = int
    # 需要注意，这个cmp是自定义的函数，返回值是1,0,-1
    def cmp(a, b): return (a > b) - (a < b)

    def bytes(x): return x.encode('utf-8')

    def bstr(x): return str(x)

    from io import StringIO

    from urllib.request import (urlopen, ProxyHandler, build_opener,
                                install_opener)
    from urllib.parse import quote as urlquote

    def iterkeys(d): return iter(d.keys())

    def itervalues(d): return iter(d.values())

    def iteritems(d): return iter(d.items())

    def keys(d): return list(d.keys())

    def values(d): return list(d.values())

    def items(d): return list(d.items())

    import queue as queue
    
    
# This is from Armin Ronacher from Flash simplified later by six
def with_metaclass(meta, *bases):
    """Create a base class with a metaclass."""
    # This requires a bit of explanation: the basic idea is to make a dummy
    # metaclass for one level of class instantiation that replaces itself with
    # the actual metaclass.
    # 这个函数创建一个带有元类的基类，主要作用是兼容python2和python3的语法，现在有了一个更新的方案，是使用装饰器@six.add_metaclass(Meta)
    # 参考文献：https://qa.1r1g.com/sf/ask/1295967501/
    # https://zhuanlan.zhihu.com/p/354828950
    # https://www.jianshu.com/p/224ffcb8e73e
    class metaclass(meta):

        def __new__(cls, name, this_bases, d):
            return meta(name, bases, d)
    return type.__new__(metaclass, str('temporary_class'), (), {})
