"""N72-17 B004 compatibility boundaries for callable-like line objects."""

from __future__ import annotations

import pytest

import backtrader as bt
from backtrader.linebuffer import LineBuffer
from backtrader.lineiterator import LineIterator, StrategyBase
from backtrader.lineseries import Lines


class _CallDescriptorFailure(RuntimeError):
    pass


class _PseudoCallIterable:
    """Iterable with an instance-visible ``__call__`` descriptor only."""

    def __init__(self, trace, *, error=None):
        self.trace = trace
        self.error = error

    @property
    def __call__(self):
        self.trace.append("call-lookup")
        if self.error is not None:
            raise self.error
        return object()

    def __iter__(self):
        self.trace.append("iter")
        return iter((3.0, 4.0))


def test_lines_assignment_keeps_pseudo_call_iterable_as_line_object():
    trace = []
    value = _PseudoCallIterable(trace)
    lines = Lines()
    lines.lines.append(LineBuffer())

    lines[0] = value

    assert lines.lines[0] is value
    assert trace == ["call-lookup"]


def test_lines_assignment_propagates_call_descriptor_error_before_iteration():
    trace = []
    failure = _CallDescriptorFailure("call descriptor failed")
    value = _PseudoCallIterable(trace, error=failure)
    lines = Lines()
    lines.lines.append(LineBuffer())

    with pytest.raises(_CallDescriptorFailure) as caught:
        lines[0] = value

    assert caught.value is failure
    assert trace == ["call-lookup"]


def test_lineiterator_lines_pseudo_factory_uses_legacy_empty_lines_fallback():
    trace = []
    pseudo_factory = _PseudoCallIterable(trace)

    class ProbeIndicator(bt.Indicator):
        lines = ("value",)

    original_lines = ProbeIndicator.lines
    ProbeIndicator.lines = pseudo_factory
    try:
        instance = LineIterator.__new__(ProbeIndicator)
    finally:
        ProbeIndicator.lines = original_lines

    assert isinstance(instance.lines, Lines)
    assert len(instance.lines) == 0
    # The first lookup is hasattr(..., "__call__"); call syntax performs its
    # own special-method lookup and fails, after which the constructor falls
    # back to an empty Lines instance.
    assert trace == ["call-lookup", "call-lookup"]


def test_lineiterator_lines_descriptor_error_propagates_before_fallback():
    trace = []
    failure = _CallDescriptorFailure("factory descriptor failed")
    pseudo_factory = _PseudoCallIterable(trace, error=failure)

    class ProbeIndicator(bt.Indicator):
        lines = ("value",)

    original_lines = ProbeIndicator.lines
    ProbeIndicator.lines = pseudo_factory
    try:
        with pytest.raises(_CallDescriptorFailure) as caught:
            LineIterator.__new__(ProbeIndicator)
    finally:
        ProbeIndicator.lines = original_lines

    assert caught.value is failure
    assert trace == ["call-lookup"]


def test_strategy_init_pseudo_call_descriptor_preserves_legacy_failure_order():
    trace = []
    pseudo_init = _PseudoCallIterable(trace)

    class ProbeStrategyBase(StrategyBase):
        pass

    instance = LineIterator.__new__(ProbeStrategyBase)
    original_init = ProbeStrategyBase.__dict__.get("__init__")
    ProbeStrategyBase.__init__ = pseudo_init
    try:
        with pytest.raises(TypeError, match="not callable"):
            StrategyBase.__init__(instance)
    finally:
        if original_init is None:
            del ProbeStrategyBase.__init__
        else:
            ProbeStrategyBase.__init__ = original_init

    assert trace == ["call-lookup", "call-lookup"]


def test_strategy_init_call_descriptor_error_propagates_before_invocation():
    trace = []
    failure = _CallDescriptorFailure("strategy __init__ call descriptor failed")
    pseudo_init = _PseudoCallIterable(trace, error=failure)

    class ProbeStrategyBase(StrategyBase):
        pass

    instance = LineIterator.__new__(ProbeStrategyBase)
    original_init = ProbeStrategyBase.__dict__.get("__init__")
    ProbeStrategyBase.__init__ = pseudo_init
    try:
        with pytest.raises(_CallDescriptorFailure) as caught:
            StrategyBase.__init__(instance)
    finally:
        if original_init is None:
            del ProbeStrategyBase.__init__
        else:
            ProbeStrategyBase.__init__ = original_init

    assert caught.value is failure
    assert trace == ["call-lookup"]
