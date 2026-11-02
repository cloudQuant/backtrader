#!/usr/bin/env python
"""Store base classes.

Store provides per-instance state and lifecycle helpers for store
implementations. LiveStoreBase builds on it as the contract for live
stores. Store instances do not impose singleton behavior.

Classes:
    StoreParams: Parameter management for Store classes.
    Store: Per-instance base class for Store implementations.

Example:
    Using a store to get data and broker:
    >>> store = bt.observers.backends.ViStore()
    >>> data = store.getdata()
    >>> broker = store.getbroker()
"""

import collections
from typing import Any, Optional

# Keep the generic mixin import path; Store itself does not inherit it.
from .mixins.singleton import SingletonMixin
from .parameters import make_legacy_parameter_accessor

# Remove MetaParams import since we'll eliminate metaclass usage
# from backtrader.metabase import MetaParams


# Store parameter management
class StoreParams:
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
        params = getattr(self.__class__, "params", ())
        self.p = make_legacy_parameter_accessor(params, name=f"{self.__class__.__name__}Params")


# Store base class
class Store(StoreParams):
    """Per-instance base class for store implementations.

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

    # Default retained for subclasses that inspect the class before instance
    # initialization. Each Store instance receives its own value in __init__.
    _started = False
    params = ()
    BrokerCls: Any = None  # broker class registered by a concrete Store
    DataCls: Any = None  # feed class registered by a concrete Store

    def __init__(self):
        """Initialize parameters and per-instance Store lifecycle state."""
        super().__init__()
        self._started = False
        self.broker = None
        self._env = None
        self._cerebro = None
        self.datas: Optional[list] = None
        self.notifs: Optional[collections.deque] = None

    def getdata(self, *args, **kwargs):
        """Construct the configured feed and bind it to this Store instance."""
        if self.DataCls is None:
            raise NotImplementedError("A concrete Store must provide DataCls or override getdata")
        data = self.DataCls(*args, **kwargs)
        data._store = self
        return data

    def getbroker(self, *args, **kwargs):
        """Construct the configured broker and bind it to this Store instance."""
        if self.BrokerCls is None:
            raise NotImplementedError(
                "A concrete Store must provide BrokerCls or override getbroker"
            )
        broker = self.BrokerCls(*args, **kwargs)
        broker._store = self
        return broker

    def start(self, data=None, broker=None):
        """Register Store participants and initialize common lifecycle state.

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
            self.datas = []
            self.broker = None
        # If data is not None
        if data is not None:
            self._cerebro = self._env = data._env
            if self.datas is None:  # defensive: start() initializes this
                self.datas = []
            self.datas.append(data)
            # If self.broker is not None
            if self.broker is not None:
                if hasattr(self.broker, "data_started"):
                    self.broker.data_started(data)
        # If broker is not None
        elif broker is not None:
            self.broker = broker

    def stop(self):
        """Stop the Store.

        Concrete stores with resources to release should override this hook.
        """

    def put_notification(self, msg, *args, **kwargs):
        """Add a message to the notification queue.

        Args:
            msg: The notification message.
            *args: Additional positional arguments to store with the message.
            **kwargs: Additional keyword arguments to store with the message.
        """
        if self.notifs is None:
            self.notifs = collections.deque()
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        """Return the pending "store" notifications"""
        if self.notifs is None:
            return []
        self.notifs.append(None)  # put a mark / threads could still append
        return list(iter(self.notifs.popleft, None))
