#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from collections import OrderedDict

from .py3 import iteritems


# 这是一个没有使用到的类，创建的意图应该是保持添加进orderedDict类中保持DefaultDict的特征
# 在整个backtrader中没有找到这个类的使用，大家忽略就好，甚至可以删除，不会影响使用。
class OrderedDefaultdict(OrderedDict):
    # 类初始化，传入*args参数和**kwargs参数
    def __init__(self, *args, **kwargs):
        # 如果没有传入*args的话，默认self.default_factory是None
        if not args:
            self.default_factory = None
        # 如果传入了*args，如果args[0]不满足是None或者可调用，将会报错，如果满足了，默认将是atgs[0],剩下的参数将是args[1:]
        else:
            if not (args[0] is None or callable(args[0])):
                raise TypeError("first argument must be callable or None")
            self.default_factory = args[0]
            args = args[1:]
        super(OrderedDefaultdict, self).__init__(*args, **kwargs)

    # 当key值不存在的时候，如果self.default_factory是None的话，将会返回key error;如果不是None的话，将会返回self.default_factory()
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        self[key] = default = self.default_factory()
        return default

    # 可选方法，用于支持pickle
    def __reduce__(self):  # optional, for pickle support
        args = (self.default_factory,) if self.default_factory else ()
        return self.__class__, args, None, None, iteritems(self)
