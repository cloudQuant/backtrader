"""SumN must not treat a dynamically replaced fsum as the native operation."""

import math
import subprocess
import sys

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators.basicops as ops


def frame():
    values = [float(i % 11 - 5) for i in range(70)]
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * 70,
        },
        index=pd.date_range("2024-01-01", periods=70, freq="min"),
    )


def run_callback_case(action, force_generic, after_construction=False):
    original_fsum = math.fsum
    original_func = vars(ops.SumN)["func"]
    original_threshold = ops._MIN_PERIOD_FOR_SUM_ONCE
    observed = []
    holder = []

    def custom(window):
        values = tuple(window)
        if len(values) == 32:
            observed.append(values)
            if action == "mutate" and len(observed) == 1:
                holder[0].data.array[40] = 500.0
            if action == "valueerror" and len(observed) == 2:
                raise ValueError("deliberate fsum failure")
            if action == "runtimeerror" and len(observed) == 2:
                raise RuntimeError("deliberate callback failure")
        return original_fsum(values) + 37.0

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ops.SumN(self.data.close, period=32)
            holder.append(self.ind)
            if after_construction:
                math.fsum = custom
                ops.SumN.func = staticmethod(custom)

    try:
        if not after_construction:
            math.fsum = custom
            ops.SumN.func = staticmethod(custom)
        if force_generic:
            ops._MIN_PERIOD_FOR_SUM_ONCE = 10**9
        engine = bt.Cerebro(stdstats=False, runonce=True)
        engine.adddata(bt.feeds.PandasData(dataname=frame()))
        engine.addstrategy(Probe)
        try:
            indicator = engine.run()[0].ind
        except Exception as exc:  # noqa: BLE001 - compare observable fallback behavior
            return ("error", type(exc).__name__, str(exc), observed)
        return ("ok", list(indicator.sumn.array), observed)
    finally:
        math.fsum = original_fsum
        ops.SumN.func = original_func
        ops._MIN_PERIOD_FOR_SUM_ONCE = original_threshold


def same(a, b):
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if (
        isinstance(a, float)
        and isinstance(b, float)
        and math.isnan(a)
        and math.isnan(b)
    ):
        return True
    return a == b


@pytest.mark.parametrize("action", ["return", "mutate", "valueerror", "runtimeerror"])
@pytest.mark.parametrize("after_construction", [False, True])
def test_dynamic_fsum_and_concrete_class_func_use_generic_order(action, after_construction):
    expected = run_callback_case(action, True, after_construction)
    actual = run_callback_case(action, False, after_construction)
    assert same(actual, expected)
    assert len(actual[-1]) >= 2


def test_unmodified_native_fsum_keeps_fast_path_and_matches_formula(monkeypatch):
    calls = []
    original = ops._once_exact_sum

    def tracked(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(ops, "_once_exact_sum", tracked)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ops.SumN(self.data.close, period=32)

    engine = bt.Cerebro(stdstats=False, runonce=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame()))
    engine.addstrategy(Probe)
    result = list(engine.run()[0].ind.sumn.array)
    assert calls
    values = list(frame().close)
    for i in range(31, len(values)):
        assert result[i].hex() == math.fsum(values[i - 31 : i + 1]).hex()


def test_preimport_fsum_replacement_does_not_qualify_as_native():
    program = r"""
import math
import pandas as pd
math.fsum=math.prod
import backtrader as bt
import backtrader.indicators.basicops as ops
calls=[]
original_fast=ops._once_exact_sum
def tracked(*args):
 calls.append(1)
 return original_fast(*args)
ops._once_exact_sum=tracked
values=[float(i%3+1) for i in range(70)]
frame=pd.DataFrame({'open':values,'high':values,'low':values,'close':values,'volume':[1.0]*70},index=pd.date_range('2024-01-01',periods=70,freq='min'))
class Probe(bt.Strategy):
 def __init__(self):self.ind=bt.ind.SumN(self.data.close,period=32)
e=bt.Cerebro(stdstats=False,runonce=True);e.adddata(bt.feeds.PandasData(dataname=frame));e.addstrategy(Probe)
s=e.run()[0]
assert calls==[],calls
for i in range(31,70):assert s.ind.sumn.array[i]==math.prod(values[i-31:i+1])
"""
    subprocess.run([sys.executable, "-c", program], check=True)



@pytest.mark.parametrize("replacement", ["fsum", "class_func", "instance_func"])
def test_individual_pre_run_binding_changes_use_generic_path(monkeypatch, replacement):
    native = math.fsum
    windows = []
    fast_calls = []

    def custom(window):
        windows.append(tuple(window))
        return native(window) + 7.0

    original_fast = ops._once_exact_sum

    def tracked(*args):
        fast_calls.append(True)
        return original_fast(*args)

    monkeypatch.setattr(ops, "_once_exact_sum", tracked)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ops.SumN(self.data.close, period=32)
            if replacement == "fsum":
                monkeypatch.setattr(math, "fsum", custom)
            elif replacement == "class_func":
                monkeypatch.setattr(ops.SumN, "func", staticmethod(custom))
            else:
                self.ind.func = custom

    engine = bt.Cerebro(stdstats=False, runonce=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame()))
    engine.addstrategy(Probe)
    result = engine.run()[0].ind.sumn.array
    assert not fast_calls
    expected = [native(frame().close.iloc[i - 31 : i + 1]) for i in range(31, 70)]
    if replacement != "fsum":
        expected = [value + 7.0 for value in expected]
        assert len(windows) == 39
    assert list(result[31:]) == expected
