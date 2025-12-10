#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .lineiterator import LineIterator, ObserverBase, StrategyBase


# Observer类 - 重构为不使用元类
class Observer(ObserverBase):
    """
    Observer base class that has been refactored to remove metaclass usage
    while maintaining the same functionality.
    """

    # _stclock设置成False
    _stclock = False
    # 拥有的实例
    _OwnerCls = StrategyBase
    # line的类型
    _ltype = LineIterator.ObsType
    # 是否保存到csv等文件中
    csv = True
    # 画图设置选择
    plotinfo = dict(plot=False, subplot=True)

    def __new__(cls, *args, **kwargs):
        """
        Custom __new__ to implement the functionality previously in MetaObserver.donew
        """
        # Create the instance using parent's __new__
        _obj = super(Observer, cls).__new__(cls)

        # Initialize _analyzers list (previously done in MetaObserver.donew)
        _obj._analyzers = list()  # keep children analyzers

        return _obj

    def __init__(self, *args, **kwargs):
        """
        Initialize Observer with functionality previously in MetaObserver.dopreinit
        """
        # Initialize parent first
        super(Observer, self).__init__(*args, **kwargs)

        # Handle _stclock functionality (previously in MetaObserver.dopreinit)
        if self._stclock:  # Change the clock if strategy wide observer
            self._clock = self._owner

    # An Observer is ideally always observing and that' why prenext calls next.
    # The behavior can be overriden by subclasses
    def prenext(self):
        self.next()

    # 注册analyzer
    def _register_analyzer(self, analyzer):
        self._analyzers.append(analyzer)

    def _start(self):
        # PERFORMANCE FIX: Ensure _owner is set before calling start()
        # This is a fallback for cases where findowner didn't find the strategy during __init__
        if not hasattr(self, "_owner") or self._owner is None:
            # Try to get owner from _parent (set by strategy when adding observer)
            if hasattr(self, "_parent") and self._parent is not None:
                self._owner = self._parent

        self.start()

    def start(self):
        pass
