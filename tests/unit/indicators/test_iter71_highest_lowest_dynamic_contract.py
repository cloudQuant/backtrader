import math
import pandas as pd
import pytest
import backtrader as bt
import backtrader.indicators.basicops as ops


def frame(values):
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
        },
        index=pd.date_range("2020-01-01", periods=len(values), freq="min"),
    )


def same(a, b):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
        return a.hex() == b.hex()
    return a == b


@pytest.mark.parametrize("period", [37, 129])
@pytest.mark.parametrize("once", [False, True])
def test_new_finite_nan_ties_full_windows(period, once, monkeypatch):
    values = [-0.0] + [0.0] * 140 + [float((i // 3) % 7 - 3) for i in range(160)]
    values[173] = math.nan
    values[244] = math.nan
    helper = []
    orig = ops._once_monotonic_extreme

    def tracked(*args):
        helper.append(args[-1])
        return orig(*args)

    monkeypatch.setattr(ops, "_once_monotonic_extreme", tracked)

    class P(bt.Strategy):
        def __init__(self):
            self.highest_node = bt.ind.Highest(self.data.close, period=period)
            self.lowest_node = bt.ind.Lowest(self.data.close, period=period)

    c = bt.Cerebro(stdstats=False, preload=True, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=frame(values)))
    c.addstrategy(P)
    s = c.run()[0]
    for i in range(period - 1, len(values)):
        win = values[i - period + 1 : i + 1]
        assert same(s.highest_node.highest.array[i], max(win))
        assert same(s.lowest_node.lowest.array[i], min(win))
    assert bool(helper) == once


@pytest.mark.parametrize("kind", ["highest", "lowest"])
@pytest.mark.parametrize("placement", ["class_before", "class_after", "instance"])
@pytest.mark.parametrize("behavior", ["normal", "mutate", "valueerror", "runtimeerror"])
def test_public_callback_binding_and_window_order(kind, placement, behavior):
    cls = ops.Highest if kind == "highest" else ops.Lowest
    native = max if kind == "highest" else min
    original_func = vars(cls)["func"]
    original_cutoff = ops._MIN_PERIOD_FOR_MONOTONIC_ONCE
    original_helper = ops._once_monotonic_extreme

    def trial(force_generic):
        seen = []
        holder = []
        fast = []
        values = [float((i * 3) % 17 - 8) for i in range(90)]

        def callback(window):
            seen.append(tuple(window))
            if behavior == "mutate" and len(seen) == 1:
                holder[0].data.array[70] = 999.0
            if behavior == "valueerror" and len(seen) == 2:
                raise ValueError("test callback")
            if behavior == "runtimeerror" and len(seen) == 2:
                raise RuntimeError("test callback")
            return native(window) + 3.0

        def observe(*args):
            fast.append(True)
            return original_helper(*args)

        class P(bt.Strategy):
            def __init__(self):
                self.i = cls(self.data.close, period=37)
                holder.append(self.i)
                if placement == "class_after":
                    cls.func = staticmethod(callback)
                if placement == "instance":
                    self.i.func = callback

        try:
            if placement == "class_before":
                cls.func = staticmethod(callback)
            ops._MIN_PERIOD_FOR_MONOTONIC_ONCE = 10**9 if force_generic else original_cutoff
            ops._once_monotonic_extreme = observe
            c = bt.Cerebro(stdstats=False, preload=True, runonce=True)
            c.adddata(bt.feeds.PandasData(dataname=frame(values)))
            c.addstrategy(P)
            try:
                out = ("ok", list(c.run()[0].i.lines[0].array))
            except Exception as ex:
                out = ("error", type(ex).__name__, str(ex))
            return out, seen, fast
        finally:
            cls.func = original_func
            ops._MIN_PERIOD_FOR_MONOTONIC_ONCE = original_cutoff
            ops._once_monotonic_extreme = original_helper

    expected = trial(True)
    actual = trial(False)
    assert not actual[2]
    assert same(actual, expected)
    assert len(actual[1]) >= 2
    if behavior == "mutate":
        assert any(999.0 in window for window in actual[1][1:])
    if behavior == "valueerror":
        assert actual[0][0] == "ok" and math.isnan(actual[0][1][37])
    if behavior == "normal":
        assert len(actual[1]) == 54
        initial = [float((i * 3) % 17 - 8) for i in range(90)]
        assert actual[1] == [tuple(initial[i - 36 : i + 1]) for i in range(36, 90)]
