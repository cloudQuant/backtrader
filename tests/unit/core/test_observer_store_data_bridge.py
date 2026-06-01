"""Unit tests for forwarding store/data notifications to observers."""

import backtrader as bt


class RecordingObserver:
    """Collect forwarded observer runtime notifications."""

    def __init__(self):
        self.store_events = []
        self.data_events = []

    def notify_store_event(self, msg, *args, **kwargs):
        self.store_events.append((msg, args, kwargs))

    def notify_data_event(self, data, status, *args, **kwargs):
        self.data_events.append((data, status, args, kwargs))


class DummyStrategy:
    """Minimal strategy-shaped object for Cerebro notification tests."""

    _notify_store_to_observers = bt.Strategy._notify_store_to_observers
    _notify_data_to_observers = bt.Strategy._notify_data_to_observers

    def __init__(self, observer):
        self.stats = [observer]
        self.store_calls = []
        self.data_calls = []

    def notify_store(self, msg, *args, **kwargs):
        self.store_calls.append((msg, args, kwargs))

    def notify_data(self, data, status, *args, **kwargs):
        self.data_calls.append((data, status, args, kwargs))


class DummyStore:
    """Minimal store wrapper that serves queued notifications once."""

    def __init__(self, notifications):
        self._notifications = list(notifications)

    def get_notifications(self):
        items = list(self._notifications)
        self._notifications = []
        return items


class DummyData:
    """Minimal data feed wrapper that serves queued notifications once."""

    _NOTIFNAMES = ["CONNECTED", "DISCONNECTED", "CONNBROKEN", "DELAYED", "LIVE"]

    def __init__(self, notifications):
        self._notifications = list(notifications)
        self._name = "rb2610"

    def get_notifications(self):
        items = list(self._notifications)
        self._notifications = []
        return items


def test_cerebro_storenotify_forwards_to_strategy_and_observer():
    """Store runtime events should reach both strategy hooks and observer hooks."""
    observer = RecordingObserver()
    strategy = DummyStrategy(observer)
    store = DummyStore(
        [("runtime_event", (), {"event": {"event_type": "store_connected", "level": "INFO"}})]
    )
    cerebro = bt.Cerebro()
    cerebro.stores = [store]
    cerebro.runningstrats = [strategy]

    cerebro._storenotify()

    assert strategy.store_calls[0][0] == "runtime_event"
    assert observer.store_events[0][0] == "runtime_event"
    assert observer.store_events[0][2]["event"]["event_type"] == "store_connected"


def test_cerebro_datanotify_forwards_to_strategy_and_observer():
    """Data status events should reach both strategy hooks and observer hooks."""
    observer = RecordingObserver()
    strategy = DummyStrategy(observer)
    data = DummyData([(4, (), {"source": "live"})])
    cerebro = bt.Cerebro()
    cerebro.datas = [data]
    cerebro.runningstrats = [strategy]

    cerebro._datanotify()

    assert strategy.data_calls[0][0] is data
    assert strategy.data_calls[0][1] == 4
    assert observer.data_events[0][0] is data
    assert observer.data_events[0][1] == 4
