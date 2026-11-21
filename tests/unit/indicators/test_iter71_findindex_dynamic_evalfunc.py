"""Index finder must evaluate dynamic _evalfunc on each original window."""

import math

import backtrader as bt
import backtrader.indicators.basicops as basicops
import pytest

from test_iter71_numeric_acceptance_regressions import _indicator


CASES = (
    (bt.ind.FindFirstIndexHighest, max, min, True),
    (bt.ind.FindFirstIndexLowest, min, max, True),
    (bt.ind.FindLastIndexHighest, max, min, False),
    (bt.ind.FindLastIndexLowest, min, max, False),
)


@pytest.mark.parametrize("indicator_type,initial,later,first", CASES)
@pytest.mark.parametrize("behavior", ["switch", "value_error", "runtime_error"])
def test_dynamic_evalfunc_keeps_per_window_access_and_errors(
    monkeypatch, indicator_type, initial, later, first, behavior
):
    indicator = _indicator(indicator_type, 32, 100)
    source = indicator.data.array
    fallback_calls = []

    class Parameters:
        def __init__(self, original):
            self.original = original
            self.reads = 0

        def __getattr__(self, name):
            return getattr(self.original, name)

        @property
        def _evalfunc(self):
            self.reads += 1
            if behavior == "value_error":
                raise ValueError("window rejected")
            if behavior == "runtime_error":
                raise RuntimeError("window failed")
            return initial if self.reads == 1 else later

    params = Parameters(indicator.p)
    indicator.p = params

    def fallback(_self, start, end):
        fallback_calls.append((start, end))

    monkeypatch.setattr(bt.Indicator, "once_via_next", fallback)
    indicator.once(63, 70)
    if behavior == "runtime_error":
        assert params.reads == 1
        assert fallback_calls == [(63, 70)]
        return
    assert params.reads == 7
    assert fallback_calls == []
    actual = indicator.lines[0].array[63:70]
    if behavior == "value_error":
        assert all(math.isnan(value) for value in actual)
        return

    expected = []
    for index in range(63, 70):
        window = source[index - 31 : index + 1]
        extreme = (initial if index == 63 else later)(window)
        if first:
            result = next(i for i, value in enumerate(reversed(window)) if value == extreme)
        else:
            result = 31 - next(i for i, value in enumerate(window) if value == extreme)
        expected.append(float(result))
    assert list(actual) == expected


@pytest.mark.parametrize("indicator_type,initial,later,first", CASES)
def test_plain_parameters_retain_the_deque_path(monkeypatch, indicator_type, initial, later, first):
    indicator = _indicator(indicator_type, 32, 100)
    original = basicops._once_monotonic_index
    calls = []

    def observe(*args):
        calls.append(None)
        return original(*args)

    monkeypatch.setattr(basicops, "_once_monotonic_index", observe)
    indicator.once(63, 70)
    assert calls == [None]


def test_accessor_class_descriptor_is_not_invoked_by_fast_path_check(monkeypatch):
    from backtrader.parameters import ParameterAccessor

    indicator = _indicator(bt.ind.FindFirstIndexHighest, 32, 100)
    reads = []

    def chooser(_params):
        reads.append(None)
        return max if len(reads) == 1 else min

    monkeypatch.setattr(ParameterAccessor, "_evalfunc", property(chooser), raising=False)
    indicator.once(63, 70)
    assert len(reads) == 7
    assert list(indicator.lines[0].array[63:70]) == [13.0, 27.0, 28.0, 29.0, 30.0, 31.0, 8.0]


def test_accessor_instance_dict_collision_does_not_add_key_comparisons():
    indicator = _indicator(bt.ind.FindFirstIndexHighest, 32, 100)
    params = indicator.p
    state = object.__getattribute__(params, "__dict__")
    original = state.copy()
    comparisons = []

    class Collision:
        def __hash__(self):
            return hash("_evalfunc")

        def __eq__(self, other):
            comparisons.append(other)
            return False

    state.clear()
    state[Collision()] = None
    state.update(original)
    comparisons.clear()
    indicator.once(63, 70)
    # Each original window reads _evalfunc once; the guard must add none.
    assert len(comparisons) == 7


def test_indicator_instance_dict_collision_does_not_add_key_comparisons():
    indicator = _indicator(bt.ind.FindFirstIndexHighest, 32, 100)
    state = object.__getattribute__(indicator, "__dict__")
    original = state.copy()
    comparisons = []

    class Collision:
        def __hash__(self):
            return hash("_params_instance")

        def __eq__(self, other):
            comparisons.append(other)
            return False

    state.clear()
    state[Collision()] = None
    state.update(original)
    comparisons.clear()
    indicator.once(63, 70)
    # One read for period and one for each window's _evalfunc.
    assert len(comparisons) == 8


@pytest.mark.parametrize("indicator_type,initial,later,first", CASES)
def test_empty_range_does_not_read_evalfunc(
    monkeypatch, indicator_type, initial, later, first
):
    indicator = _indicator(indicator_type, 32, 100)
    calls = []

    class Parameters:
        def __init__(self, original):
            self.original = original

        def __getattr__(self, name):
            return getattr(self.original, name)

        @property
        def _evalfunc(self):
            raise AssertionError("empty range must not read _evalfunc")

    indicator.p = Parameters(indicator.p)

    def fallback(_self, start, end):
        calls.append((start, end))

    monkeypatch.setattr(bt.Indicator, "once_via_next", fallback)
    indicator.once(63, 63)
    assert calls == []
