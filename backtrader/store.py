#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import collections

# Remove MetaParams import since we'll eliminate metaclass usage
# from backtrader.metabase import MetaParams


# Simple singleton implementation without metaclass
class SingletonMixin(object):
    """Mixin class to make a class a singleton without using metaclasses"""

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "_singleton"):
            cls._singleton = super(SingletonMixin, cls).__new__(cls)
            cls._singleton._initialized = False
        return cls._singleton

    def __init__(self, *args, **kwargs):
        if self._initialized:
            return
        self._initialized = True
        # Call the original __init__ if it exists
        super(SingletonMixin, self).__init__(*args, **kwargs)


# Store parameter management
class StoreParams(object):
    """Simple parameter management for Store classes"""

    def __init__(self):
        # Initialize parameters from the class-level params tuple
        self.p = type("Params", (), {})()
        params = getattr(self.__class__, "params", ())

        # Set default values from params tuple
        for param in params:
            if isinstance(param, tuple) and len(param) >= 2:
                name, default_value = param[0], param[1]
                setattr(self.p, name, default_value)
            elif isinstance(param, str):
                setattr(self.p, param, None)


# Store基类
class Store(SingletonMixin, StoreParams):
    """Base class for all Stores"""

    # 开始，默认是False
    _started = False
    # 参数
    params = ()

    # 获取数据
    def __init__(self):
        super(Store, self).__init__()
        self.broker = None
        self._env = None
        self._cerebro = None
        self.datas = None
        self.notifs = None

    def getdata(self, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        data = self.DataCls(*args, **kwargs)
        data._store = self
        return data

    # 获取broker
    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        broker = cls.BrokerCls(*args, **kwargs)
        broker._store = cls
        return broker

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    # 开始
    def start(self, data=None, broker=None):
        # 如果还没有开始，就初始化
        if not self._started:
            self._started = True
            self.notifs = collections.deque()
            self.datas = list()
            self.broker = None
        # 如果数据不是None
        if data is not None:
            self._cerebro = self._env = data._env
            self.datas.append(data)
            # 如果self.broker不是None的话
            if self.broker is not None:
                if hasattr(self.broker, "data_started"):
                    self.broker.data_started(data)
        # 如果broker不是None的话
        elif broker is not None:
            self.broker = broker

    # 结束
    def stop(self):
        pass

    # 把信息添加到通知
    def put_notification(self, msg, *args, **kwargs):
        self.notifs.append((msg, args, kwargs))

    # 获取通知的信息
    def get_notifications(self):
        """Return the pending "store" notifications"""
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]
