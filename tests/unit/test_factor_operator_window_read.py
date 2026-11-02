"""Focused contracts for the standard LineBuffer research window reader."""

import array
import math
import struct

import pytest

import backtrader.research.operators as operators
from backtrader.errors import FactorComputationContext, FactorComputationError
from backtrader.linebuffer import LineBuffer
from backtrader.lineiterator import LineIteratorMixin
from backtrader.research.operators import OperatorInputError, OperatorReason


def _line(values):
    line = LineBuffer()
    line.array = array.array("d", values)
    line.lencount = len(values)
    line._idx = len(values) - 1
    return line


def _bits(value):
    return struct.pack("=d", value)


def test_standard_unbounded_linebuffer_reads_one_ordered_array_window(monkeypatch):
    values = [-0.0, math.ulp(0.0), 1.25, -3.5]
    line = _line(values)

    def scalar_read_forbidden(*args, **kwargs):
        raise AssertionError("eligible LineBuffer used the scalar reader")

    monkeypatch.setattr(operators, "_read_operand", scalar_read_forbidden)
    actual, reason = operators._read_window(line, len(values))

    assert reason is OperatorReason.READY
    assert [_bits(value) for value in actual] == [_bits(value) for value in values]


def test_window_clamps_an_index_past_the_logical_end():
    line = _line([1.0, 2.0, 3.0, 99.0])
    line.lencount = 3
    line._idx = 20

    actual, reason = operators._read_window(line, 2)

    assert actual == [2.0, 3.0]
    assert reason is OperatorReason.READY


def test_window_uses_the_current_array_after_reset():
    line = _line([1.0, 2.0, 3.0])
    prior_array = line.array

    line.reset()
    assert line.array is not prior_array
    line.array.extend([8.0, 9.0])
    line.lencount = 2
    line._idx = 1

    actual, reason = operators._read_window(line, 2)

    assert actual == [8.0, 9.0]
    assert reason is OperatorReason.READY


def test_subclass_and_qbuffer_keep_the_scalar_fallback():
    class CustomLine(LineBuffer):
        def __init__(self):
            super().__init__()
            self.reads = 0

        def __getitem__(self, ago):
            self.reads += 1
            return super().__getitem__(ago)

    custom = CustomLine()
    custom.array = array.array("d", [2.0, 4.0, 6.0])
    custom.lencount = 3
    custom._idx = 2
    assert operators._read_window(custom, 3) == ([2.0, 4.0, 6.0], OperatorReason.READY)
    assert custom.reads == 3

    queued = _line([1.0, 3.0])
    queued._minperiod = 2
    queued.qbuffer()
    queued.array.extend([1.0, 3.0])
    queued.lencount = 2
    queued._idx = 1
    assert operators._read_window(queued, 2) == ([1.0, 3.0], OperatorReason.READY)


@pytest.mark.parametrize("method_name", ["__getattribute__", "__len__", "__getitem__"])
def test_linebuffer_special_method_replacement_disables_fast_path(monkeypatch, method_name):
    line = _line([5.0, 7.0])
    original = getattr(LineBuffer, method_name)
    calls = []

    if method_name == "__getattribute__":

        def tracked(self, name):
            calls.append(name)
            return original(self, name)

    elif method_name == "__len__":

        def tracked(self):
            calls.append("len")
            return original(self)

    else:

        def tracked(self, ago):
            calls.append(ago)
            return original(self, ago)

    monkeypatch.setattr(LineBuffer, method_name, tracked)
    assert operators._read_window(line, 2) == ([5.0, 7.0], OperatorReason.READY)
    assert calls


def test_nan_calls_reason_lookup_at_its_absolute_index_and_stops_in_order(monkeypatch):
    line = _line([1.0, float("nan"), float("inf")])
    calls = []
    monkeypatch.setattr(
        operators,
        "_associated_reason",
        lambda source, *, absolute_index: calls.append(absolute_index),
    )

    assert operators._read_window(line, 3) == (None, OperatorReason.INCOMPLETE_WINDOW)
    assert calls == [1]


def test_infinity_before_nan_raises_before_reason_lookup(monkeypatch):
    line = _line([float("inf"), float("nan")])
    calls = []
    monkeypatch.setattr(
        operators,
        "_associated_reason",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(OperatorInputError, match="source line contains infinity"):
        operators._read_window(line, 2)
    assert calls == []


def test_reason_lookup_failures_are_not_suppressed(monkeypatch):
    line = _line([1.0, float("nan")])
    failure = LookupError("reason lookup failed")

    def fail_reason_lookup(*args, **kwargs):
        raise failure

    monkeypatch.setattr(operators, "_associated_reason", fail_reason_lookup)
    with pytest.raises(LookupError) as caught:
        operators._read_window(line, 2)
    assert caught.value is failure


def test_infinity_keeps_strict_factor_and_asset_error_attribution():
    line = _line([1.0, float("inf")])
    context = FactorComputationContext("alpha003")

    class CallbackOwner(LineIteratorMixin):
        def __init__(self, strict_context):
            self._factor_strict_context = strict_context

    owner = CallbackOwner(context)
    context.bind_object(owner, "asset-A")

    with pytest.raises(FactorComputationError) as caught:
        owner._factor_run_callback(lambda: operators._read_window(line, 2), "once")

    error = caught.value
    assert isinstance(error.__cause__, OperatorInputError)
    assert error.factor == "alpha003"
    assert error.asset == "asset-A"
    assert error.phase == "once"
    assert context.failed is True
