"""Long-window finite checks retain ordered float and missing-data semantics."""

import math
import backtrader as bt
import pandas as pd
import pytest
import backtrader.indicators.contrib.digital_macd as module


@pytest.mark.parametrize("period", [5, 128, 257])
@pytest.mark.parametrize("gap", [False, True])
@pytest.mark.parametrize("segmented", [False, True])
@pytest.mark.parametrize("custom_coeffs", [False, True])
def test_compensated_once_matches_independent_ordered_windows(
    monkeypatch, period, gap, segmented, custom_coeffs
):
    # Execute the compensated branch on both supported interpreters; sum itself
    # remains the interpreter's real implementation.
    monkeypatch.setattr(module, "_FLOAT_SUM_COMPENSATED", True)

    class Segmented(bt.ind.DigitalMacd):
        def once(self, start, end):
            while start < end:
                stop = min(start + 31, end)
                super().once(start, stop)
                start = stop

    kind = Segmented if segmented else bt.ind.DigitalMacd
    values = [100 + i * 0.013 + math.sin(i / 9) for i in range(650)]
    if gap:
        for i in (140, 141, 390):
            values[i] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.d = kind(self.data, signal_period=period)
            if custom_coeffs:
                self.d._fast_coeffs = (0.75, -0.25, 0.13)
                self.d._slow_coeffs = (0.1, 0.9, -0.3, 0.02)

    frame = pd.DataFrame(
        {k: values for k in ("open", "high", "low", "close")},
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )
    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Probe)
    ind = c.run()[0].d
    fast = ind._fast_coeffs
    slow = ind._slow_coeffs
    width = ind._max_lookback
    reference = []
    for i in range(len(values)):
        if i + 1 < width:
            reference.append(math.nan)
            continue
        a = b = 0.0
        for j, v in enumerate(fast):
            a += v * values[i - j]
        for j, v in enumerate(slow):
            b += v * values[i - j]
        m = (a - b) / 0.01
        reference.append(m if math.isfinite(m) else math.nan)
    signal = []
    for i in range(len(values)):
        window = reference[i - period + 1 : i + 1]
        signal.append(
            sum(window) / period
            if len(window) == period and all(math.isfinite(v) for v in window)
            else math.nan
        )
    for actual, expected in ((ind.macd.array, reference), (ind.signal.array, signal)):
        for got, want in zip(actual, expected):
            if math.isnan(want):
                assert math.isnan(got)
            else:
                assert got.hex() == want.hex()


def test_numpy_proxy_need_not_expose_ufunc(monkeypatch):
    np = module._np
    if np is None:
        pytest.skip("NumPy is unavailable")

    class Proxy:
        def __getattr__(self, name):
            if name == "ufunc":
                raise AttributeError(name)
            return getattr(np, name)

    values = [100 + math.sin(i / 11) for i in range(420)]
    frame = pd.DataFrame(
        {k: values for k in ("open", "high", "low", "close")},
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.d = bt.ind.DigitalMacd(self.data, signal_period=128)

    def run():
        c = bt.Cerebro(stdstats=False, runonce=True)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        return c.run()[0].d.signal.array.tobytes()

    monkeypatch.setattr(module, "_FLOAT_SUM_COMPENSATED", True)
    expected = run()
    monkeypatch.setattr(module, "_np", Proxy())
    assert run() == expected


def test_math_proxy_retains_isfinite_read_sequence(monkeypatch):
    original_math = module.math
    seen = []

    class MathProxy:
        def __getattr__(self, name):
            if name == "isfinite":
                seen.append(name)
            return getattr(original_math, name)

    values = [100 + i * 0.01 for i in range(340)]
    frame = pd.DataFrame(
        {k: values for k in ("open", "high", "low", "close")},
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.d = bt.ind.DigitalMacd(self.data, signal_period=128)

    def run():
        c = bt.Cerebro(stdstats=False, runonce=True)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        return c.run()[0].d.signal.array.tobytes()

    monkeypatch.setattr(module, "_FLOAT_SUM_COMPENSATED", True)
    expected = run()
    monkeypatch.setattr(module, "math", MathProxy())
    assert run() == expected
    assert len(seen) == 19221


def test_numpy_module_getter_keeps_original_read_count(monkeypatch):
    from types import ModuleType

    np = module._np
    if np is None:
        pytest.skip("NumPy is unavailable")
    seen = []

    class Spy(ModuleType):
        def __getattribute__(self, name):
            if name == "isfinite":
                seen.append(name)
            return super().__getattribute__(name)

    values = [100 + i * 0.01 for i in range(340)]
    frame = pd.DataFrame(
        {k: values for k in ("open", "high", "low", "close")},
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.d = bt.ind.DigitalMacd(self.data, signal_period=128)

    def run():
        c = bt.Cerebro(stdstats=False, runonce=True)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        return c.run()[0].d.signal.array.tobytes()

    monkeypatch.setattr(module, "_FLOAT_SUM_COMPENSATED", True)
    expected = run()
    previous = np.__class__
    try:
        np.__class__ = Spy
        assert run() == expected
    finally:
        np.__class__ = previous
    assert len(seen) == 3


def test_missing_math_binding_retains_getattr_sequence(monkeypatch):
    values = [100 + i * 0.01 for i in range(340)]
    frame = pd.DataFrame(
        {k: values for k in ("open", "high", "low", "close")},
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.d = bt.ind.DigitalMacd(self.data, signal_period=128)

    def run():
        c = bt.Cerebro(stdstats=False, runonce=True)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        return c.run()[0].d.signal.array.tobytes()

    monkeypatch.setattr(module, "_FLOAT_SUM_COMPENSATED", True)
    expected = run()
    saved = math.isfinite
    reads = []

    def lookup(name):
        if name == "isfinite":
            reads.append(name)
            return saved
        raise AttributeError(name)

    monkeypatch.delattr(math, "isfinite")
    monkeypatch.setattr(math, "__getattr__", lookup, raising=False)
    assert run() == expected
    assert len(reads) == 19221
