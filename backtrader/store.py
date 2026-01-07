#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Store Module - Data storage and broker connection management.

This module provides base classes for Store implementations, which manage
connections to external data sources and brokers. It includes singleton
pattern support and parameter management for store classes.

Classes:
    SingletonMixin: Mixin class to implement singleton pattern.
    StoreParams: Parameter management for Store classes.
    Store: Base class for all Store implementations.

Example:
    Using a store to get data and broker:
    >>> store = bt.observers.backends.ViStore()
    >>> data = store.getdata()
    >>> broker = store.getbroker()
"""
import collections

# Remove MetaParams import since we'll eliminate metaclass usage
# from backtrader.metabase import MetaParams


# Simple singleton implementation without metaclass
class SingletonMixin(object):
    """Mixin class to make a class a singleton without using metaclasses.

    This mixin ensures only one instance of the class exists. The instance
    is created on first instantiation and reused on subsequent calls.
    """

    def __new__(cls, *args, **kwargs):
        """Create and return the singleton instance.

        Args:
            *args: Positional arguments passed to the class constructor.
            **kwargs: Keyword arguments passed to the class constructor.

        Returns:
            SingletonMixin: The single instance of this class.
        """
        if not hasattr(cls, "_singleton"):
            cls._singleton = super(SingletonMixin, cls).__new__(cls)
            cls._singleton._initialized = False
        return cls._singleton

    def __init__(self, *args, **kwargs):
        """Initialize the singleton instance only once.

        Args:
            *args: Positional arguments passed to the parent __init__.
            **kwargs: Keyword arguments passed to the parent __init__.

        Note:
            If the singleton has already been initialized, this method
            returns immediately without reinitializing.
        """
        if self._initialized:
            return
        self._initialized = True
        # Call the original __init__ if it exists
        super(SingletonMixin, self).__init__(*args, **kwargs)


# Store parameter management
class StoreParams(object):
    """Simple parameter management for Store classes.

    This class provides automatic parameter initialization from the
    class-level params tuple, creating a self.p attribute with
    all parameter values.
    """

    def __init__(self):
        """Initialize parameters from the class-level params tuple.

        Parses the params tuple defined at class level and creates
        a self.p object with all parameter values as attributes.
        """
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


# Store base class
class Store(SingletonMixin, StoreParams):
    """Base class for all Stores.

    Stores manage connections to external data sources and brokers.
    They provide data feeds and broker instances, and handle
    notifications from the external service.

    Attributes:
        _started: Whether the store has been started.
        params: Tuple of parameter definitions.
        broker: The broker instance associated with this store.
        BrokerCls: The broker class to use (None by default).
        DataCls: The data class to use (None by default).
    """

    # Started, defaults to False
    _started = False
    # Parameters
    params = ()

    # Get data
    def __init__(self):
        """Initialize the Store instance.

        Sets up internal state for broker, environment, cerebro,
        data sources, and notifications.
        """
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

    # Get broker
    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        broker = cls.BrokerCls(*args, **kwargs)
        broker._store = cls
        return broker

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    # Start
    def start(self, data=None, broker=None):
        """Start the store and initialize connections.

        Args:
            data: Data feed to register with the store (optional).
            broker: Broker instance to register with the store (optional).

        Note:
            On first call, initializes the notification queue and data list.
            Subsequent calls can add data feeds or set the broker.
        """
        # If not started yet, initialize
        if not self._started:
            self._started = True
            self.notifs = collections.deque()
            self.datas = list()
            self.broker = None
        # If data is not None
        if data is not None:
            self._cerebro = self._env = data._env
            self.datas.append(data)
            # If self.broker is not None
            if self.broker is not None:
                if hasattr(self.broker, "data_started"):
                    self.broker.data_started(data)
        # If broker is not None
        elif broker is not None:
            self.broker = broker

    # End
    def stop(self):
        """Stop the store and clean up resources.

        This method should be overridden by subclasses to perform
        any necessary cleanup.
        """

    # Add message to notifications
    def put_notification(self, msg, *args, **kwargs):
        """Add a message to the notification queue.

        Args:
            msg: The notification message.
            *args: Additional positional arguments to store with the message.
            **kwargs: Additional keyword arguments to store with the message.
        """
        self.notifs.append((msg, args, kwargs))

    # Get notification message
    def get_notifications(self):
        """Return the pending "store" notifications"""
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]
