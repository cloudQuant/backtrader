"""Bounded QBuffer window reads must match the scalar logical-grid reader."""

import pytest

import backtrader.research.operators as operators
from backtrader.linebuffer import LineBuffer
from backtrader.research.operators import OperatorInputError, OperatorReason


def _queued_line(values, capacity, *, extrasize=0, line_type=LineBuffer):
    line = line_type()
    line._minperiod = capacity
    line.qbuffer(extrasize=extrasize)
    for value in values:
        line.forward()
        line[0] = value
    return line


def _force_scalar_window(monkeypatch, source, period):
    with monkeypatch.context() as patch:
        patch.setattr(
            operators,
            "_try_read_qbuffer_linebuffer_window",
            lambda *_args, **_kwargs: operators._FAST_WINDOW_MISS,
        )
        return operators._read_window(source, period)


def _assert_same_window(actual, expected):
    assert actual[1] is expected[1]
    if actual[0] is None or expected[0] is None:
        assert actual[0] is expected[0]
    else:
        assert actual[0] == expected[0]


@pytest.mark.parametrize(
    ("capacity", "period"),
    ((1, 1), (4, 3), (5, 5), (11, 7), (7, 9)),
)
def test_qbuffer_window_matches_scalar_after_many_deque_wraps(monkeypatch, capacity, period):
    rows = 512
    source = _queued_line(range(rows), capacity)
    scalar_reads = []
    read_operand = operators._read_operand

    def count_scalar_reads(line, ago=0):
        scalar_reads.append(ago)
        return read_operand(line, ago)

    monkeypatch.setattr(operators, "_read_operand", count_scalar_reads)
    fast = operators._read_window(source, period)
    fast_read_count = len(scalar_reads)
    scalar_reads.clear()
    scalar = _force_scalar_window(monkeypatch, source, period)

    _assert_same_window(fast, scalar)
    if capacity >= period:
        assert fast == (list(range(rows - period, rows)), OperatorReason.READY)
        assert fast_read_count == 0
        assert len(scalar_reads) == period
    else:
        assert fast == (None, OperatorReason.INCOMPLETE_WINDOW)
        assert fast_read_count > 0
        assert len(scalar_reads) > 0


def test_qbuffer_window_reads_own_reason_tail_with_different_capacity(monkeypatch):
    source = _queued_line(range(64), capacity=9)
    reasons = _queued_line(
        [float(OperatorReason.READY)] * 64,
        capacity=2,
    )
    source.array[-1] = float("nan")
    reasons.array[-1] = float(OperatorReason.DOMAIN_ERROR)
    source._factor_research_reason_line = reasons

    observed = []
    associated_reason = operators._associated_reason

    def record_reason(line, *, absolute_index):
        result = associated_reason(line, absolute_index=absolute_index)
        observed.append((absolute_index, result))
        return result

    monkeypatch.setattr(operators, "_associated_reason", record_reason)
    fast = operators._read_window(source, 7)
    assert fast == (None, OperatorReason.INCOMPLETE_WINDOW)
    assert observed == [(63, OperatorReason.DOMAIN_ERROR)]

    observed.clear()
    scalar = _force_scalar_window(monkeypatch, source, 7)
    assert scalar == fast
    assert observed == [(63, OperatorReason.DOMAIN_ERROR)]


def test_qbuffer_window_preserves_first_invalid_order_and_reason_failures(monkeypatch):
    source = _queued_line([1.0, 2.0, 3.0], capacity=3)
    source.array[1] = float("nan")
    source.array[2] = float("inf")
    reason_calls = []
    monkeypatch.setattr(
        operators,
        "_associated_reason",
        lambda line, *, absolute_index: reason_calls.append(absolute_index),
    )

    assert operators._read_window(source, 3) == (
        None,
        OperatorReason.INCOMPLETE_WINDOW,
    )
    assert reason_calls == [1]

    source.array[0] = float("inf")
    reason_calls.clear()
    with pytest.raises(OperatorInputError, match="source line contains infinity"):
        operators._read_window(source, 3)
    assert reason_calls == []

    source.array[0] = 1.0
    lookup_error = LookupError("reason lookup failed")

    def fail_reason_lookup(*_args, **_kwargs):
        raise lookup_error

    monkeypatch.setattr(operators, "_associated_reason", fail_reason_lookup)
    with pytest.raises(LookupError) as caught:
        operators._read_window(source, 3)
    assert caught.value is lookup_error


