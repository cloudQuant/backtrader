"""SMA keeps the fsum binding captured at the start of once()."""

import math
from pathlib import Path
import subprocess
import sys

import backtrader as bt
import backtrader.indicators.sma as sma
import pytest

from .test_iter71_numeric_acceptance_regressions import _indicator


@pytest.mark.parametrize("behavior", ["return", "raise", "rebind"])
def test_replaced_fsum_keeps_window_calls_and_fallback(monkeypatch, behavior):
    indicator = _indicator(bt.ind.SMA, 32, 100)
    destination = indicator.lines[0].array
    for index in range(31, 36):
        destination[index] = -12345.0
    calls = []
    later_calls = []
    fallback_calls = []

    def later(window):
        later_calls.append(len(window))
        return 1000.0

    def custom(window):
        calls.append(len(window))
        if behavior == "raise" and len(calls) == 3:
            raise ValueError("third window")
        if behavior == "rebind" and len(calls) == 1:
            monkeypatch.setattr(math, "fsum", later)
        return 42.0

    def fallback(_indicator, start, end):
        fallback_calls.append((start, end))

    monkeypatch.setattr(math, "fsum", custom)
    monkeypatch.setattr(bt.Indicator, "once_via_next", fallback)
    indicator.once(31, 36)
    if behavior == "raise":
        assert calls == [32] * 3
        assert fallback_calls == [(31, 36)]
        assert list(destination[31:36]) == [42.0 / 32] * 2 + [-12345.0] * 3
    else:
        assert calls == [32] * 5
        assert fallback_calls == []
        assert list(destination[31:36]) == [42.0 / 32] * 5
    assert later_calls == []


def test_optimized_once_keeps_original_fsum_when_rebound_after_selection(monkeypatch):
    indicator = _indicator(bt.ind.SMA, 32, 100)
    source = indicator.data.array
    for index in range(len(source)):
        source[index] = 1.0
    source[0] = 1e16
    expected = [math.fsum(source[i - 31 : i + 1]) / 32 for i in range(31, 36)]
    original = sma._once_exact_sma
    fake_calls = []

    def fake(window):
        fake_calls.append(len(window))
        return 1000.0

    def observe(*args):
        monkeypatch.setattr(math, "fsum", fake)
        return original(*args)

    monkeypatch.setattr(sma, "_once_exact_sma", observe)
    indicator.once(31, 36)
    assert fake_calls == []
    assert list(indicator.lines[0].array[31:36]) == expected


def test_fsum_replaced_before_sma_import_uses_window_path():
    root = str(Path(__file__).resolve().parents[3])
    code = """
import math
import sys
sys.path.insert(0, sys.argv[1])
calls = []
def custom(window):
    calls.append(len(window))
    return 42.0
math.fsum = custom
import backtrader as bt
from tests.unit.indicators.test_iter71_numeric_acceptance_regressions import _indicator
indicator = _indicator(bt.ind.SMA, 32, 100)
calls.clear()
indicator.once(31, 36)
assert calls == [32] * 5, calls
assert list(indicator.lines[0].array[31:36]) == [42.0 / 32] * 5
"""
    subprocess.run([sys.executable, "-c", code, root], check=True, capture_output=True, text=True)
