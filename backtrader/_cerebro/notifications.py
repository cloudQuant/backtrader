"""Cerebro notification dispatch mixin (iteration 28 split).

Moved verbatim from ``backtrader/cerebro.py``: store/data callbacks and
broker notification delivery.
"""

from ..brokers import BackBroker
from ..feed import AbstractDataBase


class NotificationMixin:
    """Notification dispatch half of Cerebro (see module docstring)."""

    def addstorecb(self, callback):
        """Adds a callback to get messages which would be handled by the
        notify_store method

        The signature of the callback must support the following:

          - callback(msg, *args, *kwargs)

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        """
        self.storecbs.append(callback)

    def _notify_store(self, msg, *args, **kwargs):
        """Internal method to dispatch store notifications."""
        for callback in self.storecbs:
            callback(msg, *args, **kwargs)

        self.notify_store(msg, *args, **kwargs)

    def notify_store(self, msg, *args, **kwargs):
        """Receive store notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        """

    def _storenotify(self):
        """Process and dispatch store notifications to strategies."""
        for store in self.stores:
            for notif in store.get_notifications():
                msg, args, kwargs = notif

                self._notify_store(msg, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.notify_store(msg, *args, **kwargs)
                    if hasattr(strat, "_notify_store_to_observers"):
                        strat._notify_store_to_observers(msg, *args, **kwargs)

    def adddatacb(self, callback):
        """Adds a callback to get messages which would be handled by the
        notify_data method

        The signature of the callback must support the following:

          - callback(data, status, *args, *kwargs)

        The actual ``*args`` and ``**kwargs`` received are implementation
        defined (depend entirely on the *data/broker/store*), but in general one
        should expect them to be *printable* to allow for reception and
        experimentation.
        """
        self.datacbs.append(callback)

    def _datanotify(self):
        """Process and dispatch data notifications to strategies."""
        for data in self.datas:
            if type(data).get_notifications is AbstractDataBase.get_notifications:
                notifications = data.notifs
                if not notifications:
                    continue

                notifications.append(None)
                while True:
                    notif = notifications.popleft()
                    if notif is None:
                        break
                    status, args, kwargs = notif
                    self._notify_data(data, status, *args, **kwargs)
                    for strat in self.runningstrats:
                        strat.notify_data(data, status, *args, **kwargs)
                        if hasattr(strat, "_notify_data_to_observers"):
                            strat._notify_data_to_observers(data, status, *args, **kwargs)
            else:
                for notif in data.get_notifications():
                    status, args, kwargs = notif
                    self._notify_data(data, status, *args, **kwargs)
                    for strat in self.runningstrats:
                        strat.notify_data(data, status, *args, **kwargs)
                        if hasattr(strat, "_notify_data_to_observers"):
                            strat._notify_data_to_observers(data, status, *args, **kwargs)

    def _notify_data(self, data, status, *args, **kwargs):
        """Internal method to dispatch data notifications."""
        for callback in self.datacbs:
            callback(data, status, *args, **kwargs)

        self.notify_data(data, status, *args, **kwargs)

    def notify_data(self, data, status, *args, **kwargs):
        """Receive data notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker/store*), but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        """

    # Notify broker info
    def _brokernotify(self):
        """
        Internal method which kicks the broker and delivers any broker
        notification to the strategy
        """
        # Call broker's next
        broker = self._broker
        broker.next()
        if type(broker).get_notification is BackBroker.get_notification:
            notifications = broker.notifs
            while notifications:
                order = notifications.popleft()
                owner = order.owner
                if owner is None:
                    owner = self.runningstrats[0]  # default
                # Notify order info through first strategy
                owner._addnotification(order, quicknotify=self.p.quicknotify)
        else:
            while True:
                # Get order info to notify, if order is None break loop, otherwise get order's owner.
                # If owner is None, default to first strategy
                order = broker.get_notification()
                if order is None:
                    break

                owner = order.owner
                if owner is None:
                    owner = self.runningstrats[0]  # default
                # Notify order info through first strategy
                owner._addnotification(order, quicknotify=self.p.quicknotify)