def test_qbuffer_window_matches_scalar_after_rewind_backwards_reset_and_extension(
    monkeypatch,
):
    source = _queued_line(range(80), capacity=8)

    source.rewind(3)
    _assert_same_window(
        operators._read_window(source, 5),
        _force_scalar_window(monkeypatch, source, 5),
    )

    source.backwards(2)
    _assert_same_window(
        operators._read_window(source, 4),
        _force_scalar_window(monkeypatch, source, 4),
    )

    source.extend(float("nan"), size=2)
    _assert_same_window(
        operators._read_window(source, 4),
        _force_scalar_window(monkeypatch, source, 4),
    )

    source.reset()
    assert operators._read_window(source, 3) == (None, OperatorReason.NOT_READY)
    for value in (901.0, 902.0, 903.0, 904.0, 905.0, 906.0):
        source.forward()
        source[0] = value
    assert operators._read_window(source, 4) == (
        [903.0, 904.0, 905.0, 906.0],
        OperatorReason.READY,
    )


@pytest.mark.parametrize("override", ("subclass", "getitem", "len"))
def test_nonstandard_qbuffer_uses_scalar_fallback(monkeypatch, override):
    if override == "subclass":

        class CustomLineBuffer(LineBuffer):
            pass

        source = _queued_line(range(16), capacity=6, line_type=CustomLineBuffer)
    else:
        source = _queued_line(range(16), capacity=6)
        method_name = "__getitem__" if override == "getitem" else "__len__"
        original = getattr(LineBuffer, method_name)

        if method_name == "__getitem__":

            def wrapped(self, ago):
                return original(self, ago)

        else:

            def wrapped(self):
                return original(self)

        monkeypatch.setattr(LineBuffer, method_name, wrapped)

    scalar_reads = []
    read_operand = operators._read_operand

    def count_scalar_reads(line, ago=0):
        scalar_reads.append(ago)
        return read_operand(line, ago)

    monkeypatch.setattr(operators, "_read_operand", count_scalar_reads)
    result = operators._read_window(source, 4)

    assert result == ([12.0, 13.0, 14.0, 15.0], OperatorReason.READY)
    assert scalar_reads == [-3, -2, -1, 0]


def test_qbuffer_fast_path_requires_exact_deque_storage(monkeypatch):
    source = _queued_line(range(16), capacity=6)
    source.array = list(source.array)
    scalar_reads = []
    read_operand = operators._read_operand

    def count_scalar_reads(line, ago=0):
        scalar_reads.append(ago)
        return read_operand(line, ago)

    monkeypatch.setattr(operators, "_read_operand", count_scalar_reads)
    assert operators._read_window(source, 4) == (
        [12.0, 13.0, 14.0, 15.0],
        OperatorReason.READY,
    )
    assert scalar_reads == [-3, -2, -1, 0]


def test_qbuffer_custom_cell_conversion_uses_scalar_fallback(monkeypatch):
    class FloatCell:
        def __init__(self, value):
            self.value = value
            self.conversions = 0

        def __float__(self):
            self.conversions += 1
            return self.value

    source = _queued_line(range(8), capacity=6)
    cell = FloatCell(99.0)
    source.array[-1] = cell
    scalar_reads = []
    read_operand = operators._read_operand

    def count_scalar_reads(line, ago=0):
        scalar_reads.append(ago)
        return read_operand(line, ago)

    monkeypatch.setattr(operators, "_read_operand", count_scalar_reads)
    assert operators._read_window(source, 4) == (
        [4.0, 5.0, 6.0, 99.0],
        OperatorReason.READY,
    )
    assert scalar_reads == [-3, -2, -1, 0]
    assert cell.conversions == 1


def test_short_window_traverses_only_qbuffer_tail_and_extension(monkeypatch):
    capacity = 4096
    extension = 2
    period = 7
    rows = capacity
    source = _queued_line(range(rows), capacity=capacity, extrasize=5)
    source.extend(12345.0, size=extension)

    original_islice = operators._islice
    observed = {}

    class CountingIterator:
        def __init__(self, source_iterator):
            self._iterator = source_iterator
            self.next_calls = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.next_calls += 1
            return next(self._iterator)

    def counted_islice(iterable, start, stop=None):
        counting = CountingIterator(iterable)
        observed["iterator"] = counting
        observed["start"] = start
        observed["stop"] = stop
        return original_islice(counting, start, stop)

    monkeypatch.setattr(operators, "_islice", counted_islice)
    assert operators._read_window(source, period) == (
        [float(value) for value in range(rows - period, rows)],
        OperatorReason.READY,
    )
    assert observed["start"] == extension
    assert observed["stop"] == extension + period
    assert observed["iterator"].next_calls == extension + period
    assert observed["iterator"].next_calls < capacity // 100
