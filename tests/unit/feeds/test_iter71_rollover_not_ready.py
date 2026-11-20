"""Live rollover waits without consuming the active bar or spinning."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from backtrader.feeds.rollover import RollOver
from backtrader.utils import date2num


class Source:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = 0
        self.current = None
        self.datetime = SimpleNamespace(datetime=lambda: self.current[0])
        self.lines = SimpleNamespace()

    def next(self):
        self.calls += 1
        step = next(self.steps, False)
        if step is None or step is False:
            return step
        self.current = step
        dt, price = step
        self.lines.datetime = [date2num(dt)]
        for name in ("open", "high", "low", "close", "volume", "openinterest"):
            setattr(self.lines, name, [price])
        return True


def test_not_ready_preserves_active_bar_and_resumes_synchronization():
    start = datetime(2025, 1, 1)
    first = Source([None, (start, 100), (start + timedelta(days=1), 101), False])
    second = Source([None, (start, 200), (start + timedelta(days=1), 201), False])
    rollover = RollOver()
    rollover._d = first
    rollover._ds = [second]
    rollover._dts = [datetime.min]
    rollover._dexp = None
    rollover.forward()

    assert rollover._load() is None
    assert first.calls == 1 and second.calls == 0
    assert rollover._load() is None
    assert first.calls == 2 and second.calls == 1
    assert rollover._load() is True
    assert first.calls == 2 and rollover.close[0] == 100
    rollover.forward()
    assert rollover._load() is True
    assert rollover.close[0] == 101


def test_expired_feed_not_ready_does_not_discard_active_bar():
    start = datetime(2025, 1, 1)
    first = Source([(start, 100), (start + timedelta(days=1), 101)])
    expired = Source([None, (start, 90), None, (start + timedelta(days=1), 91)])
    rollover = RollOver()
    rollover._d = first
    rollover._ds = []
    rollover._dts = []
    rollover._dexp = expired
    rollover.forward()

    assert rollover._load() is None
    assert first.calls == 1 and expired.calls == 1
    assert rollover._load() is True
    assert first.calls == 1 and expired.calls == 2
    assert rollover.close[0] == 100
    rollover.forward()
    assert rollover._load() is None
    assert first.calls == 2 and expired.calls == 3
    assert rollover._load() is True
    assert first.calls == 2 and expired.calls == 4
    assert rollover.close[0] == 101


def test_exhausted_secondary_is_removed_without_spinning():
    start = datetime(2025, 1, 1)
    active = Source([(start, 100)])
    exhausted = Source([False])
    rollover = RollOver()
    rollover._d = active
    rollover._ds = [exhausted]
    rollover._dts = [datetime.min]
    rollover._dexp = None
    rollover.forward()

    assert rollover._load() is True
    assert rollover.close[0] == 100
    assert not rollover._ds and not rollover._dts
    assert exhausted.calls == 1


def test_feed_load_retries_without_losing_pending_bar():
    start = datetime(2025, 1, 1)
    active = Source([(start, 100), (start + timedelta(days=1), 101)])
    secondary = Source([None, (start, 200), (start + timedelta(days=1), 201)])
    rollover = RollOver()
    rollover._d = active
    rollover._ds = [secondary]
    rollover._dts = [datetime.min]
    rollover._dexp = None
    rollover._start_finish()

    assert rollover.load() is None
    assert len(rollover) == 0
    assert rollover.load() is True
    assert len(rollover) == 1 and rollover.close[0] == 100
    assert rollover.load() is True
    assert len(rollover) == 2 and rollover.close[0] == 101


def test_secondary_keeps_progress_before_not_ready():
    start = datetime(2025, 1, 1)
    active = Source([(start + timedelta(days=2), 100)])
    secondary = Source(
        [(start, 200), (start + timedelta(days=1), 201), None, (start + timedelta(days=2), 202)]
    )
    rollover = RollOver()
    rollover._d, rollover._ds = active, [secondary]
    rollover._dts, rollover._dexp = [datetime.min], None
    rollover.forward()

    assert rollover._load() is None
    assert active.calls == 1 and secondary.calls == 3
    assert rollover._dts == [start + timedelta(days=1)]
    assert rollover._load() is True
    assert active.calls == 1 and secondary.calls == 4
    assert rollover.close[0] == 100


def test_rollover_occurs_after_delayed_secondary_is_ready():
    start = datetime(2025, 1, 1)
    first = Source([(start, 100), None, (start + timedelta(days=1), 101)])
    second = Source([None, (start, 200), (start + timedelta(days=1), 201)])
    calls = []
    rollover = RollOver(
        checkdate=lambda dt, data: True,
        checkcondition=lambda old, new: calls.append((old, new)) or True,
    )
    rollover._d, rollover._ds = first, [second]
    rollover._dts, rollover._dexp = [datetime.min], None
    rollover.forward()

    assert rollover._load() is None
    assert rollover._load() is True
    assert rollover.close[0] == 200 and calls == [(first, second)]
    rollover.forward()
    assert rollover._load() is None
    assert rollover._load() is True
    assert rollover.close[0] == 201 and calls == [(first, second)]
