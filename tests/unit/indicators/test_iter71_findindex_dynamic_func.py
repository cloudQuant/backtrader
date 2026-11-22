"""Runonce must honor runtime replacement of the index finder function."""

import math

import backtrader as bt
import backtrader.indicators.basicops as basicops
import pytest

try:
    from tests.unit.indicators.test_iter71_numeric_acceptance_regressions import _indicator
except ImportError:
    from test_iter71_numeric_acceptance_regressions import _indicator


@pytest.mark.parametrize(
    "indicator_type,base",
    [
        (bt.ind.FindFirstIndexHighest, basicops.FindFirstIndex),
        (bt.ind.FindFirstIndexLowest, basicops.FindFirstIndex),
        (bt.ind.FindLastIndexHighest, basicops.FindLastIndex),
        (bt.ind.FindLastIndexLowest, basicops.FindLastIndex),
    ],
)
@pytest.mark.parametrize("behavior", ["return", "value_error", "runtime_error"])
def test_late_base_func_replacement_retains_window_and_fallback_semantics(
    monkeypatch, indicator_type, base, behavior
):
    indicator = _indicator(indicator_type, 32, 100)
    calls = []
    fallback_calls = []

    def custom(_self, window):
        calls.append(len(window))
        if behavior == "value_error":
            raise ValueError("window rejected")
        if behavior == "runtime_error":
            raise RuntimeError("window failed")
        return 7

    def fallback(_self, start, end):
        fallback_calls.append((start, end))

    monkeypatch.setattr(base, "func", custom)
    monkeypatch.setattr(bt.Indicator, "once_via_next", fallback)
    indicator.once(63, 70)

    if behavior == "runtime_error":
        assert calls == [32]
        assert fallback_calls == [(63, 70)]
    else:
        assert calls == [32] * 7
        assert fallback_calls == []
        result = indicator.lines[0].array[63:70]
        if behavior == "return":
            assert list(result) == [7.0] * 7
        else:
            assert all(math.isnan(value) for value in result)
