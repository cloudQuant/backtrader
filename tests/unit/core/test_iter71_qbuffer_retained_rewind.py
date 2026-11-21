"""A retained future slot can be rewound after a bounded buffer fills."""

import pytest

from backtrader.linebuffer import LineBuffer


@pytest.mark.parametrize("period", [1, 3, 7])
def test_rewind_retained_slot_at_capacity(period):
    line = LineBuffer()
    line._minperiod = period
    line.qbuffer(extrasize=1)
    for value in range(period + 5):
        line.forward(value=float(value))
    last = float(period + 4)
    assert line[0] == last
    count = len(line)
    line.rewind()
    assert len(line) == count - 1
    assert line[0] == last - 1.0
    assert line[1] == last
    line.advance()
    assert len(line) == count
    assert line[0] == last

@pytest.mark.parametrize("extra", [0, 1])
def test_rewind_preserves_subclass_set_idx_dispatch(extra):
    class CustomLine(LineBuffer):
        def set_idx(self, idx):
            raise AssertionError("the inherited idx property does not call this")

    line = CustomLine()
    line._minperiod = 3
    line.qbuffer(extrasize=extra)
    for value in range(8):
        line.forward(value=float(value))
    line.rewind()
    assert len(line) == 7
    if extra:
        assert line[0] == 6.0
        assert line[1] == 7.0


@pytest.mark.parametrize("extra", [0, 1])
def test_rewind_preserves_overridden_idx_property(extra):
    class CustomLine(LineBuffer):
        @property
        def idx(self):
            return LineBuffer.idx.fget(self)

        @idx.setter
        def idx(self, value):
            self.writes.append(value)
            LineBuffer.idx.fset(self, value)

        def __init__(self):
            self.writes = []
            super().__init__()

    line = CustomLine()
    line._minperiod = 3
    line.qbuffer(extrasize=extra)
    for value in range(8):
        line.forward(value=float(value))
    before = len(line.writes)
    current = line.idx
    line.rewind()
    assert line.writes[before:] == [current - 1]
    assert len(line) == 7
