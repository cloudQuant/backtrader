"""Extrema operations preserve the original in-place window order."""

import random
from array import array

import backtrader as bt
import backtrader.indicators.basicops as basicops
import pytest

from test_iter71_numeric_acceptance_regressions import _indicator


CASES = (
    (bt.ind.Highest, max, None, 0),
    (bt.ind.Lowest, min, None, 0),
    (bt.ind.FindFirstIndexHighest, max, "first", 0),
    (bt.ind.FindFirstIndexLowest, min, "first", 0),
    (bt.ind.FindLastIndexHighest, max, "last", 0),
    (bt.ind.FindLastIndexLowest, min, "last", 1),
)


@pytest.mark.parametrize("typecode", ["d", "f"])
@pytest.mark.parametrize("indicator_type,chooser,position,seed", CASES)
def test_same_source_and_destination_match_in_place_window_order(
    indicator_type, chooser, position, seed, typecode
):
    randomizer = random.Random(seed)
    values = [float(randomizer.randint(-10, 10)) for _ in range(100)]
    expected = array(typecode, values)
    for index in range(63, 90):
        window = expected[index - 31 : index + 1]
        extreme = chooser(window)
        if position == "first":
            value = next(i for i, item in enumerate(reversed(window)) if item == extreme)
        elif position == "last":
            value = 31 - next(i for i, item in enumerate(window) if item == extreme)
        else:
            value = extreme
        expected[index] = value

    indicator = _indicator(indicator_type, 32, 100)
    source = array(typecode, values)
    indicator.data.array = source
    indicator.lines[0].array = source
    indicator.once(63, 90)
    assert list(source) == list(expected)


@pytest.mark.parametrize("indicator_type,chooser,position,seed", CASES)
def test_separate_standard_arrays_keep_deque_path(monkeypatch, indicator_type, chooser, position, seed):
    indicator = _indicator(indicator_type, 32, 100)
    helper_name = "_once_monotonic_extreme" if position is None else "_once_monotonic_index"
    original = getattr(basicops, helper_name)
    calls = []

    def observe(*args):
        calls.append(None)
        return original(*args)

    monkeypatch.setattr(basicops, helper_name, observe)
    indicator.once(63, 90)
    assert len(calls) == 1
