"""R71-100 strict-factor context lookup compatibility and failure guards."""

from __future__ import annotations

from contextvars import copy_context
from threading import Thread
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader import linebuffer
from backtrader.errors import FactorComputationError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec
from backtrader.research.strict import computation_scope
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.unit.test_factor_research_representatives import (
    _frames,
    _research_feed,
    _research_spec,
)


class _NativeExpressionFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    required_fields = formula_fields
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.expression = self.data.close * 2.0

    def next(self):
        self.outputs[self.datas[0]].factor[0] = self.expression[0]


class _OverflowExpressionFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    required_fields = formula_fields
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.expression = self.data.close * 1.0e308

    def next(self):
        self.outputs[self.datas[0]].factor[0] = self.expression[0]


class _LateAddedChild(bt.Indicator):
    lines = ("value",)

    def next(self):
        self.lines.value[0] = self.data.close[0]


def _build_factor_run(*, runonce, factor_class=_NativeExpressionFactor, overflow=False):
    frames = _frames(periods=8)
    frame = frames["asset-0"].copy()
    if overflow:
        frame.loc[:, "close"] = 2.0
    frames = {"asset-0": frame}
    research = _research_spec(frames)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    factor = FactorSpec(
        name="test_factor",
        indicator=factor_class,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    return cerebro, frame


def test_direct_context_hit_precedes_owner_and_contextvar_fallback(monkeypatch):
    context = object()

    class DirectContextLine:
        def __init__(self):
            self._factor_strict_context = context
            self.owner_reads = 0

        @property
        def _owner(self):
            self.owner_reads += 1
            raise AssertionError("direct context hit must not inspect its owner")

    class ForbiddenContextVarRead:
        @staticmethod
        def get():
            raise AssertionError("direct context hit must not use the ambient fallback")

    line = DirectContextLine()
    monkeypatch.setattr(linebuffer, "_ACTIVE_FACTOR_CONTEXT", ForbiddenContextVarRead())

    assert linebuffer._factor_context_for_line(line) is context
    assert line.owner_reads == 0


def test_direct_context_property_is_read_again_without_caching():
    first_context = object()
    second_context = object()
    contexts = iter((first_context, second_context))

    class DynamicContextLine:
        @property
        def _factor_strict_context(self):
            return next(contexts)

    line = DynamicContextLine()

    assert linebuffer._factor_context_for_line(line) is first_context
    assert linebuffer._factor_context_for_line(line) is second_context


def test_owner_ref_fallback_keeps_late_attached_context_precedence():
    owner_context = object()
    ambient_context = object()
    factor_owner = SimpleNamespace(_factor_strict_context=owner_context)
    lines_owner = SimpleNamespace(_owner_ref=factor_owner)
    line = SimpleNamespace(_factor_strict_context=None, _owner=lines_owner)

    token = linebuffer._ACTIVE_FACTOR_CONTEXT.set(ambient_context)
    try:
        assert linebuffer._factor_context_for_line(line) is owner_context
    finally:
        linebuffer._ACTIVE_FACTOR_CONTEXT.reset(token)


def test_owner_ref_context_precedes_conflicting_intermediary_owner_context():
    owner_ref_context = object()
    intermediary_context = object()
    owner_ref = SimpleNamespace(_factor_strict_context=owner_ref_context)
    intermediary_owner = SimpleNamespace(
        _factor_strict_context=intermediary_context,
        _owner_ref=owner_ref,
    )
    line = SimpleNamespace(_factor_strict_context=None, _owner=intermediary_owner)

    assert linebuffer._factor_context_for_line(line) is owner_ref_context


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_real_factor_expression_and_shared_feed_context_fallback(runonce):
    cerebro, frame = _build_factor_run(runonce=runonce)
    strategy = cerebro.run(preload=True)[0]
    factor = strategy.factor_instances["test_factor"]
    context = factor._factor_strict_context
    feed_line = factor.datas[0].close

    assert factor.expression._factor_strict_context is context
    assert linebuffer._factor_context_for_line(factor.expression) is context
    assert getattr(feed_line, "_factor_strict_context", None) is not context
    assert linebuffer._factor_context_for_line(feed_line) is None

    with computation_scope(context, "next"):
        assert linebuffer._factor_context_for_line(feed_line) is context

    assert linebuffer._factor_context_for_line(feed_line) is None
    observed = strategy.get_panel().factors["test_factor"].to_numpy(dtype="float64")
    assert observed == pytest.approx(frame["close"].to_numpy(dtype="float64") * 2.0)
    assert context.failed is False


def test_thread_context_is_explicit_but_object_and_owner_contexts_remain_visible():
    cerebro, _frame = _build_factor_run(runonce=False)
    strategy = cerebro.run(preload=True)[0]
    factor = strategy.factor_instances["test_factor"]
    context = factor._factor_strict_context
    feed_line = factor.datas[0].close
    late_expression = feed_line * 3.0
    late_expression._owner = factor
    assert getattr(late_expression, "_factor_strict_context", None) is None
    assert linebuffer._factor_context_for_line(late_expression) is context

    late_child = _LateAddedChild(factor.datas[0])
    assert getattr(late_child, "_factor_strict_context", None) is None
    factor.addindicator(late_child)
    assert late_child._factor_strict_context is context
    assert late_child.lines._factor_strict_context is context
    assert late_child.lines[0]._factor_strict_context is context

    observed = {}
    token = linebuffer._ACTIVE_FACTOR_CONTEXT.set(context)
    try:
        thread = Thread(
            target=lambda: observed.update(
                ambient=linebuffer._ACTIVE_FACTOR_CONTEXT.get(),
                shared_feed=linebuffer._factor_context_for_line(feed_line),
                attached_expression=linebuffer._factor_context_for_line(factor.expression),
                late_owner_expression=linebuffer._factor_context_for_line(late_expression),
            )
        )
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()

        copied = copy_context()
        copied_thread = Thread(
            target=lambda: copied.run(
                lambda: observed.update(
                    copied_ambient=linebuffer._ACTIVE_FACTOR_CONTEXT.get(),
                    copied_shared_feed=linebuffer._factor_context_for_line(feed_line),
                )
            )
        )
        copied_thread.start()
        copied_thread.join(timeout=5)
        assert not copied_thread.is_alive()
    finally:
        linebuffer._ACTIVE_FACTOR_CONTEXT.reset(token)

    assert observed["ambient"] is None
    assert observed["shared_feed"] is None
    assert observed["attached_expression"] is context
    assert observed["late_owner_expression"] is context
    assert observed["copied_ambient"] is context
    assert observed["copied_shared_feed"] is context


@pytest.mark.parametrize(
    ("runonce", "expected_phase"),
    ((False, "next"), (True, "once")),
    ids=("runnext-overflow", "runonce-overflow"),
)
def test_real_factor_expression_infinity_still_fails_closed(runonce, expected_phase):
    cerebro, _frame = _build_factor_run(
        runonce=runonce,
        factor_class=_OverflowExpressionFactor,
        overflow=True,
    )

    with pytest.raises(FactorComputationError) as caught:
        cerebro.run(preload=True)

    error = caught.value
    assert error.code == "FACTOR_COMPUTATION_FAILED"
    assert error.factor == "test_factor"
    assert error.phase == expected_phase
    assert isinstance(error.__cause__, ArithmeticError)
    assert "infinity" in str(error.__cause__).lower()
