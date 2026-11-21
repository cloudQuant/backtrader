"""Clock updates retain their source-resolution behavior under live changes."""

import weakref

from backtrader.linebuffer import LineActions
from backtrader.lineiterator import LineIterator


class _Clock:
    def __init__(self, length):
        self.length = length

    def __len__(self):
        return self.length


class _Iterator:
    def __init__(self, data, clock):
        self.datas = [data]
        self._clock = clock
        self.length = 0

    def __len__(self):
        return self.length

    def forward(self):
        self.length += 1


def test_valid_source_clock_does_not_require_lines_descriptor():
    class Data:
        def __init__(self, clock):
            self._clock = clock

        @property
        def lines(self):
            raise RuntimeError("the valid direct source clock does not need lines")

    clock = _Clock(1)
    obj = _Iterator(Data(clock), _Clock(0))

    assert LineIterator._clk_update(obj) == 1
    assert obj._clock is clock
    assert len(obj) == 1


def test_replaced_nested_lineaction_clock_after_action_cache_invalidation():
    class Data:
        def __init__(self, action):
            self._clock = action
            self.lines = []

    action = object.__new__(LineActions)
    original, replacement = _Clock(1), _Clock(2)
    action.__dict__["_clock"] = original
    obj = _Iterator(Data(action), _Clock(0))
    assert LineIterator._clk_update(obj) == 1
    assert obj._clock is original

    action.__dict__["_clock"] = replacement
    action.__dict__.pop("_lineaction_source_clock_cache", None)

    assert LineIterator._clk_update(obj) == 2
    assert obj._clock is replacement
    assert len(obj) == 2


def test_direct_clock_descriptor_is_read_once_and_lines_never_read():
    reads = []
    clock = _Clock(1)

    class Data:
        @property
        def _clock(self):
            reads.append("clock")
            return clock

        @property
        def lines(self):
            reads.append("lines")
            raise AssertionError("lines should not be read")

    obj = _Iterator(Data(), _Clock(0))
    assert LineIterator._clk_update(obj) == 1
    assert reads == ["clock"]


def test_replacing_lines_changes_fallback_source_clock():
    class Line:
        def __init__(self, clock):
            self._clock = clock

    class Data:
        _clock = None

        def __init__(self, line):
            self.lines = [line]

    first, replacement = _Clock(1), _Clock(2)
    data = Data(Line(first))
    obj = _Iterator(data, _Clock(0))
    assert LineIterator._clk_update(obj) == 1
    data.lines = [Line(replacement)]
    assert LineIterator._clk_update(obj) == 2
    assert obj._clock is replacement


def test_class_lines_descriptor_can_change_after_first_update():
    class Data:
        def __init__(self, clock):
            self._clock = clock
            self.lines = [self]

    first, replacement = _Clock(1), _Clock(2)
    data = Data(first)
    obj = _Iterator(data, _Clock(0))
    assert LineIterator._clk_update(obj) == 1

    def broken_lines(_self):
        raise RuntimeError("a valid direct clock does not read lines")

    Data.lines = property(broken_lines)
    data._clock = replacement
    assert LineIterator._clk_update(obj) == 2
    assert obj._clock is replacement


def test_empty_datas_preserves_existing_cache_shaped_state():
    obj = _Iterator(None, _Clock(0))
    obj.datas = []

    class Sentinel:
        def __init__(self, owner):
            self.owner = weakref.ref(owner)

        def __del__(self):
            owner = self.owner()
            if owner is not None:
                owner._clock = _Clock(7)

    obj.__dict__["_bt_clk_update_cache"] = (Sentinel(obj), None, None, None, None, None, 0)
    assert LineIterator._clk_update(obj) == 0
    assert LineIterator._clk_update(obj) == 0
    assert isinstance(obj.__dict__["_bt_clk_update_cache"][0], Sentinel)
